import sqlite3
conn = sqlite3.connect('C:/Users/prot/Documents/PDOS/PDOS-Python-Backend/pdos.db')
c = conn.cursor()
try:
    c.execute('ALTER TABLE tasks ADD COLUMN product_name VARCHAR')
    conn.commit()
    print("Column added")
except Exception as e:
    print(e)
conn.close()
