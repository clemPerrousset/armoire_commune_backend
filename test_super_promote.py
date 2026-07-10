from fastapi.testclient import TestClient
from main import app
from models import User
from auth import get_password_hash
import pytest
import os

# conftest.py gère l'engine de test et la fixture session
client = TestClient(app)

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
