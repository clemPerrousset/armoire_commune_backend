from fastapi.testclient import TestClient
from sqlmodel import Session, select
import pytest
from main import app
from models import User
from auth import get_password_hash

# conftest.py gère l'engine de test et la fixture session
client = TestClient(app)


def create_user(session: Session, email: str, is_admin: bool = False, is_point_relais: bool = False) -> User:
    user = User(
        nom="Test",
        prenom="User",
        email=email,
        password_hash=get_password_hash("password"),
        is_admin=is_admin,
        is_point_relais=is_point_relais
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def get_token(email: str) -> str:
    response = client.post("/auth/login", data={"username": email, "password": "password"})
    return response.json()["access_token"]


def test_signup_defaults_to_false_point_relais(session):
    response = client.post("/auth/signup", json={
        "nom": "New", "prenom": "User",
        "email": "new@example.com", "password": "password"
    })
    assert response.status_code == 200
    assert response.json()["is_point_relais"] is False

    user = session.exec(select(User).where(User.email == "new@example.com")).first()
    assert user.is_point_relais is False


def test_admin_can_promote_point_relais(session):
    admin = create_user(session, "admin@example.com", is_admin=True)
    user = create_user(session, "normal@example.com")

    admin_token = get_token(admin.email)

    response = client.put(
        f"/admin/users/{user.id}/promote-point-relais",
        params={"is_point_relais": True},
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    assert "point relais status set to True" in response.json()["message"]

    session.refresh(user)
    assert user.is_point_relais is True


def test_normal_user_cannot_promote_point_relais(session):
    user1 = create_user(session, "user1@example.com")
    user2 = create_user(session, "user2@example.com")

    user1_token = get_token(user1.email)

    response = client.put(
        f"/admin/users/{user2.id}/promote-point-relais",
        params={"is_point_relais": True},
        headers={"Authorization": f"Bearer {user1_token}"}
    )
    assert response.status_code == 403


def test_get_users_me_returns_point_relais(session):
    user = create_user(session, "pr@example.com", is_point_relais=True)
    token = get_token(user.email)

    response = client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["is_point_relais"] is True
