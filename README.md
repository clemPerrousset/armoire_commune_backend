# L'Armoire Commune — Backend API

API REST pour la gestion du partage d'objets communautaires à Dijon.

## Installation et déploiement

### Docker (recommandé)

```bash
cp .env.example .env        # configurer SECRET_KEY et superUserPassword
docker-compose up -d --build
```

L'API est exposée sur le port **80** : `http://localhost`

Les données sont persistées dans `./data` (bind mount — survit à un `docker-compose up -d --build`, seule l'image applicative est reconstruite).

Au démarrage, `entrypoint.sh` exécute dans l'ordre :
1. **Restauration automatique** — si `./data/database.db` est absent ou vide et qu'un backup existe dans `../db_backups`, le plus récent est restauré avant tout.
2. **Migration additive** (`migrate.py`) — ajoute les tables/colonnes manquantes déclarées dans les modèles, sans jamais supprimer ni renommer de données. Évite qu'un changement de modèle (ex: nouveau champ) fasse planter le démarrage sur une base déjà peuplée.
3. **Seed** (`seed.py`) — no-op si un admin existe déjà.

### Sauvegardes automatiques (hors docker)

Un script de sauvegarde à chaud (`scripts/backup_db.py`, via `sqlite3.Connection.backup()`, cohérent même en écriture concurrente) écrit des snapshots horodatés dans `../db_backups` — **en dehors** du dossier `./data` et du repo git, pour survivre à une suppression accidentelle de l'un ou l'autre. Rétention par défaut : 7 jours.

À configurer une fois sur le serveur via `crontab -e` :

```cron
0 * * * * cd /home/ubuntu/armoire_commune/armoire_commune_backend && /usr/bin/python3 scripts/backup_db.py >> ../db_backups/backup.log 2>&1
```

Coût négligeable pour une base de cette taille (quelques ms, quelques Ko/backup).

### Développement local

```bash
pip install -r requirements.txt
python seed.py          # initialise la BDD avec des données de test
uvicorn main:app --reload
```

L'API est accessible sur `http://127.0.0.1:8000`.  
La documentation interactive est disponible sur `/docs`.

---

## Cycle de réservation

- **Retrait** : jeudi ou vendredi au point relais
- **Retour** : lundi, mardi ou mercredi de la semaine suivante
- **Durée** : 1, 2 ou 3 semaines (le champ `nb_semaines` est obligatoire)
- `date_debut` est automatiquement ajustée au **prochain jeudi**
- `date_fin` est automatiquement calculée : mercredi à 22h00 de la dernière semaine

```
Jeudi semaine N  ──────────────────────►  Mercredi semaine N+nb_semaines à 22h00
    Retrait                                            Retour
```

---

## Rôles

| Rôle | Capacités |
|---|---|
| **Utilisateur** | Consulter, réserver, favoris, historique |
| **Point Relais** | + Retrait et retour d'objets (périmètre de ses lieux) |
| **Admin** | Accès complet à toutes les routes |

---

## Tests

```bash
pytest -v
```

Les tests utilisent une base SQLite en mémoire (`conftest.py`). Chaque test repart d'un état vide.

Fichiers de tests :
- `test_app.py` — flux complet (auth, création, réservation, retour, recherche)
- `test_reservations.py` — cycle jeudi, multi-semaines, chevauchement, annulation, historique, filtres admin
- `test_late_returns.py` — gestion des retards (extension / alerte)
- `test_auth.py`, `test_favoris.py`, `test_historique.py`, `test_lieux.py`, `test_tags.py`, `test_point_relais.py`, `test_super_promote.py`
- `test_migrate.py` — migration additive (colonnes manquantes ajoutées + backfill du DEFAULT, idempotence)

---

## Référence API

> Les exemples utilisent `http://127.0.0.1:8000` (local). Remplacez par `http://localhost` en Docker.

### Authentification

```bash
# Inscription
curl -X POST "http://127.0.0.1:8000/auth/signup" \
  -H "Content-Type: application/json" \
  -d '{"nom":"Dupont","prenom":"Jean","email":"jean@exemple.com","password":"monPass"}'

# Connexion — retourne un JWT Bearer
curl -X POST "http://127.0.0.1:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=jean@exemple.com&password=monPass"
```

### Profil utilisateur

```bash
curl "http://127.0.0.1:8000/users/me" -H "Authorization: Bearer TOKEN"

# Favoris
curl "http://127.0.0.1:8000/users/favoris" -H "Authorization: Bearer TOKEN"
curl -X POST "http://127.0.0.1:8000/users/favoris/1" -H "Authorization: Bearer TOKEN"
curl -X DELETE "http://127.0.0.1:8000/users/favoris/1" -H "Authorization: Bearer TOKEN"
```

### Objets

```bash
# Liste (sans filtre = tous les objets, y compris réservés)
curl "http://127.0.0.1:8000/objets"

# Uniquement disponibles la semaine prochaine
curl "http://127.0.0.1:8000/objets?available=true"

# Filtres cumulables : nom (recherche partielle), tag_id, available, date_check
curl "http://127.0.0.1:8000/objets?nom=perceuse&tag_id=2&available=true"

# Détail
curl "http://127.0.0.1:8000/objets/1"

# Créer (admin) — sans champ quantite
curl -X POST "http://127.0.0.1:8000/objets" \
  -H "Authorization: Bearer TOKEN_ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"nom":"Perceuse","description":"Filaire","tag_id":1,"consommable_ids":[]}'

# Supprimer (admin) — refusé si réservation active ou en cours
curl -X DELETE "http://127.0.0.1:8000/admin/objets/1" -H "Authorization: Bearer TOKEN_ADMIN"

# Marquer indisponible (maintenance)
curl -X PUT "http://127.0.0.1:8000/admin/objets/1/available?available=false" \
  -H "Authorization: Bearer TOKEN_ADMIN"

# Effacer une alerte de retard
curl -X POST "http://127.0.0.1:8000/admin/objets/1/clear-alert" \
  -H "Authorization: Bearer TOKEN_ADMIN"

# Objets en alerte (admin)
curl "http://127.0.0.1:8000/admin/objets/alerts" -H "Authorization: Bearer TOKEN_ADMIN"
```

### Réservations

```bash
# Créer (date_debut est ajustée au prochain jeudi automatiquement)
curl -X POST "http://127.0.0.1:8000/reservations" \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"objet_id":1,"lieu_id":1,"date_debut":"2025-01-06T10:00:00","nb_semaines":2}'

# Mes réservations actives / en cours (avec objet et lieu imbriqués)
curl "http://127.0.0.1:8000/reservations/me" -H "Authorization: Bearer TOKEN"

# Historique : réservations terminées (avec objet et lieu imbriqués)
curl "http://127.0.0.1:8000/reservations/historique" -H "Authorization: Bearer TOKEN"

# Annuler une réservation (statut active seulement)
curl -X POST "http://127.0.0.1:8000/reservations/1/cancel" -H "Authorization: Bearer TOKEN"

# Calendrier d'un objet (semaines réservées)
curl "http://127.0.0.1:8000/reservations/objet/1"

# Toutes les réservations — filtre optionnel par statut (admin)
curl "http://127.0.0.1:8000/admin/reservations?status=active" -H "Authorization: Bearer TOKEN_ADMIN"
# statuts disponibles : active, en_cours, terminee, annulee

# Marquer comme retourné (admin)
curl -X POST "http://127.0.0.1:8000/admin/reservations/1/return" \
  -H "Authorization: Bearer TOKEN_ADMIN"

# Vérifier les retards (admin)
curl -X POST "http://127.0.0.1:8000/admin/reservations/check-late" \
  -H "Authorization: Bearer TOKEN_ADMIN"
```

### Métadonnées (tags, lieux, consommables)

```bash
# Tags
curl "http://127.0.0.1:8000/admin_meta/tags"
curl -X POST "http://127.0.0.1:8000/admin_meta/tags" \
  -H "Authorization: Bearer TOKEN_ADMIN" -d '{"nom":"Jardinage"}'
curl -X DELETE "http://127.0.0.1:8000/admin_meta/tags/1" -H "Authorization: Bearer TOKEN_ADMIN"

# Lieux (avec champ description pour les horaires)
curl "http://127.0.0.1:8000/admin_meta/lieux"
curl -X POST "http://127.0.0.1:8000/admin_meta/lieux" \
  -H "Authorization: Bearer TOKEN_ADMIN" \
  -H "Content-Type: application/json" \
  -d '{"nom":"LAC","lat":47.32,"long":5.04,"adresse":"1 rue LAC","description":"Lun-Ven 9h-18h"}'
curl -X DELETE "http://127.0.0.1:8000/admin_meta/lieux/1" -H "Authorization: Bearer TOKEN_ADMIN"

# Consommables
curl "http://127.0.0.1:8000/admin_meta/consommables"
curl -X POST "http://127.0.0.1:8000/admin_meta/consommables" \
  -H "Authorization: Bearer TOKEN_ADMIN" \
  -d '{"nom":"Piles AA","description":"Pack 4","quantite":10,"prix":3.50}'
```

### Gestion des utilisateurs (admin)

```bash
# Promouvoir admin
curl -X PUT "http://127.0.0.1:8000/admin/users/2/promote?is_admin=true" \
  -H "Authorization: Bearer TOKEN_ADMIN"

# Promouvoir point relais
curl -X PUT "http://127.0.0.1:8000/admin/users/2/promote-point-relais?is_point_relais=true" \
  -H "Authorization: Bearer TOKEN_ADMIN"

# Assigner un lieu à un point relais
curl -X POST "http://127.0.0.1:8000/admin/users/2/lieux/1" \
  -H "Authorization: Bearer TOKEN_ADMIN"

# Super-promote (bootstrap / urgence) — par email
curl -X POST "http://127.0.0.1:8000/admin/users/super-promote" \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"SUPER_USER_PASSWORD","is_admin":true}'

# Lister les admins (bootstrap / urgence)
curl -X POST "http://127.0.0.1:8000/admin/users/super-list-admins" \
  -H "Content-Type: application/json" \
  -d '{"password":"SUPER_USER_PASSWORD"}'
```

### Opérations Point Relais (scan QR)

```bash
# Retrait : réservation active → en_cours
curl -X POST "http://127.0.0.1:8000/objets/1/retirer" \
  -H "Authorization: Bearer TOKEN_POINT_RELAIS"

# Retour : réservation → terminee, mise à jour du lieu physique
curl -X POST "http://127.0.0.1:8000/objets/1/retourner?lieu_id=1" \
  -H "Authorization: Bearer TOKEN_POINT_RELAIS"
```

---

## Modèles de données

### Objet
| Champ | Type | Description |
|---|---|---|
| `nom` | str | Nom de l'objet |
| `description` | str | Description |
| `image` | str? | URL ou base64 |
| `disponibilite_globale` | bool | False = en maintenance/panne |
| `alert` | bool | True = retard avec conflit de réservation |
| `tag_id` | int? | Catégorie |
| `current_lieu_id` | int? | Localisation physique actuelle |

### Reservation
| Champ | Type | Description |
|---|---|---|
| `date_debut` | datetime | Jeudi de début (auto-ajusté) |
| `date_fin` | datetime | Mercredi à 22h00 de fin |
| `nb_semaines` | int | Durée : 1, 2 ou 3 |
| `status` | str | `active` / `en_cours` / `terminee` / `annulee` |
| `objet` | ObjetBrief | Objet imbriqué dans les réponses |
| `lieu` | LieuBrief | Lieu imbriqué dans les réponses |

### Lieu
| Champ | Type | Description |
|---|---|---|
| `nom` | str | Nom du point relais |
| `adresse` | str | Adresse postale |
| `lat` / `long` | float | Coordonnées GPS |
| `description` | str? | Horaires d'ouverture ou infos complémentaires |
