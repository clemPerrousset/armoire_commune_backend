"""Statistiques admin : calcul, PDF, envoi d'e-mail et routes."""
import smtplib
from datetime import datetime

import pytest

import mailer
import pdf_report
from models import ObjetTagLink, Reservation, Tag
from stats_service import compute_stats
from test_reservations import _create_base_data, _login, client

NOW = datetime(2030, 1, 15, 12, 0)


def _res(session, objet, user, lieu, debut, fin, status, semaines=1):
    session.add(Reservation(
        date_debut=debut, date_fin=fin, status=status, nb_semaines=semaines,
        user_id=user.id, objet_id=objet.id, lieu_id=lieu.id,
    ))
    session.commit()


@pytest.fixture
def jeu(session):
    """Un petit historique autour de NOW (2030-01-15)."""
    admin, user, lieu, objet = _create_base_data(session)
    tag = Tag(nom="Bricolage")
    session.add(tag)
    session.commit()
    session.add(ObjetTagLink(objet_id=objet.id, tag_id=tag.id))
    session.commit()
    d = datetime
    _res(session, objet, user, lieu, d(2030, 1, 14), d(2030, 1, 21), "retire", 2)
    _res(session, objet, user, lieu, d(2030, 1, 10), d(2030, 1, 14), "terminee")
    _res(session, objet, user, lieu, d(2030, 1, 12), d(2030, 1, 19), "annulee")
    _res(session, objet, user, lieu, d(2029, 12, 20), d(2029, 12, 27), "terminee")
    _res(session, objet, user, lieu, d(2030, 1, 5), d(2030, 1, 12), "en_verification")
    _res(session, objet, user, lieu, d(2030, 1, 9), d(2030, 1, 13), "en_preparation")  # en retard
    return admin, user, lieu, objet


def test_stats_semaine(session, jeu):
    stats = compute_stats(session, "semaine", NOW)
    assert (stats["debut"], stats["fin"]) == ("2030-01-09", "2030-01-15")
    act, snap = stats["activite"], stats["snapshot"]

    # démarrées dans la fenêtre, hors annulées : retire (14), terminee (10), en_preparation (9)
    assert act["reservations"] == 3
    assert act["semaines_reservees"] == 4  # 2 + 1 + 1
    assert act["credits_consommes"] == 4
    assert (act["annulations"], act["taux_annulation"]) == (1, 25.0)
    # rendus : terminee (fin 14) + en_verification (fin 12)
    assert act["objets_rendus"] == 2
    assert act["objets_distincts_reserves"] == 1 and act["emprunteurs_actifs"] == 1
    assert act["top_objets"] == [{"nom": "Perceuse", "reservations": 3}]
    assert act["par_categorie"] == [{"nom": "Bricolage", "reservations": 3}]
    assert act["par_lieu"] == [{"nom": "LieuTest", "reservations": 3}]

    statuts = {s["statut"]: s["nombre"] for s in snap["reservations_par_statut"]}
    assert statuts == {
        "en_preparation": 1, "mis_a_disposition": 0, "retire": 1, "restitue": 0, "en_verification": 1,
    }
    assert snap["reservations_en_cours"] == 3
    assert snap["objets_empruntes"] == 1 and snap["objets_en_verification"] == 1
    assert snap["objets_en_retard"] == 1  # la réservation en préparation a dépassé sa fin
    assert snap["utilisateurs_inscrits"] == 2 and snap["administrateurs"] == 1
    assert snap["objets_total"] == 1 and snap["lieux"] == 1


def test_stats_series_temporelles(session, jeu):
    series = compute_stats(session, "semaine", NOW)["series"]
    assert series["labels"][0] == "09/01" and series["labels"][-1] == "15/01" and len(series["labels"]) == 7
    # 09/01 -> index 0 ; réservations aux 09, 10 et 14 ; retours le 12 et le 14
    assert series["reservations"] == [1, 1, 0, 0, 0, 1, 0]
    assert series["retours"] == [0, 0, 0, 1, 0, 1, 0]


def test_stats_mois_et_annee(session, jeu):
    mois = compute_stats(session, "mois", NOW)
    assert len(mois["series"]["labels"]) == 30
    # 5 : les 3 de la semaine + celle du 05/01 + celle du 20/12/2029 (annulée exclue)
    assert mois["activite"]["reservations"] == 5

    annee = compute_stats(session, "annee", NOW)
    assert len(annee["series"]["labels"]) == 12
    assert annee["series"]["labels"][-1] == "janv 30" and annee["series"]["labels"][0] == "févr 29"
    assert annee["debut"] == "2029-02-01"
    assert sum(annee["series"]["reservations"]) == 5  # la réservation du 05/01 entre dans l'année
    assert annee["series"]["reservations"][-2] == 1  # décembre 2029


def test_stats_nouveaux_inscrits(session, jeu):
    _, user, _, _ = jeu
    user.created_at = datetime(2030, 1, 14)
    session.add(user)
    session.commit()
    assert compute_stats(session, "semaine", NOW)["activite"]["nouveaux_inscrits"] == 1
    # les comptes sans date d'inscription (créés avant le champ) ne comptent pas
    user.created_at = None
    session.add(user)
    session.commit()
    assert compute_stats(session, "semaine", NOW)["activite"]["nouveaux_inscrits"] == 0


def test_stats_base_vide_et_periode_invalide(session):
    stats = compute_stats(session, "mois", NOW)
    assert stats["activite"]["reservations"] == 0 and stats["activite"]["taux_annulation"] == 0.0
    assert stats["activite"]["top_objets"] == []
    with pytest.raises(ValueError):
        compute_stats(session, "decennie", NOW)


def test_stats_annee_a_cheval_sur_deux_annees(session):
    labels = compute_stats(session, "annee", datetime(2030, 3, 10))["series"]["labels"]
    assert labels[0] == "avr 29" and labels[-1] == "mars 30"


def test_stats_objet_sans_categorie_ni_lieu(session):
    _, user, lieu, objet = _create_base_data(session)
    session.add(Reservation(date_debut=datetime(2030, 1, 14), date_fin=datetime(2030, 1, 21),
                            status="retire", user_id=user.id, objet_id=objet.id, lieu_id=None))
    session.add(Reservation(date_debut=datetime(2030, 1, 14), date_fin=datetime(2030, 1, 21),
                            status="retire", user_id=user.id, objet_id=None, lieu_id=lieu.id))
    session.commit()
    act = compute_stats(session, "semaine", NOW)["activite"]
    assert act["par_categorie"] == [{"nom": "Sans catégorie", "reservations": 1}]
    assert {"nom": "Non précisé", "reservations": 1} in act["par_lieu"]


def test_stats_categorie_principale_seule(session):
    """Objet ancien : une catégorie principale (tag_id) mais aucun lien multi-catégories."""
    _, user, lieu, objet = _create_base_data(session)
    tag = Tag(nom="Jardinage")
    session.add(tag)
    session.commit()
    objet.tag_id = tag.id
    session.add(objet)
    session.add(Reservation(date_debut=datetime(2030, 1, 14), date_fin=datetime(2030, 1, 21),
                            status="retire", user_id=user.id, objet_id=objet.id, lieu_id=lieu.id))
    session.commit()
    assert compute_stats(session, "semaine", NOW)["activite"]["par_categorie"] == [
        {"nom": "Jardinage", "reservations": 1}
    ]


# ---------------------------------------------------------------- PDF

def test_pdf_complet(session, jeu):
    pdf = pdf_report.build_pdf(compute_stats(session, "mois", NOW))
    assert pdf.startswith(b"%PDF") and len(pdf) > 1500


def test_pdf_base_vide(session):
    pdf = pdf_report.build_pdf(compute_stats(session, "annee", NOW))
    assert pdf.startswith(b"%PDF")


def test_pdf_caracteres_hors_latin1_et_saut_de_page(session):
    assert pdf_report._t("prix 5 € — ok") == "prix 5 ? ? ok"
    pdf = pdf_report._Report()
    pdf.add_page()
    pdf.set_y(pdf.h - 30)  # graphique trop bas : doit passer à la page suivante
    pdf_report._bar_chart(pdf, "Test", ["a", "b"], [("S", pdf_report.MINT, [0, 3])])
    assert pdf.page_no() == 2


# ---------------------------------------------------------------- e-mail

class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.calls = host, port, []
        self.sent = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def send_message(self, msg):
        self.calls.append("send")
        self.sent = msg


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"):
        monkeypatch.delenv(k, raising=False)
    return FakeSMTP


def test_mail_non_configure(fake_smtp):
    with pytest.raises(mailer.MailNotConfigured):
        mailer.send_mail("a@b.fr", "s", "b")
    assert fake_smtp.instances == []


def test_mail_starttls_login_et_piece_jointe(fake_smtp, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_USER", "robot@test.fr")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    mailer.send_mail("contact@test.fr", "Sujet", "Corps", attachment=b"%PDF-x", attachment_name="r.pdf")

    smtp = fake_smtp.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.test", 587)
    assert smtp.calls == ["starttls", ("login", "robot@test.fr", "secret"), "send"]
    assert smtp.sent["From"] == "robot@test.fr"  # SMTP_FROM absent : on retombe sur SMTP_USER
    assert smtp.sent["To"] == "contact@test.fr" and smtp.sent["Subject"] == "Sujet"
    piece = list(smtp.sent.iter_attachments())[0]
    assert piece.get_filename() == "r.pdf" and piece.get_content() == b"%PDF-x"


def test_mail_ssl_sans_identifiants_ni_piece_jointe(fake_smtp, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_PORT", "465")
    monkeypatch.setenv("SMTP_FROM", "noreply@test.fr")
    mailer.send_mail("contact@test.fr", "Sujet", "Corps")
    smtp = fake_smtp.instances[0]
    assert smtp.port == 465 and smtp.calls == ["send"]  # SMTP_SSL : ni starttls ni login
    assert smtp.sent["From"] == "noreply@test.fr"
    assert list(smtp.sent.iter_attachments()) == []


def test_destinataire_par_defaut_et_configurable(monkeypatch):
    monkeypatch.delenv("STATS_RECIPIENT", raising=False)
    assert mailer.stats_recipient() == "contact@larmoirecommune.fr"
    monkeypatch.setenv("STATS_RECIPIENT", "autre@test.fr")
    assert mailer.stats_recipient() == "autre@test.fr"


# ---------------------------------------------------------------- routes

def test_routes_droits(session):
    _create_base_data(session)
    uh = _login("user@test.com", "user")
    for method, url in (("get", "/admin/stats"), ("post", "/admin/stats/export")):
        assert getattr(client, method)(url).status_code == 401
        assert getattr(client, method)(url, headers=uh).status_code == 403


def test_route_stats(session, jeu):
    ah = _login("admin@test.com", "admin")
    r = client.get("/admin/stats?periode=annee", headers=ah)
    assert r.status_code == 200
    body = r.json()
    assert body["periode"] == "annee" and set(body) >= {"snapshot", "activite", "series"}
    # période par défaut : le mois
    assert client.get("/admin/stats", headers=ah).json()["periode"] == "mois"
    assert client.get("/admin/stats?periode=siecle", headers=ah).status_code == 400
    assert client.post("/admin/stats/export?periode=siecle", headers=ah).status_code == 400


def test_route_export_envoie_le_pdf(session, jeu, monkeypatch):
    envoyes = []
    monkeypatch.delenv("STATS_RECIPIENT", raising=False)
    monkeypatch.setattr(mailer, "send_mail", lambda *a, **k: envoyes.append((a, k)))
    ah = _login("admin@test.com", "admin")

    r = client.post("/admin/stats/export?periode=semaine", headers=ah)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "sent_to": "contact@larmoirecommune.fr"}
    (args, kwargs) = envoyes[0]
    assert args[0] == "contact@larmoirecommune.fr"
    assert "7 derniers jours" in args[1]
    assert kwargs["attachment"].startswith(b"%PDF")
    assert kwargs["attachment_name"] == "statistiques-semaine.pdf"


def test_route_export_erreurs_mail(session, jeu, monkeypatch, fake_smtp):
    ah = _login("admin@test.com", "admin")
    # SMTP non configuré : message explicite
    r = client.post("/admin/stats/export?periode=mois", headers=ah)
    assert r.status_code == 503 and "non configuré" in r.json()["detail"]

    def boom(exc):
        def _raise(*a, **k):
            raise exc
        return _raise

    monkeypatch.setattr(mailer, "send_mail", boom(smtplib.SMTPAuthenticationError(535, b"bad")))
    assert client.post("/admin/stats/export?periode=mois", headers=ah).status_code == 502
    monkeypatch.setattr(mailer, "send_mail", boom(ConnectionRefusedError()))
    assert client.post("/admin/stats/export?periode=mois", headers=ah).status_code == 502
