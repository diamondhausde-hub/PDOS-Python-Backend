import sqlite3
import sys

def check_schema():
    conn = sqlite3.connect('pdos.db')
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(brand_activity_logs);")
    columns = [row[1] for row in cursor.fetchall()]
    print("Columns:", columns)

if __name__ == "__main__":
    check_schema()
