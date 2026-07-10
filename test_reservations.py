"""
Tests pour le système de réservation :
- Cycle jeudi→mercredi
- Réservations multi-semaines (1, 2, 3)
- Blocage de chevauchement
- Annulation
- Calendrier (réservations par objet)
- Historique des réservations terminées
- Filtre statut admin
"""
import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta

from models import User, Lieu, Tag, Objet, Reservation
from auth import get_password_hash

from main import app
client = TestClient(app)


def _create_base_data(session):
    """Crée admin, user, lieu et objet de base, retourne leurs instances."""
    admin = User(nom="Admin", prenom="A", email="admin@test.com", password_hash=get_password_hash("admin"), is_admin=True)
    user = User(nom="User", prenom="B", email="user@test.com", password_hash=get_password_hash("user"))
    lieu = Lieu(nom="LieuTest", lat=0.0, long=0.0, adresse="1 rue Test")
    objet = Objet(nom="Perceuse", description="Perceuse électrique")
    for obj in (admin, user, lieu, objet):
        session.add(obj)
    session.commit()
    for obj in (admin, user, lieu, objet):
        session.refresh(obj)
    return admin, user, lieu, objet


def _login(email, password):
    res = client.post("/auth/login", data={"username": email, "password": password})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# ---------------------------------------------------------------
# 1. Cycle jeudi
# ---------------------------------------------------------------

def test_date_ajustee_au_jeudi(session):
    """Une date quelconque est automatiquement décalée au prochain jeudi."""
    _, _, lieu, objet = _create_base_data(session)
    headers = _login("user@test.com", "user")

    # On envoie un lundi 2025-01-06 → doit être ajusté au jeudi 2025-01-09
    lundi = datetime(2025, 1, 6, 10, 0)
    res = client.post("/reservations", json={
        "objet_id": objet.id,
        "lieu_id": lieu.id,
        "date_debut": lundi.isoformat(),
        "nb_semaines": 1,
    }, headers=headers)
    assert res.status_code == 200, res.json()
    data = res.json()
    assert data["date_debut"].startswith("2025-01-09"), f"Attendu 2025-01-09, obtenu {data['date_debut']}"


def test_date_jeudi_reste_jeudi(session):
    """Un jeudi envoyé reste le même jeudi."""
    _, _, lieu, objet = _create_base_data(session)
    headers = _login("user@test.com", "user")

    jeudi = datetime(2025, 1, 9, 10, 0)  # C'est un jeudi
    res = client.post("/reservations", json={
        "objet_id": objet.id,
        "lieu_id": lieu.id,
        "date_debut": jeudi.isoformat(),
        "nb_semaines": 1,
    }, headers=headers)
    assert res.status_code == 200, res.json()
    assert res.json()["date_debut"].startswith("2025-01-09")


def test_date_fin_une_semaine(session):
    """date_fin = mercredi suivant à 22h00 (jeudi + 6 jours)."""
    _, _, lieu, objet = _create_base_data(session)
    headers = _login("user@test.com", "user")

    jeudi = datetime(2025, 1, 9, 10, 0)
    res = client.post("/reservations", json={
        "objet_id": objet.id,
        "lieu_id": lieu.id,
        "date_debut": jeudi.isoformat(),
        "nb_semaines": 1,
    }, headers=headers)
    assert res.status_code == 200, res.json()
    data = res.json()
    # Jeudi 9 janvier + 6 jours = mercredi 15 janvier 22:00
    assert data["date_fin"] == "2025-01-15T22:00:00", data["date_fin"]


# ---------------------------------------------------------------
# 2. Multi-semaines
# ---------------------------------------------------------------

def test_deux_semaines(session):
    """Une réservation de 2 semaines s'étend jusqu'au mercredi 22h de la 2e semaine."""
    _, _, lieu, objet = _create_base_data(session)
    headers = _login("user@test.com", "user")

    jeudi = datetime(2025, 1, 9, 10, 0)
    res = client.post("/reservations", json={
        "objet_id": objet.id,
        "lieu_id": lieu.id,
        "date_debut": jeudi.isoformat(),
        "nb_semaines": 2,
    }, headers=headers)
    assert res.status_code == 200, res.json()
    data = res.json()
    assert data["nb_semaines"] == 2
    # Jeudi 9 jan + 13 jours = mercredi 22 janvier 22:00
    assert data["date_fin"] == "2025-01-22T22:00:00", data["date_fin"]


def test_trois_semaines(session):
    _, _, lieu, objet = _create_base_data(session)
    headers = _login("user@test.com", "user")

    jeudi = datetime(2025, 1, 9, 10, 0)
    res = client.post("/reservations", json={
        "objet_id": objet.id,
        "lieu_id": lieu.id,
        "date_debut": jeudi.isoformat(),
        "nb_semaines": 3,
    }, headers=headers)
    assert res.status_code == 200, res.json()
    data = res.json()
    assert data["nb_semaines"] == 3
    # Jeudi 9 jan + 20 jours = mercredi 29 janvier 22:00
    assert data["date_fin"] == "2025-01-29T22:00:00", data["date_fin"]


def test_nb_semaines_invalide(session):
    _, _, lieu, objet = _create_base_data(session)
    headers = _login("user@test.com", "user")

    res = client.post("/reservations", json={
        "objet_id": objet.id,
        "lieu_id": lieu.id,
        "date_debut": datetime(2025, 1, 9).isoformat(),
        "nb_semaines": 5,
    }, headers=headers)
    assert res.status_code == 400


# ---------------------------------------------------------------
# 3. Blocage de chevauchement
# ---------------------------------------------------------------

def test_chevauchement_bloque(session):
    """Deux réservations sur la même semaine sont refusées."""
    admin, _, lieu, objet = _create_base_data(session)
    user2 = User(nom="User2", prenom="C", email="user2@test.com", password_hash=get_password_hash("user2"))
    session.add(user2)
    session.commit()

    headers1 = _login("user@test.com", "user")
    headers2 = _login("user2@test.com", "user2")

    jeudi = datetime(2025, 1, 9, 10, 0)
    payload = {"objet_id": objet.id, "lieu_id": lieu.id, "date_debut": jeudi.isoformat(), "nb_semaines": 1}

    res1 = client.post("/reservations", json=payload, headers=headers1)
    assert res1.status_code == 200

    res2 = client.post("/reservations", json=payload, headers=headers2)
    assert res2.status_code == 400


def test_deux_semaines_bloque_semaine_incluse(session):
    """Une réservation 1 semaine S2 est refusée si l'objet est déjà réservé 2 semaines à partir de S1."""
    _, _, lieu, objet = _create_base_data(session)
    user2 = User(nom="User2", prenom="C", email="user2@test.com", password_hash=get_password_hash("user2"))
    session.add(user2)
    session.commit()

    headers1 = _login("user@test.com", "user")
    headers2 = _login("user2@test.com", "user2")

    # User1 réserve 2 semaines à partir du 9 jan (→ jusqu'au 22 jan)
    res1 = client.post("/reservations", json={
        "objet_id": objet.id, "lieu_id": lieu.id,
        "date_debut": datetime(2025, 1, 9).isoformat(), "nb_semaines": 2,
    }, headers=headers1)
    assert res1.status_code == 200

    # User2 essaie de réserver la semaine du 16 jan → chevauche
    res2 = client.post("/reservations", json={
        "objet_id": objet.id, "lieu_id": lieu.id,
        "date_debut": datetime(2025, 1, 16).isoformat(), "nb_semaines": 1,
    }, headers=headers2)
    assert res2.status_code == 400


def test_semaine_suivante_disponible(session):
    """Une réservation est possible sur une semaine non chevauchante."""
    _, _, lieu, objet = _create_base_data(session)
    user2 = User(nom="User2", prenom="C", email="user2@test.com", password_hash=get_password_hash("user2"))
    session.add(user2)
    session.commit()

    headers1 = _login("user@test.com", "user")
    headers2 = _login("user2@test.com", "user2")

    # User1 : semaine du 9 jan
    client.post("/reservations", json={
        "objet_id": objet.id, "lieu_id": lieu.id,
        "date_debut": datetime(2025, 1, 9).isoformat(), "nb_semaines": 1,
    }, headers=headers1)

    # User2 : semaine du 16 jan → ok
    res2 = client.post("/reservations", json={
        "objet_id": objet.id, "lieu_id": lieu.id,
        "date_debut": datetime(2025, 1, 16).isoformat(), "nb_semaines": 1,
    }, headers=headers2)
    assert res2.status_code == 200


# ---------------------------------------------------------------
# 4. Annulation
# ---------------------------------------------------------------

def test_annulation_par_user(session):
    _, _, lieu, objet = _create_base_data(session)
    headers = _login("user@test.com", "user")

    res = client.post("/reservations", json={
        "objet_id": objet.id, "lieu_id": lieu.id,
        "date_debut": datetime(2025, 1, 9).isoformat(), "nb_semaines": 1,
    }, headers=headers)
    assert res.status_code == 200
    reservation_id = res.json()["id"]

    cancel = client.post(f"/reservations/{reservation_id}/cancel", headers=headers)
    assert cancel.status_code == 200

    # Après annulation, l'objet doit être dispo à nouveau
    res2 = client.get(f"/objets?available=true&date_check={datetime(2025, 1, 6).isoformat()}")
    assert res2.status_code == 200
    assert any(o["id"] == objet.id for o in res2.json())


def test_annulation_double_refusee(session):
    _, _, lieu, objet = _create_base_data(session)
    headers = _login("user@test.com", "user")

    res = client.post("/reservations", json={
        "objet_id": objet.id, "lieu_id": lieu.id,
        "date_debut": datetime(2025, 1, 9).isoformat(), "nb_semaines": 1,
    }, headers=headers)
    reservation_id = res.json()["id"]

    client.post(f"/reservations/{reservation_id}/cancel", headers=headers)
    # Deuxième annulation doit échouer
    res2 = client.post(f"/reservations/{reservation_id}/cancel", headers=headers)
    assert res2.status_code == 400


def test_annulation_autre_user_refusee(session):
    _, _, lieu, objet = _create_base_data(session)
    user2 = User(nom="U2", prenom="X", email="user2@test.com", password_hash=get_password_hash("user2"))
    session.add(user2)
    session.commit()

    headers1 = _login("user@test.com", "user")
    headers2 = _login("user2@test.com", "user2")

    res = client.post("/reservations", json={
        "objet_id": objet.id, "lieu_id": lieu.id,
        "date_debut": datetime(2025, 1, 9).isoformat(), "nb_semaines": 1,
    }, headers=headers1)
    reservation_id = res.json()["id"]

    cancel = client.post(f"/reservations/{reservation_id}/cancel", headers=headers2)
    assert cancel.status_code == 403


# ---------------------------------------------------------------
# 5. Données réservation enrichies (objet + lieu dans la réponse)
# ---------------------------------------------------------------

def test_reservation_contient_objet_et_lieu(session):
    """La réponse de création doit inclure les objets et lieux imbriqués."""
    _, _, lieu, objet = _create_base_data(session)
    headers = _login("user@test.com", "user")

    res = client.post("/reservations", json={
        "objet_id": objet.id, "lieu_id": lieu.id,
        "date_debut": datetime(2025, 1, 9).isoformat(), "nb_semaines": 1,
    }, headers=headers)
    assert res.status_code == 200, res.json()
    data = res.json()
    assert data["objet"]["nom"] == "Perceuse"
    assert data["lieu"]["nom"] == "LieuTest"


def test_mes_reservations_contient_objet_et_lieu(session):
    _, _, lieu, objet = _create_base_data(session)
    headers = _login("user@test.com", "user")

    client.post("/reservations", json={
        "objet_id": objet.id, "lieu_id": lieu.id,
        "date_debut": datetime(2025, 1, 9).isoformat(), "nb_semaines": 1,
    }, headers=headers)

    res = client.get("/reservations/me", headers=headers)
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["objet"]["nom"] == "Perceuse"
    assert res.json()[0]["lieu"]["nom"] == "LieuTest"


# ---------------------------------------------------------------
# 6. Calendrier objet
# ---------------------------------------------------------------

def test_calendrier_objet(session):
    _, _, lieu, objet = _create_base_data(session)
    headers = _login("user@test.com", "user")

    client.post("/reservations", json={
        "objet_id": objet.id, "lieu_id": lieu.id,
        "date_debut": datetime(2025, 1, 9).isoformat(), "nb_semaines": 1,
    }, headers=headers)

    res = client.get(f"/reservations/objet/{objet.id}")
    assert res.status_code == 200
    assert len(res.json()) == 1
    assert res.json()[0]["status"] == "active"


# ---------------------------------------------------------------
# 7. Historique réservations terminées
# ---------------------------------------------------------------

def test_historique_reservations_terminées(session):
    admin, user_obj, lieu, objet = _create_base_data(session)
    user_headers = _login("user@test.com", "user")
    admin_headers = _login("admin@test.com", "admin")

    # Créer une réservation et la terminer via admin
    res = client.post("/reservations", json={
        "objet_id": objet.id, "lieu_id": lieu.id,
        "date_debut": datetime(2025, 1, 9).isoformat(), "nb_semaines": 1,
    }, headers=user_headers)
    reservation_id = res.json()["id"]

    client.post(f"/admin/reservations/{reservation_id}/return", headers=admin_headers)

    # L'historique doit la contenir
    hist = client.get("/reservations/historique", headers=user_headers)
    assert hist.status_code == 200
    assert len(hist.json()) == 1
    assert hist.json()[0]["status"] == "terminee"

    # Mes réservations actives ne doit PAS la contenir
    active = client.get("/reservations/me", headers=user_headers)
    assert all(r["status"] != "terminee" for r in active.json())


# ---------------------------------------------------------------
# 8. Filtre statut admin
# ---------------------------------------------------------------

def test_filtre_statut_admin(session):
    admin, _, lieu, objet = _create_base_data(session)
    user2 = User(nom="U2", prenom="X", email="user2@test.com", password_hash=get_password_hash("user2"))
    session.add(user2)
    session.commit()

    user_headers = _login("user@test.com", "user")
    user2_headers = _login("user2@test.com", "user2")
    admin_headers = _login("admin@test.com", "admin")

    # Réservation 1 : semaine 1 → on l'annule
    res1 = client.post("/reservations", json={
        "objet_id": objet.id, "lieu_id": lieu.id,
        "date_debut": datetime(2025, 1, 9).isoformat(), "nb_semaines": 1,
    }, headers=user_headers)
    client.post(f"/reservations/{res1.json()['id']}/cancel", headers=user_headers)

    # Réservation 2 : semaine 2 → reste active
    client.post("/reservations", json={
        "objet_id": objet.id, "lieu_id": lieu.id,
        "date_debut": datetime(2025, 1, 16).isoformat(), "nb_semaines": 1,
    }, headers=user2_headers)

    res_all = client.get("/admin/reservations", headers=admin_headers)
    assert res_all.status_code == 200
    assert len(res_all.json()) == 2

    res_active = client.get("/admin/reservations?status=active", headers=admin_headers)
    assert len(res_active.json()) == 1
    assert res_active.json()[0]["status"] == "active"

    res_annulee = client.get("/admin/reservations?status=annulee", headers=admin_headers)
    assert len(res_annulee.json()) == 1
    assert res_annulee.json()[0]["status"] == "annulee"


# ---------------------------------------------------------------
# 9. Filtre disponibilité (fix bug "Tous" = défaut False)
# ---------------------------------------------------------------

def test_filtre_tous_affiche_objets_reserves(session):
    _, _, lieu, objet = _create_base_data(session)
    headers = _login("user@test.com", "user")

    client.post("/reservations", json={
        "objet_id": objet.id, "lieu_id": lieu.id,
        "date_debut": datetime(2025, 1, 9).isoformat(), "nb_semaines": 1,
    }, headers=headers)

    # Sans paramètre (= tous) → l'objet réservé doit apparaître
    res_tous = client.get("/objets")
    assert any(o["id"] == objet.id for o in res_tous.json())

    # available=true → l'objet réservé ne doit PAS apparaître pour cette semaine
    res_dispo = client.get(f"/objets?available=true&date_check={datetime(2025, 1, 6).isoformat()}")
    assert not any(o["id"] == objet.id for o in res_dispo.json())


# ---------------------------------------------------------------
# 10. Suppression objet
# ---------------------------------------------------------------

def test_delete_objet(session):
    _, _, _, objet = _create_base_data(session)
    admin_headers = _login("admin@test.com", "admin")

    res = client.delete(f"/admin/objets/{objet.id}", headers=admin_headers)
    assert res.status_code == 200

    res2 = client.get(f"/objets/{objet.id}")
    assert res2.status_code == 404


def test_delete_objet_avec_resa_active_bloque(session):
    _, _, lieu, objet = _create_base_data(session)
    user_headers = _login("user@test.com", "user")
    admin_headers = _login("admin@test.com", "admin")

    client.post("/reservations", json={
        "objet_id": objet.id, "lieu_id": lieu.id,
        "date_debut": datetime(2025, 1, 9).isoformat(), "nb_semaines": 1,
    }, headers=user_headers)

    res = client.delete(f"/admin/objets/{objet.id}", headers=admin_headers)
    assert res.status_code == 400


# ---------------------------------------------------------------
# 11. Description lieu
# ---------------------------------------------------------------

def test_lieu_avec_description(session):
    # Créer l'admin AVANT le login
    admin = User(nom="Admin", prenom="A", email="admin_lieu@test.com", password_hash=get_password_hash("admin"), is_admin=True)
    session.add(admin)
    session.commit()

    admin_headers = _login("admin_lieu@test.com", "admin")

    res = client.post("/admin_meta/lieux", json={
        "nom": "LAC", "lat": 47.3, "long": 5.0,
        "adresse": "1 rue LAC",
        "description": "Ouvert lun-ven 9h-18h",
    }, headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["description"] == "Ouvert lun-ven 9h-18h"
