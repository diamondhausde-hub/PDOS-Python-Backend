import re

with open('routers/misc_router.py', 'r', encoding='utf-8') as f:
    text = f.read()

replacement = '''    db.commit()
    db.refresh(new_client)
    
    target_name = new_client.doctor_name if new_client.client_type == 'doctor' else new_client.facility_name
    create_activity_log(db, current_user.id, current_user.full_name, f"Added a new {new_client.client_type}: {target_name}", "user", new_client.id)
    
    return new_client'''

text = text.replace('''    db.commit()
    db.refresh(new_client)
    return new_client''', replacement)

with open('routers/misc_router.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")
