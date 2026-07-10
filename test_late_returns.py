import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta

from main import app
from models import Objet, Reservation, User

# conftest.py gère l'engine de test et la fixture session
client = TestClient(app)

def test_check_late_reservations_extends_if_no_future(session):
    admin_user = User(nom="Admin", prenom="A", email="admin@test.com", password_hash="hash", is_admin=True)
    user = User(nom="User", prenom="U", email="user@test.com", password_hash="hash")

    objet = Objet(nom="Perc", description="test")

    session.add(admin_user)
    session.add(user)
    session.add(objet)
    session.commit()

    now = datetime.now()
    late_res = Reservation(
        objet_id=objet.id,
        user_id=user.id,
        date_debut=now - timedelta(days=14),
        date_fin=now - timedelta(days=7),
        status="active"
    )
    session.add(late_res)
    session.commit()

    # We need a token. We can override get_current_admin instead
    from auth import get_current_admin
    app.dependency_overrides[get_current_admin] = lambda: admin_user

    response = client.post("/admin/reservations/check-late")
    assert response.status_code == 200
    data = response.json()
    assert data["processed"] == 1
    assert data["extended"] == 1
    assert data["alerts_triggered"] == 0

    # Verify DB
    session.refresh(late_res)
    # The end date should be pushed by 7 days
    assert late_res.date_fin > now - timedelta(days=8)

    app.dependency_overrides.pop(get_current_admin)

def test_check_late_reservations_alerts_if_future(session):
    admin_user = User(nom="Admin", prenom="A", email="admin2@test.com", password_hash="hash", is_admin=True)
    user1 = User(nom="User1", prenom="U", email="user1@test.com", password_hash="hash")
    user2 = User(nom="User2", prenom="U", email="user2@test.com", password_hash="hash")

    objet = Objet(nom="Perc2", description="test")

    session.add(admin_user)
    session.add(user1)
    session.add(user2)
    session.add(objet)
    session.commit()

    now = datetime.now()
    late_res = Reservation(
        objet_id=objet.id,
        user_id=user1.id,
        date_debut=now - timedelta(days=14),
        date_fin=now - timedelta(days=7),
        status="active"
    )

    future_res = Reservation(
        objet_id=objet.id,
        user_id=user2.id,
        date_debut=now - timedelta(days=6), # starts after late_res ends
        date_fin=now + timedelta(days=1),
        status="active"
    )

    session.add(late_res)
    session.add(future_res)
    session.commit()

    from auth import get_current_admin
    app.dependency_overrides[get_current_admin] = lambda: admin_user

    response = client.post("/admin/reservations/check-late")
    assert response.status_code == 200
    data = response.json()
    assert data["processed"] == 1
    assert data["extended"] == 0
    assert data["alerts_triggered"] == 1

    # Verify DB
    session.refresh(objet)
    assert objet.alert is True

    # Test clear alert
    response2 = client.post(f"/admin/objets/{objet.id}/clear-alert")
    assert response2.status_code == 200
    session.refresh(objet)
    assert objet.alert is False

    app.dependency_overrides.pop(get_current_admin)
