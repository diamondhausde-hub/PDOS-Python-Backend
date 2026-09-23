"""routers/products_router.py — /products/*"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, Request
from sqlalchemy.orm import Session

import models, schemas, auth
from database import get_db
from routers.deps import (
    ALLOWED_TYPES, MAX_SIZE, store_file_locally,
    dispatch_notification_sync, create_activity_log,
)


router = APIRouter()


@router.get("/products", response_model=List[schemas.ProductResponse])
def get_products(db: Session = Depends(get_db), current_user: models.User = Depends(auth.require_password_set)):
    query = db.query(models.Product).filter(models.Product.is_active == True)
    if current_user.brand_id and current_user.role in ("rep", "supervisor"):
        query = query.filter(models.Product.brand_id == current_user.brand_id)
    products = query.all()
    for p in products:
        if p.barcode is None:
            p.barcode = ""
    return products


@router.post("/products", response_model=schemas.ProductResponse)
def create_product(
    product: schemas.ProductCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    if current_user.role == "admin":
        raise HTTPException(status_code=403, detail="Admin has no business data access")
    if current_user.role == "rep":
        raise HTTPException(status_code=403, detail="Reps cannot create products")
    if current_user.role == "general_manager":
        raise HTTPException(status_code=403, detail="Use the supervisor account for this brand to create products")
    brand_id = current_user.brand_id
    if not brand_id:
        raise HTTPException(status_code=422, detail="Supervisor account has no brand assigned")
    new_prod = models.Product(
        name=product.name, category=product.category, price=product.price,
        barcode=product.barcode, min_threshold=product.min_threshold,
        stock_qty=product.stock_qty, description=product.description,
        image_url=product.image_url, brand_id=brand_id,
    )
    db.add(new_prod)
    db.commit()
    db.refresh(new_prod)
    return new_prod


@router.put("/products/{product_id}", response_model=schemas.ProductResponse)
def update_product(
    product_id: str,
    product: schemas.ProductCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    if current_user.role not in ("general_manager", "supervisor"):
        raise HTTPException(status_code=403, detail="Not authorized")
    db_prod = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not db_prod:
        raise HTTPException(status_code=404, detail="Product not found")
    if current_user.role == "supervisor" and db_prod.brand_id != current_user.brand_id:
        raise HTTPException(status_code=403, detail="Cannot edit products from another brand")
    db_prod.name = product.name
    db_prod.category = product.category
    db_prod.price = product.price
    db_prod.min_threshold = product.min_threshold
    db_prod.stock_qty = product.stock_qty
    if product.description is not None:
        db_prod.description = product.description
    db.commit()
    db.refresh(db_prod)
    return db_prod


@router.delete("/products/{product_id}")
def delete_product(
    product_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can delete products")
    db_prod = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not db_prod:
        raise HTTPException(status_code=404, detail="Product not found")
    db_prod.is_active = False
    db.commit()
    return {"message": "Product deleted"}


@router.post("/products/{product_id}/image")
async def upload_product_image(
    product_id: str,
    file: UploadFile,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set),
):
    if current_user.role not in ("admin", "supervisor"):
        raise HTTPException(status_code=403, detail="Not authorized")
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Invalid file type")
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File too large")
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    result = await store_file_locally(contents, file.content_type, "products", product.image_url, db)
    product.image_url = result["local_path"]
    product.image_file_id = result["stored_file"].id
    db.commit()
    db.refresh(product)
    return {"image_url": product.image_url, "image_file_id": product.image_file_id}


@router.post("/products/{product_id}/report")
def report_product(
    product_id: str,
    payload: schemas.NoteCreate,
    current_user: models.User = Depends(auth.require_password_set),
    db: Session = Depends(get_db),
):
    product = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if current_user.supervisor_id:
        dispatch_notification_sync(
            db, user_id=current_user.supervisor_id, type="product_report",
            title=f"تقرير عن المنتج من {current_user.full_name}",
            message=f"{product.name}: {payload.content}", related_id=product_id,
        )
    create_activity_log(
        db, user_id=current_user.id, user_name=current_user.full_name,
        action=f"Reported product {product.name}: {payload.content}",
        log_type="product_report", related_id=product_id,
    )
    return {"status": "success"}
