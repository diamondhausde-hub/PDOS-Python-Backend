import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, User, Visit, Product, Appointment, VisitItem, Center, Brand
from schemas import UserCreate
from fastapi.testclient import TestClient
from fastapi import HTTPException
import pytest

from main import app, get_db
from routers.users_router import create_user
from analytics import get_system_overview, get_analytics

# Setup in-memory SQLite DB
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def test_revenue_and_admin_creation():
    db = SessionLocal()
    
    # Users
    admin = User(id="admin", email="admin@test.com", hashed_password="pw", full_name="Admin", role="admin")
    overseer = User(id="overseer", email="overseer@test.com", hashed_password="pw", full_name="Overseer", role="overseer")
    supervisor = User(id="sup", email="sup@test.com", hashed_password="pw", full_name="Sup", role="supervisor", brand_id="brand1")
    rep = User(id="rep1", email="rep1@test.com", hashed_password="pw", full_name="Rep 1", role="rep", supervisor_id="sup")
    
    db.add_all([admin, overseer, supervisor, rep])
    db.commit()

    # Center and Product
    brand = Brand(id="brand1", name="Test Brand")
    center = Center(id="c1", name="C1", brand_id="brand1")
    prod = Product(id="prod1", name="Product 1", price=10.0, category="Test", stock_qty=100, brand_id="brand1")
    db.add_all([brand, center, prod])
    db.commit()

    # Visits
    today = datetime.date.today()
    first_of_month = today.replace(day=1)
    
    # 1 valid visit today
    v1 = Visit(id="v1", rep_id="rep1", center_id="c1", visit_date=datetime.datetime.now(), status="done")
    db.add(v1)
    db.commit()
    v1_item = VisitItem(id="item1", visit_id="v1", product_id="prod1", qty_sold=5, price_at_sale=10.0) # $50 revenue
    db.add(v1_item)
    
    # 1 flagged visit today (should be excluded from revenue)
    v2 = Visit(id="v2", rep_id="rep1", center_id="c1", visit_date=datetime.datetime.now(), status="flagged")
    db.add(v2)
    db.commit()
    v2_item = VisitItem(id="item2", visit_id="v2", product_id="prod1", qty_sold=3, price_at_sale=10.0) # $30 revenue (excluded)
    db.add(v2_item)
    db.commit()

    # Test 1: Revenue Calculation
    sys_overview = get_system_overview(db=db, current_user=admin)
    analytics_resp = get_analytics(start_date=first_of_month, end_date=today, db=db, current_user=admin)
    
    assert sys_overview.total_revenue == 50.0, f"Expected 50.0, got {sys_overview.total_revenue}"
    assert analytics_resp.total_revenue == 50.0, f"Expected 50.0, got {analytics_resp.total_revenue}"
    assert sys_overview.total_revenue == analytics_resp.total_revenue, "Endpoints must match"

    # Test 2: User Creation Authorization
    payload = UserCreate(
        email="new@test.com", full_name="New User", role="rep",
        temporary_password="temp", brand_id="brand1", supervisor_id="sup"
    )

    # Overseer -> 403
    try:
        create_user(payload=payload, current_user=overseer, db=db)
        assert False, "Should raise 403"
    except HTTPException as e:
        assert e.status_code == 403

    # Supervisor -> 403
    try:
        create_user(payload=payload, current_user=supervisor, db=db)
        assert False, "Should raise 403"
    except HTTPException as e:
        assert e.status_code == 403

    # Admin -> Success
    new_user = create_user(payload=payload, current_user=admin, db=db)
    assert new_user.email == "new@test.com"
    assert new_user.must_change_password == True
    assert new_user.created_by == admin.id

    print("All tests passed!")
    db.close()

if __name__ == "__main__":
    test_revenue_and_admin_creation()
