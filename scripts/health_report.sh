#!/usr/bin/env bash
#
# Rapport de santé quotidien du serveur, envoyé par mail via msmtp.
#
# Vérifie : démon Docker, conteneur, réponse HTTP, emplacement et contenu de
# la base, fraîcheur des backups, disque/RAM, erreurs applicatives des
# dernières 24h. Le sujet du mail passe en "ALERTE" dès qu'un point est KO.
#
# Usage :
#     bash scripts/health_report.sh destinataire@exemple.fr   # envoie le mail
#     bash scripts/health_report.sh --dry-run                  # affiche seulement
#
# À lancer via la crontab ROOT (accès docker nécessaire), ex. tous les jours à 7h UTC :
#     0 7 * * * cd /home/ubuntu/armoire_commune/armoire_commune_backend && \
#         bash scripts/health_report.sh destinataire@exemple.fr >> ../db_backups/health.log 2>&1

set -u

# cron a un PATH minimal : sans /snap/bin, "docker" est introuvable avec le snap
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin"

cd "$(dirname "$0")/.." || exit 1

MAIL_TO="${1:-}"
if [ -z "$MAIL_TO" ]; then
    echo "Usage : $0 destinataire@exemple.fr | --dry-run" >&2
    exit 1
fi

CONTAINER="armoire-app"
DB_PATH="data/database.db"
BACKUP_DIR="../db_backups"
BACKUP_MAX_AGE_H=2
DISK_MAX_PCT=85

PROBLEMS=()
problem() { PROBLEMS+=("$1"); }

# --- Docker -----------------------------------------------------------------
if systemctl is-active --quiet docker 2>/dev/null; then
    docker_service="actif (docker)"
elif systemctl is-active --quiet snap.docker.dockerd 2>/dev/null; then
    docker_service="actif (snap.docker.dockerd)"
else
    docker_service="ARRÊTÉ"
    problem "Démon Docker arrêté"
fi

container_status=$(docker inspect -f '{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo "introuvable")
container_started=$(docker inspect -f '{{.State.StartedAt}}' "$CONTAINER" 2>/dev/null | cut -c1-19)
container_restarts=$(docker inspect -f '{{.RestartCount}}' "$CONTAINER" 2>/dev/null || echo "?")
[ "$container_status" = "running" ] || problem "Conteneur $CONTAINER : $container_status"

# La base doit être sur le bind mount /data, sinon elle disparaît au prochain rebuild
container_db_url=$(docker exec "$CONTAINER" printenv DATABASE_URL 2>/dev/null || echo "?")
case "$container_db_url" in
    sqlite:////data/*) ;;
    *) problem "DATABASE_URL du conteneur hors de /data : $container_db_url" ;;
esac

# --- HTTP -------------------------------------------------------------------
http_result=$(curl -s -o /dev/null -w '%{http_code} %{time_total}s' --max-time 10 http://localhost/ 2>/dev/null)
http_code=${http_result%% *}
[ "$http_code" = "200" ] || problem "API ne répond pas correctement (HTTP ${http_code:-aucune réponse})"

# --- Base de données ----------------------------------------------------------
if [ -s "$DB_PATH" ]; then
    db_size=$(du -h "$DB_PATH" | cut -f1)
    db_stats=$(python3 - "$DB_PATH" <<'EOF' 2>&1
import sqlite3
import sys
from datetime import datetime

conn = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)


def count(sql, *params):
    return conn.execute(sql, params).fetchone()[0]


now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
print("  Utilisateurs          : {}".format(count('SELECT COUNT(*) FROM "user"')))
print(f"  Objets                : {count('SELECT COUNT(*) FROM objet')}")
print("  Réservations actives  : {}".format(count(
    "SELECT COUNT(*) FROM reservation WHERE status IN (?, ?, ?, ?, ?)",
    "en_preparation", "mis_a_disposition", "retire", "restitue", "en_verification")))
print("  Réservations en retard: {}".format(count(
    "SELECT COUNT(*) FROM reservation WHERE status IN (?, ?, ?) AND date_fin < ?",
    "en_preparation", "mis_a_disposition", "retire", now)))
print(f"  Réservations totales  : {count('SELECT COUNT(*) FROM reservation')}")
EOF
    ) || problem "Lecture de la base impossible"
else
    db_size="-"
    db_stats="  (base absente de $DB_PATH)"
    problem "Base absente de $DB_PATH"
fi

# --- Backups ----------------------------------------------------------------
latest_backup=$(ls -1t "$BACKUP_DIR"/database_*.db 2>/dev/null | head -n 1)
backup_count=$(ls -1 "$BACKUP_DIR"/database_*.db 2>/dev/null | wc -l)
if [ -n "$latest_backup" ]; then
    backup_age_h=$(( ( $(date +%s) - $(stat -c %Y "$latest_backup") ) / 3600 ))
    backup_line="$(basename "$latest_backup") (il y a ${backup_age_h}h, $backup_count fichiers)"
    [ "$backup_age_h" -le "$BACKUP_MAX_AGE_H" ] || problem "Dernier backup vieux de ${backup_age_h}h"
else
    backup_line="AUCUN"
    problem "Aucun backup dans $BACKUP_DIR"
fi

# --- Système ----------------------------------------------------------------
disk_pct=$(df --output=pcent / | tail -n 1 | tr -dc '0-9')
[ "${disk_pct:-0}" -lt "$DISK_MAX_PCT" ] || problem "Disque plein à ${disk_pct}%"
mem_line=$(free -h | awk '/^Mem:/ {print $3 " utilisés / " $2}')
reboot_line="non"
[ -f /var/run/reboot-required ] && reboot_line="OUI (mises à jour noyau en attente)"

# --- Logs applicatifs des dernières 24h ---------------------------------------
logs_24h=$(docker logs --since 24h "$CONTAINER" 2>&1)
error_count=$(printf '%s\n' "$logs_24h" | grep -c -E "Traceback|\[ERROR\]|\[CRITICAL\]")
[ "$error_count" -eq 0 ] || problem "$error_count erreur(s) dans les logs applicatifs (24h)"
last_errors=$(printf '%s\n' "$logs_24h" | grep -E -A3 "Traceback|\[ERROR\]|\[CRITICAL\]" | tail -n 20)

# --- Rapport ----------------------------------------------------------------
# Sujet en ASCII : les accents dans un en-tête de mail demandent un encodage RFC 2047
if [ ${#PROBLEMS[@]} -eq 0 ]; then
    subject="[Armoire] OK - rapport du $(date +%d/%m/%Y)"
    status_block="Tout est OK."
else
    subject="[Armoire] ALERTE ${#PROBLEMS[@]} probleme(s) - $(date +%d/%m/%Y)"
    status_block="PROBLÈMES DÉTECTÉS :"
    for p in "${PROBLEMS[@]}"; do status_block+=$'\n'"  - $p"; done
fi

body=$(cat <<EOF
$status_block

== Service ==
  Démon Docker          : $docker_service
  Conteneur             : $container_status (démarré le ${container_started:-?} UTC, $container_restarts redémarrage(s))
  API http://localhost/ : ${http_result:-aucune réponse}
  DATABASE_URL          : $container_db_url

== Données ==
  Base                  : $DB_PATH ($db_size)
$db_stats
  Dernier backup        : $backup_line

== Système ==
  Uptime                : $(uptime -p)
  Charge (1/5/15 min)   : $(cut -d' ' -f1-3 /proc/loadavg)
  RAM                   : $mem_line
  Disque /              : ${disk_pct}% utilisé
  Redémarrage requis    : $reboot_line

== Logs (24h) ==
  Erreurs applicatives  : $error_count
$last_errors
EOF
)

if [ "$MAIL_TO" = "--dry-run" ]; then
    printf 'Subject: %s\n\n%s\n' "$subject" "$body"
    exit 0
fi

{
    echo "To: $MAIL_TO"
    echo "Subject: $subject"
    echo "Content-Type: text/plain; charset=UTF-8"
    echo
    echo "$body"
} | msmtp "$MAIL_TO" && echo "[health] $(date '+%F %T') rapport envoyé à $MAIL_TO (${#PROBLEMS[@]} problème(s))"
