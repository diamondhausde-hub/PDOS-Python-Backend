"""routers/users_router.py — /users/*, /settings/*"""
import datetime
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

import models, schemas, auth
from database import get_db
from routers.deps import (
    get_role_scoped_rep_ids,
    dispatch_notification_sync,
    ALLOWED_TYPES, MAX_SIZE,
)

router = APIRouter()

SETTING_BOUNDS = {
    "geofence_radius_meters": (50.0, 5000.0),
    "coverage_neglect_days": (1.0, 90.0),
    "max_shelf_photos_per_visit": (1.0, 20.0),
}


# ── FCM tokens ──────────────────────────────────────────────
@router.post("/users/me/fcm-tokens")
def register_fcm_token(
    payload: schemas.FCMTokenCreate,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    existing = db.query(models.FCMToken).filter(models.FCMToken.token == payload.token).first()
    if existing:
        existing.user_id = current_user.id
        existing.updated_at = datetime.datetime.now(datetime.timezone.utc)
    else:
        db.add(models.FCMToken(user_id=current_user.id, token=payload.token))
    db.commit()
    return {"message": "Token registered"}


@router.delete("/users/me/fcm-tokens")
def unregister_fcm_token(
    token: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    db.query(models.FCMToken).filter(
        models.FCMToken.token == token,
        models.FCMToken.user_id == current_user.id,
    ).delete()
    db.commit()
    return {"message": "Token unregistered"}


# ── Profile & Location ───────────────────────────────────────
@router.get("/users/me", response_model=schemas.UserResponse)
def read_users_me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user


@router.put("/users/me/location")
def update_my_location(
    payload: schemas.LocationUpdate,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    current_user.last_lat = payload.lat
    current_user.last_lng = payload.lng
    current_user.last_location_update = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    return {"message": "Location updated"}


@router.put("/users/me/password")
def update_password(
    data: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    new_password = data.get("password")
    if not new_password:
        raise HTTPException(status_code=400, detail="Password is required")
    if len(new_password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    # SECURITY: require the current password for normal changes; the
    # first-login flow (temporary password) is exempt since the user just
    # authenticated with it.
    if not current_user.must_change_password:
        current_password = data.get("current_password")
        if not current_password:
            raise HTTPException(status_code=400, detail="Current password is required")
        if not auth.verify_password(current_password, current_user.hashed_password):
            raise HTTPException(status_code=403, detail="Current password is incorrect")
    current_user.hashed_password = auth.get_password_hash(new_password)
    current_user.must_change_password = False
    db.commit()
    return {"message": "Password updated successfully"}


@router.patch("/users/me/profile", response_model=schemas.UserResponse)
def update_own_profile(
    data: schemas.ProfileUpdate,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    if data.full_name is not None:
        current_user.full_name = data.full_name
    if data.phone is not None:
        current_user.phone = data.phone
    if data.region is not None:
        current_user.region = data.region
    if data.profile_image_url is not None:
        current_user.profile_image_url = data.profile_image_url
    if data.current_password and data.new_password:
        if not auth.verify_password(data.current_password, current_user.hashed_password):
            raise HTTPException(status_code=403, detail="Current password is incorrect")
        current_user.hashed_password = auth.get_password_hash(data.new_password)
        current_user.must_change_password = False
    db.commit()
    db.refresh(current_user)
    return current_user

# ── User Signatures ──────────────────────────────────────────
from fastapi import UploadFile, File
import os
import shutil

@router.post("/users/me/signatures", response_model=schemas.UserSignatureResponse)
async def upload_signature(
    file: UploadFile = File(...),
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")
    
    file_id = str(uuid4())
    ext = file.filename.split('.')[-1] if '.' in file.filename else 'png'
    filename = f"{file_id}.{ext}"
    local_path = f"uploads/signatures/{filename}"
    
    with open(local_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    url = f"/uploads/signatures/{filename}"
    
    # Check if signature exists, if so delete old file
    sig = db.query(models.UserSignature).filter(models.UserSignature.user_id == current_user.id).first()
    if sig:
        old_path = sig.image_url.lstrip("/")
        if os.path.exists(old_path):
            os.remove(old_path)
        sig.image_url = url
    else:
        sig = models.UserSignature(
            user_id=current_user.id,
            image_url=url,
        )
        db.add(sig)
        
    db.commit()
    db.refresh(sig)
    return sig

@router.get("/users/me/signatures", response_model=schemas.UserSignatureResponse)
def get_signature(
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    sig = db.query(models.UserSignature).filter(models.UserSignature.user_id == current_user.id).first()
    if not sig:
        raise HTTPException(status_code=404, detail="Signature not found")
    return sig

@router.delete("/users/me/signatures")
def delete_signature(
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    sig = db.query(models.UserSignature).filter(models.UserSignature.user_id == current_user.id).first()
    if not sig:
        raise HTTPException(status_code=404, detail="Signature not found")
        
    old_path = sig.image_url.lstrip("/")
    if os.path.exists(old_path):
        os.remove(old_path)
        
    db.delete(sig)
    db.commit()
    return {"status": "ok"}

# ── User CRUD ────────────────────────────────────────────────
@router.post("/users", response_model=schemas.UserResponse)
def create_user(
    payload: schemas.UserCreate,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only Admin can create users")

    if payload.role in ("supervisor", "rep"):
        if not payload.brand_id:
            raise HTTPException(status_code=422, detail="brand_id is required for supervisor and rep accounts")
        brand = db.query(models.Brand).filter(models.Brand.id == payload.brand_id).first()
        if not brand:
            raise HTTPException(status_code=404, detail="Brand not found")
        if payload.role == "rep" and payload.supervisor_id:
            sup = db.query(models.User).filter(models.User.id == payload.supervisor_id).first()
            if not sup or sup.brand_id != payload.brand_id:
                raise HTTPException(status_code=422, detail="Supervisor must belong to the same brand")
    elif payload.role in ("admin", "general_manager"):
        if payload.brand_id:
            raise HTTPException(status_code=422, detail="admin and general_manager accounts must not have a brand_id")

    new_user = models.User(
        id=str(uuid4()),
        email=payload.email,
        full_name=payload.full_name,
        role=payload.role,
        phone=payload.phone,
        region=payload.region,
        supervisor_id=payload.supervisor_id,
        brand_id=payload.brand_id,
        hashed_password=auth.get_password_hash(payload.temporary_password),
        must_change_password=True,
        created_by=current_user.id,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.get("/users", response_model=List[schemas.UserResponse])
def get_users(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
    brand_id: Optional[str] = None,
    role: Optional[str] = None,
):
    query = db.query(models.User)
    if current_user.role == "supervisor":
        query = query.filter(models.User.supervisor_id == current_user.id)
    elif current_user.role in ("general_manager", "admin"):
        if brand_id:
            query = query.filter(models.User.brand_id == brand_id)
    else:
        query = query.filter(models.User.id == current_user.id)
    if role:
        query = query.filter(models.User.role == role)
    return query.all()


@router.get("/users/team-directory", response_model=List[schemas.TeamDirectoryResponse])
def get_team_directory(
    brand_id: Optional[str] = None,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("admin", "general_manager"):
        raise HTTPException(status_code=403, detail="Not authorized")
    query = db.query(models.User).filter(models.User.role == "supervisor")
    if brand_id:
        query = query.filter(models.User.brand_id == brand_id)
    supervisors = query.all()
    result = []
    for sup in supervisors:
        reps = db.query(models.User).filter(
            models.User.role == "rep",
            models.User.supervisor_id == sup.id,
        ).all()
        result.append({"supervisor": sup, "reps": reps})
    return result


@router.get("/users/team/locations", response_model=List[schemas.UserResponse])
def get_team_locations(
    brand_id: Optional[str] = None,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    rep_ids = get_role_scoped_rep_ids(current_user, db)
    query = db.query(models.User).filter(
        models.User.role == "rep",
        models.User.last_lat.isnot(None),
    )
    if rep_ids is not None:
        query = query.filter(models.User.id.in_(rep_ids))
    if brand_id:
        query = query.filter(models.User.brand_id == brand_id)
    return query.all()


@router.get("/users/{user_id}/public-profile", response_model=schemas.PublicProfileResponse)
def get_public_profile(
    user_id: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if current_user.role != "general_manager" and current_user.brand_id != target.brand_id:
        raise HTTPException(status_code=403, detail="Cross-brand profile access denied")

    completed_visits = db.query(models.Visit).filter(
        models.Visit.rep_id == user_id, models.Visit.status == "completed"
    ).count()

    target_total = db.query(func.sum(models.Target.target_qty)).filter(models.Target.rep_id == user_id).scalar() or 0
    achieved_total = 0
    for t in db.query(models.Target).filter(models.Target.rep_id == user_id).all():
        achieved_total += db.query(func.sum(models.VisitItem.qty_sold)).join(models.Visit).filter(
            models.VisitItem.product_id == t.product_id,
            models.Visit.rep_id == user_id,
            models.Visit.visit_date.between(t.period_start, t.period_end),
            models.Visit.status.notin_(["flagged", "rejected"]),
        ).scalar() or 0
    target_achievement_pct = round((achieved_total / target_total) * 100, 1) if target_total > 0 else 0.0

    team_count = db.query(models.User).filter(
        models.User.supervisor_id == user_id, models.User.role == "rep"
    ).count()

    brand_name = None
    if target.brand_id:
        brand = db.query(models.Brand).filter(models.Brand.id == target.brand_id).first()
        if brand:
            brand_name = brand.name

    return schemas.PublicProfileResponse(
        id=target.id,
        full_name=target.full_name,
        profile_image_url=target.profile_image_url,
        role=target.role,
        brand_id=target.brand_id,
        brand_name=brand_name,
        supervisor_id=target.supervisor_id,
        completed_visits=completed_visits,
        target_achievement_pct=target_achievement_pct,
        team_count=team_count,
    )


@router.get("/users/{user_id}", response_model=schemas.UserResponse)
def get_user_by_id(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # SECURITY: role-scoped access (was IDOR — any rep could read any user,
    # including live GPS coordinates)
    if current_user.role == "rep":
        if user.id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized to view this user")
    elif current_user.role == "supervisor":
        if user.supervisor_id != current_user.id and user.id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized to view this user")
    return user


@router.post("/users/{user_id}/request-deactivation")
def request_deactivation(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    if current_user.role != "general_manager":
        raise HTTPException(status_code=403, detail="Only general managers can request deactivation")
    target_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")
    for admin in db.query(models.User).filter(models.User.role == "admin").all():
        dispatch_notification_sync(
            db=db, user_id=admin.id, type="deactivation_request",
            title="Account Deactivation Request",
            message=f"GM {current_user.full_name} requested to deactivate {target_user.full_name} ({target_user.email}).",
            related_id=user_id,
        )
    return {"message": "Deactivation request sent to admins"}


@router.put("/users/{user_id}")
def update_user(
    user_id: str,
    data: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can update users")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if data.full_name is not None: user.full_name = data.full_name
    if data.phone is not None: user.phone = data.phone
    if data.region is not None: user.region = data.region
    if data.supervisor_id is not None: user.supervisor_id = data.supervisor_id
    if data.profile_image_url is not None: user.profile_image_url = data.profile_image_url
    if data.has_completed_onboarding is not None: user.has_completed_onboarding = data.has_completed_onboarding
    if data.is_active is not None:
        if user_id == current_user.id and not data.is_active:
            raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
        user.is_active = data.is_active
    db.commit()
    return {"message": "User updated"}


# ── Settings ─────────────────────────────────────────────────
@router.get("/settings", response_model=List[schemas.SystemSettingResponse])
def get_settings(
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.SystemSetting).all()


@router.put("/settings/{key}", response_model=schemas.SystemSettingResponse)
def update_setting(
    key: str,
    payload: schemas.SystemSettingUpdate,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized")
    if key in SETTING_BOUNDS:
        low, high = SETTING_BOUNDS[key]
        try:
            float_val = float(payload.value)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"{key} must be a number")
        if not (low <= float_val <= high):
            raise HTTPException(status_code=422, detail=f"{key} must be between {low} and {high}")
    setting = db.query(models.SystemSetting).filter(models.SystemSetting.key == key).first()
    if not setting:
        setting = models.SystemSetting(key=key, value=str(payload.value))
        db.add(setting)
    else:
        setting.value = str(payload.value)
    db.commit()
    db.refresh(setting)
    return setting
