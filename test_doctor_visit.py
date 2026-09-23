"""Integration test for the doctor-visit flow (safe to keep in CI)."""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pytest
import uuid
import datetime

from database import Base, get_db
from main import app
import models
from auth import create_access_token, get_current_user

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_db():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


def _make_token(db, role, email):
    uid = str(uuid.uuid4())
    db.add(models.User(id=uid, email=email, hashed_password="x", full_name=email,
                       role=role, is_active=True, must_change_password=False))
    db.commit()
    return create_access_token({"sub": uid, "role": role})


def test_doctor_visit_flow():
    db = TestingSessionLocal()
    rep_token = _make_token(db, "rep", "docrep@test.com")
    sup_token = _make_token(db, "supervisor", "docsup@test.com")
    gm_token = _make_token(db, "general_manager", "docgm@test.com")
    rep_id = db.query(models.User).filter(models.User.email == "docrep@test.com").first().id
    # wire supervisor -> rep
    sup_id = db.query(models.User).filter(models.User.email == "docsup@test.com").first().id
    db.query(models.User).filter(models.User.id == rep_id).update({"supervisor_id": sup_id})
    db.commit()
    headers_rep = {"Authorization": f"Bearer {rep_token}"}

    # 1. Rep creates a new doctor client with profile + evaluation
    r = client.post("/clients", headers=headers_rep, json={
        "id": str(uuid.uuid4()), "rep_id": rep_id,
        "doctor_name": "Dr. House", "specialty": "Nephrology",
        "birth_date": "1970-05-04T00:00:00", "gender": "male",
        "class_tier": "A", "rating": 5, "treatment_quality": "good",
    })
    assert r.status_code == 200, r.text
    doctor = r.json()
    assert doctor["gender"] == "male" and doctor["rating"] == 5

    # 2. Rep submits a completed DOCTOR visit referencing the client
    visit_payload = {
        "id": str(uuid.uuid4()),
        "client_id": doctor["id"],
        "visit_date": datetime.datetime.now().isoformat(),
        "status": "completed",
        "latitude": 33.31, "longitude": 44.36,
        "visit_type": "doctor",
        "visit_reason": "Introduce new product line",
        "interested_product_ids": ["p1", "p2"],
        "notes": "Great meeting, strong interest.",
    }
    r2 = client.post("/visits", headers=headers_rep, json=visit_payload)
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["visit_type"] == "doctor"
    assert body["visit_reason"] == "Introduce new product line"
    assert body["interested_product_ids"] == ["p1", "p2"]

    # 3. Supervisor + GM received the completion notification
    notifs_sup = db.query(models.Notification).filter(
        models.Notification.user_id == sup_id,
        models.Notification.type == "doctor_visit_completed",
    ).count()
    assert notifs_sup >= 1, "Supervisor must be notified"

    gm_user = db.query(models.User).filter(models.User.email == "docgm@test.com").first()
    notifs_gm = db.query(models.Notification).filter(
        models.Notification.user_id == gm_user.id,
        models.Notification.type == "doctor_visit_completed",
    ).count()
    assert notifs_gm >= 1, "GM must be notified"

    # sanity: center visits still default to type 'center'
    v_center = dict(visit_payload, id=str(uuid.uuid4()))
    v_center.pop("visit_type")
    r3 = client.post("/visits", headers=headers_rep, json=v_center)
    assert r3.json()["visit_type"] == "center"
