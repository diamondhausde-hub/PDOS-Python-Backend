import sqlite3

def migrate():
    print("Starting migration...")
    conn = sqlite3.connect('pdos.db')
    cursor = conn.cursor()

    columns_to_add = [
        ("purpose", "VARCHAR(30)"),
        ("visit_subtype", "VARCHAR(20)"),
        ("scheduled_datetime", "DATETIME"),
        ("rejection_report", "TEXT"),
        ("reminder_offset", "VARCHAR(10)"),
        ("accepted_at", "DATETIME"),
        ("visit_id", "VARCHAR")
    ]

    for col_name, col_type in columns_to_add:
        try:
            cursor.execute(f"ALTER TABLE tasks ADD COLUMN {col_name} {col_type}")
            print(f"Added column {col_name}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e).lower():
                print(f"Column {col_name} already exists.")
            else:
                print(f"Error adding {col_name}: {e}")

    try:
        cursor.execute("UPDATE tasks SET status = 'pending' WHERE status = 'new'")
        print(f"Updated {cursor.rowcount} tasks from 'new' to 'pending'")
    except Exception as e:
        print(f"Error updating statuses: {e}")

    conn.commit()
    conn.close()
    print("Migration complete.")

if __name__ == "__main__":
    migrate()
