"""M42 端到端集成冒烟固化（M3 批次8·路W）—— pytest 测试。

依据：
  - 规划_路2a_地图副本.md M42（端到端集成冒烟：探索版 + BOSS 版两路径固定种子可重放；
    验收标准 = 两条副本路径端到端脚本跑通、固定种子可重放、时间/天气在全程各指令处正确取值）
  - m3_shared_contract.md §4（副本流程 S0-S7 + M1-M15 迁移）+ 细化_2a3_副本两型流程 §一
    （整体体验单元：探索版=练习赛 / BOSS 版=正式赛）

两种固化形态：
  ① 子进程跑 scripts/e2e_m3_smoke.py：exit 0 + 输出含「M42 端到端冒烟全绿（探索版 + BOSS 版）」
  ② 直接 import 脚本的 run_smoke()：断言全绿 + 断言数下限 + 确定性重放一致 + 状态迁移链逐字断言

铁律：零 NoneBot import；确定性（固定 now/种子，脚本内常量）；不触碰生产存档。
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

from qbot_rpg.core.dungeon import S0, S1, S2, S3, S4, S5, S7

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "e2e_m3_smoke.py"
GREEN_LINE = "M42 端到端冒烟全绿（探索版 + BOSS 版）"
# 断言数下限（防退化护栏；当前落地 41 探索 + 83 BOSS + 2 运行级 = 126）
MIN_TOTAL_ASSERTIONS = 120
MIN_EXPLORE_ASSERTIONS = 40
MIN_BOSS_ASSERTIONS = 80
# 契约 §4.2 状态迁移链（脚本断言口径）
EXPLORE_STATES = [S0, S1, S1, S5, S7]
BOSS_STATES = [S0, S1, S1, S2, S1, S3, S4, S5, S7]


def _import_script() -> Any:
    """经 importlib 直接加载 scripts/e2e_m3_smoke.py（脚本自带 sys.path 装配 qbot_rpg）。"""
    spec = importlib.util.spec_from_file_location("e2e_m3_smoke", SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_smoke_subprocess_exit0_and_green_line() -> None:
    """子进程形态：独立运行 .venv/bin/python scripts/e2e_m3_smoke.py → exit 0 + 全绿输出。"""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(REPO), capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"exit={proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert GREEN_LINE in proc.stdout, f"缺少全绿输出；stdout:\n{proc.stdout}"


def test_smoke_core_run_green_and_deterministic() -> None:
    """函数形态：run_smoke() 全绿 + 断言数下限 + 确定性重放一致 + 状态迁移链逐字断言。"""
    mod = _import_script()
    result = mod.run_smoke()
    assert result["ok"] is True                       # 1 无失败
    assert result["failed"] == 0                      # 2 失败计数 0
    assert result["replay_identical"] is True         # 3 固定种子两次运行摘要逐字一致
    total = (int(result["runs"]["explore"]["assertions"])
             + int(result["runs"]["boss"]["assertions"])
             + int(result["passed"]))
    assert total >= MIN_TOTAL_ASSERTIONS              # 4 总断言数下限
    assert result["runs"]["explore"]["assertions"] >= MIN_EXPLORE_ASSERTIONS   # 5 探索版断言下限
    assert result["runs"]["boss"]["assertions"] >= MIN_BOSS_ASSERTIONS         # 6 BOSS 版断言下限


def test_smoke_state_migration_chains() -> None:
    """状态迁移链：探索版 S0→S1→S1→S5→S7；BOSS 版 S0→S1→S2→S1→S3→S4→S5→S7（契约 §4.2 M1-M15）。"""
    mod = _import_script()
    result = mod.run_smoke()
    assert result["runs"]["explore"]["states"] == EXPLORE_STATES   # 1 探索版链逐字一致
    assert result["runs"]["boss"]["states"] == BOSS_STATES         # 2 BOSS 版链逐字一致


def test_smoke_time_weather_hooks_sampled_per_step() -> None:
    """全程时间/天气钩子：每条路径每个指令步都有钩子取值（season/period/weather 非空且稳定）。"""
    mod = _import_script()
    result = mod.run_smoke()
    for path_key in ("explore", "boss"):
        trace = result["runs"][path_key]["trace"]
        sampled = [t for t in trace if "map_id" in t]
        assert len(sampled) >= 4                        # 1/2 每路径 ≥4 步带钩子
        assert all(t["season"] and t["period"] and t["weather"]
                   for t in sampled)                    # 3/4 每步钩子值非空
        assert all(t["season"] == "summer" for t in sampled)   # 5/6 固定 now → 季节固定（手算基准：夏）
        assert all(t["period"] == "noon" for t in sampled)     # 7/8 固定 now → 时段固定（手算基准：午）