"""
Configuration partagée pour tous les tests pytest.
Un seul engine SQLite en mémoire, recréé à chaque test pour l'isolation.
"""
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from main import app
from database import get_session

# Engine partagé entre tous les fichiers de test
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

def get_test_session():
    with Session(engine) as session:
        yield session

# Override global appliqué une seule fois
app.dependency_overrides[get_session] = get_test_session


@pytest.fixture(name="session", autouse=False)
def session_fixture():
    """Recrée les tables avant chaque test et les supprime après."""
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="client")
def client_fixture(session):
    return TestClient(app)
