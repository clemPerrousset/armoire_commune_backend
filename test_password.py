from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def _signup_and_login(email="pw@test.com", password="123456"):
    r = client.post("/auth/signup", json={"nom": "N", "prenom": "P", "email": email, "password": password})
    assert r.status_code == 200
    r = client.post("/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_default_password_flag_then_change(session):
    h = _signup_and_login()
    assert client.get("/users/me", headers=h).json()["has_default_password"] is True

    r = client.put("/users/me/password", headers=h, json={"current_password": "123456", "new_password": "nouveau-mdp"})
    assert r.status_code == 200
    assert client.get("/users/me", headers=h).json()["has_default_password"] is False

    # Ancien mot de passe refusé, nouveau accepté
    assert client.post("/auth/login", data={"username": "pw@test.com", "password": "123456"}).status_code == 401
    assert client.post("/auth/login", data={"username": "pw@test.com", "password": "nouveau-mdp"}).status_code == 200


def test_change_password_wrong_current(session):
    h = _signup_and_login()
    r = client.put("/users/me/password", headers=h, json={"current_password": "faux", "new_password": "abcdefg"})
    assert r.status_code == 400


def test_change_password_rejects_weak_or_default(session):
    h = _signup_and_login()
    assert client.put("/users/me/password", headers=h, json={"current_password": "123456", "new_password": "abc"}).status_code == 400
    assert client.put("/users/me/password", headers=h, json={"current_password": "123456", "new_password": "123456"}).status_code == 400


def test_change_password_requires_auth(session):
    assert client.put("/users/me/password", json={"current_password": "a", "new_password": "abcdefg"}).status_code == 401
