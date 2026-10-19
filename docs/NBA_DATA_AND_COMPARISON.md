# สถิติ NBA, เลือกผู้เล่นเอง และเทียบ House

รุ่น 0.2 เป็นส่วนวิเคราะห์ทดลองเพิ่มจาก v1 baseline ซึ่งยังคงใช้ backtest เดิมได้
การมีฟีเจอร์ใหม่ไม่ใช่หลักฐานว่าความแม่นยำสูงขึ้น ต้องประเมินข้อมูลจริงแบบ as-of เพิ่มภายหลัง

## เปิดหน้าจอ

```powershell
Set-Location 'C:\GPT Project\NBA Project'
uv sync --locked --python 3.11 --extra dev --extra ui
uv run --extra ui streamlit run src/nbaprob/app.py --server.address 127.0.0.1
```

เปิด `http://127.0.0.1:8501` หน้าจอมีสามแท็บ:

1. **ข้อมูล NBA** เลือกฤดูกาล/Preseason/Regular Season/Playoffs ดูตารางและดึงรายชื่อทีม
2. **วิเคราะห์คู่แข่งขัน** เลือกสองทีม เวลาเริ่มแข่งและเวลาทำนาย เลือกตัวจริงและติ๊กตัวสำรอง แล้วกรอก House
3. **ประวัติและผลจริง** เก็บคำทำนาย กรอกสกอร์สุดท้าย และเทียบความแม่นโมเดล/House/ค่าผสมบนเกมชุดเดียวกัน

คู่ในโหมดตาราง NBA เป็นคู่ที่ผู้ใช้กำหนดเอง ไม่ได้ตรวจว่าทั้งสองทีมแข่งกันจริงตาม schedule
เกมในโหมดข้อมูลโปรเจกต์ใช้ game_id และเวลาใน dataset

## แหล่งข้อมูลและสิ่งที่ทดสอบได้จริง

ใช้ [ตาราง Traditional ของ NBA](https://www.nba.com/stats/teams/traditional) และหน้าเว็บทีม NBA
ไม่ต้องมี API key ไม่มีการสมัครแพ็กเกจหรือบริการเสียเงินในโปรเจกต์นี้

ในการตรวจวันที่ 19 ตุลาคม 2026:

- อ่านตารางผ่านเบราว์เซอร์สำเร็จ: ฤดูกาล 2026–27, Preseason, Per Game รวม 31 แถว
  (มี London Lions ซึ่งเป็นทีมรับเชิญ Preseason จึงไม่เรียกว่า 31 ทีม NBA)
- เก็บค่าที่แสดงจริงพร้อม team IDs ไว้ใน `data/nba_teams_browser_capture.json`
- ดึงและอ่านตาราง roster หน้าเว็บทีม Boston และ Atlanta สำเร็จ เก็บ snapshot แยกทีมแล้ว
- คำขอไป `stats.nba.com` โดยตรงหมดเวลาจากเครื่องนี้ จึงไม่อ้างว่าดึงสดทุก endpoint ได้แล้ว
  ปุ่มดึงสถิติทีมอาจพบข้อจำกัดเครือข่ายเดียวกัน ให้ใช้ cached snapshot หรือไฟล์ที่บันทึกจากหน้าเว็บ

การ refresh มีสองทาง:

```powershell
# ขอ team stats จาก endpoint ของหน้า NBA; อาจหมดเวลาในบางเครือข่าย
uv run nbaprob nba-fetch teams --season 2026-27 --season-type Preseason

# roster ฤดูกาลปัจจุบันอ่านตารางหน้าเว็บทีม โดยไม่รวม retired/hall-of-fame tables
uv run nbaprob nba-fetch roster --season 2026-27 --team-id 1610612738

# นำเข้าตารางที่อ่านได้จากเบราว์เซอร์
uv run nbaprob nba-fetch teams --season 2026-27 --season-type Preseason --import-json data/nba_teams_browser_capture.json
```

ไฟล์ JSON แบบ NBA resultSets นำเข้าได้ในแท็บข้อมูล NBA เช่นกัน
หาก endpoint ไม่ตอบ ให้เปิดตาราง NBA ตามปกติ เลือก filters ให้ถูกต้องและรอให้ตารางแสดง
ผู้ใช้ที่ต้องการ export สามารถใช้ `scripts/export_nba_table.js` ใน browser console
สคริปต์อ่านเฉพาะตารางที่แสดงและดาวน์โหลด JSON ลงเครื่อง ไม่มีการส่งข้อมูลไปที่อื่น
จากนั้นนำ JSON เข้าแอป ไม่ใช่การดึงผ่าน API โดยอัตโนมัติ
รองรับ saved rendered HTML ด้วย `--import-html`; HTML ที่ไม่มีตารางจริงจะถูกปฏิเสธ
ห้ามเปลี่ยน season label เพื่อใช้ข้อมูลคนละฤดูกาล/ประเภทการแข่งขัน

แหล่งข้อมูลและการใช้งาน: [NBA Terms of Use](https://www.nba.com/termsofuse) ข้อ 9
จำกัดการใช้สถิติเกี่ยวกับการพนันรวมถึงการพนันที่ถูกกฎหมาย ความสามารถทางเทคนิคไม่ได้ให้สิทธิ์ใช้ข้อมูล
ตัวเชื่อมต่อไม่ได้รับรองว่าผู้ใช้มีสิทธิ์เกินเงื่อนไขสาธารณะของ NBA
หากนำไปใช้นอกขอบเขตที่อนุญาตต้องมีสิทธิ์ข้อมูลที่เหมาะสม
ไม่มี proxy, CAPTCHA bypass, การวน retry หรือการซ่อน API key

## Snapshot และ as-of

- เก็บ raw response/ค่าที่อ่าน พร้อม resource, season, season_type, source URL,
  acquisition method, retrieved_at และ content hash
- เก็บ JSON แบบไม่เขียนทับและ index ใน SQLite แยกจากเกมสำหรับ backtest
- `latest_snapshot` เลือกได้เฉพาะข้อมูลที่ retrieved_at <= as_of และ filters ตรงกัน
- เวลานำเข้าไฟล์เป็นเวลาที่ระบบทราบข้อมูล ห้ามย้อนหลังเวลาเพียงเพราะตารางระบุฤดูกาลเก่า
- สถิติรวมปัจจุบันไม่แปลงเป็นผลรายเกมในอดีต และไม่ใช้พิสูจน์ความแม่นยำย้อนหลัง
- เวลาทำนายที่ตั้งก่อนการดึง roster จะยังมองไม่เห็น roster นั้น ใช้ปุ่มเวลาปัจจุบันเมื่อต้องการวิเคราะห์ตอนนี้

## โมเดลจากตารางทีม

โหมด `experimental_team_snapshot` ใช้ small-sample shrinkage เข้าหาค่าลีก:

`estimated possessions = FGA + fta_weight * FTA - OREB + TOV`

`estimated ORtg = 100 * PTS / possessions`

`estimated DRtg = 100 * (PTS - PLUS_MINUS) / possessions`

pace ปรับด้วย 48/MIN; shrink weight = GP/(GP+snapshot_shrink_k)
ใช้ผลต่าง net rating กับ HCA เป็น margin mean และรุก/รับสองทีมประมาณ total
นี่เป็นค่าประมาณจาก Traditional ที่ปัดเศษแล้ว ไม่ใช่ค่า ORtg/DRtg/Pace ทางการ
Preseason มีจำนวนเกมน้อยและใช้ rotation ต่างจาก regular season จึงไม่อ้างผลว่า calibrated แล้ว
ค่าทั้งหมดที่ปรับจูนได้อยู่ใน YAML; ยังไม่มี rest/travel จริงในคู่ที่กำหนดเอง

## เลือกคนที่ลงเอง

ระบบแสดงรายชื่อที่ดึงจากทีม หรือรับ CSV คอลัมน์ `player_id,name,team` ตาม `examples/roster.csv`
เลือกตัวจริงทีมละ 5 คนจาก dropdown แยกตำแหน่ง **PG, SG, SF, PF, C** โดยไม่เลือกคนซ้ำ
หากต้องการย้ายตำแหน่ง ให้ล้างตำแหน่งเดิมก่อน ส่วนคนที่เหลือมี checkbox ให้ติ๊กเฉพาะตัวสำรองที่ลง
ตัวจริงถือว่าลงสนามอัตโนมัติ และต้องเลือกครบทั้งสองทีมก่อนกดคำนวณ ไม่ต้องกรอก injury status
ผล JSON บันทึก `selection_type=positioned_lineup` และแต่ละคนมี `plays`, `starter`, `position`
ผู้เล่นสำรองหรือคนที่ไม่ลงมี `position=null` ตำแหน่งที่เลือกเป็นการจัดทีมของผู้ใช้
ระบบไม่ถือว่ารายชื่อ roster คือรายชื่อพร้อมลงที่ยืนยันแล้ว

**รายชื่ออย่างเดียวไม่เพียงพอสำหรับคำนวณผลกระทบผู้เล่น**
โหมดพื้นฐานบันทึกการเลือกในผล JSON พร้อม `lineup_adjustment_applied=false`
จึงไม่เพิ่มความมั่นใจหรือปรับคะแนนโดยเดาฝีมือจากชื่อ/PPG

หากมีเรตติ้งผู้เล่นจากแหล่งที่ตรวจสอบได้ ให้แนบ lineup JSON ในตัวเลือกขั้นสูง:

```json
{
  "reported_at": "2026-10-19T09:00:00Z",
  "rating_source": "Describe rating model and dataset version",
  "probability_source": "Manual assumptions; not empirically fitted yet",
  "players": [
    {
      "player_id": "example-player",
      "name": "Example Player",
      "team": "EXACT_SELECTED_TEAM_NAME",
      "starter": false,
      "status": "questionable",
      "play_probability": 0.5,
      "baseline_minutes": 30.0,
      "expected_minutes": 30.0,
      "offense_impact": 2.0,
      "defense_impact": 1.0,
      "rating_as_of": "2026-10-19T08:00:00Z"
    }
  ]
}
```

ตัวอย่างด้านบนเป็นรูปแบบหนึ่งแถว ต้องมีทั้ง rotation ของสองทีมก่อนใช้งานจริง
baseline_minutes รวมทีมละ 240 และต้องเป็น reference rotation ที่เรตติ้งทีมฐานสะท้อนอยู่
expected_minutes เป็นน้ำหนัก rotation เมื่อคนนั้นลง; ทุก scenario จัดสรรใหม่รวม 240 โดยคนละไม่เกิน 48
ต้องมีสำรองพอให้ทุก scenario ที่มี probability > 0 เหลือคนอย่างน้อย 5 คน
starter เลือกได้ 0 หรือ 5 คนต่อทีม ไม่ได้ให้ bonus คะแนนเพียงเพราะเป็นตัวจริง

impact เป็นแต้มต่อ 100 possessions: offense บวกเพิ่มแต้มทีม; defense บวกลดแต้มคู่แข่ง
คำนวณเฉพาะส่วนต่างจาก reference rotation เพื่อไม่บวกเรตติ้งซ้ำกับทีมฐาน
ยังไม่ได้สร้าง impact rating จาก boxscore ในโปรเจกต์นี้

status มี out/doubtful/questionable/probable/available หรือกำหนด play_probability เอง
mapping ใน YAML เป็นสมมติฐานเริ่มต้น ไม่ใช่อัตราการลงจริงที่จูนแล้ว
ผู้เล่นไม่แน่ใจคำนวณทุก scenario แบบอิสระและเฉลี่ย **probability** ตามน้ำหนัก
ไม่เอาเรตติ้งเฉลี่ยไปใส่ Phi เพียงครั้งเดียว และใช้ mixture เดียวกันคำนวณ spread/total
กรณีสถานะสัมพันธ์กันต้องเตรียม joint model เพิ่ม ปัจจุบันยังสมมติ independent

## House probability แล้วเลือกอะไร

เลือกตลาดเดียวกันและเส้นเดียวกันเสมอ:

- Moneyline: primary=เจ้าบ้าน, secondary=ทีมเยือน
- Spread: เส้นเป็น handicap ของเจ้าบ้าน เช่น -6.5; primary=home cover
- Total: primary=สูง, secondary=ต่ำ

รองรับ fair probability, implied probability สองฝั่ง, Decimal และ American odds
ใน JSON probability ใช้ 0–1; ในหน้าจอใส่เปอร์เซ็นต์ได้
implied probabilities/odds จะถูก normalize เพื่อตัด overround แบบ proportional
ราคาที่ตัดน้ำเพื่อเทียบโอกาสแยกจากราคาจ่ายจริงที่ใช้คำนวณ EV

`edge = model_probability_given_no_push - house_fair_probability`

`EV ต่อหน่วย = P(win)*(decimal_odds-1) - P(loss)`

push คืนเงินจึงไม่คิดเป็นแพ้ และไม่ใช้ `p*odds-1` เมื่อมี push
เปอร์เซ็นต์ที่โมเดลสูงกว่า House ไม่ได้แปลว่าราคาจ่ายคุ้มเสมอ
ตัวอย่างทางคณิตศาสตร์: ถ้าสมมติ p=60% ราคา 1.91 ให้ EV=+0.146 ต่อหน่วย
แต่ราคา 1.50 ให้ EV=-0.10 ต่อหน่วย แม้ยังเป็นฝั่งที่มีโอกาสชนะสูงกว่า

ผลจากระบบ:

| สถานะ | ความหมาย |
| --- | --- |
| comparison_only | มี probability เปรียบเทียบ แต่ยังไม่มีราคาจ่ายจริง จึงไม่เลือกฝั่งด้วย EV |
| analytical_candidate | ผ่าน edge, EV และ scenario stress thresholds เป็นผลวิเคราะห์ทดลอง |
| no_selection | ไม่มีฝั่งผ่านเงื่อนไขทั้งหมด |
| wait_for_lineup | โอกาสเปลี่ยนมากเกินเกณฑ์ระหว่าง scenarios ควรรอรายชื่อให้ชัด |
| refresh_quote | ราคาเก่ากว่า maximum age ต้องอัปเดต |

ค่าเริ่มต้น: edge >= 3 จุดเปอร์เซ็นต์, EV และ stress EV >= 0.02 ต่อหน่วย,
buffer 3 จุดเปอร์เซ็นต์, scenario probability range <= 15 จุดเปอร์เซ็นต์, ราคาอายุไม่เกิน 30 นาที
stress ใช้ทุก scenario ที่มีน้ำหนักบวกแล้วหัก buffer ไม่ใช่ confidence interval ทางสถิติ
โมเดล/เกณฑ์เลือกนี้ยังไม่ผ่านการยืนยันบนข้อมูลจริง ไม่มี staking หรือระบบส่งเดิมพัน
House ถูกใช้เปรียบเทียบเท่านั้น ไม่ผสมกลับเข้า model probability

## CLI ตัวอย่าง

```powershell
# ตัวอย่างข้อมูลจำลองที่มากับโปรเจกต์
uv run nbaprob predict demo-next --as-of '2026-01-10T22:00:00Z' --house examples/house_odds.json --output data/comparison-demo.json

# คู่ที่กำหนดเองจาก NBA snapshot ปัจจุบัน
$nbaAsOf = (Get-Date).ToUniversalTime()
$nbaTipoff = $nbaAsOf.AddHours(4)
uv run nbaprob matchup --season 2026-27 --home-team-id 1610612738 --away-team-id 1610612737 --as-of $nbaAsOf.ToString('o') --tipoff $nbaTipoff.ToString('o') --output data/nba-matchup.json
```

`--selection`, `--lineup`, `--house` รับไฟล์ JSON ใน predict/matchup
หากไม่ได้ระบุ game_id ในไฟล์ CLI จะผูกกับคู่ที่เลือกอย่างชัดเจน;
ถ้าระบุ game_id ที่ต่างกันจะปฏิเสธ ราคา/ข้อมูลจากอนาคตก็จะถูกปฏิเสธ
ผลบันทึก config hash, snapshot identity, input quote และการเลือกผู้เล่นให้ตรวจย้อนกลับได้
