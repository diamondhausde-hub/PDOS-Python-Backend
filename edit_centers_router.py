with open('routers/centers_router.py', 'r', encoding='utf-8') as f:
    text = f.read()

from_code = '''@router.delete("/{center_id}")'''

to_code = '''class CenterStatusUpdate(BaseModel):
    status: str
    rejection_reason: Optional[str] = None

@router.patch("/{center_id}/status", response_model=schemas.CenterResponse)
def update_center_status(
    center_id: str,
    payload: CenterStatusUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_role(["admin", "general_manager"]))
):
    center = db.query(models.Center).filter(models.Center.id == center_id).first()
    if not center:
        raise HTTPException(status_code=404, detail="Center not found")
    if current_user.brand_id and center.brand_id != current_user.brand_id:
        raise HTTPException(status_code=403, detail="Not authorized for this brand")
    
    center.status = payload.status
    if payload.rejection_reason is not None:
        center.rejection_reason = payload.rejection_reason
    db.commit()
    db.refresh(center)
    return center

@router.delete("/{center_id}")'''

if 'class CenterStatusUpdate(BaseModel):' not in text:
    text = text.replace(from_code, to_code)
    # also add Optional and BaseModel imports if needed
    if 'from pydantic import BaseModel' not in text:
        text = text.replace('import schemas, models, auth', 'import schemas, models, auth\nfrom pydantic import BaseModel\nfrom typing import Optional')
        
    with open('routers/centers_router.py', 'w', encoding='utf-8') as f:
        f.write(text)

print("Done")
