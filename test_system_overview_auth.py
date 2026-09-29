import datetime
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from database import Base, get_db
import models
from auth import create_access_token

# Isolated in-memory DB
engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
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

def setup_test_environment():
    db = TestingSessionLocal()
    # Clean tables
    db.query(models.VisitItem).delete()
    db.query(models.Visit).delete()
    db.query(models.Appointment).delete()
    db.query(models.Center).delete()
    db.query(models.Product).delete()
    db.query(models.User).delete()
    db.query(models.Brand).delete()
    db.commit()

    # Create 3 Brands
    b1 = models.Brand(id="b1", name="Brand One")
    b2 = models.Brand(id="b2", name="Brand Two")
    b3 = models.Brand(id="b3", name="Brand Three")
    db.add_all([b1, b2, b3])
    db.commit()

    # Create Users
    admin = models.User(id="u_admin", email="admin@test.com", hashed_password="x", role="admin", is_active=True, full_name="Admin User", must_change_password=False)
    gm = models.User(id="u_gm", email="gm@test.com", hashed_password="x", role="general_manager", is_active=True, full_name="GM User", must_change_password=False)
    overseer = models.User(id="u_ov", email="ov@test.com", hashed_password="x", role="overseer", is_active=True, full_name="Overseer User", must_change_password=False)
    sup1 = models.User(id="u_sup1", email="sup1@test.com", hashed_password="x", role="supervisor", brand_id="b1", is_active=True, full_name="Supervisor Brand 1", must_change_password=False)
    sup2 = models.User(id="u_sup2", email="sup2@test.com", hashed_password="x", role="supervisor", brand_id="b2", is_active=True, full_name="Supervisor Brand 2", must_change_password=False)
    sup_multi = models.User(id="u_sup_multi", email="sup_multi@test.com", hashed_password="x", role="supervisor", brand_id="b1", is_active=True, full_name="Supervisor Multi", must_change_password=False)
    rep1 = models.User(id="u_rep1", email="rep1@test.com", hashed_password="x", role="rep", brand_id="b1", supervisor_id="u_sup1", is_active=True, full_name="Rep 1", must_change_password=False)

    db.add_all([admin, gm, overseer, sup1, sup2, sup_multi, rep1])
    db.commit()

    # Assign sup_multi to both b1 and b2 via UserBrand
    ub1 = models.UserBrand(user_id="u_sup_multi", brand_id="b1")
    ub2 = models.UserBrand(user_id="u_sup_multi", brand_id="b2")
    db.add_all([ub1, ub2])
    db.commit()

    # Create Products
    p1 = models.Product(id="p1", name="Prod 1", brand_id="b1", category="Cat 1", price=10.0, stock_qty=5, min_threshold=10) # low stock
    p2 = models.Product(id="p2", name="Prod 2", brand_id="b2", category="Cat 2", price=20.0, stock_qty=50, min_threshold=10)
    db.add_all([p1, p2])

    # Create Centers
    c1 = models.Center(id="c1", name="Center 1", brand_id="b1", region="North", is_active=True)
    c2 = models.Center(id="c2", name="Center 2", brand_id="b2", region="South", is_active=True)
    db.add_all([c1, c2])

    # Create Appointments
    appt1 = models.Appointment(id="a1", rep_id="u_rep1", center_id="c1", appt_date=datetime.datetime.utcnow(), appt_time="10:00", status="pending")
    db.add(appt1)

    db.commit()
    db.close()

def _auth_header(user_id: str, role: str):
    token = create_access_token(data={"sub": user_id, "role": role})
    return {"Authorization": f"Bearer {token}"}

def test_system_overview_authorization():
    setup_test_environment()

    # 1. Unauthenticated -> 401
    res = client.get("/analytics/system-overview")
    assert res.status_code == 401

    # 2. Rep -> 200 OK (scoped to rep brand)
    rep_headers = _auth_header("u_rep1", "rep")
    res = client.get("/analytics/system-overview", headers=rep_headers)
    assert res.status_code == 200

    # 3. Admin -> 200 OK (all brands)
    admin_headers = _auth_header("u_admin", "admin")
    res = client.get("/analytics/system-overview", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total_centers"] == 2
    assert data["total_products"] == 2

    # 4. Admin with brand_id -> 200 OK (scoped to b1)
    res = client.get("/analytics/system-overview?brand_id=b1", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total_centers"] == 1
    assert data["total_products"] == 1

    # 5. General Manager -> 200 OK
    gm_headers = _auth_header("u_gm", "general_manager")
    res = client.get("/analytics/system-overview", headers=gm_headers)
    assert res.status_code == 200

    # 6. Overseer -> 200 OK
    ov_headers = _auth_header("u_ov", "overseer")
    res = client.get("/analytics/system-overview", headers=ov_headers)
    assert res.status_code == 200

    # 7. Supervisor 1 querying their assigned brand b1 -> 200 OK
    sup1_headers = _auth_header("u_sup1", "supervisor")
    res = client.get("/analytics/system-overview?brand_id=b1", headers=sup1_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total_centers"] == 1
    assert data["total_products"] == 1
    assert data["pending_appointments"] == 1

    # 8. Supervisor 1 querying without brand_id -> 200 OK, automatically scoped to their assigned brand b1
    res = client.get("/analytics/system-overview", headers=sup1_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total_centers"] == 1
    assert data["total_products"] == 1

    # 9. Supervisor 1 querying an UNASSIGNED brand (b2) -> gracefully scopes to their assigned brand b1
    res = client.get("/analytics/system-overview?brand_id=b2", headers=sup1_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total_centers"] == 1
    assert data["total_products"] == 1

    # 10. Multi-Brand Supervisor querying their secondary assigned brand b2 -> 200 OK (reproduced real log failure)
    sup_multi_headers = _auth_header("u_sup_multi", "supervisor")
    res = client.get("/analytics/system-overview?brand_id=b2", headers=sup_multi_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total_centers"] == 1
    assert data["total_products"] == 1

    # 11. Multi-Brand Supervisor querying an UNASSIGNED brand b3 -> gracefully scopes to their assigned brand b1
    res = client.get("/analytics/system-overview?brand_id=b3", headers=sup_multi_headers)
    assert res.status_code == 200
