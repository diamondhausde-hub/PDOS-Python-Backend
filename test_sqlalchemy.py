from database import SessionLocal
import models
from sqlalchemy.orm import joinedload

def test():
    db = SessionLocal()
    task_id = "9a399aa2-164a-413d-86e6-b9fcf635c1cf"

    db_task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if not db_task:
        print("Task not found")
        return
    
    print("Initial task status:", db_task.status)
    db_task.status = "done" if db_task.status != "done" else "in_progress"
    
    db.commit()
    print("Commit done.")

    try:
        db_task = db.query(models.Task).options(
            joinedload(models.Task.rep),
            joinedload(models.Task.brand),
            joinedload(models.Task.supervisor),
        ).get(task_id)
        
        # Test lazy load block if it was expired
        print("Rep full_name:", db_task.rep.full_name if db_task.rep else None)
        print("Brand name:", db_task.brand.name if db_task.brand else None)
        print("Supervisor full_name:", db_task.supervisor.full_name if db_task.supervisor else None)
        print("Success")
    except Exception as e:
        print("Exception:", type(e).__name__, e)

if __name__ == "__main__":
    test()
