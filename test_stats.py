"""Statistiques admin : calcul, PDF, envoi d'e-mail et routes."""
from datetime import datetime

import pytest

import pdf_report
from models import ObjetTagLink, Reservation, Tag
from stats_service import compute_stats
from test_reservations import _create_base_data, _login, client

NOW = datetime(2030, 1, 15, 12, 0)


def _res(session, objet, user, lieu, debut, fin, status, semaines=1):
    session.add(Reservation(
        date_debut=debut, date_fin=fin, status=status, nb_semaines=semaines,
        user_id=user.id, objet_id=objet.id, lieu_id=lieu.id,
    ))
    session.commit()


@pytest.fixture
def jeu(session):
    """Un petit historique autour de NOW (2030-01-15)."""
    admin, user, lieu, objet = _create_base_data(session)
    tag = Tag(nom="Bricolage")
    session.add(tag)
    session.commit()
    session.add(ObjetTagLink(objet_id=objet.id, tag_id=tag.id))
    session.commit()
    d = datetime
    _res(session, objet, user, lieu, d(2030, 1, 14), d(2030, 1, 21), "retire", 2)
    _res(session, objet, user, lieu, d(2030, 1, 10), d(2030, 1, 14), "terminee")
    _res(session, objet, user, lieu, d(2030, 1, 12), d(2030, 1, 19), "annulee")
    _res(session, objet, user, lieu, d(2029, 12, 20), d(2029, 12, 27), "terminee")
    _res(session, objet, user, lieu, d(2030, 1, 5), d(2030, 1, 12), "en_verification")
    _res(session, objet, user, lieu, d(2030, 1, 9), d(2030, 1, 13), "en_preparation")  # en retard
    return admin, user, lieu, objet


def test_stats_semaine(session, jeu):
    stats = compute_stats(session, "semaine", NOW)
    assert (stats["debut"], stats["fin"]) == ("2030-01-09", "2030-01-15")
    act, snap = stats["activite"], stats["snapshot"]

    # démarrées dans la fenêtre, hors annulées : retire (14), terminee (10), en_preparation (9)
    assert act["reservations"] == 3
    assert act["semaines_reservees"] == 4  # 2 + 1 + 1
    assert act["credits_consommes"] == 4
    assert (act["annulations"], act["taux_annulation"]) == (1, 25.0)
    # rendus : terminee (fin 14) + en_verification (fin 12)
    assert act["objets_rendus"] == 2
    assert act["objets_distincts_reserves"] == 1 and act["emprunteurs_actifs"] == 1
    assert act["top_objets"] == [{"nom": "Perceuse", "reservations": 3}]
    assert act["par_categorie"] == [{"nom": "Bricolage", "reservations": 3}]
    assert act["par_lieu"] == [{"nom": "LieuTest", "reservations": 3}]

    statuts = {s["statut"]: s["nombre"] for s in snap["reservations_par_statut"]}
    assert statuts == {
        "en_preparation": 1, "mis_a_disposition": 0, "retire": 1, "restitue": 0, "en_verification": 1,
    }
    assert snap["reservations_en_cours"] == 3
    assert snap["objets_empruntes"] == 1 and snap["objets_en_verification"] == 1
    assert snap["objets_en_retard"] == 1  # la réservation en préparation a dépassé sa fin
    assert snap["utilisateurs_inscrits"] == 2 and snap["administrateurs"] == 1
    assert snap["objets_total"] == 1 and snap["lieux"] == 1


def test_stats_series_temporelles(session, jeu):
    series = compute_stats(session, "semaine", NOW)["series"]
    assert series["labels"][0] == "09/01" and series["labels"][-1] == "15/01" and len(series["labels"]) == 7
    # 09/01 -> index 0 ; réservations aux 09, 10 et 14 ; retours le 12 et le 14
    assert series["reservations"] == [1, 1, 0, 0, 0, 1, 0]
    assert series["retours"] == [0, 0, 0, 1, 0, 1, 0]


def test_stats_mois_et_annee(session, jeu):
    mois = compute_stats(session, "mois", NOW)
    assert len(mois["series"]["labels"]) == 30
    # 5 : les 3 de la semaine + celle du 05/01 + celle du 20/12/2029 (annulée exclue)
    assert mois["activite"]["reservations"] == 5

    annee = compute_stats(session, "annee", NOW)
    assert len(annee["series"]["labels"]) == 12
    assert annee["series"]["labels"][-1] == "janv 30" and annee["series"]["labels"][0] == "févr 29"
    assert annee["debut"] == "2029-02-01"
    assert sum(annee["series"]["reservations"]) == 5  # la réservation du 05/01 entre dans l'année
    assert annee["series"]["reservations"][-2] == 1  # décembre 2029


def test_stats_nouveaux_inscrits(session, jeu):
    _, user, _, _ = jeu
    user.created_at = datetime(2030, 1, 14)
    session.add(user)
    session.commit()
    assert compute_stats(session, "semaine", NOW)["activite"]["nouveaux_inscrits"] == 1
    # les comptes sans date d'inscription (créés avant le champ) ne comptent pas
    user.created_at = None
    session.add(user)
    session.commit()
    assert compute_stats(session, "semaine", NOW)["activite"]["nouveaux_inscrits"] == 0


def test_stats_base_vide_et_periode_invalide(session):
    stats = compute_stats(session, "mois", NOW)
    assert stats["activite"]["reservations"] == 0 and stats["activite"]["taux_annulation"] == 0.0
    assert stats["activite"]["top_objets"] == []
    with pytest.raises(ValueError):
        compute_stats(session, "decennie", NOW)


def test_stats_annee_a_cheval_sur_deux_annees(session):
    labels = compute_stats(session, "annee", datetime(2030, 3, 10))["series"]["labels"]
    assert labels[0] == "avr 29" and labels[-1] == "mars 30"


def test_stats_objet_sans_categorie_ni_lieu(session):
    _, user, lieu, objet = _create_base_data(session)
    session.add(Reservation(date_debut=datetime(2030, 1, 14), date_fin=datetime(2030, 1, 21),
                            status="retire", user_id=user.id, objet_id=objet.id, lieu_id=None))
    session.add(Reservation(date_debut=datetime(2030, 1, 14), date_fin=datetime(2030, 1, 21),
                            status="retire", user_id=user.id, objet_id=None, lieu_id=lieu.id))
    session.commit()
    act = compute_stats(session, "semaine", NOW)["activite"]
    assert act["par_categorie"] == [{"nom": "Sans catégorie", "reservations": 1}]
    assert {"nom": "Non précisé", "reservations": 1} in act["par_lieu"]


def test_stats_categorie_principale_seule(session):
    """Objet ancien : une catégorie principale (tag_id) mais aucun lien multi-catégories."""
    _, user, lieu, objet = _create_base_data(session)
    tag = Tag(nom="Jardinage")
    session.add(tag)
    session.commit()
    objet.tag_id = tag.id
    session.add(objet)
    session.add(Reservation(date_debut=datetime(2030, 1, 14), date_fin=datetime(2030, 1, 21),
                            status="retire", user_id=user.id, objet_id=objet.id, lieu_id=lieu.id))
    session.commit()
    assert compute_stats(session, "semaine", NOW)["activite"]["par_categorie"] == [
        {"nom": "Jardinage", "reservations": 1}
    ]


# ---------------------------------------------------------------- PDF

def test_pdf_complet(session, jeu):
    pdf = pdf_report.build_pdf(compute_stats(session, "mois", NOW))
    assert pdf.startswith(b"%PDF") and len(pdf) > 1500


def test_pdf_base_vide(session):
    pdf = pdf_report.build_pdf(compute_stats(session, "annee", NOW))
    assert pdf.startswith(b"%PDF")


def test_pdf_caracteres_hors_latin1_et_saut_de_page(session):
    assert pdf_report._t("prix 5 € — ok") == "prix 5 ? ? ok"
    pdf = pdf_report._Report()
    pdf.add_page()
    pdf.set_y(pdf.h - 30)  # graphique trop bas : doit passer à la page suivante
    pdf_report._bar_chart(pdf, "Test", ["a", "b"], [("S", pdf_report.MINT, [0, 3])])
    assert pdf.page_no() == 2


# ---------------------------------------------------------------- routes

def test_routes_droits(session):
    _create_base_data(session)
    uh = _login("user@test.com", "user")
    for url in ("/admin/stats", "/admin/stats/pdf"):
        assert client.get(url).status_code == 401
        assert client.get(url, headers=uh).status_code == 403


def test_route_stats(session, jeu):
    ah = _login("admin@test.com", "admin")
    r = client.get("/admin/stats?periode=annee", headers=ah)
    assert r.status_code == 200
    body = r.json()
    assert body["periode"] == "annee" and set(body) >= {"snapshot", "activite", "series"}
    # période par défaut : le mois
    assert client.get("/admin/stats", headers=ah).json()["periode"] == "mois"
    assert client.get("/admin/stats?periode=siecle", headers=ah).status_code == 400


def test_route_pdf(session, jeu):
    ah = _login("admin@test.com", "admin")
    r = client.get("/admin/stats/pdf?periode=semaine", headers=ah)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert 'filename="statistiques-semaine.pdf"' in r.headers["content-disposition"]
    assert r.content.startswith(b"%PDF")
    # période par défaut : le mois
    assert 'statistiques-mois.pdf' in client.get("/admin/stats/pdf", headers=ah).headers["content-disposition"]
    assert client.get("/admin/stats/pdf?periode=siecle", headers=ah).status_code == 400
