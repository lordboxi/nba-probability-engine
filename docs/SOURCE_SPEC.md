# NBA Probability Engine — สเปกสำหรับส่งต่อให้ Codex

สรุปจากการออกแบบร่วมกับ Claude · 19 ตุลาคม 2026 · ใช้สร้าง v1 แล้วต่อยอดถึง v5

## 0. คำสั่งถึง Codex (อ่านก่อนลงมือ)

- อ่านเอกสารทั้งฉบับก่อนเขียนโค้ด แล้วเริ่มที่ milestone v1 เท่านั้น ห้ามข้ามไปทำชั้นที่ซับซ้อนกว่า จนกว่า v1 จะผ่านเกณฑ์ในหัวข้อ 8
- ใช้ Python 3.11+ ตั้งค่าพารามิเตอร์ทั้งหมดผ่านไฟล์ YAML ห้ามฮาร์ดโค้ด และตั้ง random seed เพื่อให้ผลซ้ำได้
- ทุกฟีเจอร์ต้องคำนวณจากข้อมูลที่รู้ก่อนเวลาทาย (as-of) เท่านั้น และต้องมี test ตรวจว่าข้อมูลอนาคตไม่รั่วเข้ามา
- ทดสอบย้อนหลังแบบ walk-forward เท่านั้น ห้ามสุ่มแบ่งเกมเป็นชุดเทรนและชุดทดสอบ
- ทุกครั้งที่เพิ่มโมเดลหรือฟีเจอร์ ให้รายงาน log loss เทียบกับ baseline ในรูปแบบเดียวกัน (หัวข้อ 7) และเก็บผลทุกการทดลองไว้
- ถ้าสเปกไม่ชัดหรือข้อมูลไม่พอ ให้ถามผู้ใช้ หรือบันทึกสมมติฐานไว้ใน `docs/ASSUMPTIONS.md` อย่าเดาเงียบๆ
- ตรวจเงื่อนไขการใช้งานของแหล่งข้อมูลทุกแหล่งก่อนดึงข้อมูล และห้ามฝัง API key ไว้ในโค้ด

## 1. เป้าหมายและขอบเขต

สร้างเอนจินคำนวณความน่าจะเป็นผลการแข่งขัน NBA ที่ตรงกับความถี่จริง (calibrated) และอยู่ใกล้ราคาตลาดที่ตัดค่าน้ำแล้ว ความสำเร็จวัดด้วย log loss แบบ walk-forward ไม่ใช่เปอร์เซ็นต์ทายถูก

ผลลัพธ์ที่ระบบต้องให้:

- `p_home_win` และการแจกแจงของ margin (แต้มเจ้าบ้านลบแต้มทีมเยือน) กับ total (แต้มรวม)
- ความน่าจะเป็นชนะ/push/แพ้ของเส้นต่อรองใดๆ รวมเส้นเลขเต็ม และของเส้นสูง/ต่ำ
- v4 ขึ้นไป: การแจกแจงของ player props และการแจกแจงร่วมที่สอดคล้องกัน
- v5: win probability ระหว่างเกม

ไม่อยู่ในขอบเขต: ระบบรับเดิมพัน การเงิน บัญชีผู้ใช้ และส่วนติดต่อลูกค้า ถ้าจะนำไปใช้รับแทงจากลูกค้าจริง ต้องมีใบอนุญาตตามกฎหมายของประเทศที่ให้บริการ เพราะหลายประเทศการรับแทงโดยไม่ได้รับอนุญาตผิดกฎหมาย

หลักการสำคัญ: ความซับซ้อนไม่เท่ากับความแม่น ใน NBA สัญญาณต่อสัญญาณรบกวนต่ำ โมเดลง่ายๆ ที่ใช้เรตติ้งทีม ความได้เปรียบเจ้าบ้าน และวันพัก ได้ความแม่นส่วนใหญ่แล้ว ให้เพิ่มชั้นใหม่เมื่อผลทดสอบย้อนหลังพิสูจน์ว่าช่วยจริงเท่านั้น

## 2. สถาปัตยกรรม

ไปป์ไลน์ 5 ชั้น:

1. ข้อมูล: ผลเกม, boxscore, play-by-play, รายงานบาดเจ็บ, ตารางแข่ง, ราคาย้อนหลัง
2. เรตติ้งและฟีเจอร์: เรตติ้งทีมและผู้เล่น, ฟีเจอร์บริบท (วันพัก, การเดินทาง, HCA)
3. โมเดลหลายตัว A/B/C/D: ทำนาย margin และ total (หัวข้อ 5.3)
4. รวมโมเดลและปรับความแม่น: stacking, calibration, ผสมราคาตลาด
5. ผลลัพธ์: `p_home_win`, การแจกแจง margin/total, ความน่าจะเป็นของเส้นต่อรองและเส้นสูง/ต่ำ

วงจรวัดผล (walk-forward, log loss, CLV) ทดสอบทุกชั้นและป้อนผลกลับไปปรับชั้น 2–4 (หัวข้อ 7)

## 3. เทคโนโลยีและโครงสร้างโปรเจกต์

- ไลบรารี: `numpy`, `pandas`, `scipy`, `statsmodels`, `scikit-learn`, `lightgbm`; `pymc` (หรือ Stan) เฉพาะ v3; `pytest` และ `ruff`
- ที่เก็บข้อมูล: DuckDB หรือ SQLite ไฟล์เดียว พร้อมไฟล์ Parquet สำหรับข้อมูลดิบ
- เขียนโค้ด ชื่อตัวแปร docstring และ commit message เป็นภาษาอังกฤษ ส่วนรายงานผลเขียนเป็นภาษาไทยได้
- ห้ามเพิ่ม dependency ใหม่โดยไม่แจ้งเหตุผล

```
nba-prob/
  pyproject.toml
  config/default.yaml
  docs/ASSUMPTIONS.md
  src/nbaprob/
    data/        # adapters per source, loaders, schema validation, as-of snapshot builder
    ratings/     # team_ratings.py, player_ratings.py, priors.py
    features/    # context.py (rest, travel, HCA), build.py
    models/      # baseline_gaussian.py, gbm.py, bayes_hier.py, possession_sim.py
    ensemble/    # stacking.py, calibration.py, market_blend.py
    dist/        # margin_dist.py, totals.py
    pricing/     # devig.py, odds.py
    eval/        # walkforward.py, metrics.py, report.py
    cli.py
  tests/
  experiments/   # log of every run: config hash, data version, metrics
```

## 4. สเปกข้อมูล

| ตาราง | คอลัมน์หลัก | หมายเหตุ |
| --- | --- | --- |
| games | game\_id, season, date, home\_team, away\_team, home\_pts, away\_pts, ot\_periods | เก็บจำนวน OT ไว้ทุกเกม |
| team\_game\_stats | game\_id, team, possessions, ortg, drtg | ใช้คำนวณ Pace |
| schedule | game\_id, rest\_days\_home, rest\_days\_away, b2b\_home, b2b\_away, games\_last\_7d, travel\_km, altitude | คำนวณจากตารางแข่ง |
| player\_game\_stats | game\_id, team, player\_id, minutes | ใช้ประมาณนาทีที่คาด (v2) |
| stints หรือ pbp | game\_id, lineup, possessions, margin | ใช้คำนวณเรตติ้งผู้เล่น (v2) และจำลองเกม (v4) |
| injuries | player\_id, team, game\_id, status, reported\_at | ต้องมี timestamp ทุกแถว |
| odds | game\_id, book, market, line, price\_home, price\_away, ts, is\_open, is\_close | ใช้สำหรับผสมตลาดและ CLV |

v1 ใช้เฉพาะ games, team\_game\_stats และ schedule ตารางอื่นใช้ตั้งแต่ v2

กฎ as-of: ฟังก์ชัน `build_features(game_id, as_of)` ต้องใช้เฉพาะแถวที่ `ts` เกิดก่อนหรือเท่ากับ `as_of` ในทุกตาราง ราคาปิดมีข่าวช่วงท้ายรวมอยู่แล้ว จึงใช้เป็นอินพุตได้เฉพาะ as-of ที่ใกล้เวลาปิด

แหล่งข้อมูลที่เป็นไปได้: NBA.com stats และ Basketball-Reference (ผลเกม, boxscore, play-by-play), รายงานบาดเจ็บทางการของ NBA และผู้ให้บริการข้อมูลราคาย้อนหลัง ให้ออกแบบ loader เป็น adapter แยกต่อแหล่ง เพื่อสลับแหล่งได้โดยไม่แก้ส่วนอื่น และตรวจเงื่อนไขการใช้งานก่อนดึงข้อมูล

## 5. สเปกการคำนวณ

### 5.1 เรตติ้งทีมที่ปรับตัวได้ (v1)

```
mu      = (R_home - R_away) * Pace/100 + HCA + rest + travel
delta   = (margin_actual - mu) * 100 / Pace
R_home += K_t * delta        # the away team uses the opposite sign
R_team  = w * R_season + (1 - w) * R_prior ,  w = n / (n + k)
```

- `K_t` ใช้ Kalman gain ที่ลดลงเมื่อข้อมูลสะสม ไม่ใช่ค่าคงที่ โดย process noise และ observation noise เป็น hyperparameter ใน config
- v1 ใช้ `R_prior` จากเรตติ้งปลายฤดูกาลก่อนหน้า shrink เข้าหาค่ากลางลีก (สัดส่วน shrink เป็น hyperparameter) ส่วน v2 เปลี่ยนเป็นผลรวมเรตติ้งผู้เล่น × นาทีที่คาด
- `k` ปรับจูนจากข้อมูลย้อนหลัง ไม่ฮาร์ดโค้ด
- HCA ใช้ค่ากลางทั้งลีกก่อน ค่ารายทีมต้อง shrink แรงเข้าหาค่ากลาง
- ผลของ back-to-back การเดินทาง และสนามที่สูง ให้ประมาณด้วย regression บนข้อมูลช่วงล่าสุด (rolling) แทนตัวเลขตายตัว เพราะขนาดผลเปลี่ยนไปตามยุค

### 5.2 เรตติ้งผู้เล่นและผู้เล่นบาดเจ็บ (v2)

```
TeamNet = sum_i( P_i * m_i / 48 )        # sum of m_i = 240 minutes, P_i = impact per 100 possessions
P(win)  = sum_s( pi_s * Phi(mu_s / sigma) )
```

- `s` คือสถานการณ์ว่าใครลง/ไม่ลง และ `pi_s` คือความน่าจะเป็นของสถานการณ์นั้น ให้คำนวณทุกสถานการณ์แล้วถ่วงน้ำหนัก ห้ามปัดสถานะ questionable เป็นลง/ไม่ลง และห้ามเอาเรตติ้งเฉลี่ยไปคิดทีเดียว เพราะ Phi ไม่เป็นเส้นตรง
- ตาราง mapping จากสถานะ (out, doubtful, questionable, probable) เป็นความน่าจะเป็นที่จะลงเล่น ให้เป็น config ที่ประมาณจากข้อมูลย้อนหลัง
- รันซ้ำหลาย as-of: ตอนเปิดราคา ก่อนเกมหลายชั่วโมง และใกล้ทิปออฟเมื่อรายชื่อตัวจริงชัดแล้ว
- รองรับเรตติ้งผู้เล่นจากไฟล์ภายนอก (เช่น EPM, RAPM) หรือคำนวณเองด้วย ridge regression บน stints

### 5.3 ชุดโมเดล (v3 ขึ้นไป)

- A: เรตติ้ง + Normal margin (baseline ของ v1) ต้องคงไว้เป็นเส้นเปรียบเทียบเสมอ
- B: `LightGBM` ทำนาย margin และ total จากฟีเจอร์ เช่น ผลต่างเรตติ้ง, pace, วันพัก, จำนวนเกมใน 4–7 วัน, นาทีที่คาด, ฟอร์มล่าสุดที่ถูก shrink, ความต่อเนื่องของรายชื่อ ใส่ monotonic constraint กับฟีเจอร์ที่ควรแปรทางเดียว (เช่น ผลต่างเรตติ้ง) และเลือก hyperparameter ด้วย time-based CV
- C: Bayesian แบบลำดับชั้น คือรุก/รับรายทีมแบบ partial pooling ที่เปลี่ยนตามเวลา (random walk) ให้ posterior ของ mu และ sigma
- D (v4): จำลองรายการครองบอลแบบ Monte Carlo ให้การแจกแจงร่วมของ margin, total และ props จำนวนรอบเป็น config (เริ่มที่ 10,000 รอบต่อเกม)

### 5.4 รวมโมเดล (stacking)

```
logit(p) = sum_k( w_k * logit(p_k) ) ,  w_k >= 0 ,  sum_k w_k = 1
```

- หา `w_k` จากผล out-of-fold โดยลด log loss ให้ต่ำสุด (ใช้ scipy ที่มี simplex constraint)
- เทียบกับค่าเฉลี่ยน้ำหนักเท่ากันเสมอ ถ้า stacking ไม่ดีกว่าอย่างมีนัยสำคัญ ให้ใช้น้ำหนักเท่ากัน

### 5.5 การแจกแจงของ margin และ total

- `sigma = sigma0 * sqrt(Pace / Pace_league)` เพราะคะแนนสะสมจากจำนวนการครองบอล ให้ประมาณ `sigma0` จาก residual และปรับตามช่วงสเปรด (เกมห่างมากมักมี garbage time)
- ตรวจ QQ-plot ของ residual ถ้าหางหนากว่าโค้งปกติ ให้เลือก Student-t (fit ค่า df) หรือ empirical distribution ตามผล CRPS
- margin เป็นจำนวนเต็มและไม่มีเสมอ (มี OT) จึงใช้ `P(win) = Phi(mu / sigma)` โดยไม่ต้องใช้ continuity correction

คอนเวนชันของสเปรด: `spread` คือแต้มต่อรองของทีมเจ้าบ้าน (−6.5 คือเจ้าบ้านให้ 6.5 แต้ม) เจ้าบ้านชนะราคาเมื่อ `margin + spread > 0` ให้กำหนด `L = -spread`

```
L is a half point (e.g. 6.5):
  P(home covers) = 1 - Phi((L - mu) / sigma)
  P(push)        = 0

L is a whole number (e.g. 7):
  P(push)        = Phi((L + 0.5 - mu) / sigma) - Phi((L - 0.5 - mu) / sigma)
  P(home covers) = 1 - Phi((L + 0.5 - mu) / sigma)
  P(away covers) = Phi((L - 0.5 - mu) / sigma)
```

เส้นสูง/ต่ำใช้หลักเดียวกัน โดยแทน `mu` ด้วย `mu_total`, `sigma` ด้วย `sigma_total`, `L` ด้วยเส้นของ total และ P(home covers) ด้วย P(over)
