# สถานะการตรวจรับ v1

เกณฑ์หลักกำหนดโดยโปรเจกต์ใน `SYSTEM_SPEC.md` หัวข้อ 8 (policy 1.0)
ไฟล์นี้สรุปสถานะงาน; ค่าเกณฑ์อัตโนมัติอ่านจาก YAML ประจำ run และแสดงใน acceptance.json

## Gate A — ซอฟต์แวร์

- [x] ติดตั้งได้ด้วย Python 3.11+ และ config YAML มี validation
- [x] นำเข้า CSV ผ่าน adapter และตรวจ schema, keys, timestamps, final scores
- [x] เก็บ SQLite พร้อม versioned normalized Parquet และ metadata แหล่งข้อมูล
- [x] `build_features(game_id, as_of, tables, config)` กันผล/สถิติ/schedule ที่เผยแพร่ในอนาคต
- [x] ย้อนเล่นเหตุการณ์ตามเวลาจริง รวมกรณีผลเผยแพร่ช้าและหลายเกมซ้อนกัน
- [x] เรตติ้งรายฤดูกาล มี shrinkage prior และ adaptive Kalman gain
- [x] rolling regression เรียนบริบทจากอดีต และ rolling residuals ประมาณ sigma
- [x] แสดง p_home_win และ marginal Normal ของ margin/total
- [x] คำนวณ cover/push/loss และ over/push/under ตามคอนเวนชันในสเปก
- [x] walk-forward อย่างเดียว พร้อม comparator baselines และรายงาน log loss
- [x] เก็บทุก backtest ที่สำเร็จเป็น experiment ใหม่: config/data/source hash, versions,
      predictions, scores, calibration, QQ quantiles และรายงาน
- [x] seed คงที่ให้ dataset และ metrics ซ้ำได้ (run id และเวลารันเปลี่ยนตามจริง)
- [x] ทดสอบ CLI ตั้งแต่สร้างข้อมูล → นำเข้า → validate → backtest → predict
- [x] รายงาน ECE, CRPS baseline, season stability และ paired date-block bootstrap
- [x] เกณฑ์โมเดลแบบอัตโนมัติและสถานะ demo_only/insufficient_data/failed/passed

## Gate B — โมเดลจากข้อมูลจริง

- [ ] ข้อมูล NBA จริงที่มีประวัติเวลาเผยแพร่และสิทธิ์ใช้งานชัดเจน
- [ ] ผ่านเกณฑ์ขนาดตัวอย่าง log loss calibration และ distribution ทั้งหมดใน acceptance.json

## Gate C — กระบวนการยืนยัน

- [ ] จูน hyperparameters ด้วย nested time-based validation และทดสอบ holdout ที่ล็อกไว้
- [ ] ตรวจ reliability/QQ และเปรียบเทียบ CRPS ก่อนพิจารณาเปลี่ยน family ของการแจกแจง
- [ ] กรอก VALIDATION_PROTOCOL ของ candidate และเก็บหลักฐานก่อน/หลังเปิดผล holdout

สถานะปัจจุบัน: ตรวจซอฟต์แวร์ด้วยข้อมูลจำลองแล้ว; Gate B/C ยังรอหลักฐานจากข้อมูลจริง
ไม่มีรายการที่ต้องรอเอกสารหัวข้อ 7–8 จากภายนอก

คำสั่งตรวจ: `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`
