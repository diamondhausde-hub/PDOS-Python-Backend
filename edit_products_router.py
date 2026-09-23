with open('routers/products_router.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('''def update_product(
    product_id: str,
    payload: schemas.ProductCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_role(["admin", "general_manager"]))
):''', '''def update_product(
    product_id: str,
    payload: schemas.ProductUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.require_role(["admin", "general_manager"]))
):''')

with open('routers/products_router.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")
