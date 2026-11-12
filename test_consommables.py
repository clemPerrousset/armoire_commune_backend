"""Modification et suppression des consommables (admin)."""
from sqlmodel import select

from models import Consommable, Objet, ObjetConsommableLink
from routers import admin_meta
from test_reservations import _create_base_data, _login, client


def _creer(ah, **extra):
    body = {"nom": "Vis", "prix": 0.1, "description": "Boîte de 100", "url": "https://yapla.test/vis"}
    body.update(extra)
    r = client.post("/admin_meta/consommables", headers=ah, json=body)
    assert r.status_code == 200
    return r.json()["id"]


def test_modifier_un_consommable_partiellement(session):
    _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    cid = _creer(ah)

    r = client.put(f"/admin_meta/consommables/{cid}", headers=ah, json={"prix": 2.5})
    assert r.status_code == 200
    body = r.json()
    assert body["prix"] == 2.5
    # les champs non fournis ne bougent pas
    assert (body["nom"], body["description"], body["url"]) == ("Vis", "Boîte de 100", "https://yapla.test/vis")

    r = client.put(f"/admin_meta/consommables/{cid}", headers=ah,
                   json={"nom": "Vis inox", "quantite": 40, "url": "https://yapla.test/inox"})
    assert (r.json()["nom"], r.json()["quantite"], r.json()["url"]) == ("Vis inox", 40, "https://yapla.test/inox")


def test_modifier_vider_description_et_lien(session):
    _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    cid = _creer(ah)

    r = client.put(f"/admin_meta/consommables/{cid}", headers=ah, json={"description": "  ", "url": ""})
    assert r.status_code == 200
    assert r.json()["description"] is None and r.json()["url"] is None


def test_modifier_champs_obligatoires_proteges(session):
    _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    cid = _creer(ah)

    assert client.put(f"/admin_meta/consommables/{cid}", headers=ah, json={"nom": "   "}).status_code == 400
    # null explicite sur nom / prix / quantité = inchangé (pas d'écrasement par du vide)
    r = client.put(f"/admin_meta/consommables/{cid}", headers=ah,
                   json={"nom": None, "prix": None, "quantite": None})
    assert r.status_code == 200
    assert (r.json()["nom"], r.json()["prix"]) == ("Vis", 0.1)


def test_modifier_inconnu_et_droits(session):
    _create_base_data(session)
    ah, uh = _login("admin@test.com", "admin"), _login("user@test.com", "user")
    cid = _creer(ah)

    assert client.put("/admin_meta/consommables/9999", headers=ah, json={"prix": 1}).status_code == 404
    assert client.put(f"/admin_meta/consommables/{cid}", headers=uh, json={"prix": 1}).status_code == 403
    assert client.put(f"/admin_meta/consommables/{cid}", json={"prix": 1}).status_code == 401
    assert client.delete(f"/admin_meta/consommables/{cid}", headers=uh).status_code == 403
    assert client.delete(f"/admin_meta/consommables/{cid}").status_code == 401


def test_supprimer_un_consommable_detache_les_objets_et_la_photo(session, tmp_path, monkeypatch):
    monkeypatch.setattr(admin_meta, "IMAGE_DIR", str(tmp_path))
    _, _, _, objet = _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    cid, autre = _creer(ah), _creer(ah, nom="Clous")
    oid = objet.id
    session.add(ObjetConsommableLink(objet_id=oid, consommable_id=cid))
    session.add(ObjetConsommableLink(objet_id=oid, consommable_id=autre))
    session.commit()
    photo = tmp_path / f"consommable_{cid}.jpg"
    photo.write_bytes(b"jpg")

    assert client.delete(f"/admin_meta/consommables/{cid}", headers=ah).json() == {"ok": True}

    session.expire_all()
    assert session.get(Consommable, cid) is None
    assert not photo.exists()
    # l'objet reste, il garde seulement l'autre consommable
    assert session.get(Objet, oid) is not None
    liens = session.exec(select(ObjetConsommableLink).where(ObjetConsommableLink.objet_id == oid)).all()
    assert [l.consommable_id for l in liens] == [autre]
    assert [c["nom"] for c in client.get("/admin_meta/consommables").json()] == ["Clous"]

    assert client.delete(f"/admin_meta/consommables/{cid}", headers=ah).status_code == 404


def test_supprimer_sans_photo(session, tmp_path, monkeypatch):
    monkeypatch.setattr(admin_meta, "IMAGE_DIR", str(tmp_path))
    _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    cid = _creer(ah)
    assert client.delete(f"/admin_meta/consommables/{cid}", headers=ah).status_code == 200
