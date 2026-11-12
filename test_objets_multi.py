"""Catégories multiples, champ stockage (admin only), édition d'objet/lieu, notification de congé."""
from test_reservations import _create_base_data, _login, client
from models import Tag, Consommable


def _mk_tags(session):
    t1, t2 = Tag(nom="Bricolage"), Tag(nom="Jardinage")
    session.add(t1)
    session.add(t2)
    session.commit()
    session.refresh(t1)
    session.refresh(t2)
    return t1, t2


def test_multi_categories_et_stockage_admin_only(session):
    _create_base_data(session)
    t1, t2 = _mk_tags(session)
    ah = _login("admin@test.com", "admin")

    r = client.post("/objets", headers=ah, json={
        "nom": "Rallonge", "description": "25m", "tag_ids": [t1.id, t2.id],
        "stockage": "A1", "consommable_ids": [],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert {t["nom"] for t in body["tags"]} == {"Bricolage", "Jardinage"}
    assert body["stockage"] == "A1"
    oid = body["id"]

    # Anonyme : catégories visibles, stockage masqué
    pub = client.get(f"/objets/{oid}").json()
    assert len(pub["tags"]) == 2
    assert pub["stockage"] is None
    assert client.get("/objets").json()[0]["stockage"] is None
    # Admin : stockage visible
    assert client.get(f"/objets/{oid}", headers=ah).json()["stockage"] == "A1"

    # Filtre par catégorie secondaire
    assert len(client.get(f"/objets?tag_id={t2.id}").json()) == 1

    # Édition : une seule catégorie, nouveau stockage
    r = client.put(f"/admin/objets/{oid}", headers=ah, json={"tag_ids": [t2.id], "stockage": "B2"})
    assert r.status_code == 200
    assert [t["nom"] for t in r.json()["tags"]] == ["Jardinage"]
    assert r.json()["stockage"] == "B2"
    assert len(client.get(f"/objets?tag_id={t1.id}").json()) == 0


def test_ancien_client_tag_id_seul(session):
    _create_base_data(session)
    t1, _ = _mk_tags(session)
    ah = _login("admin@test.com", "admin")
    r = client.post("/objets", headers=ah, json={"nom": "X", "description": "d", "tag_id": t1.id, "consommable_ids": []})
    assert r.status_code == 200
    assert [t["nom"] for t in r.json()["tags"]] == ["Bricolage"]


def test_modifier_lieu_et_consommable_url(session):
    _, _, lieu, _ = _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    r = client.put(f"/admin_meta/lieux/{lieu.id}", headers=ah, json={"description": "Lun 9h-12h; Mer 14h-18h"})
    assert r.status_code == 200
    assert r.json()["description"].startswith("Lun")

    r = client.post("/admin_meta/consommables", headers=ah, json={
        "nom": "Détergent Karcher", "prix": 12.5, "url": "https://www.yapla.com/x",
    })
    assert r.status_code == 200
    cid = r.json()["id"]
    assert r.json()["url"] == "https://www.yapla.com/x"

    r = client.post("/objets", headers=ah, json={"nom": "Karcher", "description": "d", "consommable_ids": [cid]})
    assert r.json()["consommables"][0]["url"] == "https://www.yapla.com/x"


def test_conge_prolonge_et_notifie(session):
    _, _, lieu, objet = _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    uh = _login("user@test.com", "user")
    body = {"objet_id": objet.id, "lieu_id": lieu.id, "date_debut": "2026-09-10T10:00:00", "nb_semaines": 1}
    res = client.post("/reservations", json=body, headers=uh).json()
    assert res["date_fin"] == "2026-09-16T22:00:00"

    client.put("/admin/fermetures", json={"semaines": ["2026-09-10T00:00:00"]}, headers=ah)
    notifs = client.get("/users/notifications", headers=uh).json()
    assert len(notifs) == 1 and "congé" in notifs[0]["message"]
    assert client.post(f"/users/notifications/{notifs[0]['id']}/lu", headers=uh).status_code == 200
    assert client.get("/users/notifications", headers=uh).json() == []
