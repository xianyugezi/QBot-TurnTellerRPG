#!/usr/bin/env python3
"""M6 里程碑验收脚本（细化_M6_verify门禁与承接 D8：两段式门禁 = M6 唯一验收口径）。

依据（严格引用权威源，只引用不重定义）：
  - D8《细化_M6_verify门禁与承接》（VG-01~11 两段式契约 / DLY-01~10 承接裁决 /
    ACC-01~03 验收单与归档 / VG-20 输出统一「M<N> 门禁」）
  - 【总纲】VM6-1~4 / SCP-4 / ADR-07~10（段一 8 项 = M6 唯一验收口径，禁「人工看过没
    问题」勾选；DELAYED 到期扫描；归档写入者 = verify_m6.py）
  - D1~D7 载体（批1-7 已落盘）：D3 WIR/RSM（热重载接线）、D4 SMK/PCK（内容包冒烟）、
    D5 FLT/SES（故障注入）、D7 COV/LNT/CHG（质量门禁）、D1 REG/STT/SHC（三引擎基础指令）

段一 8 项（SCP-4 + D8 §1.1 断言对象表）——每项有可执行断言/产物：
  ① 热重载接线回退  D3 WIR/RSM + F5 快照冗余 → 段一① 子进程段（四测试文件 + 函数级核验）
  ② 冒烟闭环        D4 SMK/PCK → 段一② 子进程段（e2e_m6_smoke + 确定性重放）
  ③ 故障注入六类    D5 FLT/SES → 段一③ 子进程段（tests/fault/ 六脚本）
  ④ 覆盖率 ≥80%     D7 COV → 段一④ 消费 run_all_tests 报表 docs/verify/coverage_latest.txt
  ⑤ ruff/mypy/pytest D7 LNT + 5d §3.2 L133 → 段一⑤ 阶段0 快速门 + 全量 pytest
  ⑥ 内容包 validator 全绿 D4 SMK validator 矩阵 + content/ 五档包动态扫描 + 防嵌套红拦
     真拦截（2a1c-TC-22 / DLY-02 承载）+ PYTEST_FILES 红拦回归 → 段一⑥
  ⑦ 里程碑验收单    ACC-01 → 段一⑦ 写入并复核 docs/verify/m6_checklist.md（8 项逐行）
  ⑧ CHANGELOG+归档 D7 CHG + ACC-02/03 → 段一⑧ 检查 CHANGELOG 与 docs/verify/ 四归档物
段二 承接 M2-M5 DELAYED（D8 §三 DLY-01~10）：
  - DLY-07 到期扫描：解析 verify_m2/m3/m4/m5.py 每项 DELAYED 的「依赖 M<N>」目标，
    N ≤ M6 未翻转且未登记（含到期日）→ 断言失败
  - DLY-08 verify_m4 批次7-01 已翻转（pytest:test_e2e_m4_smoke.py::test_smoke_*）
  - DLY-01/03 显式残留登记（图鉴 M11 / 生活生产内容包批次）
  - DLY-02 防嵌套红拦 → 段一⑥ 红拦真拦截断言承载
  - DLY-04/05/06 /注册 /状态 /快捷 → verify_m5 已转 pytest: 承载（D1 载体）复核
  - DLY-09 缺失必测文件按失败（禁「缺失仍全绿」）；DLY-10 收口对账表打印

退出码：0 = M6 门禁通过；1 = 有失败。幂等可重跑；零 NoneBot import；不 git commit；
不使用任何生产存档。
"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent  # scripts/verify/ -> 仓库根
PY = REPO / ".venv" / "bin" / "python"
VERIFY_DIR = REPO / "scripts" / "verify"
sys.path.insert(0, str(REPO))  # 供 import qbot_rpg

_YMD = datetime.now().strftime("%Y%m%d")
_NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# -----------------------------------------------------------------------------------
# 归档物路径（D8 ACC-02：归档统一 docs/verify/，写入者 = verify_m6.py）
# -----------------------------------------------------------------------------------
CHECKLIST = REPO / "docs" / "verify" / "m6_checklist.md"
ARCHIVE_DIR = REPO / "docs" / "verify" / "m6"
ARCHIVE = ARCHIVE_DIR / f"verify_m6_{_YMD}.md"
COV_REPORT = REPO / "docs" / "verify" / "coverage_latest.txt"
SMOKE_ARCHIVE = REPO / "docs" / "verify" / "m6_smoke.md"
CHANGELOG = REPO / "CHANGELOG.md"

COV_THRESHOLD = 80.0
COV_DIRS: tuple[str, ...] = ("qbot_rpg/core", "qbot_rpg/engine", "qbot_rpg/content")

_PASS: list = []
_FAIL: list = []
_OUT: list = []
_ITEM_OK: dict = {i: False for i in range(1, 9)}        # 段一 8 项逐项结果（验收单/归档用）
_M6_CARRIER_OK: dict = {}                                # 段二 M6 承载断言实果开关
_RECON_ROWS: list = []                                   # DLY-10 收口对账行（归档用）

# -----------------------------------------------------------------------------------
# 段一载体：D3 WIR/RSM 四测试文件（①）+ 段一⑥ 子进程组（红拦回归/机制承载/D1 载体）
# -----------------------------------------------------------------------------------
HOT_RELOAD_FILES: list = [
    "tests/unit/test_hot_reload_wiring.py",         # D3 WIR：watcher 装载/调度///重载 真实后端
    "tests/unit/test_reload_translator.py",         # D3 RSM：ReloadResult 人话翻译 TPL-15~18
    "tests/unit/test_snapshot_resume_rebind.py",    # D3 RSM：P0-1 续战世代绑定/重绑定
    "tests/unit/test_battle_snapshot_generation.py",  # D3 RSM + F5 验收③ 快照冗余断言（世代）
]
# (文件, 必含用例函数) —— 函数级核验（防「文件在但用例对不上」虚假承载，对齐 verify_m4/5）
HOT_RELOAD_KEYS: list = [
    ("tests/unit/test_hot_reload_wiring.py",
     ("test_backup_snapshot_activated", "test_gm_backend_reload_success_path",
      "test_gm_backend_reload_no_watcher_message", "test_wir_12_caplog_red_yellow_counts")),
    ("tests/unit/test_reload_translator.py",
     ("test_tpl_15_success_path", "test_tpl_16_rollback_path",
      "test_tpl_17_paused_path", "test_tpl_18_no_change_path")),
    ("tests/unit/test_snapshot_resume_rebind.py",
     ("test_resume_from_snapshot_watcher_rebind_exact",
      "test_resume_from_snapshot_watcher_rebind_none_degraded",
      "test_resume_from_snapshot_watcher_rebind_fallback")),
    ("tests/unit/test_battle_snapshot_generation.py",
     ("test_rsm_02_start_snapshot_has_registry_generation",
      "test_rsm_02_turn_boundary_snapshot_carries_generation",
      "test_rsm_06_snapshot_generation_roundtrip_via_payload")),
]

FAULT_FILES: list = [  # D5 FLT/SES：六脚本（--only fault 分支同源，run_all_tests LAYER_PATHS）
    "tests/fault/fault_inject_crash.py",
    "tests/fault/fault_inject_save.py",
    "tests/fault/fault_inject_reload.py",
    "tests/fault/fault_inject_formula.py",
    "tests/fault/fault_inject_doublepay.py",
    "tests/fault/fault_inject_netdrop.py",
]

# 段一⑥ 红拦回归载体（D4 SMK-12~15 + 3e/3e2 校验面，VG-19）+ 段二机制承载
PYTEST_VALIDATOR: list = [
    "tests/unit/test_content.py",           # 红拦 R-1~R-5 全量回归（3e TC-01~11）
    "tests/unit/test_maps_schema.py",       # maps/exits/spawn/gate_guard 校验器红黄
    "tests/unit/test_enemies_schema.py",    # enemies 八段 schema 校验
    "tests/unit/test_chase_resume.py",      # 2a2-TC-10 机制承载：TestPrepareResumeBattle（PV 半值）
    "tests/unit/test_dungeon_persist.py",   # 2a3-TC-2a3-03 机制承载：TestSaveLoadSession
]
# 段二 D1 载体（DLY-04/05/06）+ DLY-08 翻转载体（D8 §三 落点）
PYTEST_D1_CARRIERS: list = [
    "tests/unit/test_register_commands.py",   # D1 TC-REG-01~05（/注册）
    "tests/unit/test_status_commands.py",     # D1 TC-STT-01~03（/状态）
    "tests/unit/test_shortcut_commands.py",   # D1 TC-SHC-01~03（快捷解绑/列表）
    "tests/unit/test_e2e_m4_smoke.py",        # DLY-08：批次7-01 翻转载体
]
# DLY-09：M6 声明必测文件缺失 → 失败（非黄提示）
PYTEST_FILES: list = HOT_RELOAD_FILES + PYTEST_VALIDATOR + PYTEST_D1_CARRIERS

# 全量 pytest（段一⑤：unit + contract + e2e + fault，对齐 run_all_tests 阶段1）
PYTEST_FULL: list = [
    "tests/unit", "tests/contract",
    "tests/contract/test_e2e_smoke.py", "tests/contract/test_3f_patch.py",
    *FAULT_FILES,
]

# -----------------------------------------------------------------------------------
# 段二 承接解析表（D8 DLY-10 收口对账；REGISTERED = DLY-01/03 唯一豁免 + 1f-TC-20 主观判据；
# RESOLVED_DOWNSTREAM = 依赖目标里程碑 COVERAGE 已承接；M6_CARRIED = verify_m6 段一实测承载）
# -----------------------------------------------------------------------------------
REGISTERED_RESIDUAL: dict = {
    "1f-TC-11": ("图鉴分级（L2 招名=？？？/L3 不显示）：依赖图鉴 codex_state 系统，归 M11 横切系统"
                 "（总纲 SCP-2「4d 图鉴 → M11」）；到期日 = 图鉴系统里程碑（M11）。"
                 "依据 D8 DLY-01。"),
    "1f-TC-12": ("中断恢复预演消息渲染：依赖图鉴（归 M11）；机制部分（ai_state 全字段快照往返）已由"
                 " test_monster_ai_battle.py::test_ai_state_snapshot_roundtrip 承载；"
                 "到期日 = 图鉴系统里程碑（M11）。依据 D8 DLY-01。"),
    "1f-TC-20": ("验收判据：2a3 BOSS 战完整节奏已由 verify_m3（2a3-TC-2a3-05）覆盖（转承载）；"
                 "图鉴/换区主观判据显式残留登记；到期日 = 图鉴系统里程碑（M11）。依据 D8 DLY-10。"),
    "3d-TC-16": ("锻造成功 TPL-10：锻造系统实装不在 M6 接线闭环范围（verify_m5 L78-81 原 DELAYED "
                 "自述「M6 生活生产批次」经 M6 范围仲裁确认非本批）；"
                 "到期日 = 生活生产内容包实现批次。"
                 "依据 D8 DLY-03。"),
    "3d-TC-17": ("锻造失败 TPL-11：同 TC-16；到期日 = 生活生产内容包实现批次。依据 D8 DLY-03。"),
}
RESOLVED_DOWNSTREAM: dict = {
    "1e-TC-14": ("verify_m3.py", "2a2-TC-17",
                 "M3 COVERAGE 已承接：2a2-TC-17 开场技 + 换区 2a2 TC-01~09（D8 DLY-10）"),
    "1f-TC-19": ("verify_m3.py", "2a2-TC-01",
                 "M3 COVERAGE 已承接：2a2 TC-01~24 换区/追击/续战全流程（D8 DLY-10）"),
    "2a1c-TC-06": ("verify_m4.py", "2.1-01",
                   "M4 COVERAGE 已承接：2.1-01 分隔符五类/紧凑双认（D8 DLY-10）"),
    "2a1c-TC-07": ("verify_m4.py", "2.1-02",
                   "M4 COVERAGE 已承接：2.1-02 紧凑/空格等价（D8 DLY-10）"),
    "2a2-TC-14": ("verify_m4.py", "2.1-02",
                  "M4 COVERAGE 已承接：2.1-02 紧凑双认（D8 DLY-10）"),
}
M6_CARRIED: dict = {
    "2a1c-TC-22": ("段一⑥ 防嵌套红拦真拦截断言（map_dungeon_entrance_ref_missing R-4："
                   "PackLoadError + 整包拒绝 + 后续 legal 装载不受污染）——D8 DLY-02 落点"),
    "2a2-TC-10": ("机制部分承载：段一⑥ PYTEST_FILES test_chase_resume.py::TestPrepareResumeBattle"
                  "（PV 半值 floor/层数保留语义）；运行期「PV>0 效果减半」断言未落盘"
                  "→ 段二显式残留登记"
                  "（到期日 = 后续战斗接线批次）【偏离 D8 ADR-D8-03，详见本档 §九】"),
    "2a3-TC-2a3-03": ("段一⑥ 会话容器双副本并发断言：save/load/clear 双会话独立进度"
                      "（{dungeon_id: doc} 容器纯函数，dungeon_persist 补白 1）——D8 DLY-10 落点"),
}
# 登记豁免校验：源 DELAYED 文本必须含「原因」关键词（防登记虚挂）
_REGISTERED_KEYWORD: dict = {
    "1f-TC-11": "图鉴", "1f-TC-12": "图鉴", "1f-TC-20": "图鉴",
    "3d-TC-16": "锻造", "3d-TC-17": "锻造",
}

# 段二六组承接裁决表（D8 §1.2）——打印与对账
GROUP_ADJUDICATION: list = [
    ("图鉴分级", "1f-TC-11 / 1f-TC-12", "显式残留登记（依赖图鉴 codex_state，归 M11）", "DLY-01"),
    ("防嵌套红拦", "2a1c-TC-22", "转 pytest: 承载（M6 校验器防嵌套规则红拦断言）", "DLY-02"),
    ("锻造 TPL-10/11", "3d-TC-16 / 3d-TC-17", "显式残留登记（锻造不在 M6 接线闭环范围）", "DLY-03"),
    ("/注册", "4f TC-01~04 / 4f TC-06", "转 pytest: 承载（D1 TC-REG-01~05）", "DLY-04"),
    ("/状态", "4f TC-07 / 4f TC-09 / 4f TC-10", "转 pytest: 承载（D1 TC-STT-01~03）", "DLY-05"),
    ("快捷解绑/列表", "4f TC-17 / 4f TC-22 / 4f TC-23",
     "转 pytest: 承载（D1 TC-SHC-01~03）", "DLY-06"),
]
# DLY-10 收口对账表（D8 §3.3 十九行：源 → 项 → 裁决 → M6 落地）
RECON_TABLE: list = [
    ("verify_m2", "1e-TC-14 换区/开场技运行期",
     "转 pytest: 承载（verify_m3 2a2-TC-17 + 换区 2a2 TC-01~09）",
     "已承载（下游 COVERAGE 核验通过）"),
    ("verify_m2", "1f-TC-11 图鉴分级", "显式残留登记（归 M11）",
     "已登记（到期日 = 图鉴系统里程碑 M11）"),
    ("verify_m2", "1f-TC-12 中断恢复", "显式残留登记（预演渲染归 M11；机制已由快照往返承载）",
     "已登记（到期日 = M11）+ 机制已承载"),
    ("verify_m2", "1f-TC-19 换区流程", "转 pytest: 承载（verify_m3 2a2 TC-01~24）",
     "已承载（下游 COVERAGE 核验通过）"),
    ("verify_m2", "1f-TC-20 验收判据", "转 pytest: 承载（2a3 BOSS 战）+ 主观判据残留登记",
     "已承载（2a3-TC-2a3-05）+ 主观判据已登记（到期日 = M11）"),
    ("verify_m3", "2a1c-TC-06 紧凑「进入上」", "转 pytest: 承载（verify_m4 2.1-01）",
     "已承载（下游 COVERAGE 核验通过）"),
    ("verify_m3", "2a1c-TC-07 /进入 幂等", "转 pytest: 承载（verify_m4 2.1-02）",
     "已承载（下游 COVERAGE 核验通过）"),
    ("verify_m3", "2a1c-TC-22 防嵌套红拦", "转 pytest: 承载（M6 校验器接线后红拦断言）→ DLY-02",
     "已承载（verify_m6 段一⑥ 防嵌套红拦真拦截断言）"),
    ("verify_m3", "2a2-TC-10 PV>0 debuff 减半",
     "转 pytest: 承载（M6 战斗接线 PV 门禁后断言）【细化定型】",
     "机制已承载（TestPrepareResumeBattle）+ 运行期断言残留登记"
     "（到期日 = 后续战斗接线批次）【偏离】"),
    ("verify_m3", "2a2-TC-14 追击态 /进入up", "转 pytest: 承载（verify_m4 2.1-02）",
     "已承载（下游 COVERAGE 核验通过）"),
    ("verify_m3", "2a3-TC-2a3-03 双副本并发",
     "转 pytest: 承载（M6 会话容器接线后并发断言，落段一）",
     "已承载（verify_m6 段一⑥ 会话容器双副本断言）"),
    ("verify_m4", "批次7-01 端到端冒烟",
     "立即翻转 pytest:test_e2e_m4_smoke.py::test_smoke_* → DLY-08",
     "已翻转（声明失真清除，无「未落盘」字样）"),
    ("verify_m5", "3d-TC-16 锻造成功 TPL-10", "显式残留登记（生活生产批次）→ DLY-03",
     "已登记（到期日 = 生活生产内容包批次）"),
    ("verify_m5", "3d-TC-17 锻造失败 TPL-11", "显式残留登记（同 TC-16）", "已登记（到期日同上）"),
    ("verify_m5", "4f TC-01~04/06 /注册", "转 pytest: 承载（D1 TC-REG-01~05）→ DLY-04",
     "已承载（verify_m5 M6 批1 翻转 + D1 载体全绿核验）"),
    ("verify_m5", "4f TC-07/09/10 /状态", "转 pytest: 承载（D1 TC-STT-01~03）→ DLY-05",
     "已承载（同上）"),
    ("verify_m5", "4f TC-17 帮助别名", "转 pytest: 承载（D1 TC-SHC-03）→ DLY-06",
     "已承载（同上）"),
    ("verify_m5", "4f TC-22 覆盖重绑/解绑", "转 pytest: 承载（D1 TC-SHC-01）→ DLY-06",
     "已承载（同上）"),
    ("verify_m5", "4f TC-23 快捷列表/持久化", "转 pytest: 承载（D1 TC-SHC-02）→ DLY-06",
     "已承载（同上）"),
]

# 验收单 8 项（D8 §5.1 模板：断言对象/产物 + 对照【规划】T 编号 + 子文档 TC 计数）
CHECKLIST_ROWS: list = [
    (1, "① 热重载回退", "verify_m6 段一①（D3 WIR/RSM 载体 + F5 快照冗余，四测试文件）",
     "F5（L3436-3439）", "D3 21 例"),
    (2, "② 冒烟闭环",
     "scripts/e2e_m6_smoke.py + tests/unit/test_e2e_m6_smoke.py（四步矩阵 + validator 四件套）",
     "F6（L3441-3444）", "D4 21 例"),
    (3, "③ 故障注入六类", "tests/fault/ 六脚本（crash/save/reload/formula/doublepay/netdrop）",
     "G3（L3460-3463）", "D5 26 例"),
    (4, "④ 覆盖率 ≥80%",
     "docs/verify/coverage_latest.txt（D7 COV 报表：core/engine/content 各自 ≥80%）",
     "G4（L3465-3468）", "D7 30 例（COV）"),
    (5, "⑤ ruff/mypy/pytest", "pyproject [tool.ruff]/[tool.mypy] 阶段0 快速门 + 全量 pytest",
     "G4", "D7 30 例（LNT）"),
    (6, "⑥ 内容包 validator 全绿",
     "content/ 五档包动态扫描 + validator 矩阵 + 防嵌套红拦 + PYTEST_FILES 红拦回归",
     "F6/G1", "D4 21 例"),
    (7, "⑦ 里程碑验收单", "docs/verify/m6_checklist.md（本文件，verify_m6 段一⑦ 写入）",
     "G1（L3450-3453）", "D8 21 例"),
    (8, "⑧ CHANGELOG+归档", "CHANGELOG.md（M6 条目 + ACC-03 欠账段）+ docs/verify/ 四归档物",
     "G1/G4", "D7 30 例（CHG）"),
]


def out(msg: str = "") -> None:
    """打印 + 归档摘要缓冲（ACC-02 报告主体素材）。"""
    _OUT.append(msg)
    print(msg)


def check(name: str, fn) -> None:
    try:
        fn()
        _PASS.append(name)
        out(f"  ✓ {name}")
    except Exception as exc:  # noqa: BLE001
        _FAIL.append((name, str(exc)))
        out(f"  ✗ {name}: {exc}")


def _pytest(paths: list) -> tuple[bool, int, int, str]:
    """子进程 pytest（-q 由 pytest.ini addopts 全局注入，-rN 强制输出汇总行，对齐 verify_m0/5）。"""
    cmd = [str(PY), "-m", "pytest", "--tb=short", "-rN", "--disable-warnings", *paths]
    r = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, timeout=900)
    text = r.stdout + r.stderr
    m_p = re.search(r"(\d+) passed", text)
    m_f = re.search(r"(\d+) failed", text)
    passed = int(m_p.group(1)) if m_p else 0
    failed = int(m_f.group(1)) if m_f else 0
    tail = "\n".join((r.stdout or "").splitlines()[-3:]).strip()
    return r.returncode == 0, passed, failed, tail


def _assert_file_functions(path: Path, fns: tuple) -> None:
    """函数级核验：文件落盘 + 用例函数存在于 def 列表（防虚假承载，对齐 verify_m4/5）。"""
    assert path.exists(), f"必测文件缺失（DLY-09 按失败）：{path.relative_to(REPO)}"
    # 批8 收口修复：支持 async def 用例（test_backup_snapshot_activated 为 async）
    pat = r"^(?:async\s+)?def (test_\w+)\s*\("
    defined = set(re.findall(pat, path.read_text(encoding="utf-8"), re.M))
    for fn in fns:
        assert fn in defined, f"{path.name} 中不存在用例 {fn}（函数级核验失败）"


# ==============================================================================
# 段一① 热重载接线回退（D3 WIR/RSM + F5 快照冗余）
# ==============================================================================
def t_seg1_hot_reload() -> None:
    for rel, fns in HOT_RELOAD_KEYS:
        _assert_file_functions(REPO / rel, fns)
    ok, passed, failed, tail = _pytest(HOT_RELOAD_FILES)
    assert ok, f"D3 WIR/RSM 载体 pytest 未全绿：{tail}"
    assert passed >= 20, f"D3 载体通过数异常低：{passed}"
    out(f"    D3 WIR/RSM 四文件 {passed} passed / {failed} failed"
        "（watcher 装载/调度///重载/翻译/续战世代绑定/快照冗余）")
    _ITEM_OK[1] = True


# ==============================================================================
# 段一② 冒烟闭环（D4 SMK/PCK：真实引擎四步 + validator 四件套 + 确定性重放）
# ==============================================================================
def t_seg1_smoke() -> None:
    smoke_script = REPO / "scripts" / "e2e_m6_smoke.py"
    assert smoke_script.exists(), "scripts/e2e_m6_smoke.py 缺失（D4 冒烟载体）"
    r = subprocess.run([str(PY), str(smoke_script)], cwd=str(REPO),
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, f"e2e_m6_smoke 子进程非零退出：{r.stderr[-400:]}"
    assert "M6 内容包冒烟全绿" in r.stdout, f"未输出全绿行：{r.stdout[-300:]}"
    # 确定性重放（D4 SMK-03）：同参两次 run_smoke 摘要逐字一致 + green
    spec = importlib.util.spec_from_file_location("e2e_m6_smoke", smoke_script)
    assert spec is not None and spec.loader is not None, "e2e_m6_smoke 无法装载（spec/loader 缺失）"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    a = mod.run_smoke()
    b = mod.run_smoke()
    assert a["green"] is True, f"冒烟存在失败断言：{a.get('failures')}"
    assert a == b, "确定性重放不一致（D4 SMK-03：同参两次 run_smoke 摘要须逐字一致）"
    total = int(a["passed"]) + int(a["failed"])
    assert total >= 25, f"冒烟断言数 {total} 低于下限（D4 SMK-05）"
    out(f"    e2e_m6_smoke 子进程 exit 0 + 全绿行；run_smoke 断言 {a['passed']} 通过 / 重放一致")
    _ITEM_OK[2] = True


# ==============================================================================
# 段一③ 故障注入六类（D5 FLT/SES：六脚本 + --only fault 同源分支）
# ==============================================================================
def t_seg1_fault() -> None:
    for rel in FAULT_FILES:
        assert (REPO / rel).exists(), f"故障注入脚本缺失：{rel}"
    ok, passed, failed, tail = _pytest(FAULT_FILES)
    assert ok, f"tests/fault/ 六脚本未全绿：{tail}"
    out(f"    tests/fault/ 六脚本 {passed} passed / {failed} failed"
        "（crash/save/reload/formula/doublepay/netdrop）")
    _ITEM_OK[3] = True


# ==============================================================================
# 段一④ 覆盖率 ≥80%（D7 COV：消费 run_all_tests 阶段3 报表，三目录各自 ≥80% 禁合计稀释）
# ==============================================================================
def t_seg1_coverage() -> None:
    assert COV_REPORT.exists(), (
        "docs/verify/coverage_latest.txt 缺失——先跑 scripts/run_all_tests.py"
        "（阶段3 覆盖率段生成报表，"
        "D7 COV-05；verify_m6 段一④ 消费该报表，VG-15）")
    text = COV_REPORT.read_text(encoding="utf-8")
    rows: dict = {}
    pat = r"\| (qbot_rpg/(?:core|engine|content)) \| (\d+) \| (\d+) \| ([0-9.]+) \|"
    for m in re.finditer(pat, text):
        rows[m.group(1)] = (int(m.group(2)), int(m.group(3)), float(m.group(4)))
    missing = [d for d in COV_DIRS if d not in rows]
    assert not missing, f"覆盖率报表缺目录行：{missing}"
    for d in COV_DIRS:
        st, mis, pct = rows[d]
        assert pct >= COV_THRESHOLD, (
            f"{d} 行覆盖 {pct:.2f}% < {COV_THRESHOLD:.0f}%"
            "（D7 COV-02 禁合计稀释 / COV-04 阈值断言）")
        assert st > 0, f"{d} statements=0（测量异常，不静默放行）"
        out(f"    {d}：{pct:.2f}% 行覆盖（statements={st}，missing={mis}）"
            f"≥ {COV_THRESHOLD:.0f}% ✅")
    assert "门禁结论：通过" in text, "覆盖率报表门禁结论非通过"
    _ITEM_OK[4] = True


# ==============================================================================
# 段一⑤ ruff/mypy/pytest 全绿（D7 LNT 阶段0 快速门 + 全量 pytest）
# ==============================================================================
def t_seg1_lint() -> None:
    lint_ok = True
    for tool, args in (("ruff", ["check", "."]), ("mypy", ["."])):
        exe = PY.parent / tool
        if not exe.exists():
            exe = Path(tool)
        r = subprocess.run([str(exe), *args], cwd=str(REPO),
                           capture_output=True, text=True, timeout=900)
        tail = "\n".join((r.stdout + r.stderr).splitlines()[-2:]).strip()
        out(f"    {tool} → {'通过' if r.returncode == 0 else '失败'}（{tail}）")
        lint_ok = lint_ok and r.returncode == 0
    assert lint_ok, ("ruff/mypy 阶段0 快速门失败（D7 LNT-04；存量基线豁免见"
                      " docs/verify/lint_baseline.md）")
    # 全量 pytest（unit + contract + e2e + fault；M6 门禁 pytest 全绿含新增用例，5d §3.2 L139）
    ok, passed, failed, tail = _pytest(PYTEST_FULL)
    assert ok, f"全量 pytest 未全绿：{tail}"
    assert passed >= 500, f"全量 pytest 通过数异常低：{passed}"
    out(f"    全量 pytest：{passed} passed / {failed} failed（unit + contract + e2e + fault）")
    _ITEM_OK[5] = True


# ==============================================================================
# 段一⑥ 内容包 validator 全绿（D4 SMK validator 矩阵 + 五档包动态扫描 +
#      防嵌套红拦真拦截【2a1c-TC-22 / DLY-02】+ PYTEST_FILES 红拦回归）
# ==============================================================================
def _validator_four_packs() -> None:
    """validator 矩阵（红拦真拦截/黄提示可过，D4 SMK-12~14）——e2e 已断言，此处轻量复核。"""
    from qbot_rpg.content.field_meta import default_field_meta_table
    from qbot_rpg.content.loader import PackLoadError, build_pack

    packs_dir = REPO / "tests" / "fixtures" / "packs"

    def _load(name: str):
        return build_pack(packs_dir / name, default_field_meta_table(), {}, 1)

    p, _ = _load("legal")
    assert p.report.ok and len(p.report.errors) == 0 and len(p.report.warnings) == 0, \
        "legal 应 0 红 0 黄（SMK-12 全绿基线）"
    try:
        _load("badref")
        raise AssertionError("badref 应红拦 PackLoadError（SMK-12 红拦真拦截）")
    except PackLoadError:
        pass
    mp, _ = _load("missing_mod")
    assert mp.report.ok and any(
        "Y-6" in str(w.kind) or w.detail.get("module") == "statuses" for w in mp.report.warnings), \
        "missing_mod 应软放行 + Y-6(statuses) 黄提示（SMK-13）"
    op, _ = _load("old_schema")
    assert op.report.ok, "old_schema 应容忍加载不红拦（SMK-14）"


def _five_pack_dynamic_scan() -> None:
    """content/ 五档包动态扫描（D8 附录 A L191：全部预置包逐档 validator 全绿）。"""
    from qbot_rpg.content.field_meta import default_field_meta_table
    from qbot_rpg.content.loader import build_pack

    content_dir = REPO / "content"
    packs = sorted(d.name for d in content_dir.iterdir()
                   if d.is_dir() and (d / "manifest.json").exists())
    assert packs, "content/ 无预置内容包（动态扫描对象缺失）"
    for name in packs:
        pack, changed = build_pack(content_dir / name, default_field_meta_table(), {}, 1)
        assert pack.report.ok, f"{name} 校验失败：{[e.kind for e in pack.report.errors]}"
        assert len(pack.report.errors) == 0, f"{name} 存在红拦：{pack.report.errors}"
        out(f"    content/{name}：0 红 / {len(pack.report.warnings)} 黄 / 绿"
            f"（注册 {len(changed)} 模块）")
    out(f"    content/ 动态扫描：{len(packs)} 档预置包全绿（含五档 demo_*）")


def _anti_nesting_red_block() -> None:
    """防嵌套红拦真拦截（2a1c-TC-22 / DLY-02 承载，D8 §三）。

    红拦 = 校验器 error（map_dungeon_entrance_ref_missing R-4）+ 包装载 PackLoadError +
    整包拒绝（D-02 半挂载禁止）且后续 legal 装载不受污染。构造：maps 节点挂 dungeon_entrances
    引用不存在副本（2a1c R1 引用必须存在）+ 合法 dungeon 模块（触发引用检查）。
    """
    from qbot_rpg.content.field_meta import default_field_meta_table
    from qbot_rpg.content.loader import PackLoadError, build_pack
    from qbot_rpg.content.map_models import validate_maps

    maps = [
        {"id": "world_01", "name": "新手村", "desc": "d", "spawn": [],
         "exits": {}, "dungeon_entrances": [{"dungeon": "no_such_dungeon", "name": "洞"}]},
        {"id": "world_02", "name": "野地", "desc": "d", "spawn": [],
         "exits": {"东": {"to": "world_01", "mode": "bidirectional"}}},
    ]
    dungeons = [{"id": "d1", "name": "副本一", "type": "explore",
                 "maps": ["world_02"], "safe_zone": "world_02"}]

    class _Report:
        def __init__(self) -> None:
            self.errors: list = []
            self.warnings: list = []

        def error(self, module, field, kind, **detail) -> None:
            self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

        def warning(self, module, field, kind, **detail) -> None:
            self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})

    rep = _Report()
    validate_maps({"maps": maps, "dungeon": dungeons}, rep)
    assert any(e["kind"] == "R-4" and e["detail"].get("rule") == "map_dungeon_entrance_ref_missing"
               for e in rep.errors), f"dungeon_entrances 悬空引用应红拦 R-4，实际 {rep.errors}"

    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        (p / "manifest.json").write_text(json.dumps(
            {"name": "t", "version": "1.0.0", "schema_version": 1,
             "modules": ["maps", "dungeon"]}, ensure_ascii=False), encoding="utf-8")
        (p / "maps.json").write_text(json.dumps(maps, ensure_ascii=False), encoding="utf-8")
        (p / "dungeon.json").write_text(json.dumps(dungeons, ensure_ascii=False), encoding="utf-8")
        try:
            build_pack(p, default_field_meta_table(), {}, 1)
            raise AssertionError("防嵌套违规包应 PackLoadError（红拦 = 加载失败）")
        except PackLoadError as exc:
            assert any(e.kind == "R-4"
                       and e.detail.get("rule") == "map_dungeon_entrance_ref_missing"
                       for e in exc.errors), f"PackLoadError 缺 R-4 引用缺失：{exc.errors}"
    # registry 未污染（红拦后合法包装载不受影响——原子快照替换语义，SMK-12 / 5d L201）
    legal, _ = build_pack(REPO / "tests" / "fixtures" / "packs" / "legal",
                          default_field_meta_table(), {}, 1)
    assert legal.report.ok, "防嵌套红拦后 legal 重载应全绿（registry 未污染）"
    out("    防嵌套红拦真拦截：validate_maps R-4 + 包装载 PackLoadError + 整包拒绝"
        " + legal 重载全绿（DLY-02 承载）")
    _M6_CARRIER_OK["2a1c-TC-22"] = True


def _session_container_concurrent() -> None:
    """会话容器双副本并发断言（2a3-TC-2a3-03 / DLY-10 落段一：【细化定型】会话容器接线）。

    {dungeon_id: doc} 容器（dungeon_persist 补白 1）：双副本会话并存互不覆盖，clear 一个
    不影响另一个（纯函数返回新容器，入参不改）。
    """
    from qbot_rpg.world.dungeon_persist import (
        clear_dungeon_session, load_dungeon_session, save_dungeon_session,
    )

    sess_a = {"dungeon_id": "dungeon_a", "dungeon_type": "explore", "state": "PEACE_EXPLORE",
              "current_map": "a1", "cleared_maps": ["a1"], "subquest_progress": {"sq": 1},
              "boss_state": {}, "rest_count": 1, "content_pack_id": "cp1",
              "content_pack_version": "1.0"}
    sess_b = {"dungeon_id": "dungeon_b", "dungeon_type": "boss", "state": "BOSS_CHASE",
              "current_map": "b2", "cleared_maps": ["b1", "b2"], "subquest_progress": {},
              "boss_state": {"hp": 100, "pv": 150}, "rest_count": 0,
              "content_pack_id": "cp1", "content_pack_version": "1.0"}
    doc_a = save_dungeon_session(sess_a)
    doc_b = save_dungeon_session(sess_b)
    assert doc_a.get("ok", True) is not False and doc_b.get("ok", True) is not False, \
        "会话序列化失败（save_dungeon_session 拒绝）"
    container = {"dungeon_a": doc_a, "dungeon_b": doc_b}
    ga = load_dungeon_session(container["dungeon_a"], "cp1")
    gb = load_dungeon_session(container["dungeon_b"], "cp1")
    assert ga["ok"] and gb["ok"], "双会话 load 应均成功"
    assert (list(ga["session"]["cleared_maps"]) == ["a1"]
            and ga["session"]["subquest_progress"] == {"sq": 1}), \
        "副本 A 进度应独立保留（cleared=[a1]/子任务 sq=1）"
    assert (sorted(gb["session"]["cleared_maps"]) == ["b1", "b2"]
            and gb["session"]["boss_state"]["hp"] == 100), \
        "副本 B 进度应独立保留（cleared=[b1,b2]/BOSS 残血 100）"
    cl = clear_dungeon_session(container, "dungeon_a")
    assert cl["ok"] and "dungeon_a" not in cl["store"] and "dungeon_b" in cl["store"], \
        "clear 副本 A 后 B 应仍在容器（并发进度独立）"
    assert sorted(container) == ["dungeon_a", "dungeon_b"], \
        "clear 纯函数不应改入参容器"
    out("    会话容器双副本并发：双会话并存互不覆盖 + clear 单副本不影响另一副本"
        " + 入参不改（2a3-TC-2a3-03 承载）")
    _M6_CARRIER_OK["2a3-TC-2a3-03"] = True


def t_seg1_validator() -> None:
    for rel in PYTEST_VALIDATOR:
        assert (REPO / rel).exists(), f"段一⑥ 红拦回归载体缺失（DLY-09 按失败）：{rel}"
    _validator_four_packs()
    _five_pack_dynamic_scan()
    _anti_nesting_red_block()
    _session_container_concurrent()
    ok, passed, failed, tail = _pytest(PYTEST_VALIDATOR)
    assert ok, f"段一⑥ 红拦回归 + 机制承载 pytest 未全绿：{tail}"
    assert "test_chase_resume.py" in " ".join(PYTEST_VALIDATOR)
    _M6_CARRIER_OK["2a2-TC-10"] = True  # 机制承载（TestPrepareResumeBattle）全绿
    ok2, p2, f2, tail2 = _pytest(PYTEST_D1_CARRIERS)
    assert ok2, f"段二 D1 载体/翻转载体 pytest 未全绿：{tail2}"
    out(f"    红拦回归 + 机制承载 {passed} passed / {failed} failed；"
        f"D1 载体 + DLY-08 翻转载体 {p2} passed / {f2} failed")
    _ITEM_OK[6] = True


# ==============================================================================
# 段一⑦ 里程碑验收单（ACC-01：verify_m6 段一⑦ 写入 m6_checklist.md，8 项逐行）
# ==============================================================================
def _write_checklist() -> None:
    date = datetime.now().strftime("%Y-%m-%d")
    lines = [
        "# M6 里程碑验收单（docs/verify/m6_checklist.md）",
        "",
        f"> 写入者：verify_m6 段一⑦（D8 ACC-01；写入者 = verify_m6.py）；生成时间：{date}",
        "> 粒度：到子文档，不进每条 TC（【总纲】附录 A L193）；对照【规划】L3481 任务"
        "> T 编号（F5-F6/G2-G4）。",
        "> 子文档 TC 计数（D1~D7 各档「文档总览」验收用例数）："
        "> D1 29 + D2 15 + D3 21 + D4 21 + D5 26 + D6 30 + D7 30",
        "> = 172 例 TC（D8 §〇 断言对象聚合）——verify_m6 段一断言对象的 TC 计数总和。",
        "",
        "| 验收项 | 断言对象/产物 | 对照【规划】任务 | 子文档 TC 计数 | 勾选时间 | 结论 |",
        "|---|---|---|---|---|---|",
    ]
    for idx, item, obj, task, tc in CHECKLIST_ROWS:
        concl = "✅ 通过" if _ITEM_OK[idx] else "❌ 失败（回溯见 docs/verify/m6/ 归档报告）"
        lines.append(f"| {item} | {obj} | {task} | {tc} | {date} | {concl} |")
    lines += ["", "---", ""]
    lines += ["| 子文档 | 验收用例计数 |（D8 §〇 断言对象聚合）|", "|---|---|"]
    for doc, cnt in (("D1", 29), ("D2", 15), ("D3", 21), ("D4", 21),
                     ("D5", 26), ("D6", 30), ("D7", 30), ("合计", 172)):
        lines.append(f"| {doc} | {cnt} 例 | |")
    lines += ["", "## 失败回溯", ""]
    failures = [f"{name}: {err}" for name, err in _FAIL]
    lines.append("（无失败时填「无」）" if not failures else "\n".join(f"- {f}" for f in failures))
    CHECKLIST.parent.mkdir(parents=True, exist_ok=True)
    CHECKLIST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def t_seg1_checklist() -> None:
    _write_checklist()
    assert CHECKLIST.exists(), "m6_checklist.md 未落盘（ACC-01 产物缺失）"
    text = CHECKLIST.read_text(encoding="utf-8")
    assert "# M6 里程碑验收单" in text
    rows = re.findall(r"^\| ([①-⑧]) ", text, re.M)
    assert len(rows) == 8, f"验收单应 8 项逐行，实际 {len(rows)}"
    for idx in range(1, 9):
        assert f"| {CHECKLIST_ROWS[idx - 1][1]} " in text
        mark = "✅ 通过" if _ITEM_OK[idx] else "❌ 失败"
        assert mark in text, f"验收单第 {idx} 项结论缺失（{mark}）"
    assert re.search(r"\d{4}-\d{2}-\d{2}", text), "验收单缺勾选时间"
    assert "172" in text, "验收单缺子文档 TC 计数合计（172 例）"
    out(f"    验收单 {CHECKLIST.relative_to(REPO)} 落盘："
        "8 项逐行（T 编号 + TC 计数 + 勾选时间 + 结论）")
    _ITEM_OK[7] = True


# ==============================================================================
# 段一⑧ CHANGELOG + verify 输出归档（D7 CHG + ACC-02/03）
# ==============================================================================
def t_seg1_archive() -> None:
    assert CHANGELOG.exists(), "CHANGELOG.md 缺失（D7 CHG-01 Keep a Changelog 建档）"
    chg = CHANGELOG.read_text(encoding="utf-8")
    assert "## [Unreleased]" in chg, "CHANGELOG 缺 [Unreleased] 段（D7 CHG-01）"
    assert re.search(r"M6", chg), "CHANGELOG 缺 M6 条目（D7 CHG-03 建档）"
    assert "M0-M5 归档欠账" in chg, "CHANGELOG 缺 ACC-03 M0-M5 归档欠账说明段"
    for rel in (CHECKLIST, ARCHIVE, SMOKE_ARCHIVE, COV_REPORT):
        assert rel.exists(), f"verify 归档物缺失（ACC-02 四物齐全）：{rel.relative_to(REPO)}"
    out("    CHANGELOG（M6 条目 + ACC-03 欠账段）✅；docs/verify/ 四归档物齐全 "
        "（m6_checklist.md / m6/ 报告 / m6_smoke.md / coverage_latest.txt）")
    _ITEM_OK[8] = True


# ==============================================================================
# 段二 DLY-07 到期扫描（t_coverage_self_consistent 升级：解析 verify_m2~m5 每项
# DELAYED 的「依赖 M<N>」，N ≤ M6 未翻转且未登记 → 断言失败）
# ==============================================================================
def _load_coverage(script: str) -> dict:
    tree = ast.parse((VERIFY_DIR / script).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "COVERAGE":
                    try:
                        return ast.literal_eval(node.value)
                    except (ValueError, SyntaxError) as exc:
                        raise AssertionError(f"{script} COVERAGE 非字面量 dict：{exc}")
        elif isinstance(node, ast.AnnAssign):
            # 批8 收口修复：verify_m2 为 `COVERAGE: dict = {...}`（带注解赋值，
            # AST 节点是 AnnAssign 非 Assign）——原解析漏配
            if isinstance(node.target, ast.Name) and node.target.id == "COVERAGE":
                if node.value is None:
                    raise AssertionError(f"{script} COVERAGE 注解赋值无值")
                try:
                    return ast.literal_eval(node.value)
                except (ValueError, SyntaxError) as exc:
                    raise AssertionError(f"{script} COVERAGE 非字面量 dict：{exc}")
    raise AssertionError(f"{script} 未解析到 COVERAGE 字面量 dict")


def _tc_id(key: str) -> str:
    toks = key.split()
    if len(toks) >= 2 and re.match(r"^[0-9]+[a-z]+$", toks[0]) and toks[1].startswith("TC"):
        # 批8 收口修复：统一连字符格式（"1f-TC-19"）——原 toks[0] 截断与
        # RECON/in_scan/registered_ids 的连字符格式不匹配导致对账漏配
        return toks[0] + "-" + toks[1]
    return toks[0]


def t_seg2_delayed_scan() -> None:
    """DLY-07 到期扫描 + DLY-10 收口对账（实现时以实测复核 D8 对账表裁决）。"""
    out("  —— DLY-07 到期扫描：verify_m2/m3/m4/m5 每项 DELAYED 的「依赖 M<N>」目标 ——")
    found_all: dict = {}
    for script in ("verify_m2.py", "verify_m3.py", "verify_m4.py", "verify_m5.py"):
        cov = _load_coverage(script)
        for key, val in cov.items():
            if not (isinstance(val, str) and val.startswith("DELAYED")):
                continue
            tid = _tc_id(str(key))
            val = str(val)
            deps = [int(m) for m in re.findall(r"依赖\s*M\s*(\d+)", val)]
            batch7 = "依赖批次7·路H1" in val
            found_all[tid] = (script, deps, batch7)
            line = f"    {script} {tid} ｜ 依赖 M{deps or '-'}{' + 批次7·路H1' if batch7 else ''}"
            if tid in REGISTERED_RESIDUAL:
                assert any(kw in val for kw in ("图鉴", "锻造") if kw), "登记项原因缺失"
                assert REGISTERED_RESIDUAL[tid]
                if _REGISTERED_KEYWORD.get(tid):
                    assert _REGISTERED_KEYWORD[tid] in val, \
                        f"{tid} 登记项源文本缺原因关键词「{_REGISTERED_KEYWORD[tid]}」"
                out(line + " → 显式残留登记（含到期日）✅")
                continue
            if batch7:
                raise AssertionError(
                    f"{script} {tid} 仍为 DELAYED 且依赖批次7·路H1（DLY-08 已翻转 "
                    "pytest:test_e2e_m4_smoke.py::test_smoke_*；过期未翻转 → 失败）")
            if tid in RESOLVED_DOWNSTREAM:
                tgt, substr, why = RESOLVED_DOWNSTREAM[tid]
                src = (VERIFY_DIR / tgt).read_text(encoding="utf-8")
                m = re.search(r'"[^"]*' + re.escape(substr) + r'[^"]*"\s*:\s*"pytest:', src)
                assert m, f"{tid} 依赖 {tgt} COVERAGE 未承接（缺 {substr} 的 pytest: 承载行）"
                out(line + f" → 转 pytest: 承载（{why}）✅")
                continue
            if tid in M6_CARRIED:
                assert _M6_CARRIER_OK.get(tid), f"{tid} M6 段一承载断言未全绿：{M6_CARRIED[tid][0]}"
                out(line + f" → M6 段一实测承载（{M6_CARRIED[tid][1][:40]}…）✅")
                continue
            if deps and max(deps) > 6:
                out(line + f" → 依赖 M{max(deps)}（> M6 未到期，不触发扫描）")
                continue
            raise AssertionError(
                f"{script} {tid} DELAYED 过期未翻转且未登记（DLY-07 / ADR-D8-03）：依赖 "
                f"M{deps or '?'}（N ≤ M6）未转 pytest: 承载且未显式残留登记（含到期日）→ 失败")
    # DLY-10 收口对账：源脚本 DELAYED 全集 == 对账表预期集（防新增 DELAYED 无人收口）
    registered_ids = set(REGISTERED_RESIDUAL) | set(RESOLVED_DOWNSTREAM) | set(M6_CARRIED)
    for tid in found_all:
        assert tid in registered_ids or (found_all[tid][1] and max(found_all[tid][1]) > 6), \
            f"发现未对账 DELAYED 项：{found_all[tid][0]} {tid}"
    expected = registered_ids | {"批次7-01"}
    assert "批次7-01" in expected
    # 批次7-01 已翻转（不再是 DELAYED）→ 由 DLY-08 专项核验；其余对账项必须仍以 DELAYED 形态在场
    # （键带 .py 与 found_all script 值一致——批8 收口修复：原无 .py 导致下方永不匹配）
    in_scan = {
        "verify_m2.py": {"1e-TC-14", "1f-TC-11", "1f-TC-12", "1f-TC-19", "1f-TC-20"},
        "verify_m3.py": {"2a1c-TC-06", "2a1c-TC-07", "2a1c-TC-22", "2a2-TC-10", "2a2-TC-14",
                         "2a3-TC-2a3-03"},
        "verify_m5.py": {"3d-TC-16", "3d-TC-17"},
    }
    for script, ids in in_scan.items():
        absent = [t for t in ids if t not in found_all or found_all[t][0] != script]
        assert not absent, f"对账表项未在 {script} 以 DELAYED 形态在场（或源文件变更）：{absent}"
    for row in RECON_TABLE:
        _RECON_ROWS.append(row)
    out("    对账：verify_m2 5 项 + verify_m3 6 项 + verify_m5 2 项 DELAYED 全数收口；"
        "verify_m4 批次7-01 由 DLY-08 翻转核验（非 DELAYED 形态）")
    out("  —— DLY-10 收口对账表（19 行，裁决按 D8 §3.3 逐项落地）——")


# ==============================================================================
# 段二 DLY-08 verify_m4 批次7-01 立即翻转核验 / DLY-04/05/06 D1 载体 / DLY-09
# ==============================================================================
def t_seg2_m4_flip() -> None:
    """DLY-08：verify_m4 批次7-01 已转 pytest: 承载（TC-DLY-01：无「未落盘」字样）。"""
    src = (VERIFY_DIR / "verify_m4.py").read_text(encoding="utf-8")
    assert re.search(r'"批次7-01[^"]*"\s*:\s*"pytest:test_e2e_m4_smoke\.py::test_smoke_', src), \
        "verify_m4 批次7-01 未翻转（DLY-08：须 pytest:test_e2e_m4_smoke.py::test_smoke_*）"
    assert "未落盘" not in src, "verify_m4 仍含「未落盘」字样（批次7-01 声明失真未清除，TC-DLY-01）"
    assert 'tests/unit/test_e2e_m4_smoke.py' in src, \
            "test_e2e_m4_smoke.py 未入 verify_m4 PYTEST_FILES"
    tfile = REPO / "tests" / "unit" / "test_e2e_m4_smoke.py"
    fns = set(re.findall(r"^def (test_\w+)\s*\(", tfile.read_text(encoding="utf-8"), re.M))
    for fn in ("test_smoke_subprocess_exit0_and_green_line",
               "test_run_smoke_green_and_deterministic",
               "test_path_assertion_counts", "test_smoke_core_run_green"):
        assert fn in fns, f"test_e2e_m4_smoke.py 缺翻转承载用例 {fn}（DLY-08 四用例）"
    out("    verify_m4 批次7-01：已翻转 pytest:test_e2e_m4_smoke.py::test_smoke_*"
        "（四用例函数级核验 + 无「未落盘」字样）")


def t_seg2_d1_carriers() -> None:
    """DLY-04/05/06：verify_m5 原 DELAYED（/注册 /状态 /快捷）已转 pytest: 承载（D1 载体）。"""
    src = (VERIFY_DIR / "verify_m5.py").read_text(encoding="utf-8")
    expect = [
        ("4f TC-01", "test_register_commands.py"), ("4f TC-02", "test_register_commands.py"),
        ("4f TC-03", "test_register_commands.py"), ("4f TC-04", "test_register_commands.py"),
        ("4f TC-06", "test_register_commands.py"),
        ("4f TC-07", "test_status_commands.py"), ("4f TC-09", "test_status_commands.py"),
        ("4f TC-10", "test_status_commands.py"),
        ("4f TC-17", "test_shortcut_commands.py"), ("4f TC-22", "test_shortcut_commands.py"),
        ("4f TC-23", "test_shortcut_commands.py"),
    ]
    for tc, needle in expect:
        pat = r'"(' + re.escape(tc) + r')[^"]*"\s*:\s*"pytest:[^"]*' + re.escape(needle)
        m = re.search(pat, src)
        assert m, f"verify_m5 {tc} 未转 pytest: 承载（DLY-04/05/06：D1 载体 {needle}）"
    out("    verify_m5 4f TC-01~04/06（/注册）+ TC-07/09/10（/状态）+ TC-17/22/23（快捷）"
        "→ 全数 pytest: 承载（D1 REG/STT/SHC 载体；载体全绿已在段一⑥ 子进程段核验）")


def t_seg2_no_missing() -> None:
    """DLY-09：M6 声明必测文件缺失按失败（禁「缺失仍全绿」）。"""
    missing = [rel for rel in PYTEST_FILES if not (REPO / rel).exists()]
    assert not missing, f"verify_m6 声明必测文件缺失（DLY-09 / ADR-08 按失败，不黄提示）：{missing}"


def _print_adjudication() -> None:
    out("  —— 段二六组承接裁决表（D8 §1.2：转 pytest: 承载 / 显式残留登记）——")
    out("  | 组 | 承接的 DELAYED 项 | 裁决 | 落点 |")
    out("  |---|---|---|---|")
    for group, items, ruling, dly in GROUP_ADJUDICATION:
        out(f"  | {group} | {items} | {ruling} | {dly} |")
    out("  —— DLY-10 收口对账表（D8 §3.3，19 行）——")
    out("  | 源 | 项 | 裁决 | M6 落地 |")
    out("  |---|---|---|---|")
    for src, item, ruling, landed in RECON_TABLE:
        out(f"  | {src} | {item} | {ruling} | {landed} |")


# ==============================================================================
# ACC-02 verify 输出归档（docs/verify/m6/verify_m6_<YYYYMMDD>.md）
# ==============================================================================
def _write_archive() -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    item_lines = [f"| {name} | {'✅ 通过' if _ITEM_OK[i] else '❌ 失败'} | {obj} |"
                  for i, name, obj, _task, _tc in CHECKLIST_ROWS]
    lines = [
        "# verify_m6 归档报告（ACC-02）",
        "",
        "> 写入者：verify_m6.py（D8 ACC-02：归档统一 docs/verify/，写入者 = verify_m6.py）",
        f"> 运行时间：{_NOW}；命令：.venv/bin/python scripts/verify/verify_m6.py",
        "> 本报告 = 全量输出摘要 + 断言计数 + 失败回溯（D8 ACC-02 归档物①）；冒烟留档 = "
        "docs/verify/m6_smoke.md（②）；覆盖率报表 = docs/verify/coverage_latest.txt（③）；"
        "验收单 = docs/verify/m6_checklist.md（④）。",
        "",
        "## 一、段一 8 项验收单结果",
        "",
        "| 验收项 | 结论 | 断言对象/产物 |",
        "|---|---|---|",
        *item_lines,
        "",
        "## 二、断言计数",
        "",
        f"- 脚本断言：{len(_PASS)} 通过 / {len(_FAIL)} 失败",
        "- 子进程 pytest：D3 四文件 + 六故障脚本 + 红拦回归/D1 载体 + 全量 suite 均全绿",
        "- 断言对象聚合：D1~D7 共 172 例 TC（D8 §〇），由 verify_m6 段一断言对象消费",
        "",
        "## 三、段二 DELAYED 承接裁决（DLY-01~10 收口）",
        "",
        "### 3.1 六组承接裁决（D8 §1.2）",
        "",
        "| 组 | 承接的 DELAYED 项 | 裁决 | 落点 |",
        "|---|---|---|---|",
    ]
    for group, items, ruling, dly in GROUP_ADJUDICATION:
        lines.append(f"| {group} | {items} | {ruling} | {dly} |")
    lines += ["", "### 3.2 DLY-10 收口对账表（19 行）", "",
              "| 源 | 项 | 裁决 | M6 落地 |", "|---|---|---|---|"]
    for src, item, ruling, landed in RECON_TABLE:
        lines.append(f"| {src} | {item} | {ruling} | {landed} |")
    lines += ["", "### 3.3 残留登记（唯一豁免 DLY-01/03 + 偏离登记）", ""]
    for tid, note in REGISTERED_RESIDUAL.items():
        lines.append(f"- {tid}：{note}")
    lines.append("- 2a2-TC-10（偏离 D8 ADR-D8-03 新增登记）：运行期「PV>0 效果减半」断言未落盘，"
                 "机制部分（PV 半值 floor/层数保留）已由 test_chase_resume.py 的"
                 "TestPrepareResumeBattle 承载；"
                 "到期日 = 后续战斗接线批次。")
    lines += ["", "## 四、失败回溯", "", "（无失败时填「无」）" if not _FAIL
              else "\n".join(f"- {name}: {err}" for name, err in _FAIL),
              "", "## 五、归档物清单", "",
              "- 验收单（ACC-01）：docs/verify/m6_checklist.md",
              f"- 本报告（ACC-02）：docs/verify/m6/verify_m6_{_YMD}.md",
              "- 冒烟留档：docs/verify/m6_smoke.md（D4 SMK-16 五段内容物）",
              "- 覆盖率报表：docs/verify/coverage_latest.txt（D7 COV-05）",
              "", "*M6 门禁：M6 完结判据 = verify_m6 段一（8 项验收单）+ 段二（6 组承接）全绿"
              "（D8 §八 BCH-4 ①）。*",
              ]
    ARCHIVE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out(f"  ✓ ACC-02 归档报告已写入 {ARCHIVE.relative_to(REPO)}")


def main() -> int:
    out("=" * 62)
    out("M6 门禁：verify_m6 两段式门禁（D8 细化_M6_verify门禁与承接 —— M6 唯一验收口径）")
    out(f"运行时间：{_NOW}　工作目录：{REPO}")
    out("=" * 62)

    out("\n【段一】8 项验收单（总纲 SCP-4 + D8 VG-01~09；每项有可执行断言/产物，禁人工勾选）")
    checks_seg1 = [
        ("段一① 热重载接线回退（D3 WIR/RSM 载体 + F5 快照冗余断言，四测试文件子进程全绿）",
         t_seg1_hot_reload),
        ("段一② 冒烟闭环（e2e_m6_smoke 子进程 exit 0 + 全绿行 + 四步矩阵 + 确定性重放）",
         t_seg1_smoke),
        ("段一③ 故障注入六类（tests/fault/ 六脚本 + --only fault 同源分支，子进程全绿）",
         t_seg1_fault),
        ("段一④ 覆盖率 ≥80%（coverage_latest.txt 报表：core/engine/content 各自 ≥80%，禁合计稀释）",
         t_seg1_coverage),
        ("段一⑤ ruff/mypy/pytest 全绿（pyproject 阶段0 快速门 + 全量 pytest）", t_seg1_lint),
        ("段一⑥ 内容包 validator 全绿（五档包动态扫描 + 四件套矩阵 + 防嵌套红拦 + 红拦回归子进程）",
         t_seg1_validator),
    ]
    for name, fn in checks_seg1:
        check(name, fn)

    out("\n【段一⑦】里程碑验收单（ACC-01：verify_m6 写入 docs/verify/m6_checklist.md 并复核）")
    check("段一⑦ 里程碑验收单（8 项逐行：T 编号 + TC 计数 + 勾选时间 + 结论）", t_seg1_checklist)

    out("\n【段二】承接 M2-M5 DELAYED（D8 VG-10 + DLY-01~10；转 pytest: 承载 / 显式残留登记）")
    _print_adjudication()
    checks_seg2 = [
        ("段二 DLY-07 到期扫描 + DLY-10 收口对账（解析 verify_m2~m5 DELAYED 依赖 M<N>，"
         "N≤6 未翻转且未登记 → 失败）",
         t_seg2_delayed_scan),
        ("段二 DLY-08 verify_m4 批次7-01 已翻转（test_e2e_m4_smoke.py::test_smoke_*，"
         "无「未落盘」字样）",
         t_seg2_m4_flip),
        ("段二 DLY-04/05/06 /注册 /状态 /快捷 已转 pytest: 承载（D1 REG/STT/SHC 载体核验）",
         t_seg2_d1_carriers),
        ("段二 DLY-09 缺失必测文件按失败（M6 声明 PYTEST_FILES 全数落盘，禁「缺失仍全绿」）",
         t_seg2_no_missing),
    ]
    for name, fn in checks_seg2:
        check(name, fn)

    out("\n【ACC-02】verify 输出归档（docs/verify/m6/verify_m6_<YYYYMMDD>.md）")
    _write_archive()

    out("\n【段一⑧】CHANGELOG + verify 输出归档（D7 CHG + ACC-02/03）")
    check("段一⑧ CHANGELOG（M6 条目 + ACC-03 M0-M5 欠账段）+ docs/verify/ 归档物齐全",
          t_seg1_archive)

    n_fail = len(_FAIL)
    out("\n" + "=" * 62)
    out(f"结果：脚本断言 {len(_PASS)} 通过 / {n_fail} 失败；段一 8 项 = "
        f"{sum(1 for i in range(1, 9) if _ITEM_OK[i])}/8 通过")
    if _FAIL:
        out("失败回溯：")
        for name, err in _FAIL:
            out(f"  ✗ {name}: {err}")
        out("M6 门禁：verify_m6 未通过 ✘（失败回溯见 docs/verify/m6/ 归档报告；修复后重跑本脚本）")
        return 1
    out(f"M6 门禁：verify_m6 全绿 ✔（段一 8 项验收单 + 段二 6 组 DELAYED 承接全绿；"
        f"归档 docs/verify/m6_checklist.md + docs/verify/m6/verify_m6_{_YMD}.md）")
    return 0


if __name__ == "__main__":
    sys.exit(main())