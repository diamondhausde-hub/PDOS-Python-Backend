"""routers/misc_router.py — notes, targets, brands, clients, field-reports, logs"""
import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session
from sqlalchemy import func

import models, schemas, auth
from database import get_db
from routers.deps import (
    get_role_scoped_rep_ids,
    dispatch_notification_sync,
    create_activity_log,
    ALLOWED_TYPES, MAX_SIZE, store_file_locally,
)

router = APIRouter()


# ── Notes ────────────────────────────────────────────────────
def _note_response_models(notes, db):
    cache = {}
    for n in notes:
        for uid, attr in ((n.sender_id, "sender"), (n.recipient_id, "recipient")):
            if uid not in cache:
                u = db.query(models.User).filter(models.User.id == uid).first()
                cache[uid] = u.full_name if u else None
            setattr(n, f"{attr}_name", cache[uid])
    return notes


def _can_send_note_to(current_user: models.User, target: models.User) -> bool:
    if current_user.role == "admin":
        return True
    if current_user.role == "general_manager":
        return target.role in ("rep", "supervisor")
    if current_user.role == "supervisor":
        return target.role == "rep" and target.supervisor_id == current_user.id
    if current_user.role == "rep":
        return target.role == "supervisor" and current_user.supervisor_id == target.id
    return False


@router.post("/users/{user_id}/notes", response_model=schemas.NoteResponse)
def send_note(
    user_id: str,
    payload: schemas.NoteCreate,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if not _can_send_note_to(current_user, target):
        raise HTTPException(status_code=403, detail="You can only send notes to your team members")
    note = models.Note(
        sender_id=current_user.id, recipient_id=user_id,
        content=payload.content, visit_id=payload.visit_id or None,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    dispatch_notification_sync(
        db, user_id=user_id, type="direct_note",
        title=f"ملاحظة من {current_user.full_name}",
        message=payload.content, related_id=note.id,
    )
    _note_response_models([note], db)
    return note


@router.post("/reps/{rep_id}/notes", response_model=schemas.NoteResponse)
def send_note_to_rep(
    rep_id: str,
    payload: schemas.NoteCreate,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    """Backwards-compatible wrapper."""
    return send_note(rep_id, payload, current_user, db)


@router.get("/notes", response_model=List[schemas.NoteResponse])
def list_notes(
    user_id: Optional[str] = None,
    visit_id: Optional[str] = None,
    visit_center_id: Optional[str] = None,
    limit: int = 50,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    q = db.query(models.Note)
    if current_user.role == "rep":
        q = q.filter(
            (models.Note.sender_id == current_user.id) |
            (models.Note.recipient_id == current_user.id)
        )
    elif current_user.role == "supervisor":
        team_ids = [u.id for u in db.query(models.User).filter(models.User.supervisor_id == current_user.id).all()]
        team_ids.append(current_user.id)
        q = q.filter(
            (models.Note.sender_id.in_(team_ids)) |
            (models.Note.recipient_id.in_(team_ids))
        )
    if user_id:
        q = q.filter((models.Note.sender_id == user_id) | (models.Note.recipient_id == user_id))
    if visit_id:
        q = q.filter(models.Note.visit_id == visit_id)
    if visit_center_id:
        q = q.join(models.Visit, models.Note.visit_id == models.Visit.id).filter(
            models.Visit.center_id == visit_center_id
        )
    notes = q.order_by(models.Note.created_at.desc()).limit(min(limit, 200)).all()
    _note_response_models(notes, db)
    return notes


# ── Targets ──────────────────────────────────────────────────
def _assert_can_manage_target(current_user: models.User, target_rep_id: str, db: Session):
    if current_user.role == "admin":
        return
    if current_user.role == "supervisor":
        rep = db.query(models.User).filter(models.User.id == target_rep_id).first()
        if rep and rep.supervisor_id == current_user.id:
            return
    raise HTTPException(status_code=403, detail="Not authorized for this rep")


@router.get("/targets", response_model=List[schemas.TargetResponse])
def get_targets(brand_id: Optional[str] = None, db: Session = Depends(get_db), current_user: models.User = Depends(auth.require_password_set)):
    rep_ids = get_role_scoped_rep_ids(current_user, db)
    query = db.query(models.Target)
    if rep_ids is not None:
        query = query.filter(models.Target.rep_id.in_(rep_ids))
    if brand_id:
        query = query.filter(models.Target.brand_id == brand_id)
    results = []
    for t in query.all():
        achieved = db.query(func.sum(models.VisitItem.qty_sold)).join(models.Visit).filter(
            models.VisitItem.product_id == t.product_id,
            models.Visit.rep_id == t.rep_id,
            models.Visit.visit_date.between(t.period_start, t.period_end),
            models.Visit.status.notin_(["flagged", "rejected"]),
        ).scalar() or 0
        prod = db.query(models.Product).filter(models.Product.id == t.product_id).first()
        view_count = db.query(models.TargetView).filter(models.TargetView.target_id == t.id).count()
        user_viewed = db.query(models.TargetView).filter(
            models.TargetView.target_id == t.id,
            models.TargetView.rep_id == current_user.id,
        ).first() is not None
        results.append({**t.__dict__, "achieved_qty": achieved, "product_name": prod.name if prod else None,
                        "view_count": view_count, "user_viewed": user_viewed})
    return results


@router.post("/targets", response_model=schemas.TargetResponse)
def create_target(
    payload: schemas.TargetCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    _assert_can_manage_target(current_user, payload.rep_id, db)
    t = models.Target(
        product_id=payload.product_id, rep_id=payload.rep_id,
        period_start=payload.period_start, period_end=payload.period_end,
        target_qty=payload.target_qty, notes=payload.notes,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    prod = db.query(models.Product).filter(models.Product.id == payload.product_id).first()
    return {**t.__dict__, "achieved_qty": 0, "product_name": prod.name if prod else None, "view_count": 0}


@router.post("/targets/bulk")
def create_bulk_targets(
    payload: schemas.TargetBulkCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    if current_user.role not in ("admin", "supervisor"):
        raise HTTPException(status_code=403, detail="Not authorized")
    created_ids = []
    for rep_id in payload.rep_ids:
        # Same authorization as single-target creation — supervisors may
        # only assign targets to their own reps.
        _assert_can_manage_target(current_user, rep_id, db)
        t = models.Target(
            product_id=payload.product_id, rep_id=rep_id,
            period_start=payload.period_start, period_end=payload.period_end,
            target_qty=payload.target_qty, notes=payload.notes,
        )
        db.add(t)
        db.flush()
        created_ids.append(t.id)
    db.commit()
    return {"message": f"Created {len(created_ids)} targets", "target_ids": created_ids}


@router.put("/targets/{target_id}", response_model=schemas.TargetResponse)
def update_target(
    target_id: str,
    payload: schemas.TargetUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    t = db.query(models.Target).filter(models.Target.id == target_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Target not found")
    _assert_can_manage_target(current_user, t.rep_id, db)
    if payload.period_start: t.period_start = payload.period_start
    if payload.period_end: t.period_end = payload.period_end
    if payload.target_qty is not None: t.target_qty = payload.target_qty
    db.commit()
    db.refresh(t)
    achieved = db.query(func.sum(models.VisitItem.qty_sold)).join(models.Visit).filter(
        models.VisitItem.product_id == t.product_id,
        models.Visit.rep_id == t.rep_id,
        models.Visit.visit_date.between(t.period_start, t.period_end),
        models.Visit.status.notin_(["flagged", "rejected"]),
    ).scalar() or 0
    view_count = db.query(models.TargetView).filter(models.TargetView.target_id == t.id).count()
    prod = db.query(models.Product).filter(models.Product.id == t.product_id).first()
    return {**t.__dict__, "achieved_qty": achieved, "product_name": prod.name if prod else None, "view_count": view_count}


@router.delete("/targets/{target_id}")
def delete_target(target_id: str, db: Session = Depends(get_db), current_user: models.User = Depends(auth.require_password_set)):
    t = db.query(models.Target).filter(models.Target.id == target_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Target not found")
    _assert_can_manage_target(current_user, t.rep_id, db)
    db.delete(t)
    db.commit()
    return {"message": "Target deleted"}


@router.post("/targets/{target_id}/view")
def view_target(target_id: str, db: Session = Depends(get_db), current_user: models.User = Depends(auth.require_password_set)):
    t = db.query(models.Target).filter(models.Target.id == target_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Target not found")
    if not db.query(models.TargetView).filter(models.TargetView.target_id == target_id, models.TargetView.rep_id == current_user.id).first():
        db.add(models.TargetView(target_id=target_id, rep_id=current_user.id))
        db.commit()
    return {"message": "Target viewed"}


@router.get("/targets/{target_id}/views", response_model=List[schemas.TargetViewResponse])
def get_target_views(target_id: str, db: Session = Depends(get_db), current_user: models.User = Depends(auth.require_password_set)):
    if not db.query(models.Target).filter(models.Target.id == target_id).first():
        raise HTTPException(status_code=404, detail="Target not found")
    results = []
    for v in db.query(models.TargetView).filter(models.TargetView.target_id == target_id).all():
        rep = db.query(models.User).filter(models.User.id == v.rep_id).first()
        results.append({**v.__dict__, "rep_name": rep.full_name if rep else None})
    return results


# ── Clients ──────────────────────────────────────────────────
def _assert_can_touch_client(current_user: models.User, client: models.Client, db: Session):
    """Reps: own clients only. Supervisors: own + their reps' clients.
    Admin/GM: unrestricted."""
    if current_user.role in ("admin", "general_manager"):
        return
    if client.rep_id == current_user.id:
        return
    if current_user.role == "supervisor":
        rep = db.query(models.User).filter(models.User.id == client.rep_id).first()
        if rep and rep.supervisor_id == current_user.id:
            return
    raise HTTPException(status_code=403, detail="Not authorized")


@router.get("/clients", response_model=List[schemas.ClientResponse])
def get_clients(
    rep_id: Optional[str] = None,
    brand_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    query = db.query(models.Client)
    
    if current_user.role not in ("admin", "general_manager"):
        user_brand_ids = [b.id for b in current_user.brands]
        if current_user.brand_id and current_user.brand_id not in user_brand_ids:
            user_brand_ids.append(current_user.brand_id)
        query = query.filter(models.Client.brand_id.in_(user_brand_ids))
        
    if brand_id:
        query = query.filter(models.Client.brand_id == brand_id)
    if rep_id:
        query = query.filter(models.Client.rep_id == rep_id)
        
    return query.offset(offset).limit(limit).all()


@router.post("/clients", response_model=schemas.ClientResponse)
def create_client(
    payload: schemas.ClientCreate,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("admin", "rep", "supervisor"):
        raise HTTPException(status_code=403, detail="Not authorized")
    if current_user.role == "rep" and payload.rep_id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot create client for another rep")
    if current_user.role == "supervisor":
        # Supervisor can only create clients for themselves or their reps
        if payload.rep_id != current_user.id:
            rep = db.query(models.User).filter(models.User.id == payload.rep_id).first()
            if not rep or rep.supervisor_id != current_user.id:
                raise HTTPException(status_code=403, detail="Cannot create client for a rep not under your supervision")
    
    existing = db.query(models.Client).filter(models.Client.id == payload.id).first()
    if existing:
        return existing
    new_client = models.Client(**payload.dict())
    db.add(new_client)
    db.commit()
    db.refresh(new_client)
    
    target_name = new_client.doctor_name if new_client.client_type == 'doctor' else new_client.facility_name
    create_activity_log(db, current_user.id, current_user.full_name, f"Added a new {new_client.client_type}: {target_name}", "user", new_client.id)
    
    return new_client


@router.put("/clients/{client_id}", response_model=schemas.ClientResponse)
def update_client(
    client_id: str,
    payload: schemas.ClientCreate,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    client = db.query(models.Client).filter(models.Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _assert_can_touch_client(current_user, client, db)
    for key, value in payload.dict(exclude_unset=True).items():
        setattr(client, key, value)
    client.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    db.refresh(client)
    return client


@router.delete("/clients/{client_id}")
def delete_client(
    client_id: str,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    client = db.query(models.Client).filter(models.Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    _assert_can_touch_client(current_user, client, db)
    db.delete(client)
    db.commit()
    return {"message": "Client deleted"}


# ── Brands ───────────────────────────────────────────────────
@router.get("/brands", response_model=List[schemas.BrandResponse])
def get_brands(db: Session = Depends(get_db), current_user: models.User = Depends(auth.require_password_set)):
    return db.query(models.Brand).all()


@router.get("/brands/{brand_id}", response_model=schemas.BrandResponse)
def get_brand(brand_id: str, db: Session = Depends(get_db), current_user: models.User = Depends(auth.require_password_set)):
    b = db.query(models.Brand).filter(models.Brand.id == brand_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Brand not found")
    return b

@router.post("/brands", response_model=schemas.BrandResponse)
def create_brand(payload: schemas.BrandCreate, db: Session = Depends(get_db), current_user: models.User = Depends(auth.require_password_set)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    if db.query(models.Brand).filter(models.Brand.name == payload.name).first():
        raise HTTPException(status_code=400, detail="Brand name already exists")
    b = models.Brand(name=payload.name, logo_url=payload.logo_url)
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


@router.put("/brands/{brand_id}", response_model=schemas.BrandResponse)
def update_brand(brand_id: str, payload: schemas.BrandUpdate, db: Session = Depends(get_db), current_user: models.User = Depends(auth.require_password_set)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    b = db.query(models.Brand).filter(models.Brand.id == brand_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Brand not found")
    if payload.name is not None: b.name = payload.name
    if payload.logo_url is not None: b.logo_url = payload.logo_url
    if payload.is_active is not None: b.is_active = payload.is_active
    db.commit()
    db.refresh(b)
    return b


@router.patch("/brands/{brand_id}/toggle", response_model=schemas.BrandResponse)
def toggle_brand(brand_id: str, db: Session = Depends(get_db), current_user: models.User = Depends(auth.require_password_set)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    b = db.query(models.Brand).filter(models.Brand.id == brand_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Brand not found")
    b.is_active = not b.is_active
    db.commit()
    db.refresh(b)
    return b


# ── Field Reports ─────────────────────────────────────────────
@router.post("/field-reports", response_model=schemas.FieldReportResponse)
def create_field_report(report: schemas.FieldReportCreate, db: Session = Depends(get_db), current_user: models.User = Depends(auth.require_password_set)):
    # SECURITY: rep_id is taken from the authenticated user, never from the
    # payload (was spoofable — anyone could file reports as someone else).
    if report.rep_id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot file a field report for another user")
    db_report = db.query(models.FieldReport).filter(models.FieldReport.id == report.id).first()
    if db_report:
        if db_report.rep_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized")
        db_report.content = report.content
        db_report.photo_url = report.photo_url
    else:
        db_report = models.FieldReport(id=report.id, rep_id=current_user.id, content=report.content, photo_url=report.photo_url)
        db.add(db_report)
    db.commit()
    db.refresh(db_report)
    
    create_activity_log(db, current_user.id, current_user.full_name, f"Submitted a field report: {db_report.content[:30]}...", "alert", db_report.id)
    
    return db_report


@router.get("/field-reports", response_model=List[schemas.FieldReportResponse])
def get_field_reports(
    rep_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    query = db.query(models.FieldReport)
    rep_ids = get_role_scoped_rep_ids(current_user, db)
    if rep_ids is not None:
        query = query.filter(models.FieldReport.rep_id.in_(rep_ids))
    if rep_id:
        query = query.filter(models.FieldReport.rep_id == rep_id)
    return query.offset(offset).limit(limit).all()


@router.post("/field-reports/{report_id}/photo")
async def upload_field_report_photo(
    report_id: str,
    file: UploadFile,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    report = db.query(models.FieldReport).filter(models.FieldReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Field report not found")
    if report.rep_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Invalid file type")
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File too large")
    result = await store_file_locally(contents, file.content_type, "visits", None, db)
    report.photo_url = result["local_path"]
    report.photo_file_id = result["stored_file"].id
    db.commit()
    db.refresh(report)
    return {"photo_url": report.photo_url, "photo_file_id": report.photo_file_id}


# ── Activity Logs ────────────────────────────────────────────
@router.get("/logs", response_model=List[schemas.ActivityLogResponse])
def get_logs(
    log_type: Optional[str] = None,
    brand_id: Optional[str] = None,
    limit: int = 100,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("admin", "general_manager"):
        raise HTTPException(status_code=403, detail="Not authorized")
    query = db.query(models.ActivityLog)
    if brand_id:
        query = query.join(models.User, models.ActivityLog.user_id == models.User.id).filter(models.User.brand_id == brand_id)
    if log_type and log_type != "all":
        query = query.filter(models.ActivityLog.log_type == log_type)
    return query.order_by(models.ActivityLog.created_at.desc()).limit(limit).all()

@router.get("/audit-logs", response_model=List[schemas.ActivityLogResponse])
def get_audit_logs(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    return db.query(models.ActivityLog).order_by(models.ActivityLog.created_at.desc()).offset(offset).limit(limit).all()
