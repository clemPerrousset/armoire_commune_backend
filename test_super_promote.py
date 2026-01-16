from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from main import app
from database import get_session
from models import User
from auth import get_password_hash
import pytest
import os
from sqlalchemy.pool import StaticPool

# Setup in-memory DB
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

def test_super_promote_success(session, monkeypatch):
    # Mock environment variable
    monkeypatch.setenv("superUserPassword", "secret123")

    # Create non-admin user
    user = User(nom="User", prenom="Test", email="test@example.com", password_hash=get_password_hash("pass"), is_admin=False)
    session.add(user)
    session.commit()
    session.refresh(user)

    # Call super-promote
    payload = {
        "password": "secret123",
        "is_admin": True
    }
    response = client.post(f"/admin/users/{user.id}/super-promote", json=payload)

    assert response.status_code == 200
    assert response.json()["message"] == f"User {user.email} admin status set to True"

    # Verify in DB
    session.refresh(user)
    assert user.is_admin is True

def test_super_promote_wrong_password(session, monkeypatch):
    monkeypatch.setenv("superUserPassword", "secret123")

    user = User(nom="User", prenom="Test", email="test2@example.com", password_hash=get_password_hash("pass"), is_admin=False)
    session.add(user)
    session.commit()
    session.refresh(user)

    payload = {
        "password": "wrongpassword",
        "is_admin": True
    }
    response = client.post(f"/admin/users/{user.id}/super-promote", json=payload)

    assert response.status_code == 401
    session.refresh(user)
    assert user.is_admin is False

def test_super_promote_no_env_var(session, monkeypatch):
    # Ensure env var is unset
    monkeypatch.delenv("superUserPassword", raising=False)

    user = User(nom="User", prenom="Test", email="test3@example.com", password_hash=get_password_hash("pass"), is_admin=False)
    session.add(user)
    session.commit()
    session.refresh(user)

    payload = {
        "password": "anypassword",
        "is_admin": True
    }
    response = client.post(f"/admin/users/{user.id}/super-promote", json=payload)

    assert response.status_code == 401
