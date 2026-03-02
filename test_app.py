from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from main import app
from database import get_session
from models import User, Tag, Lieu, Objet, Reservation
from auth import get_password_hash
import pytest
from datetime import datetime
from sqlalchemy.pool import StaticPool

# Use an in-memory SQLite database for testing
sqlite_url = "sqlite://"
connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args, poolclass=StaticPool)

def get_session_override():
    with Session(engine) as session:
        yield session

app.dependency_overrides[get_session] = get_session_override
client = TestClient(app)

@pytest.fixture(name="session")
def session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)

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

    # 3. Create Objet (Admin)
    obj_data = {
        "nom": "Drill",
        "description": "Powerful",
        "quantite": 1,
        "tag_id": tag.id,
        "consommable_ids": []
    }
    res = client.post("/objets", json=obj_data, headers=admin_headers)
    assert res.status_code == 200
    objet_id = res.json()["id"]

    # 4. List Objets (Public)
    res = client.get("/objets")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["nom"] == "Drill"

    # 5. Login User
    res = client.post("/auth/login", data={"username": "user@test.com", "password": "user"})
    assert res.status_code == 200
    user_token = res.json()["access_token"]
    user_headers = {"Authorization": f"Bearer {user_token}"}

    # 6. Reserve Objet
    # Use a specific date (Monday) to test the Wednesday adjustment logic
    monday_date = datetime(2023, 10, 23, 10, 30) # Monday
    res_data = {
        "objet_id": objet_id,
        "lieu_id": lieu.id,
        "date_debut": monday_date.isoformat()
    }
    res = client.post("/reservations", json=res_data, headers=user_headers)
    if res.status_code != 200:
        print(res.json())
    assert res.status_code == 200

    # Verify the reservation dates were correctly calculated
    reservation = res.json()
    reservation_id = reservation["id"]

    # Wednesday 2023-10-25 10:30:00
    expected_start = "2023-10-25T10:30:00"
    # Tuesday 2023-10-31 22:00:00
    expected_end = "2023-10-31T22:00:00"

    assert reservation["date_debut"] == expected_start
    assert reservation["date_fin"] == expected_end

    # 7. Check Availability (Should be 0 now)
    # Note: list_objets logic checks if quantite > active reservations
    # Our reservation is active for the same date check window.
    # So if we query availability on the same Monday date, it will check the window [Wednesday, next Tuesday]
    res = client.get(f"/objets?available=true&date_check={monday_date.isoformat()}")
    # Should be empty because quantity is 1 and 1 is reserved in that window
    assert res.status_code == 200
    assert len(res.json()) == 0

    # 8. Admin Return Object
    res = client.post(f"/admin/reservations/{reservation_id}/return", headers=admin_headers)
    assert res.status_code == 200

    # 9. Check Availability (Should be 1 now)
    res = client.get(f"/objets?available=true&date_check={monday_date.isoformat()}")
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
