from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml


def _run(project_root: Path, env: dict[str, str], *args: str):
    return subprocess.run(
        [sys.executable, "-m", "video_to_notes", *args],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
    )


def _lecture() -> dict:
    return {
        "schema_version": "1.0",
        "stage": "completion_draft",
        "metadata": {},
        "overview": {},
        "sections": [{"id": "sec_01", "title": "方法", "blocks": []}],
        "problems": [],
        "supplements": [],
        "figures": [],
        "summary": [],
        "review": {"issues": []},
    }


def _seed_workspace(ws: Path) -> None:
    (ws / "lecture").mkdir(parents=True, exist_ok=True)
    (ws / "evidence").mkdir(parents=True, exist_ok=True)
    (ws / "lecture" / "lecture.json").write_text(
        json.dumps(_lecture(), ensure_ascii=False), encoding="utf-8"
    )
    (ws / "evidence" / "timeline.json").write_text(
        '{"timeline": []}', encoding="utf-8"
    )


def _canonical_result(ws: Path) -> tuple[dict, dict]:
    lecture = json.loads((ws / "lecture" / "lecture.json").read_text(encoding="utf-8"))
    repair = lecture["review"]["pedagogical_repair"]
    publication = {
        "sections": lecture["sections"],
        "problems": lecture["problems"],
        "supplements": lecture["supplements"],
        "summary": lecture["summary"],
    }
    business = {
        "models": repair["models"],
        "max_rounds": repair["max_rounds"],
        "rounds": repair["rounds"],
        "status": repair["status"],
        "resolved": repair["resolved"],
        "unresolved": repair["unresolved"],
        "unresolved_issue_ids": repair["unresolved_issue_ids"],
        "complete_with_unresolved": repair["complete_with_unresolved"],
    }
    return publication, business


def test_api_and_codex_share_same_two_round_repair_business_result(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake-video")

    ped_payload = {
        "issues": [{
            "target_id": "sec_01",
            "severity": "info",
            "label": "clarity",
            "message": "增加方法归纳。",
            "source_value": None,
            "review_value": None,
        }]
    }
    round1_payload = {
        "repairs": [{
            "issue_id": "pg_001",
            "target_id": "sec_01",
            "status": "unresolved",
            "action": "keep",
            "content": "",
        }]
    }
    round2_payload = {
        "repairs": [{
            "issue_id": "pg_001",
            "target_id": "sec_01",
            "status": "resolved",
            "action": "append_summary",
            "content": "方法归纳：先识别条件，再组织推导。",
        }]
    }

    ped_file = tmp_path / "pedagogical.json"
    r1_file = tmp_path / "repair1.json"
    r2_file = tmp_path / "repair2.json"
    ped_file.write_text(json.dumps(ped_payload, ensure_ascii=False), encoding="utf-8")
    r1_file.write_text(json.dumps(round1_payload, ensure_ascii=False), encoding="utf-8")
    r2_file.write_text(json.dumps(round2_payload, ensure_ascii=False), encoding="utf-8")

    # API transport.
    api_root = tmp_path / "api_workspace"
    api_config = tmp_path / "api.yaml"
    api_config.write_text(yaml.safe_dump({
        "project": {"workspace_root": str(api_root), "project_root": str(project_root)},
        "review": {
            "factual": {"enabled": False},
            "math": {"enabled": False},
            "pedagogical": {
                "enabled": True,
                "whole_lecture": True,
                "llm": {"provider": "file", "response_files": [str(ped_file)]},
                "repair": {
                    "enabled": True,
                    "llm": {"provider": "file", "response_files": [str(r1_file), str(r2_file)]},
                },
            },
        },
    }, allow_unicode=True), encoding="utf-8")
    result = _run(project_root, env, "--config", str(api_config), "init", str(video))
    assert result.returncode == 0, result.stderr
    api_ws = api_root / "lesson"
    _seed_workspace(api_ws)
    result = _run(project_root, env, "--config", str(api_config), "review", "api", str(video))
    assert result.returncode == 0, result.stderr

    # Codex handoff transport with the exact same business payloads.
    codex_root = tmp_path / "codex_workspace"
    codex_config = tmp_path / "codex.yaml"
    codex_config.write_text(yaml.safe_dump({
        "project": {"workspace_root": str(codex_root), "project_root": str(project_root)},
        "llm": {"mode": "codex_handoff"},
        "review": {
            "factual": {"enabled": False},
            "math": {"enabled": False},
            "pedagogical": {"enabled": True, "whole_lecture": True, "repair": {"enabled": True}},
        },
    }, allow_unicode=True), encoding="utf-8")
    result = _run(project_root, env, "--config", str(codex_config), "init", str(video))
    assert result.returncode == 0, result.stderr
    codex_ws = codex_root / "lesson"
    _seed_workspace(codex_ws)
    tasks = codex_ws / "tasks" / "review"
    responses = codex_ws / "responses" / "review"
    responses.mkdir(parents=True, exist_ok=True)

    result = _run(project_root, env, "--config", str(codex_config), "review", "prepare", str(video))
    assert result.returncode == 0, result.stderr
    req = json.loads((tasks / "pedagogical.request.json").read_text(encoding="utf-8"))
    (responses / "pedagogical.json").write_text(
        json.dumps({"request_id": req["request_id"], **ped_payload}, ensure_ascii=False),
        encoding="utf-8",
    )

    for round_index, payload in ((1, round1_payload), (2, round2_payload)):
        result = _run(project_root, env, "--config", str(codex_config), "review", "prepare", str(video))
        assert result.returncode == 0, result.stderr
        name = f"ped_repair_r{round_index}_sec_01"
        req = json.loads((tasks / f"{name}.request.json").read_text(encoding="utf-8"))
        (responses / f"{name}.json").write_text(
            json.dumps({"request_id": req["request_id"], **payload}, ensure_ascii=False),
            encoding="utf-8",
        )

    result = _run(project_root, env, "--config", str(codex_config), "review", "prepare", str(video))
    assert result.returncode == 0, result.stderr
    manifest = json.loads((tasks / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["phase"] == "ready"
    result = _run(project_root, env, "--config", str(codex_config), "review", "apply", str(video))
    assert result.returncode == 0, result.stderr

    assert _canonical_result(api_ws) == _canonical_result(codex_ws)


def test_codex_invalid_current_response_consumes_round_and_escalates(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake-video")
    root = tmp_path / "workspace"
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({
        "project": {"workspace_root": str(root), "project_root": str(project_root)},
        "llm": {"mode": "codex_handoff"},
        "review": {
            "factual": {"enabled": False},
            "math": {"enabled": False},
            "pedagogical": {"enabled": True, "whole_lecture": True, "repair": {"enabled": True}},
        },
    }, allow_unicode=True), encoding="utf-8")
    result = _run(project_root, env, "--config", str(config), "init", str(video))
    assert result.returncode == 0, result.stderr
    ws = root / "lesson"
    _seed_workspace(ws)
    tasks = ws / "tasks" / "review"
    responses = ws / "responses" / "review"
    responses.mkdir(parents=True, exist_ok=True)

    result = _run(project_root, env, "--config", str(config), "review", "prepare", str(video))
    assert result.returncode == 0, result.stderr
    ped_req = json.loads((tasks / "pedagogical.request.json").read_text(encoding="utf-8"))
    (responses / "pedagogical.json").write_text(json.dumps({
        "request_id": ped_req["request_id"],
        "issues": [{
            "target_id": "sec_01", "severity": "info", "label": "clarity",
            "message": "增加方法归纳。", "source_value": None, "review_value": None,
        }],
    }, ensure_ascii=False), encoding="utf-8")

    result = _run(project_root, env, "--config", str(config), "review", "prepare", str(video))
    assert result.returncode == 0, result.stderr
    r1_req = json.loads((tasks / "ped_repair_r1_sec_01.request.json").read_text(encoding="utf-8"))
    # Current request_id but schema-invalid model payload: business INVALID, not transport/stale.
    (responses / "ped_repair_r1_sec_01.json").write_text(json.dumps({
        "request_id": r1_req["request_id"],
        "repairs": "invalid",
    }), encoding="utf-8")

    result = _run(project_root, env, "--config", str(config), "review", "prepare", str(video))
    assert result.returncode == 0, result.stderr
    manifest = json.loads((tasks / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["phase"] == "pedagogical_repair_2"
    assert "ped_repair_r1_sec_01.json" in manifest["pedagogical_repair_invalid_outputs"]
    r2_req = json.loads((tasks / "ped_repair_r2_sec_01.request.json").read_text(encoding="utf-8"))
    assert r2_req["required_model"] == "sol-medium"
    (responses / "ped_repair_r2_sec_01.json").write_text(json.dumps({
        "request_id": r2_req["request_id"],
        "repairs": [{
            "issue_id": "pg_001", "target_id": "sec_01", "status": "resolved",
            "action": "append_summary", "content": "方法归纳：第二轮完成。",
        }],
    }, ensure_ascii=False), encoding="utf-8")

    result = _run(project_root, env, "--config", str(config), "review", "prepare", str(video))
    assert result.returncode == 0, result.stderr
    manifest = json.loads((tasks / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["phase"] == "ready"
    result = _run(project_root, env, "--config", str(config), "review", "apply", str(video))
    assert result.returncode == 0, result.stderr
    reviewed = json.loads((ws / "lecture" / "lecture.json").read_text(encoding="utf-8"))
    rounds = reviewed["review"]["pedagogical_repair"]["rounds"]
    assert rounds[0]["status"] == "invalid"
    assert rounds[1]["status"] == "resolved"
    assert reviewed["summary"][0]["content"] == "方法归纳：第二轮完成。"


def test_api_invalid_model_response_consumes_business_round(tmp_path):
    project_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root / "src")
    video = tmp_path / "lesson.mp4"
    video.write_bytes(b"fake-video")
    root = tmp_path / "workspace"

    ped = tmp_path / "ped.json"
    invalid = tmp_path / "invalid.json"
    resolved = tmp_path / "resolved.json"
    ped.write_text(json.dumps({
        "issues": [{
            "target_id": "sec_01", "severity": "info", "label": "clarity",
            "message": "增加方法归纳。", "source_value": None, "review_value": None,
        }]
    }, ensure_ascii=False), encoding="utf-8")
    invalid.write_text(json.dumps({"repairs": "invalid"}), encoding="utf-8")
    resolved.write_text(json.dumps({
        "repairs": [{
            "issue_id": "pg_001", "target_id": "sec_01", "status": "resolved",
            "action": "append_summary", "content": "API 第二轮完成。",
        }]
    }, ensure_ascii=False), encoding="utf-8")

    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({
        "project": {"workspace_root": str(root), "project_root": str(project_root)},
        "review": {
            "factual": {"enabled": False},
            "math": {"enabled": False},
            "pedagogical": {
                "enabled": True,
                "whole_lecture": True,
                "llm": {"provider": "file", "response_files": [str(ped)]},
                "repair": {
                    "enabled": True,
                    "llm": {"provider": "file", "response_files": [str(invalid), str(resolved)]},
                },
            },
        },
    }, allow_unicode=True), encoding="utf-8")
    result = _run(project_root, env, "--config", str(config), "init", str(video))
    assert result.returncode == 0, result.stderr
    ws = root / "lesson"
    _seed_workspace(ws)
    result = _run(project_root, env, "--config", str(config), "review", "api", str(video))
    assert result.returncode == 0, result.stderr
    reviewed = json.loads((ws / "lecture" / "lecture.json").read_text(encoding="utf-8"))
    rounds = reviewed["review"]["pedagogical_repair"]["rounds"]
    assert rounds[0]["status"] == "invalid"
    assert rounds[1]["status"] == "resolved"
    assert reviewed["summary"][0]["content"] == "API 第二轮完成。"
