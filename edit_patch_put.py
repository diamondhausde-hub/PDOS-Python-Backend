import re

with open('routers/visits_router.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('@router.patch("/visits/{visit_id}/note", response_model=schemas.VisitResponse)', '@router.put("/visits/{visit_id}/note", response_model=schemas.VisitResponse)')

with open('routers/visits_router.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")
