with open('schemas.py', 'r', encoding='utf-8') as f:
    text = f.read()

product_update = '''class ProductUpdate(BaseModel):
    name: Optional[str] = None
    price: Optional[float] = None
    category: Optional[str] = None
    description: Optional[str] = None
    barcode: Optional[str] = None
    stock_qty: Optional[int] = None
    min_threshold: Optional[int] = None
    image_url: Optional[str] = None
'''

if 'class ProductUpdate' not in text:
    text = text.replace('class ProductResponse(ProductBase):', product_update + '\nclass ProductResponse(ProductBase):')


client_update = '''class ClientUpdate(BaseModel):
    facility_name: Optional[str] = None
    facility_type: Optional[str] = None
    doctor_name: Optional[str] = None
    specialty: Optional[str] = None
    birth_date: Optional[datetime] = None
    class_tier: Optional[str] = None
    relationship_type: Optional[str] = None
    description: Optional[str] = None
    phone_number: Optional[str] = None
    region: Optional[str] = None
    area: Optional[str] = None
    street: Optional[str] = None
    nearby_landmark: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    photo_url: Optional[str] = None
    gender: Optional[str] = None
    rating: Optional[int] = None
    treatment_quality: Optional[str] = None
    client_type: Optional[str] = None
    status: Optional[str] = None
    scientific_interests: Optional[str] = None
    product_interests: Optional[str] = None
    pharmacy_type: Optional[str] = None
    institution_type: Optional[str] = None
    key_contact_name: Optional[str] = None
    key_contact_position: Optional[str] = None
    key_contact_phone: Optional[str] = None
    departments: Optional[str] = None
'''

if 'class ClientUpdate' not in text:
    text = text.replace('class ClientResponse(ClientCreate):', client_update + '\nclass ClientResponse(ClientCreate):')

with open('schemas.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Done")
