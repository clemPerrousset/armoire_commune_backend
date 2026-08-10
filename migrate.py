"""
Migration additive et non destructive : ajoute les tables et colonnes
manquantes déclarées dans les modèles SQLModel, sans jamais supprimer ou
renommer une colonne existante.

SQLModel.metadata.create_all() ne crée que les tables absentes — il ne
modifie jamais une table existante. Sans ce script, ajouter un champ à un
modèle (ex: User.credits) fait planter la première requête qui le lit sur
une base de prod déjà peuplée ("no such column"), ce qui pousse à
supprimer le fichier de base pour "repartir propre" et perdre les
données réelles.
"""
from sqlalchemy import inspect, text

from database import engine, create_db_and_tables
from sqlmodel import SQLModel


def _format_default(column):
    """Retourne la clause SQL du DEFAULT si la colonne a une valeur scalaire fixe."""
    if column.default is None or not getattr(column.default, "is_scalar", False):
        return None
    value = column.default.arg
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'{}'".format(value.replace("'", "''"))
    return None


def migrate():
    # Crée les tables qui n'existent pas du tout encore (sans toucher aux existantes)
    create_db_and_tables()

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table_name, table in SQLModel.metadata.tables.items():
            if table_name not in existing_tables:
                continue  # déjà créée ci-dessus

            existing_columns = {col["name"] for col in inspector.get_columns(table_name)}

            for column in table.columns:
                if column.name in existing_columns:
                    continue

                col_type = column.type.compile(engine.dialect)
                ddl = f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {col_type}'

                default_sql = _format_default(column)
                if default_sql is not None:
                    # SQLite applique la valeur DEFAULT à toutes les lignes
                    # existantes lors d'un ADD COLUMN, pas seulement aux futures.
                    ddl += f" DEFAULT {default_sql}"

                print(f"[migrate] {table_name}.{column.name} ({col_type}) — colonne manquante, ajout")
                conn.execute(text(ddl))


if __name__ == "__main__":
    migrate()
