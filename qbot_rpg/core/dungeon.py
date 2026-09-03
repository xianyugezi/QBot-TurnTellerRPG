"""副本状态机（S0–S7）+ 探索版流程（M3 批次5·路N：M17 副本共用 + M18 探索版流程）。

依据：
  - m3_shared_contract §4.2（副本内状态集 S0–S7 + 迁移表 M1–M15）+ §4.1（dungeon.json 两型 11 字段）
  - 细化_2a3_副本两型流程 §2（状态集/迁移表/阶段细化）+ §3（子任务五形式）+ §4（死亡处理/离开重置）
  - 细化_2a1c_地图副本衔接 §2（进入副本入场校验 R4 / 外部锚点 R8 / 离开=重置 R7 / 集合隔离 R5）
  - m3_shared_contract §4.3（子任务五形式）/ §4.4（副本会话持久化字段）

职责（core 层纯逻辑：零 NoneBot import、零 IO、纯函数/纯数据）：
  DungeonStateMachine  副本状态机：enter（入场校验 → S0）/ transition（S0–S7 迁移 M1–M15）/
                       state 查询
  DungeonSession       副本会话数据类（frozen；持久化形态 to_dict/from_dict，批次 7 接线）
  explore_run          探索版流程：入口校验 → 走通道推进（调 world.movement.resolve_move）→
                       通关 CLEARED（结算信号）→ 离开重置 S7

【工程补白】（显式标注，不冒充定稿）：
  1. BOSS 追击/决战路径（chase/caught/re_chase/kill 事件在真实战斗中的触发接线、换区续战
     残血保持/PV 半恢复/开场技）由批次5·路O 实装。本路实现迁移表全量映射（契约 §4.2
     M1–M15）；探索版（type=explore，2a3 R9 无 BOSS）上 BOSS 专属事件被拒，BOSS 版上
     探索通关事件（clear）被拒（BOSS 版通关走 M8 击杀路径）。
  2. 探索版通关 S1→S5：契约 M 表仅列 M8（S4→S5 BOSS 击杀）；探索版无 BOSS，按 S5 定义
     「BOSS 击杀/探索目标完成」（2a3 §2.2）取探索目标完成路径。
  3. 探索版死亡 S1/S2→S6：契约 M 表仅列 M9/M10（S3/S4→S6）；副本内死亡语义（2a3 §4.1
     R31 死亡≠离开）对无 BOSS 语境同适用。复活点落位（默认=入口=safe_zone，
     death_policy.revive_point 可配）在 flow 层执行。
  4. 入口校验背包形态：以 player_ctx["inventory"] = {item_id: count} count-map 契约为准
     （回退 player_ctx["player"]["inventory"]；InventoryEngine 已实装（M6 批1），真实背包
     结算接线归装配层）。入场次数落点 player_ctx["dungeon_entries"] = {dungeon_id: count}
     （每日口径由批次 7 持久化）。校验先于消耗（2a1c §2.1：不足/超限拦截，不扣道具、
     不消耗次数）。
  5. 通关掉落结算（drops 实际发奖/首通奖励）由批次 7 接线（奖励管线 P 路）；本路仅出结算
     信号 {state:"cleared", reward_hint}。
  6. 会话持久化（存档落点、content_pack_id+version 防跨包串档校验）由批次 7 接线；
     DungeonSession.to_dict/from_dict 提供持久化形态。
  7. 入口区落位 = safe_zone 缺省 maps[0]（2a1c R3 入口区缺省即安全区；入口区与 maps[0]
     的对应为工程约定）。
  8. cleared_maps = 已清/已到访图集合：探索版每走通一张图即登记（2a1c §2.3 当前区域/已清
     区域记录）；BOSS 版登记口径由路 O 细化。
  9. subquest_progress 仅计数登记 {quest_id: int}；子任务完整条目形态（路P ProgressTracker
     的 {current,target,done,claimed}，挂 player session["dungeon_subquests"]）由批次 7
     收口归一。
  10. /休息 安全区落点校验（非安全区拒绝，TC-2a3-15）在 flow 层（explore_run）执行；
      状态机按 M15 迁移表放行 S0/S1/S3（原地休息≠离开：位置/BOSS 血量/快照保留）。休息
      次数上限（rest_per_dungeon 可配）由批次 7 接线。
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple, cast

from qbot_rpg.content.dungeon_models import DungeonDef
from qbot_rpg.content.map_models import MapDef, parse_maps

__all__ = [
    "S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7",
    "DungeonSession",
    "DungeonStateMachine",
    "explore_run",
]

# -------------------------------------------------------------------------------------
# 副本内状态集 S0–S7（m3_shared_contract §4.2 / 细化_2a3 §2.2）
# -------------------------------------------------------------------------------------
S0 = "ENTRY"              # 入口态（=安全区）
S1 = "PEACE_EXPLORE"      # 平静探索（走通道/子任务/宝箱采集）
S2 = "ELITE_ESCALATE"     # 升压精英（遭遇精英，可打可绕）
S3 = "BOSS_CHASE"         # BOSS 追击态（chasing:true，/进入 <方向> 追击）
S4 = "FINAL_DEATHMATCH"   # 决战态（BOSS 房/残血续战）
S5 = "CLEARED"            # 通关态（奖励/图鉴/首通）
S6 = "DEAD_RECOVER"       # 死亡复活态（复活点 + 虚弱禁入非安全区）
S7 = "LEFT"               # 离开态（副本重置）

# 迁移表（m3_shared_contract §4.2 M1–M15；值 = 后置状态）
#   walk       M2 走图：S0→S1；平静探索内继续走图（S1→S1，M 表未列，S1 语义=漫步）
#              【补白】；追击中走图（S3→S3，追到=caught 事件判定，路O 接线）
#   elite      M3 遭遇精英（S1→S2）；elite_done M4 击败/脱离（S2→S1）
#   chase      M5 换区（S1/S2→S3，BOSS 版；触发接线路O）
#   caught     M6 追到续战（S3→S4，路O）；re_chase M7 决战再次换区（S4→S3，路O）
#   kill       M8 击杀（S4→S5，路O）
#   death      M9/M10（S3/S4→S6）+ 探索版 S1/S2→S6【补白 3】
#   recover    M11 虚弱结束（S6→S1）
#   leave      M12（S1/S3→S7）/ M13（S5→S7）/ M14（S6→S7）+ S0→S7【补白：从入口区
#              非战斗离开同属「离开=重置」语义，2a1c TC-16】
#   clear      探索版通关 S1→S5【补白 2】
#   rest       M15 原地休息≠离开（S0/S1/S3 状态不变，rest_count+1；安全区落点校验在 flow）
_TRANSITIONS: Dict[str, Dict[str, str]] = {
    "walk": {S0: S1, S1: S1, S3: S3},
    "elite": {S1: S2},
    "elite_done": {S2: S1},
    "chase": {S1: S3, S2: S3},
    "caught": {S3: S4},
    "re_chase": {S4: S3},
    "kill": {S4: S5},
    "death": {S1: S6, S2: S6, S3: S6, S4: S6},
    "recover": {S6: S1},
    "leave": {S0: S7, S1: S7, S3: S7, S5: S7, S6: S7},
    "clear": {S1: S5},
    "rest": {S0: S0, S1: S1, S3: S3},
}

# BOSS 专属事件（2a3 R9 探索版无 BOSS → 探索版上拒绝；触发接线=批次5·路O）
_BOSS_EVENTS: Tuple[str, ...] = ("chase", "caught", "re_chase", "kill")


# -------------------------------------------------------------------------------------
# 副本会话（m3 §4.4 持久化字段；frozen 不可变，更新走 with_*）
# -------------------------------------------------------------------------------------
@dataclass(frozen=True)
class DungeonSession:
    """副本会话数据类（任务交付字段：state/current_map/cleared_maps/subquest_progress/
    boss_state/rest_count/external_anchor；外加 dungeon_id/dungeon_type 型别镜像与
    content_pack 防跨包串档——m3 §4.4）。持久化形态 = to_dict/from_dict（批次 7 接线）。
    """

    dungeon_id: str
    dungeon_type: str
    state: str = S0
    current_map: Optional[str] = None
    cleared_maps: frozenset = frozenset()
    subquest_progress: Dict[str, int] = field(default_factory=dict)
    boss_state: Dict[str, Any] = field(default_factory=dict)
    rest_count: int = 0
    external_anchor: Optional[str] = None
    content_pack_id: Optional[str] = None
    content_pack_version: Optional[str] = None
    # M3 审查批次3 P2-3：追击态字段（chase 管线与 frozen dataclass 互操作）——
    # begin_chase 经 with_chase 返回新实例；持久化随 to_dict/from_dict 落库
    chasing: bool = False
    chase_target: Optional[str] = None
    zone_chase_context: Optional[Dict[str, Any]] = None  # 换区追击上下文（chase_ctx 快照）

    # ---- 不可变更新辅助 ---------------------------------------------------------
    def with_chase(
        self,
        chasing: bool,
        target: Optional[str] = None,
        ctx: Optional[Dict[str, Any]] = None,
    ) -> "DungeonSession":
        """追击态更新（M3 审查批次3 P2-3）：返回新实例，chasing/chase_target/zone_chase_context 落位。"""
        return dataclasses.replace(
            self, chasing=chasing, chase_target=target, zone_chase_context=ctx
        )

    def with_state(self, state: str) -> "DungeonSession":
        return dataclasses.replace(self, state=state)

    def with_current_map(self, map_id: Optional[str]) -> "DungeonSession":
        return dataclasses.replace(self, current_map=map_id)

    def with_cleared(self, map_id: str) -> "DungeonSession":
        return dataclasses.replace(self, cleared_maps=frozenset(set(self.cleared_maps) | {map_id}))

    def with_subquest_progress(self, progress: Mapping[str, int]) -> "DungeonSession":
        return dataclasses.replace(self, subquest_progress=dict(progress))

    def with_rest_count(self, count: int) -> "DungeonSession":
        return dataclasses.replace(self, rest_count=count)

    # ---- 持久化形态（批次 7 接线；set ↔ list）------------------------------------
    def to_dict(self) -> dict:
        return {
            "dungeon_id": self.dungeon_id,
            "dungeon_type": self.dungeon_type,
            "state": self.state,
            "current_map": self.current_map,
            "cleared_maps": sorted(self.cleared_maps),
            "subquest_progress": dict(self.subquest_progress),
            "boss_state": dict(self.boss_state),
            "rest_count": self.rest_count,
            "external_anchor": self.external_anchor,
            "chasing": self.chasing,
            "chase_target": self.chase_target,
            "zone_chase_context": dict(self.zone_chase_context) if self.zone_chase_context else None,
            "content_pack_id": self.content_pack_id,
            "content_pack_version": self.content_pack_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DungeonSession":
        cm_raw = data.get("cleared_maps", ())
        if isinstance(cm_raw, Mapping):
            cm = tuple(str(k) for k in cm_raw.keys())
        elif isinstance(cm_raw, (list, tuple, set)):
            cm = tuple(str(x) for x in cm_raw)
        else:
            cm = ()
        sp = data.get("subquest_progress")
        sp_norm: Dict[str, int] = {}
        if isinstance(sp, Mapping):
            for k, v in sp.items():
                if isinstance(v, int) and not isinstance(v, bool):
                    sp_norm[str(k)] = v
        bs = data.get("boss_state")
        return cls(
            dungeon_id=str(data.get("dungeon_id", "")),
            dungeon_type=str(data.get("dungeon_type", "explore")),
            state=str(data.get("state", S0)),
            current_map=data.get("current_map"),
            cleared_maps=frozenset(cm),
            subquest_progress=sp_norm,
            boss_state=dict(bs) if isinstance(bs, Mapping) else {},
            rest_count=int(data.get("rest_count", 0) or 0),
            external_anchor=data.get("external_anchor"),
            content_pack_id=data.get("content_pack_id"),
            chasing=bool(data.get("chasing", False)),
            chase_target=data.get("chase_target"),
            zone_chase_context=dict(data["zone_chase_context"]) if isinstance(data.get("zone_chase_context"), Mapping) else None,
            content_pack_version=data.get("content_pack_version"),
        )


# -------------------------------------------------------------------------------------
# 数据归一（纯函数，无 IO）
# -------------------------------------------------------------------------------------
def _norm_dungeon_def(dungeon_def: object) -> DungeonDef:
    """dungeon_def 入参归一：DungeonDef 直通 / raw dict → from_entry；其余形态抛 TypeError。"""
    if isinstance(dungeon_def, DungeonDef):
        return dungeon_def
    if isinstance(dungeon_def, Mapping):
        return cast(DungeonDef, DungeonDef.from_entry(dungeon_def))
    raise TypeError("dungeon_def 须为 DungeonDef 或 dict")


def _maps_index(maps_src: object) -> Dict[str, MapDef]:
    """maps 入参归一 → {map_id: MapDef}（形态对齐 world/movement._maps_index）。

    接受：modules 容器（{"maps": [...]}）/ MapDef 列表 / 原始节点 dict 列表 /
    单个节点 dict / None（空）。零失败（形态异常 → 空索引）。
    """
    if maps_src is None:
        return {}
    if isinstance(maps_src, Mapping):
        if "maps" in maps_src:  # modules 容器（content 装载形态）
            entries = maps_src.get("maps")
            if isinstance(entries, list):
                return {str(m.id): m for m in parse_maps(maps_src) if m.id}
            return {}
        if "id" in maps_src:  # 单个地图节点
            m = cast(MapDef, MapDef.from_entry(maps_src))
            return {str(m.id): m} if m.id else {}
        return {}
    if isinstance(maps_src, (list, tuple)):
        out: Dict[str, MapDef] = {}
        for e in maps_src:
            if isinstance(e, MapDef):
                m = e
            elif isinstance(e, Mapping):
                m = cast(MapDef, MapDef.from_entry(e))
            else:
                continue
            if m.id:
                out[str(m.id)] = m
        return out
    return {}


def _safe_zone(dungeon_def: DungeonDef) -> Optional[str]:
    """安全区地图：safe_zone 配置；缺省 = maps[0]（2a1c R3 入口区缺省即安全区【补白 7】）。"""
    sz = dungeon_def.safe_zone
    if isinstance(sz, str) and sz:
        return sz
    maps = dungeon_def.maps
    return str(maps[0]) if maps else None


def _current_world_map(player_ctx: Mapping[str, Any]) -> Optional[str]:
    """当前地图 ID：ctx["map_id"]（会话上下文）→ 兜底 ctx["player"]["map_id"]。"""
    cur = player_ctx.get("map_id")
    if isinstance(cur, str) and cur:
        return cur
    player = player_ctx.get("player")
    if isinstance(player, Mapping):
        pcur = player.get("map_id")
        if isinstance(pcur, str) and pcur:
            return pcur
    return None


def _set_map_id(player_ctx: dict, map_id: Optional[str]) -> None:
    """玩家位置原地改（对齐 world/movement.move_to_map：ctx["map_id"] + player["map_id"]）。"""
    player_ctx["map_id"] = map_id
    player = player_ctx.get("player")
    if isinstance(player, dict):
        player["map_id"] = map_id


def _ctx_str(player_ctx: Mapping[str, Any], key: str) -> Optional[str]:
    """ctx 键读取：ctx 直取 → 回退 ctx["player"]（如 content_pack_id/version）。"""
    v = player_ctx.get(key)
    if isinstance(v, str) and v:
        return v
    player = player_ctx.get("player")
    if isinstance(player, Mapping):
        pv = player.get(key)
        if isinstance(pv, str) and pv:
            return pv
    return None


def _inventory_map(player_ctx: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    """背包 count-map：ctx["inventory"] 优先，回退 ctx["player"]["inventory"]（【补白 4】）。"""
    inv = player_ctx.get("inventory")
    if isinstance(inv, Mapping):
        return inv
    player = player_ctx.get("player")
    if isinstance(player, Mapping):
        pinv = player.get("inventory")
        if isinstance(pinv, Mapping):
            return pinv
    return None


def _entries_map(player_ctx: dict) -> Dict[str, int]:
    """入场次数表 ctx["dungeon_entries"]（{dungeon_id: count}）；缺失 → 安装空表并返回。"""
    raw = player_ctx.get("dungeon_entries")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, Mapping):
        entries = {str(k): v for k, v in raw.items()}
    else:
        entries = {}
    player_ctx["dungeon_entries"] = entries
    return entries


def _validate_entry(player_ctx: dict, dungeon_def: DungeonDef) -> Tuple[Optional[str], dict]:
    """入场校验（2a1c R4 / 契约 §4.1：entry_item 消耗 + entry_limit 次数限制；0=不限）。

    校验先于消耗（2a1c §2.1：不足/超限拦截，不扣道具、不消耗次数）。探索版默认
    entry_item:null / entry_limit:0 → 天然宽松（2a3 R11）。返回 (blocked_reason, effects)；
    effects = {"item_consumed": str|None, "entry_count": int}。
    """
    item_id = dungeon_def.entry_item
    limit = dungeon_def.entry_limit
    inv = _inventory_map(player_ctx)
    entries = _entries_map(player_ctx)
    did = dungeon_def.id
    used = entries.get(did)
    used = used if isinstance(used, int) and not isinstance(used, bool) else 0

    if item_id:
        have = 0
        if inv is not None:
            v = inv.get(item_id)
            if isinstance(v, int) and not isinstance(v, bool):
                have = v
        if have < 1:
            return f"缺少入场道具：{item_id}（入场校验先于消耗：未扣道具、未消耗次数）", {}
        if not isinstance(inv, dict):
            return "背包形态非法：入场道具扣减需 dict count-map（工程补白 4）", {}
    if limit is not None and limit > 0 and used >= int(limit):
        return f"今日进入次数已达上限（{used}/{int(limit)}）；未扣道具、未消耗次数", {}

    # 消耗（全部校验通过后才扣；entry_limit 0=不限仅不拦截，计数恒登记）
    effects: dict = {"item_consumed": None, "entry_count": used + 1}
    if item_id:
        inv = cast(Dict[str, Any], inv)
        inv[item_id] = int(inv.get(item_id, 0) or 0) - 1
        effects["item_consumed"] = item_id
    entries[did] = used + 1
    return None, effects


# -------------------------------------------------------------------------------------
# 副本状态机（m3_shared_contract §4.2 M1–M15）
# -------------------------------------------------------------------------------------
class DungeonStateMachine:
    """副本状态机（纯逻辑，无 IO）。

    构造（可选）：DungeonStateMachine(dungeon_def, ctx) 供「机器持有定义」形态；
    enter/transition 亦可直接传参（本路测试主用形态）。
    """

    def __init__(self, dungeon_def: object = None, ctx: Optional[dict] = None) -> None:
        self._dungeon_def = dungeon_def
        self._ctx = ctx

    # ---- 进入（M1：无 → S0）-----------------------------------------------------
    def enter(self, player_ctx: dict, dungeon_def: object = None) -> dict:
        """进入副本（M1）：入场校验（BOSS 版 entry_item/entry_limit 拦截，探索版宽松）
        → 落位 safe_zone（外部锚点记录）→ S0 会话。

        成功：{"ok", "state":S0, "session", "external_anchor", "safe_zone",
              "entry_item_consumed", "entry_count", "note"}（player_ctx 原地改：
              位置→safe_zone；扣道具；入场次数 +1）。
        拦截：{"ok": False, "reason", "state": None, "session": None}（不改 ctx）。
        """
        ddef = _norm_dungeon_def(dungeon_def if dungeon_def is not None else self._dungeon_def)
        dtype = ddef.type if ddef.type in ("explore", "boss") else "explore"

        blocked, effects = _validate_entry(player_ctx, ddef)
        if blocked:
            return {"ok": False, "reason": blocked, "state": None, "session": None}

        anchor = _current_world_map(player_ctx)
        safe = _safe_zone(ddef)
        _set_map_id(player_ctx, safe)  # 落位入口区（=安全区，2a1c R3）
        session = DungeonSession(
            dungeon_id=ddef.id,
            dungeon_type=dtype,
            state=S0,
            current_map=safe,
            external_anchor=anchor,
            content_pack_id=_ctx_str(player_ctx, "content_pack_id"),
            content_pack_version=_ctx_str(player_ctx, "content_pack_version"),
        )
        return {
            "ok": True,
            "state": S0,
            "session": session,
            "external_anchor": anchor,
            "safe_zone": safe,
            "entry_item_consumed": effects["item_consumed"],
            "entry_count": effects["entry_count"],
            "note": f"进入副本「{ddef.name or ddef.id}」（{dtype}）；战斗中断可续玩，离开副本将重置",
        }

    # ---- 迁移（M1–M15）----------------------------------------------------------
    def transition(self, event: object, session: DungeonSession) -> dict:
        """S0–S7 迁移（m3_shared_contract §4.2 M1–M15；探索版路径 S0→S1→S5→S7 + 死亡 S6，
        BOSS 追击/决战路径批次5·路O 接线）。

        成功：{"ok", "state", "session", "event"}（session 为更新后新实例）。
        拒绝：{"ok": False, "reason", "state", "session"}（原会话不变）。
        """
        if not isinstance(session, DungeonSession):
            return {"ok": False, "reason": "会话形态非法（须 DungeonSession）",
                    "state": None, "session": session}
        ev = "" if event is None else str(event)
        table = _TRANSITIONS.get(ev)
        if table is None:
            return {"ok": False, "reason": f"未知事件：{ev}（契约 §4.2 迁移表）",
                    "state": session.state, "session": session}
        dtype = session.dungeon_type
        if ev in _BOSS_EVENTS and dtype != "boss":
            return {"ok": False,
                    "reason": "探索版无 BOSS（2a3 R9）；BOSS 追击/决战路径由批次5·路O 接线",
                    "state": session.state, "session": session}
        if ev == "clear" and dtype != "explore":
            return {"ok": False,
                    "reason": "BOSS 版通关走 M8 击杀路径（批次5·路O 接线）",
                    "state": session.state, "session": session}
        cur = session.state
        if cur not in table:
            return {"ok": False,
                    "reason": f"状态 {cur} 不能响应事件 {ev}（契约 §4.2 迁移表 M1-M15）",
                    "state": cur, "session": session}
        nxt = table[cur]
        kw: dict = {"state": nxt}
        if ev == "rest":
            kw["rest_count"] = session.rest_count + 1
        if ev == "leave":
            # M12/M13/M14 离开=副本重置：进度/BOSS/休息全清，下次满状态重打（2a1c R7）
            kw.update(current_map=None, cleared_maps=frozenset(),
                      subquest_progress={}, boss_state={}, rest_count=0)
        sess2 = dataclasses.replace(session, **kw)
        return {"ok": True, "state": nxt, "session": sess2, "event": ev}

    # ---- 状态查询 ---------------------------------------------------------------
    def state(self, session: object) -> Optional[str]:
        """当前状态查询：session.state；非 DungeonSession → None。"""
        return session.state if isinstance(session, DungeonSession) else None


# -------------------------------------------------------------------------------------
# 探索版流程（M18：练习赛。2a3 §0.1/§2.1：进入 → 走通道探索 → 子任务/宝箱/采集 → 通关结算）
# -------------------------------------------------------------------------------------
def _norm_direction(direction: object) -> Optional[str]:
    """方向字面量归一（上/下/左/右 + 北/南/东/西 + 英文键 → up/down/left/right）。
    延迟导入 world.movement（core 模块级零 world 依赖）。"""
    raw = "" if direction is None else str(direction).strip().lower()
    from qbot_rpg.world.movement import DIRECTION_ALIASES
    return DIRECTION_ALIASES.get(raw)


def _resolve_walk(player_ctx: dict, maps_src: object, direction: str,
                  conditions: Optional[Callable[[Mapping[str, object], dict], bool]],
                  mover: Optional[Callable[[dict, str], dict]]) -> dict:
    """走通道推进：默认调 world.movement.resolve_move（契约 §2.4 行走判定 + M05 隐藏门）；
    mover 可注入替身（纯逻辑测试/路 O 复用）。"""
    if mover is not None:
        return mover(player_ctx, direction)
    from qbot_rpg.world.movement import resolve_move  # 延迟导入：core 零 world 模块级依赖
    return resolve_move(player_ctx, direction, maps=maps_src, conditions=conditions)


def _reward_hint(dungeon_def: DungeonDef) -> str:
    """通关结算提示（【补白 5】：掉落结算/首通奖励由批次 7 接线，本路仅提示配置形态）。"""
    drops = dungeon_def.drops
    normal = drops.get("normal")
    n = len(normal) if isinstance(normal, list) else 0
    fc = drops.get("first_clear")
    has_fc = isinstance(fc, Mapping) and bool(fc)
    return ("探索通关（无 BOSS）：drops normal×" + str(n)
            + (" + first_clear 首通奖励" if has_fc else "")
            + "；掉落结算由批次 7 接线（奖励管线 P 路）")


def explore_run(player_ctx: dict, dungeon_def: object, maps: object,
                actions: Sequence[Any] = (),
                conditions: Optional[Callable[[Mapping[str, object], dict], bool]] = None,
                mover: Optional[Callable[[dict, str], dict]] = None) -> dict:
    """探索版（练习赛）流程（M18，2a3 §0.1/§2；仅 type=explore）。

    流程：入口校验（探索版 entry_item null 不扣 / entry_limit 0 不限）→ 走通道推进
    （调 movement.resolve_move；集合隔离 R5）→ 通关 CLEARED（结算信号
    {state:"cleared", reward_hint}；掉落结算批次 7 / 奖励 P 路）→ 离开重置 S7。

    actions（顺序执行；单步失败不中断后续，步骤记入 steps）：
      ("walk", <方向>)       走通道推进（S0→S1；S1 内继续走图；hidden 门经 conditions 注入）
      ("subquest", <id>, <delta>)   子任务进度登记（计数；完成判定/奖励=任务系统批次接线）
      ("clear",)             探索目标完成 → S5 通关（结算信号）
      ("death",)             探索中死亡（S1/S2）→ S6（复活点=safe_zone）
      ("recover",)           虚弱结束 → S1（M11）
      ("rest",)              安全区 /休息（M15；非安全区拒绝 TC-2a3-15）
      ("leave",)             非战斗离开 → S7（副本重置 + 回外部锚点 R8）

    返回：{"ok", "state", "session", "steps", "cleared"?, "left", "external_anchor"}。
    """
    ddef = _norm_dungeon_def(dungeon_def)
    if ddef.type != "explore":
        return {"ok": False,
                "reason": "仅探索版（练习赛）流程（2a3 R1）；BOSS 版由批次5·路O 接线",
                "state": None, "session": None, "steps": [], "cleared": None, "left": False,
                "external_anchor": None}

    machine = DungeonStateMachine()
    ent = machine.enter(player_ctx, ddef)
    steps: List[dict] = [{"event": "enter", "ok": ent["ok"]}]
    if not ent["ok"]:
        steps[0]["reason"] = ent["reason"]
        return {"ok": False, "reason": ent["reason"], "state": None, "session": None,
                "steps": steps, "cleared": None, "left": False, "external_anchor": None}
    session = ent["session"]
    steps[0].update({"state": S0, "map_id": session.current_map, "session": session})

    cleared_signal: Optional[dict] = None
    left = False
    for action in actions:
        name = action[0] if isinstance(action, (list, tuple)) and action else ""
        if name == "walk":
            direction = action[1] if len(action) > 1 else None
            step = _step_walk(player_ctx, ddef, maps, session, direction, conditions, mover)
        elif name == "subquest":
            qid = action[1] if len(action) > 1 else None
            delta = action[2] if len(action) > 2 else 1
            step = _step_subquest(session, qid, delta)
        elif name == "clear":
            step = _step_clear(machine, ddef, session)
            if step["ok"] and cleared_signal is None:
                cleared_signal = step["cleared"]
                # M7 N-03：副本通关事件（RN-10 三表 flat；探索版 clear 通关点）
                # M12.5 批5 路5B：键改读解析中心（settings.events 可配，缺省回退现键）
                try:
                    from qbot_rpg.core.event_bus import bump_event, resolve_event_key

                    bump_event(
                        player_ctx,
                        resolve_event_key(player_ctx, "副本通关"),
                        instance={"tag": "milestone"},
                    )
                except Exception:
                    pass
        elif name == "death":
            step = _step_death(machine, ddef, player_ctx, session)
        elif name == "recover":
            step = _step_recover(machine, session)
        elif name == "rest":
            step = _step_rest(machine, ddef, session)
        elif name == "leave":
            step = _step_leave(machine, player_ctx, session)
            if step["ok"]:
                left = True
        else:
            step = {"ok": False, "reason": f"未知探索动作：{name!r}",
                    "state": session.state, "session": session}
        steps.append(step)
        if step.get("ok") and isinstance(step.get("session"), DungeonSession):
            session = step["session"]

    return {"ok": True, "state": session.state, "session": session, "steps": steps,
            "cleared": cleared_signal, "left": left, "external_anchor": ent["external_anchor"]}


# -------------------------------------------------------------------------------------
# 探索版动作步骤（单步纯函数：返回 step dict，含 ok/state/session）
# -------------------------------------------------------------------------------------
def _step_walk(player_ctx: dict, dungeon_def: DungeonDef, maps_src: object, session: DungeonSession,
               direction: object, conditions: Optional[Callable[[Mapping[str, object], dict], bool]],
               mover: Optional[Callable[[dict, str], dict]]) -> dict:
    """走通道推进（M2 + S1 内走图；2a1c R5 集合隔离：只在本副本 maps 集合内推进）。"""
    norm = _norm_direction(direction)
    if norm is None:
        return {"ok": False,
                "reason": f"『{direction}』不是方向（上/下/左/右），也没有叫这个名字的入口",
                "state": session.state, "session": session}
    if session.state not in (S0, S1, S3):
        return {"ok": False, "reason": f"状态 {session.state} 不能走图（契约 §4.2）",
                "state": session.state, "session": session}
    index = _maps_index(maps_src)
    dungeon_ids = {str(m) for m in dungeon_def.maps}
    cur = session.current_map
    md = index.get(cur) if cur else None
    if md is None:
        return {"ok": False, "reason": "找不到当前地图", "state": session.state, "session": session}
    ex = md.exit(norm)
    if ex is None or not ex.to:
        return {"ok": False, "reason": "此方向没有通道", "state": session.state, "session": session}
    if str(ex.to) not in dungeon_ids:
        return {"ok": False, "reason": "此方向没有通道（副本内走图仅限本副本 maps 集合，2a1c R5）",
                "state": session.state, "session": session}
    res = _resolve_walk(player_ctx, maps_src, str(direction), conditions, mover)
    if not res.get("ok"):
        return {"ok": False, "reason": res.get("reason", "无法移动"),
                "state": session.state, "session": session}
    to = str(res.get("to") or "")
    if to not in dungeon_ids:
        # 防御回滚（mover 注入形态可能越界）：位置还原，不登记
        _set_map_id(player_ctx, cur)
        return {"ok": False, "reason": "此方向没有通道（集合隔离 R5）",
                "state": session.state, "session": session}
    sess2 = session.with_current_map(to).with_cleared(to)  # 已清/已到访登记【补白 8】
    tr = DungeonStateMachine().transition("walk", sess2)
    if not tr["ok"]:
        return {"ok": False, "reason": tr["reason"], "state": sess2.state, "session": sess2}
    return {"ok": True, "event": "walk", "state": tr["state"], "session": tr["session"],
            "to": to, "map_id": to, "name": res.get("name")}


def _step_subquest(session: DungeonSession, quest_id: object, delta: object) -> dict:
    """子任务进度登记（【补白 9】：仅计数；完成判定/奖励由任务系统批次接线）。"""
    qid = "" if quest_id is None else str(quest_id)
    if not qid:
        return {"ok": False, "reason": "子任务 ID 为空", "state": session.state, "session": session}
    d = 1
    if isinstance(delta, (int, float)) and not isinstance(delta, bool):
        d = int(delta)
    prog = dict(session.subquest_progress)
    cur = prog.get(qid, 0)
    if not isinstance(cur, int) or isinstance(cur, bool):
        cur = 0
    prog[qid] = max(0, cur + d)
    sess2 = session.with_subquest_progress(prog)
    return {"ok": True, "event": "subquest", "state": sess2.state, "session": sess2,
            "quest_id": qid, "progress": prog[qid]}


def _step_clear(machine: "DungeonStateMachine", dungeon_def: DungeonDef,
                session: DungeonSession) -> dict:
    """探索目标完成 → S5 通关（【补白 2】：结算信号 {state:"cleared", reward_hint}）。"""
    tr = machine.transition("clear", session)
    if not tr["ok"]:
        return {"ok": False, "reason": tr["reason"], "state": session.state, "session": session}
    return {"ok": True, "event": "clear", "state": S5, "session": tr["session"],
            "cleared": {"state": "cleared", "reward_hint": _reward_hint(dungeon_def),
                        "dungeon_id": dungeon_def.id, "dungeon_name": dungeon_def.name}}


def _step_death(machine: "DungeonStateMachine", dungeon_def: DungeonDef,
                player_ctx: dict, session: DungeonSession) -> dict:
    """探索中死亡 → S6（【补白 3】：S1/S2 副本内死亡；复活点=入口=safe_zone）。"""
    if session.state not in (S1, S2):
        return {"ok": False, "reason": f"状态 {session.state} 不能响应死亡（探索版 S1/S2，2a3 §4.1）",
                "state": session.state, "session": session}
    tr = machine.transition("death", session)
    if not tr["ok"]:
        return {"ok": False, "reason": tr["reason"], "state": session.state, "session": session}
    revive = _safe_zone(dungeon_def)  # 默认复活点=入口=safe_zone（death_policy.revive_point 可配批次 7）
    sess2 = tr["session"].with_current_map(revive)
    _set_map_id(player_ctx, revive)
    return {"ok": True, "event": "death", "state": S6, "session": sess2, "map_id": revive}


def _step_recover(machine: "DungeonStateMachine", session: DungeonSession) -> dict:
    """虚弱结束 → S1（M11：从复活点/安全区恢复探索）。"""
    tr = machine.transition("recover", session)
    if not tr["ok"]:
        return {"ok": False, "reason": tr["reason"], "state": session.state, "session": session}
    return {"ok": True, "event": "recover", "state": S1, "session": tr["session"],
            "map_id": tr["session"].current_map}


def _step_rest(machine: "DungeonStateMachine", dungeon_def: DungeonDef,
               session: DungeonSession) -> dict:
    """安全区 /休息（M15：原地休息≠离开；非安全区拒绝 TC-2a3-15【补白 10】）。"""
    safe = _safe_zone(dungeon_def)
    if session.current_map is None or session.current_map != safe:
        return {"ok": False, "reason": "非安全区不可 /休息（2a3 R16 / TC-2a3-15：安全区 /休息 ≠ 离开）",
                "state": session.state, "session": session}
    tr = machine.transition("rest", session)
    if not tr["ok"]:
        return {"ok": False, "reason": tr["reason"], "state": session.state, "session": session}
    return {"ok": True, "event": "rest", "state": tr["state"], "session": tr["session"],
            "rest_count": tr["session"].rest_count}


def _step_leave(machine: "DungeonStateMachine", player_ctx: dict,
                session: DungeonSession) -> dict:
    """非战斗离开 → S7（M12/M13/M14：副本重置 + 回外部锚点 R8）。"""
    tr = machine.transition("leave", session)
    if not tr["ok"]:
        return {"ok": False, "reason": tr["reason"], "state": session.state, "session": session}
    anchor = tr["session"].external_anchor
    _set_map_id(player_ctx, anchor)  # R8：回进入时世界节点坐标
    return {"ok": True, "event": "leave", "state": S7, "session": tr["session"], "map_id": anchor}
