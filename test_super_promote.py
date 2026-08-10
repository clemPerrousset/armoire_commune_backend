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
        "email": user.email,
        "password": "secret123",
        "is_admin": True
    }
    response = client.post("/admin/users/super-promote", json=payload)

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
        "email": user.email,
        "password": "wrongpassword",
        "is_admin": True
    }
    response = client.post("/admin/users/super-promote", json=payload)

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
        "email": user.email,
        "password": "anypassword",
        "is_admin": True
    }
    response = client.post("/admin/users/super-promote", json=payload)

    assert response.status_code == 401

def test_super_promote_user_not_found(session, monkeypatch):
    monkeypatch.setenv("superUserPassword", "secret123")

    payload = {
        "email": "doesnotexist@example.com",
        "password": "secret123",
        "is_admin": True
    }
    response = client.post("/admin/users/super-promote", json=payload)

    assert response.status_code == 404

def test_super_list_admins_success(session, monkeypatch):
    monkeypatch.setenv("superUserPassword", "secret123")

    admin1 = User(nom="Admin", prenom="One", email="admin1@example.com", password_hash=get_password_hash("pass"), is_admin=True)
    admin2 = User(nom="Admin", prenom="Two", email="admin2@example.com", password_hash=get_password_hash("pass"), is_admin=True)
    regular = User(nom="Regular", prenom="User", email="regular@example.com", password_hash=get_password_hash("pass"), is_admin=False)
    session.add(admin1)
    session.add(admin2)
    session.add(regular)
    session.commit()

    payload = {"password": "secret123"}
    response = client.post("/admin/users/super-list-admins", json=payload)

    assert response.status_code == 200
    emails = {u["email"] for u in response.json()}
    assert emails == {"admin1@example.com", "admin2@example.com"}

def test_super_list_admins_wrong_password(session, monkeypatch):
    monkeypatch.setenv("superUserPassword", "secret123")

    payload = {"password": "wrongpassword"}
    response = client.post("/admin/users/super-list-admins", json=payload)

    assert response.status_code == 401

def test_super_list_admins_no_env_var(session, monkeypatch):
    monkeypatch.delenv("superUserPassword", raising=False)

    payload = {"password": "anypassword"}
    response = client.post("/admin/users/super-list-admins", json=payload)

    assert response.status_code == 401
