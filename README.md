# armoire_commune_backend
l'application de partage d'objet à Dijon !

## Installation et Lancement

1. Installer les dépendances :
   ```bash
   pip install -r requirements.txt
   ```

2. Initialiser la base de données (exemple) :
   ```bash
   python seed.py
   ```

3. Lancer le serveur :
   ```bash
   uvicorn main:app --reload
   ```

## Documentation API

Voici la liste des routes disponibles avec des exemples d'utilisation via `curl`.

### Authentification

#### Inscription
```bash
curl -X POST "http://127.0.0.1:8000/auth/signup" \
-H "Content-Type: application/json" \
-d '{
  "nom": "Dupont",
  "prenom": "Jean",
  "email": "jean@exemple.com",
  "password": "monSuperMotDePasse"
}'
```

#### Connexion (Login)
Récupère un token d'accès (JWT).
```bash
curl -X POST "http://127.0.0.1:8000/auth/login" \
-H "Content-Type: application/x-www-form-urlencoded" \
-d "username=jean@exemple.com&password=monSuperMotDePasse"
```

### Utilisateurs (Admin)

#### Promouvoir un administrateur
Nécessite un token Admin.
```bash
curl -X PUT "http://127.0.0.1:8000/admin/users/2/promote?is_admin=true" \
-H "Authorization: Bearer VOTRE_TOKEN_ADMIN"
```

### Métadonnées (Admin)

#### Créer un Tag
```bash
curl -X POST "http://127.0.0.1:8000/admin_meta/tags" \
-H "Authorization: Bearer VOTRE_TOKEN_ADMIN" \
-H "Content-Type: application/json" \
-d '{"nom": "Bricolage"}'
```

#### Lister les Tags (Public)
```bash
curl -X GET "http://127.0.0.1:8000/admin_meta/tags"
```

#### Créer un Lieu
```bash
curl -X POST "http://127.0.0.1:8000/admin_meta/lieux" \
-H "Authorization: Bearer VOTRE_TOKEN_ADMIN" \
-H "Content-Type: application/json" \
-d '{
  "nom": "La Ressourcerie",
  "lat": 47.3220,
  "long": 5.0415,
  "adresse": "123 Rue de Dijon"
}'
```

#### Créer un Consommable
```bash
curl -X POST "http://127.0.0.1:8000/admin_meta/consommables" \
-H "Authorization: Bearer VOTRE_TOKEN_ADMIN" \
-H "Content-Type: application/json" \
-d '{
  "nom": "Vis à bois",
  "description": "Boite de 50",
  "quantite": 100,
  "prix": 5.50
}'
```

### Objets

#### Créer un Objet (Admin)
```bash
curl -X POST "http://127.0.0.1:8000/objets" \
-H "Authorization: Bearer VOTRE_TOKEN_ADMIN" \
-H "Content-Type: application/json" \
-d '{
  "nom": "Perceuse à percussion",
  "description": "Puissante, filaire",
  "quantite": 2,
  "tag_id": 1,
  "consommable_ids": [1],
  "disponibilite_globale": true
}'
```

#### Lister les objets (Public)
Filtres disponibles : `nom`, `tag_id`, `available` (bool).
```bash
# Tous les objets
curl -X GET "http://127.0.0.1:8000/objets"

# Objets disponibles uniquement (vérifie le stock vs réservations en cours)
curl -X GET "http://127.0.0.1:8000/objets?available=true"
```

#### Changer la disponibilité technique d'un objet (Admin)
Pour marquer un objet comme cassé/en réparation.
```bash
curl -X PUT "http://127.0.0.1:8000/admin/objets/1/available?available=false" \
-H "Authorization: Bearer VOTRE_TOKEN_ADMIN"
```

### Réservations

#### Créer une réservation (User)
Réserve pour 7 jours à partir de la date donnée.
```bash
curl -X POST "http://127.0.0.1:8000/reservations" \
-H "Authorization: Bearer VOTRE_TOKEN_USER" \
-H "Content-Type: application/json" \
-d '{
  "objet_id": 1,
  "lieu_id": 1,
  "date_debut": "2023-10-27T10:00:00"
}'
```

#### Mes réservations (User)
```bash
curl -X GET "http://127.0.0.1:8000/reservations/me" \
-H "Authorization: Bearer VOTRE_TOKEN_USER"
```

#### Toutes les réservations (Admin)
```bash
curl -X GET "http://127.0.0.1:8000/admin/reservations" \
-H "Authorization: Bearer VOTRE_TOKEN_ADMIN"
```

#### Retourner un objet (Admin)
Marque la réservation comme terminée.
```bash
curl -X POST "http://127.0.0.1:8000/admin/reservations/1/return" \
-H "Authorization: Bearer VOTRE_TOKEN_ADMIN"
```
