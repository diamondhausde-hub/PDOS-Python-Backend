"""routers/visits_router.py — /visits/*, /appointments/*, /stock-checks, /expenses/*, /sync/*"""
import datetime
import json
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

import models, schemas, auth
from database import get_db
from routers.deps import (
    get_role_scoped_rep_ids,
    dispatch_notification_sync,
    create_activity_log,
    enrich_visits,
    haversine_distance,
    get_setting,
    manager,
    ALLOWED_TYPES, MAX_SIZE, store_file_locally,
    generate_next_reference_code,
)

router = APIRouter()


# ── Internal helpers ─────────────────────────────────────────
def _assert_can_manage_appointment(current_user: models.User, appt_rep_id: str, db: Session):
    if current_user.role == "admin":
        return
    if current_user.role == "supervisor":
        rep = db.query(models.User).filter(models.User.id == appt_rep_id).first()
        if rep and rep.supervisor_id == current_user.id:
            return
    if current_user.role == "rep" and current_user.id == appt_rep_id:
        return
    raise HTTPException(status_code=403, detail="Not authorized")


def _assert_can_manage_visit(current_user: models.User, visit_rep_id: str, db: Session):
    if current_user.role == "admin":
        return
    if current_user.role == "rep" and current_user.id == visit_rep_id:
        return
    if current_user.role == "supervisor":
        rep = db.query(models.User).filter(models.User.id == visit_rep_id).first()
        if rep and rep.supervisor_id == current_user.id:
            return
    raise HTTPException(status_code=403, detail="Not authorized for this rep")


# ── Appointments ─────────────────────────────────────────────
@router.get("/appointments", response_model=List[schemas.AppointmentResponse])
def get_appointments(current_user: models.User = Depends(auth.require_password_set), db: Session = Depends(get_db)):
    rep_ids = get_role_scoped_rep_ids(current_user, db)
    query = db.query(models.Appointment)
    if rep_ids is not None:
        query = query.filter(models.Appointment.rep_id.in_(rep_ids))
    results = []
    for a in query.all():
        center = db.query(models.Center).filter(models.Center.id == a.center_id).first()
        client = db.query(models.Client).filter(models.Client.id == a.client_id).first() if a.client_id else None
        product = db.query(models.Product).filter(models.Product.id == a.suggested_product_id).first() if a.suggested_product_id else None
        results.append({
            **a.__dict__,
            "center_name": center.name if center else None,
            "client_name": f"{client.doctor_name or client.facility_name or ''}" if client else None,
            "suggested_product_name": product.name if product else None,
        })
    return results


@router.post("/appointments", response_model=schemas.AppointmentResponse)
def create_appointment(payload: schemas.AppointmentCreate, current_user: models.User = Depends(auth.require_password_set), db: Session = Depends(get_db)):
    _assert_can_manage_appointment(current_user, payload.rep_id, db)
    
    # Idempotency check
    existing = db.query(models.Appointment).filter(models.Appointment.id == payload.id).first()
    if existing:
        if not existing.reference_code:
            existing.reference_code = generate_next_reference_code(db, "APT")
            db.commit()
            db.refresh(existing)
        center = db.query(models.Center).filter(models.Center.id == existing.center_id).first()
        client = db.query(models.Client).filter(models.Client.id == existing.client_id).first() if existing.client_id else None
        return {**existing.__dict__, "center_name": center.name if center else None,
                "client_name": f"{client.doctor_name or client.facility_name or ''}" if client else None}

    ref_code = generate_next_reference_code(db, "APT")
    a = models.Appointment(
        id=payload.id,
        reference_code=ref_code,
        rep_id=payload.rep_id, client_id=payload.client_id,
        center_id=payload.center_id, appt_date=payload.appt_date,
        appt_time=payload.appt_time, reminder_minutes_before=payload.reminder_minutes_before,
        notes=payload.notes, status=payload.status,
    )
    db.add(a)
    db.commit()
    db.refresh(a)

    center = db.query(models.Center).filter(models.Center.id == a.center_id).first()
    client = db.query(models.Client).filter(models.Client.id == a.client_id).first() if a.client_id else None
    target_name = client.doctor_name if (client and client.doctor_name) else (client.facility_name if client else (center.name if center else "Unknown"))
    
    create_activity_log(db, current_user.id, current_user.full_name, f"Scheduled an appointment with {target_name} on {a.appt_date}", "visit", a.id)
    center = db.query(models.Center).filter(models.Center.id == a.center_id).first()
    client = db.query(models.Client).filter(models.Client.id == a.client_id).first() if a.client_id else None
    return {**a.__dict__, "center_name": center.name if center else None,
            "client_name": f"{client.doctor_name or client.facility_name or ''}" if client else None}


@router.put("/appointments/{id}", response_model=schemas.AppointmentResponse)
def update_appointment(id: str, payload: schemas.AppointmentUpdate, current_user: models.User = Depends(auth.require_password_set), db: Session = Depends(get_db)):
    a = db.query(models.Appointment).filter(models.Appointment.id == id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    _assert_can_manage_appointment(current_user, a.rep_id, db)
    if payload.client_id is not None: a.client_id = payload.client_id
    if payload.appt_date: a.appt_date = payload.appt_date
    if payload.appt_time: a.appt_time = payload.appt_time
    if payload.status: a.status = payload.status
    if payload.notes: a.notes = payload.notes
    if payload.supervisor_note is not None: a.supervisor_note = payload.supervisor_note
    if payload.suggested_product_id is not None: a.suggested_product_id = payload.suggested_product_id
    db.commit()
    db.refresh(a)
    center = db.query(models.Center).filter(models.Center.id == a.center_id).first()
    client = db.query(models.Client).filter(models.Client.id == a.client_id).first() if a.client_id else None
    return {**a.__dict__, "center_name": center.name if center else None,
            "client_name": f"{client.doctor_name or client.facility_name or ''}" if client else None}


@router.delete("/appointments/{id}")
def delete_appointment(id: str, current_user: models.User = Depends(auth.require_password_set), db: Session = Depends(get_db)):
    a = db.query(models.Appointment).filter(models.Appointment.id == id).first()
    if not a:
        raise HTTPException(status_code=404, detail="Appointment not found")
    _assert_can_manage_appointment(current_user, a.rep_id, db)
    db.delete(a)
    db.commit()
    return {"message": "Appointment deleted"}


# ── Check-in ─────────────────────────────────────────────────
@router.post("/visits/check-in", response_model=schemas.VisitResponse)
async def check_in(
    payload: schemas.CheckInRequest,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    if not payload.center_id and not payload.client_id:
        raise HTTPException(status_code=400, detail="Must provide either center_id or client_id")

    visit_status = "arrived"
    center = None
    client = None
    center_id = payload.center_id if payload.center_id != "" else None

    if center_id:
        center = db.query(models.Center).filter(models.Center.id == center_id).first()
        if not center:
            raise HTTPException(status_code=404, detail="Center not found")
        if center.latitude and center.longitude and payload.latitude and payload.longitude:
            if haversine_distance(payload.latitude, payload.longitude, center.latitude, center.longitude) > get_setting(db, "geofence_radius_meters", 500.0):
                visit_status = "flagged"
    elif payload.client_id:
        client = db.query(models.Client).filter(models.Client.id == payload.client_id).first()
        if not client:
            raise HTTPException(status_code=404, detail="Client not found")
        if client.latitude and client.longitude and payload.latitude and payload.longitude:
            if haversine_distance(payload.latitude, payload.longitude, client.latitude, client.longitude) > get_setting(db, "geofence_radius_meters", 500.0):
                visit_status = "flagged"

    existing_visit = db.query(models.Visit).filter(models.Visit.id == payload.visit_id).first()
    if existing_visit:
        _assert_can_manage_visit(current_user, existing_visit.rep_id, db)
        existing_visit.status = visit_status
        db.commit()
        db.refresh(existing_visit)
        return enrich_visits([existing_visit], db)[0]

    new_visit = models.Visit(
        id=payload.visit_id, rep_id=current_user.id,
        center_id=center_id, client_id=payload.client_id,
        appointment_id=payload.appointment_id,
        visit_date=datetime.datetime.now(datetime.timezone.utc),
        arrival_time=datetime.datetime.now(datetime.timezone.utc),
        status=visit_status, latitude=payload.latitude, longitude=payload.longitude,
    )
    db.add(new_visit)
    if payload.appointment_id:
        appt = db.query(models.Appointment).filter(models.Appointment.id == payload.appointment_id).first()
        if appt:
            appt.status = "done"
    if visit_status == "flagged" and current_user.supervisor_id and center:
        db.add(models.Notification(
            user_id=current_user.supervisor_id, type="visit_flagged",
            title="Flagged Check-in",
            message=f"Rep {current_user.full_name} checked in out-of-bounds at {center.name}",
            related_id=new_visit.id,
        ))
    db.commit()
    db.refresh(new_visit)
    enrich_visits([new_visit], db)
    target_name = client.doctor_name if (client and client.doctor_name) else (client.facility_name if client else (center.name if center else "Unknown target"))
    create_activity_log(db, current_user.id, current_user.full_name, f"Checked in at {target_name}", "visit", new_visit.id)
    await manager.broadcast("refresh_analytics")
    return new_visit


# ── Visits CRUD ───────────────────────────────────────────────
@router.post("/visits", response_model=schemas.VisitResponse)
async def create_visit(
    visit: schemas.VisitCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    center_id = visit.center_id if visit.center_id != "" else None
    status_to_save = visit.status

    center = db.query(models.Center).filter(models.Center.id == center_id).first() if center_id else None
    if center and center.latitude and center.longitude and visit.latitude and visit.longitude:
        if haversine_distance(visit.latitude, visit.longitude, center.latitude, center.longitude) > get_setting(db, "geofence_radius_meters", 500.0):
            status_to_save = "flagged"
    elif not center and visit.client_id:
        client = db.query(models.Client).filter(models.Client.id == visit.client_id).first()
        if client and client.latitude and client.longitude and visit.latitude and visit.longitude:
            if haversine_distance(visit.latitude, visit.longitude, client.latitude, client.longitude) > get_setting(db, "geofence_radius_meters", 500.0):
                status_to_save = "flagged"

    existing = db.query(models.Visit).filter(models.Visit.id == visit.id).first()
    if existing:
        _assert_can_manage_visit(current_user, existing.rep_id, db)
    interested_json = (
        json.dumps(visit.interested_product_ids) if visit.interested_product_ids else None
    )
    if existing:
        existing.status = status_to_save
        if visit.notes:
            existing.notes = visit.notes
        existing.completion_time = visit.completion_time
        existing.visit_type = visit.visit_type or "center"
        existing.visit_reason = visit.visit_reason
        existing.interested_product_ids = interested_json
        if not existing.reference_code:
            existing.reference_code = generate_next_reference_code(db, "VST")
        new_visit = existing
    else:
        ref_code = generate_next_reference_code(db, "VST")
        new_visit = models.Visit(
            id=visit.id, reference_code=ref_code, rep_id=current_user.id, center_id=center_id,
            client_id=visit.client_id, appointment_id=visit.appointment_id,
            visit_date=visit.visit_date, status=status_to_save,
            notes=visit.notes, latitude=visit.latitude, longitude=visit.longitude,
            visit_type=visit.visit_type or "center",
            visit_reason=visit.visit_reason,
            interested_product_ids=interested_json,
            arrival_time=visit.arrival_time,
            completion_time=visit.completion_time,
            retroactive_reason=visit.retroactive_reason,
            save_location_lat=visit.save_location_lat,
            save_location_lng=visit.save_location_lng,
        )
        db.add(new_visit)
    if visit.appointment_id:
        appt = db.query(models.Appointment).filter(models.Appointment.id == visit.appointment_id).first()
        if appt:
            appt.status = "done"
            
    if hasattr(visit, 'task_id') and visit.task_id:
        task = db.query(models.Task).filter(models.Task.id == visit.task_id).first()
        if task:
            task.visit_id = new_visit.id
            task.status = 'done'
            task.completed_at = datetime.datetime.utcnow()
            
    # Keep the visit, item rows, and stock effects in one transaction. A
    # retried request only inserts missing item rows, so stock is decremented
    # once per visit/product.
    for item in visit.items:
        if db.query(models.VisitItem).filter(models.VisitItem.visit_id == new_visit.id, models.VisitItem.product_id == item.product_id).first():
            continue
        prod = db.query(models.Product).filter(models.Product.id == item.product_id).first()
        price = item.price_at_sale if item.price_at_sale is not None else (prod.price if prod else 0.0)
        db.add(models.VisitItem(visit_id=new_visit.id, product_id=item.product_id, qty_sold=item.qty_sold, qty_free=item.qty_free, price_at_sale=price))
        if prod and item.qty_sold > 0:
            prod.stock_qty = max(0, prod.stock_qty - item.qty_sold)
    for req in visit.special_requests:
        if not db.query(models.SpecialRequest).filter(models.SpecialRequest.id == req.id).first():
            db.add(models.SpecialRequest(
                id=req.id,
                visit_id=new_visit.id,
                request_type=req.request_type,
                description=req.description,
            ))
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(new_visit)
    enrich_visits([new_visit], db)
    if new_visit.status == "flagged" and current_user.supervisor_id:
        dispatch_notification_sync(db=db, user_id=current_user.supervisor_id, type="visit_flagged",
                                   title="Flagged Visit Alert",
                                   message=f"{current_user.full_name} submitted a visit that violated geofencing rules.",
                                   related_id=new_visit.id)
    # Doctor-visit flow: inform the supervisor AND every general manager
    if (new_visit.visit_type == "doctor" and new_visit.status == "completed"):
        client = db.query(models.Client).filter(models.Client.id == new_visit.client_id).first() if new_visit.client_id else None
        doctor_label = f"Dr. {client.doctor_name}" if client and client.doctor_name else "a doctor"
        tier = f" — Class {client.class_tier}" if client and client.class_tier else ""
        msg = f"{current_user.full_name} completed a doctor visit with {doctor_label}{tier}."
        recipients = {current_user.supervisor_id} if current_user.supervisor_id else set()
        for gm in db.query(models.User).filter(models.User.role == "general_manager", models.User.is_active == True).all():
            recipients.add(gm.id)
        for rid in recipients:
            if not rid:
                continue
            dispatch_notification_sync(db=db, user_id=rid, type="doctor_visit_completed",
                                       title="Doctor Visit Completed",
                                       message=msg, related_id=new_visit.id)
    center = db.query(models.Center).filter(models.Center.id == new_visit.center_id).first() if new_visit.center_id else None
    client = db.query(models.Client).filter(models.Client.id == new_visit.client_id).first() if new_visit.client_id else None
    target_name = client.doctor_name if (client and client.doctor_name) else (client.facility_name if client else (center.name if center else "Unknown target"))
    
    action_text = f"Updated visit to {target_name} (Status: {new_visit.status})"
    if new_visit.status == "in_progress":
        action_text = f"Started visit to {target_name}"
    elif new_visit.status == "completed":
        items_sold = sum([item.qty_sold for item in visit.items])
        gifts_given = sum([item.qty_free for item in visit.items])
        action_text = f"Completed visit to {target_name}."
        if items_sold > 0 or gifts_given > 0:
            action_text += f" Sold {items_sold} items, gave {gifts_given} gifts."
            
    create_activity_log(db, current_user.id, current_user.full_name, action_text, "visit", new_visit.id)

    await manager.broadcast("refresh_analytics")
    return new_visit


@router.get("/visits", response_model=List[schemas.VisitResponse])
def get_visits(
    status: Optional[str] = None,
    brand_id: Optional[str] = None,
    rep_id: Optional[str] = None,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    rep_ids = get_role_scoped_rep_ids(current_user, db)
    query = db.query(models.Visit)
    if rep_ids is not None:
        query = query.filter(models.Visit.rep_id.in_(rep_ids))
    if rep_id:
        if rep_ids is not None and rep_id not in rep_ids:
            raise HTTPException(status_code=403, detail="Not authorized for this rep")
        query = query.filter(models.Visit.rep_id == rep_id)
    if brand_id:
        query = query.filter(models.Visit.brand_id == brand_id)
    if status:
        query = query.filter(models.Visit.status == status)
    return enrich_visits(query.all(), db)



@router.get("/visits/{visit_id}", response_model=schemas.VisitResponse)
def get_visit(visit_id: str, current_user: models.User = Depends(auth.require_password_set), db: Session = Depends(get_db)):
    visit = db.query(models.Visit).filter(models.Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    _assert_can_manage_visit(current_user, visit.rep_id, db)
    return enrich_visits([visit], db)[0]

@router.put("/visits/{visit_id}/review", response_model=schemas.VisitResponse)
def review_visit(
    visit_id: str,
    payload: schemas.VisitReviewRequest,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    visit = db.query(models.Visit).filter(models.Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    if current_user.role == "supervisor":
        rep = db.query(models.User).filter(models.User.id == visit.rep_id).first()
        if not rep or rep.supervisor_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized for this rep")
    elif current_user.role not in ("admin", "general_manager", "overseer"):
        raise HTTPException(status_code=403, detail="Not authorized")
    if visit.status != "flagged":
        raise HTTPException(status_code=409, detail="Visit is no longer pending review")
    if payload.status == "completed":
        visit.status = "completed"
    elif payload.status == "rejected":
        visit.status = "rejected"
        for item in visit.items:
            prod = db.query(models.Product).filter(models.Product.id == item.product_id).first()
            if prod:
                prod.stock_qty += item.qty_sold
        if visit.appointment_id:
            appt = db.query(models.Appointment).filter(models.Appointment.id == visit.appointment_id).first()
            if appt:
                appt.status = "pending"
    else:
        raise HTTPException(status_code=400, detail="Invalid status")
    visit.reviewed_by = current_user.id
    visit.reviewed_at = datetime.datetime.now(datetime.timezone.utc)
    visit.review_note = payload.note
    db.commit()
    db.refresh(visit)
    enrich_visits([visit], db)
    dispatch_notification_sync(db=db, user_id=visit.rep_id, type="visit_reviewed",
                               title=f"Visit {payload.status.capitalize()}",
                               message=f"Your flagged visit has been {payload.status}. Note: {payload.note}",
                               related_id=visit.id)
    return visit


@router.put("/visits/{visit_id}/note", response_model=schemas.VisitResponse)
def add_visit_note(
    visit_id: str,
    payload: schemas.ReviewNoteCreate,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    visit = db.query(models.Visit).filter(models.Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    _assert_can_manage_visit(current_user, visit.rep_id, db)
    visit.supervisor_note = payload.review_note
    db.commit()
    db.refresh(visit)
    enrich_visits([visit], db)
    dispatch_notification_sync(db=db, user_id=visit.rep_id, type="visit_note",
                               title="New supervisor note", message=payload.review_note, related_id=visit.id)
    return visit


@router.get("/visits/{visit_id}/invoice")
def get_visit_invoice(visit_id: str, current_user: models.User = Depends(auth.require_password_set), db: Session = Depends(get_db)):
    from fpdf import FPDF
    import tempfile, os as _os
    from starlette.background import BackgroundTask

    visit = db.query(models.Visit).filter(models.Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    _assert_can_manage_visit(current_user, visit.rep_id, db)

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt=f"Invoice for Visit: {visit.id}", ln=True, align="C")
    pdf.cell(200, 10, txt=f"Date: {visit.visit_date}", ln=True)
    pdf.cell(200, 10, txt=f"Status: {visit.status}", ln=True)
    for item in visit.visit_items:
        pdf.cell(200, 10, txt=f"- Product ID: {item.product_id} | Sold: {item.qty_sold} | Free: {item.qty_free}", ln=True)

    fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    _os.close(fd)
    pdf.output(temp_path)

    def _cleanup():
        try:
            _os.remove(temp_path)
        except OSError:
            pass

    # Delete the temp file after the response is sent (was leaking files)
    return FileResponse(
        temp_path, media_type="application/pdf",
        filename=f"invoice_{visit_id}.pdf",
        background=BackgroundTask(_cleanup),
    )


@router.post("/visits/{visit_id}/signature")
async def upload_visit_signature(
    visit_id: str, file: UploadFile,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    visit = db.query(models.Visit).filter(models.Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    if visit.rep_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Invalid file type")
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File too large")
    result = await store_file_locally(contents, file.content_type, "signatures", None, db)
    visit.signature_url = result["local_path"]
    visit.signature_file_id = result["stored_file"].id
    db.commit()
    db.refresh(visit)
    return {"signature_url": visit.signature_url, "signature_file_id": visit.signature_file_id}


@router.post("/visits/{visit_id}/photos", response_model=schemas.VisitPhotoResponse)
async def upload_visit_photo(
    visit_id: str, file: UploadFile,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    visit = db.query(models.Visit).filter(models.Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    if visit.rep_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the rep who owns this visit can upload photos")
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Invalid file type")
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File too large")
    result = await store_file_locally(contents, file.content_type, "visits", None, db)
    vp = models.VisitPhoto(visit_id=visit_id, photo_url=result["local_path"], photo_file_id=result["stored_file"].id)
    db.add(vp)
    db.commit()
    db.refresh(vp)
    return vp


# ── Stock checks ─────────────────────────────────────────────
@router.post("/stock-checks", response_model=List[schemas.StockCheckResponse])
def create_stock_checks(
    payload: List[schemas.StockCheckCreate],
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    results = []
    for item in payload:
        visit = db.query(models.Visit).filter(models.Visit.id == item.visit_id).first()
        if not visit or visit.rep_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized for this visit")
        existing = db.query(models.PharmacyStockCheck).filter_by(visit_id=item.visit_id, product_id=item.product_id).first()
        if existing:
            results.append(existing)
            continue
        new_check = models.PharmacyStockCheck(**item.dict())
        db.add(new_check)
        results.append(new_check)
    db.commit()
    for r in results:
        db.refresh(r)
    return results


# ── Expenses ─────────────────────────────────────────────────
@router.post("/expenses", response_model=schemas.ExpenseResponse)
def create_expense(
    payload: schemas.ExpenseCreate,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    if payload.visit_id:
        visit = db.query(models.Visit).filter(models.Visit.id == payload.visit_id).first()
        if not visit:
            raise HTTPException(status_code=404, detail="Visit not found")
        if current_user.role == "rep" and visit.rep_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized")
    existing = db.query(models.Expense).filter(models.Expense.id == payload.id).first()
    threshold = float((db.query(models.SystemSetting).filter(models.SystemSetting.key == "expense_approval_threshold").first() or type("o", (), {"value": "999999"})()).value)
    requires_admin = payload.amount > threshold
    requires_gm = current_user.role == "supervisor"
    if existing:
        existing.category = payload.category
        existing.amount = payload.amount
        existing.description = payload.description
        existing.requires_admin_approval = requires_admin
        existing.requires_gm_approval = requires_gm
        db.commit()
        db.refresh(existing)
        return existing
    new_expense = models.Expense(
        id=payload.id, visit_id=payload.visit_id, rep_id=current_user.id,
        category=payload.category, amount=payload.amount, description=payload.description,
        requires_admin_approval=requires_admin, requires_gm_approval=requires_gm,
    )
    db.add(new_expense)
    db.commit()
    db.refresh(new_expense)
    create_activity_log(db, current_user.id, current_user.full_name, f"Submitted expense ${new_expense.amount:.2f}", "order", new_expense.id)
    return new_expense


@router.get("/expenses/all", response_model=List[schemas.ExpenseResponse])
def get_all_expenses(
    status: Optional[str] = None, brand_id: Optional[str] = None,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    if current_user.role not in ("admin", "general_manager"):
        raise HTTPException(status_code=403, detail="Not authorized")
    query = db.query(models.Expense)
    if brand_id:
        query = query.join(models.User, models.Expense.rep_id == models.User.id).filter(models.User.brand_id == brand_id)
    if status and status != "all":
        query = query.filter(models.Expense.status == status)
    return query.order_by(models.Expense.created_at.desc()).all()


@router.get("/expenses/my", response_model=List[schemas.ExpenseResponse])
def get_my_expenses(current_user: models.User = Depends(auth.require_password_set), db: Session = Depends(get_db)):
    return db.query(models.Expense).filter(models.Expense.rep_id == current_user.id).order_by(models.Expense.created_at.desc()).all()


@router.get("/expenses/team", response_model=List[schemas.ExpenseResponse])
def get_team_expenses(
    status: Optional[str] = None,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    rep_ids = get_role_scoped_rep_ids(current_user, db)
    query = db.query(models.Expense)
    if status and status != "all":
        query = query.filter(models.Expense.status == status)
    if rep_ids is not None:
        query = query.filter(models.Expense.rep_id.in_(rep_ids))
    return query.order_by(models.Expense.created_at.desc()).all()


@router.get("/visits/{visit_id}/expenses", response_model=List[schemas.ExpenseResponse])
def get_visit_expenses(visit_id: str, current_user: models.User = Depends(auth.require_password_set), db: Session = Depends(get_db)):
    visit = db.query(models.Visit).filter(models.Visit.id == visit_id).first()
    if not visit:
        raise HTTPException(status_code=404, detail="Visit not found")
    # SECURITY: role-scoped access (was readable by any authenticated user)
    _assert_can_manage_visit(current_user, visit.rep_id, db)
    return db.query(models.Expense).filter(models.Expense.visit_id == visit_id).all()


@router.post("/expenses/{expense_id}/receipt")
async def upload_expense_receipt(
    expense_id: str, file: UploadFile,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    expense = db.query(models.Expense).filter(models.Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    if expense.rep_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Invalid file type")
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File too large")
    result = await store_file_locally(contents, file.content_type, "receipts", None, db)
    expense.receipt_image_url = result["local_path"]
    expense.receipt_file_id = result["stored_file"].id
    db.commit()
    db.refresh(expense)
    return expense


@router.patch("/expenses/{expense_id}/status", response_model=schemas.ExpenseResponse)
def update_expense_status(
    expense_id: str, payload: schemas.ExpenseStatusUpdate,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    expense = db.query(models.Expense).filter(models.Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    if expense.rep_id == current_user.id:
        raise HTTPException(status_code=403, detail="Cannot approve your own expense")
    if current_user.role == "general_manager":
        if not expense.requires_gm_approval:
            raise HTTPException(status_code=403, detail="GM can only manage GM-required expenses")
    elif current_user.role == "supervisor" and expense.requires_gm_approval:
        raise HTTPException(status_code=403, detail="This expense requires GM approval")
    else:
        _assert_can_manage_visit(current_user, expense.rep_id, db)
    if expense.status not in ["pending", "escalated"]:
        raise HTTPException(status_code=409, detail="Already reviewed")
    if payload.status == "approved" and current_user.role not in ("admin", "general_manager"):
        expense.status = "escalated" if expense.requires_admin_approval else "approved"
    else:
        expense.status = payload.status
    expense.rejection_reason = payload.rejection_reason
    if payload.status == "approved" and expense.status == "approved":
        expense.approved_by = current_user.id
        expense.approved_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()
    db.refresh(expense)
    return expense


# ── Sync ─────────────────────────────────────────────────────
@router.post("/sync/abandon")
async def abandon_sync_item(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    if current_user.supervisor_id:
        import uuid
        db.add(models.Notification(
            id=str(uuid.uuid4()),
            user_id=current_user.supervisor_id,
            type="sync_abandoned",
            title="مزامنة متجاهلة",
            message=f"المندوب {current_user.full_name} قام بتجاهل عنصر من نوع {payload.get('type')}.",
            related_id=payload.get("id"),
            created_at=datetime.datetime.now(datetime.timezone.utc),
        ))
        db.commit()
    return {"status": "ok"}
