# ช่วงเปิดฤดูกาล: ใช้ข้อมูลที่มี และแสดงสิ่งที่ยังขาด

หน้าวิเคราะห์ใช้ Regular Season เป็นค่าเริ่มต้น แม้ยังไม่มีสถิติฤดูกาลใหม่ก็วิเคราะห์ได้
หากมีตารางฤดูกาลก่อนหรือรายชื่อทีมจากตาราง Preseason ใน snapshot แล้ว
เลือก **ใช้สถิติ Preseason ช่วยตั้งต้น Regular Season** ได้เมื่อมี snapshot ปีเดียวกัน
ระบบเก็บประเภทและ provenance แยกกัน เกม Preseason ไม่ถูกนับเป็นเกม Regular Season
ต้องเลือกเวลาแข่งจริงเอง ปัจจุบันยังไม่ตรวจเทียบ NBA schedule

## ฐานโมเดลทีม

1. อ่าน Regular Season ของฤดูกาลก่อนหน้าเท่านั้น ด้วย team ID และเวลาที่ระบบทราบข้อมูล
2. ประมาณ pace/offense/defense จาก Traditional เช่นเดิม
3. ลดค่าฤดูกาลก่อนเข้าหาค่าลีก เผื่อจำนวนเกมและการเปลี่ยนทีม:
   `retention = prior_shrink * previous_GP/(previous_GP + snapshot_shrink_k)`
4. สำหรับเกม Regular Season ผสม Preseason ปีเดียวกันเข้าฐานก่อน ด้วย
   `pre_weight = (Preseason_GP * preseason_game_weight)/(Preseason_GP * preseason_game_weight + snapshot_shrink_k)`
   จากนั้นผสมข้อมูลประเภทการแข่งขันที่เลือกในฤดูกาลใหม่:
   `new_weight = effective_GP/(effective_GP + snapshot_shrink_k)`
   โดย Regular Season/Playoffs ใช้ GP ตามประเภทนั้น และ Preseason ใช้ `GP * preseason_game_weight`
5. เมื่อไม่มีฐานก่อนหน้า ใช้ค่าลีกใน config; ไม่สร้างเกม/สถิติปลอมแทนข้อมูลที่หาย

ค่าเริ่มต้น retention สูงสุด 0.65, shrink_k=20, น้ำหนักต่อเกม Preseason=0.1
ค่าทั้งหมดเป็นสมมติฐานเริ่มต้นที่ยังไม่จูน ไม่ใช่ความมั่นใจทางสถิติ
เมื่อมี snapshot ใหม่ น้ำหนักเปลี่ยนตามจำนวนเกมที่นำเข้า ไม่ได้ดึงหรือฝึกโมเดลเองตามเวลา
ยังไม่ได้วัด roster continuity จริง การเปลี่ยนผู้เล่นจะไม่ถูกปรับอัตโนมัติ

นำเข้าฐานฤดูกาลก่อนได้ในแท็บ **ข้อมูล NBA → ฐานข้อมูลฤดูกาลก่อน**
รองรับ JSON/HTML ที่มี filters ตรง หรือขอ endpoint โดยตรงเมื่อเครือข่ายอนุญาต
snapshot ยังคงใช้เวลานำเข้าจริง ห้ามย้อนหลังเวลาไปก่อนที่ระบบทราบข้อมูล

## House ช่วยประเมินช่วงข้อมูลน้อย

เลือกตลาด เส้น และกรอกทั้งสองฝั่งของราคา พร้อมเวลาและชื่อ House
ระบบแปลงราคาเป็น implied probability แล้วตัดค่าน้ำแบบ proportional
กรณีประกาศว่าเป็น fair probability อยู่แล้ว จะตรวจว่ารวมกันได้หนึ่ง
ค่า fair probability หลังตัดค่าน้ำยังเป็นเพียงประมาณการจากตลาด

ตัวเลือก **ใช้ House ช่วยประเมินช่วงข้อมูลน้อย** แสดงผลแยกจากโมเดลอิสระ:

```
team_evidence = effective_GP + preseason_effective_GP + prior_equivalent_games * previous_GP/(previous_GP + shrink_k)
evidence = min(home_evidence, away_evidence)
model_weight = evidence/(evidence + model_weight_k)
assisted_p = model_weight * independent_p + (1-model_weight) * house_fair_p
```

ค่าเริ่มต้น prior_equivalent_games=5 และ model_weight_k=20
หากไม่มีทั้งข้อมูลก่อนหน้าและเกมใหม่เลย assisted_p เท่ากับ house_fair_p
หากใช้ Preseason เป็นฐานของเกม Regular Season จะมี evidence เพิ่มเพียง GP * 0.1 ตามค่าเริ่มต้น
ตัวอย่าง Preseason 5 เกมให้ equivalent evidence 0.5 เกม (ไม่ใช่ 5 เกม Regular Season)
ถ้าไม่มีข้อมูลฤดูกาลก่อนและยังไม่แข่ง Regular Season น้ำหนักโมเดลเท่ากับ 0.5/20.5 ≈ 2.44%
นี่เป็นสมมติฐานเริ่มต้น ไม่ใช่น้ำหนักที่พิสูจน์ว่าเหมาะที่สุด
มีข้อมูลเพิ่มแล้วน้ำหนักโมเดลจะเพิ่มตามสูตร ยังไม่ได้เรียนรู้น้ำหนักที่เหมาะที่สุด
แสดงน้ำหนักจริงและ probability ทั้งสามค่าในตารางเดียวกันให้ตรวจได้

- Moneyline: บอกทีมที่ House ให้โอกาสชนะมากกว่า; เท่ากันแสดงว่าเท่ากัน
- ค่าน้ำต้องมาจากเกม Regular Season ที่กำลังทำนาย ทั้งคู่แข่ง เวลาแข่ง ตลาด และเส้นต้องตรงกัน
- Spread: ทีมต่อดูจากเครื่องหมายเส้นเจ้าบ้าน ไม่ใช้โอกาส cover มาอ้างว่าเป็นโอกาสชนะเกม
- Total: แสดงโอกาสสูง/ต่ำ ไม่มีทีมต่อ
- Spread/Total แสดง probability เฉพาะกรณีไม่ push; ไม่สร้าง market push probability ขึ้นเอง
- ค่า assisted ใช้ House ที่กำลังเทียบเป็น input จึงไม่อ้าง independent edge/EV หรือเลือกฝั่งจากค่านั้น
- ตาราง EV เดิมเป็นของโมเดลอิสระเท่านั้น โมเดล snapshot ที่ยังไม่ผ่าน holdout จริงจะไม่เสนอ candidate
- ราคาเก่าจะแสดงให้ refresh แม้ยังอ่านค่าอ้างอิงย้อนหลังได้

หากยังไม่เลือกรายชื่อครบ สามารถเลือก **วิเคราะห์ระดับทีมโดยยังไม่ระบุตัวจริง** อย่างชัดเจน
ผลจะแจ้งว่าขาด selected_lineup การเลือกชื่อคน/ตำแหน่งอย่างเดียวยังไม่สร้าง impact rating

## เก็บข้อมูลเพื่อพัฒนาต่อ

การกดคำนวณบันทึกผล JSON, ราคา, รายชื่อ, snapshot IDs, config hash, เวลา as-of และเวลา issue จริง
หากเป็นราคาลองใช้ ให้ติ๊ก **ราคาตัวอย่างสำหรับทดสอบ (ไม่รวมในสถิติ)** เพื่อไม่ปะปนกับข้อมูลจริง
ใน `prediction_journal.sqlite` ข้างฐานข้อมูลเกม กดซ้ำด้วยผลเหมือนเดิมจะไม่เพิ่มสำเนา
คำทำนายเดิมไม่ถูกแก้ไข ผลจริงบันทึกแยกและการแก้สกอร์สร้าง revision ใหม่
ผู้ใช้กรอกเฉพาะผลสุดท้ายหลังแข่ง (รวม OT ไม่รับสกอร์เสมอ)

รายงานใช้คำทำนายล่าสุดที่บันทึกจริงก่อน tipoff เพียงหนึ่งคำทำนายต่อเกม
ไม่รวมข้อมูลจำลอง การ archive หลังแข่ง และ as-of ที่อยู่หลังเวลา issue
เทียบ Brier, log loss และ accuracy ของโมเดล/House/assisted บนเกม Moneyline ชุดเดียวกัน
รายงานเชิงพรรณนาเหล่านี้ยังไม่ใช่ acceptance gate หรือหลักฐานกำไร/CLV
ยังไม่มี auto-retraining, แหล่งผลจริงอัตโนมัติ หรือการประเมิน spread/total ใน journal

```powershell
uv run nbaprob matchup --season 2026-27 --season-type 'Regular Season' --home-team-id 1610612738 --away-team-id 1610612737 --tipoff '2026-10-20T00:00:00Z' --as-of '2026-10-19T12:00:00Z' --house examples/house_odds.json --use-market-prior --record
```

House JSON ต้องเป็นของคู่ที่เลือก หากมี game_id อยู่แล้วต้องตรงกับคู่และเวลาแข่ง
CLI ใช้ Preseason prior เมื่อเลือก Regular Season โดยอัตโนมัติเมื่อมี snapshot; ปิดด้วย `--no-preseason-prior`
ใช้เวลากับราคาจริงของผู้ใช้ ตัวอย่างเวลาในคำสั่งไม่ใช่ schedule ที่ยืนยันแล้ว

## ช่องว่างที่ยังต้องเติม

- สถิติ Regular Season ฤดูกาลก่อน/ปัจจุบันที่ยังไม่มี: หน้าจอระบุแยกตามทีม
- Impact ratings, นาทีลงสนาม และ roster continuity ที่มีหลักฐานรองรับ
- ตารางแข่ง วันพัก และการเดินทางจริง
- ประวัติราคาปิดและราคาหลาย House; ตอนนี้กรอกราคาเดียวต่อคำทำนาย
- ผลจริงและจำนวนเกมพอสำหรับ calibration / holdout / การจูนน้ำหนัก
- การตรวจความเหมาะสมของ prior และ sigma ต่อฤดูกาล; ค่าความผันผวนยังเป็น defaults

การมีข้อมูลเพิ่มช่วยให้ทดสอบและปรับปรุงได้ แต่ยังไม่รับรองว่าโมเดลจะดีขึ้นหรือชนะตลาด
