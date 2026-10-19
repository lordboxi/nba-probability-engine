# NBA Probability Engine — ข้อกำหนดระบบของเรา

เจ้าของข้อกำหนด: โปรเจกต์ NBA Probability Engine · รุ่นนโยบาย 1.0 · 19 ตุลาคม 2026

เอกสารนี้เป็นมาตรฐานปัจจุบันของโปรเจกต์ พัฒนาโดยใช้แนวทางข้อมูล/เรตติ้ง/โมเดล v1
ใน `SOURCE_SPEC.md` หัวข้อ 1–5 เป็นฐาน และกำหนดหัวข้อ 6–8 ต่อไปนี้เอง
เมื่อข้อกำหนดการวัดผลหรือการตรวจรับขัดกัน ให้ใช้เอกสารนี้และ YAML ที่บันทึกประจำ run
`SOURCE_SPEC.md` เก็บเป็นหลักฐานต้นทาง; ไม่ต้องรอเอกสารส่วนที่หายไปจากผู้จัดทำเดิม

เป้าหมายคือความน่าจะเป็นที่วัดคุณภาพได้และตรวจย้อนกลับได้ การเป็นระบบของเราเอง
ครอบคลุมโค้ด โมเดล schema กระบวนการประเมินและเกณฑ์ตรวจรับ
ข้อมูล NBA ภายนอกยังต้องมีสิทธิ์ใช้งานตามแหล่งของข้อมูล

## 6. วงจรพัฒนาระบบ

1. ตรวจ schema/สิทธิ์/เวลาเผยแพร่ข้อมูล นำเข้าเป็น immutable dataset version
2. กำหนดสมมติฐานและ config ก่อนทดลอง ใช้ `seed` คงที่
3. ทำ inner walk-forward บนช่วงพัฒนาเพื่อจูน ห้าม random split
4. ล็อกวิธีเลือกโมเดล config เกณฑ์ตรวจรับ และขอบเขต final holdout ก่อนเปิดดูผล
5. ประเมินแบบ walk-forward ตามหัวข้อ 7 และบันทึกทุกการทดลอง
6. ตัดสินตามหัวข้อ 8 โมเดลหรือฟีเจอร์ใหม่ต้องพิสูจน์ประโยชน์ก่อนเพิ่ม complexity

คำสั่ง `backtest` เป็นเครื่องมือประเมิน walk-forward ไม่ได้ทำ hyperparameter search
หรือพิสูจน์ว่า final holdout ถูกล็อกโดยอัตโนมัติ ใช้ `VALIDATION_PROTOCOL.md`
บันทึกหลักฐานกระบวนการควบคู่กับ experiment artifacts

## 7. การวัดผลและมาตรฐานรายงาน

### 7.1 เวลาทำนายและชุดทดสอบ

- ประเมินก่อน tipoff ตาม `evaluation.prediction_lead_minutes`; ทุก feature ใช้ `ts <= as_of`
- ใช้ publication time ของผล/boxscore จริง ถ้าผลยังไม่เผยแพร่ห้ามอัปเดตโมเดล
- warmup ใช้จำนวนผลที่ทราบแล้วตาม `evaluation.min_train_games`
- start รวมขอบเขตและ end ไม่รวมขอบเขต โดยกรองเวลา tipoff; history ก่อน start ใช้เทรนได้
- final holdout อนุญาต online updates ของ state และ rolling fits ตาม algorithm ที่ล็อกไว้
  เมื่อผลเกมก่อนหน้าเผยแพร่แล้ว ห้ามเปลี่ยน hyperparameters หลังเห็นผล holdout
- รายงานจำนวนเกม ช่วงเวลา ฤดูกาล เวลาทำนาย dataset hash และข้อมูลที่ถูกตัดออกโดยกฎ warmup
  ต้องใช้เกมชุดเดียวกันในการเทียบทุก baseline; ห้ามเลือกเฉพาะเกมที่โมเดลดูดี

### 7.2 คะแนนหลักและ baseline

คะแนนตัดสินหลักคือ binary log loss:

`LL = mean(-y*log(p) - (1-y)*log(1-p))`

clip probability เพื่อเสถียรภาพตัวเลขด้วยค่าจาก YAML และเก็บ p เดิมใน predictions
ค่าต่ำดีกว่า; `delta = LL_model - LL_reference` ติดลบหมายถึงโมเดลดีกว่า
Accuracy ใช้ประกอบเท่านั้น ห้ามใช้เป็นเกณฑ์เลือกโมเดล

baseline ที่ต้องรายงานทุกครั้ง:

| ชื่อ | วิธี |
| --- | --- |
| baseline_gaussian_v1 | โมเดลเรตติ้ง + บริบท + Gaussian ปัจจุบัน |
| hca_only | `Phi(initial_hca / margin_sigma)` คงที่ เป็น reference หลัก |
| expanding_home_frequency | ความถี่เจ้าบ้านชนะจากผลที่ทราบแล้ว + Beta prior จาก YAML |
| coin_flip | p = 0.5 ทุกเกม |

เมื่อเพิ่มโมเดลรุ่นถัดไป ต้องคง baseline Gaussian v1 ไว้เทียบด้วย
การชนะ baseline ง่ายไม่ได้หมายความว่าชนะตลาดหรือรับรอง calibration ทุกกลุ่ม

### 7.3 Calibration และการแจกแจง

- รายงาน Brier score, reliability bins ตาม `calibration_bins` และ
  `ECE = sum_bin(n_bin/N * abs(mean_probability - observed_frequency))`
- ECE ขึ้นกับขนาดตัวอย่างและ bins ต้องแสดง count และห้ามสรุปจาก ECE ค่าเดียว
- margin/total รายงาน continuous Gaussian CRPS, RMSE, mean residual, coverage ของช่วงกลาง 90%
- CRPS reference ของ margin คือ Normal(initial_hca, margin_sigma)
  และของ total คือ Normal(2*league_ortg*league_pace/100, total_sigma) คงที่
- รายงาน standardized residual QQ quantiles ของ margin และ total
  ตรวจความคลาดเคลื่อน/หางแจกแจงก่อนเปลี่ยน family และยืนยัน CRPS ด้วย holdout ใหม่
- รายงาน log loss แยกทุกฤดูกาลเพื่อให้เห็นความเสื่อมที่ค่าเฉลี่ยรวมอาจซ่อนอยู่
- pricing unit tests ต้องครอบคลุมเส้นเต็ม ครึ่งแต้ม pick'em และผลรวม win/push/loss = 1
  โดย v1 ยังไม่ประเมิน spread/total outcome log loss หากไม่มีข้อมูลเส้นราคาย้อนหลัง

### 7.4 ความไม่แน่นอนและการทดลองหลายครั้ง

ใช้ paired block bootstrap ของส่วนต่าง log loss เทียบ HCA-only
block เป็นวันแข่งตาม `data.calendar_timezone`; สุ่มทั้งวันพร้อมเกมทั้งหมดในวันนั้น
แต่ละ replicate คิดค่าเฉลี่ยถ่วงตามจำนวนเกม ไม่ใช่เฉลี่ยค่าเฉลี่ยรายวัน
seed, จำนวน bootstrap samples และ confidence level ต้องอยู่ใน config

ค่าปริยาย: 1,000 replicates, ช่วง percentile สองด้าน 95%, อย่างน้อย 60 วันแข่ง
bootstrap นี้เก็บความสัมพันธ์ภายในวัน แต่ไม่ได้จำลอง serial dependence ข้ามวันทั้งหมด
และไม่ได้แก้ selection bias จากการลองโมเดลซ้ำ จึงต้องใช้ locked holdout แยกจาก tuning
อย่าอ้าง significance จากการเลือก run ที่ดีที่สุดในหลาย run

### 7.5 ราคาและ CLV

v1 ไม่ใช้ราคาตลาดเป็น input หรือ gate จึงแสดง `not available` แทนการสร้างคะแนนขึ้นมา
เมื่อมี licensed odds adapter ให้เทียบ p ตลาดที่ตัดค่าน้ำจาก timestamp เดียวกับ as-of
ราคาปิดใช้เป็นข้อมูลอ้างอิงภายหลังได้ ห้ามป้อนย้อนหลังเข้าคำทำนายก่อนข่าวปิดตลาด

หากภายหลังประเมิน CLV ต้องมี side, market, line, quote ที่ออกจริง และ close quote
เปรียบเทียบตลาด/line/side เดียวกันเท่านั้น กำหนด `CLV = decimal_taken/decimal_close - 1`
ค่าบวกหมายถึงได้ราคา decimal สูงกว่าราคาปิด ไม่ใช่กำไรจริง และ CLV ไม่แทน log loss
หาก line เปลี่ยนและไม่มี quote เส้นเดิม ให้รายงานว่าเปรียบเทียบไม่ได้

### 7.6 Artifact contract

ทุก backtest ที่สำเร็จสร้างโฟลเดอร์ใหม่ ไม่เขียนทับ run เก่า:

| ไฟล์ | สิ่งที่ต้องมี |
| --- | --- |
| config.yaml | config เต็ม รวม seed และเกณฑ์ตรวจรับ |
| manifest.json | report schema, run/time, config/data/source hashes, dependencies, provenance, filters, metrics, gates |
| predictions.csv | game/season/tipoff/as-of/result time, labels, p ของทุก baseline, mean/sigma, pace, training count |
| calibration.csv | bin, count, mean probability, observed frequency |
| residual_qq.csv | theoretical Normal และ observed standardized quantiles |
| acceptance.json | policy version, status, checks, observed values/rules, bootstrap interval |
| report.md | สรุปภาษาไทย ตารางเทียบหลัก/ฤดูกาล/distribution และผลตรวจเกณฑ์ |

run เก่าก่อน report schema 2 ยังคงเป็นหลักฐานการทดลองเดิม
แต่ไม่อ้างว่าผ่านเกณฑ์ใหม่จนกว่าจะรันใหม่ด้วยนโยบายปัจจุบัน

## 8. เกณฑ์ผ่าน milestone v1

ตัวเลขต่อไปนี้เป็นมาตรฐานเริ่มต้นที่เราเลือกสำหรับโปรเจกต์ ไม่ใช่มาตรฐานสากลหรือผลที่พิสูจน์แล้ว
หากเปลี่ยนเกณฑ์ ต้องเพิ่ม policy version และประเมิน holdout ใหม่ ห้ามลดเกณฑ์เพื่อให้ run เดิมผ่าน

### 8.1 Gate A — ซอฟต์แวร์และความถูกต้อง

- ผ่าน pytest ทั้งหมด, Ruff lint และ format check
- ผ่าน future-data mutation tests ของ outcome, stats และ schedule รวมผลที่เผยแพร่ล่าช้า
- input validation กัน timestamp ไม่มี timezone, final score เสมอ, keys ซ้ำและ stats ก่อนทราบผล
- CLI demo/ingest/validate/backtest/predict ทำงานครบ; SQLite/Parquet round-trip ไม่เปลี่ยน dataset hash
- config/data/source เดิมให้คำทำนาย คะแนน และ bootstrap เหมือนเดิม
- probabilities อยู่ใน [0,1], pricing รวมได้ 1, sigma > 0

Gate A ยืนยันด้วย test/check outputs แยกจากผล backtest
`acceptance.json` ไม่อ้างว่าได้รัน tests หรือยืนยัน Gate A แทนผู้พัฒนา

### 8.2 Gate B — โมเดลจากข้อมูลจริง (ตรวจอัตโนมัติ)

ค่าจริงที่ใช้ในแต่ละ run อ่านจาก `acceptance` ใน YAML:

| เงื่อนไข | ค่าเริ่มต้น |
| --- | ---: |
| มี metadata ระบุ real data, source และ usage note | ต้องมี |
| จำนวนเกมที่ประเมินหลัง warmup | >= 1,000 |
| จำนวนฤดูกาลที่ประเมิน | >= 2 |
| จำนวนเกมทุกฤดูกาลที่อยู่ในการประเมิน | >= 200 |
| จำนวนวันแข่งที่ใช้ bootstrap | >= 60 |
| Log loss ดีขึ้นจาก HCA-only | >= 0.005 |
| Upper endpoint ของ paired 95% CI ของ Δ LL vs HCA | < 0 |
| Log loss เทียบทุก simple baseline | ไม่แย่กว่า |
| Δ LL vs HCA ในแต่ละฤดูกาล | <= +0.01 |
| ECE ของ p_home_win | <= 0.05 |
| Brier score เทียบ HCA-only | ไม่แย่กว่า |
| Margin/total central 90% coverage | 0.85–0.95 |
| Absolute mean margin residual | <= 2 แต้ม |
| Absolute mean total residual | <= 3 แต้ม |
| CRPS margin และ total เทียบ fixed Normal reference | ไม่แย่กว่า |

ทุก check ต้องผ่านจึงได้ `automated_model_gate_passed=true`
สถานะ `demo_only` ใช้กับข้อมูลจำลองเสมอ แม้ตัวเลขดูดี
`insufficient_data` ใช้เมื่อ provenance/ขนาดข้อมูล/จำนวนฤดูกาล/วันแข่งไม่ครบ
`failed` คือข้อมูลครบแต่คะแนนไม่ผ่าน; `passed` คือ Gate B ผ่าน

### 8.3 Gate C — กระบวนการยืนยันและการขึ้น milestone

ก่อนประกาศว่า v1 ผ่านและเพิ่ม v2 ต้องมี Gate A + Gate B พร้อมหลักฐานต่อไปนี้:

- บันทึก `VALIDATION_PROTOCOL.md` ฉบับที่กรอกจริงก่อนเปิดผล final holdout
- มี training/tuning/holdout ranges, เวลาเผยแพร่, data/config/source hashes และรายการ run ที่ใช้เลือกโมเดล
- ตรวจว่า hyperparameters และ acceptance policy ไม่ถูกเลือก/ปรับจาก final holdout
- ตรวจ reliability counts, residual QQ และการเสื่อมรายฤดูกาลจาก report ของ run ที่ผ่าน
- กำหนด candidate เป็น baseline รุ่นที่จะคงไว้สำหรับการทดลอง v2

`passed` ใน Gate B จึงไม่ใช่คำรับรองสิทธิ์ข้อมูลหรือหลักฐานว่า holdout ไม่เคยถูกเปิดดู
Gate C ใช้บันทึกการพัฒนาที่ตรวจย้อนกลับได้ ประเมินโดยเจ้าของโปรเจกต์เมื่อมีข้อมูลจริง

### 8.4 ขอบเขตการต่อยอด

สามารถพัฒนา v2 เป็นส่วนทดลองแยกจาก v1 ได้ตามขอบเขตงานของโปรเจกต์
การประกาศเลื่อน milestone ที่ยืนยันคุณภาพแล้วต้องให้ v1 ผ่านทั้งสาม gate ก่อน
ส่วนผู้เล่น/นาที/สถานะการลงเล่นแบบ scenario ที่ยังไม่มี historical validation ต้องระบุ experimental
v3 ensemble และ v4 simulation ต้องทำ ablation และวัดด้วยมาตรฐานหัวข้อ 7 เดิม
ถ้าตัวใหม่ไม่ช่วย out-of-sample ให้คง baseline ที่ง่ายกว่า
ข้อมูลจริงและตลาดยังไม่พร้อมไม่เป็นเหตุให้ข้ามการพิสูจน์คุณภาพด้วยข้อมูลจำลอง

## 9. ส่วนทดลอง: ข้อมูล NBA และ House comparison

ใช้ `NBA_DATA_AND_COMPARISON.md` เป็นข้อกำหนดส่วนเพิ่มเติม:
เก็บสถิติทีม/roster เป็น timestamped snapshots, ให้ผู้ใช้เลือกคนลงเอง,
และแยก House fair probability จาก offered odds และ EV
เก็บ v1 walk-forward pipeline เป็น baseline อิสระ ไม่ใช้สถิติรวมปัจจุบันย้อนสร้างฟีเจอร์อดีต
manual names ไม่เปลี่ยน probability จนกว่าจะมี impact ratings และ reference rotation
เกณฑ์เลือกฝั่งเป็นการวิเคราะห์ทดลอง ไม่ใช้สถานะ Gate B ของ v1 มาอ้างว่า feature ใหม่นี้ผ่านแล้ว
