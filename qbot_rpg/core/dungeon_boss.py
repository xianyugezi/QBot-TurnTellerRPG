"""BOSS 版副本流程状态机（M3 批次5·路O：M19 BOSS 版流程 + M20 BOSS 三阶段机制与换区联动）。

依据：细化_2a3 §2.3 + 2a2 + m3_shared_contract §3/§4.2
  - 细化_2a3_副本两型流程.md §2.3（S3 BOSS 换区追击「高潮」/ S4 决战阶段机制三阶段表：
    阶段1 100-60% 常规 → 阶段2 60-30% 狂暴 + 换区 PV 恢复一半 → 阶段3 30-0% 绝境大招循环）
  - 细化_2a2_换区追击流程.md（R1-R27：残血阈值触发 / PV 半恢复满值口径向下取整 R9 /
    残血保持不重置 R12-R13 / 追到续战 = 残血 + PV 半值 + 开场技 R19-R20）
  - m3_shared_contract §3（enemies zone_change 配置：enabled/hp_threshold/targets/timing）
    + §4.2（副本内状态集 S0-S7 + 迁移表 M1-M15：M5 换区→S3、M6 追到→S4、M7 再换区、
    M8 击杀→S5、M9 战斗死亡→S6）

范围：BOSS 房进入校验（守门怪 gate_guard 需先击败）→ 决战三阶段阈值（phase_for）→
残血换区触发（should_zone_change）→ 追到续战准备标记（on_chase_continue）。

工程补白（定稿/契约未明示处，显式标注，不冒充定稿）：
  1. 守门怪标记：gate_guard 为 maps.json 节点级字段（细化_2a1a §1.7）；dungeon_def 级
     gate_guard 为工程扩展（schema 未列，解析优先级 dungeon_def > maps）。已击败标记 =
     session 键 "gate_guards_defeated"（当前副本实例内已击败守门怪 id 集合；支持
     set/list/tuple/frozenset/Mapping）。core/dungeon.py DungeonSession 尚未落盘（批次5
     ·路N 并行），本路以扁平 dict 键承载，收口时对齐路N 字段。
  2. zone_change.timing 枚举键 after_action / phase_changed（对齐 dungeon_models
     ZONE_CHANGE_TIMINGS 工程补白）；phase_changed 语义衔接 monster_phases
     PhaseTable.detect_transition 的 changed / phase_changed_event：enemy_state 显式传
     phase_changed 标志（本结算点是否发生阶段切换）时严格判定；未传则仅按阈值判定
     （after_action 口径）。
  3. 三阶段阈值：默认 (100, 60, 30)，边界归下阶段（60% 整 → 阶段2、30% 整 → 阶段3，
     衔接 monster_phases PhaseTable 工程收敛 1）。phases 配置可覆盖（构造器 phases
     参数 > boss_def.phases > 默认阈值）。phase_for 对输入夹取至 [0,100] 百分比定义域。
  4. on_chase_continue 返回续战准备标记 + PV 半值计算值：pv_half_value =
     floor(pv_max × pv_recover)（2a2 §2.1 满值口径，pv_recover 取 zone_change 子段或
     缺省 0.5）。标记键与契约 §3.2 续战语义一一对应（resume 续战 / hp_keep 残血保持
     R12-R13 / pv_half PV 半恢复 R9 / opening_skill 换区后第一回合开场技 R20）。
  5. 战斗资源操作零直扣：本模块产出纯判定/准备数据；残血保持、PV 半恢复、开场技的实际
     战斗接线由批次 6 经 1g4 battle_boundary 通道消费（批次6 world/chase.py 负责换区
     逃跑/候选区随机/玩家走通道追击/实际续战接线；本路只做 BOSS 三阶段状态机 + 换区
     触发接口预留）。
  6. 入场限制（entry_item 扣道具 / entry_limit 次数，场所校验先于消耗）属副本入口
     M1 → S0 流程，为 core/dungeon.py enter_dungeon（批次5·路N）职责，本路不重复实现。

铁律：零 NoneBot import；纯函数无 IO；平台无关（m3 铁律 4）；每功能可追溯（铁律 8）。
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from qbot_rpg.core.monster_phases import DEFAULT_THRESHOLDS, PhaseTable

__all__ = [
    "BossFlow",
    "DEFAULT_PHASE_THRESHOLDS",
    "DEFAULT_PV_RECOVER",
    "SESSION_GATE_GUARDS_KEY",
    "ZC_TRIGGER_AFTER_ACTION",
    "ZC_TRIGGER_PHASE_CHANGED",
]

# -------------------------------------------------------------------------------------
# 常量（工程补白见模块 docstring）
# -------------------------------------------------------------------------------------

#: 决战三阶段默认阈值（100-60/60-30/30-0，2a3 §2.3 S4 阶段表；衔接 monster_phases）。
DEFAULT_PHASE_THRESHOLDS: Sequence[float] = tuple(float(t) for t in DEFAULT_THRESHOLDS)

#: 换区/续战 PV 恢复比例缺省值（2a2 §2.1 pv_recover 0.5，向下取整）。
DEFAULT_PV_RECOVER: float = 0.5

#: session 已击败守门怪标记键（工程补白 1）。
SESSION_GATE_GUARDS_KEY: str = "gate_guards_defeated"

#: zone_change.timing 枚举键：行动后触发（怪物回合行动结算后，2a2 R5）。
ZC_TRIGGER_AFTER_ACTION: str = "after_action"

#: zone_change.timing 枚举键：阶段切换后触发（衔接 monster_phases phase_changed）。
ZC_TRIGGER_PHASE_CHANGED: str = "phase_changed"


# -------------------------------------------------------------------------------------
# 纯函数辅助（dict 或 Def 对象统一读取 / 血量百分比 / PV 半值）
# -------------------------------------------------------------------------------------


def _cfg_get(cfg: Any, key: str, default: Any = None) -> Any:
    """从 dict / Mapping / BaseDef（.get）等任意带 get 的对象读取配置值。"""
    if cfg is None:
        return default
    if isinstance(cfg, Mapping):
        return cfg.get(key, default)
    getter = getattr(cfg, "get", None)
    if callable(getter):
        return getter(key, default)
    return default


def _hp_pct(enemy_state: Mapping[str, Any]) -> Optional[float]:
    """从 enemy_state 读取血量百分比（0-100）。

    {hp, max_hp} → hp/max_hp×100；{hp_pct} → 百分比直读（2a2 §1.1 阈值口径统一为
    百分比，避免绝对数值随配置档漂移）；不可解 → None（视为无法判定，不触发换区）。
    """
    if not isinstance(enemy_state, Mapping):
        return None
    hp = enemy_state.get("hp")
    max_hp = enemy_state.get("max_hp")
    if (
        isinstance(hp, (int, float))
        and not isinstance(hp, bool)
        and isinstance(max_hp, (int, float))
        and not isinstance(max_hp, bool)
        and max_hp > 0
    ):
        return hp / max_hp * 100.0
    pct = enemy_state.get("hp_pct")
    if isinstance(pct, (int, float)) and not isinstance(pct, bool):
        return float(pct)
    return None


def _pv_half_value(pv_max: Optional[float], pv_recover: float) -> int:
    """PV 半恢复值：floor(pv_max × pv_recover)（2a2 §2.1 满值口径，向下取整）。

    例：PV=300 → 150；PV=201（奇数）→ 100；普通怪 PV=15 → 7。不可解 → 0。
    """
    if pv_max is None or pv_max < 0:
        return 0
    try:
        product = float(pv_max) * float(pv_recover)
    except (TypeError, ValueError):
        return 0
    return int(product // 1)


# -------------------------------------------------------------------------------------
# BossFlow：BOSS 房进入 / 三阶段 / 换区触发 / 续战准备
# -------------------------------------------------------------------------------------


class BossFlow:
    """BOSS 版副本流程状态机（M19 BOSS 房进入/守门怪 + M20 三阶段机制与换区联动）。

    纯逻辑、零 IO：所有输入（boss_def / dungeon_def / session / maps / player_ctx /
    enemy_state / cfg）皆为调用方传入的数据，本类不读写外部存储、不直扣战斗资源。
    """

    def __init__(
        self,
        boss_def: Any,
        dungeon_def: Any,
        session: Any,
        maps: Optional[Mapping[str, Any]] = None,
        phases: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> None:
        """Args:
            boss_def: BOSS 怪物配置（EnemyDef 或 dict；读取 zone_change / phases / pv）。
            dungeon_def: 副本配置（DungeonDef 或 dict；读取 boss_room / boss / gate_guard）。
            session: 副本会话（DungeonSession 或 dict；读取已击败守门怪标记 / boss_state）。
            maps: 地图注册表 map_id → MapDef/dict（节点级 gate_guard 查询，2a1a §1.7）。
            phases: 阶段配置覆盖 [{threshold, ...}]（工程补白 3；缺省 → boss_def.phases
                → 默认阈值 (100,60,30)）。
        """
        self._boss = boss_def
        self._dungeon = dungeon_def
        self._session = session
        self._maps = maps if isinstance(maps, Mapping) else {}

        phase_cfg = phases
        if phase_cfg is None:
            phase_cfg = _cfg_get(boss_def, "phases")
        if phase_cfg is None:
            phase_cfg = _cfg_get(dungeon_def, "boss_phases")
        self._phase_table = PhaseTable(
            phases=phase_cfg if isinstance(phase_cfg, (list, tuple)) else None,
            monster_name=str(_cfg_get(boss_def, "name", "") or ""),
            default_thresholds=DEFAULT_PHASE_THRESHOLDS,
        )

    # ------------------------------------------------------------ 会话/配置读取

    def _session_get(self, key: str, default: Any = None) -> Any:
        return _cfg_get(self._session, key, default)

    def _resolve_boss_room(self) -> Optional[str]:
        """BOSS 房地图 ID（dungeon_def.boss_room，m3 §4.1）。"""
        room = _cfg_get(self._dungeon, "boss_room")
        return room if isinstance(room, str) and room else None

    def _resolve_gate_guard(self) -> Optional[str]:
        """守门怪解析（工程补白 1）：dungeon_def.gate_guard → BOSS 房地图 gate_guard。"""
        gg = _cfg_get(self._dungeon, "gate_guard")
        if isinstance(gg, str) and gg:
            return gg
        room = self._resolve_boss_room()
        if room is None:
            return None
        map_cfg = _cfg_get(self._maps, room)
        if map_cfg is None:
            return None
        mg = _cfg_get(map_cfg, "gate_guard")
        return mg if isinstance(mg, str) and mg else None

    def _gate_guard_defeated(self, gate_guard: str) -> bool:
        """session 已击败标记查询（工程补白 1：gate_guards_defeated 集合/映射内）。"""
        defeated = self._session_get(SESSION_GATE_GUARDS_KEY)
        if defeated is None:
            return False
        if isinstance(defeated, (set, frozenset, list, tuple)):
            return gate_guard in defeated
        if isinstance(defeated, Mapping):
            return bool(defeated.get(gate_guard, False))
        return False

    # ------------------------------------------------------------ M19 BOSS 房进入

    def enter_boss_room(
        self, player_ctx: Optional[Mapping[str, Any]] = None
    ) -> dict:
        """BOSS 房进入检查（M19：守门怪 gate_guard 需先击败，未击败返回拦截）。

        判定链：场所校验（player_ctx.map_id == boss_room，缺省跳过）→ 守门怪解析 →
        session 已击败标记。拦截/放行为纯判定结果，不消耗资源（entry_item 扣减与
        entry_limit 计数属副本入口 M1 流程，core/dungeon.py enter_dungeon 职责）。

        Args:
            player_ctx: 玩家上下文 {map_id?, boss_hp?, boss_max_hp?}（可选）。

        Returns:
            拦截: {"allowed": False, "reason": "gate_guard" | "wrong_room", ...}
            放行: {"allowed": True, "room": <boss_room>, "boss": <boss_id>,
                   "gate_guard": <守门怪 id 或 None>, "phase": <阶段号或 None>}
        """
        room = self._resolve_boss_room()
        boss_id = _cfg_get(self._dungeon, "boss")
        if not isinstance(boss_id, str) or not boss_id:
            boss_id = None

        # 场所校验：player_ctx 提供 map_id 时校验当前图 == BOSS 房（工程补白：缺省跳过）
        if isinstance(player_ctx, Mapping):
            cur = player_ctx.get("map_id")
            if (
                isinstance(cur, str)
                and cur
                and room is not None
                and cur != room
            ):
                return {
                    "allowed": False,
                    "reason": "wrong_room",
                    "room": room,
                    "boss": boss_id,
                    "player_map": cur,
                }

        gate_guard = self._resolve_gate_guard()
        if gate_guard is not None and not self._gate_guard_defeated(gate_guard):
            return {
                "allowed": False,
                "reason": "gate_guard",
                "gate_guard": gate_guard,
                "room": room,
                "boss": boss_id,
                "message": f"守门怪 {gate_guard} 尚未击败，无法进入 BOSS 房",
            }

        return {
            "allowed": True,
            "room": room,
            "boss": boss_id,
            "gate_guard": gate_guard,
            "phase": self._boss_phase_from_ctx(player_ctx),
        }

    def _boss_phase_from_ctx(
        self, player_ctx: Optional[Mapping[str, Any]]
    ) -> Optional[int]:
        """player_ctx/session.boss_state 带 BOSS 血量时顺手给出当前阶段（可选便利）。"""
        if isinstance(player_ctx, Mapping):
            hp = player_ctx.get("boss_hp")
            mhp = player_ctx.get("boss_max_hp")
            if (
                isinstance(hp, (int, float))
                and not isinstance(hp, bool)
                and isinstance(mhp, (int, float))
                and not isinstance(mhp, bool)
                and mhp > 0
            ):
                return self.phase_for(hp / mhp * 100.0)
        boss_state = self._session_get("boss_state")
        if isinstance(boss_state, Mapping):
            hp = boss_state.get("hp")
            mhp = boss_state.get("max_hp")
            if (
                isinstance(hp, (int, float))
                and not isinstance(hp, bool)
                and isinstance(mhp, (int, float))
                and not isinstance(mhp, bool)
                and mhp > 0
            ):
                return self.phase_for(hp / mhp * 100.0)
        return None

    # ------------------------------------------------------------ M20 三阶段机制

    def phase_for(self, hp_pct: float) -> int:
        """HP 百分比 → 决战阶段号（M20 三阶段机制，2a3 §2.3 S4 阶段表）。

        默认阈值 100-60/60-30/30-0（边界归下阶段：60% → 2、30% → 3），phases 配置可
        覆盖（构造器 phases > boss_def.phases > 默认）。衔接 monster_phases.PhaseTable
        （细化_1f phase_changed 联动语义：阶段切换由 detect_transition 判定）。
        输入夹取至 [0,100] 百分比定义域（工程补白 3）。
        """
        try:
            pct = float(hp_pct)
        except (TypeError, ValueError):
            pct = 0.0
        pct = max(0.0, min(100.0, pct))
        return self._phase_table.resolve_phase(pct)

    # ------------------------------------------------------------ M20 换区联动

    def should_zone_change(
        self, enemy_state: Mapping[str, Any], cfg: Any = None
    ) -> bool:
        """BOSS 残血换区触发判定（M20 换区联动 / m3 §3.2 R1-R6 + 2a2 §1.1）。

        cfg = enemies zone_change 配置 {enabled, hp_threshold, targets, timing,
        pv_recover?}；cfg 缺省 → 取 boss_def.zone_change。判定链（2a2 R1-R4/R3）：
          1. cfg 缺失 / enabled=False / targets 空 → 永不换区（R4）
          2. hp=0 → 击杀优先，不进换区（R3）
          3. hp_pct > hp_threshold×100 → 不触发（R1/R2，不残血不换区）
          4. timing=phase_changed 且本结算点无阶段切换（enemy_state.phase_changed
             假或未传）→ 不触发（衔接 monster_phases phase_changed 语义）
          5. 其余 → 触发（条件满足即必换区，无概率博弈，R6）

        Args:
            enemy_state: 怪物状态 {hp, max_hp} 或 {hp_pct}（百分比）；phase_changed
                可选标志（timing=phase_changed 时参与判定）。
            cfg: zone_change 配置子段；缺省 → boss_def.zone_change。
        """
        if not isinstance(cfg, Mapping):
            cfg = _cfg_get(self._boss, "zone_change")
        if not isinstance(cfg, Mapping):
            return False
        if _cfg_get(cfg, "enabled", True) is False:
            return False
        if not _cfg_get(cfg, "targets"):
            return False  # 候选区缺失/为空 = 永不换区（2a2 R4）
        pct = _hp_pct(enemy_state)
        if pct is None:
            return False
        threshold = _cfg_get(cfg, "hp_threshold")
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            return False
        threshold = float(threshold)
        if pct <= 0.0:
            return False  # hp=0 击杀优先（R3）
        if pct > threshold * 100.0:
            return False  # 不残血不触发（R1/R2）
        timing = _cfg_get(cfg, "timing", ZC_TRIGGER_AFTER_ACTION)
        if timing == ZC_TRIGGER_PHASE_CHANGED:
            if not isinstance(enemy_state, Mapping) or not enemy_state.get("phase_changed"):
                return False
        return True

    # ------------------------------------------------------------ 追到续战准备

    def on_chase_continue(
        self, player_ctx: Optional[Mapping[str, Any]] = None
    ) -> dict:
        """追到续战准备（M6 追到 → S4 决战：残血保持 + PV 半恢复 + 开场技）。

        返回续战标记 + PV 半值计算值；不直扣任何战斗资源——实际续战战斗接线由批次 6 经
        1g4 battle_boundary 通道消费本 dict：
          resume: True       进行中战斗续战（追到触发遭遇，2a2 R19）
          hp_keep: True      残血保持（不重置不回血，R12/R13）
          pv_half: True      PV 半恢复触发标记（R9）
          pv_half_value      floor(pv_max × pv_recover)（满值口径向下取整，§2.1）
          pv_recover         恢复比例（zone_change.pv_recover 或缺省 0.5）
          opening_skill: True 换区后第一回合怪物开场技（R20 / 细化_1f 开场技触发点）
          timing             "chase_continue"
        player_ctx 为签名对齐预留（批次 6 接线传续战上下文；本路不消费）。
        """
        pv_max = _cfg_get(self._boss, "pv")
        if not isinstance(pv_max, (int, float)) or isinstance(pv_max, bool):
            pv_max = None
        zc = _cfg_get(self._boss, "zone_change")
        recover = DEFAULT_PV_RECOVER
        if isinstance(zc, Mapping):
            r = _cfg_get(zc, "pv_recover", DEFAULT_PV_RECOVER)
            if isinstance(r, (int, float)) and not isinstance(r, bool):
                recover = float(r)

        result: dict = {
            "resume": True,
            "hp_keep": True,
            "pv_half": True,
            "pv_half_value": _pv_half_value(pv_max, recover),
            "pv_recover": recover,
            "opening_skill": True,
            "timing": "chase_continue",
        }
        # 残血保持数据源透传（session.boss_state 血量快照；供批次 6 接线核对）
        boss_state = self._session_get("boss_state")
        if isinstance(boss_state, Mapping):
            hp = boss_state.get("hp")
            mhp = boss_state.get("max_hp")
            if (
                isinstance(hp, (int, float))
                and not isinstance(hp, bool)
                and isinstance(mhp, (int, float))
                and not isinstance(mhp, bool)
                and mhp > 0
            ):
                result["boss_hp"] = hp
                result["boss_max_hp"] = mhp
        return result
