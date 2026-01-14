from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlmodel import Session, select, SQLModel
from datetime import datetime, timedelta

from database import get_session
from models import Objet, User, Consommable, ObjetConsommableLink, Reservation
from auth import get_current_admin

router = APIRouter(tags=["Objets"])

class ObjetCreate(SQLModel):
    nom: str
    description: str
    image: Optional[str] = None
    quantite: int = 1
    tag_id: Optional[int] = None
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
        query = query.where(Objet.nom.contains(nom))
    if tag_id:
        query = query.where(Objet.tag_id == tag_id)

    objets = session.exec(query).all()

    if not available:
        return objets

    # Filter by availability
    if not date_check:
        date_check = datetime.now()

    # We check if we can START a reservation at date_check (7 days duration)
    check_start = date_check
    check_end = date_check + timedelta(days=7)

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
