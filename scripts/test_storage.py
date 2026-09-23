"""Integration test for storage system"""
import sys, os, io, uuid, time, hashlib, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5432/pdos"
os.environ["CORS_ORIGINS"] = "*"

import httpx

BASE = "http://localhost:9876"

proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0",
     "--port", "9876", "--log-level", "warning"],
    cwd=os.path.join(os.path.dirname(__file__), ".."),
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
time.sleep(6)

try:
    cli = httpx.Client(base_url=BASE, timeout=15)

    # 1. Login
    r = cli.post("/auth/login", data={"username": "rep@pdos.com", "password": "password123"})
    assert r.status_code == 200, f"Login: {r.text}"
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    print("1. Login OK")

    # 2. Get IDs
    uid = cli.get("/users/me", headers=h).json()["id"]
    cid = cli.get("/centers", headers=h).json()[0]["id"]
    print(f"2. User={uid[:8]} Center={cid[:8]} OK")

    # 3. Check-in
    vid = str(uuid.uuid4())
    r = cli.post("/visits/check-in", headers=h, json={
        "visit_id": vid, "center_id": cid, "latitude": 24.71, "longitude": 46.67})
    assert r.status_code == 200, f"Checkin: {r.text}"
    print("3. Visit created OK")

    # 4. Upload photo
    png = bytes([0x89,0x50,0x47,0x4E,0x0D,0x0A,0x1A,0x0A,0x00,0x00,0x00,0x0D,
        0x49,0x48,0x44,0x52,0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x01,0x08,0x02,
        0x00,0x00,0x00,0x90,0x77,0x53,0xDE,0x00,0x00,0x00,0x0C,0x49,0x44,0x41,
        0x54,0x08,0xD7,0x63,0x60,0x60,0x00,0x00,0x00,0x02,0x00,0x01,0xE2,0x21,
        0xBC,0x33,0x00,0x00,0x00,0x00,0x49,0x45,0x4E,0x44,0xAE,0x42,0x60,0x82])
    sha = hashlib.sha256(png).hexdigest()
    files = {"file": ("p.png", io.BytesIO(png), "image/png")}

    r = cli.post(f"/visits/{vid}/photos", files=files, headers=h)
    assert r.status_code == 200, f"Photo upload: {r.text}"
    pu = r.json()["photo_url"]
    pf = r.json().get("photo_file_id")
    print(f"4. Photo URL={pu} FK={pf}")

    r = cli.get(pu, headers=h)
    assert r.status_code == 200 and len(r.content) == len(png), f"Fetch photo: {r.status_code}"
    print(f"5. Fetch photo HTTP 200 {len(r.content)}b")

    # 6. Signature
    r = cli.post(f"/visits/{vid}/signature", files={"file": ("s.png", io.BytesIO(png), "image/png")}, headers=h)
    assert r.status_code == 200, f"Sig upload: {r.text}"
    su = r.json()["signature_url"]
    sf = r.json().get("signature_file_id")
    print(f"6. Sig URL={su} FK={sf}")

    r = cli.get(su, headers=h)
    assert r.status_code == 200
    print(f"7. Fetch sig HTTP 200 {len(r.content)}b")

    # 8. Receipt
    eid = str(uuid.uuid4())
    r = cli.post("/expenses", headers=h, json={"id": eid, "visit_id": vid, "category": "transport", "amount": 50.0})
    assert r.status_code == 200
    r = cli.post(f"/expenses/{eid}/receipt", files={"file": ("r.png", io.BytesIO(png), "image/png")}, headers=h)
    assert r.status_code == 200, f"Receipt: {r.text}"
    ru = r.json()["receipt_image_url"]
    rf = r.json().get("receipt_file_id")
    print(f"8. Receipt URL={ru} FK={rf}")

    r = cli.get(ru, headers=h)
    assert r.status_code == 200
    print(f"9. Fetch receipt HTTP 200 {len(r.content)}b")

    # 10. DB check
    from database import SessionLocal
    db = SessionLocal()
    cnt = db.execute("SELECT COUNT(*) FROM stored_files").scalar()
    print(f"10. stored_files count: {cnt}")

    dedup = db.execute("SELECT COUNT(*) FROM stored_files WHERE sha256=:s", {"s": sha}).scalar()
    print(f"11. Dedup check (sha256={sha[:12]}): {dedup} records match")

    db.close()
    print("\n=== ALL TESTS PASSED ===")
finally:
    proc.terminate(); proc.wait(5)
