import re

with open('routers/visits_router.py', 'r', encoding='utf-8') as f:
    text = f.read()

replacement = '''          existing.completion_time = visit.completion_time
          existing.arrival_time = visit.arrival_time
          existing.retroactive_reason = visit.retroactive_reason
          existing.save_location_lat = visit.save_location_lat
          existing.save_location_lng = visit.save_location_lng
          existing.visit_type = visit.visit_type or "center"'''

text = text.replace('''          existing.completion_time = visit.completion_time
          existing.visit_type = visit.visit_type or "center"''', replacement)

replacement_new = '''            id=visit.id, reference_code=ref_code, rep_id=current_user.id, center_id=center_id,
            client_id=visit.client_id, appointment_id=visit.appointment_id,
            visit_date=visit.visit_date, status=status_to_save,
            notes=visit.notes, latitude=visit.latitude, longitude=visit.longitude,
            visit_type=visit.visit_type or "center",
            visit_reason=visit.visit_reason,
            interested_product_ids=interested_json,
            arrival_time=visit.arrival_time,
            completion_time=visit.completion_time,
            retroactive_reason=visit.retroactive_reason,
            save_location_lat=visit.save_location_lat,
            save_location_lng=visit.save_location_lng,
        )'''

text = text.replace('''            id=visit.id, reference_code=ref_code, rep_id=current_user.id, center_id=center_id,
            client_id=visit.client_id, appointment_id=visit.appointment_id,
            visit_date=visit.visit_date, status=status_to_save,
            notes=visit.notes, latitude=visit.latitude, longitude=visit.longitude,
            visit_type=visit.visit_type or "center",
            visit_reason=visit.visit_reason,
            interested_product_ids=interested_json,
        )''', replacement_new)


special_req_code = '''    db.commit()
    db.refresh(new_visit)
    for req in visit.special_requests:
        if not db.query(models.SpecialRequest).filter(models.SpecialRequest.id == req.id).first():
            db.add(models.SpecialRequest(id=req.id, visit_id=new_visit.id, request_type=req.request_type, description=req.description))
    db.commit()
    db.refresh(new_visit)
    enrich_visits([new_visit], db)'''

text = text.replace('''    db.commit()
    db.refresh(new_visit)
    enrich_visits([new_visit], db)''', special_req_code)

with open('routers/visits_router.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")
