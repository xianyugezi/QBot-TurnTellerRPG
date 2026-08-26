"""换区追击续战装配 + 离开副本重置（M3 批次6·路R：M14 换区续战装配 + M15 离开副本重置）。

依据：
  - 细化_2a2_换区追击流程.md §2-4（PV 半恢复 R9/R10/R11：满值口径向下取整 + 门禁语义 debuff
    层数保留破防全量爆发；血量保持不重置 R12/R13；追到续战 R19-R21：残血 + PV 半值 + 开场技；
    快照与持久化 §3.3）+ §5（离开副本重置 R24/R25）
  - m3_shared_contract §3.2（换区规则要点：续战 BOSS 残血保持 + PV 半恢复向下取整 + 开场技 +
    血量不重置；门禁语义 debuff 层数保留）+ §4.4（快照续玩 ai_state+combo_state 全保留；
    死亡 ≠ 离开，离开即重置；副本会话持久化含换区上下文）
  - 规划_路2a_地图副本.md M14（换区后战斗续接：不新建战斗实体、同会话续接、PV=floor(PV×pv_recover)）
    + M15（离开副本重置界定：非战斗离开、恢复入口明示）
  - 衔接细化_1g4_战斗世界边界.md J-01（换区 PV 恢复裁决：HP 残血保留 + PV 恢复半值 + 开场技
    并行不冲突）/ 1g3（战斗快照续战）/ 1f（开场技 battle_start 触发点）

职责（world 层纯逻辑：零 NoneBot import、零 IO、纯函数，返回数据不落库、不改入参）：
  prepare_resume_battle   M14：追到后装配续战战斗上下文（残血保持 + PV 半恢复 + 开场技 +
                         战斗快照续接 ai_state 保留）→ 战斗侧消费
  exit_dungeon_reset      M15：非战斗离开 → 副本全清（BOSS/残血/子任务/休息/换区上下文）+
                         回外部锚点 + 重置信号；死亡离开同样重置（死亡 ≠ 离开，离开即重置）

工程补白（定稿/契约未明示处，显式标注，不冒充定稿）：
  1. chase_ctx 契约：本路消费 world/chase.py（批次6·路Q 并行）pursue 的返回——捕获
     {caught: True, target_map, chase_over: True, continue_data?}（chase.py 补白 6：
     捕获时内嵌 bf.on_chase_continue() 结果于 continue_data）。追到与否由 caught 判定：
     未追到 → 拒绝装配（resume: False, reason: not_caught），不产出续战标记。
  2. pv_half_value 满值口径优先级（2a2 §2.1）：chase_ctx.continue_data.pv_half_value
     （路O on_chase_continue 按 boss_def.pv 满值预计算，权威）→ chase_ctx.pv_half_value
     → enemy_state.pv_max / max_pv → enemy_state.pv（当前值近似满值，仅兜底）。公式
     floor(pv_max × pv_recover)，pv_recover 取 continue_data.pv_recover /
     chase_ctx.pv_recover / zone_change.pv_recover / 缺省 0.5。
  3. 开场技 opening_skill 仅为续战标记；实际战斗首回合开场技触发由战斗侧接线（细化_1f
     battle_start 触发点，2a2 §4.5 R20），本路不接线、不触发。
  4. PV 门禁语义（R11）：pv_half_value > 0 即门禁重新建立——此前 debuff 层数保留、效果减半，
     破防（PV=0）后全量爆发；层数保留/减半的实际战斗结算由 1g4 battle_boundary 通道消费本
     dict 的 pv_half / pv_half_value 键，本路只产标记。
  5. battle_ready 反映是否持有进行中战斗快照（battle_state 非空）→ 同会话续接；battle_state
     缺省（None）时 battle_ready: False、reason: missing_snapshot，resume 语义仍成立
     （残血/PV 半值/开场技由接线按副本 BOSS 状态持久化重建战斗实体——2a2 §3.3）。
  6. exit_dungeon_reset 纯函数不改入参：返回清空后新会话（session 键）+ external_anchor；
     玩家位置回外部锚点（R8）由接线层落地。战斗中离开判定源 = player_ctx 战斗标志
     （in_battle/battle_active/in_combat/battle_session_id/battle_state 非空），战斗中断
     ≠ 离开（2a2 §5.2，走快照续玩 M27）。
  7. 换区上下文全清两种落位形态：boss_state 内（chasing/pv/zone_target）与 session 顶层
     （chase_ctx/zone_chase/chase/chasing/chase_target）——m3 §4.4 换区上下文随副本会话持久化。
  8. 离开判定点「玩家当前图已脱离 dungeon.maps 集合」（2a2 §5.1 R24）由接线层出口通道事件
     前置保证，本函数只做重置装配。

铁律：零 NoneBot import；纯函数无 IO；平台无关；每功能可追溯（m3 铁律 4/8）。
"""

from __future__ import annotations

import dataclasses
from typing import Any, Mapping, Optional

__all__ = [
    "DEFAULT_PV_RECOVER",
    "MESSAGE_HINT_LEAVE_RESET",
    "MESSAGE_HINT_BATTLE_ONGOING",
    "STATE_LEFT",
    "prepare_resume_battle",
    "exit_dungeon_reset",
]

# -------------------------------------------------------------------------------------
# 常量（工程补白见模块 docstring）
# -------------------------------------------------------------------------------------

#: 换区/续战 PV 恢复比例缺省值（2a2 §2.1 pv_recover 0.5，向下取整；对齐 dungeon_boss）。
DEFAULT_PV_RECOVER: float = 0.5

#: 离开副本重置提示（M15 恢复入口明示，R25 尾部）。
MESSAGE_HINT_LEAVE_RESET: str = "离开副本将重置"

#: 战斗中离开拒绝提示（R25 完整文案：「战斗中断可续玩，离开副本将重置」）。
MESSAGE_HINT_BATTLE_ONGOING: str = "战斗中断可续玩，离开副本将重置"

#: 离开态（副本重置）状态键（对齐 core.dungeon S7 = "LEFT"；world 层自持常量避免跨层依赖）。
STATE_LEFT: str = "LEFT"

#: 战斗中离开判定源键（补白 6：战斗中断 ≠ 离开，2a2 §5.2）。
_BATTLE_FLAG_KEYS: tuple = ("in_battle", "battle_active", "in_combat", "battle_session_id")

#: 换区上下文顶层键（补白 7：随副本会话持久化的换区上下文形态，全清）。
_ZONE_CHASE_KEYS: tuple = ("chase_ctx", "zone_chase", "chase", "chasing", "chase_target")


# -------------------------------------------------------------------------------------
# 纯函数辅助（dict / dataclass / Def 对象统一读取 + 数值校验 + PV 半值）
# -------------------------------------------------------------------------------------


def _get(cfg: Any, key: str, default: Any = None) -> Any:
    """从 dict / Mapping / 任意带 get 或属性对象读取配置值（对齐 dungeon_boss._cfg_get）。"""
    if cfg is None:
        return default
    if isinstance(cfg, Mapping):
        return cfg.get(key, default)
    getter = getattr(cfg, "get", None)
    if callable(getter):
        return getter(key, default)
    return default


def _num(value: Any) -> bool:
    """数值校验（排除 bool——bool 是 int 子类）。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _pv_half_value(
    pv_current: Optional[float], pv_max: Optional[float], pv_recover: float
) -> int:
    """PV 恢复后值：current + floor((max − current) × pv_recover)（缺失量口径，向下取整）。

    2026-08-26 用户拍板（设计审查批次2 P1-1）：恢复「已损失的一半」——
    pv_recover=0 → 不恢复（保持当前值）、1 → 补满全恢复（与定稿 L98 双锚点自洽）；
    破防场景 current=0 与原满值口径数值一致（例：PV=300 破防 → 150；PV=201 破防 → 100）。
    pv_current 缺失 → 近似 pv_max（未破防不降）。
    """
    if pv_max is None or pv_max < 0:
        return 0
    try:
        cur = (
            float(pv_current)
            if isinstance(pv_current, (int, float)) and not isinstance(pv_current, bool)
            else float(pv_max)
        )
        cur = min(cur, float(pv_max))
        loss = float(pv_max) - cur
        return int((cur + loss * float(pv_recover)) // 1)
    except (TypeError, ValueError):
        return 0


# -------------------------------------------------------------------------------------
# M14：追到续战装配（残血保持 + PV 半恢复 + 开场技 + 战斗快照续接）
# -------------------------------------------------------------------------------------


def prepare_resume_battle(
    chase_ctx: Any,
    enemy_state: Optional[Mapping[str, Any]] = None,
    battle_state: Optional[Mapping[str, Any]] = None,
) -> dict:
    """追到后构建续战战斗上下文（M14 换区后战斗续接，2a2 §4.5 R19-R21 + m3 §3.2）。

    Args:
        chase_ctx: 追击上下文 = world/chase.py pursue 捕获返回 {caught, target_map,
            continue_data?}；continue_data = 路O on_chase_continue 结果（预计算
            pv_half_value / pv_recover / boss_hp，补白 1/2）。
        enemy_state: 怪物战斗状态 {hp, max_hp, pv, pv_max?}；血量保持残血不重置
            （R12/R13），PV 满值口径取 pv_max / max_pv / pv（补白 2）。
        battle_state: 进行中战斗快照（1g4 BattleSnapshot dict 形态；透传，ai_state /
            combo_state 保留——m3 §4.4，1g3 快照续战）。

    Returns:
        续战上下文 dict：
          resume: True              进行中战斗续战（追到触发遭遇，R19）
          hp_keep: True             残血保持（血量不重置不回血，R12/R13）
          pv_half: True             PV 半恢复触发标记（R9）
          pv_half_value             floor(pv_max × pv_recover)（满值口径向下取整）
          pv_recover                恢复比例（continue_data / chase_ctx / zone_change /
                                    缺省 0.5）
          opening_skill: True       换区后第一回合怪物开场技（R20；触发由战斗侧接线，补白 3）
          battle_ready              battle_state 非空（同会话快照续接；缺省 → False，补白 5）
          timing: "chase_continue"  续战语义标记（对齐 dungeon_boss.on_chase_continue）
          boss_hp / boss_max_hp     残血透传（数据源 = enemy_state → continue_data.boss_hp）
          ai_state / combo_state    战斗快照保留（battle_state 提供时透传）
          battle_state              快照透传（引用；纯函数不改写，补白 5）
          chase_target              追击目标图（chase_ctx.target_map，可选）
        未追到（caught 非真）：{resume: False, battle_ready: False, reason: "not_caught",
          message, hp_keep/pv_half/opening_skill: False, pv_half_value: 0, timing: None}
    """
    chase = chase_ctx if isinstance(chase_ctx, Mapping) else {}
    if not chase.get("caught"):
        return {
            "resume": False,
            "battle_ready": False,
            "reason": "not_caught",
            "message": "未追到 BOSS，无法装配续战（M13 错失窗口）",
            "hp_keep": False,
            "pv_half": False,
            "opening_skill": False,
            "pv_half_value": 0,
            "timing": None,
        }

    enemy = enemy_state if isinstance(enemy_state, Mapping) else {}
    # 路O on_chase_continue 结果（路Q pursue 捕获时内嵌于 continue_data；补白 1/2）
    continue_data = chase.get("continue_data")
    cd = continue_data if isinstance(continue_data, Mapping) else {}

    # ---- 残血保持（R12/R13）：血量不重置，透传残血原值；enemy_state 不改写 ------------
    # 数据源优先级：enemy_state（战斗内残血权威）→ continue_data.boss_hp（会话持久化）
    hp = enemy.get("hp")
    mhp = enemy.get("max_hp")
    if not _num(hp):
        hp = cd.get("boss_hp")
    if not _num(mhp):
        mhp = cd.get("boss_max_hp")
    boss_hp: Optional[float] = hp if _num(hp) else None
    boss_max_hp: Optional[float] = mhp if _num(mhp) else None

    # ---- PV 半恢复（R9/R10/R11）：满值口径向下取整（补白 2 优先级） -------------------
    pv_recover = DEFAULT_PV_RECOVER
    hinted = cd.get("pv_recover")
    if not _num(hinted):
        hinted = chase.get("pv_recover")
    if _num(hinted):
        pv_recover = float(hinted)
    else:
        zc = chase.get("zone_change")
        if isinstance(zc, Mapping):
            zr = zc.get("pv_recover")
            if _num(zr):
                pv_recover = float(zr)
    precomputed = cd.get("pv_half_value")
    if not _num(precomputed):
        precomputed = chase.get("pv_half_value")
    if _num(precomputed):
        pv_half_value = int(precomputed)
    else:
        pv_max: Optional[float] = None
        for k in ("pv_max", "max_pv"):
            v = enemy.get(k)
            if _num(v):
                pv_max = v
                break
        pv_current_value: Optional[float] = enemy.get("pv") if _num(enemy.get("pv")) else None
        if pv_max is None:
            pv_max = pv_current_value  # 兜底：无上限字段时以当前值近似（补白 2）
        pv_half_value = _pv_half_value(pv_current_value, pv_max, pv_recover)

    # ---- 战斗快照续接（1g3/1g4；m3 §4.4：ai_state + combo_state 全保留） --------------
    snap = battle_state if isinstance(battle_state, Mapping) else None
    ai_state = snap.get("ai_state") if snap is not None else None
    combo_state = snap.get("combo_state") if snap is not None else None

    result: dict = {
        "resume": True,
        "hp_keep": True,
        "pv_half": True,
        "pv_half_value": pv_half_value,
        "pv_recover": pv_recover,
        "opening_skill": True,
        "battle_ready": snap is not None,
        "timing": "chase_continue",
    }
    if boss_hp is not None:
        result["boss_hp"] = boss_hp
    if boss_max_hp is not None:
        result["boss_max_hp"] = boss_max_hp
    if ai_state is not None:
        result["ai_state"] = ai_state
    if combo_state is not None:
        result["combo_state"] = combo_state
    if snap is not None:
        result["battle_state"] = battle_state
    target = chase.get("target_map")
    if not isinstance(target, str) or not target:
        target = chase.get("target")  # 别名兜底（非 chase.py 契约键）
    if isinstance(target, str) and target:
        result["chase_target"] = target
    if snap is None:
        result["reason"] = "missing_snapshot"
    return result


# -------------------------------------------------------------------------------------
# M15：离开副本重置（非战斗离开 → 副本全清 + 回外部锚点；死亡离开同样重置）
# -------------------------------------------------------------------------------------


def _read_field(session: Any, key: str, default: Any = None) -> Any:
    """从副本会话（DungeonSession dataclass / dict 持久化形态）读取字段。"""
    if session is None:
        return default
    if isinstance(session, Mapping):
        return session.get(key, default)
    return getattr(session, key, default)


def _battle_in_progress(player_ctx: Any) -> bool:
    """战斗中离开判定（补白 6：战斗中断 ≠ 离开，2a2 §5.2 —— 走快照续玩 M27）。"""
    ctx = player_ctx if isinstance(player_ctx, Mapping) else {}
    for k in _BATTLE_FLAG_KEYS:
        if ctx.get(k):
            return True
    bs = ctx.get("battle_state")
    if isinstance(bs, Mapping) and bs:
        return True
    return False


def exit_dungeon_reset(
    session: Any,
    player_ctx: Optional[Mapping[str, Any]] = None,
) -> dict:
    """非战斗离开 → 副本全清（M15 离开副本重置界定，2a2 §5 R24/R25 + m3 §4.4）。

    离开 = 非战斗 + 已离开副本区域（判定点「脱离 dungeon.maps」由接线层前置，补白 8）。
    重置范围（2a2 §5.4）：BOSS 状态 / 残血 / 子任务进度 / 休息次数 / 换区上下文全清，
    下次进入按 dungeon.json 初始状态满状态重打；死亡离开同样重置（死亡 ≠ 离开，离开即
    重置——2a2 §5.2 + m3 §4.4）。玩家位置回外部锚点（R8）由接线层落地（本函数纯返回）。

    Args:
        session: 副本会话（DungeonSession dataclass 或 to_dict 持久化 dict 形态）。
        player_ctx: 玩家上下文（战斗标志判定源：in_battle/battle_active/in_combat/
            battle_session_id/battle_state 非空 → 拒绝重置，走快照续玩）。

    Returns:
        重置成功：{reset: True, state: "LEFT", external_anchor, message_hint: "离开副本
          将重置", session: 清空后新会话, boss_state_cleared: True}
        战斗中拒绝：{reset: False, reason: "battle_in_progress", state, session,
          message_hint: "战斗中断可续玩，离开副本将重置"}
    """
    if _battle_in_progress(player_ctx):
        return {
            "reset": False,
            "reason": "battle_in_progress",
            "state": _read_field(session, "state"),
            "session": session,
            "message_hint": MESSAGE_HINT_BATTLE_ONGOING,
        }

    is_dataclass = session is not None and not isinstance(session, Mapping) and hasattr(
        session, "__dataclass_fields__"
    )
    external_anchor = _read_field(session, "external_anchor")

    # 保留元数据（副本标识 / 外部锚点 / 防跨包串档）；副本内进度全清（2a2 §5.4）
    cleared_kw: dict = {
        "state": STATE_LEFT,
        "current_map": None,
        "subquest_progress": {},
        "boss_state": {},
        "rest_count": 0,
    }

    if is_dataclass:
        cleared_kw["cleared_maps"] = frozenset()
        cleared_session = dataclasses.replace(session, **cleared_kw)
    else:
        cleared_kw["cleared_maps"] = []
        base = dict(session) if isinstance(session, Mapping) else {}
        base.update(cleared_kw)
        # 换区上下文顶层键全清（补白 7）；保留 dungeon_id/dungeon_type/external_anchor 等
        for k in _ZONE_CHASE_KEYS:
            base.pop(k, None)
        cleared_session = base

    return {
        "reset": True,
        "state": STATE_LEFT,
        "external_anchor": external_anchor,
        "message_hint": MESSAGE_HINT_LEAVE_RESET,
        "session": cleared_session,
        "boss_state_cleared": True,
    }
