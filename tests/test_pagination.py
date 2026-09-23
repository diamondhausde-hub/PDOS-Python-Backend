import pytest
from fastapi.testclient import TestClient
from main import app
from routers.deps import get_db
import auth
from models import Base, Client, FieldReport, ActivityLog, User
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sqlalchemy.pool import StaticPool

# In‑memory SQLite database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create tables
Base.metadata.create_all(bind=engine)

# Override DB dependency

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

# Mock authentication to bypass JWT and provide an admin user

def mock_require_password_set():
    return User(id="admin-id", role="admin")

app.dependency_overrides[auth.require_password_set] = mock_require_password_set

client = TestClient(app)

def seed_clients(db):
    for i in range(5):
        db.add(Client(facility_name=f"Client {i}", rep_id="rep-1"))
    db.commit()

def seed_field_reports(db):
    for i in range(5):
        db.add(FieldReport(content=f"Report {i}", rep_id="rep-1"))
    db.commit()

def seed_audit_logs(db):
    for i in range(5):
        db.add(ActivityLog(action=f"action_{i}", user_name="admin", log_type="system", user_id="admin-id"))
    db.commit()

@pytest.fixture(autouse=True)
def setup_db():
    db = TestingSessionLocal()
    seed_clients(db)
    seed_field_reports(db)
    seed_audit_logs(db)
    db.close()

def test_clients_pagination():
    response = client.get("/clients?limit=2&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2

def test_field_reports_pagination():
    response = client.get("/field-reports?limit=2&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2

def test_audit_logs_pagination():
    response = client.get("/audit-logs?limit=2&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2
