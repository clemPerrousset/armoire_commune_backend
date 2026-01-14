from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List
from datetime import datetime, timedelta
from pydantic import BaseModel

from database import get_session
from models import Reservation, Objet, User, Lieu
from auth import get_current_user, get_current_admin

router = APIRouter(tags=["Reservations"])

class ReservationCreate(BaseModel):
    objet_id: int
    lieu_id: int
    date_debut: datetime

@router.post("/reservations", response_model=Reservation)
def create_reservation(res_in: ReservationCreate, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    # 1. Check Objet
    obj = session.get(Objet, res_in.objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")

    # 2. Check Availability
    if not obj.disponibilite_globale:
        raise HTTPException(status_code=400, detail="Objet currently unavailable (broken/maintenance)")

    date_fin = res_in.date_debut + timedelta(days=7)

    # Count overlap
    overlap_count = 0
    # Note: accessing obj.reservations triggers a query if not loaded.
    for res in obj.reservations:
        if res.status == 'active':
            # Overlap logic: Res.start < New.End AND Res.end > New.Start
            if res.date_debut < date_fin and res.date_fin > res_in.date_debut:
                overlap_count += 1

    if overlap_count >= obj.quantite:
        raise HTTPException(status_code=400, detail="Objet not available for this date")

    # 3. Create
    db_res = Reservation(
        objet_id=res_in.objet_id,
        user_id=current_user.id,
        lieu_id=res_in.lieu_id,
        date_debut=res_in.date_debut,
        date_fin=date_fin,
        status="active"
    )
    session.add(db_res)
    session.commit()
    session.refresh(db_res)
    return db_res

@router.get("/reservations/me", response_model=List[Reservation])
def list_my_reservations(session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    return session.exec(select(Reservation).where(Reservation.user_id == current_user.id)).all()

@router.get("/admin/reservations", response_model=List[Reservation])
def list_all_reservations(session: Session = Depends(get_session), admin: User = Depends(get_current_admin)):
    return session.exec(select(Reservation)).all()

@router.post("/admin/reservations/{reservation_id}/return")
def return_object(reservation_id: int, session: Session = Depends(get_session), admin: User = Depends(get_current_admin)):
    res = session.get(Reservation, reservation_id)
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")

    res.status = "terminee"
    session.add(res)
    session.commit()
    return {"message": "Object returned", "reservation_id": reservation_id}
