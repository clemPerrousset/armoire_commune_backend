"""Envoi d'e-mails via SMTP (configuré par variables d'environnement, cf. .env.example)."""
import os
import smtplib
from email.message import EmailMessage
from typing import Optional


class MailNotConfigured(Exception):
    """Les variables SMTP_* ne sont pas renseignées."""


def stats_recipient() -> str:
    return os.getenv("STATS_RECIPIENT", "contact@larmoirecommune.fr")


def send_mail(
    to: str,
    subject: str,
    body: str,
    attachment: Optional[bytes] = None,
    attachment_name: str = "document.pdf",
) -> None:
    host = os.getenv("SMTP_HOST", "").strip()
    sender = os.getenv("SMTP_FROM", "").strip() or os.getenv("SMTP_USER", "").strip()
    if not host or not sender:
        raise MailNotConfigured("SMTP_HOST / SMTP_FROM non renseignés")
    port = int(os.getenv("SMTP_PORT", "587") or 587)
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if attachment is not None:
        msg.add_attachment(attachment, maintype="application", subtype="pdf", filename=attachment_name)

    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
    with server:
        if port != 465:
            server.starttls()
        if user:
            server.login(user, password)
        server.send_message(msg)
