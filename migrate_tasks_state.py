import sqlite3

def migrate():
    conn = sqlite3.connect('pdos.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute("ALTER TABLE tasks ADD COLUMN visit_started_at DATETIME")
    except sqlite3.OperationalError:
        pass
        
    try:
        cursor.execute("ALTER TABLE tasks ADD COLUMN visit_completed_at DATETIME")
    except sqlite3.OperationalError:
        pass
        
    conn.commit()
    conn.close()
    print("Migration completed.")

if __name__ == "__main__":
    migrate()
