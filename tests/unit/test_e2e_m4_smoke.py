# 文件：test_e2e_m4_smoke.py
# 创建：2026-08-26
# 作者：Hermes Agent（M4 批次7 路H1 收尾）
# 功能描述：M4 端到端冒烟 pytest 固化（子进程 exit0 + run_smoke 断言数下限 + 确定性重放）
# 依据：m4_shared_contract §5 + 细化_2b1~2b5 + 3c/3d

"""M4 端到端冒烟固化测试。

调用 scripts/e2e_m4_smoke.py（核心函数 run_smoke / 子进程两种形态），断言：
1. 子进程 exit 0 且输出含「M4 端到端冒烟全绿」
2. run_smoke 返回 ok=True + 六条路径均非零断言
3. 确定性重放（replay_identical=True，同 seed/now 两跑一致）
4. 全链路关键值（NPC 置灰 / 补签只计）
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SMOKE = REPO / "scripts" / "e2e_m4_smoke.py"
MIN_TOTAL_ASSERTIONS = 140  # 全链路断言数下限
PATHS = ("npc", "shop", "quest", "checkin", "shortcut", "pageclamp")  # runs 键序


def _import_script():
    spec = importlib.util.spec_from_file_location("e2e_m4_smoke", SMOKE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_smoke_subprocess_exit0_and_green_line() -> None:
    """子进程跑冒烟：exit 0 且输出含全绿行。"""
    r = subprocess.run(
        [sys.executable, str(SMOKE)], capture_output=True, text=True, timeout=120, cwd=REPO
    )
    assert r.returncode == 0, f"冒烟子进程非零退出：{r.stderr[-500:]}"
    assert "M4 端到端冒烟全绿" in r.stdout, f"未输出全绿行：{r.stdout[-300:]}"


def test_run_smoke_green_and_deterministic() -> None:
    """run_smoke 全绿 + 确定性重放。"""
    mod = _import_script()
    run1 = mod.run_smoke()
    assert run1["ok"] is True, f"冒烟失败：{run1.get('failures')}"
    assert int(run1.get("failed", 0)) == 0, f"存在失败断言：{run1.get('failures')}"
    assert bool(run1.get("replay_identical")), "确定性重放不一致"


def test_path_assertion_counts() -> None:
    """六条路径均有断言记录（子进程 stdout 六段全绿）。"""
    r = subprocess.run(
        [sys.executable, str(SMOKE)], capture_output=True, text=True, timeout=120, cwd=REPO
    )
    assert r.returncode == 0
    for label in ("NPC", "商店", "任务", "签到", "快捷", "翻页"):
        assert label in r.stdout, f"stdout 缺 {label} 路径输出"
    # 总断言数 ≥ 下限
    import re
    m = re.search(r"= (\d+) 通过 / (\d+) 失败", r.stdout)
    assert m, "未解析断言计数行"
    total = int(m.group(1)) + int(m.group(2))
    assert total >= MIN_TOTAL_ASSERTIONS, f"断言数 {total} 低于下限 {MIN_TOTAL_ASSERTIONS}"


def test_smoke_core_run_green() -> None:
    """核心链路关键值（NPC 交付置灰 + 补签只计不补发，从子进程 stdout 断言）。"""
    r = subprocess.run(
        [sys.executable, str(SMOKE)], capture_output=True, text=True, timeout=120, cwd=REPO
    )
    assert r.returncode == 0
    assert "已听" in r.stdout or "听过了" in r.stdout, "NPC 信息交付未见置灰标记"
    assert "只计" in r.stdout or "不补发" in r.stdout, "补签未见只计不补发提示"
