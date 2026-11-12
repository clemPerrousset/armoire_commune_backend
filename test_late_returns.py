"""check-late : prolongation ou alerte des réservations dont la date de fin est dépassée.
Les dates sont relatives à now() car l'endpoint compare à datetime.now()."""
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from main import app
from models import Objet, Reservation, User
from auth import get_current_admin

client = TestClient(app)


def _admin_override(user):
    app.dependency_overrides[get_current_admin] = lambda: user


def _base(session, suffix=""):
    admin = User(nom="Admin", prenom="A", email=f"admin{suffix}@test.com", password_hash="hash", is_admin=True)
    u1 = User(nom="U1", prenom="U", email=f"u1{suffix}@test.com", password_hash="hash")
    u2 = User(nom="U2", prenom="U", email=f"u2{suffix}@test.com", password_hash="hash")
    objet = Objet(nom=f"Perc{suffix}", description="test")
    for o in (admin, u1, u2, objet):
        session.add(o)
    session.commit()
    for o in (admin, u1, u2, objet):
        session.refresh(o)
    return admin, u1, u2, objet


def test_check_late_prolonge_si_pas_de_reservation_suivante(session):
    admin, u1, _, objet = _base(session)
    now = datetime.now()
    late = Reservation(objet_id=objet.id, user_id=u1.id, date_debut=now - timedelta(days=14),
                       date_fin=now - timedelta(days=7), status="retire")
    session.add(late)
    session.commit()
    ancienne_fin = late.date_fin
    _admin_override(admin)

    r = client.post("/admin/reservations/check-late")
    assert r.status_code == 200
    data = r.json()
    assert data["extended"] == 1
    assert data["alerts_triggered"] == 0

    session.refresh(late)
    assert late.date_fin == ancienne_fin + timedelta(days=7)


def test_check_late_alerte_si_reservation_suivante_puis_clear(session):
    admin, u1, u2, objet = _base(session, "2")
    now = datetime.now()
    late = Reservation(objet_id=objet.id, user_id=u1.id, date_debut=now - timedelta(days=14),
                       date_fin=now - timedelta(days=7), status="retire")
    futur = Reservation(objet_id=objet.id, user_id=u2.id, date_debut=now - timedelta(days=6),
                        date_fin=now + timedelta(days=1), status="en_preparation")
    session.add(late)
    session.add(futur)
    session.commit()
    _admin_override(admin)

    data = client.post("/admin/reservations/check-late").json()
    assert data["extended"] == 0
    assert data["alerts_triggered"] == 1
    session.refresh(objet)
    assert objet.alert is True

    # La liste des alertes contient l'objet (route admin)
    alerts = client.get("/admin/objets/alerts").json()
    assert [o["id"] for o in alerts] == [objet.id]

    assert client.post(f"/admin/objets/{objet.id}/clear-alert").status_code == 200
    session.refresh(objet)
    assert objet.alert is False


def test_check_late_ignore_restitue_et_en_verification(session):
    admin, u1, _, objet = _base(session, "3")
    now = datetime.now()
    for st in ("restitue", "en_verification"):
        session.add(Reservation(objet_id=objet.id, user_id=u1.id, date_debut=now - timedelta(days=14),
                                date_fin=now - timedelta(days=7), status=st))
    session.commit()
    _admin_override(admin)
    data = client.post("/admin/reservations/check-late").json()
    assert data["extended"] == 0 and data["alerts_triggered"] == 0


def test_alerts_vide_sans_retard(session):
    admin, _, _, _ = _base(session, "4")
    _admin_override(admin)
    assert client.get("/admin/objets/alerts").json() == []


def test_clear_alert_objet_inconnu_404(session):
    admin, _, _, _ = _base(session, "5")
    _admin_override(admin)
    assert client.post("/admin/objets/9999/clear-alert").status_code == 404
