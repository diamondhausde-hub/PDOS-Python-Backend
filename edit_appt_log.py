import re

with open('routers/visits_router.py', 'r', encoding='utf-8') as f:
    text = f.read()

replacement = '''    db.add(a)
    db.commit()
    db.refresh(a)

    center = db.query(models.Center).filter(models.Center.id == a.center_id).first()
    client = db.query(models.Client).filter(models.Client.id == a.client_id).first() if a.client_id else None
    target_name = client.doctor_name if (client and client.doctor_name) else (client.facility_name if client else (center.name if center else "Unknown"))
    
    create_activity_log(db, current_user.id, current_user.full_name, f"Scheduled an appointment with {target_name} on {a.appt_date}", "visit", a.id)'''

text = text.replace('''    db.add(a)
    db.commit()
    db.refresh(a)''', replacement)

with open('routers/visits_router.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")
