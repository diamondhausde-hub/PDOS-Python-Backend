import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, User, Visit, Center, SystemSetting, Brand
from routers.centers_router import get_coverage
from fastapi import HTTPException

# Setup in-memory SQLite DB
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def test_coverage_logic():
    db = SessionLocal()
    
    # Create setting
    setting = SystemSetting(key="coverage_neglect_days", value="14")
    
    # Create test users
    sup1 = User(id="sup1", email="sup1@test.com", hashed_password="pw", full_name="Sup 1", role="supervisor")
    sup2 = User(id="sup2", email="sup2@test.com", hashed_password="pw", full_name="Sup 2", role="supervisor")
    rep1 = User(id="rep1", email="rep1@test.com", hashed_password="pw", full_name="Rep 1", role="rep", supervisor_id="sup1")
    rep2 = User(id="rep2", email="rep2@test.com", hashed_password="pw", full_name="Rep 2", role="rep", supervisor_id="sup2")
    
    # Create brand and centers
    brand = Brand(id="brand1", name="Test Brand")
    c1 = Center(id="c1", name="Center 1", latitude=10.0, longitude=20.0, assigned_rep_id="rep1", is_active=True, brand_id="brand1")
    c2 = Center(id="c2", name="Center 2", latitude=11.0, longitude=21.0, assigned_rep_id="rep2", is_active=True, brand_id="brand1")
    
    db.add_all([setting, sup1, sup2, rep1, rep2, brand, c1, c2])
    db.commit()
    
    today = datetime.date.today()
    
    # Visit 1: by rep1 to c1 (10 days ago, completed)
    v1_date = datetime.datetime.combine(today - datetime.timedelta(days=10), datetime.time(10, 0))
    v1 = Visit(id="v1", rep_id="rep1", center_id="c1", visit_date=v1_date, status="done")
    
    # Visit 2: by rep1 to c1 (yesterday, rejected)
    v2_date = datetime.datetime.combine(today - datetime.timedelta(days=1), datetime.time(10, 0))
    v2 = Visit(id="v2", rep_id="rep1", center_id="c1", visit_date=v2_date, status="rejected")
    
    # Visit 3: by rep2 to c2 (20 days ago, completed)
    v3_date = datetime.datetime.combine(today - datetime.timedelta(days=20), datetime.time(10, 0))
    v3 = Visit(id="v3", rep_id="rep2", center_id="c2", visit_date=v3_date, status="done")

    db.add_all([v1, v2, v3])
    db.commit()
    
    # Test 1: Supervisor 1 coverage
    res_sup1 = get_coverage(current_user=sup1, db=db)
    
    c1_res = next((x for x in res_sup1 if x["center_id"] == "c1"), None)
    c2_res = next((x for x in res_sup1 if x["center_id"] == "c2"), None)
    
    assert c1_res is not None
    # the last valid visit is v1 (10 days ago), because v2 is rejected.
    assert c1_res["last_visit_date"] == v1_date
    assert c1_res["status"] == "visited"
    
    # c2_res should have NO valid visit returned because supervisor 1 doesn't oversee rep2!
    assert c2_res is not None
    assert c2_res["last_visit_date"] is None
    assert c2_res["status"] == "neglected"
    
    # Test 2: Supervisor 2 coverage
    res_sup2 = get_coverage(current_user=sup2, db=db)
    c2_res_sup2 = next((x for x in res_sup2 if x["center_id"] == "c2"), None)
    
    assert c2_res_sup2["last_visit_date"] == v3_date
    assert c2_res_sup2["status"] == "neglected" # 20 days > 14 days
    
    print("Coverage tests passed!")

if __name__ == "__main__":
    test_coverage_logic()
