from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool
from database import get_session
from main import app
from models import User, Objet

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
SQLModel.metadata.create_all(engine)

def get_session_override():
    with Session(engine) as session:
        yield session

app.dependency_overrides[get_session] = get_session_override
client = TestClient(app)

def test_favoris():
    with Session(engine) as session:
        user = User(nom="Test", prenom="Test", email="test@test.com", password_hash="hash")
        objet = Objet(nom="Test Object", description="Test")
        session.add(user)
        session.add(objet)
        session.commit()
        session.refresh(user)
        session.refresh(objet)
        user_id = user.id
        objet_id = objet.id

    # Mock authentication
    from auth import get_current_user
    def override_get_current_user():
        with Session(engine) as session:
            return session.get(User, user_id)

    app.dependency_overrides[get_current_user] = override_get_current_user

    # Add to favorites
    res = client.post(f"/users/favoris/{objet_id}")
    assert res.status_code == 200

    # List favorites
    res = client.get("/users/favoris")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["id"] == objet_id

    # List historique (should be empty here)
    res = client.get("/users/historique")
    assert res.status_code == 200
    assert len(res.json()) == 0

    # Remove from favorites
    res = client.delete(f"/users/favoris/{objet_id}")
    assert res.status_code == 200

    # List favorites again
    res = client.get("/users/favoris")
    assert res.status_code == 200
    assert len(res.json()) == 0
