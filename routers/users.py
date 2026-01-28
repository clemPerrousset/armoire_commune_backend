from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import Session, select
from typing import List, Optional
from datetime import timedelta
from pydantic import BaseModel
import os

from database import get_session
from models import User
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
    association_id: Optional[int] = None

class Token(BaseModel):
    access_token: str
    token_type: str

class SuperPromoteRequest(BaseModel):
    password: str
    is_admin: bool

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

@router.get("/users/me", response_model=UserRead)
def read_users_me(current_user: User = Depends(get_current_user)):
    return current_user

@router.put("/admin/users/{user_id}/promote")
def promote_user(user_id: int, is_admin: bool, current_admin: User = Depends(get_current_admin), session: Session = Depends(get_session)):
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_admin = is_admin
    session.add(user)
    session.commit()
    return {"message": f"User {user.email} admin status set to {is_admin}"}

@router.post("/admin/users/{user_id}/super-promote")
def promote_user_super(
    user_id: int,
    request: SuperPromoteRequest,
    session: Session = Depends(get_session)
):
    super_password = os.getenv("superUserPassword")
    if not super_password or request.password != super_password:
         raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials"
        )

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_admin = request.is_admin
    session.add(user)
    session.commit()
    return {"message": f"User {user.email} admin status set to {request.is_admin}"}
