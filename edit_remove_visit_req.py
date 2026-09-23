import re

with open('routers/visits_router.py', 'r', encoding='utf-8') as f:
    text = f.read()

bad_checkin = '''    db.commit()
    db.refresh(new_visit)
    for req in visit.special_requests:
        if not db.query(models.SpecialRequest).filter(models.SpecialRequest.id == req.id).first():
            db.add(models.SpecialRequest(id=req.id, visit_id=new_visit.id, request_type=req.request_type, description=req.description))
    db.commit()
    db.refresh(new_visit)
    enrich_visits([new_visit], db)
    target_name = client.doctor_name if (client and client.doctor_name) else (client.facility_name if client else (center.name if center else "Unknown target"))
    create_activity_log(db, current_user.id, current_user.full_name, f"Checked in at {target_name}", "visit", new_visit.id)
    await manager.broadcast("refresh_analytics")
    return new_visit'''

good_checkin = '''    db.commit()
    db.refresh(new_visit)
    enrich_visits([new_visit], db)
    target_name = client.doctor_name if (client and client.doctor_name) else (client.facility_name if client else (center.name if center else "Unknown target"))
    create_activity_log(db, current_user.id, current_user.full_name, f"Checked in at {target_name}", "visit", new_visit.id)
    await manager.broadcast("refresh_analytics")
    return new_visit'''

text = text.replace(bad_checkin, good_checkin)

with open('routers/visits_router.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")
