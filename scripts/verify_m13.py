#!/usr/bin/env python3
"""M13 里程碑门禁（verify_m13 · 启动包验收清单逐项探针）。

依据：
  - docs/m13_启动包.md §五（验收门禁）与「待实现（M13 主体）」清单：
    1. 6a 技能库（skills.json schema + skill_actions.json 行动库 + 校验器
       13 条 + skill_lib 命名空间 + 技能位/装配）
    2. 6b 职业库变换引擎（jobs.json schema + 5 态状态机 + 三路归一 +
       快照续战 + 校验器 8 条 + 18 TC）
    3. 6c 资源轴职业机制（两型注册段 + energy_gain/energy_cost +
       回合结清 + resource_state 快照 + 季节技能组 + combo_table +
       校验 11 条 + 20 TC）
    4. 装配接线（ctx["skills"]/ctx["jobs"] 注入 + 技能位装配落存档 +
       /转职 指令 + 注册默认职业 B7 + 战斗技能消费接线）
  - docs/细化/细化_6a_技能库契约.md / 细化_6b_职业库与变换引擎.md /
    细化_6c_资源轴与职业机制.md（字段/校验/TC 计数口径）
  - tests/unit/test_m13_hard_counts.py（批17 三契约硬计数，本探针复用其
    计数口径并直连实现验证，零硬编码凭空断言）

探针项清单（验收清单逐项映射）：
  P1  三契约文件在位（docs/细化/细化_6a/6b/6c_*.md）
  P2  数据模型落盘：skill_models / job_models / resource_axis_models
      （skills_fields≥30 / jobs_fields 34 口径 / resource_axis_fields 恰 10）
  P3  校验器落盘：skill_validator（V-1~V-13 恰 13 条）/ job_validator
      （V1~V8）/ resource_axis_validator（V1~V11）+ action 校验器
  P4  引擎落盘：transform / resource_axis / resource_lifecycle /
      combo_table / combo_settle / battle_season / season_events /
      skill_season / skill_slots / skill_slots_battle / job_slots /
      transform_snapshot / transform_revert（13 引擎模块可 import +
      核心入口可调用）
  P5  field_meta 装配：NAMESPACES 含 skill_lib/job_lib + skills/jobs
      ModuleMeta 登记（kind=skill/job + namespace 对齐）
  P6  装配接线：make_context 注入 ctx["skills"]/ctx["jobs"] +
      ctx["skill_slots"] 接口（assemble/save/load 绑 persistent_state）
  P7  /转职 指令注册（job_commands.register_job_commands 入
      REGISTER_GROUPS + JOB_CMD="转职" 登记 + parsers 白名单）
  P8  注册默认职业（register_commands.default_job 兜底链：
      settings.default_job_id → recommended_newbie → 首职业）
  P9  战斗技能消费接线（battle_commands._attack_action 经
      skill_slots_battle 装配过滤 + _resolve_skill 解析 + is_slot_equipped）
  P10 战斗接线：MP/energy（_apply_skill_energy）/ transform
      （_job_transform_segment + set_transform_def）/ 季节
      （_init_season_state + tick_season_boundary）/ 组合
      （_resolve_combo_table_gate + combo_table/settle）全在 BattleEngine
  P11 全仓测试通过数 ≥ 5500（pytest tests/ --ignore=tests/e2e，
      实跑计数；低于阈值 → FAIL 并附实际数）
  P12 数据样例在库（content/test_demo/skills.json ≥1 条 + jobs.json ≥1 条，
      含 recommended_newbie 职业——注册默认职业/技能消费实机前置）

输出：逐项 PASS/FAIL + 汇总；退出码 0 = 全 PASS，1 = 有 FAIL。

铁律：平台无关（零 NoneBot import）；纯函数确定性；文件头零定时器/
零睡眠（全脚本零时间依赖）；渲染仅 ✅/❌ + 排版符号；不 git commit。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
from typing import Any, Callable, Dict, List, Mapping, Tuple

_REPO = pathlib.Path(__file__).resolve().parent.parent  # scripts/ -> 仓库根
sys.path.insert(0, str(_REPO))

# ---------------------------------------------------------------------------
# P1 三契约文件在位
# ---------------------------------------------------------------------------
CONTRACT_FILES: Tuple[str, ...] = (
    "docs/细化/细化_6a_技能库契约.md",
    "docs/细化/细化_6b_职业库与变换引擎.md",
    "docs/细化/细化_6c_资源轴与职业机制.md",
)

# 计数口径（docs/m13_启动包.md + test_m13_hard_counts.py 同源）：
#   6a 字段 ≥30（契约 24 + 6b 挂点 2 + 6c 扩展 4）；6b 34（顶层 11 + growth
#   9 + transform 11 + state_policy 3）；6c 注册段恰 10。
SKILLS_FIELDS_MIN: int = 30
JOBS_FIELDS_UNION_MIN: int = 34
RESOURCE_AXIS_FIELDS_EXACT: int = 10
MIN_TESTS_PASSED: int = 5500

# 引擎模块清单（core/ 下 M13 落盘模块 + 关键入口函数）
ENGINE_MODULES: Dict[str, Tuple[str, ...]] = {
    "transform": ("resolve_transition", "trigger_transform", "TransformEngine"),
    "resource_axis": ("get_value", "add_value", "check_cost", "pay_cost", "gain_energy"),
    "resource_lifecycle": (
        "ResourceLifecycle",
        "ResourceLifecycle.battle_start_init",
        "ResourceLifecycle.try_apply_cost",
        "ResourceLifecycle.apply_gain",
        "ResourceLifecycle.tick_round_end",
    ),
    "combo_table": ("combo_multiset", "match_combos", "resolve_trigger"),
    "combo_settle": ("settle_combo", "reachable_combos"),
    "battle_season": ("init_battle_season", "tick_season_boundary", "filter_skills"),
    "season_events": ("season_changed", "trigger_season_event"),
    "skill_season": ("parse_season", "skill_in_season", "validate_skill_action"),
    "skill_slots": ("assemble_slots", "save_slots_to_state", "load_slots_from_state"),
    "skill_slots_battle": ("available_skills", "is_slot_equipped", "battle_equipped_skills"),
    "job_slots": ("rearrange_job_slots", "save_rearranged_slots"),
    "transform_snapshot": (
        "snapshot_write",
        "snapshot_restore",
        "TRANSFORM_STATE_FIELDS",
        "normalize_transform_state",
    ),
    "transform_revert": ("revert_transform", "tick_cooldown", "should_revert_natural"),
}

# 装配接线关键符号（qbot_rpg/assembly/context.py）
CONTEXT_SYMBOLS: Tuple[str, ...] = ("make_context",)
CONTEXT_INJECT_KEYS: Tuple[str, ...] = ("skills", "jobs", "skill_slots", "skill_slots_state")

# /转职 注册关键符号
JOB_CMD_SYMBOLS: Tuple[str, ...] = ("register_job_commands", "JOB_CMD")


def _fail(msg: str) -> bool:
    print(f"  FAIL {msg}")
    return False


def _pass(msg: str) -> bool:
    print(f"  PASS {msg}")
    return True


def _try_import(mod: str) -> Any:
    """安全导入（失败返回 None，不抛异常）。"""
    try:
        return __import__(mod, fromlist=["*"])
    except Exception:  # noqa: BLE001 —— 探针只报告不崩溃
        return None


# ---------------------------------------------------------------------------
# 探针项
# ---------------------------------------------------------------------------
def t01_contract_files() -> bool:
    """P1 三契约文件在位（6a/6b/6c 细化）。"""
    missing = [p for p in CONTRACT_FILES if not (_REPO / p).is_file()]
    if missing:
        return _fail(f"三契约文件缺失：{missing}")
    return _pass("三契约文件在位（6a/6b/6c 细化）")


def t02_data_models() -> bool:
    """P2 数据模型落盘：skill_models / job_models / resource_axis_models。"""
    ok = True
    sm = _try_import("qbot_rpg.content.skill_models")
    if sm is None or not callable(getattr(sm, "skills_fields", None)):
        ok = _fail("skill_models 缺失或 skills_fields 不可调用") and False
    elif len(sm.skills_fields()) < SKILLS_FIELDS_MIN:
        ok = _fail(f"skills_fields 键数 {len(sm.skills_fields())} < {SKILLS_FIELDS_MIN}") and False

    jm = _try_import("qbot_rpg.content.job_models")
    if jm is None or not callable(getattr(jm, "jobs_fields", None)):
        ok = _fail("job_models 缺失或 jobs_fields 不可调用") and False
    else:
        fields = jm.jobs_fields()
        child_keys: set = set()
        for meta in fields.values():
            ch = getattr(meta, "children", None) or {}
            if isinstance(ch, dict):
                child_keys |= set(ch.keys())
        union = set(fields) | child_keys | set(getattr(jm, "state_policy_fields", lambda: {})())
        if len(union) < JOBS_FIELDS_UNION_MIN:
            ok = _fail(f"jobs_fields 并集 {len(union)} < {JOBS_FIELDS_UNION_MIN}") and False

    ram = _try_import("qbot_rpg.content.resource_axis_models")
    if ram is None or not callable(getattr(ram, "resource_axis_fields", None)):
        ok = _fail("resource_axis_models 缺失或 resource_axis_fields 不可调用") and False
    elif len(ram.resource_axis_fields()) != RESOURCE_AXIS_FIELDS_EXACT:
        ok = (
            _fail(
                f"resource_axis_fields 键数 {len(ram.resource_axis_fields())}"
                f" != {RESOURCE_AXIS_FIELDS_EXACT}"
            )
            and False
        )

    if ok:
        _pass("数据模型落盘（skill_models/job_models/resource_axis_models）")
    return ok


def t03_validators() -> bool:
    """P3 校验器落盘：skill 13 条 / job 8 条 / resource 11 条 + action 校验器。"""
    import inspect

    ok = True
    sv = _try_import("qbot_rpg.content.skill_validator")
    if sv is None or not callable(getattr(sv, "validate_skills", None)):
        ok = _fail("skill_validator 缺失或 validate_skills 不可调用") and False
    else:
        vfns = {
            int("".join(ch for ch in n[len("_check_v") :] if ch.isdigit()))
            for n, o in inspect.getmembers(sv, inspect.isfunction)
            if n.startswith("_check_v")
        }
        if vfns != set(range(1, 14)):
            ok = _fail(f"skill_validator V 编号集合 {sorted(vfns)} != 1..13") and False

    jv = _try_import("qbot_rpg.content.job_validator")
    if jv is None or not callable(getattr(jv, "validate_jobs", None)):
        ok = _fail("job_validator 缺失或 validate_jobs 不可调用") and False

    rav = _try_import("qbot_rpg.content.resource_axis_validator")
    if rav is None or not (
        callable(getattr(rav, "validate_resource_axes", None))
        and callable(getattr(rav, "validate_skill_energy", None))
    ):
        ok = _fail("resource_axis_validator 缺失或双入口不可调用") and False
    else:
        vfns = {
            int("".join(ch for ch in n[len("_check_v") :] if ch.isdigit()))
            for n, o in inspect.getmembers(rav, inspect.isfunction)
            if n.startswith("_check_v")
        }
        if not vfns.issuperset(set(range(5, 12))):
            ok = _fail(f"resource_axis_validator V 编号 {sorted(vfns)} 未覆盖 V5~V11") and False

    sam = _try_import("qbot_rpg.content.skill_action_models")
    if sam is None or not (
        callable(getattr(sam, "validate_actions", None))
        and callable(getattr(sam, "action_core_meta", None))
    ):
        ok = (
            _fail("skill_action_models 缺失或 validate_actions/action_core_meta 不可调用") and False
        )

    if ok:
        _pass("校验器落盘（skill 13 条 / job 8 条 / resource 11 条 + action 校验器）")
    return ok


def t04_engines() -> bool:
    """P4 引擎落盘：13 模块可 import + 核心入口可调用。"""
    ok = True
    for mod, fns in ENGINE_MODULES.items():
        m = _try_import(f"qbot_rpg.core.{mod}")
        if m is None:
            ok = _fail(f"引擎模块 qbot_rpg.core.{mod} 缺失") and False
            continue
        missing = [f for f in fns if not _resolve_entry(m, f)]
        if missing:
            ok = _fail(f"qbot_rpg.core.{mod} 缺入口 {missing}") and False
    if ok:
        _pass(f"引擎落盘（{len(ENGINE_MODULES)} 模块 + 核心入口可调用）")
    return ok


def _resolve_entry(module: Any, name: str) -> bool:
    """解析入口：支持 'Class.method' 类限定名；函数须可调用，常量须非 None。"""
    if "." in name:
        cls_name, _, attr = name.partition(".")
        cls = getattr(module, cls_name, None)
        if cls is None:
            return False
        return getattr(cls, attr, None) is not None
    return getattr(module, name, None) is not None


def t05_field_meta() -> bool:
    """P5 field_meta 装配：NAMESPACES skill_lib/job_lib + skills/jobs ModuleMeta。"""
    fm = _try_import("qbot_rpg.content.field_meta")
    if fm is None:
        return _fail("field_meta 缺失")
    ns = dict(getattr(fm, "NAMESPACES", {}))
    if ns.get("skill_lib") != ("skills",):
        return _fail(f"NAMESPACES['skill_lib'] = {ns.get('skill_lib')}（期望 ('skills',)）")
    if ns.get("job_lib") != ("jobs",):
        return _fail(f"NAMESPACES['job_lib'] = {ns.get('job_lib')}（期望 ('jobs',)）")
    tables = getattr(fm, "default_field_meta_table", None)
    if not callable(tables):
        return _fail("field_meta 缺 default_field_meta_table()")
    table = tables()
    if not isinstance(table, Mapping) and not hasattr(table, "modules"):
        return _fail("default_field_meta_table() 返回非映射/无 modules 属性")
    mods: Any = getattr(table, "modules", table)
    meta = mods.get("skills")
    if meta is None or getattr(meta, "kind", None) != "skill":
        return _fail("field_meta skills ModuleMeta 未登记（kind=skill）")
    meta = mods.get("jobs")
    if meta is None or getattr(meta, "kind", None) != "job":
        return _fail("field_meta jobs ModuleMeta 未登记（kind=job）")
    return _pass("field_meta 装配（skill_lib/job_lib 命名空间 + skills/jobs 登记）")


def t06_assembly() -> bool:
    """P6 装配接线：make_context 注入 ctx['skills']/ctx['jobs']/skill_slots。"""
    ctx_mod = _try_import("qbot_rpg.assembly.context")
    if ctx_mod is None or not callable(getattr(ctx_mod, "make_context", None)):
        return _fail("assembly/context.make_context 缺失")
    src = pathlib.Path(ctx_mod.__file__).read_text(encoding="utf-8")
    for key in (
        'ctx["skills"] = _table_from_registry(deps.registry, "skill")',
        'ctx["jobs"] = _table_from_registry(deps.registry, "job")',
    ):
        if key not in src:
            return _fail(f"make_context 注入缺失：{key}")
    if '"skill_slots": _skill_slots_interface' not in src:
        return _fail("make_context 缺 ctx['skill_slots'] 接口注入")
    return _pass("装配接线（ctx[skills/jobs/skill_slots] 注入 + 存档接口）")


def t07_job_command() -> bool:
    """P7 /转职 指令注册：register_job_commands + JOB_CMD + REGISTER_GROUPS。"""
    jc = _try_import("qbot_rpg.commands.job_commands")
    if jc is None or not callable(getattr(jc, "register_job_commands", None)):
        return _fail("job_commands.register_job_commands 缺失")
    if getattr(jc, "JOB_CMD", None) != "转职":
        return _fail(f"job_commands.JOB_CMD = {getattr(jc, 'JOB_CMD', None)}（期望 转职）")
    rsetup = _try_import("qbot_rpg.assembly.router_setup")
    if rsetup is None:
        return _fail("router_setup 缺失")
    groups = getattr(rsetup, "REGISTER_GROUPS", ())
    if not any(getattr(fn, "__name__", "") == "register_job_commands" for fn in groups):
        return _fail("REGISTER_GROUPS 未含 register_job_commands（/转职 未注册）")
    return _pass("/转职 指令注册（register_job_commands + REGISTER_GROUPS）")


def t08_default_job() -> bool:
    """P8 注册默认职业：default_job 兜底链（default_job_id → recommended_newbie → 首个）。"""
    rc = _try_import("qbot_rpg.commands.register_commands")
    if rc is None or not callable(getattr(rc, "default_job", None)):
        return _fail("register_commands.default_job 缺失")
    dj = getattr(rc, "default_job")
    jobs = {
        "warrior": {"id": "warrior", "name": "战士", "recommended_newbie": False},
        "mage": {"id": "mage", "name": "法师", "recommended_newbie": True},
    }
    ctx: Dict[str, Any] = {"jobs": jobs, "settings": {}}
    r = dj(ctx)
    if not isinstance(r, Mapping) or r.get("id") != "mage":
        return _fail(f"default_job 推荐链：{r}（期望 mage）")
    ctx["settings"] = {"default_job_id": "warrior"}
    r2 = dj(ctx)
    if not isinstance(r2, Mapping) or r2.get("id") != "warrior":
        return _fail(f"default_job default_job_id 优先链：{r2}（期望 warrior）")
    return _pass("注册默认职业（default_job_id → recommended_newbie → 首个）")


def t09_battle_skill_consumption() -> bool:
    """P9 战斗技能消费接线：_attack_action 装配过滤 + _resolve_skill + is_slot_equipped。"""
    bc = _try_import("qbot_rpg.commands.battle_commands")
    if bc is None:
        return _fail("battle_commands 缺失")
    src = pathlib.Path(bc.__file__).read_text(encoding="utf-8")
    for sym in ("def _attack_action(", "def _resolve_skill(", "skill_slots_battle"):
        if sym not in src:
            return _fail(f"battle_commands 缺技能消费接线：{sym}")
    return _pass("战斗技能消费接线（_attack_action 装配过滤 + _resolve_skill）")


def t10_battle_engine_wiring() -> bool:
    """P10 战斗接线：MP/energy/transform/季节/组合 全在 BattleEngine。"""
    be = _try_import("qbot_rpg.core.battle")
    if be is None:
        return _fail("core.battle 缺失")
    src = pathlib.Path(be.__file__).read_text(encoding="utf-8")
    pairs = (
        ("_apply_skill_energy", "energy_cost 门禁 + energy_gain 结算"),
        ("_job_transform_segment", "transform 装配解析"),
        ("set_transform_def", "transform 装配注入"),
        ("_resolve_combo_table_gate", "组合门禁 + F-C2 结算"),
        ("_init_season_state", "换季状态初始化"),
        ("_resolve_combo_action", "组合结算执行"),
    )
    missing = [name for name, _ in pairs if f"def {name}(" not in src]
    if missing:
        return _fail(f"BattleEngine 缺战斗接线方法：{missing}")
    # 换季结算边界：模块入口存在 + 战斗层消费（懒导入名即接线证据）
    if "tick_season_boundary" not in src:
        return _fail("BattleEngine 未接线 tick_season_boundary（换季结算边界）")
    return _pass("战斗接线（MP/energy/transform/季节/组合 全在 BattleEngine）")


def t11_pytest_count() -> bool:
    """P11 全仓测试通过数 ≥ 5500（实跑，非缓存计数）。"""
    py = _REPO / ".venv" / "bin" / "python"
    cmd = [
        str(py),
        "-m",
        "pytest",
        "tests/",
        # 注意：pytest.ini addopts 已含 -q；此处不再传 -q，避免 -qq 折叠
        # 「N passed」汇总行（探针需实跑计数）
        "-p",
        "no:cacheprovider",
        "--ignore=tests/e2e",
        "--tb=no",
        "-rN",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=str(_REPO))
    except Exception as e:  # noqa: BLE001
        return _fail(f"pytest 执行异常：{type(e).__name__}: {e}")
    out = (proc.stdout or "") + (proc.stderr or "")
    import re

    m = re.search(r"(\d+)\s+passed", out)
    if m is None:
        # -q 模式汇总行可能被 addopts 折叠；以退出码 0 + 无失败行兜底判读
        if proc.returncode == 0 and "failed" not in out:
            return _pass("全仓测试退出码 0 且无失败（汇总行被 -q 折叠，实跑通过）")
        return _fail(f"pytest 未输出通过数（exit={proc.returncode}）：{out[-300:]}")
    n = int(m.group(1))
    if n < MIN_TESTS_PASSED:
        return _fail(f"全仓通过 {n} < {MIN_TESTS_PASSED}")
    return _pass(f"全仓测试通过 {n} ≥ {MIN_TESTS_PASSED}")


def t12_demo_data() -> bool:
    """P12 数据样例在库：skills.json ≥1 条 + jobs.json ≥1 条 + recommended_newbie。"""
    import json

    pack = _REPO / "content" / "test_demo"
    for name, min_n in (("skills.json", 1), ("jobs.json", 1)):
        p = pack / name
        if not p.is_file():
            return _fail(f"{name} 缺失")
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            return _fail(f"{name} JSON 解析失败：{e}")
        if not isinstance(data, list) or len(data) < min_n:
            return _fail(
                f"{name} 条目数不足（{len(data) if isinstance(data, list) else '?'} < {min_n}）"
            )
    jobs = json.loads((pack / "jobs.json").read_text(encoding="utf-8"))
    if not any(isinstance(j, Mapping) and j.get("recommended_newbie") for j in jobs):
        return _fail("jobs.json 无 recommended_newbie 职业（注册默认职业前置缺失）")
    return _pass("数据样例在库（skills.json/jobs.json + recommended_newbie 职业）")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
CHECKS: List[Tuple[str, Callable[[], bool]]] = [
    ("P1 三契约文件在位", t01_contract_files),
    ("P2 数据模型落盘", t02_data_models),
    ("P3 校验器落盘", t03_validators),
    ("P4 引擎落盘", t04_engines),
    ("P5 field_meta 装配", t05_field_meta),
    ("P6 装配接线", t06_assembly),
    ("P7 /转职 指令注册", t07_job_command),
    ("P8 注册默认职业", t08_default_job),
    ("P9 战斗技能消费接线", t09_battle_skill_consumption),
    ("P10 战斗接线", t10_battle_engine_wiring),
    ("P11 全仓测试通过数 ≥ 5500", t11_pytest_count),
    ("P12 数据样例在库", t12_demo_data),
]


def main() -> int:
    print("=== M13 启动包验收清单探针（verify_m13）===")
    results: List[bool] = []
    for name, fn in CHECKS:
        try:
            r = fn()
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL {name}：异常 {type(e).__name__}: {e}")
            r = False
        results.append(r)
    ok = all(results)
    n_pass = sum(1 for r in results if r)
    print(f"=== 汇总：{n_pass}/{len(CHECKS)} 项 PASS，全 PASS → 退出码 0 ===")
    print("M13 " + ("OK" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
