import datetime
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from auth import create_access_token, get_password_hash
from database import Base, get_db
from main import app


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
client = TestClient(app)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def _user(db, email, role="rep", active=True, supervisor_id=None, password="pw"):
    user = models.User(
        id=str(uuid.uuid4()),
        email=email,
        hashed_password=get_password_hash(password),
        full_name=email,
        role=role,
        is_active=active,
        supervisor_id=supervisor_id,
        must_change_password=False,
    )
    db.add(user)
    db.commit()
    return user


def _headers(user):
    token = create_access_token({"sub": user.id, "role": user.role})
    return {"Authorization": f"Bearer {token}"}


def setup_function():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db


def teardown_function():
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=engine)


def test_login_rejects_inactive_user():
    db = TestingSessionLocal()
    _user(db, "inactive@example.com", active=False)

    response = client.post(
        "/auth/login",
        data={"username": "inactive@example.com", "password": "pw"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "User account is inactive"


def test_check_in_client_target_and_existing_visit_authorization():
    db = TestingSessionLocal()
    owner = _user(db, "owner@example.com")
    other = _user(db, "other@example.com")
    client_target = models.Client(
        id=str(uuid.uuid4()),
        rep_id=owner.id,
        doctor_name="Dr. Target",
        client_type="doctor",
    )
    db.add(client_target)
    db.commit()
    visit_id = str(uuid.uuid4())

    first = client.post(
        "/visits/check-in",
        headers=_headers(owner),
        json={"visit_id": visit_id, "client_id": client_target.id},
    )
    assert first.status_code == 200, first.text
    assert first.json()["client_id"] == client_target.id

    unauthorized = client.post(
        "/visits/check-in",
        headers=_headers(other),
        json={"visit_id": visit_id, "client_id": client_target.id},
    )
    assert unauthorized.status_code == 403

    stored = db.query(models.Visit).filter(models.Visit.id == visit_id).one()
    assert stored.rep_id == owner.id


def test_create_visit_is_idempotent_and_stock_is_decremented_once():
    db = TestingSessionLocal()
    rep = _user(db, "stock@example.com")
    brand = models.Brand(id=str(uuid.uuid4()), name="Stock Brand")
    product = models.Product(
        id=str(uuid.uuid4()),
        name="Sample",
        price=10,
        category="sample",
        stock_qty=10,
        brand_id=brand.id,
    )
    db.add_all([brand, product])
    db.commit()
    visit_id = str(uuid.uuid4())
    payload = {
        "id": visit_id,
        "visit_date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "status": "completed",
        "items": [{"product_id": product.id, "qty_sold": 2, "qty_free": 0}],
    }

    first = client.post("/visits", headers=_headers(rep), json=payload)
    second = client.post("/visits", headers=_headers(rep), json=payload)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    db.refresh(product)
    assert product.stock_qty == 8
    assert db.query(models.VisitItem).filter(models.VisitItem.visit_id == visit_id).count() == 1


def test_rep_id_filter_is_limited_by_rbac_scope():
    db = TestingSessionLocal()
    supervisor = _user(db, "supervisor@example.com", role="supervisor")
    team_rep = _user(db, "team@example.com", supervisor_id=supervisor.id)
    outside_rep = _user(db, "outside@example.com")
    for rep in (team_rep, outside_rep):
        db.add(
            models.Visit(
                id=str(uuid.uuid4()),
                rep_id=rep.id,
                visit_date=datetime.datetime.now(datetime.timezone.utc),
            )
        )
    db.commit()

    allowed = client.get(
        f"/visits?rep_id={team_rep.id}",
        headers=_headers(supervisor),
    )
    denied = client.get(
        f"/visits?rep_id={outside_rep.id}",
        headers=_headers(supervisor),
    )

    assert allowed.status_code == 200
    assert {visit["rep_id"] for visit in allowed.json()} == {team_rep.id}
    assert denied.status_code == 403
