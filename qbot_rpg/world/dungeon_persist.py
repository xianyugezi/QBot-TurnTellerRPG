"""M3 批次7·路U：M29 副本内死亡处理 + M30 副本会话持久化（qbot_rpg/world/dungeon_persist.py）。

依据：
  - 细化_2a3_副本两型流程.md §2（S6 死亡复活态：复活点 + 虚弱期禁入非安全区含 BOSS 房；
    迁移表 M9：S4→S6、M10：S3→S6、M11：S6→S1、M14：S6→S7 死亡后主动离开=重置）
    + §4（死亡处理与离开重置 R26-R32：复活点默认入口可配 R27 / 惩罚三档 R28 /
    未配 checkpoint 自动降级重置 R29 / BOSS 状态 keep-reset R30 / 死亡≠离开 R31 /
    虚弱 1 分钟可配禁入非安全区 / 复活点=安全区可休息）
  - m3_shared_contract §4.4（副本内死亡：复活点复活 + 虚弱期禁入非安全区含 BOSS 房；
    死亡 ≠ 离开，离开即重置；副本会话持久化：当前区域/已清区域/子任务进度/换区上下文/
    BOSS 状态/休息次数随存档，清理时机=通关/重置；含 content_pack_id+version 防跨包串档）
  - 规划_路2a_地图副本.md M29（副本内死亡处理：复活点/checkpoint/BOSS 状态/虚弱）
    + M30（副本进度会话持久化：随玩家存档、清理时机=通关/重置、防跨包串档）
  - 衔接 world/battle_boundary.py（DEATH-07 find_nearest_respawn_point：最近安全区 BFS /
    DEATH-02 虚弱时间态 WEAK_UNTIL_KEY / DEATH-01 默认 60 秒 / DEATH-08 界别：副本内死亡
    走 2a3 §4.1，不落野图结算链）+ world/chase_resume.py（离开=重置、换区上下文顶层键
    清单【补白 7】）

职责（world 层纯逻辑：零 NoneBot import、零 IO、纯函数/纯数据契约；存储层真实 IO
由 M4 路3 A4 接线——本模块文档进出、不落库）：
  on_dungeon_death          M29：副本内死亡结算——复活点复活（revive_point/checkpoint/
                            safe_zone 优先，BFS 兜底衔接 battle_boundary）+ 虚弱标记
                            （weakened: True，禁入非安全区含 BOSS 房）+ BOSS 状态保留
                            （死亡≠离开，离开才重置）
  save_dungeon_session      M30：序列化副本会话（当前区域/已清/子任务/换区上下文/BOSS/
                            休息次数 + content_pack_id+version 防跨包串档）
  load_dungeon_session      M30：反序列化缺补默认；content_pack_id 不匹配 → 拒绝信号不串档
  clear_dungeon_session     M30：通关/重置清理会话
  is_weakened / check_weakened_entry   虚弱判定与禁入非安全区检查（含 BOSS 房）

【工程补白】（显式标注，不冒充定稿）：
  1. 存储层真实 IO（存档落点、事务、清理删除）由 M4 路3 A4 接线；save/load/clear 为纯
     数据契约：save 产文档 → load 消费该文档（或存储读回同形文档）；clear 消费
     {dungeon_id: doc} 会话容器或单文档并返回新容器（纯函数不改入参）。
  2. 虚弱标记落点：本路纯数据契约 = 会话持久化 dict 顶层 weakened/weak_until + player_ctx
     镜像（ctx["weakened"]/["weak_until"]）；权威时间态（player persistent_state 的
     WEAK_UNTIL_KEY，1g4 DEATH-02）由 M4 死亡结算链 battle_boundary.apply_weakness 落地。
     DungeonSession dataclass 无 weakened 字段——死亡后会话一律以持久化 dict 形态返回
     （M4 可经 DungeonSession.from_dict 重建，临时键被忽略）。
  3. 复活点解析优先级（R27 / M29 实现要点）：① death_policy.revive_point（显式配置，
     可指向 checkpoint 区/任意区域）→ ② BFS 兜底（衔接 battle_boundary.find_nearest_
     respawn_point：死亡图按地图连通关系找最近安全区，safe_zones={safe_zone}，
     default=safe_zone；2a1c R3 缺省 safe_zone=maps[0]）。checkpoint 参与复活点仅经
     revive_point 显式指向；checkpoint 默认职责 = 进度回退（TC-2a3-10：复活于入口、
     进度回退到 checkpoint）。BFS 连通只计非隐藏通道（hidden=条件门，复活路径不可依赖）。
  4. checkpoint 回退契约（M29 / TC-2a3-10）：checkpoints = 区域快照点列表；最近已到达
     checkpoint = 按 dungeon.maps 配置序最后一个 ∈ cleared_maps 者；回退 = cleared_maps
     保留至该 checkpoint 区（含），其后图需重探；子任务/休息/BOSS 按其配置处理。
     未配置 checkpoints 或未到达任何 checkpoint → R29 自动降级为重置副本（不悬空）。
  5. penalty 三档（R28）：checkpoint（默认；未配/未到达自动降级 reset）/ reset（等价
     离开重置：进度/BOSS/休息全清，满状态重打 TC-2a3-11）/ none（仅复活，进度原样保留，
     低难探索适用 TC-2a3-12）。
  6. BOSS 状态（R30）：boss_state 模式 keep（默认）→ 残血/阶段保留（死亡≠离开）；reset →
     清空满状态重打；penalty=reset 或降级重置恒清空（TC-2a3-11/13 满状态重打）。
  7. 死亡可达状态 = S1/S2/S3/S4（契约迁移表 M9：S4→S6、M10：S3→S6；探索版 S1/S2→S6
     为 core.dungeon 补白 3 口径）；S0/S5/S6/S7 拒绝（S6 已死亡不重复结算）。
  8. 虚弱时长：death_policy.weak_duration_sec 可配，缺省 60 秒（1g4 DEATH-01 / 框架
     L285）；now_iso 未提供时仅出 weakened 标记不出 weak_until（时间态由接线补齐）。
     **0 = 不虚弱**（对齐 battle_boundary.apply_weakness「0 → 不虚弱」口径）：不写
     weakened/weak_until 标记（含会话与 ctx 镜像），死亡仅复活不进入虚弱期
     （审查_M3_批次4 P1-2 修复：此前 weak_duration_sec=0 仍写 weakened=True 且无
     weak_until，is_weakened 回退布尔标记 → 玩家被永久禁入非安全区）。
  9. on_dungeon_death 玩家位置落点：→ 复活点（与 core.dungeon enter/_step_death 同口径
     就地改 player_ctx["map_id"] + player["map_id"]；纯数据契约，无 IO）。

铁律：零 NoneBot import；纯函数（无 IO、确定性）；平台无关（细化_3a R1）；不拼玩家文案
（返回约定值/信号由壳层翻译）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple, cast

from qbot_rpg.content.dungeon_models import DungeonDef
from qbot_rpg.content.map_models import MapDef, parse_maps
from qbot_rpg.world.battle_boundary import find_nearest_respawn_point

__all__ = [
    "STATE_DEAD_RECOVER",
    "WEAK_DURATION_DEFAULT_SEC",
    "WEAKENED_KEY",
    "WEAK_UNTIL_KEY",
    "PENALTY_CHECKPOINT",
    "PENALTY_RESET",
    "PENALTY_NONE",
    "BOSS_STATE_KEEP",
    "BOSS_STATE_RESET",
    "SCHEMA_VERSION",
    "DEFAULT_DUNGEON_TYPE",
    "DEFAULT_STATE",
    "on_dungeon_death",
    "save_dungeon_session",
    "load_dungeon_session",
    "clear_dungeon_session",
    "is_weakened",
    "check_weakened_entry",
]

# -------------------------------------------------------------------------------------
# 常量（契约 §4.2 状态键 / 1g4 DEATH / 2a3 §4 配置档）
# -------------------------------------------------------------------------------------

#: S6 死亡复活态（对齐 core.dungeon.S6；world 层自持常量避免跨层依赖——chase_resume 同风格）。
STATE_DEAD_RECOVER: str = "DEAD_RECOVER"

#: 虚弱缺省时长（1g4 DEATH-01 / 框架 L285：默认 1 分钟）。
WEAK_DURATION_DEFAULT_SEC: int = 60

#: 会话/ctx 虚弱标记键（本路纯数据契约标记，补白 2）。
WEAKENED_KEY: str = "weakened"

#: 会话/ctx 虚弱截止键（ISO-8601 UTC，时间态；对齐 battle_boundary.WEAK_UNTIL_KEY 语义）。
WEAK_UNTIL_KEY: str = "weak_until"

#: R28 惩罚三档。
PENALTY_CHECKPOINT: str = "checkpoint"   # ① checkpoint 回退（默认）
PENALTY_RESET: str = "reset"             # ② 重置副本
PENALTY_NONE: str = "none"               # ③ 无惩罚（低难探索适用）

#: R30 BOSS 状态两档。
BOSS_STATE_KEEP: str = "keep"            # 保留残血（默认）
BOSS_STATE_RESET: str = "reset"          # 满状态重打

#: 副本会话存档文档 schema 版本（防串档/迁移锚点；M4 存储层随文档落库）。
SCHEMA_VERSION: int = 1

#: 缺省会话字段（对齐 DungeonSession 缺省：dungeon_type="explore" / state=S0=ENTRY）。
DEFAULT_DUNGEON_TYPE: str = "explore"
DEFAULT_STATE: str = "ENTRY"

#: 死亡可达状态（契约迁移表 M9：S4→S6、M10：S3→S6 + 探索版 S1/S2→S6 补白 7）。
_DEATH_ELIGIBLE_STATES: Tuple[str, ...] = (
    "PEACE_EXPLORE", "ELITE_ESCALATE", "BOSS_CHASE", "FINAL_DEATHMATCH",
)

#: 换区上下文顶层键（对齐 chase_resume 补白 7：m3 §4.4 换区上下文随副本会话持久化）。
_ZONE_CHASE_KEYS: Tuple[str, ...] = ("chase_ctx", "zone_chase", "chase", "chasing", "chase_target")


# -------------------------------------------------------------------------------------
# 数据归一辅助（纯函数，无 IO）
# -------------------------------------------------------------------------------------


def _is_num(value: object) -> bool:
    """数值校验（排除 bool——bool 是 int 子类）。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _norm_dungeon_def(dungeon_def: object) -> DungeonDef:
    """dungeon_def 入参归一：DungeonDef 直通 / raw dict → from_entry；其余形态抛 TypeError。"""
    if isinstance(dungeon_def, DungeonDef):
        return dungeon_def
    if isinstance(dungeon_def, Mapping):
        return cast(DungeonDef, DungeonDef.from_entry(dungeon_def))
    raise TypeError("dungeon_def 须为 DungeonDef 或 dict")


def _resolve_dungeon_def(player_ctx: Mapping[str, Any], dungeon_def: object) -> Optional[DungeonDef]:
    """副本定义解析：显式 kwarg → ctx["dungeon_def"] → ctx["dungeon"] → player["dungeon_def"]。"""
    src = dungeon_def
    if src is None:
        src = player_ctx.get("dungeon_def")
    if src is None:
        src = player_ctx.get("dungeon")
    if src is None:
        player = player_ctx.get("player")
        if isinstance(player, Mapping):
            src = player.get("dungeon_def")
    if src is None:
        return None
    if isinstance(src, DungeonDef):
        return src
    if isinstance(src, Mapping):
        try:
            return cast(DungeonDef, DungeonDef.from_entry(src))
        except (TypeError, ValueError):
            return None
    return None


def _maps_index(maps_src: object) -> Dict[str, MapDef]:
    """maps 入参归一 → {map_id: MapDef}（形态对齐 world/movement._maps_index，零失败）。"""
    if maps_src is None:
        return {}
    if isinstance(maps_src, Mapping):
        if "maps" in maps_src:  # modules 容器（content 装载形态）
            if isinstance(maps_src.get("maps"), list):
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
    """安全区地图：safe_zone 配置；缺省 = maps[0]（2a1c R3 入口区缺省即安全区）。"""
    sz = dungeon_def.safe_zone
    if isinstance(sz, str) and sz:
        return sz
    maps = dungeon_def.maps
    return str(maps[0]) if maps else None


def _adjacency(maps_index: Mapping[str, MapDef], dungeon_ids: Iterable[str]) -> Dict[str, list]:
    """副本内地图连通表 {map_id: [neighbor, ...]}（集合隔离 R5：只记 dungeon.maps 集合内）。

    通道模式 hidden（条件门，2a1b R7-R9）不计连通——复活路径不可依赖条件门（补白 3）。
    """
    idset = set(dungeon_ids)
    adj: Dict[str, list] = {}
    for map_id in idset:
        md = maps_index.get(map_id)
        if md is None:
            continue
        for ex in md.exits.values():
            if ex is None or not ex.to:
                continue
            if ex.mode == "hidden":
                continue
            nxt = str(ex.to)
            if nxt in idset:
                adj.setdefault(map_id, []).append(nxt)
    return adj


def _set_map_id(player_ctx: dict, map_id: Optional[str]) -> None:
    """玩家位置原地改（对齐 core.dungeon._set_map_id：ctx["map_id"] + player["map_id"]）。"""
    player_ctx["map_id"] = map_id
    player = player_ctx.get("player")
    if isinstance(player, dict):
        player["map_id"] = map_id


def _session_dict(session: object) -> Dict[str, Any]:
    """会话 → dict 形态：DungeonSession（has to_dict）/ 持久化 dict / 其他 Mapping 直通。"""
    if session is None:
        return {}
    if isinstance(session, Mapping):
        return dict(session)
    to_dict = getattr(session, "to_dict", None)
    if callable(to_dict):
        d = to_dict()
        return dict(d) if isinstance(d, Mapping) else {}
    return {}


def _normalize_cleared(raw: object) -> frozenset:
    """已清/已到访图集合归一（list/set/tuple/Mapping 键形态 → frozenset，对齐 from_dict）。"""
    if isinstance(raw, Mapping):
        return frozenset(str(k) for k in raw.keys())
    if isinstance(raw, (list, tuple, set, frozenset)):
        return frozenset(str(x) for x in raw)
    return frozenset()


def _mapping_dict(raw: object) -> Dict[str, Any]:
    """Mapping → dict 拷贝；非 Mapping → {}（pyright 友好窄化）。"""
    return dict(raw) if isinstance(raw, Mapping) else {}


def _iso_parse(iso: str) -> Optional[datetime]:
    """ISO-8601 UTC 字符串解析（Z → +00:00）；失败返回 None。"""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _add_iso_seconds(iso: str, seconds: int) -> Optional[str]:
    """ISO-8601 UTC 字符串 + 秒 → ISO-8601 UTC（对齐 battle_boundary._add_iso_seconds）。"""
    dt = _iso_parse(iso)
    if dt is None:
        return None
    return (dt + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _iso_remaining_sec(until_iso: str, now_iso: str) -> int:
    """虚弱剩余秒数（≤0 = 未虚弱；解析失败保守返回 0）。"""
    until = _iso_parse(until_iso)
    now = _iso_parse(now_iso)
    if until is None or now is None:
        return 0
    delta = until - now
    if delta.total_seconds() <= 0:
        return 0
    return int(delta.total_seconds())


# -------------------------------------------------------------------------------------
# 副本死亡配置解析（death_policy / checkpoints，R27-R30；dungeon_def.raw 读取）
# -------------------------------------------------------------------------------------


def _death_policy(dungeon_def: DungeonDef) -> Dict[str, Any]:
    """death_policy 配置解析（dungeon.json raw；容错缺省，红拦归属 content 校验器）。

    字段：revive_point（R27 复活点，可指向 checkpoint 区）/ penalty（R28 三档，缺省
    checkpoint）/ boss_state（R30 keep-reset，缺省 keep）/ weak_duration_sec（补白 8，
    缺省 60）。
    """
    dp = dungeon_def.raw.get("death_policy")
    dp = dp if isinstance(dp, Mapping) else {}
    penalty = dp.get("penalty")
    if penalty not in (PENALTY_CHECKPOINT, PENALTY_RESET, PENALTY_NONE):
        penalty = PENALTY_CHECKPOINT
    boss_mode = dp.get("boss_state")
    if boss_mode not in (BOSS_STATE_KEEP, BOSS_STATE_RESET):
        boss_mode = BOSS_STATE_KEEP
    revive = dp.get("revive_point")
    revive = revive if isinstance(revive, str) and revive else None
    wd = dp.get("weak_duration_sec")
    weak = wd if isinstance(wd, int) and not isinstance(wd, bool) and wd >= 0 \
        else WEAK_DURATION_DEFAULT_SEC
    return {
        "revive_point": revive,
        "penalty": penalty,
        "boss_state": boss_mode,
        "weak_duration_sec": weak,
    }


def _checkpoints(dungeon_def: DungeonDef) -> Tuple[str, ...]:
    """checkpoints 列表（M29：区域快照点列表；非 string 项跳过）。"""
    raw = dungeon_def.raw.get("checkpoints")
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(str(c) for c in raw if isinstance(c, str) and c)


def _resolve_respawn_point(
    death_map: str,
    dungeon_def: DungeonDef,
    maps_index: Mapping[str, MapDef],
    policy: Mapping[str, Any],
) -> Tuple[str, dict]:
    """复活点解析（补白 3 优先级）：① revive_point 显式 → ② BFS 兜底（safe_zone）。

    checkpoint 参与复活点仅经 death_policy.revive_point 显式指向（R27「可配 revive_point
    指定区域（如 checkpoint 区）」）；checkpoint 的默认职责 = 进度回退（TC-2a3-10：复活于
    入口、进度回退到 checkpoint），见 _rollback_cleared。
    """
    dungeon_ids = {str(m) for m in dungeon_def.maps}
    safe = _safe_zone(dungeon_def)
    # ① 显式配置（R27：death_policy.revive_point；可指向 checkpoint 区 / 任意区域）
    rp = policy.get("revive_point")
    if isinstance(rp, str) and rp and rp in dungeon_ids:
        return rp, {"source": "revive_point"}
    # ② BFS 兜底（衔接 battle_boundary DEATH-07：死亡图按连通找最近安全区；复活点=安全区 R27）
    fallback = find_nearest_respawn_point(
        death_map,
        adjacency=_adjacency(maps_index, dungeon_ids),
        respawn_points={},
        safe_zones=[safe] if safe else [],
        default=safe or death_map,
    )
    return fallback, {"source": "bfs"}


def _rollback_cleared(
    cleared: frozenset,
    checkpoints: Tuple[str, ...],
    dungeon_maps: Sequence[object],
) -> Tuple[Optional[frozenset], Optional[str]]:
    """checkpoint 回退：cleared_maps 保留至最近已到达 checkpoint 区（含）。

    返回 (None, None) = 未到达任何 checkpoint（调用方按 R29 降级重置）。
    """
    order = {str(m): i for i, m in enumerate(dungeon_maps)}
    reached = [c for c in checkpoints if c in cleared]
    if not reached:
        return None, None
    deepest = max(reached, key=lambda c: order.get(c, -1))
    idx = order.get(deepest, -1)
    kept = frozenset(m for m in cleared if order.get(m, -1) <= idx) | {deepest}
    return kept, deepest


# -------------------------------------------------------------------------------------
# M29：副本内死亡处理（复活点 + 虚弱 + BOSS 保留；2a3 §4 R26-R32 / 契约 §4.4）
# -------------------------------------------------------------------------------------


def on_dungeon_death(
    player_ctx: dict,
    session: object,
    dungeon_def: object = None,
    maps: object = None,
    now_iso: str = "",
) -> dict:
    """副本内死亡结算（M29 / 2a3 §4.1 R26-R32 + 契约 §4.4：死亡≠离开）。

    复活点复活（补白 3 优先级：revive_point 显式（可指向 checkpoint 区）→ BFS 兜底
    衔接 battle_boundary；safe_zone 为缺省复活点）+ 虚弱标记（weakened: True，虚弱中禁入
    非安全区含 BOSS 房，check_weakened_entry 判定）+ BOSS 状态保留（残血不因死亡重置——
    死亡≠离开，离开才重置；R30 keep/reset 按 death_policy.boss_state 配置）。

    Args:
        player_ctx: 玩家上下文 dict（位置就地改 → 复活点；dungeon_def/maps 兜底源；
            ctx["weakened"]/["weak_until"] 虚弱镜像写入，补白 2）。
        session: 副本会话（DungeonSession dataclass 或持久化 dict 形态）。
        dungeon_def: 副本定义（DungeonDef 或 raw dict）；缺省读 player_ctx。
        maps: 地图源（modules 容器/MapDef 列表/节点 dict 列表，BFS 连通表用）；缺省
            player_ctx["maps"]。
        now_iso: 当前时间 ISO-8601 UTC（提供时出 weak_until；缺省仅 weakened 标记）。

    Returns:
        成功：{revived: True, state: "DEAD_RECOVER", respawn_point, respawn_source,
          weakened: bool（weak_duration_sec>0 时 True，0=不虚弱）, weak_until,
          boss_state_preserved, session: 更新后持久化 dict,
          progress: {penalty, rolled_back, checkpoint_zone, degraded_to_reset}, note}
        拒绝：{revived: False, reason, state, session}（原会话不变、不改 ctx）。
    """
    ddef = _resolve_dungeon_def(player_ctx, dungeon_def)
    if ddef is None:
        return {"revived": False,
                "reason": "缺少副本定义（dungeon_def），无法解析复活点/死亡配置",
                "state": _session_dict(session).get("state"), "session": session}

    sess = _session_dict(session)
    if not sess:
        return {"revived": False, "reason": "会话形态非法（须 DungeonSession 或持久化 dict）",
                "state": None, "session": session}
    state = str(sess.get("state", ""))
    if state not in _DEATH_ELIGIBLE_STATES:
        return {"revived": False,
                "reason": f"状态 {state} 不能响应副本内死亡（迁移表 M9/M10：S1/S2/S3/S4→S6）",
                "state": state, "session": session}

    death_map = sess.get("current_map")
    if not isinstance(death_map, str) or not death_map:
        death_map = player_ctx.get("map_id") or ""
    cleared = _normalize_cleared(sess.get("cleared_maps"))
    maps_src = maps if maps is not None else player_ctx.get("maps")
    maps_index = _maps_index(maps_src)

    policy = _death_policy(ddef)
    checkpoints = _checkpoints(ddef)
    respawn, info = _resolve_respawn_point(
        death_map, ddef, maps_index, policy)

    # ---- 进度处理（R28 三档）------------------------------------------------------
    penalty = policy["penalty"]
    new_cleared = cleared
    new_sub: Dict[str, int] = {
        str(k): v for k, v in _mapping_dict(sess.get("subquest_progress")).items()
        if isinstance(v, int) and not isinstance(v, bool)
    }
    new_rest = sess.get("rest_count")
    new_rest = new_rest if isinstance(new_rest, int) and not isinstance(new_rest, bool) else 0
    rolled_back = False
    checkpoint_zone: Optional[str] = None
    degraded_to_reset = False
    if penalty == PENALTY_RESET:
        new_cleared = frozenset()
        new_sub = {}
        new_rest = 0
    elif penalty == PENALTY_CHECKPOINT:
        if checkpoints:
            rb, zone = _rollback_cleared(cleared, checkpoints, ddef.maps)
            if rb is not None:
                new_cleared = rb
                rolled_back = True
                checkpoint_zone = zone
            else:
                # R29：未到达任何 checkpoint → 自动降级为重置副本
                new_cleared = frozenset()
                new_sub = {}
                new_rest = 0
                degraded_to_reset = True
        else:
            # R29：未配置 checkpoint → 自动降级为重置副本（不悬空）
            new_cleared = frozenset()
            new_sub = {}
            new_rest = 0
            degraded_to_reset = True
    # penalty == none → 进度/BOSS 原样保留（TC-2a3-12）

    # ---- BOSS 状态（R30 + 降级/重置恒清空）----------------------------------------
    boss_cleared = penalty == PENALTY_RESET or degraded_to_reset or policy["boss_state"] == BOSS_STATE_RESET
    new_boss = {} if boss_cleared else _mapping_dict(sess.get("boss_state"))

    # ---- 虚弱标记（补白 2/8）：weak_duration_sec==0 → 不虚弱（不写 weakened/weak_until，
    # 对齐 battle_boundary.apply_weakness「0 → 不虚弱」；审查_M3_批次4 P1-2 修复）------------
    weaken = policy["weak_duration_sec"] > 0
    weak_until: Optional[str] = None
    if weaken and now_iso:
        weak_until = _add_iso_seconds(now_iso, policy["weak_duration_sec"])

    # ---- 会话更新（持久化 dict 形态）-----------------------------------------------
    new_sess = dict(sess)
    new_sess.update({
        "state": STATE_DEAD_RECOVER,
        "current_map": respawn,
        "cleared_maps": sorted(new_cleared),
        "subquest_progress": new_sub,
        "boss_state": new_boss,
        "rest_count": new_rest,
    })
    if weaken:
        new_sess[WEAKENED_KEY] = True
        if weak_until is not None:
            new_sess[WEAK_UNTIL_KEY] = weak_until
    else:
        new_sess.pop(WEAKENED_KEY, None)
        new_sess.pop(WEAK_UNTIL_KEY, None)

    # 玩家位置 → 复活点 + 虚弱镜像（纯数据契约；权威时间态由 M4 结算链落地）
    _set_map_id(player_ctx, respawn)
    if weaken:
        player_ctx[WEAKENED_KEY] = True
        if weak_until is not None:
            player_ctx[WEAK_UNTIL_KEY] = weak_until
    else:
        player_ctx.pop(WEAKENED_KEY, None)
        player_ctx.pop(WEAK_UNTIL_KEY, None)

    return {
        "revived": True,
        "state": STATE_DEAD_RECOVER,
        "respawn_point": respawn,
        "respawn_source": info.get("source"),
        "weakened": weaken,
        "weak_until": weak_until,
        "boss_state_preserved": not boss_cleared,
        "session": new_sess,
        "progress": {
            "penalty": penalty,
            "rolled_back": rolled_back,
            "checkpoint_zone": checkpoint_zone,
            "degraded_to_reset": degraded_to_reset,
        },
        "note": "副本内死亡：复活点复活 + 虚弱（禁入非安全区含 BOSS 房）；"
                "死亡≠离开，BOSS 状态按配置保留/重置，离开才重置",
    }


# -------------------------------------------------------------------------------------
# M30：副本会话持久化（序列化 / 反序列化缺补默认 / content_pack 防串档 / 清理）
# -------------------------------------------------------------------------------------


def save_dungeon_session(session: object) -> dict:
    """序列化副本会话（M30 / m3 §4.4：当前区域/已清区域/子任务进度/换区上下文/BOSS 状态/
    休息次数随存档 + content_pack_id+version 防跨包串档）。

    产出存档文档（含 schema_version）；换区上下文顶层键（chase_ctx/zone_chase/chase/
    chasing/chase_target，对齐 chase_resume 补白 7）收拢进 zone_chase_context 子文档，
    load 时还原。weakened/weak_until 临时标记随档透传（补白 2）。

    Args:
        session: 副本会话（DungeonSession dataclass 或持久化 dict 形态）。

    Returns:
        成功：存档文档 dict（即 M4 路3 A4 落库负载）。
        拒绝：{ok: False, reason}（会话无 dungeon_id，无法序列化）。
    """
    base = _session_dict(session)
    if not isinstance(base.get("dungeon_id"), str) or not base["dungeon_id"]:
        return {"ok": False,
                "reason": "会话无 dungeon_id（须 DungeonSession 或持久化 dict）"}

    cleared = _normalize_cleared(base.get("cleared_maps"))
    sub = base.get("subquest_progress")
    sub_norm = {str(k): v for k, v in sub.items()} if isinstance(sub, Mapping) else {}
    boss = base.get("boss_state")
    boss_norm = dict(boss) if isinstance(boss, Mapping) else {}
    rest = base.get("rest_count")
    rest_norm = rest if isinstance(rest, int) and not isinstance(rest, bool) else 0

    out: Dict[str, Any] = {"schema_version": SCHEMA_VERSION}
    for k in ("dungeon_id", "dungeon_type", "state", "current_map", "external_anchor",
              "content_pack_id", "content_pack_version", WEAKENED_KEY, WEAK_UNTIL_KEY):
        if k in base:
            out[k] = base[k]
    out["cleared_maps"] = sorted(cleared)
    out["subquest_progress"] = sub_norm
    out["boss_state"] = boss_norm
    out["rest_count"] = rest_norm
    zone_chase = {k: base[k] for k in _ZONE_CHASE_KEYS if k in base}
    if zone_chase:
        out["zone_chase_context"] = zone_chase
    return out


def _normalize_session_dict(doc: Mapping[str, Any]) -> Dict[str, Any]:
    """存档文档 → 会话持久化 dict（缺补默认；与 DungeonSession.from_dict 同缺省口径）。

    缺省：dungeon_type="explore" / state="ENTRY" / cleared_maps=[] / subquest_progress={}
    / boss_state={} / rest_count=0 / current_map 与 external_anchor 原样（可为 None）。
    """
    cleared = _normalize_cleared(doc.get("cleared_maps"))
    sub = doc.get("subquest_progress")
    sub_norm = {str(k): v for k, v in sub.items()
                if isinstance(v, int) and not isinstance(v, bool)} if isinstance(sub, Mapping) else {}
    boss = doc.get("boss_state")
    boss_norm = dict(boss) if isinstance(boss, Mapping) else {}
    rest = doc.get("rest_count")
    rest_norm = rest if isinstance(rest, int) and not isinstance(rest, bool) else 0

    sess: Dict[str, Any] = {
        "dungeon_id": str(doc.get("dungeon_id", "")),
        "dungeon_type": str(doc.get("dungeon_type", DEFAULT_DUNGEON_TYPE)),
        "state": str(doc.get("state", DEFAULT_STATE)),
        "current_map": doc.get("current_map"),
        "cleared_maps": sorted(cleared),
        "subquest_progress": sub_norm,
        "boss_state": boss_norm,
        "rest_count": rest_norm,
        "external_anchor": doc.get("external_anchor"),
    }
    for k in ("content_pack_id", "content_pack_version"):
        if k in doc:
            sess[k] = doc[k]
    # 临时标记透传（补白 2）
    if WEAKENED_KEY in doc:
        sess[WEAKENED_KEY] = doc[WEAKENED_KEY]
    if WEAK_UNTIL_KEY in doc:
        sess[WEAK_UNTIL_KEY] = doc[WEAK_UNTIL_KEY]
    # 换区上下文还原到顶层（m3 §4.4 换区上下文随副本会话持久化）
    zc = doc.get("zone_chase_context")
    if isinstance(zc, Mapping):
        for k in _ZONE_CHASE_KEYS:
            if k in zc:
                sess[k] = zc[k]
    return sess


def load_dungeon_session(store: object, content_pack_id: Optional[str] = None,
                         expected_version: Optional[str] = None) -> dict:
    """反序列化副本会话（M30）：缺补默认；content_pack 不匹配 → 拒绝信号不串档。

    Args:
        store: 存档文档（save_dungeon_session 产物 / 存储层读回同形文档）。
        content_pack_id: 当前内容包 ID；提供时校验文档 content_pack_id 一致（防跨包
            串档）。文档缺 content_pack_id（旧档）且提供期望 → 按不匹配拒绝（保守）。
        expected_version: 当前内容包版本；提供时校验文档 content_pack_version 一致
            （契约 §4.4「id+version 防跨包串档」的 version 侧；审查_M3_批次4 P2-15）。
            文档缺 content_pack_version（旧档）且提供期望 → 按不匹配拒绝（保守）。

    Returns:
        成功：{ok: True, session: 会话持久化 dict（缺补默认后）, dungeon_id,
          content_pack_id, content_pack_version, schema_version}
        拒绝：{ok: False, reason: "invalid_store" | "content_pack_mismatch"
          | "content_pack_version_mismatch", session: None, ...}（不产出会话，不串档）
    """
    if not isinstance(store, Mapping):
        return {"ok": False, "reason": "invalid_store", "session": None,
                "note": "store 须为 save_dungeon_session 产出的存档文档（含 dungeon_id）"}
    if not isinstance(store.get("dungeon_id"), str) or not store["dungeon_id"]:
        return {"ok": False, "reason": "invalid_store", "session": None,
                "note": "store 须为 save_dungeon_session 产出的存档文档（含 dungeon_id）"}

    found = store.get("content_pack_id")
    found = str(found) if isinstance(found, str) and found else None
    if content_pack_id and found != content_pack_id:
        return {"ok": False, "reason": "content_pack_mismatch",
                "expected": content_pack_id, "found": found, "session": None,
                "note": "存档 content_pack 与当前内容包不匹配：拒绝加载，防跨包串档（M30）"}
    if expected_version is not None:
        found_ver = store.get("content_pack_version")
        found_ver = str(found_ver) if isinstance(found_ver, str) and found_ver else None
        if found_ver != expected_version:
            return {"ok": False, "reason": "content_pack_version_mismatch",
                    "expected_version": expected_version, "found_version": found_ver,
                    "session": None,
                    "note": "存档 content_pack_version 与当前内容包版本不匹配：拒绝加载，"
                            "防跨包串档（M30 / 契约 §4.4 id+version 双侧）"}

    sess = _normalize_session_dict(store)
    return {
        "ok": True,
        "session": sess,
        "dungeon_id": sess.get("dungeon_id"),
        "content_pack_id": sess.get("content_pack_id"),
        "content_pack_version": sess.get("content_pack_version"),
        "schema_version": store.get("schema_version", 0),
    }


def clear_dungeon_session(store: object, dungeon_id: str) -> dict:
    """通关/重置清理副本会话（M30：清理时机=通关/重置）。

    Args:
        store: 会话存储容器 {dungeon_id: doc}（清键）或单文档（清行）。None → 视为空容器。
        dungeon_id: 待清理副本 ID。

    Returns:
        成功：{ok: True, cleared: bool（是否存在）, dungeon_id, store: 清理后容器
          （单文档形态 → None）, note}
        形态非法：{ok: False, reason: "invalid_store", dungeon_id, note}
        纯函数：不改入参 store，返回新容器。
    """
    did = "" if dungeon_id is None else str(dungeon_id)
    if isinstance(store, Mapping):
        probe = store.get("dungeon_id")
        if isinstance(probe, str) and probe:
            # 单文档形态
            if probe == did:
                return {"ok": True, "cleared": True, "dungeon_id": did, "store": None,
                        "note": "通关/重置：会话文档已清理（存储行删除由 M4 路3 A4 接线）"}
            return {"ok": True, "cleared": False, "dungeon_id": did, "store": store,
                    "note": "通关/重置：会话文档已清理（存储行删除由 M4 路3 A4 接线）"}
        # 容器形态：剔除目标键，返回新容器
        new_store = {k: v for k, v in store.items() if str(k) != did}
        existed = len(new_store) != len(store)
        return {"ok": True, "cleared": existed, "dungeon_id": did, "store": new_store,
                "note": "通关/重置：副本会话已从容器清理（落库删除由 M4 路3 A4 接线）"}
    if store is None:
        return {"ok": True, "cleared": False, "dungeon_id": did, "store": {},
                "note": "通关/重置：无既有会话可清理"}
    return {"ok": False, "reason": "invalid_store", "dungeon_id": did,
            "note": "store 须为 {dungeon_id: doc} 容器或单文档"}


# -------------------------------------------------------------------------------------
# 虚弱判定与禁入非安全区（含 BOSS 房）检查（2a3 §4.3 虚弱衔接 / 契约 §4.4）
# -------------------------------------------------------------------------------------


def is_weakened(session: object = None, player_ctx: object = None, now_iso: str = "") -> bool:
    """虚弱判定（补白 2）：会话 dict weakened/weak_until + ctx 镜像 + player persistent 兜底。

    - 存在 weak_until（时间态）且提供 now_iso → 按剩余秒数判定（≤0 = 虚弱结束）
    - 否则回退 weakened 布尔标记
    """
    sources: list = []
    if session is not None:
        sources.append(_session_dict(session))
    if isinstance(player_ctx, Mapping):
        sources.append(player_ctx)
        player = player_ctx.get("player")
        if isinstance(player, Mapping):
            sources.append(player)
    flag_weakened = any(src.get(WEAKENED_KEY) is True for src in sources)
    weak_until: Optional[str] = None
    for src in sources:
        wu = src.get(WEAK_UNTIL_KEY)
        if isinstance(wu, str) and wu:
            weak_until = wu
            break
    if weak_until is not None:
        if not now_iso:
            return flag_weakened  # 无时间基准：以标记为准
        return _iso_remaining_sec(weak_until, now_iso) > 0
    return flag_weakened


def check_weakened_entry(
    session: object,
    map_id: str,
    dungeon_def: object = None,
    player_ctx: object = None,
    now_iso: str = "",
) -> dict:
    """虚弱期间禁入非安全区检查（含 BOSS 房；2a3 R31 / 契约 §4.4）。

    非虚弱 → {ok: True, weakened: False}。虚弱中：安全区（可滞留/休息）放行；
    其余地图（含 BOSS 房）拦截。dungeon_def 缺失时 fail-safe 拦截（无法判定安全区）。

    Returns:
        {ok, weakened, map_id, reason?, safe_zone?}
    """
    mid = "" if map_id is None else str(map_id)
    weak = is_weakened(session, player_ctx, now_iso)
    if not weak:
        return {"ok": True, "weakened": False, "map_id": mid}

    ddef = None
    if dungeon_def is not None:
        try:
            ddef = _norm_dungeon_def(dungeon_def)
        except TypeError:
            ddef = None
    if ddef is None and isinstance(player_ctx, Mapping):
        ddef = _resolve_dungeon_def(player_ctx, None)
    if ddef is None:
        return {"ok": False, "reason": "虚弱中：无法判定安全区（缺少 dungeon_def，fail-safe 拦截）",
                "weakened": True, "map_id": mid}
    safe = _safe_zone(ddef)
    if mid and safe is not None and mid == safe:
        return {"ok": True, "weakened": True, "map_id": mid, "safe_zone": safe}
    return {"ok": False, "reason": "虚弱中不可进入非安全区（含 BOSS 房）",
            "weakened": True, "map_id": mid, "safe_zone": safe}
