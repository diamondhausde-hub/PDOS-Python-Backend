import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from main import app
from database import Base, get_db
from models import User
import uuid

# Isolated in-memory DB — must never touch the real development database
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
    # Install our DB override only for the duration of each test,
    # so parallel test modules sharing `app` never leak state.
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)

def teardown_module(module):
    pass

def test_live_tracking_role_scoping():
    db = next(override_get_db())
    from auth import get_password_hash
    hashed_pw = get_password_hash("pw")
    
    # Create Supervisor A
    sup_a = User(id=str(uuid.uuid4()), email="supA@example.com", hashed_password=hashed_pw, full_name="Sup A", role="supervisor", is_active=True)
    
    # Create Supervisor B
    sup_b = User(id=str(uuid.uuid4()), email="supB@example.com", hashed_password=hashed_pw, full_name="Sup B", role="supervisor", is_active=True)
    
    # Create Rep under A with location
    rep_a = User(id=str(uuid.uuid4()), email="repA@example.com", hashed_password=hashed_pw, full_name="Rep A", role="rep", supervisor_id=sup_a.id, is_active=True, last_lat=10.0, last_lng=20.0)
    
    # Create Rep under B with location
    rep_b = User(id=str(uuid.uuid4()), email="repB@example.com", hashed_password=hashed_pw, full_name="Rep B", role="rep", supervisor_id=sup_b.id, is_active=True, last_lat=30.0, last_lng=40.0)
    
    db.add_all([sup_a, sup_b, rep_a, rep_b])
    db.commit()

    # Login as Rep A and update location
    login_a = client.post("/auth/login", data={"username": "repA@example.com", "password": "pw"})
    token_a = login_a.json()["access_token"]
    
    res = client.put("/users/me/location", json={"lat": 11.0, "lng": 21.0}, headers={"Authorization": f"Bearer {token_a}"})
    assert res.status_code == 200

    # Login as Sup A and get team locations
    login_sup_a = client.post("/auth/login", data={"username": "supA@example.com", "password": "pw"})
    token_sup_a = login_sup_a.json()["access_token"]
    
    res = client.get("/users/team/locations", headers={"Authorization": f"Bearer {token_sup_a}"})
    assert res.status_code == 200
    locations = res.json()
    assert len(locations) == 1
    assert locations[0]["id"] == rep_a.id
    assert locations[0]["last_lat"] == 11.0
    assert locations[0]["last_lng"] == 21.0
