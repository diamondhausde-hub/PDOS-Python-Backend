"""routers/centers_router.py — /centers/*"""
import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

import models, schemas, auth
from database import get_db
from routers.deps import (
    get_role_scoped_rep_ids,
    dispatch_notification_sync,
    create_activity_log,
    get_setting,
)

router = APIRouter()


@router.get("/centers", response_model=List[schemas.CenterResponse])
def get_centers(db: Session = Depends(get_db), current_user: models.User = Depends(auth.require_password_set)):
    query = db.query(models.Center).filter(models.Center.is_active == True)
    # Brand isolation — brand-bound users (supervisor/rep) only see their
    # own brand's centers; admin/GM see everything.
    if current_user.brand_id:
        query = query.filter(models.Center.brand_id == current_user.brand_id)
    return query.all()


@router.post("/centers", response_model=schemas.CenterResponse)
def create_center(
    payload: schemas.CenterCreate,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    if current_user.role in ("admin", "general_manager"):
        raise HTTPException(status_code=403, detail="Only supervisors and reps can create centers")
    brand_id = current_user.brand_id
    if not brand_id:
        raise HTTPException(status_code=422, detail="Your account has no brand assigned")

    if payload.latitude and payload.longitude:
        existing = db.query(models.Center).filter(
            models.Center.name == payload.name,
            models.Center.brand_id == brand_id,
            models.Center.latitude.between(payload.latitude - 0.0005, payload.latitude + 0.0005),
            models.Center.longitude.between(payload.longitude - 0.0005, payload.longitude + 0.0005),
            models.Center.is_active == True,
        ).first()
    else:
        existing = db.query(models.Center).filter(
            models.Center.name == payload.name,
            models.Center.brand_id == brand_id,
            models.Center.is_active == True,
        ).first()
    if existing:
        return existing

    new_center = models.Center(
        name=payload.name, region=payload.region,
        latitude=payload.latitude, longitude=payload.longitude,
        address=payload.address, assigned_rep_id=payload.assigned_rep_id,
        brand_id=brand_id, created_by=current_user.id,
    )
    db.add(new_center)
    db.commit()
    db.refresh(new_center)
    
    create_activity_log(db, current_user.id, current_user.full_name, f"Added a new center: {new_center.name}", "user", new_center.id)
    
    return new_center


@router.put("/centers/{center_id}", response_model=schemas.CenterResponse)
def update_center(
    center_id: str,
    payload: schemas.CenterUpdate,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to update centers")
    center = db.query(models.Center).filter(models.Center.id == center_id).first()
    if not center:
        raise HTTPException(status_code=404, detail="Center not found")
    if payload.name is not None: center.name = payload.name
    if payload.region is not None: center.region = payload.region
    if payload.latitude is not None: center.latitude = payload.latitude
    if payload.longitude is not None: center.longitude = payload.longitude
    if payload.address is not None: center.address = payload.address
    if payload.assigned_rep_id is not None: center.assigned_rep_id = payload.assigned_rep_id
    if payload.is_active is not None: center.is_active = payload.is_active
    db.commit()
    db.refresh(center)
    return center


@router.delete("/centers/{center_id}")
def delete_center(
    center_id: str,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to delete centers")
    center = db.query(models.Center).filter(models.Center.id == center_id).first()
    if not center:
        raise HTTPException(status_code=404, detail="Center not found")
    center.is_active = False
    db.commit()
    return {"message": "Center deleted successfully"}


@router.post("/centers/{center_id}/report")
def report_center(
    center_id: str,
    payload: schemas.NoteCreate,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    center = db.query(models.Center).filter(models.Center.id == center_id).first()
    if not center:
        raise HTTPException(status_code=404, detail="Center not found")
    # NOTE: centers have a plain name (doctor_name/facility_name live on Client)
    name = center.name or "Unnamed center"
    if current_user.supervisor_id:
        dispatch_notification_sync(
            db, user_id=current_user.supervisor_id, type="center_report",
            title=f"تقرير عن مركز من {current_user.full_name}",
            message=f"{name}: {payload.content}", related_id=center_id,
        )
    create_activity_log(
        db, user_id=current_user.id, user_name=current_user.full_name,
        action=f"Center Report — {name}: {payload.content}",
    )
    return {"message": "Report sent successfully"}


@router.get("/centers/coverage", response_model=List[schemas.CenterCoverageResponse])
def get_coverage(
    brand_id: Optional[str] = None,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    rep_ids = get_role_scoped_rep_ids(current_user, db)
    neglect_days = int(get_setting(db, "coverage_neglect_days", 14))

    q_centers = db.query(models.Center).filter(models.Center.is_active == True)
    if brand_id:
        q_centers = q_centers.filter(models.Center.brand_id == brand_id)

    result = []
    for c in q_centers.all():
        q = db.query(func.max(models.Visit.visit_date)).filter(
            models.Visit.center_id == c.id,
            models.Visit.status.notin_(["rejected", "flagged"]),
        )
        if rep_ids is not None:
            q = q.filter(models.Visit.rep_id.in_(rep_ids))
        last_visit = q.scalar()

        status = "neglected"
        if last_visit:
            days_since = (datetime.date.today() - last_visit.date()).days
            if days_since <= neglect_days:
                status = "visited"

        note_visit = db.query(models.Visit).filter(
            models.Visit.center_id == c.id,
            models.Visit.review_note.isnot(None),
            models.Visit.review_note != "",
        ).order_by(models.Visit.reviewed_at.desc()).first()

        result.append({
            "center_id": c.id, "name": c.name, "lat": c.latitude, "lng": c.longitude,
            "last_visit_date": last_visit, "assigned_rep_id": c.assigned_rep_id,
            "status": status, "has_supervisor_note": note_visit is not None,
            "supervisor_note": note_visit.review_note if note_visit else None,
        })
    return result


@router.get("/centers/{center_id}", response_model=schemas.CenterResponse)
def get_center(
    center_id: str,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    center = db.query(models.Center).filter(models.Center.id == center_id, models.Center.is_active == True).first()
    if not center:
        raise HTTPException(status_code=404, detail="Center not found")
    if current_user.brand_id and center.brand_id != current_user.brand_id:
        raise HTTPException(status_code=403, detail="Center belongs to a different brand")
    return center
