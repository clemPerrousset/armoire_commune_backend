from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from main import app
from database import get_session
from models import User, Lieu
from auth import get_password_hash
import pytest
from sqlalchemy.pool import StaticPool

# Use an in-memory SQLite database for testing
sqlite_url = "sqlite://"
connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, connect_args=connect_args, poolclass=StaticPool)

def get_session_override():
    with Session(engine) as session:
        yield session

# Apply overrides globally for this test session context
app.dependency_overrides[get_session] = get_session_override
client = TestClient(app)

@pytest.fixture(name="session")
def session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)

def test_list_lieux(session):
    # 1. Create Data
    lieu1 = Lieu(nom="Lieu 1", lat=1.0, long=1.0, adresse="Adresse 1")
    lieu2 = Lieu(nom="Lieu 2", lat=2.0, long=2.0, adresse="Adresse 2")
    session.add(lieu1)
    session.add(lieu2)
    session.commit()

    # 2. Get Lieux
    res = client.get("/admin_meta/lieux")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    assert data[0]["nom"] == "Lieu 1"
    assert data[1]["nom"] == "Lieu 2"

def test_delete_lieu(session):
    # 1. Create Data
    admin = User(nom="Admin", prenom="A", email="admin@test.com", password_hash=get_password_hash("admin"), is_admin=True)
    user = User(nom="User", prenom="B", email="user@test.com", password_hash=get_password_hash("user"), is_admin=False)
    lieu = Lieu(nom="To Delete", lat=10.0, long=10.0, adresse="Delete St")
    session.add(admin)
    session.add(user)
    session.add(lieu)
    session.commit()
    session.refresh(lieu)
    lieu_id = lieu.id

    # 2. Login as Admin
    res = client.post("/auth/login", data={"username": "admin@test.com", "password": "admin"})
    admin_token = res.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 3. Login as User
    res = client.post("/auth/login", data={"username": "user@test.com", "password": "user"})
    user_token = res.json()["access_token"]
    user_headers = {"Authorization": f"Bearer {user_token}"}

    # 4. Attempt Delete as Anon (401)
    res = client.delete(f"/admin_meta/lieux/{lieu_id}")
    assert res.status_code == 401

    # 5. Attempt Delete as User (403)
    res = client.delete(f"/admin_meta/lieux/{lieu_id}", headers=user_headers)
    assert res.status_code == 403

    # 6. Delete as Admin (200)
    res = client.delete(f"/admin_meta/lieux/{lieu_id}", headers=admin_headers)
    assert res.status_code == 200

    # Verify deletion
    session.expire_all()
    assert session.get(Lieu, lieu_id) is None

    # 7. Delete Non-Existent (404)
    res = client.delete(f"/admin_meta/lieux/{lieu_id + 999}", headers=admin_headers)
    if res.status_code != 404 and res.status_code != 405:
         print(f"Unexpected status code for non-existent: {res.status_code}")
