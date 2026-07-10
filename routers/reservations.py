from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel

from database import get_session
from models import Reservation, Objet, User, Lieu
from auth import get_current_user, get_current_admin

router = APIRouter(tags=["Reservations"])


# --- Response models with nested objet/lieu ---

class ObjetBrief(BaseModel):
    id: int
    nom: str
    image: Optional[str] = None

    class Config:
        from_attributes = True

class LieuBrief(BaseModel):
    id: int
    nom: str
    adresse: str
    description: Optional[str] = None

    class Config:
        from_attributes = True

class ReservationRead(BaseModel):
    id: int
    date_debut: datetime
    date_fin: datetime
    status: str
    nb_semaines: int
    objet_id: Optional[int] = None
    lieu_id: Optional[int] = None
    user_id: Optional[int] = None
    objet: Optional[ObjetBrief] = None
    lieu: Optional[LieuBrief] = None

    class Config:
        from_attributes = True


# --- Helpers ---

def next_thursday(reference: datetime) -> datetime:
    """Retourne le prochain jeudi à partir de reference (inclus si c'est un jeudi)."""
    # weekday() : 0=lundi … 3=jeudi … 6=dimanche
    days_ahead = (3 - reference.weekday()) % 7
    return reference + timedelta(days=days_ahead)


def compute_date_fin(date_debut: datetime, nb_semaines: int) -> datetime:
    """Mercredi 22h00 qui suit la fin de l'emprunt (nb_semaines semaines après le jeudi de début)."""
    # Jeudi → +6 jours = mercredi suivant ; +6 + 7*(nb_semaines-1) pour les semaines sup.
    date_fin = date_debut + timedelta(days=6 + 7 * (nb_semaines - 1))
    return date_fin.replace(hour=22, minute=0, second=0, microsecond=0)


def _has_overlap(reservations, date_debut: datetime, date_fin: datetime) -> bool:
    """Vérifie si une réservation active/en_cours chevauche la plage donnée."""
    for res in reservations:
        if res.status in ("active", "en_cours"):
            if res.date_debut < date_fin and res.date_fin > date_debut:
                return True
    return False


# --- Endpoints ---

class ReservationCreate(BaseModel):
    objet_id: int
    lieu_id: int
    date_debut: datetime
    nb_semaines: int = 1  # 1, 2 ou 3 semaines


@router.post("/reservations", response_model=ReservationRead)
def create_reservation(
    res_in: ReservationCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    if res_in.nb_semaines not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="nb_semaines doit être 1, 2 ou 3")

    obj = session.get(Objet, res_in.objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")
    if not obj.disponibilite_globale:
        raise HTTPException(status_code=400, detail="Objet indisponible (maintenance/panne)")

    lieu = session.get(Lieu, res_in.lieu_id)
    if not lieu:
        raise HTTPException(status_code=404, detail="Lieu not found")

    # Ajustement au prochain jeudi
    date_debut = next_thursday(res_in.date_debut)
    date_fin = compute_date_fin(date_debut, res_in.nb_semaines)

    # Vérification de disponibilité sur toute la durée
    if _has_overlap(obj.reservations, date_debut, date_fin):
        raise HTTPException(status_code=400, detail="Objet non disponible sur cette période")

    db_res = Reservation(
        objet_id=res_in.objet_id,
        user_id=current_user.id,
        lieu_id=res_in.lieu_id,
        date_debut=date_debut,
        date_fin=date_fin,
        status="active",
        nb_semaines=res_in.nb_semaines,
    )
    session.add(db_res)
    session.commit()
    session.refresh(db_res)
    return db_res


@router.get("/reservations/me", response_model=List[ReservationRead])
def list_my_reservations(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    reservations = session.exec(
        select(Reservation).where(
            Reservation.user_id == current_user.id,
            Reservation.status.in_(["active", "en_cours"])
        )
    ).all()
    return reservations


@router.get("/reservations/historique", response_model=List[ReservationRead])
def list_reservation_historique(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """Réservations terminées de l'utilisateur connecté, triées du plus récent au plus ancien."""
    reservations = session.exec(
        select(Reservation).where(
            Reservation.user_id == current_user.id,
            Reservation.status == "terminee"
        ).order_by(Reservation.date_fin.desc())
    ).all()
    return reservations


@router.post("/reservations/{reservation_id}/cancel")
def cancel_reservation(
    reservation_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    res = session.get(Reservation, reservation_id)
    if not res:
        raise HTTPException(status_code=404, detail="Réservation introuvable")
    if res.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Action non autorisée")
    if res.status not in ("active",):
        raise HTTPException(status_code=400, detail=f"Impossible d'annuler une réservation au statut '{res.status}'")

    res.status = "annulee"
    session.add(res)
    session.commit()
    return {"message": "Réservation annulée", "reservation_id": reservation_id}


@router.get("/reservations/objet/{objet_id}", response_model=List[ReservationRead])
def list_reservations_for_objet(
    objet_id: int,
    session: Session = Depends(get_session)
):
    """Réservations actives/en_cours pour un objet — utilisé pour griser le calendrier."""
    reservations = session.exec(
        select(Reservation).where(
            Reservation.objet_id == objet_id,
            Reservation.status.in_(["active", "en_cours"])
        )
    ).all()
    return reservations


@router.get("/admin/reservations", response_model=List[ReservationRead])
def list_all_reservations(
    status: Optional[str] = Query(None, description="Filtrer par statut : active, en_cours, terminee, annulee"),
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    query = select(Reservation)
    if status:
        query = query.where(Reservation.status == status)
    return session.exec(query).all()


@router.post("/admin/reservations/{reservation_id}/return")
def return_object(
    reservation_id: int,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    res = session.get(Reservation, reservation_id)
    if not res:
        raise HTTPException(status_code=404, detail="Réservation introuvable")

    res.status = "terminee"
    session.add(res)
    session.commit()
    return {"message": "Objet retourné", "reservation_id": reservation_id}


@router.post("/admin/reservations/check-late")
def check_late_reservations(
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    now = datetime.now()
    late_reservations = session.exec(
        select(Reservation).where(
            Reservation.status.in_(["active", "en_cours"]),
            Reservation.date_fin < now
        )
    ).all()

    processed_count = 0
    extended_count = 0
    alerted_count = 0

    for late_res in late_reservations:
        processed_count += 1
        obj = session.get(Objet, late_res.objet_id)
        if not obj:
            continue

        future_reservations_exist = any(
            res.id != late_res.id
            and res.status == "active"
            and res.date_debut >= late_res.date_fin
            for res in obj.reservations
        )

        if future_reservations_exist:
            obj.alert = True
            session.add(obj)
            alerted_count += 1
        else:
            late_res.date_fin += timedelta(days=7)
            session.add(late_res)
            extended_count += 1

    session.commit()
    return {
        "message": "Vérification des retards effectuée",
        "processed": processed_count,
        "extended": extended_count,
        "alerts_triggered": alerted_count,
    }
