# GitHub repository

Repository นี้เป็น Private มีเฉพาะเจ้าของและคนที่ได้รับเชิญเข้าถึงซอร์สโค้ด
ไม่มีการเปิด GitHub Pages หรือ public tunnel
ไฟล์สำหรับ Streamlit Community Cloud อยู่ใน `deployment/` โดยตั้งใจให้ deploy แอปแบบ Private

## เปิดใช้จากเครื่องใหม่

ต้องมี Python 3.11+, Git และ uv:

```powershell
git clone https://github.com/lordboxi/nba-probability-engine.git
Set-Location nba-probability-engine
uv sync --locked --python 3.11 --extra dev --extra ui
uv run nbaprob demo
uv run --extra ui streamlit run src/nbaprob/app.py --server.address 127.0.0.1
```

คำสั่ง demo สร้างข้อมูลจำลองสำหรับลองระบบ ไม่ใช่ข้อมูล NBA จริง
NBA snapshots, SQLite, ราคา House และประวัติคำทำนายใน `data/` ไม่ถูกอัปโหลด
บนเครื่องใหม่ให้นำเข้าหรือดึงข้อมูล NBA ตามคู่มือ `NBA_DATA_AND_COMPARISON.md`
และ `OPENING_SEASON.md` เมื่อต้องการใช้ข้อมูลจริง

`uv.lock` เก็บเวอร์ชัน dependency ที่ตรวจแล้ว และ GitHub Actions รัน lint, format และ tests
ทุกครั้งที่ push หรือเปิด pull request

## อัปเดตโค้ด

```powershell
git add src tests config docs README.md
git commit -m 'Describe the change'
git push
```

เก็บ credentials ไว้นอก repository ห้าม commit `.env` หรือ Streamlit secrets
ไฟล์โค้ดใน `src/nbaprob/data/` และ `src/nbaprob/dist/` เป็นส่วนของโปรแกรมและต้องอยู่ใน Git
ส่วน `/data/` และ `/dist/` ที่รากโปรเจกต์เป็นข้อมูล/ผล build ซึ่งถูก ignore แยกกัน
