"""Flux objets : scan QR par rôle, retrait/retour, vérification, maintenance, images, suppression."""
import io

import pytest
from PIL import Image
from sqlmodel import select

from auth import get_password_hash
from models import (
    Consommable, Lieu, Objet, ObjetConsommableLink, ObjetTagLink, Reservation, Tag, User,
    UserLieuLink, UserObjetFavorisLink, UserObjetHistoriqueLink,
)
from test_reservations import _create_base_data, _login, client

THURSDAY = "2030-01-03T10:00:00"


def _reserve(headers, lieu, objet, date=THURSDAY, n=1):
    r = client.post("/reservations", json={
        "objet_id": objet.id, "lieu_id": lieu.id, "date_debut": date, "nb_semaines": n,
    }, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _point_relais(session, email, lieux=()):
    pr = User(nom="PR", prenom="P", email=email, password_hash=get_password_hash("pr"), is_point_relais=True)
    session.add(pr)
    session.commit()
    session.refresh(pr)
    for lieu in lieux:
        session.add(UserLieuLink(user_id=pr.id, lieu_id=lieu.id))
    session.commit()
    return _login(email, "pr")


def _current_lieu(session, objet_id):
    session.expire_all()
    return session.get(Objet, objet_id).current_lieu_id


def _png_bytes(size=(2000, 1000)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- scan

def test_scan_cycle_complet_admin(session):
    admin, user, lieu, objet = _create_base_data(session)
    uh, ah = _login("user@test.com", "user"), _login("admin@test.com", "admin")
    res = _reserve(uh, lieu, objet)

    etapes = [
        ("en_preparation", "mis_a_disposition", lieu.id),
        ("mis_a_disposition", "retire", None),
        ("retire", "restitue", lieu.id),
        ("restitue", "en_verification", lieu.id),
    ]
    for ancien, nouveau, lieu_attendu in etapes:
        r = client.post(f"/objets/{objet.id}/scan", headers=ah)
        assert r.status_code == 200, r.text
        body = r.json()
        assert (body["ancien_statut"], body["nouveau_statut"]) == (ancien, nouveau)
        assert body["reservation_id"] == res["id"]
        assert body["verification_requise"] is (nouveau == "en_verification")
        assert _current_lieu(session, objet.id) == lieu_attendu

    # Plus rien à avancer par scan une fois en vérification
    assert client.post(f"/objets/{objet.id}/scan", headers=ah).status_code == 400


def test_scan_permissions_point_relais(session):
    admin, user, lieu, objet = _create_base_data(session)
    uh, ah = _login("user@test.com", "user"), _login("admin@test.com", "admin")
    prh = _point_relais(session, "pr@test.com", [lieu])
    pr_sans_lieu = _point_relais(session, "pr2@test.com")
    _reserve(uh, lieu, objet)
    scan = f"/objets/{objet.id}/scan"

    # La mise à disposition est réservée aux admins
    assert client.post(scan, headers=prh).status_code == 403
    assert client.post(scan, headers=ah).json()["nouveau_statut"] == "mis_a_disposition"

    # Point relais d'un autre lieu : refusé
    r = client.post(scan, headers=pr_sans_lieu)
    assert r.status_code == 403 and "assigné" in r.json()["detail"]

    # Point relais du bon lieu : retrait puis restitution
    assert client.post(scan, headers=prh).json()["nouveau_statut"] == "retire"
    assert client.post(scan, headers=prh).json()["nouveau_statut"] == "restitue"
    # Le passage en vérification est réservé aux admins
    assert client.post(scan, headers=prh).status_code == 403


def test_scan_utilisateur_simple_refuse(session):
    _, _, lieu, objet = _create_base_data(session)
    uh = _login("user@test.com", "user")
    assert client.post(f"/objets/{objet.id}/scan", headers=uh).status_code == 403
    assert client.post(f"/objets/{objet.id}/scan").status_code == 401


def test_scan_objet_inconnu_et_sans_reservation(session):
    _, _, _, objet = _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    assert client.post("/objets/9999/scan", headers=ah).status_code == 404
    assert client.post(f"/objets/{objet.id}/scan", headers=ah).status_code == 404


def test_scan_remise_en_service_apres_maintenance(session):
    _, _, _, objet = _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    prh = _point_relais(session, "pr@test.com")

    assert client.put(f"/admin/objets/{objet.id}/available?available=false", headers=ah).status_code == 200
    # Seul un admin peut remettre en service
    assert client.post(f"/objets/{objet.id}/scan", headers=prh).status_code == 403

    r = client.post(f"/objets/{objet.id}/scan", headers=ah)
    assert r.status_code == 200
    assert (r.json()["ancien_statut"], r.json()["nouveau_statut"]) == ("maintenance", "disponible")
    assert client.get(f"/objets/{objet.id}").json()["disponibilite_globale"] is True


# ---------------------------------------------------------------- retirer / retourner (legacy)

def test_retirer_admin_et_erreurs(session):
    _, user, lieu, objet = _create_base_data(session)
    uh, ah = _login("user@test.com", "user"), _login("admin@test.com", "admin")
    res = _reserve(uh, lieu, objet)

    assert client.post("/objets/9999/retirer", headers=ah).status_code == 404
    # Pas encore mis à disposition
    assert client.post(f"/objets/{objet.id}/retirer", headers=ah).status_code == 404

    client.post(f"/admin/reservations/{res['id']}/avancer", headers=ah)
    r = client.post(f"/objets/{objet.id}/retirer", headers=ah)
    assert r.status_code == 200 and r.json()["reservation_id"] == res["id"]


def test_retirer_point_relais(session):
    _, user, lieu, objet = _create_base_data(session)
    uh, ah = _login("user@test.com", "user"), _login("admin@test.com", "admin")
    res = _reserve(uh, lieu, objet)
    client.post(f"/admin/reservations/{res['id']}/avancer", headers=ah)

    sans_lieu = _point_relais(session, "pr0@test.com")
    assert client.post(f"/objets/{objet.id}/retirer", headers=sans_lieu).status_code == 403

    autre = Lieu(nom="Autre", lat=1.0, long=1.0, adresse="2 rue Autre")
    session.add(autre)
    session.commit()
    mauvais_lieu = _point_relais(session, "pr1@test.com", [autre])
    assert client.post(f"/objets/{objet.id}/retirer", headers=mauvais_lieu).status_code == 404

    bon = _point_relais(session, "pr2@test.com", [lieu])
    assert client.post(f"/objets/{objet.id}/retirer", headers=bon).status_code == 200


def test_retourner(session):
    _, user, lieu, objet = _create_base_data(session)
    uh, ah = _login("user@test.com", "user"), _login("admin@test.com", "admin")
    res = _reserve(uh, lieu, objet)
    for _ in range(2):
        client.post(f"/admin/reservations/{res['id']}/avancer", headers=ah)  # → retire

    assert client.post(f"/objets/9999/retourner?lieu_id={lieu.id}", headers=ah).status_code == 404

    autre = Lieu(nom="Autre", lat=1.0, long=1.0, adresse="2 rue Autre")
    session.add(autre)
    session.commit()
    session.refresh(autre)
    pr = _point_relais(session, "pr@test.com", [lieu])
    assert client.post(f"/objets/{objet.id}/retourner?lieu_id={autre.id}", headers=pr).status_code == 403

    r = client.post(f"/objets/{objet.id}/retourner?lieu_id={lieu.id}", headers=pr)
    assert r.status_code == 200 and r.json()["current_lieu_id"] == lieu.id
    session.expire_all()
    assert session.get(Reservation, res["id"]).status == "restitue"

    # Sans réservation en cours : seule la localisation est mise à jour
    r = client.post(f"/objets/{objet.id}/retourner?lieu_id={lieu.id}", headers=ah)
    assert r.status_code == 200


# ---------------------------------------------------------------- vérification / maintenance

def test_verification_puis_validation(session):
    _, user, lieu, objet = _create_base_data(session)
    uh, ah = _login("user@test.com", "user"), _login("admin@test.com", "admin")
    res = _reserve(uh, lieu, objet)

    assert client.get("/admin/objets/verification", headers=ah).json() == []
    for _ in range(4):
        client.post(f"/admin/reservations/{res['id']}/avancer", headers=ah)

    a_verifier = client.get("/admin/objets/verification", headers=ah).json()
    assert len(a_verifier) == 1
    assert a_verifier[0]["id"] == objet.id
    assert a_verifier[0]["reservation"]["status"] == "en_verification"

    assert client.post(f"/admin/objets/{objet.id}/valider", headers=ah).status_code == 200
    assert client.get("/reservations/historique", headers=uh).json()[0]["status"] == "terminee"
    # Rien à valider une deuxième fois
    assert client.post(f"/admin/objets/{objet.id}/valider", headers=ah).status_code == 404
    assert client.post("/admin/objets/9999/valider", headers=ah).status_code == 404


def test_mise_en_maintenance_ferme_les_reservations(session):
    _, user, lieu, objet = _create_base_data(session)
    uh, ah = _login("user@test.com", "user"), _login("admin@test.com", "admin")
    res = _reserve(uh, lieu, objet)
    client.post(f"/admin/reservations/{res['id']}/avancer", headers=ah)

    assert client.post("/admin/objets/9999/mettre-en-maintenance", headers=ah).status_code == 404
    assert client.post(f"/admin/objets/{objet.id}/mettre-en-maintenance", headers=ah).status_code == 200

    session.expire_all()
    assert session.get(Reservation, res["id"]).status == "terminee"
    en_maintenance = client.get("/admin/objets/maintenance", headers=ah).json()
    assert [o["id"] for o in en_maintenance] == [objet.id]
    # Réserver un objet en maintenance est refusé
    r = client.post("/reservations", json={
        "objet_id": objet.id, "lieu_id": lieu.id, "date_debut": "2030-02-07T10:00:00", "nb_semaines": 1,
    }, headers=uh)
    assert r.status_code == 400


def test_disponibilite_objet_inconnu_404(session):
    _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    assert client.put("/admin/objets/9999/available?available=false", headers=ah).status_code == 404


# ---------------------------------------------------------------- lecture / création / édition

def test_get_objet_404_et_historique(session):
    admin, user, lieu, objet = _create_base_data(session)
    uh = _login("user@test.com", "user")
    assert client.get("/objets/9999").status_code == 404

    # Première consultation : crée le lien d'historique ; deuxième : met la date à jour
    assert client.get(f"/objets/{objet.id}", headers=uh).status_code == 200
    assert client.get(f"/objets/{objet.id}", headers=uh).status_code == 200
    session.expire_all()
    liens = session.exec(select(UserObjetHistoriqueLink).where(UserObjetHistoriqueLink.objet_id == objet.id)).all()
    assert len(liens) == 1
    assert client.get("/users/historique", headers=uh).json()[0]["id"] == objet.id


def test_objet_ancien_avec_tag_unique_expose_tags(session):
    _, _, _, _ = _create_base_data(session)
    tag = Tag(nom="Cuisine")
    session.add(tag)
    session.commit()
    session.refresh(tag)
    ancien = Objet(nom="Ancien", description="d", tag_id=tag.id)  # aucun ObjetTagLink
    session.add(ancien)
    session.commit()
    session.refresh(ancien)
    data = client.get(f"/objets/{ancien.id}").json()
    assert [t["nom"] for t in data["tags"]] == ["Cuisine"]
    assert data["tag"]["nom"] == "Cuisine"


def test_creation_et_edition_erreurs(session):
    _, _, _, objet = _create_base_data(session)
    ah = _login("admin@test.com", "admin")

    assert client.post("/objets", headers=ah, json={"nom": "X", "description": "d", "tag_ids": [999]}).status_code == 404
    assert client.post("/objets", headers=ah, json={"nom": "X", "description": "d", "consommable_ids": [999]}).status_code == 404
    assert client.put("/admin/objets/9999", headers=ah, json={"nom": "Y"}).status_code == 404
    assert client.put(f"/admin/objets/{objet.id}", headers=ah, json={"tag_ids": [999]}).status_code == 404
    assert client.put(f"/admin/objets/{objet.id}", headers=ah, json={"consommable_ids": [999]}).status_code == 404
    # Non-admin refusé
    uh = _login("user@test.com", "user")
    assert client.put(f"/admin/objets/{objet.id}", headers=uh, json={"nom": "Z"}).status_code == 403


def test_edition_nom_description_consommables(session):
    _, _, _, objet = _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    cons = Consommable(nom="Huile", prix=3.0, url="https://example.org/huile")
    session.add(cons)
    session.commit()
    session.refresh(cons)

    r = client.put(f"/admin/objets/{objet.id}", headers=ah, json={
        "nom": "Perceuse Pro", "description": "Nouvelle desc", "consommable_ids": [cons.id], "stockage": "C4",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["nom"] == "Perceuse Pro" and body["description"] == "Nouvelle desc"
    assert body["consommables"][0]["nom"] == "Huile"
    assert body["stockage"] == "C4"

    # Vider les consommables
    r = client.put(f"/admin/objets/{objet.id}", headers=ah, json={"consommable_ids": []})
    assert r.json()["consommables"] == []


def test_stockage_masque_pour_non_admin_partout(session):
    admin, user, lieu, objet = _create_base_data(session)
    ah, uh = _login("admin@test.com", "admin"), _login("user@test.com", "user")
    client.put(f"/admin/objets/{objet.id}", headers=ah, json={"stockage": "A1"})
    client.post(f"/users/favoris/{objet.id}", headers=uh)
    client.get(f"/objets/{objet.id}", headers=uh)  # historique

    assert client.get("/objets", headers=uh).json()[0]["stockage"] is None
    assert client.get("/users/favoris", headers=uh).json()[0]["stockage"] is None
    assert client.get("/users/historique", headers=uh).json()[0]["stockage"] is None
    # …mais visible pour l'admin, y compris dans la liste
    assert client.get("/objets", headers=ah).json()[0]["stockage"] == "A1"
    assert client.get("/admin/objets/maintenance", headers=ah).json() == []


def test_liste_disponibles_sans_date(session):
    _, user, lieu, objet = _create_base_data(session)
    # Sans date_check : calculé à partir d'aujourd'hui, l'objet libre est listé
    assert [o["id"] for o in client.get("/objets?available=true").json()] == [objet.id]


# ---------------------------------------------------------------- suppression

def test_suppression_objet_nettoie_les_liens(session):
    admin, user, lieu, objet = _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    tag = Tag(nom="T")
    cons = Consommable(nom="C", prix=1.0)
    session.add(tag)
    session.add(cons)
    session.commit()
    session.refresh(tag)
    session.refresh(cons)
    session.add(ObjetTagLink(objet_id=objet.id, tag_id=tag.id))
    session.add(ObjetConsommableLink(objet_id=objet.id, consommable_id=cons.id))
    session.add(UserObjetFavorisLink(user_id=user.id, objet_id=objet.id))
    session.add(UserObjetHistoriqueLink(user_id=user.id, objet_id=objet.id))
    session.commit()

    oid = objet.id
    assert client.delete("/admin/objets/9999", headers=ah).status_code == 404
    assert client.delete(f"/admin/objets/{oid}", headers=ah).status_code == 200

    session.expire_all()
    for model in (ObjetTagLink, ObjetConsommableLink, UserObjetFavorisLink, UserObjetHistoriqueLink):
        assert session.exec(select(model).where(model.objet_id == oid)).all() == []


def test_suppression_tag_nettoie_les_liens_multi(session):
    _, _, _, objet = _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    t1, t2 = Tag(nom="A"), Tag(nom="B")
    session.add(t1)
    session.add(t2)
    session.commit()
    session.refresh(t1)
    session.refresh(t2)
    client.put(f"/admin/objets/{objet.id}", headers=ah, json={"tag_ids": [t1.id, t2.id]})

    tid = t1.id
    assert client.delete(f"/admin_meta/tags/{tid}", headers=ah).status_code == 200
    session.expire_all()
    assert session.exec(select(ObjetTagLink).where(ObjetTagLink.tag_id == tid)).all() == []
    assert [t["nom"] for t in client.get(f"/objets/{objet.id}").json()["tags"]] == ["B"]


# ---------------------------------------------------------------- images

def test_upload_image_objet(session, monkeypatch, tmp_path):
    import routers.objets as objets_router
    monkeypatch.setattr(objets_router, "IMAGE_DIR", str(tmp_path))
    _, _, _, objet = _create_base_data(session)
    ah, uh = _login("admin@test.com", "admin"), _login("user@test.com", "user")

    files = {"file": ("photo.png", _png_bytes(), "image/png")}
    assert client.post(f"/admin/objets/{objet.id}/image", files=files, headers=uh).status_code == 403
    assert client.post("/admin/objets/9999/image", files=files, headers=ah).status_code == 404
    bad = {"file": ("x.txt", b"hello", "text/plain")}
    assert client.post(f"/admin/objets/{objet.id}/image", files=bad, headers=ah).status_code == 400

    r = client.post(f"/admin/objets/{objet.id}/image", files=files, headers=ah)
    assert r.status_code == 200
    assert r.json()["image_url"] == f"/images/{objet.id}.jpg"
    saved = Image.open(tmp_path / f"{objet.id}.jpg")
    assert saved.size == (1200, 600)  # 2000x1000 réduit en conservant les proportions
    assert client.get(f"/objets/{objet.id}").json()["image"] == f"/images/{objet.id}.jpg"


def test_upload_image_consommable(session, monkeypatch, tmp_path):
    import routers.admin_meta as meta_router
    monkeypatch.setattr(meta_router, "IMAGE_DIR", str(tmp_path))
    _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    cons = client.post("/admin_meta/consommables", json={"nom": "Colle", "prix": 2.0}, headers=ah).json()

    files = {"file": ("c.png", _png_bytes((300, 300)), "image/png")}
    assert client.post("/admin_meta/consommables/9999/image", files=files, headers=ah).status_code == 404
    bad = {"file": ("x.txt", b"hello", "text/plain")}
    assert client.post(f"/admin_meta/consommables/{cons['id']}/image", files=bad, headers=ah).status_code == 400

    r = client.post(f"/admin_meta/consommables/{cons['id']}/image", files=files, headers=ah)
    assert r.status_code == 200
    assert r.json()["image_url"] == f"/images/consommable_{cons['id']}.jpg"
    assert (tmp_path / f"consommable_{cons['id']}.jpg").exists()
