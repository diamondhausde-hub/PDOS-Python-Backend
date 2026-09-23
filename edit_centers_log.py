import re

with open('routers/centers_router.py', 'r', encoding='utf-8') as f:
    text = f.read()

replacement = '''    db.commit()
    db.refresh(new_center)
    
    create_activity_log(db, current_user.id, current_user.full_name, f"Added a new center: {new_center.name}", "user", new_center.id)
    
    return new_center'''

text = text.replace('''    db.commit()
    db.refresh(new_center)
    return new_center''', replacement)

with open('routers/centers_router.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")
