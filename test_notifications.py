import datetime
import asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, User, Visit, Product, Appointment, VisitItem, Center, Notification, Brand
from schemas import VisitCreate, VisitReviewRequest
from fastapi.testclient import TestClient
from fastapi import HTTPException
import pytest

from main import app, get_db
from routers.visits_router import create_visit, review_visit

# Setup in-memory SQLite DB
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

async def _notification_triggers_scenario():
    db = SessionLocal()
    
    # Users
    supervisor = User(id="sup", email="sup@test.com", hashed_password="pw", full_name="Sup", role="supervisor")
    rep = User(id="rep1", email="rep1@test.com", hashed_password="pw", full_name="Rep 1", role="rep", supervisor_id="sup")
    db.add_all([supervisor, rep])
    db.commit()

    # Brand + Center
    brand = Brand(id="brand1", name="Test Brand")
    center = Center(id="c1", name="C1", latitude=30.0, longitude=40.0, brand_id="brand1")
    db.add_all([brand, center])
    db.commit()

    # Test 1: Flagged Check-in generates notification for Supervisor
    payload = VisitCreate(
        id="v1",
        center_id="c1",
        visit_date=datetime.datetime.now(),
        latitude=30.1, # far away -> flagged
        longitude=40.1
    )
    
    visit_res = await create_visit(visit=payload, current_user=rep, db=db)
    assert visit_res.status == "flagged"
    
    # Check supervisor notification
    sup_notif = db.query(Notification).filter(Notification.user_id == supervisor.id).first()
    assert sup_notif is not None
    assert sup_notif.type == "visit_flagged"
    assert sup_notif.related_id == "v1"
    
    # Test 2: Supervisor Review generates notification for Rep
    review_res = review_visit("v1", VisitReviewRequest(status="completed", note="Looks ok"), current_user=supervisor, db=db)
    assert review_res.status == "completed"
    
    # Check rep notification
    rep_notif = db.query(Notification).filter(Notification.user_id == rep.id).first()
    assert rep_notif is not None
    assert rep_notif.type == "visit_reviewed"
    assert rep_notif.related_id == "v1"

    print("Notification trigger tests passed!")
    db.close()

def test_notification_triggers():
    asyncio.run(_notification_triggers_scenario())

if __name__ == "__main__":
    asyncio.run(test_notification_triggers())
