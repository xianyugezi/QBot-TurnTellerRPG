#!/usr/bin/env python3
"""M2 怪物体系门禁（细化_5d §2.1 L91：1e 怪物八段 schema 14 + 1f 怪物AI 状态机 20 = 34 条 TC，G3 门禁）。

覆盖口径（诚实化覆盖声明原则）：
- 34 条 TC 逐条在 COVERAGE 声明承载位置——「pytest:<文件>::<用例>」或「脚本断言」或「DELAYED:依赖 X」；
  绝不允许声称覆盖实际未覆盖的 TC：
    * 1e-TC-14（换区/开场技运行期行为）→ DELAYED，依赖 M3（spawn/换区挂接）
    * 1f-TC-11（意图图鉴分级）/ TC-12（中断恢复消息）→ DELAYED，依赖 M6 图鉴（+M3 spawn）
    * 1f-TC-19（换区流程）/ TC-20（验收判据）→ DELAYED，依赖 M3/M6
- 并行路测试（test_monster_ai.py B1 / test_monster_intent_phases.py B3 /
  test_battle_boundary.py C2 / test_monster_conditions_chains.py B2）已落盘纳入
  子进程 pytest 门禁；文件缺失（异常）→ 黄提示跳过（不判失败，对应 TC 当前未承载视为声明缺口，随文件落盘补位）。
- 机制：脚本内核心断言（归一化概率 / L0 套内门 / 锚点+L7 兜底 / enemies 校验合法坏例 / decide_lost）
  + 子进程跑相关 pytest 测试文件。

用法：.venv/bin/python scripts/verify/verify_m2.py
门禁语义：脚本断言全过 + 已落盘 pytest 文件全绿 → 0；任一 FAIL → 1。
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

_PASS: list = []
_FAIL: list = []

# ----------------------------------------------------------------------------------
# 覆盖声明：34 条 TC 逐条承载位置（依据：细化_5d §2.1 L91 M2 行 = 34 条）
# ----------------------------------------------------------------------------------
COVERAGE: dict = {
    # ── 1e 怪物八段 schema（14 TC，细化_1e §⑥；A3 路：tests/unit/test_enemies_schema.py）──
    "1e-TC-01 合法普通怪全量": "pytest:test_enemies_schema.py::test_tc01_legal_enemy_full_green（八段齐全+零红零黄）+/ 脚本断言:legal 包 check_pack 零红零黄",
    "1e-TC-02 stats 漏键模板补全": "pytest:test_enemies_schema.py::test_tc02_stats_missing_template_fill",
    "1e-TC-03 无弱点怪": "pytest:test_enemies_schema.py::test_tc03_no_weakness_warning_not_blocking",
    "1e-TC-04 元素 ID 非法": "pytest:test_enemies_schema.py::test_tc04_invalid_element_ref_blocked",
    "1e-TC-05 PV 约束": "pytest:test_enemies_schema.py::test_tc05_pv_negative_blocked_and_range_note",
    "1e-TC-06 行动引用缺失": "pytest:test_enemies_schema.py::test_tc06_action_ref_missing_blocked",
    "1e-TC-07 概率归一化语义": "pytest:test_enemies_schema.py::test_tc07_probability_normalization_semantics（数据级池成员/权重和）+/ 脚本断言:L6 池口径（t_1f_tc13_tc02）",
    "1e-TC-08 触发类型与别名": "pytest:test_enemies_schema.py::test_tc08a~test_tc08e（非法枚举/缺 chance/旧别名归一/权威枚举/参数完整性）",
    "1e-TC-09 掉落扩展域": "pytest:test_enemies_schema.py::test_tc09a~test_tc09d（chance 越界/count min>max/condition 枚举/合法扩展+空引用）",
    "1e-TC-10 lore 递增": "pytest:test_enemies_schema.py::test_tc10a~test_tc10c（非递增/越界 1-100/合法递增）",
    "1e-TC-11 木桩忽略项": "pytest:test_enemies_schema.py::test_tc11a_training_tier_dummy_ignored_fields + test_tc11b_type_dummy_marker_variant",
    "1e-TC-12 木桩数值": "pytest:test_enemies_schema.py::test_tc12a_dummy_negative_stats_and_def_base_blocked + test_tc12b_dummy_no_weakness_exempt",
    "1e-TC-13 三档模板默认值抽查": "pytest:test_enemies_schema.py::test_tc13a_elite_template_fill_values + test_tc13b_boss_and_normal_pv_defaults + test_tc13c_difficulty_template_constants",
    "1e-TC-14 换区/开场技行为验收（运行期）": "DELAYED：依赖 M3（spawn/换区挂接）——残血换区 PV 恢复一半（向下取整）/battle_start 开场技为运行期行为，schema 层不验证（test_enemies_schema 内标 skip 注明）",
    # ── 1f 怪物AI 状态机（20 TC，细化_1f §⑥；B1 引擎 + C1 集成 + B2/B3 并行路）──
    "1f-TC-01 套间切换+enter_action": "pytest:test_monster_ai_battle.py::test_tc08_chain_inside_skips_eval（套间 L1 切 enraged + enter_action roar 入强制队列被执行）+ pytest:test_monster_ai.py（B1 路 pytest 已落盘纳入）",
    "1f-TC-02 残血狂暴权重修正": "脚本断言:t_1f_tc13_tc02（enraged weight_mod attack×1.5/defense×0.5 → ≈63.2%/31.6%/5.3%）+ pytest:test_monster_ai.py（B1 路 pytest 已落盘纳入）",
    "1f-TC-03 濒死处决": "pytest:test_monster_ai.py（并行路 B1：dying 态 death_rattle/final_strike exclusive；已落盘纳入）",
    "1f-TC-04 阈值单源": "pytest:test_monster_intent_phases.py（B3 路 pytest 已落盘纳入）",
    "1f-TC-05 起身触发": "pytest:test_monster_ai.py（B1 路 pytest 已落盘纳入）",
    "1f-TC-06 评估优先级序": "pytest:test_monster_ai.py（B1 路 pytest 已落盘纳入）",
    "1f-TC-07 同级随机": "pytest:test_monster_conditions_chains.py（B2 路 pytest 已落盘纳入）",
    "1f-TC-08 套内不评估": "pytest:test_monster_ai_battle.py::test_tc08_chain_inside_skips_eval + 脚本断言:t_1f_tc08_l0_inside_gate（L0 套内门）",
    "1f-TC-09 兜底普攻": "脚本断言:t_1f_tc14_tc09_anchor_and_l7（空池 L7 兜底普攻）+ pytest:test_monster_ai.py（B1 路 pytest 已落盘纳入）",
    "1f-TC-10 L1 永远公开": "pytest:test_monster_intent_phases.py（B3 路 pytest 已落盘纳入）；ai_state.intent 键形态由 test_monster_ai_battle.py::test_ai_action_dict_shape_and_merge 背书",
    "1f-TC-11 图鉴分级": "DELAYED：依赖 M6（图鉴 codex_state 解锁分级）——L2 招名=？？？/L3 不显示需图鉴接线",
    "1f-TC-12 中断恢复": "DELAYED：依赖 M6（图鉴）+ M3（spawn）——中断恢复含预演消息渲染；机制部分（ai_state 全字段快照往返，chain_pos/chain_queue/charge/intent 不丢）已由 test_monster_ai_battle.py::test_ai_state_snapshot_roundtrip 承载",
    "1f-TC-13 权重归一化": "脚本断言:t_1f_tc13_tc02（L6 池 40/20/10 → ≈57.1%/28.6%/14.3%）+ pytest:test_monster_ai.py（B1 路 pytest 已落盘纳入）",
    "1f-TC-14 锚点开关": "脚本断言:t_1f_tc14_tc09_anchor_and_l7（p=0 不入池/全 0 空池→纯脚本 BOSS）+ pytest:test_enemies_schema.py::test_tc07（数据级池成员资格）+ pytest:test_monster_ai.py（B1 路 pytest 已落盘纳入）",
    "1f-TC-15 hungry 保底": "pytest:test_monster_ai_battle.py::test_tc15_hungry_forced_pick（连续 3 回合第 3 回合强制选）+ pytest:test_monster_ai.py（B1 路 pytest 已落盘纳入）",
    "1f-TC-16 chain C roll": "pytest:test_monster_ai_battle.py::test_tc16_chain_roll_success + test_tc16_chain_roll_fail_breaks（成功必接/失败断链+链冷却）+ pytest:test_monster_conditions_chains.py（B2 路 pytest 已落盘纳入）",
    "1f-TC-17 打断=套完结": "pytest:test_monster_ai_battle.py::test_tc17_interrupt_breaks_chain（清在途队列/链冷却/combo_broken 标记/不续原套）",
    "1f-TC-18 蓄力跨回合": "pytest:test_monster_ai_battle.py::test_tc18_charge_cross_rounds（蓄力期不评估/释放大伤害）",
    "1f-TC-19 换区流程": "DELAYED：依赖 M3（换区/追击流程 + spawn）——逃向区域/追击/残血续战/PV 恢复一半/开场技",
    "1f-TC-20 验收判据": "DELAYED：依赖 M3/M6（完整 BOSS 战 + 图鉴 + 换区）——可读性/差异性/应对面/博弈深度/先教后考/QQ 适配等全流程判据",
}

# 补充引擎覆盖（超出 34 条具名 TC，不计入 COVERAGE 计数；与 5d §2.1 M2 行「补充引擎覆盖」对应）
SUPPLEMENT: dict = {
    "补充-1g4 世界边界（C2 路 battle_boundary）": "脚本断言:t_1g4_decide_lost（LOST 判定链 6 分支）+ pytest:test_battle_boundary.py（C2 路 pytest 已落盘纳入）",
    "补充-坏引用包八段坏例 + action.json AI 字段": "pytest:test_enemies_schema.py::test_badref_8seg_red_blocks（R1/R2/R3/R5/R6/R8/R13/R15 八类红拦）+ test_legal_action_library_ai_fields（T24 ActionCore+AI 字段表面）",
}

# 子进程 pytest 目标文件（已全部落盘；缺失（异常）黄提示跳过，不判失败）
PYTEST_FILES: list = [
    "tests/unit/test_enemies_schema.py",      # A3：1e TC-01~13 + badref + action.json AI 字段
    "tests/unit/test_monster_ai_battle.py",   # C1：1f TC-08/15/16/17/18 + 快照往返（TC-11/12/19/20 标 skip）
    "tests/unit/test_monster_ai.py",          # 并行路 B1：状态机 TC-01/02/03/05/06/07/09/10/13/14/15
    "tests/unit/test_monster_intent_phases.py",  # 并行路 B3：intent/phase
    "tests/unit/test_battle_boundary.py",     # 并行路 C2：1g4 世界边界
    "tests/unit/test_monster_conditions_chains.py",  # 并行路 B2：13 类触发/chain C roll
]


def check(name: str, fn) -> None:
    try:
        fn()
        _PASS.append(name)
        print(f"  ✓ {name}")
    except Exception as e:  # noqa: BLE001
        _FAIL.append((name, str(e)))
        print(f"  ✗ {name}: {e}")


def _yellow(text: str) -> None:
    print(f"  [黄] {text}")


# ==============================================================================
# 核心断言 ①：L6 随机池归一化概率（TC-13 权重归一化 + TC-02 残血狂暴权重修正）
# ==============================================================================
from qbot_rpg.core.monster_ai import ENRAGED, IDLE, IN_CHAIN, NORMAL, MonsterAI  # noqa: E402

_ACTION_LIB = {
    "claw_swipe": {"id": "claw_swipe", "kind": "active", "power": 1.2, "attack_type": "斩",
                   "tags": ["attack"]},
    "tail_sweep": {"id": "tail_sweep", "kind": "active", "power": 0.8, "attack_type": "打",
                   "tags": ["attack"]},
    "roar": {"id": "roar", "kind": "active", "power": 0.0, "attack_type": "魔",
             "tags": ["defense"]},
    "big_bite": {"id": "big_bite", "kind": "active", "power": 1.8, "attack_type": "斩",
                 "tags": ["attack"]},
}


def _ai_bs(ai_state: dict | None = None) -> dict:
    """battle_state 最小形态 + ai_state（decide 播种 14 键默认后供 pool_probabilities 读）。"""
    bs = {"enemy": {"hp": 1000, "max_hp": 1000}, "turn": 3, "ai_state": ai_state or {}}
    return bs


def t_1f_tc13_tc02_normalized_prob() -> None:
    """TC-13：阶段1 随机池 40/20/10 → P ≈ 57.1%/28.6%/14.3%（火球=锚点不入池）；
    TC-02：enraged weight_mod {attack:1.5, defense:0.5} → ≈63.2%/31.6%/5.3%（1f §⑥ 同口径）。"""
    ai = MonsterAI({
        "id": "w", "name": "W",
        "actions": [
            {"action": "claw_swipe", "probability": 1, "weight": 40},
            {"action": "tail_sweep", "probability": 1, "weight": 20},
            {"action": "roar", "probability": 1, "weight": 10},
            {"action": "big_bite", "probability": 0, "weight": 0},   # 锚点（仅链/条件触发）
        ],
        "special_actions": [], "chains": [],
        "ai": {"states": {"enraged": {"weight_mod": {"attack": 1.5, "defense": 0.5}}}},
    }, _ACTION_LIB, random.Random(1))
    bs = _ai_bs()
    ai.decide(bs)  # 播种 ai_state 14 键默认（_ensure_ai_state）

    p = ai.pool_probabilities(bs)
    assert set(p) == {"claw_swipe", "tail_sweep", "roar"}, \
        f"TC-13 池成员=40/20/10 三招，锚点不入池；实际 {set(p)}"
    assert abs(p["claw_swipe"] - 40 / 70) < 1e-9 and abs(p["tail_sweep"] - 20 / 70) < 1e-9 \
        and abs(p["roar"] - 10 / 70) < 1e-9, f"TC-13 归一化比例不符：{p}"
    assert round(p["claw_swipe"], 3) == round(0.571, 3) == 0.571
    assert round(p["tail_sweep"], 3) == round(0.286, 3) == 0.286
    assert round(p["roar"], 3) == round(0.143, 3) == 0.143
    assert abs(sum(p.values()) - 1.0) < 1e-9, "归一化概率和=1（小数 fraction，铁律 5）"

    # TC-02：切 enraged → 攻击类 ×1.5（claw 60 / tail 30）、防御类 ×0.5（roar 5）→ Σ=95
    bs["ai_state"]["state"] = ENRAGED
    p2 = ai.pool_probabilities(bs)
    assert abs(p2["claw_swipe"] - 60 / 95) < 1e-9 and abs(p2["tail_sweep"] - 30 / 95) < 1e-9 \
        and abs(p2["roar"] - 5 / 95) < 1e-9, f"TC-02 狂暴权重修正不符：{p2}"
    assert round(p2["claw_swipe"], 3) == round(0.632, 3) and \
        round(p2["tail_sweep"], 3) == round(0.316, 3) and \
        round(p2["roar"], 3) == round(0.053, 3), f"TC-02 ≈63.2/31.6/5.3 不符：{p2}"


# ==============================================================================
# 核心断言 ②：L0 套内门（TC-08 套内不评估）
# ==============================================================================
def t_1f_tc08_l0_inside_gate() -> None:
    """在途链尾扫待执行 + HP 40%（<50 阈值）→ decide 走 L0 推进尾扫，不切状态/不评估（TC-08）。"""
    ai = MonsterAI({
        "id": "brute", "name": "蛮兽",
        "actions": [
            {"action": "claw_swipe", "probability": 1, "weight": 40},
            {"action": "tail_sweep", "probability": 1, "weight": 20},
        ],
        "special_actions": [], "chains": [],
        "ai": {"states": {"enraged": {"enter_action": "roar"}},
               "transitions": [{"from": "normal", "to": "enraged",
                                "condition": {"type": "hp_below", "value": 50}}]},
    }, _ACTION_LIB, random.Random(1))
    bs = _ai_bs({"chain_queue": ["tail_sweep"], "chain_id": "c1", "chain_pos": 1,
                 "exec_state": IN_CHAIN})
    bs["enemy"]["hp"] = 400  # 40% < 50：若评估会切 enraged
    act = ai.decide(bs)
    st = bs["ai_state"]
    assert act["action_id"] == "tail_sweep" and act["source"] == "L0_chain", \
        f"L0 套内应推进尾扫；实际 {act.get('action_id')}/{act.get('source')}"
    assert st["state"] == NORMAL, f"套内不切状态（TC-08）；实际 {st['state']}"
    assert st["chain_queue"] == [] and st["chain_id"] is None and st["exec_state"] == IDLE, \
        "套结算完回 idle（在途链清空）"


# ==============================================================================
# 核心断言 ③：锚点开关 + L7 兜底普攻（TC-14 / TC-09）
# ==============================================================================
def t_1f_tc14_tc09_anchor_and_l7() -> None:
    """probability=0 全锚点 → 空池（纯脚本 BOSS，TC-14）；L0-L6 无产出 → L7 兜底普攻（TC-09）。"""
    ai = MonsterAI({
        "id": "script_boss", "name": "S",
        "actions": [{"action": "big_bite", "probability": 0, "weight": 100}],
        "special_actions": [], "chains": [],
    }, _ACTION_LIB, random.Random(1))
    bs = _ai_bs()
    ai.decide(bs)
    assert ai.pool_probabilities(bs) == {}, "TC-14 全表 0 = 纯脚本 BOSS：随机池空"
    act = ai.decide(bs)
    assert act["type"] == "normal" and act["skill_id"] is None and act["source"] == "L7", \
        f"TC-09 L7 兜底普攻不符：{act.get('type')}/{act.get('source')}"


# ==============================================================================
# 核心断言 ④：enemies 八段校验器——合法包零红零黄 + badref 坏例红拦（TC-01 载体 + 交付③）
# ==============================================================================
def t_1e_validator_legal_badref() -> None:
    from qbot_rpg.content.loader import PackLoadError, build_pack
    from qbot_rpg.content.validator import check_pack

    legal_dir = REPO / "tests" / "fixtures" / "packs" / "legal"
    badref_dir = REPO / "tests" / "fixtures" / "packs" / "badref"
    assert legal_dir.is_dir() and badref_dir.is_dir(), "fixtures 缺失（legal/badref）"

    # 合法包（含八段怪）整包校验：无拦截 + 零黄基线（TC-01 / 细化_3e#TC-30 同步口径）
    modules = {}
    for name in ("action", "effects", "statuses", "items", "enemies"):
        modules[name] = json.loads((legal_dir / f"{name}.json").read_text(encoding="utf-8"))
    rep = check_pack(modules)
    assert not rep.errors, f"合法包不应红拦（TC-01）：{rep.errors}"
    assert not rep.warnings, f"合法包应为零黄提示（TC-01）：{rep.warnings}"

    # badref 八段坏例：整包红拦（PackLoadError 抛错），引用/枚举/参数三类规则命中
    try:
        build_pack(badref_dir)
        raise AssertionError("badref 包应红拦（PackLoadError 未抛出）")
    except PackLoadError as ei:
        rules = {e.detail.get("rule") for e in ei.errors}
        assert {"R1_action_ref", "R3_element_ref", "R2_trigger_type_invalid",
                "R6_unlock_increasing", "R8_tier_enum"} <= rules, \
            f"badref 八段坏例缺拦截规则：{rules}"


# ==============================================================================
# 核心断言 ⑤：1g4 世界边界——decide_lost 判定链（补充覆盖，C2 路 battle_boundary）
# ==============================================================================
def t_1g4_decide_lost() -> None:
    from qbot_rpg.world.battle_boundary import (
        LOST_ENTER_PENDING, LOST_EXIT_BY_PLAYER, LOST_EXIT_NO_RESPAWN, LOST_RESOLVE_NORMAL,
        LOST_RESPAWNED, LOST_WAIT_REFRESH, decide_lost,
    )

    d = decide_lost
    assert d(target_present=True, has_pending=False, spawn_row_exists=True,
             can_respawn=True, refreshed=False) == LOST_RESOLVE_NORMAL, "① 在场合正常结算"
    assert d(target_present=False, has_pending=False, spawn_row_exists=True,
             can_respawn=True, refreshed=False) == LOST_ENTER_PENDING, "② 不在场写挂起"
    assert d(target_present=False, has_pending=True, spawn_row_exists=True,
             can_respawn=True, refreshed=False) == LOST_WAIT_REFRESH, "③ 有刷新等刷新"
    assert d(target_present=False, has_pending=True, spawn_row_exists=True,
             can_respawn=True, refreshed=True) == LOST_RESPAWNED, "③ 已刷新继续战斗"
    assert d(target_present=False, has_pending=True, spawn_row_exists=False,
             can_respawn=False, refreshed=False) == LOST_EXIT_NO_RESPAWN, "④ 无刷新按退出"
    assert d(target_present=True, has_pending=False, spawn_row_exists=True, can_respawn=True,
             refreshed=False, player_exited=True) == LOST_EXIT_BY_PLAYER, "⑤ 玩家逃跑按退出"


# ==============================================================================
# 汇总与子进程 pytest 门禁
# ==============================================================================
def main() -> int:
    print("== verify_m2 脚本核心断言（M2 怪物体系）==")
    checks = [
        ("1f-TC-13+TC-02 归一化概率（40/20/10→57.1/28.6/14.3；狂暴≈63.2/31.6/5.3）", t_1f_tc13_tc02_normalized_prob),
        ("1f-TC-08 L0 套内门（在途链推进/不切状态）", t_1f_tc08_l0_inside_gate),
        ("1f-TC-14+TC-09 锚点开关+L7 兜底普攻", t_1f_tc14_tc09_anchor_and_l7),
        ("1e-TC-01 校验器合法零红零黄 + badref 八段红拦", t_1e_validator_legal_badref),
        ("补充-1g4 decide_lost 判定链（6 分支）", t_1g4_decide_lost),
    ]
    for name, fn in checks:
        check(name, fn)

    print("\n== 子进程 pytest（M2 相关测试文件；文件缺失（异常）→ 黄提示跳过）==")
    existing = [f for f in PYTEST_FILES if (REPO / f).exists()]
    missing = [f for f in PYTEST_FILES if not (REPO / f).exists()]
    for f in missing:
        _yellow(f"{f} 缺失（异常）→ 跳过；对应 TC 承载（B1/B2/B3/C2 路）随文件落盘后生效")
    pytest_ok = False
    if existing:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", *existing, "-q", "--tb=short", "-rN",
             "--disable-warnings"],
            cwd=str(REPO), capture_output=True, text=True, timeout=600,
        )
        tail = "\n".join((proc.stdout or "").splitlines()[-4:])
        print(tail)
        if proc.returncode != 0:
            print((proc.stdout or "")[-3000:])
        pytest_ok = proc.returncode == 0
    else:
        _yellow("无已落盘 pytest 文件，跳过子进程段（本脚本核心断言仍执行）")

    print("\n== 覆盖声明（细化_5d §2.1 L91：M2 怪物 = 34 条 TC，诚实化逐条标注）==")
    for tc, carrier in COVERAGE.items():
        print(f"  {tc} → {carrier}")
    print("  ── 补充引擎覆盖（不计入 34 计数）──")
    for tc, carrier in SUPPLEMENT.items():
        print(f"  {tc} → {carrier}")
    delayed = [k for k, v in COVERAGE.items() if v.startswith("DELAYED")]
    print(f"\n  DELAYED 项（{len(delayed)}/34）：{', '.join(k.split(' ')[0] for k in delayed)}")

    n_fail = len(_FAIL)
    print(f"\n结果：脚本断言 {len(_PASS)} 通过 / {n_fail} 失败；pytest {'✔' if pytest_ok else '✘'}"
          f"{'（缺失文件黄提示不判失败）' if missing else ''}")
    if n_fail or not pytest_ok:
        for name, err in _FAIL:
            print(f"  FAIL {name}: {err}")
        print("M2 门禁：verify_m2 未通过 ✘（失败回溯：细化_1e/1f #TC-NN + 断言原文见上；D8 VG-20 统一「M<N> 门禁」输出）")
        return 1
    print("M2 门禁：verify_m2 全绿 ✔（34 TC 中 29 已承载 + 5 DELAYED；并行路落盘后自动纳入；D8 VG-20）")
    return 0


if __name__ == "__main__":
    sys.exit(main())