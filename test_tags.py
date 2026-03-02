from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from main import app
from database import get_session
from models import User, Tag, Objet
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

def test_delete_tag(session):
    # 1. Create Data
    admin = User(nom="Admin", prenom="A", email="admin@test.com", password_hash=get_password_hash("admin"), is_admin=True)
    user = User(nom="User", prenom="B", email="user@test.com", password_hash=get_password_hash("user"), is_admin=False)
    tag = Tag(nom="Tag to delete")
    session.add(admin)
    session.add(user)
    session.add(tag)
    session.commit()
    session.refresh(tag)

    # Create an object linked to this tag
    objet = Objet(nom="Objet linked to tag", description="Test", quantite=1, tag_id=tag.id)
    session.add(objet)
    session.commit()
    session.refresh(objet)

    tag_id = tag.id
    objet_id = objet.id

    # 2. Login as Admin
    res = client.post("/auth/login", data={"username": "admin@test.com", "password": "admin"})
    admin_token = res.json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 3. Login as User
    res = client.post("/auth/login", data={"username": "user@test.com", "password": "user"})
    user_token = res.json()["access_token"]
    user_headers = {"Authorization": f"Bearer {user_token}"}

    # 4. Attempt Delete as Anon (401)
    res = client.delete(f"/admin_meta/tags/{tag_id}")
    assert res.status_code == 401

    # 5. Attempt Delete as User (403)
    res = client.delete(f"/admin_meta/tags/{tag_id}", headers=user_headers)
    assert res.status_code == 403

    # 6. Delete as Admin (200)
    res = client.delete(f"/admin_meta/tags/{tag_id}", headers=admin_headers)
    assert res.status_code == 200

    # Verify deletion
    session.expire_all()
    assert session.get(Tag, tag_id) is None

    # Verify that the linked object's tag_id is set to null
    linked_objet = session.get(Objet, objet_id)
    assert linked_objet is not None
    assert linked_objet.tag_id is None

    # 7. Delete Non-Existent (404)
    res = client.delete(f"/admin_meta/tags/{tag_id + 999}", headers=admin_headers)
    assert res.status_code == 404
