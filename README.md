# armoire_commune_backend
l'application de partage d'objet à Dijon !

## Installation et Déploiement

### Déploiement avec Docker (Recommandé)

Cette méthode est recommandée pour le déploiement sur serveur ou pour lancer l'application rapidement sans gérer les dépendances Python manuellement.

**Prérequis :**
- Docker
- Docker Compose

**Étapes :**

1.  **Configurer les variables d'environnement** :
    Copiez le fichier d'exemple et modifiez-le si nécessaire (notamment la `SECRET_KEY`).
    ```bash
    cp .env.example .env
    ```

2.  **Lancer l'application** :
    ```bash
    docker-compose up -d --build
    ```
    L'option `-d` lance le conteneur en arrière-plan.

3.  **Accéder à l'application** :
    L'API sera accessible sur le port **80** de votre machine : `http://localhost` (ou l'IP de votre serveur).

    *Note : Le conteneur initialise automatiquement la base de données au démarrage.*

**Persistance des données :**
Les données de la base de données sont stockées de manière persistante dans le dossier `./data` à la racine du projet.

---

### Développement Local (Sans Docker)

Pour le développement ou si vous ne souhaitez pas utiliser Docker.

1.  **Installer les dépendances** :
    ```bash
    pip install -r requirements.txt
    ```

2.  **Initialiser la base de données** :
    ```bash
    python seed.py
    ```

3.  **Lancer le serveur** :
    ```bash
    uvicorn main:app --reload
    ```
    L'application sera accessible sur `http://127.0.0.1:8000`.

## Documentation API

**Note importante concernant les ports :**
Les exemples ci-dessous utilisent `http://127.0.0.1:8000`, ce qui correspond à l'installation locale (sans Docker).
**Si vous utilisez Docker**, l'application est exposée sur le port **80**. Vous devez donc retirer `:8000` des URLs (exemple : `http://127.0.0.1/auth/signup`).

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

#### Promouvoir un administrateur (Super User)
Utilise le mot de passe super utilisateur défini dans les variables d'environnement (`superUserPassword`).
Ceci est utile pour le bootstrapping ou l'accès d'urgence.

```bash
curl -X POST "http://127.0.0.1:8000/admin/users/2/super-promote" \
-H "Content-Type: application/json" \
-d '{
  "password": "VOTRE_SUPER_USER_PASSWORD",
  "is_admin": true
}'
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
