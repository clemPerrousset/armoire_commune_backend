#!/usr/bin/env python3
"""
Sauvegarde à chaud de la base SQLite vers un dossier hors du volume docker.

Utilise l'API sqlite3.Connection.backup() (pas un simple cp) pour garantir
un snapshot cohérent même si l'appli est en train d'écrire en même temps.

Usage :
    python3 scripts/backup_db.py [chemin_db] [dossier_backups] [retention_jours]

Défauts : data/database.db -> ../db_backups, rétention 7 jours.
À lancer via cron sur l'hôte (PAS dans le conteneur), ex. toutes les heures :
    0 * * * * cd /home/ubuntu/armoire_commune/armoire_commune_backend && \
        /usr/bin/python3 scripts/backup_db.py >> ../db_backups/backup.log 2>&1
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_DB_PATH = Path("data/database.db")
DEFAULT_BACKUP_DIR = Path("../db_backups")
DEFAULT_RETENTION_DAYS = 7


def backup(db_path: Path, backup_dir: Path, retention_days: int) -> None:
    if not db_path.exists():
        print(f"[backup] {db_path} introuvable, rien à sauvegarder.")
        return

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"database_{timestamp}.db"

    src_conn = sqlite3.connect(str(db_path))
    dest_conn = sqlite3.connect(str(dest))
    try:
        with dest_conn:
            src_conn.backup(dest_conn)
    finally:
        src_conn.close()
        dest_conn.close()

    print(f"[backup] Sauvegarde créée : {dest}")

    cutoff = datetime.now().timestamp() - retention_days * 86400
    for old_backup in backup_dir.glob("database_*.db"):
        if old_backup.stat().st_mtime < cutoff:
            old_backup.unlink()
            print(f"[backup] Ancienne sauvegarde supprimée : {old_backup}")


if __name__ == "__main__":
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB_PATH
    backup_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_BACKUP_DIR
    retention_days = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_RETENTION_DAYS
    backup(db_path, backup_dir, retention_days)
