import io
import os
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File
from sqlmodel import Session, select, SQLModel
from datetime import datetime, timedelta
from pydantic import BaseModel
from PIL import Image

from database import get_session
from models import (
    Objet, User, Consommable, ObjetConsommableLink, Reservation,
    UserObjetHistoriqueLink, Lieu, UserLieuLink, Fermeture,
    STATUTS_BLOQUANTS, STATUT_SUIVANT
)
from auth import get_current_admin, get_current_user_optional, get_current_point_relais, get_current_user
from routers.fermetures import week_end

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


class ReservationBrief(BaseModel):
    id: int
    status: str
    date_debut: datetime
    date_fin: datetime
    nb_semaines: int
    user_id: Optional[int] = None

    class Config:
        from_attributes = True


class ObjetWithReservation(BaseModel):
    """Objet avec sa réservation courante — utilisé pour la liste de vérification."""
    id: Optional[int]
    nom: str
    description: str
    image: Optional[str] = None
    disponibilite_globale: bool
    reservation: Optional[ReservationBrief] = None

    class Config:
        from_attributes = True


class ScanResult(BaseModel):
    objet_id: int
    objet_nom: str
    ancien_statut: str
    nouveau_statut: str
    reservation_id: Optional[int] = None
    verification_requise: bool = False  # True quand on atteint en_verification


def _next_thursday(reference: datetime) -> datetime:
    days_ahead = (3 - reference.weekday()) % 7
    return reference + timedelta(days=days_ahead)


def _is_available_for_week(obj: Objet, date_debut: datetime, date_fin: datetime, fermetures=None) -> bool:
    for res in obj.reservations:
        if res.status in STATUTS_BLOQUANTS:
            if res.date_debut < date_fin and res.date_fin > date_debut:
                return False
    for f in fermetures or []:
        if f.date_debut < date_fin and week_end(f.date_debut) > date_debut:
            return False
    return True


def _get_reservation_active(objet_id: int, session: Session) -> Optional[Reservation]:
    return session.exec(
        select(Reservation).where(
            Reservation.objet_id == objet_id,
            Reservation.status.in_(STATUTS_BLOQUANTS)
        )
    ).first()


# --- CRUD Objets ---

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

    if not date_check:
        date_check = datetime.now()

    check_start = _next_thursday(date_check)
    check_end = check_start + timedelta(days=6)
    check_end = check_end.replace(hour=22, minute=0, second=0, microsecond=0)

    fermetures = session.exec(select(Fermeture)).all()

    return [
        obj for obj in objets
        if obj.disponibilite_globale and _is_available_for_week(obj, check_start, check_end, fermetures)
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


# --- Admin CRUD ---

@router.delete("/admin/objets/{objet_id}")
def delete_objet(
    objet_id: int,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    obj = session.get(Objet, objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")

    active = [r for r in obj.reservations if r.status in STATUTS_BLOQUANTS]
    if active:
        raise HTTPException(status_code=400, detail="Impossible de supprimer un objet avec des réservations actives")

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
    obj = session.get(Objet, objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")

    if file.content_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        raise HTTPException(status_code=400, detail="Format non supporté")

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


# --- Alertes (objets en retard) ---

@router.get("/admin/objets/alerts", response_model=List[Objet])
def list_objets_en_retard(
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    """Objets dont la réservation est en retard (date_fin dépassée, pas encore restitués)."""
    now = datetime.now()
    late_reservations = session.exec(
        select(Reservation).where(
            Reservation.status.in_(["en_preparation", "mis_a_disposition", "retire"]),
            Reservation.date_fin < now
        )
    ).all()

    objet_ids = list({r.objet_id for r in late_reservations if r.objet_id})
    if not objet_ids:
        return []

    return session.exec(select(Objet).where(Objet.id.in_(objet_ids))).all()


# --- Objets en maintenance ---

@router.get("/admin/objets/maintenance", response_model=List[Objet])
def list_objets_en_maintenance(
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    """Objets marqués indisponibles (maintenance) — à rescanner pour les remettre en service."""
    objets = session.exec(select(Objet)).all()
    return [obj for obj in objets if not obj.disponibilite_globale]


# --- QR Scan : avancement du statut ---

@router.post("/objets/{objet_id}/scan", response_model=ScanResult)
def scan_objet(
    objet_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_point_relais)
):
    """
    Scan du QR code d'un objet par un admin ou point_relais.
    Avance le statut de la réservation active au statut suivant.
    """
    obj = session.get(Objet, objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")

    reservation = _get_reservation_active(objet_id, session)
    if not reservation:
        # Objet sans réservation en cours : s'il est indisponible (ex. maintenance),
        # le scan sert à confirmer qu'il est réparé/de retour et le remet en service.
        if not obj.disponibilite_globale:
            obj.disponibilite_globale = True
            session.add(obj)
            session.commit()
            return ScanResult(
                objet_id=objet_id,
                objet_nom=obj.nom,
                ancien_statut="maintenance",
                nouveau_statut="disponible",
                reservation_id=None,
                verification_requise=False,
            )
        raise HTTPException(status_code=404, detail="Aucune réservation active pour cet objet")

    ancien_statut = reservation.status
    if ancien_statut not in STATUT_SUIVANT:
        raise HTTPException(
            status_code=400,
            detail=f"Statut '{ancien_statut}' ne peut pas être avancé par scan"
        )

    nouveau_statut = STATUT_SUIVANT[ancien_statut]
    reservation.status = nouveau_statut
    session.add(reservation)
    session.commit()

    return ScanResult(
        objet_id=objet_id,
        objet_nom=obj.nom,
        ancien_statut=ancien_statut,
        nouveau_statut=nouveau_statut,
        reservation_id=reservation.id,
        verification_requise=(nouveau_statut == "en_verification"),
    )


# --- Vérification admin ---

@router.get("/admin/objets/verification", response_model=List[ObjetWithReservation])
def list_objets_a_verifier(
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    """Objets dont la réservation est en statut 'en_verification' — à valider par l'admin."""
    reservations = session.exec(
        select(Reservation).where(Reservation.status == "en_verification")
    ).all()

    result = []
    for res in reservations:
        obj = session.get(Objet, res.objet_id)
        if obj:
            result.append(ObjetWithReservation(
                id=obj.id,
                nom=obj.nom,
                description=obj.description,
                image=obj.image,
                disponibilite_globale=obj.disponibilite_globale,
                reservation=ReservationBrief(
                    id=res.id,
                    status=res.status,
                    date_debut=res.date_debut,
                    date_fin=res.date_fin,
                    nb_semaines=res.nb_semaines,
                    user_id=res.user_id,
                )
            ))
    return result


@router.post("/admin/objets/{objet_id}/valider")
def valider_objet(
    objet_id: int,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    """Valide un objet en_verification → le remet en stock disponible."""
    obj = session.get(Objet, objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")

    reservation = session.exec(
        select(Reservation).where(
            Reservation.objet_id == objet_id,
            Reservation.status == "en_verification"
        )
    ).first()

    if not reservation:
        raise HTTPException(status_code=404, detail="Aucune réservation en_verification pour cet objet")

    reservation.status = "terminee"
    session.add(reservation)

    obj.disponibilite_globale = True
    session.add(obj)
    session.commit()

    return {"message": f"Objet '{obj.nom}' validé et remis en stock", "objet_id": objet_id}


@router.post("/admin/objets/{objet_id}/mettre-en-maintenance")
def mettre_en_maintenance(
    objet_id: int,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    """Met un objet en maintenance (indisponible) après vérification."""
    obj = session.get(Objet, objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")

    reservation = session.exec(
        select(Reservation).where(
            Reservation.objet_id == objet_id,
            Reservation.status == "en_verification"
        )
    ).first()

    if reservation:
        reservation.status = "terminee"
        session.add(reservation)

    obj.disponibilite_globale = False
    session.add(obj)
    session.commit()

    return {"message": f"Objet '{obj.nom}' mis en maintenance", "objet_id": objet_id}


# --- Retrait / Retour (legacy, maintenant géré via scan) ---

@router.post("/objets/{objet_id}/retirer")
def retirer_objet(
    objet_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_point_relais)
):
    obj = session.get(Objet, objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")

    if current_user.is_admin:
        statement = select(Reservation).where(
            Reservation.objet_id == objet_id,
            Reservation.status == "mis_a_disposition",
        )
    else:
        user_lieux_ids = [lieu.id for lieu in current_user.lieux]
        if not user_lieux_ids:
            raise HTTPException(status_code=403, detail="Aucun lieu associé à ce point relais")
        statement = select(Reservation).where(
            Reservation.objet_id == objet_id,
            Reservation.status == "mis_a_disposition",
            Reservation.lieu_id.in_(user_lieux_ids)
        )

    reservation = session.exec(statement).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Aucune réservation mis_a_disposition pour cet objet")

    reservation.status = "retire"
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

    if not current_user.is_admin:
        user_lieux_ids = [lieu.id for lieu in current_user.lieux]
        if lieu_id not in user_lieux_ids:
            raise HTTPException(status_code=403, detail="Lieu non autorisé pour ce point relais")

    statement = select(Reservation).where(
        Reservation.objet_id == objet_id,
        Reservation.status.in_(["retire", "mis_a_disposition"])
    )
    reservation = session.exec(statement).first()

    if reservation:
        reservation.status = "restitue"
        session.add(reservation)

    obj.current_lieu_id = lieu_id
    session.add(obj)
    session.commit()

    return {"message": "Objet retourné", "objet_id": obj.id, "current_lieu_id": lieu_id}
