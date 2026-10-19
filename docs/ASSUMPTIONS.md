# สมมติฐานและขอบเขต v1

ใช้ `SYSTEM_SPEC.md` เป็นข้อกำหนดปัจจุบันของระบบ โดยโปรเจกต์กำหนดหัวข้อ 7–8 เองแล้ว
`SOURCE_SPEC.md` เก็บเป็นเอกสารต้นทาง ไม่เป็นเงื่อนไขให้รอเอกสารเพิ่มเติม
เกณฑ์ตรวจรับอยู่ใน SYSTEM_SPEC หัวข้อ 8 และ `acceptance` ใน YAML ประจำการทดลอง

1. **ขอบเขต**: คง v1 baseline Gaussian สำหรับการประเมินเดิม และเพิ่มส่วนทดลอง
   NBA snapshots, manual roster selection, optional player scenarios และ House comparison
   ตาม `NBA_DATA_AND_COMPARISON.md` ยังไม่ทำ GBM, Bayesian, stacking, market blend,
   props หรือ live probability ไม่ติดตั้ง dependency
   สำหรับโมเดลที่ยังไม่ได้ใช้ (`statsmodels`, `scikit-learn`, `lightgbm`, `pymc`)
2. **ข้อมูล**: demo เป็นข้อมูลจำลองทั้งหมด ชื่อทีม `DEMO_*`; ขณะนี้มี NBA snapshots
   ที่อ่านหน้าเว็บจริงแยกเก็บตามเวลาที่ทราบข้อมูล ไม่ใช้แทน historical as-of datasets
   ผลทดสอบกับ demo ใช้ยืนยันการทำงานของโปรแกรมเท่านั้น ไม่ยืนยัน calibration,
   ความได้เปรียบตลาด หรือความแม่นยำ NBA จริง
3. **พารามิเตอร์เริ่มต้น**: ค่าทั้งหมดใน YAML เป็นจุดตั้งต้นที่ยังไม่จูน รวม `season_blend_k`,
   process/observation noise, HCA และ prior shrink ควรเลือกด้วย inner walk-forward
   บนช่วงอดีตและล็อกค่าก่อนประเมิน outer holdout ห้ามเลือกจากผล test แล้วอ้างเป็น OOS
4. **เวลา**: `date` หมายถึงเวลา tipoff ที่มี timezone ไม่ใช่แค่วันที่; `ts` ใน games
   คือเวลาที่ fixture นี้ทราบแล้ว และเพิ่ม `results_available_at` เพื่อแยกเวลาทราบผล
   ห้ามอนุมานว่า final score ทราบตั้งแต่วันแข่ง หากแหล่งข้อมูลไม่มีเวลาเผยแพร่
   ผู้เตรียมข้อมูลต้องกำหนดเวลาแบบอนุรักษนิยมและบันทึกวิธีใน usage note
5. **ข้อมูลแก้ย้อนหลัง**: รองรับ snapshot เดียวต่อ game/team ในแต่ละ dataset
   ไม่รองรับประวัติ revision ห้ามใช้ score/stat ที่แก้ย้อนหลังแล้วอ้าง timestamp ของฉบับเก่า
   การเปลี่ยน dataset จะได้ hash และ Parquet archive ใหม่ ราคาหรือ injuries ยังไม่เป็นอินพุต
6. **ตารางแข่ง**: ถ้าไม่มี schedule snapshot ที่ทราบในเวลา as-of จะคำนวณวันพักและ
   congestion จาก fixtures ที่ทราบแล้ว; rest นับวันปฏิทินใน `calendar_timezone`
   (ค่าเริ่มต้น America/New_York) ลบหนึ่งวัน และ cap ตาม YAML
   ตารางแข่งก่อนหน้าอาจยังไม่ทราบผล จึงใช้เป็นบริบทตารางแข่งได้ แต่ไม่ใช้เป็นผลเทรน
7. **คอลัมน์กำกวมใน schedule**: `games_last_7d` คือจำนวนเกม 7 วันที่ผ่านมาของเจ้าบ้าน
   ลบทีมเยือน, `travel_km` คือระยะเดินทางทีมเยือนลบเจ้าบ้าน, `altitude` คือความสูงสนาม
   ปัจจุบันลบความสูงสนามล่าสุดของทีมเยือน (เมตร) ใช้เป็น proxy สำหรับ altitude exposure
   ข้อมูลเหล่านี้ต้องเตรียมภายนอกและมี `ts` หากไม่มี snapshot ให้ travel/altitude เป็นศูนย์
   พร้อมแสดง `schedule_override=false` ไม่อ้างว่าได้ประมาณผลการเดินทางจากข้อมูลที่ไม่มี
8. **Pace/total**: ใช้ rolling mean ของ possessions ต่อ 48 นาที โดยปรับ OT ด้วย
   `48 / (48 + 5 * ot_periods)` และ shrink เข้าหาค่าลีกใน YAML
   ORtg/DRtg เป็น points per 100 possessions; ค่าเฉลี่ย offense ของทีมหนึ่งกับ defense
   ของอีกทีมใช้ประมาณแต้มต่อ 100 แล้วรวมสองทีมเป็น `total_rate`
   rolling stats ยกยอดข้ามฤดูกาลตาม window; เรตติ้งเริ่มฤดูกาลใหม่จาก effective rating
   ฤดูกาลก่อน × prior_shrink และ freeze prior เมื่อพบทีมครั้งแรกในฤดูกาลใหม่
9. **Kalman update**: เก็บ variance รายทีม ใช้ gain ของแต่ละทีม
   `(variance_i + Q) / (variance_home + variance_away + 2Q + observation_noise)`
   และ update ด้วย residual ต่อ 100 possessions จาก forecast ที่ออกจริงก่อนเกม
   gain ลดลงตามข้อมูลสะสมเมื่อ Q=0; Q>0 ทำให้ gain มี floor เพื่อให้ตามฟอร์มใหม่ได้
   นี่เป็น adaptive approximation ไม่ใช่ full covariance Kalman filter
10. **บริบท/uncertainty**: ridge regression แบบ rolling ของ margin ลบ rating component
    เรียน HCA, rest, b2b, congestion, travel, altitude จากผลที่ทราบแล้วเท่านั้น
    ใช้ prior HCA จนกว่าจะครบ minimum games ค่า sigma เรียนจาก prequential residuals
    ที่ปรับด้วย pace ใช้ spread bucket เมื่อมีตัวอย่างพอ มิฉะนั้นใช้ residual รวม
11. **Gaussian และราคา**: ทำตามสูตร 5.5 สำหรับเส้นครึ่งแต้มและเส้นเต็มแต้ม
    ยกเว้น spread=0 ให้ push=0 และ cover=p_home_win เพราะ NBA จบเสมอไม่ได้
    เส้นอื่นเช่น 7.25 ใช้ threshold ของคะแนนจำนวนเต็ม (เทียบเท่า 7.5)
    ไม่ใช่ Asian quarter-line แบบแบ่งเดิมพันครึ่งหนึ่ง
    Gaussian เป็น marginal approximation ไม่ใช่ joint score simulator หรือ normalized
    discrete no-tie distribution; การแจกแจง margin/total ยังมี support เป็นจำนวนจริง
12. **การวัดผล**: prequential walk-forward ออก forecast ก่อน tipoff ตาม lead ใน YAML
    อัปเดตเรตติ้งและ regression เมื่อผลเผยแพร่แล้วเท่านั้น เหตุการณ์ timestamp เดียวกัน
    ประมวลผล result → stats → forecast จึงใช้ข้อมูลที่ `ts <= as_of` ได้
    warmup นับเฉพาะผลที่ทราบ; เทียบทุกโมเดลบนเกมชุดเดียวกัน
    baseline เพิ่มเติมคือ HCA-only, expanding home-win frequency (Beta(1,1) smoothing)
    และ 50/50 ไม่มี random split; รายงาน paired date-block bootstrap CI ตามนโยบายของเรา
    ช่วง CI ไม่แก้ selection bias จากการจูนซ้ำ ต้องยืนยันด้วย locked holdout แยกต่างหาก
13. **Diagnostics**: ให้ log loss, Brier, accuracy (ประกอบเท่านั้น), continuous Normal CRPS,
    RMSE, bias, coverage, reliability bins และ QQ quantiles ทั้ง margin/total
    ยังไม่เปลี่ยนเป็น Student-t/empirical โดยอัตโนมัติ ต้องพิสูจน์ด้วย out-of-sample CRPS ก่อน
    ECE, distribution CRPS baselines, season scores และ acceptance.json
    ใช้มาตรฐานถาวรใน SYSTEM_SPEC หัวข้อ 7–8 รุ่นนโยบายที่ระบุใน config
14. **แหล่งข้อมูล/สิทธิ์**: v1 CSV ทำงาน offline ส่วนใหม่มี NBA Stats/หน้าเว็บทีม adapter
    ตรวจ NBA Terms of Use แล้วและบันทึกข้อจำกัดใน NBA_DATA_AND_COMPARISON.md
    source snapshot ไม่ได้แสดงว่ามีสิทธิ์ใช้เกินเงื่อนไข NBA และไม่ใช่ licensed betting feed
    CSV ภายนอกยังต้องมี source/usage note; ห้ามวาง API key ใน config/โค้ด
15. **dependencies**: เพิ่ม PyYAML เพื่อทำ YAML config และ pyarrow เพื่ออ่าน/เขียน Parquet
    SQLite ใช้ standard library ล็อก dependency ที่ติดตั้งจริงด้วย `uv.lock`
    เพิ่ม Streamlit เป็น optional UI dependency เพื่อเลือกผู้เล่นและเทียบ House บนเครื่อง
    paths ใน config ตีความ relative ต่อ working directory; เรียกคำสั่งจาก root โปรเจกต์
