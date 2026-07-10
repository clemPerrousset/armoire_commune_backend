from fastapi.testclient import TestClient
from sqlmodel import select
from main import app
from models import User, Tag, Lieu, Objet, Reservation
from auth import get_password_hash
import pytest
from datetime import datetime

# conftest.py gère l'engine de test et la fixture session
client = TestClient(app)

def test_full_flow(session):
    # 1. Create Data
    admin = User(nom="Admin", prenom="A", email="admin@test.com", password_hash=get_password_hash("admin"), is_admin=True)
    user = User(nom="User", prenom="B", email="user@test.com", password_hash=get_password_hash("user"), is_admin=False)
    lieu = Lieu(nom="LieuTest", lat=0, long=0, adresse="Street")
    tag = Tag(nom="TagTest")
    session.add(admin)
    session.add(user)
    session.add(lieu)
    session.add(tag)
    session.commit()
    session.refresh(tag)
    session.refresh(lieu)

    # 2. Login Admin
    res = client.post("/auth/login", data={"username": "admin@test.com", "password": "admin"})
    assert res.status_code == 200
    admin_token = res.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 3. Create Objet (Admin) — sans champ quantite
    obj_data = {
        "nom": "Drill",
        "description": "Powerful",
        "tag_id": tag.id,
        "consommable_ids": []
    }
    res = client.post("/objets", json=obj_data, headers=admin_headers)
    assert res.status_code == 200
    objet_id = res.json()["id"]

    # 4. List Objets (Public) — sans paramètre = tous
    res = client.get("/objets")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["nom"] == "Drill"

    # 5. Login User
    res = client.post("/auth/login", data={"username": "user@test.com", "password": "user"})
    assert res.status_code == 200
    user_token = res.json()["access_token"]
    user_headers = {"Authorization": f"Bearer {user_token}"}

    # 6. Reserve Objet — cycle jeudi (lundi → ajusté au jeudi suivant)
    # Lundi 2023-10-23 → prochain jeudi = 2023-10-26
    monday_date = datetime(2023, 10, 23, 10, 30)
    res_data = {
        "objet_id": objet_id,
        "lieu_id": lieu.id,
        "date_debut": monday_date.isoformat(),
        "nb_semaines": 1,
    }
    res = client.post("/reservations", json=res_data, headers=user_headers)
    if res.status_code != 200:
        print(res.json())
    assert res.status_code == 200

    reservation = res.json()
    reservation_id = reservation["id"]

    # Jeudi 2023-10-26 ; fin = mercredi 2023-11-01 22:00
    assert reservation["date_debut"].startswith("2023-10-26"), reservation["date_debut"]
    assert reservation["date_fin"] == "2023-11-01T22:00:00", reservation["date_fin"]

    # 7. Check Availability (Should be 0 now)
    res = client.get(f"/objets?available=true&date_check={monday_date.isoformat()}")
    assert res.status_code == 200
    assert len(res.json()) == 0

    # 8. Admin Return Object
    res = client.post(f"/admin/reservations/{reservation_id}/return", headers=admin_headers)
    assert res.status_code == 200

    # 9. Check Availability (Should be 1 now)
    res = client.get(f"/objets?available=true&date_check={monday_date.isoformat()}")
    assert len(res.json()) == 1

    # 10. Check Case-Insensitive Search
    res = client.get("/objets?nom=dRiLL")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["nom"] == "Drill"

    res = client.get("/objets?nom=DRILL")
    assert res.status_code == 200
    assert len(res.json()) == 1

    res = client.get("/objets?nom=drill")
    assert res.status_code == 200
    assert len(res.json()) == 1

def test_get_current_user(session):
    # 1. Create User
    user = User(nom="Test", prenom="User", email="me@test.com", password_hash=get_password_hash("password"), is_admin=False)
    session.add(user)
    session.commit()

    # 2. Login
    res = client.post("/auth/login", data={"username": "me@test.com", "password": "password"})
    assert res.status_code == 200
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Get Me
    res = client.get("/users/me", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "me@test.com"
    assert data["nom"] == "Test"
    assert data["prenom"] == "User"
    assert data["is_admin"] is False
