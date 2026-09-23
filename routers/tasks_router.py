from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func
from typing import List, Optional
import datetime
from datetime import timedelta

from database import get_db
import models
import schemas
from auth import get_current_user

router = APIRouter(prefix="/tasks", tags=["Tasks & Brand Activity Logs"])


# ─── Helpers ────────────────────────────────────────────────────────────────

def _get_brand_color(brand) -> str:
    """Return the brand's own color, or fallback to a computed one."""
    if brand and hasattr(brand, 'color') and brand.color:
        return brand.color
    if brand and brand.name:
        return "#9C27B0" if "cebelia" in brand.name.lower() else "#4CAF50"
    return "#757575"


def _enrich_task(task) -> dict:
    """Convert a Task ORM object to a dict enriched with names/colors."""
    d = {c.name: getattr(task, c.name) for c in task.__table__.columns}
    d["rep_name"] = task.rep.full_name if task.rep else "غير معروف"
    d["brand_name"] = task.brand.name if task.brand else "غير معروف"
    d["brand_color"] = _get_brand_color(task.brand)
    d["supervisor_name"] = task.supervisor.full_name if task.supervisor else None
    return d


def _get_scoped_query(db: Session, current_user: models.User):
    """Return a Task query scoped by the user's role."""
    query = db.query(models.Task).options(
        joinedload(models.Task.rep),
        joinedload(models.Task.brand),
        joinedload(models.Task.supervisor),
    ).filter(models.Task.is_deleted == False)

    if current_user.role == "rep":
        # Reps only see tasks assigned to them
        query = query.filter(models.Task.rep_id == current_user.id)
    elif current_user.role == "supervisor":
        # Supervisors see tasks they created + tasks of their reps
        rep_ids = [r.id for r in current_user.reps] if current_user.reps else []
        rep_ids.append(current_user.id)
        query = query.filter(
            or_(
                models.Task.supervisor_id == current_user.id,
                models.Task.rep_id.in_(rep_ids),
            )
        )
    # admin / general_manager see everything

    return query


def _log_history(db: Session, task_id: str, action: str, changed_by: str,
                 old_status: str = None, new_status: str = None, note: str = None):
    """Write an audit record to task_history."""
    entry = models.TaskHistory(
        task_id=task_id,
        action=action,
        old_status=old_status,
        new_status=new_status,
        changed_by=changed_by,
        note=note,
    )
    db.add(entry)


# ─── CRUD Endpoints ────────────────────────────────────────────────────────

@router.post("/", response_model=schemas.TaskResponse)
def create_task(
    task: schemas.TaskCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Create a new task. Supervisor/GM only."""
    if current_user.role not in ("supervisor", "general_manager", "admin"):
        raise HTTPException(403, "Only supervisors and managers can create tasks")

    db_task = models.Task(**task.dict())
    if not db_task.supervisor_id:
        db_task.supervisor_id = current_user.id
    if not db_task.brand_id:
        db_task.brand_id = current_user.brand_id
    if db_task.status == 'new':
        db_task.status = 'pending'
    db.add(db_task)
    db.flush()

    _log_history(db, db_task.id, "created", current_user.id,
                 new_status=db_task.status,
                 note=f"Task assigned to rep")

    db.commit()

    # Reload with relationships
    db_task = db.query(models.Task).options(
        joinedload(models.Task.rep),
        joinedload(models.Task.brand),
        joinedload(models.Task.supervisor),
    ).populate_existing().get(db_task.id)

    return _enrich_task(db_task)


@router.get("/", response_model=List[schemas.TaskResponse])
def get_tasks(
    rep_id: Optional[str] = None,
    brand_id: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Get tasks scoped by role. Supports filtering by rep, brand, status."""
    query = _get_scoped_query(db, current_user)

    if rep_id:
        query = query.filter(models.Task.rep_id == rep_id)
    if brand_id:
        query = query.filter(models.Task.brand_id == brand_id)
    if status:
        query = query.filter(models.Task.status == status)

    tasks = query.order_by(models.Task.created_at.desc()).all()
    return [_enrich_task(t) for t in tasks]


@router.patch("/{task_id}", response_model=schemas.TaskResponse)
def update_task(
    task_id: str,
    task_update: schemas.TaskUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Update a task's status, notes, or priority."""
    db_task = db.query(models.Task).filter(
        models.Task.id == task_id, 
        models.Task.is_deleted == False
    ).first()

    if not db_task:
        raise HTTPException(404, "Task not found")

    # Role check: rep can only update their own tasks
    if current_user.role == "rep" and db_task.rep_id != current_user.id:
        raise HTTPException(403, "You can only update your own tasks")

    old_status = db_task.status

    if task_update.status is not None and task_update.status != old_status:
        if task_update.status == 'rejected' and not task_update.rejection_report:
            raise HTTPException(422, "rejection_report is required when rejecting a task")

        db_task.status = task_update.status
        if task_update.status in ["done", "completed"]:
            if not db_task.completed_at:
                db_task.completed_at = datetime.datetime.utcnow()
        else:
            db_task.completed_at = None
            
        if task_update.status == "accepted":
            db_task.accepted_at = datetime.datetime.utcnow()

        _log_history(db, task_id, "status_changed", current_user.id,
                     old_status=old_status, new_status=task_update.status)

    if task_update.progress_note is not None and task_update.progress_note != db_task.progress_note:
        db_task.progress_note = task_update.progress_note
        _log_history(db, task_id, "updated", current_user.id,
                     note=f"Progress note updated")

    if task_update.priority is not None and task_update.priority != db_task.priority:
        db_task.priority = task_update.priority
        _log_history(db, task_id, "updated", current_user.id,
                     note=f"Priority changed to {task_update.priority}")

    if task_update.notes is not None:
        db_task.notes = task_update.notes
        
    if task_update.rejection_report is not None:
        db_task.rejection_report = task_update.rejection_report
    if task_update.reminder_offset is not None:
        db_task.reminder_offset = task_update.reminder_offset
    if task_update.visit_id is not None:
        db_task.visit_id = task_update.visit_id
    if task_update.accepted_at is not None:
        db_task.accepted_at = task_update.accepted_at

    db.commit()
    
    # Reload with relationships explicitly to avoid lazy-load issues
    db_task = db.query(models.Task).options(
        joinedload(models.Task.rep),
        joinedload(models.Task.brand),
        joinedload(models.Task.supervisor),
    ).populate_existing().get(task_id)

    return _enrich_task(db_task)


@router.delete("/{task_id}")
def delete_task(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Soft-delete a task. Supervisor/GM/Admin only."""
    task = db.query(models.Task).filter(
        models.Task.id == task_id,
        models.Task.is_deleted == False,
    ).first()
    if not task:
        raise HTTPException(404, "Task not found")

    if current_user.role not in ("supervisor", "general_manager", "admin"):
        raise HTTPException(403, "Only supervisors and managers can delete tasks")

    task.is_deleted = True
    _log_history(db, task_id, "deleted", current_user.id,
                 old_status=task.status, note="Task deleted")
    db.commit()
    return {"ok": True}


# ─── Task History ───────────────────────────────────────────────────────────

@router.get("/{task_id}/history", response_model=List[schemas.TaskHistoryResponse])
def get_task_history(
    task_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Get the change history of a specific task."""
    entries = db.query(models.TaskHistory).options(
        joinedload(models.TaskHistory.user),
    ).filter(
        models.TaskHistory.task_id == task_id,
    ).order_by(models.TaskHistory.created_at.asc()).all()

    result = []
    for e in entries:
        d = {c.name: getattr(e, c.name) for c in e.__table__.columns}
        d["changed_by_name"] = e.user.full_name if e.user else None
        result.append(d)
    return result


# ─── Search Targets (Autocomplete) ─────────────────────────────────────────

@router.get("/search-targets", response_model=List[schemas.SearchTargetResponse])
def search_targets(
    q: str = Query(..., min_length=1, description="Search query"),
    type: Optional[str] = Query(None, description="Filter by type: doctor, pharmacy, institution, center"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Autocomplete search across clients (doctors/pharmacies) and centers."""
    results = []
    search = f"%{q}%"

    if type is None or type in ("doctor", "pharmacy", "institution"):
        # Search clients
        client_query = db.query(models.Client).filter(
            or_(
                models.Client.doctor_name.ilike(search),
                models.Client.facility_name.ilike(search),
            )
        )
        if type:
            client_query = client_query.filter(models.Client.client_type == type)

        # Brand scoping
        if current_user.brand_id:
            client_query = client_query.filter(models.Client.brand_id == current_user.brand_id)

        for c in client_query.limit(10).all():
            name = c.doctor_name or c.facility_name or "Unknown"
            results.append({
                "id": c.id,
                "name": name,
                "type": c.client_type or "doctor",
                "region": c.region,
            })

    if type is None or type == "center":
        # Search centers
        center_query = db.query(models.Center).filter(
            models.Center.name.ilike(search),
            models.Center.is_active == True,
        )
        if current_user.brand_id:
            center_query = center_query.filter(models.Center.brand_id == current_user.brand_id)

        for c in center_query.limit(10).all():
            results.append({
                "id": c.id,
                "name": c.name,
                "type": "center",
                "region": c.region,
            })

    return results[:10]


# ─── Brand Activity Logs ───────────────────────────────────────────────────

@router.post("/logs", response_model=schemas.BrandActivityLogResponse)
def create_activity_log(
    log: schemas.BrandActivityLogCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    db_log = models.BrandActivityLog(**log.dict())
    if not db_log.rep_id:
        db_log.rep_id = current_user.id
    db.add(db_log)

    # Auto-complete linked task
    if db_log.task_id:
        task = db.query(models.Task).filter(models.Task.id == db_log.task_id).first()
        if task and task.status != 'done':
            old = task.status
            task.status = 'done'
            task.completed_at = datetime.datetime.utcnow()
            _log_history(db, task.id, "status_changed", current_user.id,
                         old_status=old, new_status="done",
                         note="Auto-completed via activity log")

    db.commit()
    db.refresh(db_log)

    d = {c.name: getattr(db_log, c.name) for c in db_log.__table__.columns}
    rep = db.query(models.User).get(db_log.rep_id) if db_log.rep_id else None
    brand = db.query(models.Brand).get(db_log.brand_id) if db_log.brand_id else None
    d["rep_name"] = rep.full_name if rep else None
    d["brand_name"] = brand.name if brand else None
    return d


@router.get("/logs", response_model=List[schemas.BrandActivityLogResponse])
def get_activity_logs(
    brand_id: Optional[str] = None,
    rep_id: Optional[str] = None,
    date_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.BrandActivityLog).options(
        joinedload(models.BrandActivityLog.rep),
        joinedload(models.BrandActivityLog.brand),
    )

    # Role scoping
    if current_user.role == "rep":
        query = query.filter(models.BrandActivityLog.rep_id == current_user.id)
    elif current_user.role == "supervisor":
        rep_ids = [r.id for r in current_user.reps] if current_user.reps else []
        rep_ids.append(current_user.id)
        query = query.filter(models.BrandActivityLog.rep_id.in_(rep_ids))

    if brand_id:
        query = query.filter(models.BrandActivityLog.brand_id == brand_id)
    if rep_id:
        query = query.filter(models.BrandActivityLog.rep_id == rep_id)

    if date_filter:
        now = datetime.datetime.utcnow()
        if date_filter == 'today':
            query = query.filter(models.BrandActivityLog.logged_at >= now.date())
        elif date_filter == 'week':
            query = query.filter(models.BrandActivityLog.logged_at >= now - timedelta(days=7))
        elif date_filter == 'month':
            query = query.filter(models.BrandActivityLog.logged_at >= now - timedelta(days=30))

    logs = query.order_by(models.BrandActivityLog.logged_at.desc()).all()
    result = []
    for l in logs:
        d = {c.name: getattr(l, c.name) for c in l.__table__.columns}
        d["rep_name"] = l.rep.full_name if l.rep else None
        d["brand_name"] = l.brand.name if l.brand else None
        result.append(d)
    return result
