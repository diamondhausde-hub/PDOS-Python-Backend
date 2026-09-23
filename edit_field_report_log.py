import re

with open('routers/misc_router.py', 'r', encoding='utf-8') as f:
    text = f.read()

replacement = '''    db.commit()
    db.refresh(db_report)
    
    create_activity_log(db, current_user.id, current_user.full_name, f"Submitted a field report: {db_report.content[:30]}...", "alert", db_report.id)
    
    return db_report'''

text = text.replace('''    db.commit()
    db.refresh(db_report)
    return db_report''', replacement)

with open('routers/misc_router.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")
