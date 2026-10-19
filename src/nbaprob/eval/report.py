"""Every completed backtest writes its config, data identity, scores and diagnostics."""

import hashlib
import importlib.metadata
import json
import platform
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.stats import norm

from nbaprob.data.store import data_version
from nbaprob.eval.acceptance import assess_v1
from nbaprob.eval.metrics import reliability, summarize


def source_version():
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parents[1]
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def save_experiment(predictions, tables, config, parameters=None) -> Path:
    parameters = parameters or {}
    config_text = yaml.safe_dump(config, sort_keys=True)
    config_hash = hashlib.sha256(config_text.encode()).hexdigest()
    name = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    directory = Path(config["evaluation"]["experiment_directory"]) / name
    directory.mkdir(parents=True, exist_ok=False)
    metrics = summarize(predictions, config)
    acceptance = assess_v1(predictions, tables.metadata, metrics, config)
    evaluation_as_of = (
        pd.Timestamp(parameters["as_of"])
        if parameters.get("as_of")
        else tables.games.results_available_at.max()
    )
    candidates = tables.games[tables.games.results_available_at <= evaluation_as_of]
    if parameters.get("start"):
        candidates = candidates[candidates.date >= pd.Timestamp(parameters["start"])]
    if parameters.get("end"):
        candidates = candidates[candidates.date < pd.Timestamp(parameters["end"])]
    sample = {
        "dataset_games": len(tables.games),
        "dataset_completed_games": int(tables.games.results_available_at.notna().sum()),
        "evaluation_as_of": evaluation_as_of.isoformat(),
        "candidate_games": len(candidates),
        "excluded_warmup_games": len(candidates) - len(predictions),
        "evaluated_games": len(predictions),
        "first_tipoff": pd.to_datetime(predictions.date, utc=True).min().isoformat(),
        "last_tipoff": pd.to_datetime(predictions.date, utc=True).max().isoformat(),
    }
    manifest = {
        "report_schema_version": "2",
        "run_id": name,
        "created_at": datetime.now(UTC).isoformat(),
        "config_hash": config_hash,
        "data_version": data_version(tables),
        "source_hash": source_version(),
        "python": platform.python_version(),
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "scipy", "PyYAML", "pyarrow")
        },
        "data_metadata": tables.metadata,
        "parameters": parameters,
        "sample": sample,
        "evaluation": "chronological prequential walk-forward; no random splits",
        "metrics": metrics,
        "acceptance": acceptance,
    }
    (directory / "config.yaml").write_text(config_text, encoding="utf-8")
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    (directory / "acceptance.json").write_text(
        json.dumps(acceptance, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    predictions.to_csv(directory / "predictions.csv", index=False)
    calibration = reliability(
        predictions.home_win, predictions.p_home_win, config["evaluation"]["calibration_bins"]
    )
    calibration.to_csv(directory / "calibration.csv", index=False)
    q = np.asarray(config["evaluation"]["qq_probabilities"])
    qq = {"probability": q, "normal_quantile": norm.ppf(q)}
    for target in ("margin", "total"):
        residual = predictions[target] - predictions[f"mu_{target}"]
        residual /= predictions[f"sigma_{target}"]
        qq[f"{target}_quantile"] = np.quantile(residual, q)
    pd.DataFrame(qq).to_csv(directory / "residual_qq.csv", index=False)
    synthetic = bool(tables.metadata.get("synthetic", False))
    lines = [
        "# NBA Probability Engine — v1 walk-forward report",
        "",
        "ข้อมูล: **ข้อมูลจำลอง (synthetic)**"
        if synthetic
        else f"ข้อมูล: {tables.metadata.get('source', 'local import')}",
        "",
        f"เกมที่ทดสอบ: {len(predictions)}",
        f"ช่วง tipoff: {sample['first_tipoff']} ถึง {sample['last_tipoff']}",
        f"ตัดออกด้วย warmup: {sample['excluded_warmup_games']} จาก "
        f"{sample['candidate_games']} เกมที่มีผลและผ่านตัวกรองเวลา",
        "",
        "| Model | Log loss ↓ | Δ vs HCA ↓ | Brier ↓ | ECE ↓ | Accuracy |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model, score in metrics["models"].items():
        lines.append(
            f"| {model} | {score['log_loss']:.6f} | "
            f"{score['log_loss_delta_vs_hca_only']:+.6f} | {score['brier']:.6f} | "
            f"{score['ece']:.4f} | {score['accuracy']:.3f} |"
        )
    lines += [
        "",
        "| Distribution | CRPS ↓ | Baseline CRPS | Δ CRPS ↓ | RMSE ↓ | Mean error | 90% coverage |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for target, score in metrics["distributions"].items():
        lines.append(
            f"| {target} | {score['crps']:.4f} | {score['baseline_crps']:.4f} | "
            f"{score['crps_delta_vs_baseline']:+.4f} | {score['rmse']:.4f} | "
            f"{score['mean_error']:.4f} | {score['coverage_90']:.3f} |"
        )
    lines += ["", "| Season | Games | Log loss ↓ | Δ vs HCA ↓ |", "| --- | ---: | ---: | ---: |"]
    for season, score in metrics["by_season"].items():
        lines.append(
            f"| {season} | {score['n_games']} | {score['log_loss']:.6f} | "
            f"{score['log_loss_delta_vs_hca_only']:+.6f} |"
        )
    bootstrap = acceptance["paired_log_loss_bootstrap"]
    interval = (
        "insufficient date blocks"
        if bootstrap["upper"] is None
        else (f"[{bootstrap['lower']:+.6f}, {bootstrap['upper']:+.6f}]")
    )
    lines += [
        "",
        f"เกณฑ์ระบบรุ่น {acceptance['policy_version']}: **{acceptance['status']}**",
        "",
        f"Paired date-block {bootstrap['confidence_level']:.0%} CI ของ Δ log loss vs HCA: "
        f"{interval}; {bootstrap['n_blocks']} blocks",
        "",
        "สถานะนี้ประเมินเกณฑ์โมเดลอัตโนมัติ; การตรวจซอฟต์แวร์และ "
        "locked-holdout protocol แยกตาม SYSTEM_SPEC.md หัวข้อ 8",
        "",
        "| Check | Passed | Observed | Rule |",
        "| --- | --- | --- | --- |",
    ]
    for item in acceptance["checks"]:
        observed = json.dumps(item["observed"], ensure_ascii=False)
        lines.append(
            f"| {item['name']} | {'yes' if item['passed'] else 'no'} | "
            f"{observed} | {item['rule']} |"
        )
    lines += [
        "",
        "ใช้เฉพาะข้อมูลที่เผยแพร่ไม่เกิน as-of ของแต่ละเกม; warmup นับเฉพาะผลที่ทราบแล้ว และ refit จากอดีตเท่านั้น",
        "",
        "ตรวจ calibration.csv และ residual_qq.csv ก่อนสรุปเรื่อง calibration หรือหางแจกแจง",
        "",
        "ยังไม่มีข้อมูลตลาด: ไม่คำนวณ market baseline, market blend หรือ CLV",
        "",
        "ค่าพารามิเตอร์เริ่มต้นยังไม่ได้จูนกับข้อมูล NBA จริง; ผลจำลองไม่ใช่หลักฐานความแม่นยำจริง",
        "",
        f"Config SHA256: `{config_hash}`",
        "",
        f"Data SHA256: `{manifest['data_version']}`",
        "",
    ]
    (directory / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return directory
