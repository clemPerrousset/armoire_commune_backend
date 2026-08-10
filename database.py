import os
from sqlmodel import SQLModel, create_engine, Session

# Le fallback pointe vers le volume persistant /data (monté par docker-compose)
# plutôt qu'un chemin relatif au conteneur : si DATABASE_URL n'est pas défini
# dans .env, on ne veut surtout pas écrire une base éphémère qui disparaît
# à chaque rebuild.
sqlite_url = os.getenv("DATABASE_URL", "sqlite:////data/database.db")

connect_args = {"check_same_thread": False}
engine = create_engine(sqlite_url, echo=True, connect_args=connect_args)

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
