import io
import os
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File
from sqlmodel import Session, select, SQLModel
from datetime import datetime, timedelta
from PIL import Image

from database import get_session
from models import Objet, User, Consommable, ObjetConsommableLink, Reservation, UserObjetHistoriqueLink, Lieu, UserLieuLink
from auth import get_current_admin, get_current_user_optional, get_current_point_relais, get_current_user

IMAGE_DIR = "/data/images"
MAX_SIZE = (500, 500)
JPEG_QUALITY = 75

router = APIRouter(tags=["Objets"])


class ObjetCreate(SQLModel):
    nom: str
    description: str
    image: Optional[str] = None
    tag_id: Optional[int] = None
    association_id: Optional[int] = None
    consommable_ids: List[int] = []
    disponibilite_globale: bool = True


def _next_thursday(reference: datetime) -> datetime:
    days_ahead = (3 - reference.weekday()) % 7
    return reference + timedelta(days=days_ahead)


def _is_available_for_week(obj: Objet, date_debut: datetime, date_fin: datetime) -> bool:
    """Retourne True si aucune réservation active/en_cours ne chevauche la plage."""
    for res in obj.reservations:
        if res.status in ("active", "en_cours"):
            if res.date_debut < date_fin and res.date_fin > date_debut:
                return False
    return True


@router.post("/objets", response_model=Objet)
def create_objet(
    objet_in: ObjetCreate,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    objet_data = objet_in.dict(exclude={"consommable_ids"})
    db_objet = Objet(**objet_data)
    session.add(db_objet)
    session.commit()
    session.refresh(db_objet)

    for c_id in objet_in.consommable_ids:
        link = ObjetConsommableLink(objet_id=db_objet.id, consommable_id=c_id)
        session.add(link)

    session.commit()
    session.refresh(db_objet)
    return db_objet


@router.get("/objets", response_model=List[Objet])
def list_objets(
    nom: Optional[str] = None,
    tag_id: Optional[int] = None,
    # available=False → tous les objets ; available=True → uniquement les disponibles cette semaine
    available: bool = Query(False, description="True = uniquement disponibles, False = tous"),
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

    # Filtrage par dispo sur la prochaine semaine de retrait (jeudi→mercredi)
    if not date_check:
        date_check = datetime.now()

    check_start = _next_thursday(date_check)
    check_end = check_start + timedelta(days=6)
    check_end = check_end.replace(hour=22, minute=0, second=0, microsecond=0)

    return [
        obj for obj in objets
        if obj.disponibilite_globale and _is_available_for_week(obj, check_start, check_end)
    ]


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


@router.delete("/admin/objets/{objet_id}")
def delete_objet(
    objet_id: int,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    obj = session.get(Objet, objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")

    # Vérification : aucune réservation active ou en cours
    active_reservations = [r for r in obj.reservations if r.status in ("active", "en_cours")]
    if active_reservations:
        raise HTTPException(
            status_code=400,
            detail="Impossible de supprimer un objet avec des réservations actives ou en cours"
        )

    session.delete(obj)
    session.commit()
    return {"ok": True, "message": f"Objet '{obj.nom}' supprimé"}


@router.put("/admin/objets/{objet_id}/available")
def set_objet_availability(
    objet_id: int,
    available: bool,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    obj = session.get(Objet, objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")
    obj.disponibilite_globale = available
    session.add(obj)
    session.commit()
    return obj


@router.post("/admin/objets/{objet_id}/clear-alert")
def clear_objet_alert(
    objet_id: int,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    obj = session.get(Objet, objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")

    obj.alert = False
    session.add(obj)
    session.commit()
    return {"message": f"Alerte effacée pour l'objet {objet_id}"}


@router.post("/admin/objets/{objet_id}/image")
async def upload_objet_image(
    objet_id: int,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    """Upload et redimensionne la photo d'un objet (max 500×500, JPEG q=75)."""
    obj = session.get(Objet, objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")

    if file.content_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        raise HTTPException(status_code=400, detail="Format non supporté — utilisez JPEG, PNG ou WebP")

    raw = await file.read()
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.thumbnail(MAX_SIZE, Image.LANCZOS)

    os.makedirs(IMAGE_DIR, exist_ok=True)
    dest = os.path.join(IMAGE_DIR, f"{objet_id}.jpg")
    img.save(dest, format="JPEG", quality=JPEG_QUALITY, optimize=True)

    obj.image = f"/images/{objet_id}.jpg"
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return {"image_url": obj.image}


@router.get("/admin/objets/alerts", response_model=List[Objet])
def list_objets_en_alerte(
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    """Liste des objets ayant une alerte de retard active."""
    return session.exec(select(Objet).where(Objet.alert == True)).all()


@router.post("/objets/{objet_id}/retirer")
def retirer_objet(
    objet_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_point_relais)
):
    obj = session.get(Objet, objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")

    # Les admins peuvent opérer sur tous les lieux ; les point_relais sont limités aux leurs
    if current_user.is_admin:
        statement = select(Reservation).where(
            Reservation.objet_id == objet_id,
            Reservation.status == "active",
        )
    else:
        user_lieux_ids = [lieu.id for lieu in current_user.lieux]
        if not user_lieux_ids:
            raise HTTPException(status_code=403, detail="Aucun lieu associé à ce point relais")
        statement = select(Reservation).where(
            Reservation.objet_id == objet_id,
            Reservation.status == "active",
            Reservation.lieu_id.in_(user_lieux_ids)
        )

    reservation = session.exec(statement).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Aucune réservation active trouvée pour cet objet")

    reservation.status = "en_cours"
    session.add(reservation)
    session.commit()

    return {"message": "Objet retiré", "reservation_id": reservation.id}


@router.post("/objets/{objet_id}/retourner")
def retourner_objet(
    objet_id: int,
    lieu_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_point_relais)
):
    obj = session.get(Objet, objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")

    # Les admins peuvent retourner à n'importe quel lieu
    if not current_user.is_admin:
        user_lieux_ids = [lieu.id for lieu in current_user.lieux]
        if lieu_id not in user_lieux_ids:
            raise HTTPException(status_code=403, detail="Lieu non autorisé pour ce point relais")

    statement = select(Reservation).where(
        Reservation.objet_id == objet_id,
        Reservation.status.in_(["en_cours", "active"])
    )
    reservation = session.exec(statement).first()

    if reservation:
        reservation.status = "terminee"
        session.add(reservation)

    obj.current_lieu_id = lieu_id
    session.add(obj)
    session.commit()

    msg = "Objet retourné"
    if reservation:
        msg += f" (réservation {reservation.id} terminée)"

    return {"message": msg, "objet_id": obj.id, "current_lieu_id": lieu_id}
