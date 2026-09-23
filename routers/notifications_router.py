"""routers/notifications_router.py — /notifications/*, /ws/notifications/*"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from jose import jwt, JWTError
from sqlalchemy.orm import Session

import models, schemas, auth
from database import get_db
from routers.deps import manager

router = APIRouter()


@router.get("/notifications", response_model=List[schemas.NotificationResponse])
def get_notifications(
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    return (
        db.query(models.Notification)
        .filter(models.Notification.user_id == current_user.id)
        .order_by(models.Notification.created_at.desc())
        .limit(limit)
        .all()
    )


@router.put("/notifications/{notification_id}/read", response_model=schemas.NotificationResponse)
def mark_notification_read(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    notif = db.query(models.Notification).filter(
        models.Notification.id == notification_id,
        models.Notification.user_id == current_user.id,
    ).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.is_read = True
    db.commit()
    db.refresh(notif)
    return notif


@router.put("/notifications/users/{user_id}/read-all")
def mark_all_notifications_read(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    if current_user.id != user_id and current_user.role not in ("admin", "overseer"):
        raise HTTPException(status_code=403, detail="Not authorized")
    db.query(models.Notification).filter(
        models.Notification.user_id == user_id,
        models.Notification.is_read == False,
    ).update({"is_read": True})
    db.commit()
    return {"message": "All notifications marked as read"}


@router.delete("/notifications/{notification_id}")
def delete_notification(
    notification_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    notif = db.query(models.Notification).filter(
        models.Notification.id == notification_id,
        models.Notification.user_id == current_user.id,
    ).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    db.delete(notif)
    db.commit()
    return {"message": "Notification deleted"}


@router.delete("/notifications")
def delete_all_notifications(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    deleted = db.query(models.Notification).filter(models.Notification.user_id == current_user.id).delete()
    db.commit()
    return {"message": f"Deleted {deleted} notifications"}


@router.websocket("/ws/notifications/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    auth_header = websocket.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, auth.SECRET_KEY, algorithms=[auth.ALGORITHM])
        token_user_id = payload.get("sub")
    except JWTError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if token_user_id != user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await manager.connect(websocket, user_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
