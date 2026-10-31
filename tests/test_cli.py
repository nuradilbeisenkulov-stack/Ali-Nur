"""Batch behavior and safe error handling using synthetic requests only."""
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys

from scripts.common import InputError, iter_jsonl
import pytest


ROOT = Path(__file__).resolve().parents[1]


def run_predict(input_path, output_path, data_dir):
    return subprocess.run([sys.executable, "-m", "scripts.predict", "--input", str(input_path), "--output", str(output_path), "--data-dir", str(data_dir)], cwd=ROOT, capture_output=True, text=True)


def test_predict_streams_one_result_per_record(tmp_path, data_dir):
    records = [
        {"ticket_id": "synthetic-one", "kind": "report", "messages": [{"role": "player", "text": "Где можно найти водительскую школу?"}]},
        {"kind": "complaint", "messages": []},
    ]
    source = tmp_path / "tickets.jsonl.gz"
    with gzip.open(source, "wt", encoding="utf-8") as stream:
        for row in records:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    target = tmp_path / "pred.jsonl"
    result = run_predict(source, target, data_dir)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in target.read_text().splitlines()]
    assert len(rows) == 2
    assert rows[0]["ticket_id"] == "synthetic-one"
    assert "ticket_id" not in rows[1]
    assert all("draft_reply" in row for row in rows)
    assert os.stat(target).st_mode & 0o077 == 0


def test_malformed_batch_does_not_overwrite_previous_output(tmp_path, data_dir):
    source = tmp_path / "bad.jsonl"
    source.write_text('{"secret":"DO_NOT_LOG_THIS"}\n{bad_json\n')
    target = tmp_path / "pred.jsonl"
    target.write_text("previous result")
    result = run_predict(source, target, data_dir)
    assert result.returncode != 0
    assert target.read_text() == "previous result"
    assert "DO_NOT_LOG_THIS" not in result.stdout + result.stderr
    assert not list(tmp_path.glob(".predict-*.tmp"))


def test_jsonl_reader_rejects_non_object_with_line_number(tmp_path):
    source = tmp_path / "array.jsonl"
    source.write_text("\n[]\n")
    with pytest.raises(InputError, match="2"):
        list(iter_jsonl(source))
