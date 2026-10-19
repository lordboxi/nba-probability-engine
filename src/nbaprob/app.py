"""Local Streamlit interface: choose a matchup, select players and compare house quotes."""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from nbaprob.analysis import STARTING_POSITIONS, analyze_forecast
from nbaprob.config import load_config
from nbaprob.data.journal import history, journal_scores, record_outcome, save_forecast
from nbaprob.data.nba_stats import NBAStatsAdapter
from nbaprob.data.schema import utc
from nbaprob.data.snapshots import latest_snapshot, save_snapshot
from nbaprob.data.store import load_tables
from nbaprob.features.build import ReplayEngine
from nbaprob.models.team_snapshot import matchup_forecast


def now():
    return datetime.now(UTC).isoformat()


def nba_panel(config, season, season_type):
    st.subheader("สถิติทีมจาก NBA.com")
    st.caption("ไม่ต้องใส่ API key · ฤดูกาลและประเภทการแข่งขันแยกกัน · เก็บเวลาที่ดึงทุกครั้ง")
    st.markdown(
        "[เปิดตาราง NBA](https://www.nba.com/stats/teams/traditional) · "
        "[ข้อกำหนดการใช้ข้อมูล NBA](https://www.nba.com/termsofuse)"
    )
    adapter_key = "nba_adapter"
    if adapter_key not in st.session_state:
        st.session_state[adapter_key] = NBAStatsAdapter(config)
    adapter = st.session_state[adapter_key]
    previous_year = int(season[:4]) - 1
    previous_season = f"{previous_year}-{(previous_year + 1) % 100:02d}"
    with st.expander(f"ฐานข้อมูลฤดูกาลก่อน {previous_season} สำหรับช่วงเปิดฤดูกาล"):
        st.caption("ใช้ Regular Season ฤดูกาลก่อนเป็นฐาน และลดน้ำหนักเพื่อเผื่อการเปลี่ยนแปลงทีม")
        prior_file = st.file_uploader(
            "นำเข้า NBA JSON/HTML ฤดูกาลก่อน", type=["json", "html"], key="prior_file"
        )
        if st.button("บันทึกฐานฤดูกาลก่อน" if prior_file else "ดึงฐานฤดูกาลก่อน", key="fetch_prior"):
            try:
                imported_prior = None
                if prior_file:
                    content = prior_file.getvalue().decode("utf-8")
                    imported_prior = (
                        content
                        if prior_file.name.lower().endswith(".html")
                        else json.loads(content)
                    )
                saved = save_snapshot(
                    adapter.fetch(
                        "teams", previous_season, "Regular Season", imported_payload=imported_prior
                    ),
                    config,
                )
                st.success(f"บันทึกฐานฤดูกาลก่อน {saved['rows']} ทีมแล้ว กดใช้เวลาปัจจุบันในแท็บวิเคราะห์")
            except (ValueError, OSError, KeyError) as error:
                st.error(str(error))
        prior = latest_snapshot(config, "teams", previous_season, now(), "Regular Season")
        st.caption(
            f"มีฐาน {previous_season} ณ {prior['retrieved_at']}"
            if prior
            else "ยังไม่มีฐานฤดูกาลก่อน: ใช้ค่าลีกเป็นฐานชั่วคราว"
        )
    if st.button("ดึงสถิติทีม", key="fetch_teams"):
        try:
            with st.spinner("กำลังติดต่อ NBA Stats…"):
                saved = save_snapshot(adapter.fetch("teams", season, season_type), config)
            st.success(f"บันทึก {saved['rows']} ทีมแล้ว")
        except (ValueError, OSError, KeyError) as error:
            st.error(str(error))
    imported = st.file_uploader("นำเข้า NBA JSON/HTML ที่บันทึกไว้ (เมื่อดึงสดไม่ได้)", type=["json", "html"])
    if imported is not None and st.button("บันทึกตารางจาก JSON"):
        try:
            value = imported.getvalue().decode("utf-8")
            payload = value if imported.name.lower().endswith(".html") else json.loads(value)
            document = adapter.fetch("teams", season, season_type, imported_payload=payload)
            save_snapshot(document, config)
            st.success("บันทึก snapshot ณ เวลานำเข้าแล้ว")
        except (ValueError, OSError, KeyError) as error:
            st.error(str(error))
    snapshot = latest_snapshot(config, "teams", season, now(), season_type)
    if snapshot is None:
        st.info("ยังไม่มีตารางสำหรับฤดูกาล/ประเภทนี้ ดึงข้อมูลหรือนำเข้า JSON ก่อน")
        return
    st.caption(f"ข้อมูล ณ {snapshot['retrieved_at']} · {season} · {season_type}")
    st.dataframe(
        pd.DataFrame(snapshot["data"]).sort_values("win_pct", ascending=False), hide_index=True
    )
    options = {row["team_id"]: row["team"] for row in snapshot["data"]}
    team_id = st.selectbox("ทีมที่ต้องการรายชื่อผู้เล่น", list(options), format_func=options.get)
    if st.button("ดึงรายชื่อผู้เล่น", key="fetch_roster"):
        try:
            with st.spinner("กำลังดึงรายชื่อ…"):
                document = adapter.fetch("roster", season, team_id=team_id)
                save_snapshot(document, config)
            st.success(f"บันทึก {len(document['data'])} รายชื่อแล้ว")
        except (ValueError, OSError, KeyError) as error:
            st.error(str(error))
    roster = latest_snapshot(config, "roster", season, now(), team_id=team_id)
    if roster:
        st.dataframe(pd.DataFrame(roster["data"]), hide_index=True)


def roster_panel(config, game, season, as_of, *, team_ids=None, synthetic=False):
    st.subheader("เลือกผู้เล่นที่ลงเอง")
    st.caption("เลือกตัวจริงจาก dropdown ให้ครบ 5 ตำแหน่ง แล้วติ๊กตัวสำรองที่ลงสนาม")
    upload = st.file_uploader(
        "รายชื่อจาก CSV (ทางเลือก)",
        type=["csv"],
        help="คอลัมน์ player_id,name,team; team ต้องตรงกับชื่อทีมที่เลือก",
    )
    all_players = []
    if upload is not None:
        frame = pd.read_csv(upload, dtype={"player_id": str})
        if not {"player_id", "name", "team"}.issubset(frame.columns):
            raise ValueError("Roster CSV requires player_id,name,team")
        all_players = frame[["player_id", "name", "team"]].to_dict(orient="records")
    elif synthetic:
        all_players = [
            {"player_id": f"{team}-{index}", "name": f"Demo player {index + 1:02d}", "team": team}
            for team in (game.home_team, game.away_team)
            for index in range(10)
        ]
        st.caption("รายชื่อตัวอย่างเป็นข้อมูลจำลอง")
    elif team_ids is not None:
        for team, team_id in team_ids.items():
            snapshot = latest_snapshot(config, "roster", season, as_of, team_id=team_id)
            if snapshot:
                all_players.extend(
                    {"player_id": row["player_id"], "name": row["name"], "team": team}
                    for row in snapshot["data"]
                )
    selections = []
    columns = st.columns(2)
    complete = True
    for column, team in zip(columns, (game.home_team, game.away_team), strict=True):
        with column:
            roster = [row for row in all_players if row["team"] == team]
            labels = {row["player_id"]: row["name"] for row in roster}
            if len(labels) != len(roster):
                raise ValueError(f"Duplicate player in roster for {team}")
            st.markdown(f"### {team}")
            if not roster:
                st.info(f"{team}: ยังไม่มีรายชื่อ ดึงในแท็บข้อมูล NBA หรือนำเข้า CSV")
                complete = False
                continue
            st.markdown("**ตัวจริง (Starting lineup)**")
            keys = {
                position: f"starter_{game.game_id}_{team}_{position}"
                for position in STARTING_POSITIONS
            }
            # Remove stale choices if an imported/refreshed roster no longer includes a player.
            for key in keys.values():
                if st.session_state.get(key) not in labels:
                    st.session_state[key] = None
            starters = {}
            for position, key in keys.items():
                other_choices = {
                    st.session_state.get(other) for other in keys.values() if other != key
                }
                chosen = st.selectbox(
                    f"{position} — {team}",
                    [None, *(player_id for player_id in labels if player_id not in other_choices)],
                    format_func=lambda player_id, names=labels: names.get(
                        player_id, "— เลือกผู้เล่น —"
                    ),
                    key=key,
                )
                if chosen is not None:
                    starters[chosen] = position
            if len(starters) < 5:
                st.caption(f"เลือกตัวจริงแล้ว {len(starters)}/5 ตำแหน่ง · ล้างตำแหน่งเดิมก่อนย้ายผู้เล่น")
                complete = False
            st.markdown("**ตัวสำรองที่ลงสนาม**")
            active_bench = set()
            for player_id, name in labels.items():
                if player_id not in starters and st.checkbox(
                    name, key=f"bench_{game.game_id}_{team}_{player_id}"
                ):
                    active_bench.add(player_id)
            st.caption(f"ตัวจริง {len(starters)} คน · ตัวสำรองที่ลง {len(active_bench)} คน")
            selections.extend(
                {
                    **row,
                    "plays": row["player_id"] in starters or row["player_id"] in active_bench,
                    "starter": row["player_id"] in starters,
                    "position": starters.get(row["player_id"]),
                }
                for row in roster
            )
    st.caption(
        "การเลือกรายชื่อจะถูกบันทึก; การปรับโอกาสชนะตามผู้เล่นต้องมี impact rating "
        "เพิ่มเติม ชื่อผู้เล่นอย่างเดียวไม่ใช้แทนค่าฝีมือ"
    )
    return {
        "game_id": game.game_id,
        "reported_at": utc(as_of).isoformat(),
        "source": "manual user selection",
        "selection_type": "positioned_lineup",
        "players": selections,
    }, complete


def house_panel(game, as_of):
    st.subheader("เทียบกับ House")
    formats = {
        "ยังไม่เปรียบเทียบ": None,
        "ความน่าจะเป็นที่ตัดค่าน้ำแล้ว (%)": "fair_probability",
        "ความน่าจะเป็นก่อนตัดค่าน้ำ (%)": "implied_probability",
        "Decimal odds": "decimal_odds",
        "American odds": "american_odds",
    }
    selected = st.selectbox("รูปแบบข้อมูล House", list(formats))
    kind = formats[selected]
    if kind is None:
        return None
    market = st.selectbox("ตลาด", ["moneyline", "spread", "total"])
    line = None
    if market != "moneyline":
        line = st.number_input(
            "เส้นราคา (spread ใช้แต้มต่อเจ้าบ้าน)", value=-6.5 if market == "spread" else 228.5, step=0.5
        )
    labels = ("สูง", "ต่ำ") if market == "total" else ("เจ้าบ้าน", "ทีมเยือน")
    columns = st.columns(2)
    values = []
    for column, label, default in zip(columns, labels, (55.0, 45.0), strict=True):
        with column:
            if kind.endswith("probability"):
                values.append(
                    st.number_input(
                        f"{label} (%)", min_value=0.01, max_value=99.99, value=default, step=0.5
                    )
                    / 100
                )
            elif kind == "decimal_odds":
                values.append(
                    st.number_input(f"ราคา {label}", min_value=1.01, value=1.91, step=0.01)
                )
            else:
                values.append(st.number_input(f"ราคา American {label}", value=-110.0, step=5.0))
    quote = {
        "game_id": game.game_id,
        "market": market,
        "line": line,
        "input_type": kind,
        "primary": values[0],
        "secondary": values[1],
        "quoted_at": st.text_input("เวลาของราคา House (มี timezone)", value=utc(as_of).isoformat()),
        "bookmaker": st.text_input("ชื่อ House / แหล่งราคา", value="กรอกด้วยตนเอง"),
        "synthetic": st.checkbox("ราคาตัวอย่างสำหรับทดสอบ (ไม่รวมในสถิติ)", value=False),
    }
    if kind.endswith("probability") and st.checkbox("มีราคา Decimal ที่เสนอจริงด้วย"):
        columns = st.columns(2)
        quote["primary_decimal"] = columns[0].number_input(
            "Decimal ฝั่งแรก", min_value=1.01, value=1.91
        )
        quote["secondary_decimal"] = columns[1].number_input(
            "Decimal ฝั่งที่สอง", min_value=1.01, value=1.91
        )
    st.caption("มีเฉพาะเปอร์เซ็นต์จะเทียบส่วนต่างได้ แต่ต้องมีราคาที่เสนอจริงจึงคำนวณความคุ้มค่าได้")
    return quote


def show_result(result, game):
    st.caption("ค่าด้านล่างมาจากโมเดลทีมอิสระ; probability ที่ผสม House แสดงแยกในตารางถัดไป")
    a, b, c = st.columns(3)
    a.metric(f"โอกาส {game.home_team} ชนะ", f"{result['p_home_win']:.1%}")
    b.metric("Margin เฉลี่ย", f"{result['margin']['mean']:+.1f}")
    c.metric("แต้มรวมเฉลี่ย", f"{result['total']['mean']:.1f}")
    if result["synthetic"]:
        st.info("ผลนี้ใช้ข้อมูลจำลอง")
    st.caption("โมเดลยังไม่ผ่านการยืนยันความแม่นยำด้วย NBA holdout จริง")
    if result.get("roster_selection") and not result["lineup_adjustment_applied"]:
        st.info("บันทึกคนที่ลงแล้ว แต่ยังไม่ได้ปรับคะแนนผู้เล่น เพราะไม่มี impact rating แนบมา")
    if "market_assisted" in result:
        assisted = result["market_assisted"]
        names = {"home": game.home_team, "away": game.away_team, "over": "สูง", "under": "ต่ำ"}
        st.subheader("Probability ช่วงข้อมูลน้อย: โมเดล + House")
        st.caption(
            f"น้ำหนักโมเดล {assisted['model_weight']:.1%} · House {assisted['house_weight']:.1%} · "
            "สูตรเริ่มต้นยังไม่ได้จูนด้วยผลจริง"
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "ฝั่ง": names[row["side"]],
                        "โมเดลอิสระ": row["independent_probability_no_push"],
                        "House ตัดค่าน้ำ": row["house_probability_no_push"],
                        "ค่าผสม House": row["assisted_probability_no_push"],
                    }
                    for row in assisted["sides"]
                ]
            ),
            hide_index=True,
            column_config={
                name: st.column_config.NumberColumn(format="percent")
                for name in ("โมเดลอิสระ", "House ตัดค่าน้ำ", "ค่าผสม House")
            },
        )
        favored = assisted["house_favored_outcome"]
        if assisted["market"] == "moneyline":
            st.write(
                f"House ให้ {names[favored]} มีโอกาสชนะมากกว่า" if favored else "House ให้โอกาสชนะเท่ากัน"
            )
        elif assisted["market"] == "spread":
            handicap = assisted["handicap_favorite"]
            st.write(f"ทีมต่อจากเส้นแต้มต่อ: {names[handicap]}" if handicap else "เส้นแต้มต่อเป็นศูนย์")
            st.caption("เปอร์เซ็นต์ในตารางนี้เป็นโอกาสชนะราคาแต้มต่อ ไม่ใช่โอกาสชนะเกม")
        else:
            st.caption("ตารางนี้เป็นโอกาสสูง/ต่ำตามเส้นที่ระบุ ไม่ได้บอกว่าทีมใดเป็นต่อ")
        st.info(
            "ค่าผสมนี้ใช้ House ที่กำลังเปรียบเทียบเป็นข้อมูล จึงยังใช้ยืนยันว่าได้เปรียบ House เดียวกันไม่ได้; "
            "ทุกค่าคิดเฉพาะกรณีไม่คืนเงิน"
        )
        if assisted["decision"] == "refresh_quote":
            st.warning("ราคา House เก่าแล้ว ควรอัปเดตก่อนใช้ค่าอ้างอิงนี้")
    if "house_comparison" in result:
        comparison = result["house_comparison"]
        side_names = {
            "home": f"{game.home_team} (เจ้าบ้าน)",
            "away": f"{game.away_team} (ทีมเยือน)",
            "over": "สูง",
            "under": "ต่ำ",
        }
        labels = {
            "analytical_candidate": "มีฝั่งผ่านเกณฑ์ราคา (ผลวิเคราะห์ทดลอง)",
            "insufficient_evidence": "ยังไม่เลือกฝั่ง: โมเดลยังไม่ผ่านการยืนยันด้วยข้อมูลจริง",
            "refresh_quote": "ควรอัปเดตราคา House",
            "wait_for_lineup": "ควรรอรายชื่อให้ชัดเจน",
            "comparison_only": "เทียบโอกาสได้ — ยังขาดราคาที่เสนอจริง",
            "no_selection": "ยังไม่เลือกฝั่งใด",
        }
        st.subheader(labels[comparison["decision"]])
        if comparison["candidate"]:
            st.write(f"ฝั่งที่ผ่านเกณฑ์: **{side_names[comparison['candidate']]}**")
        rows = [
            {
                "ฝั่ง": side_names[row["side"]],
                "โมเดล (%)": 100 * row["model_probability_no_push"],
                "House ตัดน้ำ (%)": 100 * row["house_fair_probability"],
                "ส่วนต่าง (จุด %)": 100 * row["probability_edge"],
                "EV ต่อหน่วย": row["expected_value_per_unit"],
                "EV หลังทดสอบเงื่อนไขเข้มขึ้น": row["stress_expected_value_per_unit"],
            }
            for row in comparison["sides"]
        ]
        st.dataframe(
            pd.DataFrame(rows),
            hide_index=True,
            column_config={
                name: st.column_config.NumberColumn(
                    format="%.3f" if name.startswith("EV") else "%.1f"
                )
                for name in rows[0]
                if name != "ฝั่ง"
            },
        )
        st.caption(
            "พิจารณาราคาที่คุ้มค่าและความไม่แน่นอนร่วมกัน ส่วนต่างโอกาสสูงกว่า House อย่างเดียวไม่ได้รับรองผลตอบแทน"
        )
    st.download_button(
        "ดาวน์โหลดผลวิเคราะห์ JSON",
        json.dumps(result, indent=2, ensure_ascii=False),
        file_name="nba_analysis.json",
        mime="application/json",
    )
    with st.expander("รายละเอียดข้อมูลและการคำนวณ"):
        st.json(result)


def readiness_panel(base):
    readiness = base.get("data_readiness")
    if readiness is None:
        return
    st.subheader("ข้อมูลที่ใช้และสิ่งที่ยังขาด")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "ทีม": row["team"],
                    "เกมประเภทนี้": row["games"],
                    "เกมฤดูกาลก่อน": row["previous_season_games"],
                    "เกม Preseason ที่ใช้ตั้งต้น": row["preseason_games"],
                    "น้ำหนักข้อมูลใหม่": row["current_weight"],
                    "น้ำหนัก Preseason ในเรตติ้ง": row["preseason_weight_in_final_rating"],
                }
                for row in readiness["teams"].values()
            ]
        ),
        hide_index=True,
        column_config={
            name: st.column_config.NumberColumn(format="percent")
            for name in ("น้ำหนักข้อมูลใหม่", "น้ำหนัก Preseason ในเรตติ้ง")
        },
    )
    labels = {
        "current_season_stats": "สถิติประเภทการแข่งขันนี้ในฤดูกาลใหม่",
        "previous_season_stats": "ฐาน Regular Season ฤดูกาลก่อน",
        "preseason_stats": "ฐานสถิติ Preseason (ไม่มีหรือไม่ได้เปิดใช้)",
        "player_impact_ratings": "เรตติ้งผลกระทบผู้เล่น",
        "rest_travel_context": "วันพักและการเดินทาง",
        "real_holdout_validation": "การยืนยันความแม่นด้วยข้อมูลจริงที่กันไว้ทดสอบ",
    }
    st.caption("ยังขาด: " + " · ".join(labels[name] for name in readiness["missing"]))
    if readiness["season_type"] == "Preseason":
        st.caption("เกม Preseason ได้รับน้ำหนักลดลง และไม่ถูกนับเป็นเกม Regular Season")
    elif any(row["preseason_games"] > 0 for row in readiness["teams"].values()):
        st.caption(
            "ใช้สถิติ Preseason เป็นฐานน้ำหนักต่ำสำหรับ Regular Season "
            "และลดสัดส่วนลงเมื่อมีเกม Regular Season เพิ่ม; "
            "ราคา House ต้องตรงกับเกม Regular Season ที่เลือก"
        )
    st.caption(
        "เมื่อบันทึก snapshot ที่มีเกมเพิ่ม น้ำหนักข้อมูลใหม่จะเพิ่มตามสูตรเดิม การเก็บข้อมูลยังไม่ใช่การฝึกโมเดลอัตโนมัติ"
    )


def history_panel(config):
    st.subheader("ประวัติคำทำนายและผลจริง")
    forecasts, outcomes = history(config)
    if not forecasts:
        st.info("ยังไม่มีคำทำนายที่บันทึก กดคำนวณในแท็บวิเคราะห์เพื่อเริ่มสะสมข้อมูล")
        return
    rows = [
        {
            "คู่แข่งขัน": f"{row['home_team']} — {row['away_team']}",
            "เวลาทำนาย": row["as_of"],
            "เวลาแข่ง": row["tipoff"],
            "บันทึกผลแล้ว": row["game_id"] in outcomes,
            "รหัส": row["identity"],
        }
        for row in forecasts
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    summary = journal_scores(config)
    st.write(
        f"สะสม {summary['saved_forecasts']} คำทำนาย / {summary['unique_games']} เกม · "
        f"มีผลจริงสำหรับประเมิน {summary['settled_games']} เกม"
    )
    st.caption(
        "ประเมินคำทำนายล่าสุดที่บันทึกจริงก่อนแข่งเพียงครั้งเดียวต่อเกม "
        "ไม่รวมข้อมูลจำลองและการบันทึกย้อนหลัง; เทียบโมเดล/House/ค่าผสมบนเกมชุดเดียวกัน"
    )
    if summary["matched_models"]:
        st.dataframe(
            pd.DataFrame(summary["matched_models"]).T,
            column_config={
                "log_loss": "Log loss (ต่ำดีกว่า)",
                "brier": "Brier (ต่ำดีกว่า)",
                "accuracy": st.column_config.NumberColumn("ทายถูก", format="percent"),
            },
        )
        st.caption(
            f"เกม Moneyline ที่มีข้อมูลครบเทียบกัน: {summary['matched_moneyline_games']} เกม · "
            "ยังเป็นรายงานเบื้องต้น ไม่ใช่การรับรองความได้เปรียบ"
        )
    games = {row["game_id"]: row for row in forecasts if utc(row["tipoff"]) < utc(now())}
    if games:
        with st.form("record_outcome"):
            game_id = st.selectbox(
                "เกมที่จบแล้ว (กรอกเฉพาะสกอร์สุดท้าย)",
                list(games),
                format_func=lambda value: (
                    f"{games[value]['home_team']} — {games[value]['away_team']} | "
                    f"{games[value]['tipoff']}"
                ),
            )
            a, b = st.columns(2)
            home_points = a.number_input("คะแนนเจ้าบ้าน", min_value=0, value=100, step=1)
            away_points = b.number_input("คะแนนทีมเยือน", min_value=0, value=99, step=1)
            if st.form_submit_button("บันทึกผลจริง"):
                record_outcome(config, game_id, home_points, away_points, now())
                st.success("บันทึกผลจริงแล้ว")
                st.rerun()
    st.download_button(
        "ดาวน์โหลดประวัติ JSON",
        json.dumps(
            {
                "forecasts": [{**row, "payload": json.loads(row["payload"])} for row in forecasts],
                "outcomes": outcomes,
                "scores": summary,
            },
            ensure_ascii=False,
            indent=2,
        ),
        file_name="nba_prediction_history.json",
        mime="application/json",
    )


def main():
    st.set_page_config(page_title="NBA Probability Engine", layout="wide")
    st.title("NBA Probability Engine")
    st.caption("เลือกคู่แข่ง • เลือกคนลงเอง • เทียบโอกาสกับ House")
    config = load_config(os.environ.get("NBA_CONFIG", "config/default.yaml"))
    year = datetime.now(UTC).year - (datetime.now(UTC).month < 7)
    current_season = f"{year}-{(year + 1) % 100:02d}"
    previous_year = year - 1
    has_nba = any(
        latest_snapshot(config, "teams", candidate, now(), kind) is not None
        for candidate, kind in (
            (current_season, "Preseason"),
            (current_season, "Regular Season"),
            (f"{previous_year}-{year % 100:02d}", "Regular Season"),
        )
    )
    source = st.sidebar.selectbox(
        "แหล่งข้อมูลคู่แข่งขัน", ["ข้อมูลในโปรเจกต์", "ตาราง NBA"], index=1 if has_nba else 0
    )
    season = st.sidebar.text_input("ฤดูกาล NBA", value=current_season)
    season_type = st.sidebar.selectbox(
        "ประเภทการแข่งขัน", ["Preseason", "Regular Season", "Playoffs"], index=1
    )
    analysis_tab, nba_tab, journal_tab = st.tabs(["วิเคราะห์คู่แข่งขัน", "ข้อมูล NBA", "ประวัติและผลจริง"])
    with journal_tab:
        history_panel(config)
    with nba_tab:
        nba_panel(config, season, season_type)
    with analysis_tab:
        synthetic, team_ids = False, None
        if source == "ข้อมูลในโปรเจกต์":
            if not Path(config["data"]["database"]).is_file():
                st.info("ยังไม่มีข้อมูลในโปรเจกต์ เรียก uv run nbaprob demo หรือเลือกตาราง NBA")
                return
            tables = load_tables(config["data"]["database"])
            pending = tables.games[tables.games.home_pts.isna()]
            games = (
                pending if not pending.empty else tables.games.sort_values("date", ascending=False)
            )
            labels = {
                row.game_id: f"{row.home_team} — {row.away_team} | {row.date}"
                for row in games.itertuples()
            }
            game_id = st.selectbox("คู่แข่งขัน", list(labels), format_func=labels.get)
            row = games[games.game_id == game_id].iloc[0]
            as_of = utc(
                st.text_input(
                    "เวลาทำนาย (มี timezone)",
                    value=(row.date - pd.Timedelta(hours=1)).isoformat(),
                    key=f"project_asof_{game_id}",
                )
            )
            engine = ReplayEngine(tables, config)
            base = engine.predict(game_id, as_of)
            game = engine.games[game_id]
            synthetic = bool(tables.metadata.get("synthetic", False))
            season = f"{game.season}-{(game.season + 1) % 100:02d}"
        else:
            st.caption("กำหนดคู่แข่งขันและเวลาเองสำหรับการวิเคราะห์ คู่ที่เลือกยังไม่ได้ตรวจเทียบกับตารางแข่งจริง")
            as_of = utc(st.text_input("เวลาทำนาย (มี timezone)", value=now(), key="nba_asof"))
            if st.button("ใช้เวลาปัจจุบัน"):
                st.session_state["nba_asof_next"] = now()
                st.rerun()
            snapshot = latest_snapshot(config, "teams", season, as_of, season_type)
            previous_year = int(season[:4]) - 1
            previous_season = f"{previous_year}-{(previous_year + 1) % 100:02d}"
            previous = latest_snapshot(config, "teams", previous_season, as_of, "Regular Season")
            preseason = latest_snapshot(config, "teams", season, as_of, "Preseason")
            catalog = snapshot or previous or preseason
            if catalog is None:
                st.info("ยังไม่มีรายชื่อทีม ดึง/นำเข้าตาราง NBA ปัจจุบันหรือฤดูกาลก่อน แล้วกดใช้เวลาปัจจุบัน")
                return
            if snapshot is None:
                st.info(
                    "ยังไม่มีสถิติประเภทนี้ในฤดูกาลใหม่ ใช้ฐานฤดูกาลก่อน/Preseason เมื่อมี หรือค่าลีกชั่วคราว "
                    "และสามารถเพิ่ม House เป็นข้อมูลอ้างอิงได้"
                )
            options = {row["team_id"]: row["team"] for row in catalog["data"]}
            left, right = st.columns(2)
            home = left.selectbox("เจ้าบ้าน", list(options), format_func=options.get)
            away = right.selectbox(
                "ทีมเยือน", list(options), index=min(1, len(options) - 1), format_func=options.get
            )
            tipoff = st.text_input(
                "เวลาเริ่มแข่ง (มี timezone)", value=(as_of + pd.Timedelta(hours=4)).isoformat()
            )
            use_preseason = season_type == "Regular Season" and st.checkbox(
                "ใช้สถิติ Preseason ช่วยตั้งต้น Regular Season",
                value=preseason is not None,
                disabled=preseason is None,
            )
            game, base = matchup_forecast(
                snapshot,
                home,
                away,
                tipoff,
                as_of,
                config,
                previous_snapshot=previous,
                preseason_snapshot=preseason if use_preseason else None,
                season=season,
                season_type=season_type,
                team_catalog=catalog["data"],
            )
            team_ids = {game.home_team: home, game.away_team: away}
            st.caption(
                f"วิเคราะห์ {season} · {season_type} · "
                "pace/efficiency เป็นค่าประมาณจากตาราง Traditional"
            )
        readiness_panel(base)
        selection, selection_ready = roster_panel(
            config, game, season, as_of, team_ids=team_ids, synthetic=synthetic
        )
        with st.expander("ทางเลือกขั้นสูง: impact ratings / ผู้เล่นไม่แน่ใจ"):
            impact = st.file_uploader(
                "Lineup scenario JSON (ไม่บังคับ)", type=["json"], key="impact_json"
            )
        house = house_panel(game, as_of)
        use_market_prior = False
        if house is not None and "data_readiness" in base:
            use_market_prior = st.checkbox("ใช้ House ช่วยประเมินช่วงข้อมูลน้อย", value=True)
        team_only = False
        if not selection_ready and impact is None:
            team_only = st.checkbox("วิเคราะห์ระดับทีมโดยยังไม่ระบุตัวจริง", value=False)
        if not selection_ready and impact is None and not team_only:
            st.info("เลือกตัวจริงให้ครบทั้งสองทีมก่อนคำนวณ")
        if st.button(
            "คำนวณและเปรียบเทียบ",
            type="primary",
            disabled=not selection_ready and impact is None and not team_only,
        ):
            lineup = json.loads(impact.getvalue()) if impact is not None else None
            if lineup is not None:
                lineup.setdefault("game_id", game.game_id)
            result = analyze_forecast(
                base,
                game,
                as_of,
                config,
                lineup=lineup,
                selection=selection if lineup is None and selection_ready else None,
                house=house,
                synthetic=synthetic,
                use_market_prior=use_market_prior,
            )
            identity = save_forecast(result, game, config)
            st.session_state["pending_analysis"] = (result, game, identity)
            st.rerun()
        if "pending_analysis" in st.session_state:
            result, result_game, identity = st.session_state.pop("pending_analysis")
            st.success(f"บันทึกคำทำนายและข้อมูล ณ เวลานี้แล้ว · {identity[:12]}")
            show_result(result, result_game)


if __name__ == "__main__":
    if "nba_asof_next" in st.session_state:
        st.session_state["nba_asof"] = st.session_state.pop("nba_asof_next")
    try:
        main()
    except (ValueError, OSError, KeyError, pd.errors.ParserError) as error:
        st.error(str(error))
