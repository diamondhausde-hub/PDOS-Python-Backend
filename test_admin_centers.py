import datetime
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, User, Center, Visit, Brand
from schemas import CenterCreate, CenterUpdate
from fastapi.testclient import TestClient
from fastapi import HTTPException

from main import app, get_db
from routers.centers_router import create_center, update_center, delete_center, get_centers

engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def test_centers_management():
    db = SessionLocal()
    
    # Brand + Users (rep needs a brand to own centers)
    brand = Brand(id="brand1", name="Test Brand")
    admin = User(id="admin1", email="admin@test.com", hashed_password="pw", full_name="Admin", role="admin")
    overseer = User(id="overseer1", email="ov@test.com", hashed_password="pw", full_name="Overseer", role="overseer")
    rep = User(id="rep1", email="rep@test.com", hashed_password="pw", full_name="Rep", role="rep", brand_id="brand1")
    db.add_all([brand, admin, overseer, rep])
    db.commit()

    # 1. Rep can successfully POST /centers
    new_center = create_center(CenterCreate(name="Rep Center", region="Baghdad"), current_user=rep, db=db)
    assert new_center.name == "Rep Center"
    assert new_center.is_active == True
    
    # 2. Overseer PUT/DELETE -> 403
    try:
        update_center(new_center.id, CenterUpdate(name="Updated by Overseer"), current_user=overseer, db=db)
        assert False, "Overseer should not be able to update center"
    except HTTPException as e:
        assert e.status_code == 403

    try:
        delete_center(new_center.id, current_user=overseer, db=db)
        assert False, "Overseer should not be able to delete center"
    except HTTPException as e:
        assert e.status_code == 403

    # 3. Add a visit to this center
    visit = Visit(id="v1", rep_id=rep.id, center_id=new_center.id, visit_date=datetime.datetime.now(), status="completed")
    db.add(visit)
    db.commit()

    # 4. Admin deletes the center (soft delete)
    delete_center(new_center.id, current_user=admin, db=db)
    
    # Confirm it disappeared from GET /centers
    active_centers = get_centers(db=db, current_user=admin)
    assert len(active_centers) == 0

    # Confirm visit still resolves the center correctly from DB
    db_visit = db.query(Visit).filter(Visit.id == "v1").first()
    db_center = db.query(Center).filter(Center.id == db_visit.center_id).first()
    assert db_center.name == "Rep Center"
    assert db_center.is_active == False

    print("Centers Management tests passed!")
    db.close()

if __name__ == "__main__":
    test_centers_management()
