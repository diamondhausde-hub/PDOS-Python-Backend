import re

with open('schemas.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('class TargetBase(BaseModel):\n    product_id: str\n    rep_id: str', 'class TargetBase(BaseModel):\n    product_id: str\n    rep_id: Optional[str] = None')
text = text.replace('class SystemSettingUpdate(BaseModel):\n    value: float', 'class SystemSettingUpdate(BaseModel):\n    value: str')

with open('schemas.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")
