"""内容包领域模型 —— M3 地图层（M01 maps 装载 + M07 刷怪配置）：MapDef / SpawnDef / ExitDef + validate_maps 专项校验。

依据：
  - 细化_2a1a_地图schema字段.md（节点级 8 字段：id/name/desc/spawn/exits/mechanics/gate_guard/
    dungeon_entrances；exits 4 方向；spawn 引用 enemies.json）
  - 细化_2a1b_通道规则与刷怪.md（通道 R1-R13 双向/单向/隐藏/捷径 + 刷怪 R14-R26 字段/出没/校验器）
  - 细化_2a1c_地图副本衔接.md（dungeon_entrances 8 号字段：{dungeon, name?}，非方向性挂接）
  - m3_shared_contract §2（地图层权威字段表 §2.1 / exits §2.2 / spawn 行 §2.3 / 校验器 ①-④）

本文件为批次 0 · 路 A 的**独立模块**（主 agent 收口时并入 content/models.py + validator.py 的 check_pack）：
  - 零冲突：不修改 models.py / field_meta.py / validator.py 既有内容；
    loader 侧 DEF_CLASSES["map"] 目前仍指向 models.MapDef（空壳），收口时替换为本模块 MapDef 即可。
  - validate_maps(modules, report) 为纯函数（无副作用），report 鸭子类型（见 _emit 说明），
    主 agent 收口时直接接入 check_pack 的 _Checker 实例或自建收集器。

铁律：零 NoneBot import；frozen dataclass；完整类型标注（typing 3.9 兼容）；
仅依赖 qbot_rpg.content.models 的 BaseDef。概率/倍率一律小数（weather_weights 0.5 等）。
工程补白显式标注：【工程补白】处见正文——不冒充定稿。

【工程补白】收口边界（本模块不做、待后续批次）：
  1. spawn.weather_weights 的 **key ∈ 注册天气集** 校验依赖天气引擎（M38/M41，契约 §6.2 V5/V6），
     本模块只校验值为非负小数（2a1b R26）；key 空间校验归 M41。
  2. dungeon_entrances[].dungeon 引用存在（红拦）依赖 dungeon.json（M16，契约 §4.1），此处不校验。
  3. 地图级 max_alive 聚合上限（2a1b R21）与 spawn_weight（R22）为工程补白可配项，本模块不校验。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple, cast

from qbot_rpg.content.models import BaseDef

# -------------------------------------------------------------------------------------
# 权威枚举（契约 §2.2 / §2.3 + 2a1b R25；天气 key 空间留 M41）
# -------------------------------------------------------------------------------------
EXIT_DIRECTIONS: Tuple[str, ...] = ("up", "down", "left", "right")  # 4 方向键（2a1b R2）
EXIT_MODES: Tuple[str, ...] = ("bidirectional", "one_way", "hidden")  # 双向/单向/隐藏（契约 §2.2）
SEASONS_ENUM: Tuple[str, ...] = ("spring", "summer", "autumn", "winter")  # 四季（2a1b R25）
PERIODS_ENUM: Tuple[str, ...] = ("dawn", "noon", "dusk", "night", "midnight")  # 五时段（2a1b R25）
SPAWN_COUNT_DEFAULT: int = 1  # 【工程补白】contract §2.3：spawn count 缺省 1
SPAWN_RESPAWN_MIN: int = 1  # contract §2.3：respawn_minutes 必填 ≥1
SPAWN_WEATHER_MIN: float = 0.0  # weather_weights 值非负（2a1b R26；0 = 该天气不刷）


# =====================================================================================
# Def 类型（风格对齐 EnemyDef：BaseDef + 字段访问器；spawn/exits 派生 SpawnDef/ExitDef）
# =====================================================================================


@dataclass(frozen=True)
class ExitDef:
    """exits.<方向> 通道条目（契约 §2.2：{to, mode, condition?}；4 方向键 up/down/left/right）。

    依据：契约 §2.2 + 2a1b §1.4（字段表：to 必填 / mode 必填三枚举 / condition 仅 hidden 必填）。
    """

    direction: str  # up/down/left/right（该通道在本图的方向）
    to: Optional[str]  # 目标地图 ID（须存在，硬拦）
    mode: Optional[str]  # bidirectional / one_way / hidden
    condition: object  # 条件引擎表达式 {var, op, param}（hidden 必带；双向/单向不可配）

    @classmethod
    def from_entry(cls, entry: Mapping[str, object], direction: str) -> "ExitDef":
        to = entry.get("to")
        mode = entry.get("mode")
        return cls(
            direction=direction,
            to=to if isinstance(to, str) else None,
            mode=mode if isinstance(mode, str) else None,
            condition=entry.get("condition"),
        )


@dataclass(frozen=True)
class SpawnDef:
    """maps.json spawn 行（契约 §2.3 七字段：enemy/count/respawn_minutes/active_time/seasons/periods/weather_weights）。

    依据：契约 §2.3 + 2a1b §2.1（字段表逐行追溯）+ §2.2 出没语义（R16-R22 全 AND 叠加）。
    """

    enemy: Optional[str]  # enemies.json 引用（id/name 均可）
    count: Optional[int]  # 同时在场数量上限（缺省 1【工程补白】，contract §2.3）
    respawn_minutes: Optional[int]  # 刷新间隔（分钟），必填 ≥1（contract §2.3）
    active_time: Mapping[str, object]  # {from, to} 现实钟点窗口（空=全天；"20:00"-"06:00" 跨夜）
    seasons: Tuple[str, ...]  # 季节限定（空=全年）
    periods: Tuple[str, ...]  # 时段限定（空=全天）
    weather_weights: Mapping[str, object]  # {天气: 倍率}（默认 1；0=该天气不刷；只影响刷新不驱逐）
    index: int = field(default=0)  # 【工程补白】spawn 行序号（非 schema 字段，仅诊断定位用）

    @classmethod
    def from_entry(cls, entry: Mapping[str, object], index: int = 0) -> "SpawnDef":
        count = entry.get("count")
        respawn = entry.get("respawn_minutes")
        at = entry.get("active_time")
        ww = entry.get("weather_weights")
        seasons = entry.get("seasons")
        periods = entry.get("periods")
        enemy = entry.get("enemy")
        return cls(
            enemy=enemy if isinstance(enemy, str) else None,
            count=count if isinstance(count, int) and not isinstance(count, bool) else None,
            respawn_minutes=respawn if isinstance(respawn, int) and not isinstance(respawn, bool) else None,
            active_time=at if isinstance(at, Mapping) else {},
            seasons=tuple(s for s in seasons if isinstance(s, str)) if isinstance(seasons, list) else (),
            periods=tuple(p for p in periods if isinstance(p, str)) if isinstance(periods, list) else (),
            weather_weights=ww if isinstance(ww, Mapping) else {},
            index=index,
        )

    @property
    def active_from(self) -> Optional[str]:
        """出没窗口起始（现实钟点，如 "20:00"；缺省 None=全天）。"""
        v = self.active_time.get("from")
        return v if isinstance(v, str) else None

    @property
    def active_to(self) -> Optional[str]:
        """出没窗口结束（现实钟点，如 "06:00"；跨夜写法沿用 2a1b §2.1）。"""
        v = self.active_time.get("to")
        return v if isinstance(v, str) else None


@dataclass(frozen=True)
class MapDef(BaseDef):
    """maps.json 条目（契约 §2.1 节点级 8 字段访问器，风格对齐 EnemyDef）。

    依据：契约 §2.1（id/name/desc/spawn/exits/mechanics/gate_guard/dungeon_entrances）
    + 2a1a §1（字段级 schema）+ 2a1c（8 号字段 dungeon_entrances）。
    注：id/name 由 BaseDef 承载（from_entry 冗余镜像 raw），其余 6 字段访问器见下。
    """

    # ---- 数值/字符串/映射/列表辅助（与 EnemyDef._num/_str/_mapping/_entries 同风格）----
    def _str(self, key: str) -> Optional[str]:
        v = self.raw.get(key)
        return v if isinstance(v, str) else None

    def _mapping(self, key: str) -> Mapping[str, object]:
        v = self.raw.get(key)
        return v if isinstance(v, Mapping) else {}

    def _entries(self, key: str) -> Tuple[Mapping[str, object], ...]:
        v = self.raw.get(key)
        return tuple(e for e in v if isinstance(e, Mapping)) if isinstance(v, list) else ()

    # ---- 8 字段访问器 ----
    @property
    def desc(self) -> Optional[str]:
        """地形/通道/机制/宝箱预告文本（2a1a §1.3；探索/BOSS 两版共用）。"""
        return self._str("desc")

    @property
    def spawn(self) -> Tuple[Mapping[str, object], ...]:
        """怪物分布原始行（引用 enemies.json；BOSS 房可空，contract §2.1）。"""
        return self._entries("monsters")

    def spawn_defs(self) -> Tuple[SpawnDef, ...]:
        """spawn 行 → SpawnDef 元组（带行序号 index）。"""
        return tuple(SpawnDef.from_entry(e, i) for i, e in enumerate(self.spawn))

    @property
    def exits(self) -> Mapping[str, ExitDef]:
        """4 方向通道表：direction → ExitDef（缺省方向=死路，contract §2.2；非法行跳过）。"""
        raw = self._mapping("exits")
        return {str(k): ExitDef.from_entry(v, direction=str(k))
                for k, v in raw.items() if isinstance(v, Mapping)}

    def exit(self, direction: str) -> Optional[ExitDef]:
        """按方向取通道；未配置/非法行 → None（死路）。"""
        return self.exits.get(direction)

    @property
    def exit_dirs(self) -> Tuple[str, ...]:
        """已配置方向键（subset of up/down/left/right）。"""
        return tuple(self.exits.keys())

    @property
    def mechanics(self) -> Tuple[Mapping[str, object], ...]:
        """场地效果（落石/陷阱/机关；探索/BOSS 共用，2a1a §1.6）。"""
        return self._entries("mechanics")

    @property
    def gate_guard(self) -> Optional[str]:
        """守门怪（enemies.json 怪物 ID；BOSS 房前配置，contract §2.1 / 2a1a §1.7）。"""
        return self._str("gate_guard")

    @property
    def dungeon_entrances(self) -> Tuple[Mapping[str, object], ...]:
        """副本入口挂载（2a1c：{dungeon, name?}；非方向性，与 exits 并列，contract §2.1）。"""
        return self._entries("dungeon_entrances")


def parse_maps(modules: Mapping[str, object]) -> Tuple[MapDef, ...]:
    """从 modules 提取 maps 模块 → MapDef 元组（非 list / 非对象条目跳过；供运行期与测试复用）。"""
    maps = modules.get("maps") if isinstance(modules, Mapping) else None
    if not isinstance(maps, list):
        return ()
    return tuple(cast(MapDef, MapDef.from_entry(e)) for e in maps if isinstance(e, Mapping))


# =====================================================================================
# validate_maps：maps 模块专项校验（契约 §2.2 ①-④ + 2a1b R24-R26；供主 agent 收口接 check_pack）
# =====================================================================================
# 规则清单（红拦=errors / 黄提示=warnings）：
#   硬拦 R-4：exits.<方向>.to 目标地图 ID 存在（契约 §2.2 ①）；spawn[].enemy 引用存在（2a1b R24）
#   硬拦 R-1：mode ∈ 三枚举（契约 §2.2 ②）；spawn 结构/枚举（seasons/periods R25）
#   硬拦 R-5：hidden 必带 condition（契约 §2.2 ③）；节点/出口/行结构缺失
#   硬拦 R-2：count ≥ 0 整数、respawn_minutes ≥ 1 整数（2a1b R26）；weather_weights 值 ≥ 0
#   黄提示 Y-8：双向不对称（A→B 双向而 B→A 非双向，契约 §2.2 ④ / 2a1b §1.4 ④）；
#               condition 配在非 hidden 通道（2a1b §1.4：双向/单向不可配置）
#   【工程补白】天气 key 空间（M41）、dungeon_entrances 引用（M16）不在此校验


def _emit(report: object, method: str, *args: object, **kwargs: object) -> None:
    """收集器鸭子类型适配：优先 report.<method>，其次 validator._Checker 的 _<method>。

    M3 审查 P0-1 修复（2026-08-26）：_Checker 方法名是 _err/_warn/_note（非 _error/_warning），
    加显式映射避免生产路径静默丢弃（此前 `_emit(report, "error", ...)` 找不到 callable 全丢弃，
    maps 深校验在生产 check_pack 空转）。零依赖，不 import validator。
    """
    _MAP = {"error": "_err", "warning": "_warn", "note": "_note"}
    fn = getattr(report, method, None)
    if not callable(fn):
        fn = getattr(report, _MAP.get(method, "_" + method), None)
    if callable(fn):
        fn(*args, **kwargs)


def _enemy_refs(enemies: object) -> Optional[set]:
    """enemies 模块 → 可引用集合（id ∪ name，契约 §2.3「id/name 均可」）。

    返回 None = enemies 模块未声明/形态异常 → 调用方跳过引用检查（细化_3e §2.3 默认放行）。
    """
    if not isinstance(enemies, list):
        return None
    refs: set = set()
    for e in enemies:
        if not isinstance(e, Mapping):
            continue
        eid = e.get("id")
        if isinstance(eid, str) and eid:
            refs.add(eid)
        ename = e.get("name")
        if isinstance(ename, str) and ename:
            refs.add(ename)
    return refs


def _check_exits(
    report: object,
    entry: Mapping[str, object],
    idx: int,
    node_id: object,
    map_ids: set,
) -> None:
    """exits 校验（契约 §2.2 ①-③ + 方向键约束 + condition 归属黄提示）。"""
    exits = entry.get("exits")
    if exits is None:
        return  # 缺省=死路
    if not isinstance(exits, Mapping):
        _emit(report, "error", "maps", f"maps.{idx}.exits", "R-5",
              rule="map_exits_not_object", node_id=node_id)
        return
    base = f"maps.{idx}.exits"
    for direction, ex in exits.items():
        if direction not in EXIT_DIRECTIONS:
            _emit(report, "error", "maps", f"{base}.{direction}", "R-5",
                  rule="map_exit_direction_invalid", node_id=node_id,
                  direction=direction, allowed=list(EXIT_DIRECTIONS))
            continue
        if not isinstance(ex, Mapping):
            _emit(report, "error", "maps", f"{base}.{direction}", "R-1",
                  rule="map_exit_not_object", node_id=node_id, direction=direction)
            continue
        to = ex.get("to")
        if to is None:
            _emit(report, "error", "maps", f"{base}.{direction}.to", "R-5",
                  rule="map_exit_to_required", node_id=node_id, direction=direction)
        elif not isinstance(to, str) or not to:
            _emit(report, "error", "maps", f"{base}.{direction}.to", "R-1",
                  rule="map_exit_to_invalid", node_id=node_id, direction=direction, to=to)
        elif to not in map_ids:
            _emit(report, "error", "maps", f"{base}.{direction}.to", "R-4",
                  rule="map_exit_target_missing", node_id=node_id, direction=direction, ref=to)
        mode = ex.get("mode")
        if mode is None:
            _emit(report, "error", "maps", f"{base}.{direction}.mode", "R-1",
                  rule="map_exit_mode_required", node_id=node_id, direction=direction)
        elif mode not in EXIT_MODES:
            _emit(report, "error", "maps", f"{base}.{direction}.mode", "R-1",
                  rule="map_exit_mode_invalid", node_id=node_id, direction=direction,
                  mode=mode, allowed=list(EXIT_MODES))
        condition = ex.get("condition")
        if mode == "hidden":
            if condition is None:
                _emit(report, "error", "maps", f"{base}.{direction}.condition", "R-5",
                      rule="map_exit_hidden_condition_required", node_id=node_id, direction=direction)
            elif not isinstance(condition, Mapping):
                _emit(report, "error", "maps", f"{base}.{direction}.condition", "R-5",
                      rule="map_exit_condition_invalid", node_id=node_id, direction=direction)
        elif mode in ("bidirectional", "one_way") and condition is not None:
            # 2a1b §1.4：condition 仅 hidden 可配（双向/单向不可配置）→ 黄提示不拦截
            _emit(report, "warning", "maps", f"{base}.{direction}.condition", "Y-8",
                  rule="map_exit_condition_not_hidden", node_id=node_id,
                  direction=direction, mode=mode)


def _check_spawn_int(
    report: object,
    row: Mapping[str, object],
    base: str,
    key: str,
    node_id: object,
    minimum: int,
    value_rule: str,
    required_rule: Optional[str] = None,
) -> None:
    """spawn 数值字段校验（2a1b R26）：必填（可选）且为整数 ≥ minimum（非负整数口径）。"""
    v = row.get(key)
    if v is None:
        if required_rule is not None:
            _emit(report, "error", "maps", f"{base}.{key}", "R-5",
                  rule=required_rule, node_id=node_id, key=key)
        return
    if not isinstance(v, int) or isinstance(v, bool) or v < minimum:
        _emit(report, "error", "maps", f"{base}.{key}", "R-2",
              rule=value_rule, node_id=node_id, key=key, value=v, minimum=minimum)


def _check_spawn(
    report: object,
    entry: Mapping[str, object],
    idx: int,
    node_id: object,
    enemy_refs: Optional[set],
) -> None:
    """spawn 校验（契约 §2.3 + 2a1b R24-R26）。"""
    spawn = entry.get("monsters")
    if spawn is None:
        return  # 可有（BOSS 房/纯机关区可空，contract §2.1）
    if not isinstance(spawn, list):
        _emit(report, "error", "maps", f"maps.{idx}.spawn", "R-1",
              rule="map_spawn_not_list", node_id=node_id)
        return
    for si, row in enumerate(spawn):
        base = f"maps.{idx}.spawn.{si}"
        if not isinstance(row, Mapping):
            _emit(report, "error", "maps", base, "R-1",
                  rule="map_spawn_row_not_object", node_id=node_id)
            continue
        enemy = row.get("enemy")
        if enemy is None:
            _emit(report, "error", "maps", f"{base}.enemy", "R-5",
                  rule="map_spawn_enemy_required", node_id=node_id)
        elif not isinstance(enemy, str) or not enemy:
            _emit(report, "error", "maps", f"{base}.enemy", "R-1",
                  rule="map_spawn_enemy_invalid", node_id=node_id, enemy=enemy)
        elif enemy_refs is not None and enemy not in enemy_refs:
            _emit(report, "error", "maps", f"{base}.enemy", "R-4",
                  rule="map_spawn_enemy_missing", node_id=node_id, ref=enemy)
        # 数值（2a1b R26）：count 非负整数（缺省 1 不拦）；respawn_minutes 必填且 ≥1
        _check_spawn_int(report, row, base, "count", node_id,
                         minimum=0, value_rule="map_spawn_count_invalid")
        _check_spawn_int(report, row, base, "respawn_minutes", node_id,
                         minimum=SPAWN_RESPAWN_MIN, value_rule="map_spawn_respawn_invalid",
                         required_rule="map_spawn_respawn_required")
        # 出没条件结构（2a1b §2.1 / R25 / R26）
        at = row.get("active_time")
        if at is not None:
            if not isinstance(at, Mapping):
                _emit(report, "error", "maps", f"{base}.active_time", "R-1",
                      rule="map_spawn_active_time_not_object", node_id=node_id)
            else:
                for atk in ("from", "to"):
                    v = at.get(atk)
                    if not isinstance(v, str) or not v:
                        _emit(report, "error", "maps", f"{base}.active_time.{atk}", "R-1",
                              rule="map_spawn_active_time_invalid", node_id=node_id, key=atk, value=v)
        seasons = row.get("seasons")
        if seasons is not None:
            if (not isinstance(seasons, list)
                    or any(not isinstance(s, str) or s not in SEASONS_ENUM for s in seasons)):
                _emit(report, "error", "maps", f"{base}.seasons", "R-1",
                      rule="map_spawn_seasons_invalid", node_id=node_id,
                      value=seasons, allowed=list(SEASONS_ENUM))
        periods = row.get("periods")
        if periods is not None:
            if (not isinstance(periods, list)
                    or any(not isinstance(p, str) or p not in PERIODS_ENUM for p in periods)):
                _emit(report, "error", "maps", f"{base}.periods", "R-1",
                      rule="map_spawn_periods_invalid", node_id=node_id,
                      value=periods, allowed=list(PERIODS_ENUM))
        ww = row.get("weather_weights")
        if ww is not None:
            if not isinstance(ww, Mapping):
                _emit(report, "error", "maps", f"{base}.weather_weights", "R-1",
                      rule="map_spawn_weather_weights_not_object", node_id=node_id)
            else:
                # 值非负（R26）；key ∈ 注册天气集归 M41（契约 §6.2 V5/V6）【工程补白】
                for wk, wv in ww.items():
                    if not isinstance(wv, (int, float)) or isinstance(wv, bool) or wv < SPAWN_WEATHER_MIN:
                        _emit(report, "error", "maps", f"{base}.weather_weights.{wk}", "R-2",
                              rule="map_spawn_weather_weight_invalid", node_id=node_id, key=wk, value=wv)


def _check_bidirectional_symmetry(
    report: object,
    maps: list,
    map_ids: set,
) -> None:
    """双向一致性黄提示（契约 §2.2 ④：A→B 双向而 B→A 非双向 → 黄提示"双向不对称"）。

    只对「声明为 bidirectional 的边」检查对侧；对侧缺失或非双向 → 黄提示（允许作者刻意不对称）。
    to 悬空（已红拦）的对侧跳过，避免重复噪音。
    """
    by_id: Dict[str, Tuple[int, Dict[str, Mapping[str, object]]]] = {}
    for idx, entry in enumerate(maps):
        if not isinstance(entry, Mapping):
            continue
        node_id = entry.get("id")
        if not isinstance(node_id, str) or not node_id:
            continue
        exits = entry.get("exits")
        if not isinstance(exits, Mapping):
            continue
        dirs: Dict[str, Mapping[str, object]] = {}
        for direction, ex in exits.items():
            if direction in EXIT_DIRECTIONS and isinstance(ex, Mapping):
                dirs[direction] = ex
        by_id[node_id] = (idx, dirs)
    for node_id, (idx, dirs) in by_id.items():
        for direction, ex in dirs.items():
            if ex.get("mode") != "bidirectional":
                continue
            to = ex.get("to")
            if not isinstance(to, str) or to not in map_ids or to not in by_id:
                continue  # 目标悬空已红拦；避免重复噪音
            back: Optional[Mapping[str, object]] = None
            back_dir: Optional[str] = None
            for d2, e2 in by_id[to][1].items():
                if e2.get("to") == node_id:
                    back, back_dir = e2, d2
                    break
            if back is None:
                _emit(report, "warning", "maps", f"maps.{idx}.exits.{direction}", "Y-8",
                      rule="map_exit_bidirectional_asymmetry", node_id=node_id,
                      direction=direction, to=to, back_missing=True)
            elif back.get("mode") != "bidirectional":
                _emit(report, "warning", "maps", f"maps.{idx}.exits.{direction}", "Y-8",
                      rule="map_exit_bidirectional_asymmetry", node_id=node_id,
                      direction=direction, to=to, back_missing=False,
                      back_direction=back_dir, back_mode=back.get("mode"))


def validate_maps(modules: Mapping[str, object], report: object) -> None:
    """maps 模块专项校验（M01 装载 + M07 刷怪；契约 §2.2 ①-④ + 2a1b R24-R26）。纯函数，无副作用。

    入口：主 agent 收口时在 check_pack 的 _Checker.run() 尾部调用
        validate_maps(modules, checker)  （checker._err/_warn 签名与 _emit 一致）
    或自建收集器（暴露 error(module, field, kind, **detail) / warning(...)）。
    返回 None；红拦/黄提示全部经 report 追加（D-01 一次给全量）。

    modules: 模块名（无 .json 后缀）→ parsed JSON（含 "maps" 与 "enemies"）；
             maps 未声明 → 默认放行（细化_3e §2.3）；enemies 未声明 → 跳过 enemy 引用检查。
    """
    if not isinstance(modules, Mapping):
        return
    maps = modules.get("maps")
    if maps is None:
        return  # 未声明 maps 模块：默认放行
    if not isinstance(maps, list):
        _emit(report, "error", "maps", "maps", "R-5",
              rule="module_structure", expect="list")
        return
    map_ids: set = set()
    for e in maps:
        if isinstance(e, Mapping):
            eid = e.get("id")
            if isinstance(eid, str) and eid:
                map_ids.add(eid)
    enemy_refs = _enemy_refs(modules.get("enemies"))
    for idx, entry in enumerate(maps):
        if not isinstance(entry, Mapping):
            _emit(report, "error", "maps", f"maps.{idx}", "R-5",
                  rule="entry_not_object", got=type(entry).__name__)
            continue
        node_id = entry.get("id")
        if not isinstance(node_id, str) or not node_id:
            _emit(report, "error", "maps", f"maps.{idx}", "R-5",
                  rule="map_id_required", idx=idx)
            node_id = f"<maps.{idx}>"
        # gate_guard 引用存在（契约 §2.1：守门怪 = enemies.json 怪物 ID；同 2a1b R24 精神）
        gate = entry.get("gate_guard")
        if gate is not None:
            if not isinstance(gate, str) or not gate:
                _emit(report, "error", "maps", f"maps.{idx}.gate_guard", "R-1",
                      rule="map_gate_guard_invalid", node_id=node_id, gate_guard=gate)
            elif enemy_refs is not None and gate not in enemy_refs:
                _emit(report, "error", "maps", f"maps.{idx}.gate_guard", "R-4",
                      rule="map_gate_guard_missing", node_id=node_id, ref=gate)
        # dungeon_entrances 引用（dungeon.json）依赖 M16【工程补白】：此处仅结构提示，不校验存在
        de = entry.get("dungeon_entrances")
        if de is not None and not isinstance(de, list):
            _emit(report, "error", "maps", f"maps.{idx}.dungeon_entrances", "R-1",
                  rule="map_dungeon_entrances_not_list", node_id=node_id)
        _check_exits(report, entry, idx, node_id, map_ids)
        _check_spawn(report, entry, idx, node_id, enemy_refs)
    _check_bidirectional_symmetry(report, maps, map_ids)


__all__ = [
    "MapDef",
    "SpawnDef",
    "ExitDef",
    "parse_maps",
    "validate_maps",
    "EXIT_DIRECTIONS",
    "EXIT_MODES",
    "SEASONS_ENUM",
    "PERIODS_ENUM",
    "SPAWN_COUNT_DEFAULT",
]
