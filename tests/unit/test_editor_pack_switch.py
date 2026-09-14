"""编辑器重写批7 · 换包零改动验收（验收脚本纳入测试）。

依据：
  · docs/编辑器重写_需求与约束.md 第〇节：编辑器 = 通用工具，判断标准
    「把当前内容包换成另一个内容包，编辑器零改动可用」；
  · docs/编辑器重写_实现方案.md §四 批7：全量回归 + 实机抽查（多包切换）+ 文档定稿。

本文件把 `scripts/editor_verify_packs.py`（可重复执行的只读验收脚本）纳入回归：
  A. 真实包全 PASS：脚本对 content/ 下**动态发现**的每个包调用六个只读 API，
     断言结构完整、字段可渲染、兜底不崩；
  B. 合成兜底探针全 PASS：临时目录合成包覆盖未知键 / 缺模块文件 / 非法层级声明；
  C. 反向对照（断言不是空转）：坏字段 / 分组计数不符 / 不存在的包都能被检出；
  D. 只读护栏：跑完验收后 content/ 逐字节未变；
  E. 通用性护栏：脚本不写死任何真实包名 / 业务模块字段名；
  F. CLI 契约：`--json` 纯 JSON、退出码 0、表格含全部包名。

写盘/内容包只读；不触碰仓库 content/（合成探针只写 tempfile）。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

import pytest

from qbot_rpg.web import api

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import editor_verify_packs as evp  # noqa: E402

CONTENT = _REPO / "content"
SCRIPT = _REPO / "scripts" / "editor_verify_packs.py"

# 内容包专属业务字段/模块名反面清单（与批5.1 同一约定：通用框架不得写死业务名）。
BANNED_BUSINESS = (
    "steps", "variant_override", "trigger_skill", "consume_marks", "post_state",
    "skill_chains", "veinborn", "test_demo",
)


def _flatten(nodes: List[dict]) -> List[dict]:
    out: List[dict] = []
    for n in nodes:
        out.append(n)
        out.extend(_flatten(n.get("children", [])))
    return out


def _snapshot(root: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


@pytest.fixture(scope="module")
def reports() -> List[evp.PackReport]:
    return evp.run_verification(root=CONTENT)


# =====================================================================================
# A. 真实包全 PASS
# =====================================================================================
def test_real_pack_reports_all_pass(reports: List[evp.PackReport]) -> None:
    real = [r for r in reports if r.source == "真实"]
    discovered = set(evp._discover_packs(root=CONTENT))
    assert {r.pack for r in real} == discovered
    assert real, "content/ 下未发现任何内容包"
    for r in real:
        assert r.result == "PASS", (r.pack, r.errors)
        assert r.errors == []
        assert r.modules > 0 and r.entries > 0 and r.fields > 0, r.pack


def test_report_counts_cross_check_api(reports: List[evp.PackReport]) -> None:
    """报告里的模块数 / 条目数独立复核：与只读 API 现算一致。"""
    by_pack = {r.pack: r for r in reports}
    for pid in evp._discover_packs(root=CONTENT):
        mods = api.list_modules(pid, root=CONTENT)
        assert by_pack[pid].modules == len(_flatten(mods["modules"]))
        assert by_pack[pid].entries == api.entry_index(pid, root=CONTENT)["total"]


# =====================================================================================
# B. 合成兜底探针
# =====================================================================================
def test_synthetic_fallback_probes_all_pass(reports: List[evp.PackReport]) -> None:
    synth = [r for r in reports if r.source == "合成"]
    assert len(synth) >= 2, "缺少合成兜底探针"
    for r in synth:
        assert r.result == "PASS", (r.pack, r.errors)
    # 未知/缺元数据键确实走到了兜底路径（产生告警），不是被跳过。
    assert any(r.warnings > 0 for r in synth)


# =====================================================================================
# C. 反向对照：断言不是空转
# =====================================================================================
def test_checker_detects_unrenderable_field() -> None:
    rep = evp.PackReport(pack="probe")
    warns = evp._Warnings()
    evp._check_descriptor(rep, warns, {
        "key": "k", "label": "k", "type": "str", "widget": "bogus",
        "control": "nope", "group": "g", "present": True, "help_card": {},
    }, "m/e", {"g"})
    assert any("不可渲染" in e for e in rep.errors)
    assert any("未知 control" in e for e in rep.errors)


def test_checker_detects_missing_group_and_mismatch() -> None:
    rep = evp.PackReport(pack="probe")
    warns = evp._Warnings()
    evp._check_descriptor(rep, warns, {
        "key": "k", "label": "k", "type": "str", "widget": "text",
        "control": "text", "group": "", "present": True, "help_card": {},
    }, "m/e", None)
    assert any("分组缺失" in e for e in rep.errors)
    evp._check_groups(rep, [{"name": "a", "label": "a", "count": 2}], 3, set(), "m/e")
    assert any("!= 字段数" in e for e in rep.errors)
    evp._check_descriptor(rep, warns, {
        "key": "k", "label": "k", "type": "str", "widget": "text",
        "control": "text", "group": "ghost", "present": True, "help_card": {},
    }, "m/e", {"a"})
    assert any("不在 groups 声明内" in e for e in rep.errors)


def test_verify_unknown_pack_fails_gracefully() -> None:
    r = evp.verify_pack("zz_no_such_pack_at_all", root=CONTENT)
    assert r.result == "FAIL"
    assert r.errors and "list_packs" in r.errors[0]


# =====================================================================================
# D. 只读护栏：验收跑完 content/ 逐字节未变
# =====================================================================================
def test_verification_does_not_touch_real_content() -> None:
    before = _snapshot(CONTENT)
    evp.run_verification(root=CONTENT)
    assert _snapshot(CONTENT) == before


# =====================================================================================
# E. 通用性护栏：脚本不写死真实包名 / 业务字段名
# =====================================================================================
def test_script_hardcodes_no_pack_or_business_name() -> None:
    src = SCRIPT.read_text(encoding="utf-8")
    for pid in evp._discover_packs(root=CONTENT):
        assert f'"{pid}"' not in src, f"脚本写死了内容包名：{pid}"
    for name in BANNED_BUSINESS:
        assert f'"{name}"' not in src, f"脚本写死了业务名：{name}"


# =====================================================================================
# F. CLI 契约
# =====================================================================================
def test_cli_exit_zero_and_table_lists_every_pack() -> None:
    proc = subprocess.run([sys.executable, str(SCRIPT)], cwd=str(_REPO),
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "全包 PASS" in proc.stdout
    for pid in evp._discover_packs(root=CONTENT):
        assert pid in proc.stdout


def test_cli_json_is_pure_and_all_pass() -> None:
    proc = subprocess.run([sys.executable, str(SCRIPT), "--json"], cwd=str(_REPO),
                          capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)  # 纯 JSON：多余人类摘要会解析失败
    assert len(data) >= len(evp._discover_packs(root=CONTENT))
    assert all(row["result"] == "PASS" for row in data)
    assert {row["pack"] for row in data} >= set(evp._discover_packs(root=CONTENT))
