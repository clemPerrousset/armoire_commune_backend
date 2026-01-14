from fastapi import APIRouter, Depends
from sqlmodel import Session, select
from typing import List
from database import get_session
from models import Tag, Lieu, Consommable, User
from auth import get_current_admin

router = APIRouter(prefix="/admin_meta", tags=["Admin Metadata"])

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
