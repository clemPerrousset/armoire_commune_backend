"""
Crée des comptes utilisateurs à partir des mails d'inscription Yapla reçus
sur la boîte contact@larmoirecommune.fr.

Pour chaque mail d'inscription trouvé dans INBOX :
  1. extrait l'adresse email de la personne inscrite (+ nom / prénom si présents),
  2. appelle POST /auth/signup avec le mot de passe initial "123456",
  3. déplace le mail dans le dossier "mail inscription traités"
     (le script ne lit que INBOX, il ne le retraitera donc jamais).

Variables d'environnement :
  MAIL_USER        adresse de la boîte (ex: contact@larmoirecommune.fr)
  MAIL_PASS        mot de passe d'APPLICATION Google (pas le mot de passe normal)
  MAIL_IMAP_HOST   défaut: imap.gmail.com
  API_URL          défaut: http://localhost:8000
  SOURCE_FOLDER    défaut: "Numérique/Adhésion" (libellé Gmail où Yapla range les adhésions)
  SUBJECT_PATTERN  regex du sujet des mails d'adhésion, défaut: InfosAdhesionApp
  SENDER_PATTERN   regex optionnelle sur l'expéditeur (ex: "yapla")
  PROCESSED_FOLDER défaut: "mail inscription traités"

Usage :
  python scripts/inscriptions_mail.py --dry-run     # n'écrit rien, affiche ce qui serait fait
  python scripts/inscriptions_mail.py               # exécute vraiment
"""
import argparse
import base64
import email
import html
import imaplib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from email.header import decode_header, make_header

DEFAULT_PASSWORD = "123456"
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Adresses qui ne sont jamais celle de la personne inscrite.
IGNORED_EMAIL_RE = re.compile(r"(larmoirecommune\.fr|yapla\.|no-?reply|noreply)", re.I)


def imap_utf7(name):
    """Encode un nom de dossier en UTF-7 modifié (RFC 3501) pour les accents."""
    out, buf = [], []

    def flush():
        if buf:
            raw = "".join(buf).encode("utf-16-be")
            out.append("&" + base64.b64encode(raw).decode().rstrip("=").replace("/", ",") + "-")
            buf.clear()

    for ch in name:
        if 0x20 <= ord(ch) <= 0x7E:
            flush()
            out.append("&-" if ch == "&" else ch)
        else:
            buf.append(ch)
    flush()
    return "".join(out)


def decode(value):
    return str(make_header(decode_header(value or "")))


def body_text(msg):
    parts = []
    for part in msg.walk():
        if part.get_content_maintype() != "text":
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if part.get_content_subtype() == "html":
            text = re.sub(r"<[^>]+>", "\n", text)
            text = html.unescape(text).replace("\xa0", " ")
        elif "link.yapla.com" in text:
            continue  # partie texte de repli ("cliquez sur le lien"), sans information
        parts.append(text)
    return "\n".join(parts)


def field(text, *labels):
    for label in labels:
        m = re.search(rf"{label}\s*:\s*([^\n\r<]+)", text, re.I)
        if m:
            return m.group(1).strip()
    return None


def parse_signup(msg):
    """Retourne (email, prenom, nom) ou None si aucune adresse exploitable."""
    # Format Yapla (sujet InfosAdhesionApp), une valeur par ligne :
    #   Nouvelle adhésion validée : / Prénom / Nom / email / date de fin / montant
    lines = [l.strip() for l in body_text(msg).splitlines() if l.strip()]
    for idx, line in enumerate(lines):
        found = EMAIL_RE.fullmatch(line)
        if found and not IGNORED_EMAIL_RE.search(line) and idx >= 2:
            return line.lower(), lines[idx - 2], lines[idx - 1]
    return None


def signup(api_url, address, prenom, nom):
    body = json.dumps({"email": address, "prenom": prenom, "nom": nom, "password": DEFAULT_PASSWORD}).encode()
    req = urllib.request.Request(
        f"{api_url.rstrip('/')}/auth/signup", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=20):
            return "created"
    except urllib.error.HTTPError as e:
        if e.code == 400 and b"already registered" in e.read():
            return "exists"
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    user, password = os.environ.get("MAIL_USER"), os.environ.get("MAIL_PASS")
    if not user or not password:
        sys.exit("MAIL_USER et MAIL_PASS sont requis")
    host = os.environ.get("MAIL_IMAP_HOST", "imap.gmail.com")
    api_url = os.environ.get("API_URL", "http://localhost:8000")
    subject_re = re.compile(os.environ.get("SUBJECT_PATTERN", r"InfosAdhesionApp"), re.I)
    source = '"' + imap_utf7(os.environ.get("SOURCE_FOLDER", "Numérique/Adhésion")) + '"'
    sender_pattern = os.environ.get("SENDER_PATTERN")
    sender_re = re.compile(sender_pattern, re.I) if sender_pattern else None
    folder = '"' + imap_utf7(os.environ.get("PROCESSED_FOLDER", "mail inscription traités")) + '"'

    imap = imaplib.IMAP4_SSL(host, 993)
    imap.login(user, password)
    if not args.dry_run:
        imap.create(folder)  # sans effet si le dossier existe déjà
    status, _ = imap.select(source)
    if status != "OK":
        sys.exit("Dossier source introuvable (SOURCE_FOLDER)")
    _, data = imap.uid("search", None, "ALL")
    uids = data[0].split()
    print(f"{len(uids)} mail(s) dans le dossier source")

    for uid in uids:
        _, d = imap.uid("fetch", uid, "(BODY.PEEK[])")
        msg = email.message_from_bytes(d[0][1])
        subject, sender = decode(msg["Subject"]), decode(msg["From"])
        if not subject_re.search(subject) or (sender_re and not sender_re.search(sender)):
            continue
        parsed = parse_signup(msg)
        if not parsed:
            print(f"[ignoré] adresse introuvable : {subject!r}")
            continue
        address, prenom, nom = parsed
        if args.dry_run:
            print(f"[dry-run] créerait {address} ({prenom} {nom}) puis déplacerait le mail")
            continue
        try:
            status = signup(api_url, address, prenom, nom)
        except Exception as e:  # le mail reste dans INBOX pour un nouvel essai
            print(f"[erreur] {address} : {e}")
            continue
        print(f"[{status}] {address}")
        imap.uid("copy", uid, folder)
        imap.uid("store", uid, "+FLAGS", r"(\Deleted)")
    if not args.dry_run:
        imap.expunge()
    imap.logout()


if __name__ == "__main__":
    main()
