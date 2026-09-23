import sys

file_path = r'C:\Users\prot\Documents\PDOS\PDOS-Python-Backend\routers\tasks_router.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("current_user: models.User = Depends(auth.require_password_set)", "current_user: models.User = Depends(get_current_user)")

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("tasks_router fixed")
