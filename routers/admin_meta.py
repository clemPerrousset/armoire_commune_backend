import io
import os
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlmodel import Session, select
from typing import List, Optional
from pydantic import BaseModel
from PIL import Image
from database import get_session
from models import (
    Tag, Lieu, Consommable, User, Association, Objet, Reservation,
    UserLieuLink, ObjetTagLink, ObjetConsommableLink, STATUTS_BLOQUANTS,
)
from auth import get_current_admin

IMAGE_DIR = "/data/images"

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
    # Catégories multiples : retire aussi les liens objet↔catégorie
    for link in session.exec(select(ObjetTagLink).where(ObjetTagLink.tag_id == tag_id)).all():
        session.delete(link)
    session.delete(tag)
    session.commit()
    return {"ok": True}

# Lieux
class LieuUpdate(BaseModel):
    nom: Optional[str] = None
    adresse: Optional[str] = None
    description: Optional[str] = None  # horaires d'ouverture
    lat: Optional[float] = None
    long: Optional[float] = None

@router.put("/lieux/{lieu_id}", response_model=Lieu)
def update_lieu(lieu_id: int, body: LieuUpdate, session: Session = Depends(get_session), admin: User = Depends(get_current_admin)):
    lieu = session.get(Lieu, lieu_id)
    if not lieu:
        raise HTTPException(status_code=404, detail="Lieu not found")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(lieu, key, value)
    session.add(lieu)
    session.commit()
    session.refresh(lieu)
    return lieu

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

class ConsommableUpdate(BaseModel):
    """Modification partielle : seuls les champs fournis sont changés.
    Une description ou un lien vide efface la valeur."""
    nom: Optional[str] = None
    description: Optional[str] = None
    prix: Optional[float] = None
    quantite: Optional[int] = None
    url: Optional[str] = None


@router.put("/consommables/{consommable_id}", response_model=Consommable)
def update_consommable(
    consommable_id: int,
    body: ConsommableUpdate,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    cons = session.get(Consommable, consommable_id)
    if not cons:
        raise HTTPException(status_code=404, detail="Consommable not found")
    fields = body.model_dump(exclude_unset=True)
    if fields.get("nom") is not None and not fields["nom"].strip():
        raise HTTPException(status_code=400, detail="Le nom ne peut pas être vide")
    # nom, prix et quantité sont obligatoires : null = inchangé
    for key in ("nom", "prix", "quantite"):
        if key in fields and fields[key] is None:
            fields.pop(key)
    for key in ("description", "url"):
        if key in fields and isinstance(fields[key], str) and not fields[key].strip():
            fields[key] = None
    for key, value in fields.items():
        setattr(cons, key, value)
    session.add(cons)
    session.commit()
    session.refresh(cons)
    return cons


@router.delete("/consommables/{consommable_id}")
def delete_consommable(
    consommable_id: int,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    cons = session.get(Consommable, consommable_id)
    if not cons:
        raise HTTPException(status_code=404, detail="Consommable not found")
    # Détache le consommable des objets (ils restent), puis supprime sa photo
    for link in session.exec(
        select(ObjetConsommableLink).where(ObjetConsommableLink.consommable_id == consommable_id)
    ).all():
        session.delete(link)
    image_path = os.path.join(IMAGE_DIR, f"consommable_{consommable_id}.jpg")
    session.delete(cons)
    session.commit()
    if os.path.exists(image_path):
        os.remove(image_path)
    return {"ok": True}


@router.post("/consommables/{consommable_id}/image")
async def upload_consommable_image(
    consommable_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin),
):
    cons = session.get(Consommable, consommable_id)
    if not cons:
        raise HTTPException(status_code=404, detail="Consommable not found")
    if file.content_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        raise HTTPException(status_code=400, detail="Format non supporté")
    img = Image.open(io.BytesIO(await file.read())).convert("RGB")
    img.thumbnail((1200, 1200), Image.LANCZOS)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    img.save(os.path.join(IMAGE_DIR, f"consommable_{consommable_id}.jpg"), format="JPEG", quality=75, optimize=True)
    cons.image = f"/images/consommable_{consommable_id}.jpg"
    session.add(cons)
    session.commit()
    return {"image_url": cons.image}

@router.get("/consommables", response_model=List[Consommable], tags=["Public Metadata"])
def list_consommables(session: Session = Depends(get_session)):
    return session.exec(select(Consommable)).all()
