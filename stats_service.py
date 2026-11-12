"""Calcul des statistiques d'activité (vue admin « Statistiques » et rapport PDF).

Périodes glissantes se terminant aujourd'hui :
  - semaine : les 7 derniers jours (courbe par jour)
  - mois    : les 30 derniers jours (courbe par jour)
  - annee   : les 12 derniers mois civils (courbe par mois)

Limites assumées : une réservation n'a pas de date de création ni d'horodatage des
changements de statut. « Réservations » est donc compté à la date de début du prêt,
et « retours » à la date de fin prévue des prêts déjà restitués.
"""
from collections import Counter
from datetime import datetime, time, timedelta
from typing import Dict, Optional

from sqlmodel import Session, select

from models import Lieu, Objet, Reservation, User, STATUTS_EN_COURS

PERIODES = {"semaine": 7, "mois": 30, "annee": 365}
STATUTS_RENDUS = ("restitue", "en_verification", "terminee")
LABELS_PERIODE = {"semaine": "7 derniers jours", "mois": "30 derniers jours", "annee": "12 derniers mois"}
LABELS_STATUT = {
    "en_preparation": "En préparation",
    "mis_a_disposition": "Mis à disposition",
    "retire": "Retiré (en prêt)",
    "restitue": "Restitué",
    "en_verification": "En vérification",
}
MOIS = ["janv", "févr", "mars", "avr", "mai", "juin", "juil", "août", "sept", "oct", "nov", "déc"]


def _buckets(period: str, now: datetime):
    """Retourne (début, fin, liste de (clé, libellé)) pour la période."""
    end = datetime.combine(now.date(), time.max)
    if period == "annee":
        year, month = now.year, now.month
        keys = []
        for _ in range(12):
            keys.append((year, month))
            month -= 1
            if month == 0:
                year, month = year - 1, 12
        keys.reverse()
        start = datetime(keys[0][0], keys[0][1], 1)
        return start, end, [(k, f"{MOIS[k[1] - 1]} {str(k[0])[2:]}") for k in keys]
    days = PERIODES[period]
    first = now.date() - timedelta(days=days - 1)
    keys = [first + timedelta(days=i) for i in range(days)]
    start = datetime.combine(first, time.min)
    return start, end, [(k, k.strftime("%d/%m")) for k in keys]


def _key(period: str, dt: datetime):
    return (dt.year, dt.month) if period == "annee" else dt.date()


def compute_stats(session: Session, period: str, now: Optional[datetime] = None) -> Dict:
    if period not in PERIODES:
        raise ValueError(f"période inconnue : {period}")
    now = now or datetime.now()
    start, end, buckets = _buckets(period, now)

    reservations = session.exec(select(Reservation)).all()
    users = session.exec(select(User)).all()
    objets = session.exec(select(Objet)).all()
    lieux = session.exec(select(Lieu)).all()
    objets_by_id = {o.id: o for o in objets}

    def in_period(dt: datetime) -> bool:
        return start <= dt <= end

    # --- Photographie à l'instant T ---
    par_statut = Counter(r.status for r in reservations if r.status in STATUTS_EN_COURS)
    en_retard = {
        r.objet_id for r in reservations
        if r.status in ("en_preparation", "mis_a_disposition", "retire") and r.date_fin < now
    }
    snapshot = {
        "utilisateurs_inscrits": len(users),
        "points_relais": sum(1 for u in users if u.is_point_relais),
        "administrateurs": sum(1 for u in users if u.is_admin),
        "objets_total": len(objets),
        "objets_en_maintenance": sum(1 for o in objets if not o.disponibilite_globale),
        "objets_empruntes": len({r.objet_id for r in reservations if r.status == "retire"}),
        "objets_en_verification": len({r.objet_id for r in reservations if r.status == "en_verification"}),
        "objets_en_retard": len(en_retard),
        "lieux": len(lieux),
        "reservations_en_cours": sum(par_statut.values()),
        "reservations_par_statut": [
            {"statut": s, "label": LABELS_STATUT[s], "nombre": par_statut.get(s, 0)} for s in LABELS_STATUT
        ],
    }

    # --- Activité sur la période ---
    debutees = [r for r in reservations if in_period(r.date_debut) and r.status != "annulee"]
    annulees = [r for r in reservations if in_period(r.date_debut) and r.status == "annulee"]
    rendus = [r for r in reservations if r.status in STATUTS_RENDUS and in_period(r.date_fin)]
    total_demandes = len(debutees) + len(annulees)

    top = Counter(r.objet_id for r in debutees if r.objet_id in objets_by_id)
    top_objets = [
        {"nom": objets_by_id[oid].nom, "reservations": n} for oid, n in top.most_common(5)
    ]

    par_categorie: Counter = Counter()
    for r in debutees:
        obj = objets_by_id.get(r.objet_id)
        if not obj:
            continue
        noms = {t.nom for t in obj.tags} or ({obj.tag.nom} if obj.tag else set())
        for nom in noms or {"Sans catégorie"}:
            par_categorie[nom] += 1
    lieux_by_id = {l.id: l.nom for l in lieux}
    par_lieu = Counter(lieux_by_id.get(r.lieu_id, "Non précisé") for r in debutees)

    activite = {
        "reservations": len(debutees),
        "semaines_reservees": sum(r.nb_semaines for r in debutees),
        "credits_consommes": sum(r.nb_semaines for r in debutees),
        "annulations": len(annulees),
        "taux_annulation": round(100 * len(annulees) / total_demandes, 1) if total_demandes else 0.0,
        "objets_rendus": len(rendus),
        "objets_distincts_reserves": len({r.objet_id for r in debutees}),
        "emprunteurs_actifs": len({r.user_id for r in debutees}),
        "nouveaux_inscrits": sum(1 for u in users if u.created_at and in_period(u.created_at)),
        "top_objets": top_objets,
        "par_categorie": [{"nom": n, "reservations": c} for n, c in par_categorie.most_common()],
        "par_lieu": [{"nom": n, "reservations": c} for n, c in par_lieu.most_common()],
    }

    # --- Séries temporelles (abscisse = temps) ---
    res_series = Counter(_key(period, r.date_debut) for r in debutees)
    ret_series = Counter(_key(period, r.date_fin) for r in rendus)
    series = {
        "labels": [label for _, label in buckets],
        "reservations": [res_series.get(k, 0) for k, _ in buckets],
        "retours": [ret_series.get(k, 0) for k, _ in buckets],
    }

    return {
        "periode": period,
        "periode_label": LABELS_PERIODE[period],
        "debut": start.date().isoformat(),
        "fin": end.date().isoformat(),
        "genere_le": now.strftime("%d/%m/%Y %H:%M"),
        "snapshot": snapshot,
        "activite": activite,
        "series": series,
    }
