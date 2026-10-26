from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List
from database import get_session
from models import (
    Tag, Lieu, Consommable, User, Association, Objet, Reservation,
    UserLieuLink, STATUTS_BLOQUANTS,
)
from auth import get_current_admin

router = APIRouter(prefix="/admin_meta", tags=["Admin Metadata"])

# Associations
@router.post("/associations", response_model=Association)
def create_association(association: Association, session: Session = Depends(get_session), admin: User = Depends(get_current_admin)):
    session.add(association)
    session.commit()
    session.refresh(association)
    return association

@router.get("/associations", response_model=List[Association], tags=["Public Metadata"])
def list_associations(session: Session = Depends(get_session)):
    return session.exec(select(Association)).all()

# Tags
@router.post("/tags", response_model=Tag)
def create_tag(tag: Tag, session: Session = Depends(get_session), admin: User = Depends(get_current_admin)):
    session.add(tag)
    session.commit()
    session.refresh(tag)
    return tag

@router.get("/tags", response_model=List[Tag], tags=["Public Metadata"])
def list_tags(session: Session = Depends(get_session)):
    return session.exec(select(Tag)).all()

@router.delete("/tags/{tag_id}")
def delete_tag(tag_id: int, session: Session = Depends(get_session), admin: User = Depends(get_current_admin)):
    tag = session.get(Tag, tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    # Détache les objets de ce tag (ils restent, sans catégorie)
    for obj in session.exec(select(Objet).where(Objet.tag_id == tag_id)).all():
        obj.tag_id = None
        session.add(obj)
    session.delete(tag)
    session.commit()
    return {"ok": True}

# Lieux
@router.post("/lieux", response_model=Lieu)
def create_lieu(lieu: Lieu, session: Session = Depends(get_session), admin: User = Depends(get_current_admin)):
    session.add(lieu)
    session.commit()
    session.refresh(lieu)
    return lieu

@router.get("/lieux", response_model=List[Lieu], tags=["Public Metadata"])
def list_lieux(session: Session = Depends(get_session)):
    return session.exec(select(Lieu)).all()

@router.delete("/lieux/{lieu_id}")
def delete_lieu(lieu_id: int, session: Session = Depends(get_session), admin: User = Depends(get_current_admin)):
    lieu = session.get(Lieu, lieu_id)
    if not lieu:
        raise HTTPException(status_code=404, detail="Lieu not found")
    actives = session.exec(
        select(Reservation).where(
            Reservation.lieu_id == lieu_id,
            Reservation.status.in_(STATUTS_BLOQUANTS),
        )
    ).all()
    if actives:
        raise HTTPException(status_code=400, detail="Impossible de supprimer un lieu avec des réservations en cours")
    # Nettoie les références : réservations passées, localisation des objets, points relais
    for res in session.exec(select(Reservation).where(Reservation.lieu_id == lieu_id)).all():
        res.lieu_id = None
        session.add(res)
    for obj in session.exec(select(Objet).where(Objet.current_lieu_id == lieu_id)).all():
        obj.current_lieu_id = None
        session.add(obj)
    for link in session.exec(select(UserLieuLink).where(UserLieuLink.lieu_id == lieu_id)).all():
        session.delete(link)
    session.delete(lieu)
    session.commit()
    return {"ok": True}

# Consommables
@router.post("/consommables", response_model=Consommable)
def create_consommable(consommable: Consommable, session: Session = Depends(get_session), admin: User = Depends(get_current_admin)):
    session.add(consommable)
    session.commit()
    session.refresh(consommable)
    return consommable

@router.get("/consommables", response_model=List[Consommable], tags=["Public Metadata"])
def list_consommables(session: Session = Depends(get_session)):
    return session.exec(select(Consommable)).all()
