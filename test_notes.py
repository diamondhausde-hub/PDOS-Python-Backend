from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from models import Base, User, Notification, Note
from schemas import NoteCreate
import main

# Setup in-memory SQLite DB
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_users(db):
    gm = User(id="gm", email="gm@test.com", hashed_password="pw", full_name="مدير عام", role="general_manager")
    supa = User(id="supa", email="supa@test.com", hashed_password="pw", full_name="مشرف أ", role="supervisor")
    supb = User(id="supb", email="supb@test.com", hashed_password="pw", full_name="مشرف ب", role="supervisor")
    rep1 = User(id="rep1", email="rep1@test.com", hashed_password="pw", full_name="مندوب 1", role="rep", supervisor_id="supa")
    rep2 = User(id="rep2", email="rep2@test.com", hashed_password="pw", full_name="مندوب 2", role="rep", supervisor_id="supb")
    db.add_all([gm, supa, supb, rep1, rep2])
    db.commit()
    return gm, supa, supb, rep1, rep2


def expect_403(fn):
    try:
        fn()
    except HTTPException as e:
        assert e.status_code == 403, f"expected 403, got {e.status_code}: {e.detail}"
        return
    raise AssertionError("expected HTTPException 403 but call succeeded")


def run():
    db = SessionLocal()
    gm, supa, supb, rep1, rep2 = setup_users(db)

    # 1. Supervisor → own rep: allowed
    n = main.send_note(rep1.id, NoteCreate(content="أحسنت", visit_id="v1"), current_user=supa, db=db)
    assert n.sender_id == "supa" and n.recipient_id == "rep1"
    assert n.visit_id == "v1"
    assert n.sender_name == "مشرف أ" and n.recipient_name == "مندوب 1"
    assert db.query(Notification).filter(Notification.user_id == "rep1", Notification.type == "direct_note").count() == 1

    # 2. Supervisor → other team rep: 403
    expect_403(lambda: main.send_note(rep2.id, NoteCreate(content="x"), current_user=supa, db=db))

    # 3. Supervisor → supervisor: 403
    expect_403(lambda: main.send_note(supb.id, NoteCreate(content="x"), current_user=supa, db=db))

    # 4. GM → supervisor: allowed
    main.send_note(supa.id, NoteCreate(content="تقرير الربع"), current_user=gm, db=db)

    # 5. GM → rep: allowed
    main.send_note(rep2.id, NoteCreate(content="متابعة"), current_user=gm, db=db)

    # 6. Rep → anyone: 403
    expect_403(lambda: main.send_note(supa.id, NoteCreate(content="x"), current_user=rep1, db=db))

    # 7. GET scoping: supervisor sees own team + self only
    sup_notes = main.list_notes(current_user=supa, db=db)
    assert {x.recipient_id for x in sup_notes} <= {"rep1", "supa"}, sup_notes
    assert len(sup_notes) == 2  # rep1 note + GM→supa note

    # 8. GET scoping: rep sees only own notes
    rep1_notes = main.list_notes(current_user=rep1, db=db)
    assert len(rep1_notes) == 1 and rep1_notes[0].recipient_id == "rep1"

    # 9. GET scoping: GM sees all
    gm_notes = main.list_notes(current_user=gm, db=db)
    assert len(gm_notes) == 3

    # 10. visit_id filter
    v1_notes = main.list_notes(visit_id="v1", current_user=gm, db=db)
    assert len(v1_notes) == 1 and v1_notes[0].content == "أحسنت"

    # 11. user_id filter
    rep2_notes = main.list_notes(user_id="rep2", current_user=gm, db=db)
    assert len(rep2_notes) == 1 and rep2_notes[0].recipient_id == "rep2"

    # 12. Persistence: delete the notification, note must survive
    db.query(Notification).filter(Notification.user_id == "rep1").delete()
    db.commit()
    survived = main.list_notes(user_id="rep1", current_user=gm, db=db)
    assert len(survived) == 1 and survived[0].content == "أحسنت"

    # 13. Old endpoint wrapper still works
    n2 = main.send_note_to_rep(rep1.id, NoteCreate(content="قديم"), current_user=supa, db=db)
    assert n2.recipient_id == "rep1"

    db.close()
    print("ALL NOTE TESTS PASSED")


if __name__ == "__main__":
    run()
