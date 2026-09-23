import re

with open('models.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('visit_items = relationship("VisitItem", back_populates="visit")', 'items = relationship("VisitItem", back_populates="visit")')
text = text.replace('visit_photos = relationship("VisitPhoto", back_populates="visit")', 'photos = relationship("VisitPhoto", back_populates="visit")')
text = text.replace('visit = relationship("Visit", back_populates="visit_items")', 'visit = relationship("Visit", back_populates="items")')
text = text.replace('visit = relationship("Visit", back_populates="visit_photos")', 'visit = relationship("Visit", back_populates="photos")')

with open('models.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")
