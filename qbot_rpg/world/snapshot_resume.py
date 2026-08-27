"""战斗快照续玩（M27）+ 非战斗离开重置（M28）（M3 批次7·路T）。

依据：
  - 细化_1g3_快照续战与测试.md（① 战斗快照结构 §1.2 字段级：ai_state+combo_state 全保留
    S1、turn 与 snapshot_at.turn 双写；② 中断恢复流程 §2.1 退出/超时/锁屏 → 快照续玩、
    非战斗离开 → 副本重置、§2.3 恢复时序、§2.4 死亡 ≠ 中断）+ 细化_1g4_战斗世界边界.md
    （TIME-04 中断恢复「有一场未完成的战斗」、BattleSnapshot 会话形态、F-08 lost_pending）
  - m3_shared_contract.md §4.4（快照续玩：ai_state + combo_state + 换区上下文全保留；战斗
    中断不改变副本状态（走快照续玩）；非战斗离开 = 副本重置）+ §八 10（快照完整性铁律：
    战斗中断续玩 ai_state+combo_state+换区上下文逐字段一致）
  - 规划_路2a_地图副本.md M27（战斗快照续玩：ai_state+combo_state+换区上下文逐字段保留，
    恢复入口明示「战斗中断可续玩，离开副本将重置」；超时/锁屏同路径）+ M28（非战斗离开
    重置与明示文案：离开判定 = 非战斗 + 已出副本区域；战斗中断离开不触发重置，分工明确）
  - 衔接 world/chase_resume.py（M14 续战装配 / M15 exit_dungeon_reset 重置信号 + 明示文案
    「离开副本将重置」「战斗中断可续玩，离开副本将重置」）
  - 细化_M6_热重载接线.md（M6 D3）：RSM-04（续战入口世代重绑定——按快照
    registry_generation 从 watcher._snapshots N=2 滚动 + backup_snapshot() 双口取档 →
    Registry.from_snapshot 重建注入）+ RSM-09（世代一致性自检）+ RSM-02（快照
    registry_generation 字段 F-RSM-01，旧快照缺字段兼容默认 0）+ RSM-08（SessionManager
    世代绑定契约，实装归 D5）+ WIR-14（运行期删除降级：resolve→None 降级不抛异常）+
    ADR-D3-03（世代缺失降级 = 取最近 ≤ 世代档 + 告警，不拒绝恢复）

职责（world 层纯逻辑：零 NoneBot import、零 IO、纯函数，返回数据不落库、不改入参）：
  resume_from_snapshot   M27：战斗快照续玩——BattleEngine.from_snapshot 续接（ai_state +
                         combo_state + 换区上下文 chase ctx 逐字段保留），battle_factory
                         注入（真实 BattleEngine.from_snapshot 或 stub）；战斗中断（退出/
                         超时/锁屏）不改变副本状态（续玩非重置）
  non_combat_exit        M28：非战斗状态离开副本 → 调 exit_dungeon_reset 副本重置 + 明示
                         文案「战斗中断可续玩，离开副本将重置」（恢复入口明示 M27）；
                         in_battle=True 或玩家战斗标志 → 拒绝离开提示续玩（走快照）
  pick_registry_snapshot / rebind_registry_for_snapshot
                         M6 D3 RSM-04/09：续战入口世代重绑定——按快照 registry_generation
                         从 watcher 取对应 RegistrySnapshot → Registry.from_snapshot 重建
                         → 注入 from_snapshot(registry=...)；无对应档 → 取最近 ≤ 世代档 +
                         日志告警（ADR-D3-03）；世代不一致 → RSM-09 降级 + 日志

工程补白（定稿/契约未明示处，显式标注，不冒充定稿）：
  1. battle_factory 注入（BattleEngine.from_snapshot 类方法或可调用 stub）：未注入时本函数
     退化为契约形态校验闸门——resumed=False、reason="factory_missing"，校验结论由 valid /
     missing_fields 承载；注入工厂则实际构建引擎（factory(snapshot) -> engine），resumed
     表示引擎已构建续玩就绪。工厂抛错被捕获 → reason="factory_error"（防御，不吞细节）。
  2. 快照完整性校验键（1g3 §1.2 / S1）：ai_state、combo_state 键必须存在（Mapping；空
     dict 合法——1g1c B5 战斗结束清零形态），turn 必须为数值（顶层 turn 或
     snapshot_at.turn 双写任一处，1g3 §1.3）。缺任一 → reason="incomplete_snapshot" +
     missing_fields，且不调用工厂。
  3. 换区上下文（chase ctx）判定源：快照顶层键 chase_ctx/zone_chase/zone_change/chasing/
     chase_target（chase_resume 补白 7 随副本会话持久化形态）+ ai_state 内嵌
     zone_change/pv_recover_pending（1g3 §1.2）。任一存在（非 None）→
     chase_context_preserved=True，chase_fields 列出命中的字段路径（ai_state 内嵌以
     "ai_state.zone_change" 前缀形态标识，防与顶层同名键歧义）。
  4. 续玩非重置（m3 §4.4 / 2a2 §5.2）：本函数纯返回，永不改 player_ctx/快照/副本会话；
     返回恒带 reset: False + state_unchanged: True——战斗中断不改变副本状态（走快照续玩）。
  5. non_combat_exit 明示文案复用 chase_resume.MESSAGE_HINT_BATTLE_ONGOING（恢复入口明示
     完整文案「战斗中断可续玩，离开副本将重置」，M27 实现要点），成功路径挂 entry_hint 键；
     重置自身的 message_hint（「离开副本将重置」）来自 exit_dungeon_reset 透传。拒绝路径
     via_snapshot=True（走 M27 快照续玩）。
  6. in_battle 参数为显式开关（接线层可据会话/入口事件直接判战斗）；玩家战斗标志
     （in_battle/battle_active/in_combat/battle_session_id/battle_state 非空）判定委托
     exit_dungeon_reset（chase_resume 补白 6），本函数不重复实现判定链。
  7. 世代重绑定（M6 D3 RSM-04）：watcher 参数为可注入取档源（真实 HotReloadWatcher 或
     契约替身），未注入 → rebind_status="skipped" 不改变旧行为（零影响既有调用方）。
     取档经 watcher._snapshots（N=2 滚动 deque）+ backup_snapshot()（RSM-05 契约接口，
     路A 激活；getattr 防御未实装不崩）双口；重建 Registry 用真实
     Registry.from_snapshot（content 层零 NoneBot，无环依赖）。工厂调用约定：注入 watcher
     且重建成功时 battle_factory(snap, registry=reg)（BattleEngine.from_snapshot 的
     registry 关键字透传，RSM-03）；否则 battle_factory(snap) 原样。
  8. 世代一致性自检（M6 D3 RSM-09）：重绑定后 registry.generation != 快照世代 → 判定
     degraded=True + _logger.warning 告警（含目标/实际世代）；日志仅观察性输出，不影响
     返回结构（degraded 键承载结论），纯函数契约保持。
  9. SessionManager 世代绑定契约（M6 D3 RSM-08 / F-RSM-02）：会话创建时刻世代随会话
     payload 持久化 + restore 按世代重绑定（复用本模块取档逻辑）——契约由 D3 定义，
     SessionManager 实装（acquire/release/get_active/suspend/restore 非桩）归 D5（批5），
     本模块不实现、不引入 session 依赖。

铁律：零 NoneBot import；纯函数无业务 IO；平台无关；每功能可追溯（m3 铁律 4/8）。
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional, Tuple

from qbot_rpg.content.registry import Registry
from qbot_rpg.world.chase_resume import (
    MESSAGE_HINT_BATTLE_ONGOING,
    exit_dungeon_reset,
)

_logger = logging.getLogger("qbot_rpg.world.snapshot_resume")

__all__ = [
    "MESSAGE_HINT_BATTLE_ONGOING",
    "resume_from_snapshot",
    "non_combat_exit",
    "snapshot_registry_generation",
    "pick_registry_snapshot",
    "rebind_registry_for_snapshot",
]

# -------------------------------------------------------------------------------------
# 常量（工程补白见模块 docstring）
# -------------------------------------------------------------------------------------

#: 快照完整性校验键（1g3 §1.2 / S1：ai_state+combo_state 全保留 + turn 双写；补白 2）。
_SNAPSHOT_REQUIRED_KEYS: tuple = ("ai_state", "combo_state", "turn")

#: 换区上下文顶层键（补白 3：随副本会话持久化的换区上下文形态，对齐 chase_resume 补白 7）。
_CHASE_CTX_KEYS: tuple = ("chase_ctx", "zone_chase", "zone_change", "chasing", "chase_target")

#: 换区上下文 ai_state 内嵌键（1g3 §1.2 ai_state 形态）。
_AI_STATE_CHASE_KEYS: tuple = ("zone_change", "pv_recover_pending")

#: 世代重绑定状态（M6 D3 RSM-04 / ADR-D3-03）。
_REBIND_EXACT = "exact"        # 精确世代匹配（同 generation 档命中）
_REBIND_FALLBACK = "fallback"  # 无精确档 → 最近一份世代 ≤ 目标档（ADR-D3-03 降级）
_REBIND_NONE = "none"          # 无任何可用档 → 不绑定（引擎走默认解析，降级）
_REBIND_SKIPPED = "skipped"    # 未注入 watcher → 不重绑定（旧行为零影响）


# -------------------------------------------------------------------------------------
# 纯函数辅助（dict / dataclass 统一读取 + 数值校验 + 快照字段收集）
# -------------------------------------------------------------------------------------


def _num(value: Any) -> bool:
    """数值校验（排除 bool——bool 是 int 子类；对齐 chase_resume._num）。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _read_field(session: Any, key: str, default: Any = None) -> Any:
    """从副本会话（DungeonSession dataclass / dict 持久化形态）读取字段。"""
    if session is None:
        return default
    if isinstance(session, Mapping):
        return session.get(key, default)
    return getattr(session, key, default)


def _to_int(value: Any) -> Optional[int]:
    """数值转 int（排除 bool；非法/缺失 → None）。"""
    if _num(value):
        return int(value)
    return None


def _snapshot_turn(snapshot: Mapping[str, Any]) -> Optional[int]:
    """快照回合数：顶层 turn 或 snapshot_at.turn 双写任一处（1g3 §1.2/§1.3）。"""
    t = _to_int(snapshot.get("turn"))
    if t is not None:
        return t
    sat = snapshot.get("snapshot_at")
    if isinstance(sat, Mapping):
        t = _to_int(sat.get("turn"))
        if t is not None:
            return t
    return None


def _collect_chase_fields(snapshot: Mapping[str, Any]) -> list:
    """收集快照中的换区上下文（chase ctx）字段路径（补白 3：顶层 + ai_state 内嵌）。"""
    fields: list = []
    for k in _CHASE_CTX_KEYS:
        if snapshot.get(k) is not None:
            fields.append(k)
    ai = snapshot.get("ai_state")
    if isinstance(ai, Mapping):
        for k in _AI_STATE_CHASE_KEYS:
            if ai.get(k) is not None:
                fields.append(f"ai_state.{k}")
    return fields


# -------------------------------------------------------------------------------------
# M6 D3：续战世代重绑定（RSM-04 取档 / RSM-09 一致性自检 / F-RSM-01 快照世代键）
# -------------------------------------------------------------------------------------


def snapshot_registry_generation(snapshot: Mapping[str, Any]) -> int:
    """读取快照 registry_generation（M6 D3 RSM-02 / F-RSM-01）。

    旧快照缺该字段 → 兼容读取默认 0（RSM-02：旧快照走 RSM-04 降级路径）；非数值/布尔
    同样按 0（防御）。续战世代绑定的键。非 Mapping（dataclass 快照形态）→ 默认 0（P2-RSM-04）。
    """
    if not isinstance(snapshot, Mapping):
        return 0
    v = snapshot.get("registry_generation", 0)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return 0
    return int(v)


def _snap_generation(snap_obj: Any) -> int:
    """RegistrySnapshot（或契约替身）的 generation 数值读取（防御非数值）。"""
    g = getattr(snap_obj, "generation", 0)
    if isinstance(g, bool) or not isinstance(g, (int, float)):
        return 0
    return int(g)


def pick_registry_snapshot(
    watcher: Any, generation: int
) -> Tuple[Optional[Any], str]:
    """按世代从 watcher 取对应 RegistrySnapshot（M6 D3 RSM-04）。

    取档源双口（补白 7）：① watcher._snapshots（N=2 滚动 deque，含当前有效 + 上一份，
    hot_reload.py L81/L327）；② watcher.backup_snapshot()（RSM-05 契约接口，路A 激活；
    getattr 防御未实装不崩）。返回 (RegistrySnapshot|None, status)：

      exact    找到 generation 精确匹配档（同世代重绑定，旧局旧配置）；
      fallback 无精确档 → 取最近一份世代 ≤ 目标的档 + 由调用方告警（ADR-D3-03，不拒绝恢复）；
      none     无任何可用档（含 watcher 未启动 / 目标超出全部档）；不绑定；
      skipped  未注入 watcher（不重绑定，旧行为零影响）。
    """
    if watcher is None:
        return None, _REBIND_SKIPPED
    candidates: list = []
    seen: set = set()
    for s in (getattr(watcher, "_snapshots", None) or ()):  # N=2 滚动 deque（含当前有效）
        if s is not None and id(s) not in seen:
            candidates.append(s)
            seen.add(id(s))
    backup = getattr(watcher, "backup_snapshot", None)
    if callable(backup):
        try:
            bs = backup()  # RSM-05：当前有效 registry 快照（路A 激活的公开接口）
        except Exception as exc:  # noqa: BLE001 —— 契约防御：取档失败按无此档处理（P2-RSM-07 补日志）
            _logger.debug("backup_snapshot() 取档失败：%s（按无此档降级，双口候选不受影响）", exc)
            bs = None
        if bs is not None and id(bs) not in seen:
            candidates.append(bs)
            seen.add(id(bs))
    # ① 精确世代匹配（RSM-04 首选：旧局按旧配置结算）
    for s in candidates:
        if _snap_generation(s) == generation:
            return s, _REBIND_EXACT
    # ② ADR-D3-03：无精确档 → 最近一份世代 ≤ 目标（不拒绝恢复；引用 ID 已删走 WIR-14 降级）
    le = [s for s in candidates if _snap_generation(s) <= generation]
    if le:
        return max(le, key=_snap_generation), _REBIND_FALLBACK
    return None, _REBIND_NONE


def rebind_registry_for_snapshot(
    snapshot: Mapping[str, Any], watcher: Any
) -> Tuple[Optional[Registry], str, int, Optional[int], bool]:
    """续战世代重绑定（M6 D3 RSM-04/RSM-09）：快照世代 → watcher 取档 → Registry 重建。

    Returns (registry, status, target, rebound, degraded)：
      registry  重建 Registry（content Registry.from_snapshot；无可用档 → None 不绑定）；
      status    "exact" | "fallback" | "none" | "skipped"（见 pick_registry_snapshot）；
      target    快照 registry_generation（F-RSM-01，旧快照默认 0）；
      rebound   重建 registry 的 generation（未绑定 → None）；
      degraded  RSM-09 世代一致性自检：rebound != target → True + _logger.warning 告警
                （含目标/实际世代；fallback 档必然触发——降级不拒绝恢复，补白 8）。
    """
    target = snapshot_registry_generation(snapshot)
    snap, status = pick_registry_snapshot(watcher, target)
    if snap is None:
        if status == _REBIND_SKIPPED:
            # 未注入 watcher：不重绑定、不告警（零影响既有调用方，degraded=False）
            return None, status, target, None, False
        # P1-RSM-02 修复（M6 批3B 审查）：none 降级路径（世代滚出 N=2 窗口 = 半套复发
        # 最高频场景）补告警 + degraded=True——RSM-09「日志」义务与 fallback 可观测性对齐。
        _logger.warning(
            "续战世代重绑定无可用档：快照世代=%s（watcher 无 ≤ 目标档可绑定，回退默认解析，"
            "半套配置风险；M6 D3 RSM-09 / ADR-D3-03 不拒绝恢复）", target,
        )
        return None, status, target, None, True
    try:
        # P2-RSM-03 修复（M6 批3B 审查）：畸形档（缺 tables/names/modules_raw 的契约替身）
        # → Registry.from_snapshot 异常不穿透 resume_from_snapshot，按降级 (None, none, True)
        reg: Registry = Registry.from_snapshot(snap)
    except Exception:  # noqa: BLE001 —— 契约防御：快照档残缺按无可绑定档降级
        _logger.warning(
            "续战世代重绑定快照档残缺：目标世代=%s（Registry.from_snapshot 失败，按无档降级）",
            target,
        )
        return None, "none", target, None, True
    rebound = _snap_generation(snap)
    degraded = rebound != target
    if degraded:
        # RSM-09 一致性自检 / ADR-D3-03：世代不一致 → 降级策略 + 日志告警（不拒绝恢复）
        _logger.warning(
            "续战世代重绑定降级：快照世代=%s，重绑定世代=%s（M6 D3 RSM-09 世代不一致 → "
            "RSM-04 降级 / ADR-D3-03 取最近 ≤ 世代档）", target, rebound,
        )
    return reg, status, target, rebound, degraded


# -------------------------------------------------------------------------------------
# M27：战斗快照续玩（ai_state + combo_state + 换区上下文逐字段保留，续玩非重置）
# -------------------------------------------------------------------------------------


def resume_from_snapshot(
    player_ctx: Any,
    snapshot: Any,
    battle_factory: Any = None,
    watcher: Any = None,
) -> dict:
    """战斗快照续玩（M27，1g3 §2.3 恢复时序 + m3 §4.4：ai_state+combo_state 全保留）。

    战斗中断（退出/超时/锁屏）→ 从最近回合边界快照续玩；续玩 = 原会话恢复继续，**不改变
    副本状态**（m3 §4.4：战斗中断不改变副本状态，走快照续玩而非重置，2a2 §5.2）。

    M6 D3 RSM-04：注入 watcher 时按快照 registry_generation 世代重绑定——从 watcher 取
    对应 RegistrySnapshot 重建 Registry 注入引擎（from_snapshot(registry=...)），旧局按
    旧配置结算（杜绝半套配置）；世代缺失/不一致 → ADR-D3-03 降级 + RSM-09 自检告警。

    Args:
        player_ctx: 玩家上下文（纯函数只读；战斗中断判定源之一——不在此判定重置，仅透传
            保留以便接线层消费）。本函数不修改它。
        snapshot: 进行中战斗快照（1g3 §1.2 字段级形态 / 1g4 BattleSnapshot dict 形态）。
        battle_factory: 续玩引擎工厂（可调用 snapshot -> engine）：真实 BattleEngine.
            from_snapshot 类方法或测试 stub（补白 1）。未注入 → 本函数退化为契约形态校验
            闸门（resumed=False、reason="factory_missing"，valid/missing_fields 承载结论）。
        watcher: 世代重绑定取档源（真实 HotReloadWatcher 或契约替身，补白 7）。未注入 →
            rebind_status="skipped"，不重绑定（零影响既有调用方）。

    Returns:
        快照续玩结果 dict：
          resumed                   引擎已构建、续玩就绪（True）；完整性失败 / 未注入工厂 /
                                    工厂异常 / 工厂返回空 → False
          reason                    None（成功）| "incomplete_snapshot" | "factory_missing" |
                                    "factory_error" | "factory_empty" | "invalid_snapshot"
          valid                     快照契约形态是否完整（校验闸门结论，补白 1）
          missing_fields            缺失的契约键（ai_state/combo_state 缺键或非 Mapping、
                                    turn 非数值）
          turn                      续玩回合数（顶层 turn / snapshot_at.turn，None=缺失）
          ai_state_preserved        ai_state 键存在且为 Mapping（逐字段保留载体）
          combo_state_preserved     combo_state 键存在且为 Mapping
          chase_context_preserved   换区上下文（chase ctx）任一字段存在
          chase_fields              命中字段路径列表（顶层键 + "ai_state.zone_change" 等）
          engine                    battle_factory 构建的引擎（仅注入工厂且成功时）
          reset: False              续玩非重置（m3 §4.4 / 2a2 §5.2，补白 4）
          state_unchanged: True     副本状态不被改变（战斗中断不重置）
          rebind_generation         快照 registry_generation（F-RSM-01；旧快照默认 0）
          rebound_generation        重绑定 registry 的 generation（未绑定 → None）
          rebind_status             "exact"|"fallback"|"none"|"skipped"（M6 D3 RSM-04）
          degraded                  RSM-09 世代一致性自检：重绑定世代 ≠ 快照世代 → True
    """
    # player_ctx 只读透传（补白 4：本函数永不改入参）；非 Mapping 防御
    if not isinstance(snapshot, Mapping):
        return {
            "resumed": False,
            "reason": "invalid_snapshot",
            "valid": False,
            "missing_fields": list(_SNAPSHOT_REQUIRED_KEYS),
            "turn": None,
            "ai_state_preserved": False,
            "combo_state_preserved": False,
            "chase_context_preserved": False,
            "chase_fields": [],
            "reset": False,
            "state_unchanged": True,
            "rebind_generation": 0,
            "rebound_generation": None,
            "rebind_status": _REBIND_SKIPPED,
            "degraded": False,
        }

    snap: Mapping[str, Any] = snapshot
    ai_state = snap.get("ai_state")
    combo_state = snap.get("combo_state")
    ai_state_preserved = isinstance(ai_state, Mapping)
    combo_state_preserved = isinstance(combo_state, Mapping)
    turn = _snapshot_turn(snap)
    chase_fields = _collect_chase_fields(snap)
    chase_context_preserved = bool(chase_fields)

    # 快照完整性校验（1g3 §1.2 / S1 + m3 §八 10，补白 2）：ai_state+combo_state 全保留 + turn
    missing: list = []
    if not ai_state_preserved:
        missing.append("ai_state")
    if not combo_state_preserved:
        missing.append("combo_state")
    if turn is None:
        missing.append("turn")

    base: dict = {
        "turn": turn,
        "ai_state_preserved": ai_state_preserved,
        "combo_state_preserved": combo_state_preserved,
        "chase_context_preserved": chase_context_preserved,
        "chase_fields": chase_fields,
        "reset": False,
        "state_unchanged": True,
        # M6 D3 RSM-04/09：世代重绑定信息（F-RSM-01；未达工厂阶段保持 skipped/None）
        "rebind_generation": snapshot_registry_generation(snap),
        "rebound_generation": None,
        "rebind_status": _REBIND_SKIPPED,
        "degraded": False,
    }

    if missing:
        # 完整性失败：不调用工厂（补白 2）
        return {
            **base,
            "resumed": False,
            "reason": "incomplete_snapshot",
            "valid": False,
            "missing_fields": missing,
        }

    if battle_factory is None:
        # 未注入工厂：退化为契约形态校验闸门（补白 1）
        return {
            **base,
            "resumed": False,
            "reason": "factory_missing",
            "valid": True,
            "missing_fields": [],
        }

    # M6 D3 RSM-04：续战入口世代重绑定——按快照 registry_generation 取档重建 Registry
    # 注入引擎（仅注入 watcher 时启用；未注入 → skipped 不改变旧行为，补白 7）
    reg: Optional[Registry] = None
    rebind_status = _REBIND_SKIPPED
    rebound_generation: Optional[int] = None
    degraded = False
    if watcher is not None:
        reg, rebind_status, _, rebound_generation, degraded = rebind_registry_for_snapshot(
            snap, watcher,
        )

    # 注入工厂（BattleEngine.from_snapshot 类方法 / stub）：实际构建续玩引擎（补白 1）
    try:
        if reg is not None:
            # 世代重绑定成功：registry 注入工厂（BattleEngine.from_snapshot(registry=...)
            # 透传，RSM-03；stub 工厂须接受 registry 关键字——补白 7 约定）
            engine = battle_factory(snap, registry=reg)
        else:
            engine = battle_factory(snap)
    except Exception as exc:  # noqa: BLE001 —— 注入工厂防御（补白 1）
        return {
            **base,
            "resumed": False,
            "reason": "factory_error",
            "valid": True,
            "missing_fields": [],
            "error": str(exc),
            "rebind_status": rebind_status,
            "rebound_generation": rebound_generation,
            "degraded": degraded,
        }
    if engine is None:
        return {
            **base,
            "resumed": False,
            "reason": "factory_empty",
            "valid": True,
            "missing_fields": [],
            "rebind_status": rebind_status,
            "rebound_generation": rebound_generation,
            "degraded": degraded,
        }
    return {
        **base,
        "resumed": True,
        "reason": None,
        "valid": True,
        "missing_fields": [],
        "engine": engine,
        "rebind_status": rebind_status,
        "rebound_generation": rebound_generation,
        "degraded": degraded,
    }


# -------------------------------------------------------------------------------------
# M28：非战斗离开重置与明示文案（战斗中断可续玩，离开副本将重置）
# -------------------------------------------------------------------------------------


def non_combat_exit(
    player_ctx: Any,
    session: Any,
    in_battle: bool = False,
) -> dict:
    """非战斗状态离开副本 → 副本重置 + 明示文案（M28，2a2 §5 R24/R25 + m3 §4.4）。

    离开判定（M28 实现要点）= 非战斗 + 已出副本区域（后者由接线层入口通道事件前置保证，
    同 chase_resume 补白 8）。非战斗离开 → 调 exit_dungeon_reset 副本全清（BOSS/残血/子
    任务/休息/换区上下文），下次满状态重打；明示文案「战斗中断可续玩，离开副本将重置」
    （恢复入口明示，M27 实现要点，补白 5）。

    in_battle=True（显式开关，补白 6）或玩家战斗标志（in_battle/battle_active/in_combat/
    battle_session_id/battle_state 非空，委托 exit_dungeon_reset 判定）→ 拒绝离开，提示
    续玩走 M27 快照。

    Args:
        player_ctx: 玩家上下文（战斗标志判定源，委托 exit_dungeon_reset；纯只读）。
        session: 副本会话（DungeonSession dataclass 或 to_dict 持久化 dict 形态）。
        in_battle: 显式战斗中开关（补白 6；True 直接拒绝，不调用 exit_dungeon_reset）。

    Returns:
        重置成功：{reset: True, ...exit_dungeon_reset 全字段（state/external_anchor/
          message_hint/session/boss_state_cleared）, entry_hint: "战斗中断可续玩，离开副本
          将重置", via_snapshot: False}
        战斗中拒绝：{reset: False, reason: "battle_in_progress", state, session（原样保留）,
          message_hint: "战斗中断可续玩，离开副本将重置", via_snapshot: True,
          session_unchanged: True}
    """
    if in_battle:
        # 显式战斗中开关：拒绝离开，提示续玩（走 M27 快照，补白 6）
        return {
            "reset": False,
            "reason": "battle_in_progress",
            "state": _read_field(session, "state"),
            "session": session,
            "message_hint": MESSAGE_HINT_BATTLE_ONGOING,
            "entry_hint": MESSAGE_HINT_BATTLE_ONGOING,
            "via_snapshot": True,
            "session_unchanged": True,
        }

    # 非战斗离开：委托 exit_dungeon_reset 副本重置（M15；玩家战斗标志判定也在其内）
    out = exit_dungeon_reset(session, player_ctx)
    if out.get("reset") is False:
        # 玩家战斗标志命中（chase_resume 补白 6）：战斗中离开拒绝，走快照续玩
        return {
            **out,
            "entry_hint": MESSAGE_HINT_BATTLE_ONGOING,
            "via_snapshot": True,
            "session_unchanged": True,
        }

    # 非战斗离开重置成功：挂恢复入口明示文案（M27 实现要点，补白 5）
    return {
        **out,
        "entry_hint": MESSAGE_HINT_BATTLE_ONGOING,
        "via_snapshot": False,
    }
