"""质量门禁纯函数测试（M6 批7A 审查 P1-1 补建：TC-COV-04 假数据双向验证载体）。

依据：
  - 细化_M6_质量门禁（D7）TC-COV-04「阈值断言」：人工喂假覆盖率数据 → 断言 exit≠0/exit 0
  - 批7A 审查 P1-1：_aggregate_cov 抽纯函数后喂假 JSON 双向验证（<80% 拦截 / ≥80% 放行 /
    零语句目录不达标 / 目录缺失）
  - scripts/run_all_tests.py（COV_SOURCES/COV_DIRS/COV_THRESHOLD/_aggregate_cov/_write_coverage_archive）
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
RUN_ALL = REPO / "scripts" / "run_all_tests.py"

_spec = importlib.util.spec_from_file_location("run_all_tests_mod", RUN_ALL)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["run_all_tests_mod"] = _mod
_spec.loader.exec_module(_mod)  # type: ignore[attr-defined]


def _fake_cov(core: float, engine: float, content: float, *, zero_dir: str | None = None) -> dict:
    """构造指定目录百分比的假 coverage json（files 按目录随机摊 statements）。"""
    files: dict[str, dict] = {}
    for d, pct in (("qbot_rpg/core", core), ("qbot_rpg/engine", engine),
                   ("qbot_rpg/content", content)):
        if d == zero_dir:
            continue  # 目录缺失（无文件）
        st = 100
        cv = int(st * pct / 100.0)
        files[f"{d}/fake_mod.py"] = {"summary": {"num_statements": st, "covered_lines": cv}}
    return {"files": files}


def test_aggregate_cov_all_pass():
    """双向验证①：三目录全部 ≥80% → ok=True + percent 正确。"""
    ok, out = _mod._aggregate_cov(_fake_cov(90.0, 85.0, 82.0))
    assert ok is True
    assert out["qbot_rpg/core"]["percent"] == 90.0
    assert out["qbot_rpg/engine"]["percent"] == 85.0
    assert out["qbot_rpg/content"]["percent"] == 82.0


def test_aggregate_cov_below_threshold_blocked():
    """双向验证②：任一目录 <80% → ok=False（79.99% 边界拦截）。"""
    ok, _ = _mod._aggregate_cov(_fake_cov(79.99, 90.0, 85.0))
    assert ok is False
    ok2, _ = _mod._aggregate_cov(_fake_cov(90.0, 80.01, 85.0))  # 80.01% 通过
    assert ok2 is True


def test_aggregate_cov_zero_statement_dir_fails():
    """双向验证③：目录零语句（测量异常）→ ok=False，不静默放行。"""
    ok, out = _mod._aggregate_cov(_fake_cov(90.0, 85.0, 82.0, zero_dir="qbot_rpg/engine"))
    assert ok is False
    assert out["qbot_rpg/engine"]["statements"] == 0
    assert out["qbot_rpg/engine"]["percent"] == 0.0


def test_aggregate_cov_empty_files_fails():
    """双向验证④：files 为空（无测量数据）→ 全部零语句 → ok=False。"""
    ok, _ = _mod._aggregate_cov({"files": {}})
    assert ok is False


def test_write_coverage_archive_shape(tmp_path, monkeypatch):
    """双向验证⑤：归档格式断言（TC-COV-05 形状：表头/三目录行/门禁结论行）。"""
    monkeypatch.setattr(_mod, "COV_ARCHIVE", tmp_path / "coverage_latest.txt")
    ok, cov = _mod._aggregate_cov(_fake_cov(90.0, 85.0, 82.0))
    _mod._write_coverage_archive(ok, cov)
    text = (tmp_path / "coverage_latest.txt").read_text(encoding="utf-8")
    assert "| 目录 | statements | missing | 行覆盖 % | 门禁（≥80%） |" in text
    assert "| qbot_rpg/core | 100 | 10 | 90.00 | ✅ 通过 |" in text
    assert "门禁结论：通过（exit 0）" in text