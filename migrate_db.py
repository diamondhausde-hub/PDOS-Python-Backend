from database import engine
from sqlalchemy import text
try:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE brand_activity_logs ADD COLUMN target_name VARCHAR"))
        print("Migration successful")
except Exception as e:
    print(f"Migration failed or already applied: {e}")
