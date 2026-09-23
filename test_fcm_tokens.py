import pytest
from fastapi.testclient import TestClient
from main import app
from database import Base, get_db
import models
from auth import create_access_token
import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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

def setup_test_users():
    db = TestingSessionLocal()
    # Cleanup old tokens
    db.query(models.FCMToken).delete()
    db.commit()

    user_a = db.query(models.User).filter(models.User.email == "test_a@pdos.com").first()
    if not user_a:
        user_a = models.User(id="user_a", email="test_a@pdos.com", hashed_password="x", role="rep", is_active=True, full_name="User A", must_change_password=False)
        db.add(user_a)

    user_b = db.query(models.User).filter(models.User.email == "test_b@pdos.com").first()
    if not user_b:
        user_b = models.User(id="user_b", email="test_b@pdos.com", hashed_password="x", role="rep", is_active=True, full_name="User B", must_change_password=False)
        db.add(user_b)
        
    db.commit()
    db.refresh(user_a)
    db.refresh(user_b)
    return user_a, user_b

def test_fcm_token_lifecycle():
    user_a, user_b = setup_test_users()
    
    token_a = create_access_token(data={"sub": user_a.id, "role": user_a.role})
    headers_a = {"Authorization": f"Bearer {token_a}"}

    token_b = create_access_token(data={"sub": user_b.id, "role": user_b.role})
    headers_b = {"Authorization": f"Bearer {token_b}"}

    test_fcm_token = "fcm_device_token_xyz123"

    # 1. User A logs in and registers the token
    res = client.post("/users/me/fcm-tokens", json={"token": test_fcm_token}, headers=headers_a)
    assert res.status_code == 200
    
    db = TestingSessionLocal()
    saved = db.query(models.FCMToken).filter(models.FCMToken.token == test_fcm_token).first()
    assert saved is not None
    assert saved.user_id == user_a.id

    # 2. User A registers the SAME token again (e.g. onTokenRefresh)
    res = client.post("/users/me/fcm-tokens", json={"token": test_fcm_token}, headers=headers_a)
    assert res.status_code == 200
    
    db = TestingSessionLocal()
    count = db.query(models.FCMToken).filter(models.FCMToken.token == test_fcm_token).count()
    assert count == 1 # Upserted, didn't create duplicate

    # 3. User B logs in with the SAME device (transfer ownership)
    res = client.post("/users/me/fcm-tokens", json={"token": test_fcm_token}, headers=headers_b)
    assert res.status_code == 200
    
    db = TestingSessionLocal()
    saved = db.query(models.FCMToken).filter(models.FCMToken.token == test_fcm_token).first()
    assert saved.user_id == user_b.id # Successfully transferred to User B
    count_a = db.query(models.FCMToken).filter(models.FCMToken.user_id == user_a.id).count()
    assert count_a == 0 # User A no longer has this token

    # 4. User B logs out, deletes token
    res = client.delete(f"/users/me/fcm-tokens?token={test_fcm_token}", headers=headers_b)
    assert res.status_code == 200
    
    db = TestingSessionLocal()
    count = db.query(models.FCMToken).filter(models.FCMToken.token == test_fcm_token).count()
    assert count == 0 # Token completely removed

if __name__ == "__main__":
    test_fcm_token_lifecycle()
    print("FCM Token lifecycle test passed!")

