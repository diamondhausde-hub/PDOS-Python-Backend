import pytest
import uuid
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app
from auth import get_password_hash, get_current_user
import models

# In-memory SQLite for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    # Install overrides only for the duration of each test and clean up,
    # so other test modules sharing `app` never inherit our state.
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    db = TestingSessionLocal()

    # Create test users for different roles
    admin = models.User(id="admin_id", email="admin@test.com", hashed_password="hash", full_name="Admin", role="admin")
    overseer = models.User(id="overseer_id", email="overseer@test.com", hashed_password="hash", full_name="Overseer", role="overseer")
    rep = models.User(id="rep_id", email="rep@test.com", hashed_password="hash", full_name="Rep", role="rep")
    
    # Create initial setting
    setting = models.SystemSetting(key="geofence_radius_meters", value="500.0")
    
    db.add_all([admin, overseer, rep, setting])
    db.commit()
    yield
    db.close()
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)
    Base.metadata.drop_all(bind=engine)

def get_auth_override(role: str):
    def _override():
        db = TestingSessionLocal()
        user = db.query(models.User).filter(models.User.role == role).first()
        db.close()
        return user
    return _override

def test_get_settings_as_rep():
    # Reps may READ settings (the app fetches geofence radius etc.);
    # writes remain admin-only.
    app.dependency_overrides[get_current_user] = get_auth_override("rep")
    response = client.get("/settings")
    assert response.status_code == 200

def test_get_settings_as_admin():
    app.dependency_overrides[get_current_user] = get_auth_override("admin")
    response = client.get("/settings")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["key"] == "geofence_radius_meters"

def test_update_settings_as_overseer():
    app.dependency_overrides[get_current_user] = get_auth_override("overseer")
    response = client.put("/settings/geofence_radius_meters", json={"value": "1000.0"})
    assert response.status_code == 403 # Read-only!

def test_update_settings_as_admin_valid():
    app.dependency_overrides[get_current_user] = get_auth_override("admin")
    response = client.put("/settings/geofence_radius_meters", json={"value": "1000.0"})
    assert response.status_code == 200
    data = response.json()
    assert data["value"] == "1000.0"

def test_update_settings_as_admin_out_of_bounds():
    app.dependency_overrides[get_current_user] = get_auth_override("admin")
    response = client.put("/settings/geofence_radius_meters", json={"value": "10.0"})
    assert response.status_code == 422 # Below 50
    assert "between" in response.json()["detail"]

def test_update_settings_as_admin_out_of_bounds_high():
    app.dependency_overrides[get_current_user] = get_auth_override("admin")
    response = client.put("/settings/geofence_radius_meters", json={"value": "200000.0"})
    assert response.status_code == 422 # Above 100000
    assert "between" in response.json()["detail"]
