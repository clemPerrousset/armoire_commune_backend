from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlmodel import Session, select, SQLModel
from datetime import datetime, timedelta

from database import get_session
from models import Objet, User, Consommable, ObjetConsommableLink, Reservation, UserObjetHistoriqueLink
from auth import get_current_admin, get_current_user_optional

router = APIRouter(tags=["Objets"])

class ObjetCreate(SQLModel):
    nom: str
    description: str
    image: Optional[str] = None
    quantite: int = 1
    tag_id: Optional[int] = None
    association_id: Optional[int] = None
    consommable_ids: List[int] = []
    disponibilite_globale: bool = True

@router.post("/objets", response_model=Objet)
def create_objet(objet_in: ObjetCreate, session: Session = Depends(get_session), admin: User = Depends(get_current_admin)):
    # Create Objet, excluding extra fields
    objet_data = objet_in.dict(exclude={"consommable_ids"})
    db_objet = Objet(**objet_data)
    session.add(db_objet)
    session.commit()
    session.refresh(db_objet)

    # Link Consommables
    for c_id in objet_in.consommable_ids:
        # Check if consumable exists? Optional but good.
        link = ObjetConsommableLink(objet_id=db_objet.id, consommable_id=c_id)
        session.add(link)

    session.commit()
    session.refresh(db_objet)
    return db_objet

@router.get("/objets", response_model=List[Objet])
def list_objets(
    nom: Optional[str] = None,
    tag_id: Optional[int] = None,
    available: bool = Query(True, description="Filter by availability"),
    date_check: Optional[datetime] = None,
    session: Session = Depends(get_session)
):
    query = select(Objet)
    if nom:
        query = query.where(Objet.nom.icontains(nom))
    if tag_id:
        query = query.where(Objet.tag_id == tag_id)

    objets = session.exec(query).all()

    if not available:
        return objets

    # Filter by availability
    if not date_check:
        date_check = datetime.now()

    # We check if we can START a reservation at date_check (Wednesday to next Tuesday 22:00)
    days_ahead = (2 - date_check.weekday()) % 7
    check_start = date_check + timedelta(days=days_ahead)
    check_end = check_start + timedelta(days=6)
    check_end = check_end.replace(hour=22, minute=0, second=0, microsecond=0)

    available_objets = []

    for obj in objets:
        if not obj.disponibilite_globale:
            continue

        # Count overlapping reservations
        overlap_count = 0
        for res in obj.reservations:
            if res.status == 'active':
                # Overlap logic: Res.start < CheckEnd AND Res.end > CheckStart
                if res.date_debut < check_end and res.date_fin > check_start:
                    overlap_count += 1

        if obj.quantite > overlap_count:
            available_objets.append(obj)

    return available_objets

@router.get("/objets/{objet_id}", response_model=Objet)
def get_objet(
    objet_id: int,
    session: Session = Depends(get_session),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    obj = session.get(Objet, objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")

    if current_user:
        # Check if the history link already exists
        statement = select(UserObjetHistoriqueLink).where(
            UserObjetHistoriqueLink.user_id == current_user.id,
            UserObjetHistoriqueLink.objet_id == objet_id
        )
        historique_link = session.exec(statement).first()

        if historique_link:
            historique_link.date_consultation = datetime.utcnow()
        else:
            historique_link = UserObjetHistoriqueLink(user_id=current_user.id, objet_id=objet_id)

        session.add(historique_link)
        session.commit()

    return obj

@router.put("/admin/objets/{objet_id}/available")
def set_objet_availability(objet_id: int, available: bool, session: Session = Depends(get_session), admin: User = Depends(get_current_admin)):
    """
    Route spéciale pour dire qu'un objet est de nouveau disponible (physiquement),
    ou pour le marquer indisponible (réparation).
    Note: Cela change la 'disponibilite_globale', pas les réservations.
    Pour le retour de réservation, voir /reservations/return.
    """
    obj = session.get(Objet, objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")
    obj.disponibilite_globale = available
    session.add(obj)
    session.commit()
    return obj

@router.post("/admin/objets/{objet_id}/clear-alert")
def clear_objet_alert(objet_id: int, session: Session = Depends(get_session), admin: User = Depends(get_current_admin)):
    """
    Reset l'alerte d'un objet (quand l'objet était en retard et réservé après).
    """
    obj = session.get(Objet, objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")

    obj.alert = False
    session.add(obj)
    session.commit()

    return {"message": f"Alert cleared for objet {objet_id}"}
