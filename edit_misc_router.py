with open('routers/misc_router.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('''def update_client(
    client_id: str,
    payload: schemas.ClientCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set)
):''', '''def update_client(
    client_id: str,
    payload: schemas.ClientUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_password_set)
):''')

with open('routers/misc_router.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")
