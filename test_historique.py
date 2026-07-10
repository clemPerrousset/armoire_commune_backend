from fastapi.testclient import TestClient
from sqlmodel import Session
from main import app
from models import User, Objet, UserObjetHistoriqueLink

# conftest.py gère l'engine de test et la fixture session
client = TestClient(app)


def test_history(session):
    user = User(nom="Test", prenom="Test", email="test@test.com", password_hash="hash")
    objet = Objet(nom="Test Object", description="Test")
    session.add(user)
    session.add(objet)
    session.commit()
    session.refresh(user)
    session.refresh(objet)
    user_id = user.id
    objet_id = objet.id

    # Sans authentification : pas d'entrée dans l'historique
    res = client.get(f"/objets/{objet_id}")
    assert res.status_code == 200
    links = session.query(UserObjetHistoriqueLink).all()
    assert len(links) == 0

    # Avec authentification (mock)
    from auth import get_current_user_optional
    from conftest import engine

    def override():
        with Session(engine) as s:
            return s.get(User, user_id)

    app.dependency_overrides[get_current_user_optional] = override

    res = client.get(f"/objets/{objet_id}")
    assert res.status_code == 200

    session.expire_all()
    links = session.query(UserObjetHistoriqueLink).all()
    assert len(links) == 1
    assert links[0].user_id == user_id
    assert links[0].objet_id == objet_id

    app.dependency_overrides.pop(get_current_user_optional)
