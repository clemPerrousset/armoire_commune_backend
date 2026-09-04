from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from typing import List, Set
from datetime import datetime, timedelta
from pydantic import BaseModel

from database import get_session
from models import Fermeture, Reservation, User, STATUTS_EN_COURS
from auth import get_current_admin

router = APIRouter(tags=["Fermetures"])


class FermetureRead(BaseModel):
    id: int
    date_debut: datetime
    date_fin: datetime

    class Config:
        from_attributes = True


class FermetureUpdate(BaseModel):
    semaines: List[datetime]


def _next_thursday(reference: datetime) -> datetime:
    days_ahead = (3 - reference.weekday()) % 7
    return reference + timedelta(days=days_ahead)


def week_end(date_debut: datetime) -> datetime:
    return (date_debut + timedelta(days=6)).replace(hour=22, minute=0, second=0, microsecond=0)


def _normalize(date_debut: datetime) -> datetime:
    """Ramène une date au jeudi de sa semaine, à minuit — clé de dédoublonnage stable."""
    thursday = _next_thursday(date_debut)
    return thursday.replace(hour=0, minute=0, second=0, microsecond=0)


def _to_read(f: Fermeture) -> FermetureRead:
    return FermetureRead(id=f.id, date_debut=f.date_debut, date_fin=week_end(f.date_debut))


@router.get("/fermetures", response_model=List[FermetureRead])
def list_fermetures(session: Session = Depends(get_session)):
    """Semaines de fermeture administrative — bloquent tous les objets à la réservation."""
    fermetures = session.exec(select(Fermeture)).all()
    return [_to_read(f) for f in fermetures]


@router.put("/admin/fermetures", response_model=List[FermetureRead])
def set_fermetures(
    body: FermetureUpdate,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    """
    Remplace l'ensemble des semaines fermées par la liste fournie (cases à
    cocher + un seul "Valider" : ajouts et suppressions traités en une fois).
    Les réservations en cours qui chevauchent une semaine NOUVELLEMENT fermée
    sont prolongées gratuitement (pas de crédit supplémentaire) d'autant de
    semaines fermées concernées.
    """
    requested: Set[datetime] = {_normalize(d) for d in body.semaines}

    existing = session.exec(select(Fermeture)).all()
    existing_dates = {f.date_debut for f in existing}

    for f in existing:
        if f.date_debut not in requested:
            session.delete(f)

    newly_closed = requested - existing_dates
    for d in newly_closed:
        session.add(Fermeture(date_debut=d))

    session.commit()

    if newly_closed:
        _shift_ongoing_reservations(session, newly_closed)
        session.commit()

    remaining = session.exec(select(Fermeture)).all()
    return [_to_read(f) for f in remaining]


def _shift_ongoing_reservations(session: Session, newly_closed_dates: Set[datetime]):
    reservations = session.exec(
        select(Reservation).where(Reservation.status.in_(STATUTS_EN_COURS))
    ).all()

    for res in reservations:
        overlapping = sum(
            1 for d in newly_closed_dates
            if res.date_debut < week_end(d) and res.date_fin > d
        )
        if overlapping:
            res.date_fin = res.date_fin + timedelta(days=7 * overlapping)
            session.add(res)
