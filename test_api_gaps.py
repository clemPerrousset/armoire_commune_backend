"""Couverture des cas prévisibles restants : auth, utilisateurs, métadonnées admin,
crédits, annulation, congés, migration, seed et démarrage."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from jose import jwt
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, select

import auth
import database
import main
import migrate as migrate_module
import seed
from auth import create_access_token, get_password_hash
from models import (
    Lieu, Notification, Objet, Reservation, User, UserLieuLink,
)
from test_reservations import _create_base_data, _login, client

THURSDAY = "2030-01-03T10:00:00"


def _body(objet, lieu, date=THURSDAY, n=1):
    return {"objet_id": objet.id, "lieu_id": lieu.id, "date_debut": date, "nb_semaines": n}


def _credits(headers):
    return client.get("/users/me", headers=headers).json()["credits"]


# ---------------------------------------------------------------- auth

def test_token_invalide_ou_sans_sub_ou_utilisateur_inconnu(session):
    _create_base_data(session)
    assert client.get("/users/me", headers={"Authorization": "Bearer pas-un-jwt"}).status_code == 401

    sans_sub = create_access_token({"foo": "bar"}, timedelta(minutes=5))
    assert client.get("/users/me", headers={"Authorization": f"Bearer {sans_sub}"}).status_code == 401

    inconnu = create_access_token({"sub": "personne@test.com"}, timedelta(minutes=5))
    assert client.get("/users/me", headers={"Authorization": f"Bearer {inconnu}"}).status_code == 401


def test_token_sans_expiration_explicite_utilise_15_minutes():
    token = create_access_token({"sub": "x@test.com"})
    payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
    assert payload["sub"] == "x@test.com" and "exp" in payload


def test_auth_optionnelle_tolere_les_tokens_douteux(session):
    _, _, _, objet = _create_base_data(session)
    for token in ("pas-un-jwt",
                  create_access_token({"foo": "bar"}, timedelta(minutes=5)),
                  create_access_token({"sub": "personne@test.com"}, timedelta(minutes=5))):
        r = client.get(f"/objets/{objet.id}", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200  # traité comme anonyme


def test_routes_admin_refusent_anonyme_et_non_admin(session):
    admin, user, lieu, objet = _create_base_data(session)
    uh = _login("user@test.com", "user")
    routes = [
        ("get", "/admin/reservations"), ("get", "/admin/objets/alerts"),
        ("get", "/admin/objets/maintenance"), ("get", "/admin/objets/verification"),
        ("post", "/admin/reservations/check-late"),
        ("post", "/admin/reservations/1/avancer"),
        ("post", f"/admin/objets/{objet.id}/valider"),
        ("post", f"/admin/objets/{objet.id}/mettre-en-maintenance"),
        ("post", f"/admin/objets/{objet.id}/clear-alert"),
        ("put", f"/admin/objets/{objet.id}/available?available=false"),
        ("delete", f"/admin/objets/{objet.id}"),
        ("put", "/admin/fermetures"),
        ("post", "/admin_meta/tags"), ("post", "/admin_meta/lieux"),
        ("post", "/admin_meta/consommables"), ("post", "/admin_meta/associations"),
        ("put", f"/admin_meta/lieux/{lieu.id}"),
        ("delete", f"/admin_meta/lieux/{lieu.id}"),
        ("put", f"/admin/users/{user.id}/promote?is_admin=true"),
        ("post", f"/admin/users/{user.id}/lieux/{lieu.id}"),
    ]
    for method, url in routes:
        assert getattr(client, method)(url).status_code == 401, (method, url)
        assert getattr(client, method)(url, headers=uh).status_code == 403, (method, url)


# ---------------------------------------------------------------- utilisateurs

def test_signup_doublon_et_login_invalide(session):
    payload = {"nom": "N", "prenom": "P", "email": "dup@test.com", "password": "pw"}
    assert client.post("/auth/signup", json=payload).status_code == 200
    r = client.post("/auth/signup", json=payload)
    assert r.status_code == 400 and "already" in r.json()["detail"]

    bad = client.post("/auth/login", data={"username": "dup@test.com", "password": "mauvais"})
    assert bad.status_code == 401
    unknown = client.post("/auth/login", data={"username": "nobody@test.com", "password": "x"})
    assert unknown.status_code == 401


def test_favoris_cas_limites(session):
    _, _, _, objet = _create_base_data(session)
    uh = _login("user@test.com", "user")
    assert client.post("/users/favoris/9999", headers=uh).status_code == 404
    assert client.post(f"/users/favoris/{objet.id}", headers=uh).status_code == 200
    again = client.post(f"/users/favoris/{objet.id}", headers=uh)
    assert again.status_code == 200 and "already" in again.json()["message"]
    assert len(client.get("/users/favoris", headers=uh).json()) == 1
    assert client.delete(f"/users/favoris/{objet.id}", headers=uh).status_code == 200
    assert client.delete(f"/users/favoris/{objet.id}", headers=uh).status_code == 404


def test_notifications_lecture_et_isolation(session):
    admin, user, _, _ = _create_base_data(session)
    session.add(Notification(user_id=user.id, message="Bonjour"))
    session.add(Notification(user_id=admin.id, message="Pour l'admin"))
    session.commit()
    uh, ah = _login("user@test.com", "user"), _login("admin@test.com", "admin")

    notifs = client.get("/users/notifications", headers=uh).json()
    assert [n["message"] for n in notifs] == ["Bonjour"]
    # Une notification d'un autre utilisateur est introuvable
    admin_notif = client.get("/users/notifications", headers=ah).json()[0]
    assert client.post(f"/users/notifications/{admin_notif['id']}/lu", headers=uh).status_code == 404
    assert client.post("/users/notifications/9999/lu", headers=uh).status_code == 404
    assert client.post(f"/users/notifications/{notifs[0]['id']}/lu", headers=uh).status_code == 200
    assert client.get("/users/notifications", headers=uh).json() == []
    assert client.get("/users/notifications").status_code == 401


def test_promotions_utilisateur_inconnu_404(session):
    _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    assert client.put("/admin/users/9999/promote?is_admin=true", headers=ah).status_code == 404
    assert client.put("/admin/users/9999/promote-point-relais?is_point_relais=true", headers=ah).status_code == 404


def test_promotion_admin_nominale(session):
    _, user, _, _ = _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    r = client.put(f"/admin/users/{user.id}/promote?is_admin=true", headers=ah)
    assert r.status_code == 200 and "True" in r.json()["message"]
    session.expire_all()
    assert session.get(User, user.id).is_admin is True


def test_assignation_lieu_point_relais(session):
    admin, user, lieu, _ = _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    url = f"/admin/users/{user.id}/lieux/{lieu.id}"

    assert client.post(f"/admin/users/9999/lieux/{lieu.id}", headers=ah).status_code == 404
    assert client.post(f"/admin/users/{user.id}/lieux/9999", headers=ah).status_code == 404
    assert client.post(url, headers=ah).status_code == 200
    again = client.post(url, headers=ah)
    assert again.status_code == 200 and "already" in again.json()["message"]
    assert len(session.exec(select(UserLieuLink)).all()) == 1

    assert client.delete(url, headers=ah).status_code == 200
    assert client.delete(url, headers=ah).status_code == 404


# ---------------------------------------------------------------- métadonnées admin

def test_associations_tags_lieux_consommables(session):
    _create_base_data(session)
    ah = _login("admin@test.com", "admin")

    asso = client.post("/admin_meta/associations", headers=ah,
                       json={"nom": "La Bricole", "lat": 1.0, "long": 2.0, "description": "d"})
    assert asso.status_code == 200
    assert [a["nom"] for a in client.get("/admin_meta/associations").json()] == ["La Bricole"]

    assert client.post("/admin_meta/tags", headers=ah, json={"nom": "Jardinage"}).status_code == 200
    assert [t["nom"] for t in client.get("/admin_meta/tags").json()] == ["Jardinage"]

    assert any(l["nom"] == "LieuTest" for l in client.get("/admin_meta/lieux").json())

    cons = client.post("/admin_meta/consommables", headers=ah, json={"nom": "Vis", "prix": 0.1})
    assert cons.status_code == 200
    assert [c["nom"] for c in client.get("/admin_meta/consommables").json()] == ["Vis"]


def test_modification_et_suppression_lieu(session):
    _, user, lieu, objet = _create_base_data(session)
    ah, uh = _login("admin@test.com", "admin"), _login("user@test.com", "user")

    assert client.put("/admin_meta/lieux/9999", headers=ah, json={"nom": "X"}).status_code == 404
    r = client.put(f"/admin_meta/lieux/{lieu.id}", headers=ah,
                   json={"nom": "Nouveau", "adresse": "Ici", "lat": 1.5, "long": 2.5, "description": "Lun 9h"})
    assert r.status_code == 200
    assert (r.json()["nom"], r.json()["adresse"], r.json()["lat"]) == ("Nouveau", "Ici", 1.5)

    assert client.delete("/admin_meta/lieux/9999", headers=ah).status_code == 404

    # Réservation en cours : suppression refusée
    res = client.post("/reservations", json=_body(objet, lieu), headers=uh).json()
    assert client.delete(f"/admin_meta/lieux/{lieu.id}", headers=ah).status_code == 400

    # Réservation terminée + localisation + point relais : tout est détaché puis supprimé
    lieu_id, objet_id, user_id = lieu.id, objet.id, user.id
    session.expire_all()
    reservation = session.get(Reservation, res["id"])
    reservation.status = "terminee"
    obj = session.get(Objet, objet_id)
    obj.current_lieu_id = lieu_id
    session.add(UserLieuLink(user_id=user_id, lieu_id=lieu_id))
    session.add(reservation)
    session.add(obj)
    session.commit()

    assert client.delete(f"/admin_meta/lieux/{lieu_id}", headers=ah).status_code == 200
    session.expire_all()
    assert session.get(Lieu, lieu_id) is None
    assert session.get(Objet, objet_id).current_lieu_id is None
    assert session.get(Reservation, res["id"]).lieu_id is None
    assert session.exec(select(UserLieuLink)).all() == []


def test_suppression_tag_inconnu_404(session):
    _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    assert client.delete("/admin_meta/tags/9999", headers=ah).status_code == 404


# ---------------------------------------------------------------- réservations : crédits et annulation

def test_credits_deduits_puis_rembourses(session):
    _, _, lieu, objet = _create_base_data(session)
    uh = _login("user@test.com", "user")
    assert _credits(uh) == 100

    res = client.post("/reservations", json=_body(objet, lieu, n=3), headers=uh).json()
    assert _credits(uh) == 97

    r = client.post(f"/reservations/{res['id']}/cancel", headers=uh)
    assert r.status_code == 200 and r.json()["credits_remboursés"] == 3
    assert _credits(uh) == 100
    assert client.get("/reservations/me", headers=uh).json() == []


def test_credits_insuffisants(session):
    _, user, lieu, objet = _create_base_data(session)
    user.credits = 1
    session.add(user)
    session.commit()
    uh = _login("user@test.com", "user")

    r = client.post("/reservations", json=_body(objet, lieu, n=2), headers=uh)
    assert r.status_code == 400 and "insuffisants" in r.json()["detail"]
    assert _credits(uh) == 1  # rien de débité
    assert client.post("/reservations", json=_body(objet, lieu, n=1), headers=uh).status_code == 200
    assert _credits(uh) == 0


def test_reservation_refus_objet_ou_lieu_inconnu_ou_indisponible(session):
    _, _, lieu, objet = _create_base_data(session)
    uh, ah = _login("user@test.com", "user"), _login("admin@test.com", "admin")

    inconnu = {"objet_id": 9999, "lieu_id": lieu.id, "date_debut": THURSDAY, "nb_semaines": 1}
    assert client.post("/reservations", json=inconnu, headers=uh).status_code == 404
    mauvais_lieu = {"objet_id": objet.id, "lieu_id": 9999, "date_debut": THURSDAY, "nb_semaines": 1}
    assert client.post("/reservations", json=mauvais_lieu, headers=uh).status_code == 404

    client.put(f"/admin/objets/{objet.id}/available?available=false", headers=ah)
    r = client.post("/reservations", json=_body(objet, lieu), headers=uh)
    assert r.status_code == 400 and "indisponible" in r.json()["detail"]
    assert client.post("/reservations", json=_body(objet, lieu)).status_code == 401


def test_annulation_regles(session):
    admin, user, lieu, objet = _create_base_data(session)
    other = User(nom="O", prenom="O", email="other@test.com", password_hash=get_password_hash("o"))
    session.add(other)
    session.commit()
    uh, ah, oh = _login("user@test.com", "user"), _login("admin@test.com", "admin"), _login("other@test.com", "o")
    res = client.post("/reservations", json=_body(objet, lieu), headers=uh).json()

    assert client.post("/reservations/9999/cancel", headers=uh).status_code == 404
    assert client.post(f"/reservations/{res['id']}/cancel", headers=oh).status_code == 403  # pas son emprunt

    # Après retrait : plus d'annulation possible
    client.post(f"/admin/reservations/{res['id']}/avancer", headers=ah)
    client.post(f"/admin/reservations/{res['id']}/avancer", headers=ah)
    r = client.post(f"/reservations/{res['id']}/cancel", headers=uh)
    assert r.status_code == 400 and "retire" in r.json()["detail"]
    assert _credits(uh) == 99  # pas de remboursement


def test_admin_peut_annuler_pour_un_utilisateur(session):
    _, user, lieu, objet = _create_base_data(session)
    uh, ah = _login("user@test.com", "user"), _login("admin@test.com", "admin")
    res = client.post("/reservations", json=_body(objet, lieu), headers=uh).json()
    assert client.post(f"/reservations/{res['id']}/cancel", headers=ah).status_code == 200
    assert _credits(uh) == 100


def test_avancer_reservation_inconnue_404(session):
    _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    assert client.post("/admin/reservations/9999/avancer", headers=ah).status_code == 404


def test_check_late_ignore_reservation_dont_objet_a_disparu(session):
    admin, user, _, _ = _create_base_data(session)
    now = datetime.now()
    session.add(Reservation(objet_id=9999, user_id=user.id, date_debut=now - timedelta(days=14),
                            date_fin=now - timedelta(days=7), status="retire"))
    session.commit()
    ah = _login("admin@test.com", "admin")
    data = client.post("/admin/reservations/check-late", headers=ah).json()
    assert data["extended"] == 0 and data["alerts_triggered"] == 0


# ---------------------------------------------------------------- congés

def test_liste_et_retrait_de_semaines_fermees(session):
    _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    client.put("/admin/fermetures", json={"semaines": ["2030-01-03T00:00:00", "2030-01-10T00:00:00"]}, headers=ah)
    assert len(client.get("/fermetures").json()) == 2

    # Désélectionner une semaine puis valider la retire
    r = client.put("/admin/fermetures", json={"semaines": ["2030-01-03T00:00:00"]}, headers=ah)
    assert [f["date_debut"][:10] for f in r.json()] == ["2030-01-03"]
    assert [f["date_fin"] for f in client.get("/fermetures").json()] == ["2030-01-09T22:00:00"]


def test_conge_de_deux_semaines_prolonge_de_deux_et_notifie_une_fois(session):
    _, _, lieu, objet = _create_base_data(session)
    uh, ah = _login("user@test.com", "user"), _login("admin@test.com", "admin")
    res = client.post("/reservations", json=_body(objet, lieu, n=3), headers=uh).json()
    assert res["date_fin"] == "2030-01-23T22:00:00"

    client.put("/admin/fermetures", json={"semaines": ["2030-01-10T00:00:00", "2030-01-17T00:00:00"]}, headers=ah)
    mine = client.get("/reservations/me", headers=uh).json()[0]
    assert mine["date_fin"] == "2030-02-06T22:00:00"  # +14 jours
    assert len(client.get("/users/notifications", headers=uh).json()) == 1

    # Rejouer la même liste ne prolonge rien et ne notifie pas à nouveau
    client.put("/admin/fermetures", json={"semaines": ["2030-01-10T00:00:00", "2030-01-17T00:00:00"]}, headers=ah)
    assert client.get("/reservations/me", headers=uh).json()[0]["date_fin"] == "2030-02-06T22:00:00"
    assert len(client.get("/users/notifications", headers=uh).json()) == 1


def test_conge_hors_reservation_ne_change_rien(session):
    _, _, lieu, objet = _create_base_data(session)
    uh, ah = _login("user@test.com", "user"), _login("admin@test.com", "admin")
    client.post("/reservations", json=_body(objet, lieu), headers=uh)
    client.put("/admin/fermetures", json={"semaines": ["2030-06-06T00:00:00"]}, headers=ah)
    assert client.get("/users/notifications", headers=uh).json() == []
    assert client.get("/reservations/me", headers=uh).json()[0]["date_fin"] == "2030-01-09T22:00:00"


def test_reservation_dans_un_conge_est_prolongee_en_cascade(session):
    """Prolonger peut atteindre une 2e semaine fermée : elle est comptée aussi."""
    _, _, lieu, objet = _create_base_data(session)
    uh, ah = _login("user@test.com", "user"), _login("admin@test.com", "admin")
    client.put("/admin/fermetures", json={"semaines": ["2030-01-10T00:00:00", "2030-01-17T00:00:00"]}, headers=ah)
    # 2 semaines du 03/01 : chevauche la fermeture du 10/01 → +1 sem. → chevauche aussi celle du 17/01 → +2
    r = client.post("/reservations", json=_body(objet, lieu, n=2), headers=uh)
    assert r.status_code == 200
    assert r.json()["date_fin"] == "2030-01-30T22:00:00"
    assert _credits(uh) == 98  # les semaines offertes ne coûtent rien


# ---------------------------------------------------------------- migration, seed, démarrage

def test_format_default_toutes_branches():
    f = migrate_module._format_default
    col = lambda default: SimpleNamespace(default=default)
    scalar = lambda v: SimpleNamespace(is_scalar=True, arg=v)

    assert f(col(None)) is None
    assert f(col(SimpleNamespace(is_scalar=False, arg=1))) is None
    assert f(col(scalar(None))) is None
    assert f(col(scalar(True))) == "1"
    assert f(col(scalar(False))) == "0"
    assert f(col(scalar(7))) == "7"
    assert f(col(scalar(1.5))) == "1.5"
    assert f(col(scalar("l'ami"))) == "'l''ami'"
    assert f(col(scalar([1, 2]))) is None


def test_migrate_ajoute_colonnes_et_backfill_categories(monkeypatch, tmp_path):
    """Ancienne base : objet avec tag_id, sans colonne stockage ni table objettaglink."""
    import sqlite3
    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE tag (id INTEGER PRIMARY KEY, nom VARCHAR NOT NULL)")
    conn.execute(
        "CREATE TABLE objet (id INTEGER PRIMARY KEY, nom VARCHAR NOT NULL, description VARCHAR NOT NULL, "
        "image VARCHAR, disponibilite_globale BOOLEAN NOT NULL DEFAULT 1, alert BOOLEAN NOT NULL DEFAULT 0, "
        "current_lieu_id INTEGER, tag_id INTEGER, association_id INTEGER)"
    )
    conn.execute("INSERT INTO tag (id, nom) VALUES (1, 'Bricolage')")
    conn.execute("INSERT INTO objet (id, nom, description, tag_id) VALUES (1, 'Perceuse', 'd', 1)")
    conn.execute("INSERT INTO objet (id, nom, description, tag_id) VALUES (2, 'Sans tag', 'd', NULL)")
    conn.commit()
    conn.close()

    eng = sa_create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(database, "engine", eng)
    monkeypatch.setattr(migrate_module, "engine", eng)

    migrate_module.migrate()
    migrate_module.migrate()  # idempotent

    with eng.connect() as c:
        cols = {r[1] for r in c.exec_driver_sql("PRAGMA table_info(objet)")}
        assert "stockage" in cols
        links = [tuple(r) for r in c.exec_driver_sql("SELECT objet_id, tag_id FROM objettaglink").fetchall()]
        assert links == [(1, 1)]  # un seul lien, pas de doublon après deux migrations


def test_migrate_ignore_les_tables_absentes(monkeypatch, tmp_path):
    eng = sa_create_engine(f"sqlite:///{tmp_path / 'vide.db'}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(database, "engine", eng)
    monkeypatch.setattr(migrate_module, "engine", eng)
    monkeypatch.setattr(migrate_module, "create_db_and_tables", lambda: None)  # aucune table créée
    migrate_module.migrate()  # ne doit rien faire ni planter
    with eng.connect() as c:
        assert c.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == []


def test_seed_cree_les_donnees_une_seule_fois(monkeypatch):
    eng = sa_create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    monkeypatch.setattr(seed, "engine", eng)
    monkeypatch.setattr(seed, "create_db_and_tables", lambda: SQLModel.metadata.create_all(eng))

    seed.seed()
    seed.seed()  # 2e appel : « Already seeded », rien en double

    with Session(eng) as s:
        assert len(s.exec(select(User)).all()) == 2
        assert [o.nom for o in s.exec(select(Objet)).all()] == ["Perceuse Percussion"]
        perceuse = s.exec(select(Objet)).first()
        assert [c.nom for c in perceuse.consommables] == ["Vis"]


def test_demarrage_et_racine(monkeypatch):
    appels = []
    monkeypatch.setattr(main, "create_db_and_tables", lambda: appels.append(1))
    main.on_startup()
    assert appels == [1]
    assert "Armoire" in client.get("/").json()["message"]


def test_get_session_reel_ouvre_et_ferme_une_session():
    gen = database.get_session()
    session = next(gen)
    assert isinstance(session, Session)
    gen.close()


def test_fixture_client_de_conftest(client):
    # Utilise la fixture `client` de conftest.py (TestClient lié à la base de test)
    assert client.get("/").status_code == 200
