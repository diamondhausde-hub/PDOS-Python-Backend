import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, User, Visit, Product, Appointment, VisitItem, Brand
from schemas import VisitReviewRequest
from main import app, get_db
from fastapi.testclient import TestClient

# Setup in-memory SQLite DB
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

from routers.visits_router import review_visit
from fastapi import HTTPException

def test_review_flagged_visit():
    db = SessionLocal()
    
    # Create test users
    admin = User(id="admin", email="admin@test.com", hashed_password="pw", full_name="Admin", role="admin")
    supervisor1 = User(id="sup1", email="sup1@test.com", hashed_password="pw", full_name="Sup 1", role="supervisor")
    supervisor2 = User(id="sup2", email="sup2@test.com", hashed_password="pw", full_name="Sup 2", role="supervisor")
    rep1 = User(id="rep1", email="rep1@test.com", hashed_password="pw", full_name="Rep 1", role="rep", supervisor_id="sup1")
    
    # Create brand, product and appointment
    brand = Brand(id="brand1", name="Test Brand")
    prod = Product(id="prod1", name="Product 1", price=10.0, category="Test", stock_qty=100, brand_id="brand1")
    appt = Appointment(id="appt1", rep_id="rep1", center_id="c1", appt_date=datetime.datetime.utcnow(), appt_time="10:00", status="done")
    
    db.add_all([admin, supervisor1, supervisor2, rep1, brand, prod, appt])
    db.commit()
    
    # Create a flagged visit
    date = datetime.datetime.utcnow()
    v1 = Visit(id="v1", rep_id="rep1", center_id="c1", appointment_id="appt1", visit_date=date, status="flagged")
    db.add(v1)
    db.commit()

    # Add a visit item for the flagged visit
    prod.stock_qty -= 10
    v1_item = VisitItem(id="item1", visit_id="v1", product_id="prod1", qty_sold=10, price_at_sale=10.0)
    db.add(v1_item)
    db.commit()

    # Test 1: Supervisor 2 (not rep's supervisor) tries to review -> 403
    try:
        review_visit("v1", VisitReviewRequest(status="completed"), current_user=supervisor2, db=db)
        assert False, "Should raise 403"
    except HTTPException as e:
        assert e.status_code == 403

    # Test 2: Supervisor 1 rejects the visit
    res = review_visit("v1", VisitReviewRequest(status="rejected", note="Too far"), current_user=supervisor1, db=db)
    assert res.status == "rejected"
    assert res.review_note == "Too far"

    db.refresh(prod)
    db.refresh(appt)
    assert prod.stock_qty == 100, "Stock should be restored"
    assert appt.status == "pending", "Appointment should be reverted to pending"

    # Test 3: Try to review an already resolved visit -> 409
    try:
        review_visit("v1", VisitReviewRequest(status="completed"), current_user=supervisor1, db=db)
        assert False, "Should raise 409"
    except HTTPException as e:
        assert e.status_code == 409

    print("Review tests passed!")
    db.close()

if __name__ == "__main__":
    test_review_flagged_visit()
