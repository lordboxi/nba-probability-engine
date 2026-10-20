# ฐานข้อมูล Supabase สำหรับ NBA

ใช้โปรเจกต์ NBA แยกจากโปรเจกต์อื่น แอป Streamlit ยังต้องเป็น Private เพราะทุกคนที่เข้าแอปได้
ใช้ workspace เจ้าของร่วมกัน รุ่นนี้ยังไม่มี Supabase Auth หรือ workspace แยกรายผู้ใช้

## ติดตั้ง

1. รัน SQL ใน `supabase/migrations/20261020034333_nba_persistent_data.sql` ใน SQL Editor ของโปรเจกต์ NBA
2. ตั้งค่าใน Streamlit → Manage app → Settings → Secrets โดยเจ้าของบัญชี:

```toml
[nba_storage]
url = "https://YOUR_PROJECT_REF.supabase.co"
secret_key = "YOUR_SERVER_SECRET_KEY"
workspace = "nba-owner"
```

ใช้ secret key (`sb_secret_...`) ที่เก็บบนเซิร์ฟเวอร์เท่านั้น รองรับ legacy service_role JWT ด้วย
ห้ามใส่ key ในโค้ด, GitHub, URL, CSV หรือส่งในแชต ไม่ใช้ publishable/anon key สำหรับฐานเจ้าของนี้
ในเครื่องตั้งค่าข้างต้นผ่าน `.streamlit/secrets.toml` ที่ถูก gitignore หรือ environment variables
`NBA_SUPABASE_URL`, `NBA_SUPABASE_SECRET_KEY`, `NBA_WORKSPACE_ID`

3. เปิดแอปใหม่ ต้องขึ้น “ฐานข้อมูล: Supabase” และบันทึก/เปิดประวัติได้จริง
4. ตรวจว่าตารางเปิด RLS และ anon/authenticated ไม่มีสิทธิ์เข้าถึง จากนั้นทดสอบ reboot แอป

## สิ่งที่เก็บถาวร

- `nba_snapshots`: สถิติทีม รายชื่อและสถิติผู้เล่น พร้อมเวลาและ source metadata
- `nba_forecasts`: คำทำนาย รายชื่อ/นาที ราคา House ที่ใช้ และ hash ของ inputs/config
- `nba_outcomes`: ผลจริงและ revision ของสกอร์

snapshots และ forecasts ใช้ hash ป้องกันข้อมูลซ้ำ ไม่เขียนทับ record เดิม
payload เก็บเป็น JSON text เพื่อคง byte representation สำหรับตรวจ hash
issued_at ของคำทำนายใหม่มาจากนาฬิกาเซิร์ฟเวอร์ฐานข้อมูล
เลือก snapshot ล่าสุดที่สังเกตเห็นไม่เกิน as-of; ดึงประวัติแบบแบ่งหน้า ไม่จำกัดแค่ 1,000 แถวแรก

เมื่อตั้งค่า Supabase แล้ว หากเชื่อมต่อหรือบันทึกไม่สำเร็จ ระบบจะแจ้ง error และไม่แอบเปลี่ยนไปเก็บใน SQLite
หากยังไม่ตั้งค่า จะใช้ SQLite/ไฟล์ตามเดิม และแสดงคำเตือนดิสก์ชั่วคราวบน Cloud
ชุด NBA seed จะถูกนำเข้าเมื่อเปิดแอป ส่วนข้อมูลเก่าใน SQLite **ไม่ถูกย้ายโดยอัตโนมัติ**
ใช้คำสั่ง `uv run nbaprob migrate-supabase` จากเครื่องที่มีข้อมูลเดิมเมื่อตั้งค่า environment พร้อมแล้ว
คำสั่งนี้เพิ่มข้อมูลแบบไม่เขียนทับและเก็บเวลา issue เดิมไว้ จึงไม่เปลี่ยนคำทำนายย้อนหลังให้เป็นก่อนแข่ง

dataset CSV/Parquet สำหรับ backtest และไฟล์ experiment ยังอยู่ในเครื่อง ไม่ย้ายไป Supabase ในรุ่นนี้
ควร export ประวัติ JSON สำรองด้วย แม้ใช้ฐานถาวรแล้ว

อ้างอิง: [Supabase API keys](https://supabase.com/docs/guides/api/api-keys),
[การป้องกันข้อมูล](https://supabase.com/docs/guides/database/secure-data)
