#!/bin/sh
set -e

DB_PATH="/data/database.db"
BACKUP_DIR="/backups"

# Si la base est absente ou vide (ex: volume neuf après un rebuild qui a
# perdu son bind mount), restaurer depuis le backup le plus récent avant de
# laisser seed.py repartir avec une base vierge.
if [ ! -s "$DB_PATH" ] && [ -d "$BACKUP_DIR" ]; then
    LATEST_BACKUP=$(ls -1t "$BACKUP_DIR"/database_*.db 2>/dev/null | head -n 1 || true)
    if [ -n "$LATEST_BACKUP" ]; then
        echo "Base absente/vide — restauration depuis $LATEST_BACKUP"
        mkdir -p "$(dirname "$DB_PATH")"
        cp "$LATEST_BACKUP" "$DB_PATH"
    else
        echo "Base absente et aucun backup trouvé dans $BACKUP_DIR — démarrage à vide."
    fi
fi

echo "Migration du schéma..."
python migrate.py

echo "Seeding database..."
python seed.py

# Start the server
echo "Starting server..."
exec gunicorn main:app --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
