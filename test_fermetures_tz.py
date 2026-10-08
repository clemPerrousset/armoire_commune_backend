"""Régression : une fermeture saisie en UTC ("…Z") ne doit pas faire planter
(500 → « objet déjà réservé » côté app) la réservation de n'importe quel objet."""
from datetime import datetime, timezone

from models import Fermeture, Reservation
from routers.reservations import _has_overlap, _overlaps_fermeture
from test_reservations import _create_base_data, _login, client


def test_fermeture_utc_ne_bloque_pas_autres_semaines(session):
    _, _, lieu, objet = _create_base_data(session)
    ah = _login("admin@test.com", "admin")
    r = client.put("/admin/fermetures", json={"semaines": ["2026-09-17T00:00:00Z"]}, headers=ah)
    assert r.status_code == 200

    uh = _login("user@test.com", "user")
    body = {"objet_id": objet.id, "lieu_id": lieu.id, "date_debut": "2026-10-08T10:00:00", "nb_semaines": 1}
    assert client.post("/reservations", json=body, headers=uh).status_code == 200

    # Pendant la fermeture : refus propre (400) avec le vrai motif
    body["date_debut"] = "2026-09-17T10:00:00"
    r = client.post("/reservations", json=body, headers=uh)
    assert r.status_code == 400
    assert "fermée" in r.json()["detail"]


def test_dates_aware_ne_plantent_pas(session):
    f = Fermeture(date_debut=datetime(2026, 9, 17, tzinfo=timezone.utc))
    session.add(f)
    session.commit()
    assert _overlaps_fermeture(session, datetime(2026, 9, 17, 10), datetime(2026, 9, 23, 22))
    assert not _overlaps_fermeture(session, datetime(2026, 10, 8, 10), datetime(2026, 10, 14, 22))
    res = Reservation(date_debut=datetime(2026, 10, 8, 10, tzinfo=timezone.utc),
                      date_fin=datetime(2026, 10, 14, 22, tzinfo=timezone.utc))
    assert _has_overlap([res], datetime(2026, 10, 8, 10), datetime(2026, 10, 14, 22))
