"""routers/auth_router.py — /health, /auth/login, /auth/invite"""
import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

import models, schemas, auth
from database import get_db
from routers.deps import limiter

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/auth/login", response_model=schemas.Token)
@limiter.limit("10/minute")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    request: Request = None,
):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    expires = datetime.timedelta(minutes=auth.ACCESS_TOKEN_EXPIRE_MINUTES)
    token = auth.create_access_token(data={"sub": user.id, "role": user.role}, expires_delta=expires)
    return {"access_token": token, "token_type": "bearer", "user": user}


@router.post("/auth/invite", response_model=schemas.UserResponse)
def invite_user(
    user: schemas.UserCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    if current_user.role not in ["admin", "general_manager"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    if db.query(models.User).filter(models.User.email == user.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    new_user = models.User(
        email=user.email,
        hashed_password=auth.get_password_hash(user.temporary_password),
        full_name=user.full_name,
        role=user.role,
        region=user.region,
        supervisor_id=user.supervisor_id,
        must_change_password=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user
