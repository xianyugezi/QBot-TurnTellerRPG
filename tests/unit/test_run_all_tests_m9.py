"""run_all_tests.py M9 注册断言（M9 批8·路8B 收口）。

依据：
  - docs/m9_batch_plan.md 批8（验收门禁：verify_m9_b2~b7 分批门禁 + verify_m9_smoke
    收口 + run_all_tests 注册 m9；依赖序 b2→b3→b4→b5→b7→smoke）
  - 细化_5d 测试体系总纲 §2.1/§3.2（里程碑 verify 严格依赖序 VG-13 / 未接入不假绿 VG-11）
  - scripts/run_all_tests.py（M9_SCRIPTS / _run_m9_gates）

断言点：
  - M9_SCRIPTS 字典插入序 = b2→b3→b4→b5→b7→smoke（与实现批次顺序一致；批6 联动闭环 =
    verify_m9_smoke 自身，故无独立 b6 条目）
  - 各条目指向 scripts/verify/verify_m9_*.py
  - verify_m9_smoke.py 必须已落盘（批6 交付物）；b2~b7 为 8A 并行交付，允许未落盘
    （VG-11 语义由 _run_m9_gates 按文件存在性裁决）
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUN_ALL = REPO / "scripts" / "run_all_tests.py"

_spec = importlib.util.spec_from_file_location("run_all_tests_m9_mod", RUN_ALL)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["run_all_tests_m9_mod"] = _mod
_spec.loader.exec_module(_mod)

# M9 依赖序（与实现批次顺序一致；批6 = smoke 自身，故无独立 b6 条目）
EXPECTED_ORDER = ["m9_b2", "m9_b3", "m9_b4", "m9_b5", "m9_b7", "m9_smoke"]


def test_m9_scripts_dependency_order():
    """M9_SCRIPTS 字典插入序 = 依赖序 b2→b3→b4→b5→b7→smoke（VG-13 对齐 m0~m6）。"""
    assert list(_mod.M9_SCRIPTS.keys()) == EXPECTED_ORDER


def test_m9_scripts_paths_point_to_verify_dir():
    """各条目路径落在 scripts/verify/verify_m9_*.py（真实可跑，非 None 占位）。"""
    for key, path in _mod.M9_SCRIPTS.items():
        assert path is not None, f"{key} 未接脚本路径"
        assert path.name.startswith("verify_m9_"), path
        assert path.parent.name == "verify", path
        assert str(path).startswith(str(_mod.REPO / "verify")), path


def test_m9_smoke_must_exist():
    """verify_m9_smoke.py 为批6 交付物，必须已落盘（收口核对对象）。"""
    assert _mod.VERIFY_M9_SMOKE.exists(), "verify_m9_smoke.py 缺失（批6 收口未落盘）"


def test_m9_smoke_is_last_in_dependency_order():
    """smoke 为收口门禁：依赖序末位（全链路冒烟须在分批门禁之后）。"""
    assert list(_mod.M9_SCRIPTS)[-1] == "m9_smoke"


def test_run_m9_gates_returns_true_when_all_present(monkeypatch, tmp_path):
    """VG-11 反例：全部脚本存在且 exit 0 → 返回 True（不假绿、不误报）。"""
    calls: list[str] = []

    class _FakeResult:
        returncode = 0

    fake_scripts: dict[str, Path] = {}
    for i, key in enumerate(EXPECTED_ORDER):
        p = tmp_path / f"verify_m9_{key.split('_')[1]}.py"
        p.write_text("", encoding="utf-8")
        fake_scripts[key] = p

    monkeypatch.setattr(_mod, "M9_SCRIPTS", fake_scripts)
    monkeypatch.setattr(_mod, "PY", tmp_path / "python")

    import subprocess

    def fake_run(cmd, cwd=None):
        calls.append(cmd[1])  # 记录脚本路径（cmd[0] = PY 解释器）
        return _FakeResult()

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert _mod._run_m9_gates() is True
    # 严格依赖序执行（调用顺序 = 注册顺序）
    assert calls == [str(p) for p in fake_scripts.values()]
