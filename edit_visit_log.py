import re

with open('routers/visits_router.py', 'r', encoding='utf-8') as f:
    text = f.read()

replacement = '''    center = db.query(models.Center).filter(models.Center.id == new_visit.center_id).first() if new_visit.center_id else None
    client = db.query(models.Client).filter(models.Client.id == new_visit.client_id).first() if new_visit.client_id else None
    target_name = client.doctor_name if (client and client.doctor_name) else (client.facility_name if client else (center.name if center else "Unknown target"))
    
    action_text = f"Updated visit to {target_name} (Status: {new_visit.status})"
    if new_visit.status == "in_progress":
        action_text = f"Started visit to {target_name}"
    elif new_visit.status == "completed":
        items_sold = sum([item.qty_sold for item in visit.items])
        gifts_given = sum([item.qty_free for item in visit.items])
        action_text = f"Completed visit to {target_name}."
        if items_sold > 0 or gifts_given > 0:
            action_text += f" Sold {items_sold} items, gave {gifts_given} gifts."
            
    create_activity_log(db, current_user.id, current_user.full_name, action_text, "visit", new_visit.id)

    await manager.broadcast("refresh_analytics")'''

text = text.replace('''    await manager.broadcast("refresh_analytics")''', replacement)

with open('routers/visits_router.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")
