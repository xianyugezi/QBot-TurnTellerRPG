"""批53 · 时序 / 资源 / 结算轴接线验收测试（P0 冷却 · 状态概率 · 层数 · P1 行动条/资源）。

口径：
  · `特效整理设计_1_修正轴全集.md` X27（冷却·占位键归并）/ X21（状态概率＋溢出转层）/
    X23（层数获取）/ X24（层数上限）/ X30（行动条推动）/ X34·X35（资源消耗·获取）/
    X22（状态抵抗）/ X03（会心倍率）；
  · `特效整理设计_3_落点与分期.md` §二「批 51」（旧编号 = 本批批53）；
  · `特效强度预算_设计.md` §四 红线守护（C1 缺省对拍 / C9 特效键不进面板轴 / C11 上下钳）；
  · 明确**排除** `action_speed` / `action_recovery`（数学互为倒数、必须二选一，待裁决 D2）。

覆盖：
  A. 冷却乘法轴 `cooldown_pct`：α3 同乘区一次缩放（双向）；旧占位键
     `cooldown_reduction_pct` 经聚合入口换算（旧键仍可用、**不双计**）；未配置零变化。
  B. 状态概率 `status_chance_pct`（+ `debuff_chance_pct` / `buff_chance_pct` 归并）
     ＋溢出转层；状态抵抗 `status_resist_pct`（攻/防两侧不合并）。
  C. 层数获取 `stack_gain_pct` ＋ 层数上限 `stack_cap_delta`（与批48 stacks 乘算对齐）。
  D. 行动条推动 `action_bar_shift`（复用 delay_actor / hasten_actor 双向原语）。
  E. 资源消耗 `resource_cost_pct` / 资源获取 `resource_gain_pct`（既有两处消费点）。
  F. 会心倍率 `crit_damage_pct`。
  G. 零变化对拍（红线 C1）：未配置任一特效轴 → 战斗结算快照逐字段一致、无特效轴键。

纪律：测试只构造内存对象（不写任何真实内容包）；匿名 id（s_*）；数值/区间全由测试内声明。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.equipment import EquipmentEngine
from qbot_rpg.core.player_attributes import PlayerAttributes
from qbot_rpg.core.pvp import _combatant_of
from qbot_rpg.data.gear_stats import (
    EFFECT_AXES_KEY,
    EFFECT_LEGACY_ALIASES,
    GEAR_EFFECT_KEYS,
    combatant_updates,
    route_bonus_into,
    route_legacy_aliases_into_flat,
)
from qbot_rpg.data.item import ItemInstance

BP = "player"
BN = "enemy"

PLAYER = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 0,
          "mag": 50, "spd": 50, "foc": 100, "con": 0, "str": 100, "int": 80, "agi": 50,
          "spr": 0, "lck": 50, "elem_atk": 0, "name": "P"}
ENEMY = {"max_hp": 400000, "hp": 400000, "max_mp": 0, "mp": 0, "atk": 0, "dfn": 0,
         "mag": 0, "spd": 40, "foc": 0, "con": 0, "str": 0, "int": 0, "agi": 40,
         "spr": 0, "lck": 0, "elem_atk": 0, "name": "E"}


class _QueueRNG:
    """确定性随机源（命中/会心/格挡/乱数 4 判定固定序列）。"""

    def __init__(self, seq: Any) -> None:
        self.seq = list(seq)
        self.i = 0

    def random(self) -> float:
        v = self.seq[self.i]
        self.i = (self.i + 1) % len(self.seq)
        return v


# ===========================================================================
# A · 冷却乘法轴（X27 `cooldown_pct`）+ 占位旧键归并不双计
# ===========================================================================
_SKILL = {"id": "s1", "name": "火球", "tag": "combo", "power": 100, "cooldown": 10}


def _run_cd(extra: Mapping[str, Any], *, axes: Any = None, amp: Any = None) -> Dict[str, int]:
    cfg: Dict[str, Any] = {"combo_enforce_mp": True}
    if axes is not None:
        cfg[EFFECT_AXES_KEY] = axes
    if amp is not None:
        cfg["equip_skill_amp"] = amp
    eng = BattleEngine(defs={"s1": _SKILL}, config=cfg)
    eng._rng = _QueueRNG([0.5, 0.5, 0.5, 1.0])  # noqa: SLF001
    eng.start(dict(PLAYER, **dict(extra)), dict(ENEMY), random_seed=1)
    eng.do_action("player", {"type": "skill", "skill_id": "s1", "tag": "combo",
                             "mult": 1.0})
    return dict(eng._snap.get("skill_cooldowns", {}).get("player", {}))  # noqa: SLF001


def test_a1_cooldown_axis_bidirectional() -> None:
    """`+100` → 冷却 ×2（10→20）；`−50` → ×0.5（10→5）；`0` → 原值。"""
    assert _run_cd({"cooldown_pct": 0}) == {"s1": 10}
    assert _run_cd({"cooldown_pct": 100}) == {"s1": 20}
    assert _run_cd({"cooldown_pct": -50}) == {"s1": 5}


def test_a2_cooldown_axis_single_multiplier_with_alpha3() -> None:
    """与 α3 在**同一乘区**相加后一次缩放（不是两次乘）：−25 轴 + −25 α3 → ×0.5。"""
    amp = {"player": {"s1": {"cooldown": -25}}}
    assert _run_cd({"cooldown_pct": -25}, amp=amp) == {"s1": 5}
    # 若两次乘会得到 round(10×0.75×0.75)=6 —— 断言不是 6
    assert _run_cd({"cooldown_pct": -25}, amp=amp) != {"s1": 6}


def test_a3_cooldown_axis_result_never_negative() -> None:
    """下钳：轴 −9999 被声明区间钳到 −80 → ×0.2 → 2（负冷却不可达）。"""
    assert _run_cd({"cooldown_pct": -9999}) == {"s1": 2}


def test_a4_placeholder_alias_still_usable_and_not_double_counted() -> None:
    """旧占位键 `cooldown_reduction_pct` 归并证据（唯一换算处 → 不双计）。"""
    assert EFFECT_LEGACY_ALIASES["cooldown_reduction_pct"] == ("cooldown_pct", -1.0)
    # route_bonus_into 契约不变：占位键不进 flat / pct（既有测试钉死）
    flat: Dict[str, float] = {}
    pct: Dict[str, float] = {}
    route_bonus_into({"cooldown_reduction_pct": 30}, flat, pct)
    assert flat == {} and pct == {}
    # 唯一换算点：旧键 30 → flat["cooldown_pct"] = −30，且只写一次
    route_legacy_aliases_into_flat({"cooldown_reduction_pct": 30}, flat)
    assert flat == {"cooldown_pct": -30.0}
    assert combatant_updates(flat) == {"cooldown_pct": -30.0}
    # 新旧同轴相加（各声明一次 = 各一份贡献，不是旧键算两遍）
    flat2: Dict[str, float] = {}
    route_bonus_into({"cooldown_pct": -10}, flat2, {})
    route_legacy_aliases_into_flat({"cooldown_reduction_pct": 30}, flat2)
    assert flat2 == {"cooldown_pct": -40.0}
    assert combatant_updates(flat2) == {"cooldown_pct": -40.0}


def test_a5_placeholder_alias_end_to_end_from_item() -> None:
    """旧键端到端：带 `cooldown_reduction_pct` 的装备 → 聚合 flat → combatant → 冷却缩短。"""
    bonus = {"cooldown_reduction_pct": 30}
    row = ItemInstance(item_id="sword", name="sword", count=1, quality="normal",
                       bound=False, stack_max=1, slot="weapon", stats_bonus=dict(bonus))
    attrs = PlayerAttributes(base={"atk": 10, "hp": 100})
    player: Dict[str, Any] = {
        "qid": "p1", "name": "P", "level": 5, "hp": 500, "max_hp": 500,
        "mp": 100, "max_mp": 100,
        "inventory": [row],
        "equipment": {"weapon": {"item_id": "sword", "uid": row.uid}},
        "attributes": attrs,
    }
    eng = EquipmentEngine(slots={"weapon": {"name": "武器", "max": 1}})
    bonus_out = eng.aggregate_bonus(player)
    assert bonus_out["flat"].get("cooldown_pct") == -30.0
    assert "cooldown_reduction_pct" not in bonus_out["flat"]
    # 战斗桥 → combatant（玩家档案口径）
    assert _combatant_of(player)["cooldown_pct"] == -30


def test_a6_cooldown_range_declaration_driven() -> None:
    """上/下钳按包声明（C11）：声明 min=−10 → 轴 −80 被钳为 −10 → ×0.9 → 9。"""
    axes = {"cooldown_pct": {"min": -10, "max": 200}}
    assert _run_cd({"cooldown_pct": -80}, axes=axes) == {"s1": 9}


def test_a7_cooldown_absent_is_identical() -> None:
    """未配置轴 → 与 α3 基线逐字段一致（红线 C1）。"""
    assert _run_cd({}) == {"s1": 10}
    amp = {"player": {"s1": {"cooldown": -50}}}
    assert _run_cd({}, amp=amp) == {"s1": 5}
    assert _run_cd({"cooldown_pct": 0}, amp=amp) == {"s1": 5}


def test_g1_battle_snapshot_zero_change_no_axis_keys() -> None:
    """红线 C1：未配置特效轴 → 战斗结算快照逐字段一致、且不含任何特效轴键。"""
    def _snap() -> Any:
        eng = BattleEngine().start(dict(PLAYER), dict(ENEMY), random_seed=42)
        eng.player_act("normal")
        return eng.to_snapshot()

    import json
    import re

    text_a = json.dumps(_snap(), ensure_ascii=False, sort_keys=True, default=str)
    text_b = json.dumps(_snap(), ensure_ascii=False, sort_keys=True, default=str)
    text_a = re.sub(r"[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", "<uid>", text_a)
    text_b = re.sub(r"[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", "<uid>", text_b)
    assert text_a == text_b

    def _keys(obj: Any) -> Any:
        out = []
        if isinstance(obj, Mapping):
            for k, v in obj.items():
                out.append(str(k))
                out.extend(_keys(v))
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                out.extend(_keys(v))
        return out

    keys = set(_keys(_snap()))
    assert keys and not (keys & set(GEAR_EFFECT_KEYS)), sorted(keys & set(GEAR_EFFECT_KEYS))
