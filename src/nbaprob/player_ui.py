"""Player statistics and explicit impact/minutes controls for the Streamlit app."""

import json
from urllib.parse import urlencode

import pandas as pd
import streamlit as st

from nbaprob.data.nba_stats import NBAStatsAdapter
from nbaprob.data.snapshots import latest_snapshot, save_snapshot
from nbaprob.lineups.player_stats import player_statistics, rotation_document, rotation_rows


def player_data_panel(config, season, season_type, as_of, adapter: NBAStatsAdapter):
    with st.expander("สถิติผู้เล่นจาก NBA"):
        year = int(season[:4]) - 1
        previous = f"{year}-{(year + 1) % 100:02d}"
        targets = {
            "ฤดูกาล/ประเภทที่เลือก": (season, season_type),
            "Preseason ฤดูกาลที่เลือก": (season, "Preseason"),
            "Regular Season ฤดูกาลก่อน": (previous, "Regular Season"),
        }
        target = st.selectbox(
            "ฐานสถิติผู้เล่น",
            list(targets),
            index=1 if season_type == "Regular Season" else 0,
            key="player_stats_basis",
        )
        year, kind = targets[target]
        query = urlencode({"Season": year, "SeasonType": kind})
        st.markdown(
            f"[เปิดตารางผู้เล่น NBA ตามฐานที่เลือก](https://www.nba.com/stats/players/traditional?{query})"
        )
        st.caption(f"{year} · {kind} · Per Game · เก็บตาม player ID และ team ID")
        st.caption(
            "ใช้ข้อมูลที่บันทึกไว้ด้านล่างได้ทันที ไม่จำเป็นต้องกดดึงใหม่ทุกครั้ง "
            "หากฤดูกาลใหม่ยังไม่มีเกม ให้ใช้ Preseason หรือ Regular Season ฤดูกาลก่อน"
        )
        snapshot = latest_snapshot(config, "players", year, as_of, kind)
        upload = st.file_uploader(
            "นำเข้าสถิติผู้เล่น NBA JSON/HTML", type=["json", "html"], key="player_stats_upload"
        )
        if st.button("บันทึกสถิติผู้เล่น" if upload else "ดึงสถิติผู้เล่น NBA", key="fetch_players"):
            try:
                payload = None
                if upload:
                    text = upload.getvalue().decode("utf-8-sig")
                    payload = text if upload.name.lower().endswith(".html") else json.loads(text)
                with st.spinner("กำลังอ่านสถิติผู้เล่น…"):
                    document = adapter.fetch("players", year, kind, imported_payload=payload)
                    saved = save_snapshot(document, config)
                snapshot = {**document, "identity": saved["identity"]}
                st.success(f"บันทึกสถิติผู้เล่น {saved['rows']} แถวแล้ว กดใช้เวลาปัจจุบันก่อนวิเคราะห์")
            except (ValueError, OSError, KeyError) as error:
                st.warning(
                    "ดึง/นำเข้าสถิติไม่สำเร็จ ข้อมูลที่บันทึกไว้ไม่ได้ถูกลบ "
                    "หาก NBA ติดต่อไม่ได้ ให้ใช้ข้อมูลเดิมหรืออัปโหลด NBA JSON/HTML ที่มีตารางจริง"
                )
                st.caption(str(error))
        if snapshot:
            st.caption(
                f"มีสถิติ {len(snapshot['data'])} แถว · ข้อมูล ณ {snapshot['retrieved_at']} "
                "· ค่าร้อยละเก็บเป็นสัดส่วน 0–1"
            )
            st.dataframe(pd.DataFrame(snapshot["data"]), hide_index=True)
        else:
            st.info("ยังไม่มีสถิติผู้เล่นสำหรับฐานที่เลือก ดึงสดหรือนำเข้าไฟล์ NBA ได้")


def player_analysis_panel(config, game, season, season_type, as_of, selection, complete):
    with st.expander("สถิติผู้เล่น / นาทีลงสนาม / ผลกระทบต่อทีม"):
        statistics = player_statistics(config, season, season_type, as_of, selection)
        if statistics:
            names = {row["player_id"]: row for row in selection["players"]}
            fields = {
                "gp": "GP",
                "minutes": "MIN",
                "points": "PTS",
                "rebounds": "REB",
                "assists": "AST",
                "steals": "STL",
                "blocks": "BLK",
                "turnovers": "TOV",
                "efg_pct": "eFG%",
                "ts_pct": "TS%",
                "season": "ฤดูกาล",
                "season_type": "ประเภท",
                "different_team": "สถิติจากทีมอื่น",
            }
            display = [
                {
                    "ผู้เล่น": names[key]["name"],
                    "ทีมปัจจุบัน": names[key]["team"],
                    "ลง": names[key]["plays"],
                    **{label: row[field] for field, label in fields.items()},
                }
                for key, row in statistics.items()
            ]
            st.dataframe(
                pd.DataFrame(display),
                hide_index=True,
                column_config={
                    name: st.column_config.NumberColumn(format="percent")
                    for name in ("eFG%", "TS%")
                },
            )
            st.caption(
                "เลือกข้อมูลตาม ID: ฤดูกาล/ประเภทที่เลือก → Regular Season ฤดูกาลก่อน "
                "→ Preseason ปีเดียวกัน; แสดงฤดูกาลและทีมต้นทางของทุกแถว"
            )
        missing = len(selection["players"]) - len(statistics)
        if missing:
            st.info(f"ยังไม่มีสถิติผู้เล่น {missing} คน ณ เวลาทำนาย ไม่แทนสถิติที่ขาดด้วยศูนย์")
        st.caption(
            "PTS/REB/AST และ +/- เป็นสถิติประกอบ ไม่ใช่เรตติ้งผลกระทบส่วนบุคคล "
            "ระบบไม่แปลง box score เป็นค่าฝีมือโดยอัตโนมัติ"
        )
        if not complete:
            st.caption("เลือกตัวจริงให้ครบสองทีมเพื่อแก้นาทีและเรตติ้งผลกระทบ")
            return None
        if not st.checkbox("ใช้เรตติ้งผลกระทบและนาทีที่กำหนดเอง", key="use_player_impacts"):
            return None
        st.caption(
            "นาทีฐานรวม 240 ต่อทีม ประมาณจากสถิติ MIN ของ roster ปัจจุบัน "
            "คนที่ขาดสถิติใช้น้ำหนักเริ่มต้น 12 นาที; ตรวจและแก้ให้ตรงกับชุดฐานของโมเดล "
            "ค่าผลกระทบเป็นแต้มต่อ 100 possessions: เกมรุกบวก=ดี เกมรับบวก=ช่วยลดแต้มคู่แข่ง"
        )
        st.caption(
            "นาทีวันนี้ที่รวมไม่ถึง/เกิน 240 จะถูกปรับสัดส่วนเฉพาะคนที่เลือกลง "
            "โดยจำกัดไม่เกิน 48 นาทีต่อคน ผลคำนวณจะแสดงนาทีที่ใช้จริง"
        )
        rows = rotation_rows(selection, statistics, config)
        key = f"rotation_{game.game_id}_" + "_".join(
            f"{row['player_id']}:{int(row['plays'])}:{int(row['starter'])}" for row in rows
        )
        edited = st.data_editor(
            pd.DataFrame(rows),
            key=key,
            hide_index=True,
            disabled=["player_id", "name", "team", "starter", "plays"],
            column_config={
                "baseline_minutes": st.column_config.NumberColumn(
                    "นาทีในชุดฐาน", min_value=0.0, max_value=48.0
                ),
                "expected_minutes": st.column_config.NumberColumn(
                    "นาทีที่คาดวันนี้", min_value=0.0, max_value=48.0
                ),
                "offense_impact": st.column_config.NumberColumn("ผลกระทบเกมรุก"),
                "defense_impact": st.column_config.NumberColumn("ผลกระทบเกมรับ"),
            },
        )
        source = st.text_input("แหล่งที่มาของเรตติ้งผลกระทบ", key="player_rating_source")
        if not source.strip():
            st.info("ระบุแหล่งเรตติ้งก่อนคำนวณแบบปรับผู้เล่น; ค่าเริ่มต้น 0 หมายถึงยังเป็นกลาง")
            return None
        return rotation_document(
            edited.to_dict(orient="records"), selection, statistics, game, as_of, source
        )
