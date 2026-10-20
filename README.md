# NBA Probability Engine

เอนจิน Python สำหรับทำนายความน่าจะเป็นก่อนเกม NBA พร้อม walk-forward backtest
ใช้เฉพาะข้อมูลที่ทราบ ณ เวลาออกคำทำนาย (as-of)
มี v1 baseline สำหรับ backtest และหน้าจอทดลองสำหรับสถิติ NBA, เลือกผู้เล่นเอง และเทียบ House
ไม่มีระบบรับหรือส่งเดิมพัน

Repository เป็น Public; การ deploy Streamlit Community Cloud ใช้การตั้งสิทธิ์แอปเป็น Private
อ่าน [วิธี clone และเปิดใช้งานจาก GitHub](docs/GITHUB_SETUP.md)
และ [วิธี deploy บน Streamlit Community Cloud](docs/STREAMLIT_CLOUD.md)

โปรเจกต์กำหนดมาตรฐานการวัดผลและเกณฑ์ผ่านเองแล้วใน
[ข้อกำหนดระบบ หัวข้อ 7–8](docs/SYSTEM_SPEC.md) ใช้นโยบายรุ่น 1.0

**ชุด demo เป็นข้อมูลจำลอง ส่วน NBA snapshots มาจากการอ่านหน้าเว็บจริง
โมเดลยังไม่ได้ยืนยันความแม่นยำกับ NBA holdout จริง**

## หน้าจอเลือกผู้เล่นและเทียบ House

```powershell
uv sync --locked --python 3.11 --extra dev --extra ui
uv run --extra ui streamlit run src/nbaprob/app.py --server.address 127.0.0.1
```

เปิด `http://127.0.0.1:8501` เลือกทีม → เลือกตัวจริง/ติ๊กสำรอง → กรอก House probability/odds → เปรียบเทียบ
รองรับช่วงเปิดฤดูกาล: ฐานฤดูกาลก่อนเมื่อมี, ค่าประเมินร่วมกับ House และประวัติคำทำนาย/ผลจริง
อ่าน [วิธีคำนวณช่วงเปิดฤดูกาลและส่วนที่ยังขาด](docs/OPENING_SEASON.md)
มี NBA Traditional snapshot ฤดูกาล 2026–27 Preseason และ roster Boston/Atlanta ที่อ่านจริงเก็บไว้แล้ว
endpoint สถิติทีมโดยตรงยังพบ timeout จากเครื่องนี้; ใช้ cached snapshot/นำเข้าไฟล์ได้
รายชื่ออย่างเดียวบันทึกการเลือก แต่การปรับ probability ตามผู้เล่นต้องมี impact ratings เพิ่ม
เพิ่มตารางสถิติผู้เล่น NBA และตัวแก้นาที/เรตติ้งในหน้าเว็บแล้ว อ่าน [คู่มือสถิติผู้เล่น](docs/PLAYER_STATS.md)
รองรับ [Supabase สำหรับสถิติและประวัติถาวร](docs/SUPABASE.md) ผ่าน server Secrets
อ่าน [คู่มือข้อมูล NBA และการเทียบ House](docs/NBA_DATA_AND_COMPARISON.md) สำหรับรายละเอียด

## เริ่มใช้งานบน PowerShell

ต้องมี [uv](https://docs.astral.sh/uv/) และ Python 3.11 ขึ้นไป
โปรเจกต์นี้เตรียม virtual environment และ `uv.lock` ไว้แล้ว

```powershell
Set-Location 'C:\GPT Project\NBA Project'
uv sync --locked --python 3.11 --extra dev
uv run nbaprob demo
uv run nbaprob validate
uv run nbaprob backtest
```

`demo` สร้างเกมที่จบแล้ว 480 เกมและเกมอนาคต `demo-next` อีกหนึ่งเกม
เก็บ CSV ใน `data/demo/`, ฐานข้อมูลใน `data/nba.sqlite` และ Parquet ใน `data/raw/<hash>/`
คำสั่ง demo/ingest เปลี่ยน working dataset ใน SQLite; archive ของ dataset เดิมยังอยู่

ทำนายเกมตัวอย่างก่อน tipoff พร้อมเส้นต่อรองเจ้าบ้าน −7 และเส้น total 228.5:

```powershell
uv run nbaprob predict demo-next --as-of '2026-01-10T22:00:00Z' --spread -7 --total-line 228.5 --output data/prediction.json
```

ผล JSON มี `p_home_win`, mean/sigma ของ margin และ total, ฟีเจอร์ที่ใช้และค่าสัมประสิทธิ์บริบท
`home_spread.win/push/loss` หมายถึงเจ้าบ้านชนะราคา/คืนทุน/แพ้ราคา
`over_total.win/push/loss` หมายถึงสูง/คืนทุน/ต่ำ
ทุก as-of ต้องมี timezone และอยู่ก่อนเวลา tipoff; เปลี่ยนเวลาเมื่อใช้ config demo ต่างจากค่าเริ่มต้น

## นำเข้าข้อมูลของคุณ

วาง `games.csv`, `team_game_stats.csv`, `schedule.csv` ในโฟลเดอร์เดียวกัน
สองไฟล์หลังไม่บังคับ หากไม่มีจะใช้ prior ที่ระบุใน config

```powershell
uv run nbaprob ingest 'C:\path\to\csv' --source-label 'My licensed dataset' --usage-note 'Describe source, permitted use and timestamp provenance'
uv run nbaprob validate
uv run nbaprob backtest --start '2025-10-01T00:00:00Z' --end '2026-07-01T00:00:00Z'
```

`--as-of` ของ backtest จำกัดเวลาที่ผลต้องเผยแพร่แล้ว ส่วน start/end กรองเวลา tipoff
ข้อมูลก่อน start ยังใช้ warmup ได้ ผลหลัง end ไม่สามารถเปลี่ยน forecast ในอดีตได้

ตัวอย่าง headers:

```csv
game_id,season,date,home_team,away_team,home_pts,away_pts,ot_periods,ts,results_available_at
```

```csv
game_id,team,possessions,ortg,drtg,ts
```

```csv
game_id,rest_days_home,rest_days_away,b2b_home,b2b_away,games_last_7d,travel_km,altitude,ts
```

- `game_id` เป็น string คงเลขศูนย์นำหน้า; `season` เป็นปีเริ่มฤดูกาลจำนวนเต็ม เช่น 2025
- `date` เป็น tipoff timestamp เช่น `2025-10-22T23:30:00Z`
- `games.ts` เป็นเวลาที่ทราบ fixture และต้องก่อน tipoff
- เกมที่จบแล้วต้องมีทั้งสองคะแนน, OT และ `results_available_at` ซึ่งต้องหลัง tipoff
- เกมอนาคตปล่อยสี่ช่องนี้ว่าง; final score ห้ามเสมอ
- `team_game_stats.ts` เป็นเวลาเผยแพร่ boxscore ต้องไม่ก่อน results_available_at
- `possessions` เป็น full-game possessions รวม OT; ORtg/DRtg เป็นแต้มต่อ 100 possessions
- `schedule.ts` เป็นเวลาเผยแพร่ snapshot ต้องก่อน tipoff; หนึ่งแถวต่อเกม
- `games_last_7d` เป็น home−away, `travel_km` เป็น away−home,
  `altitude` เป็นความสูงสนามปัจจุบัน−สนามก่อนหน้าของทีมเยือน (เมตร)
- timestamps ทุกช่องต้องระบุ timezone; ไม่รองรับ revision หลายฉบับใน dataset เดียว

ตรวจเงื่อนไขแหล่งข้อมูลต้นทางก่อนใช้ ไม่มีการดึงเว็บหรือ API อัตโนมัติ
ไฟล์ใน `data/demo/` เป็นตัวอย่าง schema ที่นำไปปรับใช้ได้

## โมเดลและการตรวจสอบ

เรตติ้งทีมเป็น net points ต่อ 100 possessions ใช้ prior จากฤดูกาลก่อนที่ shrink เข้าหาศูนย์
และ blend ตามจำนวนเกม อัปเดตเมื่อผลทราบด้วย gain จาก uncertainty รายทีม
mean margin รวมผลต่างเรตติ้ง × pace/100 กับ rolling ridge regression ของปัจจัยบริบท
mean total รวม offense/defense รายทีมจาก rolling stats
sigma ใช้ prequential residuals ปรับตาม pace และช่วง predicted spread เมื่อข้อมูลพอ

ระบบ replay ตาม publication timestamps: result → stats → forecast ที่เวลาเดียวกัน
ฟีเจอร์และ residual ทุกตัวสร้างจากอดีต ข้อมูลปัจจุบันไม่เข้าการ refit ก่อนผลเผยแพร่
รายงานเทียบ Gaussian v1 กับ HCA-only, expanding home frequency และ 50/50 บนเกมเดียวกัน

ทุก backtest สำเร็จสร้างโฟลเดอร์ใหม่ใน `experiments/` ประกอบด้วย:

- `report.md` — log loss, Brier, accuracy และ distribution scores
- `manifest.json` — config/data/source hash, seed ผ่าน config, package versions และ metadata
- `config.yaml`, `predictions.csv` — config และคำทำนายก่อนแข่งรายเกม
- `calibration.csv`, `residual_qq.csv` — reliability bins และ QQ diagnostics ทั้ง margin/total
- `acceptance.json` — ผลเกณฑ์โมเดลอัตโนมัติ พร้อม paired date-block bootstrap CI

รายงานเพิ่ม ECE, CRPS เทียบ fixed Normal baseline และผลแยกฤดูกาล
ค่าเริ่มต้นของเกณฑ์คือข้อมูลจริงอย่างน้อย 1,000 เกมจาก 2 ฤดูกาล,
log loss ดีขึ้นจาก HCA-only >= 0.005, upper 95% CI ของ Δ log loss < 0,
ECE <= 0.05 พร้อมเกณฑ์ Brier, bias, coverage และ CRPS ใน `acceptance` ของ YAML
ข้อมูลจำลองได้สถานะ `demo_only` เสมอ; `passed` ยืนยันเฉพาะเกณฑ์โมเดลอัตโนมัติ
ก่อนขึ้น milestone ต้องผ่านการตรวจซอฟต์แวร์และ
[บันทึก locked-holdout protocol](docs/VALIDATION_PROTOCOL.md) ตามข้อกำหนดระบบด้วย

ปรับค่าผ่าน `config/default.yaml` หรือไฟล์อื่น:

```powershell
uv run nbaprob --config config/default.yaml backtest
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

ผลสังเคราะห์ไม่ใช้เลือก hyperparameters สำหรับ NBA จริง
อ่าน [สมมติฐานและข้อจำกัด](docs/ASSUMPTIONS.md), [เกณฑ์ตรวจรับ](docs/V1_ACCEPTANCE.md)
และ [ข้อกำหนดระบบ](docs/SYSTEM_SPEC.md) ก่อนใช้ข้อมูลจริง
เก็บ [สเปกต้นฉบับ](docs/SOURCE_SPEC.md) ไว้อ้างอิงที่มาของแนวทาง
