import sqlite3

import pytest
from sqlalchemy import create_engine as sa_create_engine

import database
import migrate as migrate_module


@pytest.fixture
def old_schema_engine(monkeypatch, tmp_path):
    """Simule une base de prod avec un schéma 'ancien' — table user sans
    les colonnes credits / credits_reset_date ajoutées plus tard au modèle."""
    db_file = tmp_path / "old_schema.db"

    conn = sqlite3.connect(str(db_file))
    conn.execute(
        """
        CREATE TABLE user (
            id INTEGER PRIMARY KEY,
            nom VARCHAR NOT NULL,
            prenom VARCHAR NOT NULL,
            email VARCHAR NOT NULL,
            password_hash VARCHAR NOT NULL,
            is_admin BOOLEAN NOT NULL DEFAULT 0,
            is_point_relais BOOLEAN NOT NULL DEFAULT 0,
            association_id INTEGER
        )
        """
    )
    conn.execute(
        "INSERT INTO user (nom, prenom, email, password_hash, is_admin, is_point_relais) "
        "VALUES ('Existing', 'User', 'existing@example.com', 'hash', 0, 0)"
    )
    conn.commit()
    conn.close()

    test_engine = sa_create_engine(
        f"sqlite:///{db_file}", connect_args={"check_same_thread": False}
    )

    # migrate.py a importé `engine` par valeur depuis database.py — il faut
    # patcher les deux références pour rediriger vers la base de test.
    monkeypatch.setattr(database, "engine", test_engine)
    monkeypatch.setattr(migrate_module, "engine", test_engine)

    return test_engine


def test_migrate_adds_missing_columns_and_backfills_default(old_schema_engine):
    migrate_module.migrate()

    with old_schema_engine.connect() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(user)")}
        assert "credits" in columns
        assert "credits_reset_date" in columns

        row = conn.exec_driver_sql(
            "SELECT credits, credits_reset_date FROM user WHERE email = 'existing@example.com'"
        ).first()
        assert row[0] == 100  # backfillé automatiquement par le DEFAULT SQLite
        assert row[1] is None  # pas de default déclaré -> reste NULL


def test_migrate_does_not_touch_existing_data(old_schema_engine):
    migrate_module.migrate()

    with old_schema_engine.connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT nom, prenom, email FROM user WHERE email = 'existing@example.com'"
        ).first()
        assert row == ("Existing", "User", "existing@example.com")


def test_migrate_is_idempotent(old_schema_engine):
    migrate_module.migrate()
    migrate_module.migrate()  # rejouer ne doit pas planter (ex: redémarrage du conteneur)

    with old_schema_engine.connect() as conn:
        columns = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(user)")]
        assert columns.count("credits") == 1
