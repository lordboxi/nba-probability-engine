# Deploy บน Streamlit Community Cloud

- Repository: `lordboxi/nba-probability-engine` (Public)
- Branch: `main`
- Main file path: `deployment/streamlit_app.py`
- Python version ใน Advanced settings: `3.11`
- App visibility: **Private**

ล็อกอินที่ https://share.streamlit.io/ ผ่าน GitHub และเชื่อมสิทธิ์ repository นี้
จากนั้นสร้างแอปโดยใช้ค่าข้างต้น ตรวจสิทธิ์ Private ก่อนใช้ข้อมูลส่วนตัว
การยอมรับเงื่อนไขและการอนุญาต OAuth ต้องได้รับการยืนยันจากเจ้าของบัญชีตามหน้าเว็บ

`deployment/requirements.txt` มาจาก `uv.lock` พร้อม UI extra และติดตั้งแพ็กเกจใน repo นี้
ไฟล์ dependency อยู่ข้าง entry point เพื่อให้ Community Cloud เลือกก่อน `uv.lock` ที่ราก repo

เมื่อเปลี่ยน dependencies ให้สร้างไฟล์ใหม่จากรากโปรเจกต์:

```powershell
uv export --locked --extra ui --no-dev --no-hashes --no-editable --output-file deployment/requirements.txt
```

## ข้อมูลตั้งต้น

`deployment/seed_snapshots/` มีเฉพาะ normalized NBA snapshots ที่เก็บไว้แล้ว
ประกอบด้วยตาราง 2026–27 Preseason และ roster Boston/Atlanta ณ วันที่ 19 ตุลาคม 2026
และสถิติผู้เล่น Preseason 577 แถวที่อ่านจากตาราง NBA จริงวันที่ 20 ตุลาคม 2026
เก็บ source URL, เวลาที่ดึงจริง และ hash ของ snapshot ต้นทางไว้
ไฟล์ raw responses ต้นทางยังอยู่ในเครื่องเดิม ไม่รวมประวัติ/ราคา House ส่วนตัว
เมื่อ Cloud เริ่มทำงานจะลงทะเบียน snapshots ในฐานข้อมูลของโฮสต์ โดยไม่ย้อนหลังเวลา
ข้อมูลนี้ไม่ใช่ feed สด ต้องอัปเดตหรือนำเข้าใหม่เมื่อมีเกม/รายชื่อเปลี่ยน

## ข้อจำกัดที่ยังมี

เมื่อยังไม่ตั้งค่า Supabase: SQLite, ประวัติ ผลจริงและ snapshots อยู่ในดิสก์ชั่วคราวของ Cloud
ไม่รับประกันว่าจะคงอยู่หลัง reboot/redeploy/hibernate ให้ดาวน์โหลดประวัติ JSON เก็บไว้
เชื่อมฐานข้อมูลถาวรได้ตาม [คู่มือ Supabase](SUPABASE.md) โดยแอปจะแสดง backend ที่ใช้อยู่
ยังไม่มีระบบแยก workspace ต่อผู้ใช้
ดังนั้นแอปรุ่นนี้ตั้งใจให้เจ้าของหรือทีมที่ได้รับเชิญใช้งานใน workspace เดียวกันแบบ Private
NBA endpoints อาจ timeout จากโฮสต์เช่นเดียวกับเครื่องเดิม ใช้ snapshot/นำเข้าไฟล์เป็นทางสำรอง
