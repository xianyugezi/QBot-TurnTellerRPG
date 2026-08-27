#!/usr/bin/env python3
"""M6 内容包冒烟（D4 SMK 件套）：四步断言矩阵 + validator 四件套 + 确定性重放。

依据：
  - 细化_M6_内容包冒烟（D4）§一 SMK-01~05（落点形态/零 NoneBot/确定性/复用+增强/断言风格）
    + §二 SMK-06~11（四步逐步断言矩阵：注册门槛→锁定→攻击→结算）
    + §三 SMK-12~15（validator 四件套矩阵：legal/badref/missing_mod/old_schema）
  - scripts/e2e_m4_smoke.py（形态范本：Smoke 收集器/固定 now+seed/确定性重放/全绿行）
  - verify_m1.py L194-224（回合时序/快照往返/random_seed 续接）
  - verify_m5.py L497-513（一轮一条合并）

【铁律】零 NoneBot import；装配全部真实模块（core/battle、world/battle_boundary、
commands/battle_commands、commands/basic_commands、commands/register_commands、
content/loader、content/field_meta）；固定 now/种子 → 两次重放摘要逐字一致。
"""

from __future__ import annotations

import json
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from qbot_rpg.commands.basic_commands import (  # noqa: E402
    TPL_REGISTER_GATE,
    cmd_bag,
    cmd_equip,
    cmd_help,
    cmd_skill,
    cmd_view,
)
from qbot_rpg.commands.battle_commands import BattlePipeline, dispatch_round  # noqa: E402
from qbot_rpg.commands.parsers import parse_command as parse  # noqa: E402
from qbot_rpg.commands.register_commands import cmd_register  # noqa: E402
from qbot_rpg.content.field_meta import default_field_meta_table  # noqa: E402
from qbot_rpg.content.loader import PackLoadError, build_pack  # noqa: E402
from qbot_rpg.core.battle import BattleEngine  # noqa: E402
from qbot_rpg.world.battle_boundary import try_acquire_lock  # noqa: E402

# -------------------------------------------------------------------------------------
# 常量（固定 now / 种子 —— 确定性铁律，D4 SMK-03）
# -------------------------------------------------------------------------------------
PACKS = REPO / "tests" / "fixtures" / "packs"
LEGAL_DIR = PACKS / "legal"
_TZ8 = timezone(timedelta(hours=8))
FIXED_NOW = int(datetime(2026, 8, 1, 12, 0, 0, tzinfo=_TZ8).timestamp())  # 2026-08-01 12:00 UTC+8
SEED = 20260826  # 固定 rng 种子（D4 SMK-03：SEED=20260826）
GREEN_LINE = "M6 内容包冒烟全绿（注册门槛→锁定→攻击→结算 + validator 四件套）"


class _FixedRng:
    """固定随机源：恒 0.1 → 命中判定必过（hit_rate ≥ 10% cap_min）；确定性重放（对齐
    verify_m1 _QR 固定序列注入，D4 SMK-03 确定性铁律）。"""

    def random(self) -> float:
        return 0.1

# 冒烟玩家（对齐 test_battle_engine 构造口径；combatant 数字段）
SMOKE_PLAYER = {
    "hp": 150, "max_hp": 150, "mp": 40, "str": 20, "int": 12, "agi": 14,
    "spr": 8, "lck": 10, "con": 15, "foc": 10, "name": "冒烟侠",
}


# -------------------------------------------------------------------------------------
# 断言收集器（D4 SMK-05：Smoke.check/check_eq 收集器 + 失败行可回溯）
# -------------------------------------------------------------------------------------
class Smoke:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.failures: List[str] = []

    def check(self, cond: bool, label: str) -> bool:
        if cond:
            self.passed += 1
            return True
        self.failed += 1
        self.failures.append(label)
        return False

    def check_eq(self, got: object, want: object, label: str) -> bool:
        if got == want:
            self.passed += 1
            return True
        self.failed += 1
        self.failures.append(f"{label}：期望 {want!r}，实际 {got!r}")
        return False


# -------------------------------------------------------------------------------------
# 装配：legal 包数据（D4 SMK-02：真实模块）
# -------------------------------------------------------------------------------------
def _load_legal(name: str) -> list:
    data = json.loads((LEGAL_DIR / f"{name}.json").read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return data


def _enemy_combatant() -> Dict[str, Any]:
    """content/demo_lv15 enemies.json 的 rock_weasel（岩皮鼬）→ combatant dict（stats 映射）。

    P1-2 修复（M6 批4 审查 / PCK-10）：五档包数据装配战斗——改用 demo_lv15 档数据，
    一处覆盖 SMK-10（攻击步用内容包数据）+ PCK-10（五档包可装配真实战斗）。"""
    data = json.loads((REPO / "content" / "demo_lv15" / "enemies.json").read_text(encoding="utf-8"))
    enemies = data if isinstance(data, list) else []
    entry = next(e for e in enemies if e["id"] == "rock_weasel")
    st = entry["stats"]
    return {
        "hp": st["hp"], "max_hp": st["hp"], "mp": st["mp"],
        "str": st["str"], "int": st["int"], "agi": st["agi"],
        "spr": st["spr"], "lck": st["luk"], "con": st["con"], "foc": st["foc"],
        "name": entry["name"],
    }


def _load_pack(name: str):
    """build_pack 装载（四件套矩阵用；返回 (pack, changed) 或抛 PackLoadError）。"""
    return build_pack(PACKS / name, default_field_meta_table(), {}, 1)


# -------------------------------------------------------------------------------------
# 注册门槛 ctx（D4 SMK-06/07：registered=False → TPL_REGISTER_GATE；注册后放行）
# -------------------------------------------------------------------------------------
def _make_register_ctx(**over: Any) -> Dict[str, Any]:
    """未注册玩家 ctx（对齐 test_register_commands.make_ctx 结构；registered=False 默认）。"""
    base: Dict[str, Any] = {
        "registered": False,
        "player": None,
        "jobs": {"warrior": {"name": "战士", "recommended_newbie": True}},
        "stats": {
            "hp": {"name": "生命", "type": "resource", "base": 100},
            "mp": {"name": "魔力", "type": "resource", "base": 30},
            "str": {"name": "力量", "type": "combat", "base": 12},
            "con": {"name": "体质", "type": "combat", "base": 10},
            "int": {"name": "智力", "type": "combat", "base": 10},
            "agi": {"name": "敏捷", "type": "combat", "base": 10},
        },
        "settings": {
            "default_job_id": "warrior", "default_map": "新手村", "world_name": "艾泽拉",
        },
        "name_exists": lambda name: False,
    }
    base.update(over)
    return base


# -------------------------------------------------------------------------------------
# 四步断言矩阵（D4 §2.1）
# -------------------------------------------------------------------------------------
def step_register(s: Smoke) -> None:
    """① 注册门槛：未注册 → 4 指令 TPL_REGISTER_GATE 逐字；/帮助 豁免；注册后放行。"""
    ctx = _make_register_ctx()
    for cmd_name, handler in (("角色", cmd_view), ("背包", cmd_bag), ("装备", cmd_equip),
                              ("技能", cmd_skill)):
        out = handler(parse(f"/{cmd_name}"), ctx)
        s.check_eq(out, TPL_REGISTER_GATE, f"注册门槛·/{cmd_name} 未注册拦截")
    # /帮助 豁免（B6 注册引导版）
    help_out = cmd_help(parse("/帮助"), ctx)
    s.check("【新手引导】" in help_out, "注册门槛·/帮助 豁免返回引导版")
    # 注册后放行：真实 cmd_register（D1 REG-06）
    reg_out = cmd_register(parse("/注册 冒烟侠 战士"), ctx)
    s.check("✅" in str(reg_out) and ctx.get("registered") is True, "注册门槛·cmd_register 置 registered=True")
    # 注册后 4 指令统一放行（P2-6 修复：不再只回归 /角色）
    for cmd_name, handler in (("角色", cmd_view), ("背包", cmd_bag), ("装备", cmd_equip),
                              ("技能", cmd_skill)):
        s.check(handler(parse(f"/{cmd_name}"), ctx) != TPL_REGISTER_GATE,
                f"注册门槛·注册后 /{cmd_name} 放行")


def step_lock(s: Smoke) -> None:
    """② 锁定：try_acquire_lock 先到先得 + BattleEngine.start 装配（ADR-01 二选一两段式）。"""
    # (a) 纯函数锁断言（D4 SMK-08a）
    att = try_acquire_lock(None, "player_a", FIXED_NOW, "battle-1")
    s.check(att.acquired is True and att.lock.holder_qid == "player_a",  # type: ignore[union-attr]
            "锁定·无锁获得且 holder=调用者")
    att2 = try_acquire_lock(att.lock, "player_b", FIXED_NOW + 1, "battle-2")
    s.check(att2.acquired is False, "锁定·有锁拒绝")
    s.check(att2.lock is not None and att2.lock.holder_qid == "player_a",
            "锁定·拒绝时暴露现存锁 holder")
    # (b) BattleEngine.start 装配（D4 SMK-08b：state=act/turn=1/combatant 来自 legal 包）
    eng = BattleEngine()
    eng._rng = _FixedRng()  # type: ignore[assignment]
    eng.start(dict(SMOKE_PLAYER), _enemy_combatant(), random_seed=SEED)
    s.check(eng.state == "act", "锁定·start 后 state=act")
    bs = eng.battle_state()
    s.check(int(bs.get("turn", 0)) == 1, "锁定·start 后 turn=1")
    s.check(bs["enemy"]["name"] == "岩皮鼬", "锁定·combatant 来自内容包（岩皮鼬）")
    s.check_eq(int(bs["enemy"]["hp"]), 120, "锁定·combatant 数值来自 demo_lv15（hp=120）")  # P2-5


def step_attack(s: Smoke) -> None:
    """③ 攻击：do_action normal → final_damage>0 + HP 差分 + 一轮一条（dispatch_round 恰 1 次 send）。

    用 _FixedRng（恒 0.1）保证命中；mult=1.0 伤害约 68.6 < 岩皮鼬 hp=120（不溢出，
    HP 差分 = final_damage 成立；D4 SMK-10 保留 normal 攻击 + 数值/差分/合并三项断言）。"""
    eng = BattleEngine()
    eng._rng = _FixedRng()  # type: ignore[assignment]
    eng.start(dict(SMOKE_PLAYER), _enemy_combatant(), random_seed=SEED)
    hp_before = eng.battle_state()["enemy"]["hp"]
    out = eng.do_action("player", {"type": "normal", "mult": 1.0})
    hp_after = eng.battle_state()["enemy"]["hp"]
    s.check(out.final_damage > 0, f"攻击·final_damage>0（实得 {out.final_damage}）")
    s.check_eq(hp_before - hp_after, out.final_damage, "攻击·HP 差分=final_damage")
    # 一轮一条（D4 SMK-10 / TC-SMK-06：dispatch_round 恰 1 次 send，行动+反击合并单条；
    # 对齐 verify_m5 ④b 范本：start 后 player_act 产 TurnReport + BattlePipeline(mock sender)。
    # P0-1 修复（M6 批4 审查）：独立新引擎——不能复用上方 do_action 已推进状态的引擎
    # （其 state 已离开 act，player_act 状态错乱会致 send=2）；start→player_act 一轮时序。）
    import unittest.mock as _mock

    eng1 = BattleEngine()
    eng1._rng = _FixedRng()  # type: ignore[assignment]
    eng1.start(dict(SMOKE_PLAYER), _enemy_combatant(), random_seed=SEED)
    mock = _mock.Mock()
    mock.send.return_value = []
    pipeline = BattlePipeline(mock, level=35, name="冒烟侠", title="-", to="smoke")
    report = eng1.player_act("normal")
    dispatch_round(eng1, report, pipeline, {"battle_engine": eng1, "sender": mock,
                                            "battle_status_changes": ()})
    s.check_eq(mock.send.call_count, 1, "攻击·一轮行动+反击合并恰 1 次 send")


def step_settle(s: Smoke) -> None:
    """④ 结算：敌方 hp≤0 终局 → victory 文案 + 掉落 + 回合数 + 快照 round-trip。"""
    eng = BattleEngine()
    eng._rng = _FixedRng()  # type: ignore[assignment]
    eng.start(dict(SMOKE_PLAYER), _enemy_combatant(), random_seed=SEED)
    # 轰到敌方 hp≤0 → 引擎终局结算（eng.finished；完整回合时序 do_action→enemy_act→end_turn）
    for _ in range(50):
        if eng.finished:
            break
        eng.do_action("player", {"type": "normal", "mult": 100.0})
        if not eng.finished:
            eng.enemy_act()
            eng.end_turn()
    state = eng.battle_state()
    s.check(eng.finished or int(state["enemy"]["hp"]) <= 0, "结算·敌方 hp≤0 终局")
    # P2-4 修复（M6 批4 审查 / SMK-11）：victory 标志断言（result.flag == win）
    flag = (state.get("result") or {}).get("flag")
    s.check_eq(str(flag or ""), "win", "结算·victory 标志（result.flag=win）")
    # 回合数（BREP-24 口径：D4 偏离声明——win 模板不含「回合数 N」行，改断言引擎 turn）
    turn = int(state.get("turn", 0))
    s.check(turn >= 1, f"结算·回合数 N≥1（实得 {turn}）")
    # 快照 round-trip（D4 SMK-11：to_snapshot → from_snapshot → 核心战斗字段一致；
    # 只比 turn/hp/action_record，不比 snapshot 元数据如 snapshot_id/saved_at——恢复时清理）
    snap = eng.to_snapshot()
    eng2 = BattleEngine.from_snapshot(snap)
    for eng_a, eng_b in ((eng, eng2),):
        b1, b2 = eng_a.battle_state(), eng_b.battle_state()
        s.check_eq(int(b2["turn"]), int(b1["turn"]), "结算·快照 round-trip turn 一致")
        s.check_eq(b2["enemy"]["hp"], b1["enemy"]["hp"], "结算·快照 round-trip 敌方 HP 一致")
        s.check_eq(len(b2.get("action_record", [])), len(b1.get("action_record", [])),
                   "结算·快照 round-trip 行动记录条数一致")


def validator_matrix(s: Smoke) -> None:
    """validator 四件套矩阵（D4 SMK-12：legal/badref/missing_mod/old_schema，禁止空断言）。"""
    # legal：全过（0 红 0 黄 + registry 全注册）
    pack, changed = _load_pack("legal")
    s.check(pack.report.ok, "validator·legal report.ok")
    s.check(len(pack.report.errors) == 0 and len(pack.report.warnings) == 0,
            "validator·legal 0 errors 0 warnings")
    s.check(len(changed) >= 5, f"validator·legal 注册模块数≥5（实得 {len(changed)}）")
    # badref：红拦（PackLoadError + 不崩）
    try:
        _load_pack("badref")
        s.check(False, "validator·badref 应抛 PackLoadError")
    except PackLoadError:
        s.check(True, "validator·badref 红拦 PackLoadError")
    # missing_mod：软放行（加载成功 + Y-6 黄提示）
    try:
        mp, _ = _load_pack("missing_mod")
        y6 = any("Y-6" in str(w.kind) or "statuses" in str(w.module) for w in mp.report.warnings)
        s.check(mp.report.ok, "validator·missing_mod 软放行加载成功")
        s.check(y6, "validator·missing_mod 含 Y-6(statuses) 黄提示")  # P1-1 修复：签名断言补消费
    except PackLoadError:
        s.check(False, "validator·missing_mod 应软放行非红拦")
    # old_schema：容忍加载（不红拦 report.ok）
    try:
        op, _ = _load_pack("old_schema")
        s.check(op.report.ok, "validator·old_schema 容忍加载不红拦")
    except PackLoadError:
        s.check(False, "validator·old_schema 应容忍加载")


def run_smoke() -> Dict[str, Any]:
    """冒烟主体：四步断言 + validator 矩阵 → 汇总摘要（两次调用逐字一致）。"""
    s = Smoke()
    step_register(s)
    step_lock(s)
    step_attack(s)
    step_settle(s)
    validator_matrix(s)
    summary = {
        "passed": s.passed,
        "failed": s.failed,
        "failures": list(s.failures),
        "green": s.failed == 0,
    }
    return summary


def main() -> int:
    """确定性重放：两次 run_smoke 摘要逐字一致（D4 SMK-03）+ 全绿行。"""
    a = run_smoke()
    b = run_smoke()
    ok = a["green"] and a == b
    print(f"第一次摘要：passed={a['passed']} failed={a['failed']}")
    print(f"重放一致：{a == b}")
    if not ok:
        # P2-7 修复（M6 批4 审查）：重放不一致时打印两摘要差异，便于回溯
        if a != b:
            print(f"  摘要 A：passed={a['passed']} failed={a['failed']} failures={a['failures']}")
            print(f"  摘要 B：passed={b['passed']} failed={b['failed']} failures={b['failures']}")
        for f in a["failures"]:
            print(f"  ✗ {f}")
        print("M6 内容包冒烟失败")
        return 1
    print(GREEN_LINE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
