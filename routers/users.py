from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select
from typing import List, Optional
from datetime import timedelta
from pydantic import BaseModel
import os

from database import get_session
from models import User, Objet, UserObjetFavorisLink, UserObjetHistoriqueLink, Lieu, UserLieuLink, Notification
from routers.objets import ObjetRead, objet_to_read
from datetime import datetime
from auth import get_password_hash, create_access_token, verify_password, get_current_admin, get_current_user, ACCESS_TOKEN_EXPIRE_MINUTES

router = APIRouter()

class UserCreate(BaseModel):
    nom: str
    prenom: str
    email: str
    password: str
    association_id: Optional[int] = None

class UserRead(BaseModel):
    id: int
    nom: str
    prenom: str
    email: str
    is_admin: bool
    is_point_relais: bool
    association_id: Optional[int] = None
    credits: int = 100
    # Vrai tant que le compte utilise le mot de passe initial (rappel sur l'accueil).
    has_default_password: bool = False

    class Config:
        from_attributes = True

class PasswordChange(BaseModel):
    current_password: str
    new_password: str

class NotificationRead(BaseModel):
    id: int
    message: str
    created_at: datetime

    class Config:
        from_attributes = True

class Token(BaseModel):
    access_token: str
    token_type: str

class SuperPromoteRequest(BaseModel):
    email: str
    password: str
    is_admin: bool

class SuperPasswordRequest(BaseModel):
    password: str

@router.post("/auth/signup", response_model=UserRead)
def create_user(user: UserCreate, session: Session = Depends(get_session)):
    # Check if user exists
    existing_user = session.exec(select(User).where(User.email == user.email)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = get_password_hash(user.password)
    db_user = User(
        nom=user.nom,
        prenom=user.prenom,
        email=user.email,
        password_hash=hashed_password,
        is_admin=False,
        association_id=user.association_id
    )
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user

@router.post("/auth/login", response_model=Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_session)):
    # OAuth2PasswordRequestForm expects username and password
    user = session.exec(select(User).where(User.email == form_data.username)).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

DEFAULT_PASSWORD = "123456"
MIN_PASSWORD_LENGTH = 6

@router.get("/users/me", response_model=UserRead)
def read_users_me(current_user: User = Depends(get_current_user)):
    data = UserRead.model_validate(current_user)
    data.has_default_password = verify_password(DEFAULT_PASSWORD, current_user.password_hash)
    return data

@router.put("/users/me/password")
def change_password(
    payload: PasswordChange,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect")
    if len(payload.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Le mot de passe doit contenir au moins {MIN_PASSWORD_LENGTH} caractères")
    if payload.new_password == DEFAULT_PASSWORD:
        raise HTTPException(status_code=400, detail="Choisissez un mot de passe différent du mot de passe initial")
    current_user.password_hash = get_password_hash(payload.new_password)
    session.add(current_user)
    session.commit()
    return {"ok": True}

@router.post("/users/favoris/{objet_id}")
def add_favori(objet_id: int, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    objet = session.get(Objet, objet_id)
    if not objet:
        raise HTTPException(status_code=404, detail="Objet not found")

    link = session.exec(select(UserObjetFavorisLink).where(
        UserObjetFavorisLink.user_id == current_user.id,
        UserObjetFavorisLink.objet_id == objet_id
    )).first()

    if link:
        return {"message": "Objet already in favorites"}

    new_link = UserObjetFavorisLink(user_id=current_user.id, objet_id=objet_id)
    session.add(new_link)
    session.commit()
    return {"message": "Objet added to favorites"}

@router.delete("/users/favoris/{objet_id}")
def remove_favori(objet_id: int, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    link = session.exec(select(UserObjetFavorisLink).where(
        UserObjetFavorisLink.user_id == current_user.id,
        UserObjetFavorisLink.objet_id == objet_id
    )).first()

    if not link:
        raise HTTPException(status_code=404, detail="Objet not found in favorites")

    session.delete(link)
    session.commit()
    return {"message": "Objet removed from favorites"}

@router.get("/users/favoris", response_model=List[ObjetRead])
def list_favoris(session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    statement = select(Objet).join(UserObjetFavorisLink).where(UserObjetFavorisLink.user_id == current_user.id)
    favoris = session.exec(statement).all()
    return [objet_to_read(o, current_user.is_admin) for o in favoris]

@router.get("/users/notifications", response_model=List[NotificationRead])
def list_notifications(session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    """Notifications non lues de l'utilisateur (ex. réservation prolongée pour cause de congé)."""
    return session.exec(
        select(Notification)
        .where(Notification.user_id == current_user.id, Notification.lu == False)  # noqa: E712
        .order_by(Notification.created_at)
    ).all()

@router.post("/users/notifications/{notification_id}/lu")
def mark_notification_read(notification_id: int, session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    notif = session.get(Notification, notification_id)
    if not notif or notif.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.lu = True
    session.add(notif)
    session.commit()
    return {"ok": True}

@router.get("/users/historique", response_model=List[ObjetRead])
def list_historique(session: Session = Depends(get_session), current_user: User = Depends(get_current_user)):
    statement = (
        select(Objet)
        .join(UserObjetHistoriqueLink)
        .where(UserObjetHistoriqueLink.user_id == current_user.id)
        .order_by(UserObjetHistoriqueLink.date_consultation.desc())
    )
    historique = session.exec(statement).all()
    return [objet_to_read(o, current_user.is_admin) for o in historique]

@router.put("/admin/users/{user_id}/promote")
def promote_user(user_id: int, is_admin: bool, current_admin: User = Depends(get_current_admin), session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_admin = is_admin
    session.add(user)
    session.commit()
    return {"message": f"User {user.email} admin status set to {is_admin}"}

@router.put("/admin/users/{user_id}/promote-point-relais")
def promote_user_point_relais(user_id: int, is_point_relais: bool, current_admin: User = Depends(get_current_admin), session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_point_relais = is_point_relais
    session.add(user)
    session.commit()
    return {"message": f"User {user.email} point relais status set to {is_point_relais}"}

@router.post("/admin/users/super-promote")
def promote_user_super(
    request: SuperPromoteRequest,
    session: Session = Depends(get_session)
):
    super_password = os.getenv("superUserPassword")
    if not super_password or request.password != super_password:
         raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials"
        )

    user = session.exec(select(User).where(User.email == request.email)).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_admin = request.is_admin
    session.add(user)
    session.commit()
    return {"message": f"User {user.email} admin status set to {request.is_admin}"}

@router.post("/admin/users/super-list-admins", response_model=List[UserRead])
def list_admins_super(
    request: SuperPasswordRequest,
    session: Session = Depends(get_session)
):
    super_password = os.getenv("superUserPassword")
    if not super_password or request.password != super_password:
         raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials"
        )

    admins = session.exec(select(User).where(User.is_admin == True)).all()
    return admins


@router.post("/admin/users/{user_id}/lieux/{lieu_id}")
def assign_lieu_to_user(user_id: int, lieu_id: int, current_admin: User = Depends(get_current_admin), session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    lieu = session.get(Lieu, lieu_id)
    if not lieu:
        raise HTTPException(status_code=404, detail="Lieu not found")

    link = session.exec(select(UserLieuLink).where(
        UserLieuLink.user_id == user_id,
        UserLieuLink.lieu_id == lieu_id
    )).first()

    if link:
        return {"message": "Lieu already assigned to user"}

    new_link = UserLieuLink(user_id=user_id, lieu_id=lieu_id)
    session.add(new_link)
    session.commit()
    return {"message": f"Lieu {lieu.nom} assigned to User {user.email}"}

@router.delete("/admin/users/{user_id}/lieux/{lieu_id}")
def remove_lieu_from_user(user_id: int, lieu_id: int, current_admin: User = Depends(get_current_admin), session: Session = Depends(get_session)):
    link = session.exec(select(UserLieuLink).where(
        UserLieuLink.user_id == user_id,
        UserLieuLink.lieu_id == lieu_id
    )).first()

    if not link:
        raise HTTPException(status_code=404, detail="Lieu not assigned to this user")

    session.delete(link)
    session.commit()
    return {"message": "Lieu removed from user"}
