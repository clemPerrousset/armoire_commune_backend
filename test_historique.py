from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool
from database import get_session
from main import app
from models import User, Objet, UserObjetHistoriqueLink

# Setup in-memory DB with StaticPool to share connection across threads
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

def test_history():
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

    # Test GET without login
    res = client.get(f"/objets/{objet_id}")
    assert res.status_code == 200

    with Session(engine) as session:
        links = session.query(UserObjetHistoriqueLink).all()
        assert len(links) == 0

    # Test GET with login (mocking get_current_user_optional)
    from auth import get_current_user_optional
    def override_get_current_user_optional():
        with Session(engine) as session:
            return session.get(User, user_id)

    app.dependency_overrides[get_current_user_optional] = override_get_current_user_optional

    res = client.get(f"/objets/{objet_id}")
    assert res.status_code == 200

    with Session(engine) as session:
        links = session.query(UserObjetHistoriqueLink).all()
        assert len(links) == 1
        assert links[0].user_id == user_id
        assert links[0].objet_id == objet_id
