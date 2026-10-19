# บันทึกการยืนยัน final holdout

สถานะ: template ยังไม่ใช่หลักฐานว่ามีการล็อกหรือทดสอบ holdout จริง
กรอกเป็นไฟล์ใหม่ประจำ candidate และบันทึกเวอร์ชันไว้ก่อนเปิดดูผล

- Candidate name/version:
- Protocol recorded at (timestamp with timezone):
- Data source, permission reference and timestamp provenance:
- Dataset SHA256:
- Source SHA256:
- Config SHA256:
- Acceptance policy version:
- Development/training range:
- Inner walk-forward tuning folds and search space:
- Experiment IDs inspected during selection:
- Final holdout start (inclusive tipoff):
- Final holdout end (exclusive tipoff):
- Prediction lead and permitted online updates:
- Rule for choosing the candidate before holdout:
- Prior holdout exposure (if any):

หลังเปิดผลจึงกรอก:

- Final holdout experiment ID:
- Gate A test/lint outputs:
- Gate B acceptance.json status and failed checks:
- Calibration counts, season stability and residual QQ review:
- Changes made after viewing holdout (if any; require a new unseen holdout):
- Gate C decision and rationale:
- Version retained as baseline for the next milestone:
