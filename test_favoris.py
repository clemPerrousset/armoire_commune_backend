from fastapi.testclient import TestClient
from sqlmodel import Session
from main import app
from models import User, Objet

# conftest.py gère l'engine de test et la fixture session
client = TestClient(app)


def test_favoris(session):
    user = User(nom="Test", prenom="Test", email="test@test.com", password_hash="hash")
    objet = Objet(nom="Test Object", description="Test")
    session.add(user)
    session.add(objet)
    session.commit()
    session.refresh(user)
    session.refresh(objet)
    user_id = user.id
    objet_id = objet.id

    from auth import get_current_user
    from conftest import engine

    def override_get_current_user():
        with Session(engine) as s:
            return s.get(User, user_id)

    app.dependency_overrides[get_current_user] = override_get_current_user

    res = client.post(f"/users/favoris/{objet_id}")
    assert res.status_code == 200

    res = client.get("/users/favoris")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["id"] == objet_id

    res = client.delete(f"/users/favoris/{objet_id}")
    assert res.status_code == 200

    res = client.get("/users/favoris")
    assert res.status_code == 200
    assert len(res.json()) == 0

    app.dependency_overrides.pop(get_current_user)
