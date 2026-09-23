import sqlite3
conn = sqlite3.connect(r'C:\Users\prot\Documents\PDOS\PDOS-Python-Backend\pdos.db')
cursor = conn.cursor()

# Add new columns to tasks table
for col, typ in [
    ('target_name', 'VARCHAR'),
    ('notes', 'TEXT'),
    ('is_deleted', 'BOOLEAN DEFAULT 0'),
]:
    try:
        cursor.execute(f"ALTER TABLE tasks ADD COLUMN {col} {typ};")
        print(f"Added {col}")
    except Exception as e:
        print(f"{col}: {e}")

# Create task_history table
cursor.execute("""
CREATE TABLE IF NOT EXISTS task_history (
    id VARCHAR PRIMARY KEY,
    task_id VARCHAR NOT NULL REFERENCES tasks(id),
    action VARCHAR(20) NOT NULL,
    old_status VARCHAR(20),
    new_status VARCHAR(20),
    changed_by VARCHAR NOT NULL REFERENCES users(id),
    note TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
""")
print("task_history table created")

conn.commit()
conn.close()
print("DB migration complete!")
