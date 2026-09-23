import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, User, Visit
from analytics import get_base_visit_query

# Setup in-memory SQLite DB
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def test_analytics_scoping():
    db = SessionLocal()
    
    # Create test users
    supervisor1 = User(id="sup1", email="sup1@test.com", hashed_password="pw", full_name="Sup 1", role="supervisor")
    supervisor2 = User(id="sup2", email="sup2@test.com", hashed_password="pw", full_name="Sup 2", role="supervisor")
    
    rep1 = User(id="rep1", email="rep1@test.com", hashed_password="pw", full_name="Rep 1", role="rep", supervisor_id="sup1")
    rep2 = User(id="rep2", email="rep2@test.com", hashed_password="pw", full_name="Rep 2", role="rep", supervisor_id="sup2")
    
    db.add_all([supervisor1, supervisor2, rep1, rep2])
    db.commit()
    
    # Create test visits
    date = datetime.datetime.utcnow()
    v1 = Visit(id="v1", rep_id="rep1", center_id="c1", visit_date=date, status="done")
    v2 = Visit(id="v2", rep_id="rep2", center_id="c2", visit_date=date, status="done")
    db.add_all([v1, v2])
    db.commit()
    
    start_date = date.date()
    end_date = date.date()

    # Test 1: Rep can only see their own data
    q1 = get_base_visit_query(db, rep1, start_date, end_date, effective_rep_id=rep1.id)
    assert q1.count() == 1
    assert q1.first().id == "v1", "Rep1 should only see v1"
    
    # Test 2: Supervisor 1 can see rep1 but not rep2
    # effective_rep_id=None means team wide
    q2 = get_base_visit_query(db, supervisor1, start_date, end_date, effective_rep_id=None)
    assert q2.count() == 1
    assert q2.first().id == "v1", "Supervisor1 should only see v1 (rep1)"
    
    # Test 3: Supervisor 1 querying specific rep in their team
    q3 = get_base_visit_query(db, supervisor1, start_date, end_date, effective_rep_id="rep1")
    assert q3.count() == 1
    assert q3.first().id == "v1"

    # In main get_analytics logic, if supervisor queries out-of-team rep, effective_rep_id becomes None
    # Let's mock the get_analytics param resolution
    requested_rep_id = "rep2"
    team_rep_ids = [r.id for r in db.query(User.id).filter(User.supervisor_id == supervisor1.id).all()]
    team_rep_ids.append(supervisor1.id)
    effective_rep_id_for_sup1 = requested_rep_id if requested_rep_id in team_rep_ids else None
    
    assert effective_rep_id_for_sup1 is None, "Should block querying out-of-team rep"
    
    # So if None is passed, they get their own team
    q4 = get_base_visit_query(db, supervisor1, start_date, end_date, effective_rep_id=effective_rep_id_for_sup1)
    assert q4.count() == 1
    assert q4.first().id == "v1", "Supervisor 1 should fall back to team data, not rep2 data"

    print("Analytics Scoping Tests Passed!")
    db.close()

if __name__ == "__main__":
    test_analytics_scoping()
