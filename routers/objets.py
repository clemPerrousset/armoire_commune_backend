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
    UserObjetHistoriqueLink, UserObjetFavorisLink, Lieu, UserLieuLink, Tag, ObjetTagLink,
    STATUTS_BLOQUANTS, STATUT_SUIVANT
)
from auth import get_current_admin, get_current_user_optional, get_current_point_relais, get_current_user

IMAGE_DIR = "/data/images"
MAX_SIZE = (1200, 1200)  # assez grand pour l'affichage plein écran
JPEG_QUALITY = 75

router = APIRouter(tags=["Objets"])


class ObjetCreate(SQLModel):
    nom: str
    description: str
    image: Optional[str] = None
    tag_id: Optional[int] = None          # ancien champ (catégorie unique) — toujours accepté
    tag_ids: List[int] = []               # catégories multiples
    association_id: Optional[int] = None
    consommable_ids: List[int] = []
    disponibilite_globale: bool = True
    stockage: Optional[str] = None


class ObjetUpdate(SQLModel):
    """Modification partielle : seuls les champs fournis sont changés."""
    nom: Optional[str] = None
    description: Optional[str] = None
    tag_ids: Optional[List[int]] = None
    consommable_ids: Optional[List[int]] = None
    stockage: Optional[str] = None


class TagOut(BaseModel):
    id: int
    nom: str


class ConsommableOut(BaseModel):
    id: int
    nom: str
    description: Optional[str] = None
    quantite: int = 0
    prix: float
    image: Optional[str] = None
    url: Optional[str] = None


class ObjetRead(BaseModel):
    id: int
    nom: str
    description: str
    image: Optional[str] = None
    disponibilite_globale: bool
    alert: bool
    current_lieu_id: Optional[int] = None
    tag_id: Optional[int] = None
    tag: Optional[TagOut] = None
    tags: List[TagOut] = []
    consommables: List[ConsommableOut] = []
    stockage: Optional[str] = None  # renseigné uniquement pour les admins


def objet_to_read(obj: Objet, is_admin: bool = False) -> ObjetRead:
    tags = list(obj.tags)
    # Objets créés avant les catégories multiples : on retombe sur la catégorie unique
    if not tags and obj.tag is not None:
        tags = [obj.tag]
    return ObjetRead(
        id=obj.id,
        nom=obj.nom,
        description=obj.description,
        image=obj.image,
        disponibilite_globale=obj.disponibilite_globale,
        alert=obj.alert,
        current_lieu_id=obj.current_lieu_id,
        tag_id=obj.tag_id,
        tag=TagOut(id=obj.tag.id, nom=obj.tag.nom) if obj.tag else None,
        tags=[TagOut(id=t.id, nom=t.nom) for t in tags],
        consommables=[
            ConsommableOut(
                id=c.id, nom=c.nom, description=c.description, quantite=c.quantite,
                prix=c.prix, image=c.image, url=c.url,
            )
            for c in obj.consommables
        ],
        stockage=obj.stockage if is_admin else None,
    )


def _apply_tags(session: Session, obj: Objet, tag_ids: List[int]):
    """Remplace les catégories de l'objet ; la première devient la catégorie principale (tag_id)."""
    ids = list(dict.fromkeys(tag_ids))
    for tid in ids:
        if not session.get(Tag, tid):
            raise HTTPException(status_code=404, detail=f"Catégorie {tid} introuvable")
    for link in session.exec(select(ObjetTagLink).where(ObjetTagLink.objet_id == obj.id)).all():
        session.delete(link)
    session.flush()
    for tid in ids:
        session.add(ObjetTagLink(objet_id=obj.id, tag_id=tid))
    obj.tag_id = ids[0] if ids else None
    session.add(obj)


def _apply_consommables(session: Session, obj: Objet, consommable_ids: List[int]):
    for link in session.exec(select(ObjetConsommableLink).where(ObjetConsommableLink.objet_id == obj.id)).all():
        session.delete(link)
    session.flush()
    for c_id in dict.fromkeys(consommable_ids):
        if not session.get(Consommable, c_id):
            raise HTTPException(status_code=404, detail=f"Consommable {c_id} introuvable")
        session.add(ObjetConsommableLink(objet_id=obj.id, consommable_id=c_id))


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


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _is_available_for_week(obj: Objet, date_debut: datetime, date_fin: datetime) -> bool:
    """Libre = aucune réservation bloquante sur la période. Les congés de l'équipe
    ne comptent pas : ils prolongent la réservation au lieu de l'empêcher."""
    date_debut, date_fin = _naive(date_debut), _naive(date_fin)
    for res in obj.reservations:
        if res.status in STATUTS_BLOQUANTS:
            if _naive(res.date_debut) < date_fin and _naive(res.date_fin) > date_debut:
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

@router.post("/objets", response_model=ObjetRead)
def create_objet(
    objet_in: ObjetCreate,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    objet_data = objet_in.model_dump(exclude={"consommable_ids", "tag_ids", "tag_id"})
    db_objet = Objet(**objet_data)
    session.add(db_objet)
    session.commit()
    session.refresh(db_objet)

    tag_ids = objet_in.tag_ids or ([objet_in.tag_id] if objet_in.tag_id else [])
    _apply_tags(session, db_objet, tag_ids)
    _apply_consommables(session, db_objet, objet_in.consommable_ids)

    session.commit()
    session.refresh(db_objet)
    return objet_to_read(db_objet, is_admin=True)


@router.put("/admin/objets/{objet_id}", response_model=ObjetRead)
def update_objet(
    objet_id: int,
    objet_in: ObjetUpdate,
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    obj = session.get(Objet, objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")

    fields = objet_in.model_dump(exclude_unset=True)
    for key in ("nom", "description", "stockage"):
        if key in fields:
            setattr(obj, key, fields[key])
    session.add(obj)

    if objet_in.tag_ids is not None:
        _apply_tags(session, obj, objet_in.tag_ids)
    if objet_in.consommable_ids is not None:
        _apply_consommables(session, obj, objet_in.consommable_ids)

    session.commit()
    session.refresh(obj)
    return objet_to_read(obj, is_admin=True)


@router.get("/objets", response_model=List[ObjetRead])
def list_objets(
    nom: Optional[str] = None,
    tag_id: Optional[int] = None,
    available: bool = Query(False, description="True = uniquement disponibles, False = tous"),
    date_check: Optional[datetime] = None,
    session: Session = Depends(get_session),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    is_admin = bool(current_user and current_user.is_admin)
    query = select(Objet)
    if nom:
        query = query.where(Objet.nom.icontains(nom))
    if tag_id:
        # catégorie principale OU l'une des catégories associées
        tagged_ids = select(ObjetTagLink.objet_id).where(ObjetTagLink.tag_id == tag_id)
        query = query.where((Objet.tag_id == tag_id) | (Objet.id.in_(tagged_ids)))

    objets = session.exec(query).all()

    if not available:
        return [objet_to_read(o, is_admin) for o in objets]

    if not date_check:
        date_check = datetime.now()

    check_start = _next_thursday(date_check)
    check_end = check_start + timedelta(days=6)
    check_end = check_end.replace(hour=22, minute=0, second=0, microsecond=0)

    # Les congés de l'équipe ne rendent plus les objets indisponibles : la
    # réservation reste possible et est simplement prolongée (cf. reservations.py).
    return [
        objet_to_read(obj, is_admin) for obj in objets
        if obj.disponibilite_globale and _is_available_for_week(obj, check_start, check_end)
    ]


@router.get("/objets/{objet_id}", response_model=ObjetRead)
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

    return objet_to_read(obj, is_admin=bool(current_user and current_user.is_admin))


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

    # Nettoie les liens (catégories, consommables, favoris, historique) pour ne pas laisser d'orphelins
    for link_model in (ObjetTagLink, ObjetConsommableLink, UserObjetFavorisLink, UserObjetHistoriqueLink):
        for link in session.exec(select(link_model).where(link_model.objet_id == objet_id)).all():
            session.delete(link)
    nom = obj.nom
    session.delete(obj)
    session.commit()
    return {"ok": True, "message": f"Objet '{nom}' supprimé"}


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

@router.get("/admin/objets/alerts", response_model=List[ObjetRead])
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

    return [objet_to_read(o, True) for o in session.exec(select(Objet).where(Objet.id.in_(objet_ids))).all()]


# --- Objets en maintenance ---

@router.get("/admin/objets/maintenance", response_model=List[ObjetRead])
def list_objets_en_maintenance(
    session: Session = Depends(get_session),
    admin: User = Depends(get_current_admin)
):
    """Objets marqués indisponibles (maintenance) — à rescanner pour les remettre en service."""
    objets = session.exec(select(Objet)).all()
    return [objet_to_read(obj, True) for obj in objets if not obj.disponibilite_globale]


# --- QR Scan : avancement du statut ---

@router.post("/objets/{objet_id}/scan", response_model=ScanResult)
def scan_objet(
    objet_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_point_relais)
):
    """
    Scan du QR code d'un objet par un admin ou point_relais. Avance le statut
    de la réservation active au statut suivant, et met à jour la localisation
    physique de l'objet en conséquence.

    Un point relais (non-admin) ne peut faire avancer que le retrait
    (mis_a_disposition → retire) et la restitution (retire → restitue), et
    uniquement pour les réservations rattachées à l'un de ses lieux. La mise
    à disposition, la remise en service après maintenance et le passage en
    vérification restent réservés aux admins.
    """
    obj = session.get(Objet, objet_id)
    if not obj:
        raise HTTPException(status_code=404, detail="Objet not found")

    reservation = _get_reservation_active(objet_id, session)
    if not reservation:
        # Objet sans réservation en cours : s'il est indisponible (ex. maintenance),
        # le scan sert à confirmer qu'il est réparé/de retour et le remet en service.
        if not obj.disponibilite_globale:
            if not current_user.is_admin:
                raise HTTPException(status_code=403, detail="La remise en service est réservée à un administrateur")
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

    if not current_user.is_admin:
        if ancien_statut not in ("mis_a_disposition", "retire"):
            raise HTTPException(
                status_code=403,
                detail="Cette étape doit être effectuée par un administrateur"
            )
        user_lieux_ids = {lieu.id for lieu in current_user.lieux}
        if reservation.lieu_id not in user_lieux_ids:
            raise HTTPException(status_code=403, detail="Ce lieu n'est pas assigné à ce point relais")

    nouveau_statut = STATUT_SUIVANT[ancien_statut]
    reservation.status = nouveau_statut
    session.add(reservation)

    # Localisation physique de l'objet
    if nouveau_statut == "mis_a_disposition":
        obj.current_lieu_id = reservation.lieu_id  # posé au point relais, prêt pour le retrait
    elif nouveau_statut == "retire":
        obj.current_lieu_id = None  # parti avec l'utilisateur
    elif nouveau_statut == "restitue":
        obj.current_lieu_id = reservation.lieu_id  # de retour au point relais
    session.add(obj)

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

    # Ferme TOUTE réservation encore en cours pour cet objet, pas seulement
    # celle en en_verification : sinon une réservation restée bloquée à une
    # étape antérieure (ex: restitue) survit à la mise en maintenance et
    # ressort plus tard dans "à vérifier" quand l'objet est rescanné.
    reservations_en_cours = session.exec(
        select(Reservation).where(
            Reservation.objet_id == objet_id,
            Reservation.status.in_(STATUTS_BLOQUANTS)
        )
    ).all()

    for reservation in reservations_en_cours:
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
