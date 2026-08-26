"""内容包领域模型：dungeon.json 副本两型（explore/boss）Def 类型 + 校验函数（M3 批次0·路B / M16+M11）。

依据：
  - m3_shared_contract §4（dungeon.json 11 字段表 / 副本内状态集 S0-S7）+ §3（enemies zone_change 换区配置 4 字段）
  - 细化_2a3_副本两型流程（两型定义 R1-R12：explore 探索版=练习赛无 BOSS / boss 讨伐版=正式赛；地图共用 R4-R7；
    探索版 entry_item:null 不扣 / BOSS 版入场限制可配 R11；safe_zone 缺省=入口区 R15）
  - 细化_2a2_换区追击流程（zone_change 触发/候选区/timing 语义；§7.1 配置落点）
  - 细化_2a1d_地图字段扩展 §2.4（dungeon.json drops.first_clear 子段结构 = {items[], title, codex}，
    与宝箱级 first_clear 同构；drops 亦含 normal/boss 普通掉落数组）
  - 细化_2a1c_地图副本衔接（dungeon_entrances 挂接：maps.json 节点级入口，dungeon.maps 引用 maps.json 地图 id）

工程补白（定稿/契约未明示处，显式标注，不冒充定稿）：
  - zone_change.timing 枚举：契约仅给中文语义「行动后/阶段后」，本实现取 `after_action` / `phase_changed`
    两个枚举键（对齐细化_2a2 R5「怪物回合行动结算后」与 AI 状态机 TRIGGER_TYPES 既有命名）。
  - zone_change 缺失子字段默认放行（细化_3e §2.3「缺失字段默认放行」口径），只校验已写字段的类型/范围。
  - hp_threshold 数值大小不限制（只建议不限制原则）：仅硬拦类型 + 区间 (0,1) 越界；区间内任意值放行，不设伪精确建议阈值。
  - maps 模块未装载时（批次0·路A 后由 maps.json 提供）：地图引用检查宽松跳过并登记 N1 提示，不红拦。

铁律：零 NoneBot import；frozen dataclass；完整类型标注（typing 3.9 兼容）；仅依赖 qbot_rpg.content.models /
qbot_rpg.data.types（与 models.py 同依赖方向，零新增内容层依赖）。
registry 挂载（DEF_CLASSES）与 check_pack 接线由主 agent 收口（本模块零冲突，不改 models.py / field_meta.py / validator.py）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Set, Tuple

from qbot_rpg.content.models import BaseDef, PackError, PackNote, ValidationReport
from qbot_rpg.data.types import MapID

# -------------------------------------------------------------------------------------
# dungeon.json 权威枚举（依据：m3_shared_contract §4.1 type / §3.1 timing）
# -------------------------------------------------------------------------------------
DUNGEON_TYPES: Tuple[str, ...] = ("explore", "boss")
"""副本型别枚举：explore（探索版/练习赛，无 BOSS）/ boss（讨伐版/正式赛）【工程补白：契约 type 两值】。"""

ZONE_CHANGE_TIMINGS: Tuple[str, ...] = ("after_action", "phase_changed")
"""zone_change.timing 枚举（【工程补白】见模块 docstring：契约中文语义「行动后/阶段后」→ 上述两键）。"""


# -------------------------------------------------------------------------------------
# dungeon.json 条目 Def（m3_shared_contract §4.1 11 字段访问器，风格对齐 EnemyDef）
# -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DungeonDef(BaseDef):
    """dungeon.json 条目（副本两型：explore 探索版 / boss 讨伐版，m3_shared_contract §4.1 11 字段）。

    依据：细化_2a3 §1（两型定义 R1-R12）+ m3_shared_contract §4.1（11 字段表）+ 细化_2a1d §2.4
    （drops.first_clear 结构）。id/name 继承 BaseDef（名称冗余供旧局快照）。
    """

    # ---- 数值/字符串/映射/列表辅助（与 EnemyDef 同风格）----
    def _num(self, key: str) -> Optional[float]:
        v = self.raw.get(key)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def _str(self, key: str) -> Optional[str]:
        v = self.raw.get(key)
        return v if isinstance(v, str) else None

    def _str_list(self, key: str) -> Tuple[str, ...]:
        v = self.raw.get(key)
        return tuple(x for x in v if isinstance(x, str)) if isinstance(v, list) else ()

    def _mapping(self, key: str) -> Mapping[str, object]:
        v = self.raw.get(key)
        return v if isinstance(v, Mapping) else {}

    # ---- 11 字段访问器 ----
    @property
    def type(self) -> Optional[str]:
        """副本型别：explore（探索版）/ boss（BOSS 版）（m3 §4.1 type）。"""
        return self._str("type")

    @property
    def entry_item(self) -> Optional[str]:
        """BOSS 版入场道具 ID（m3 §4.1；explore 版 null 不扣）。"""
        return self._str("entry_item")

    @property
    def entry_limit(self) -> Optional[float]:
        """入场次数限制（m3 §4.1；0=不限；≥0 整数，校验见 R2_entry_limit_negative）。"""
        return self._num("entry_limit")

    @property
    def maps(self) -> Tuple[MapID, ...]:
        """引用 maps.json 地图 ID（m3 §4.1；两型共用同一组地图，2a3 R4-R7）。"""
        return tuple(MapID(x) for x in self._str_list("maps"))

    @property
    def boss_room(self) -> Optional[str]:
        """BOSS 房地图 ID（m3 §4.1 boss 版；∈ dungeon.maps 或 maps 模块存在）。"""
        return self._str("boss_room")

    @property
    def boss(self) -> Optional[str]:
        """BOSS 怪物 ID（m3 §4.1；引用 enemies.json）。"""
        return self._str("boss")

    @property
    def subquests(self) -> Tuple[str, ...]:
        """副本子任务（m3 §4.1；引用 quest.json，本路不校验引用）。"""
        return self._str_list("subquests")

    @property
    def safe_zone(self) -> Optional[str]:
        """安全区地图（m3 §4.1；缺省=入口区；须 ∈ dungeon.maps）。"""
        return self._str("safe_zone")

    @property
    def drops(self) -> Mapping[str, object]:
        """通关掉落容器（m3 §4.1；含 normal/boss 普通掉落 + first_clear 首通奖励，2a1d §2.4）。"""
        return self._mapping("drops")


# -------------------------------------------------------------------------------------
# 校验辅助：maps / enemies 模块引用空间收集
# -------------------------------------------------------------------------------------


def _collect_map_ids(modules: Mapping[str, object]) -> Optional[Set[str]]:
    """收集 maps 模块可用地图 id 集合；缺失/无可用 id → None（宽松跳过 + 登记，见 validate_dungeons）。

    maps.json 由批次0·路A 子代理提供；本路按「模块内 maps 键存在时检查」原则：
      - 模块缺失 / 非 list 且非 map 形态 / 收集不到任何 id → 返回 None（引用检查宽松跳过）
      - list 形态：取各条目 `id`；map 形态（键=id）：取键
    """
    maps_data = modules.get("maps")
    if isinstance(maps_data, list):
        ids = {
            str(e.get("id")) for e in maps_data if isinstance(e, Mapping) and e.get("id")
        }
        return ids if ids else None
    if isinstance(maps_data, Mapping):
        return set(maps_data.keys()) if maps_data else None
    return None


def _collect_enemy_ids(modules: Mapping[str, object]) -> Optional[Set[str]]:
    """收集 enemies 模块可用怪物 id 集合；缺失/无可用 id → None（宽松跳过 + 登记）。"""
    enemies_data = modules.get("enemies")
    if isinstance(enemies_data, list):
        ids = {
            str(e.get("id")) for e in enemies_data if isinstance(e, Mapping) and e.get("id")
        }
        return ids if ids else None
    return None


def _maps_with_entrances(modules: Mapping[str, object]) -> Set[str]:
    """maps 模块中挂副本入口（dungeon_entrances 非空）的地图 id 集。

    反向 R2 校验靶（审查_M3_批次1 P1-1）：副本内部地图（∈ dungeon.maps）不得再挂副本入口。
    maps 模块缺失 / 非 list / 无挂载 → 空集（不误拦）。
    """
    maps_data = modules.get("maps")
    if not isinstance(maps_data, list):
        return set()
    out: Set[str] = set()
    for e in maps_data:
        if not isinstance(e, Mapping):
            continue
        eid = e.get("id")
        de = e.get("dungeon_entrances")
        if isinstance(eid, str) and eid and isinstance(de, list) and de:
            out.add(eid)
    return out


# -------------------------------------------------------------------------------------
# zone_change 子段校验（enemies.json 怪物级，m3_shared_contract §3.1 4 字段）
# -------------------------------------------------------------------------------------


def _check_zone_change(
    modules: Mapping[str, object],
    errors: list,
    notes: list,
) -> None:
    """enemies.json 每只怪的 zone_change 子段校验（硬拦类型/范围；数值大小只建议不限制）。

    字段（m3 §3.1）：enabled bool / hp_threshold float ∈ (0,1) / targets 非空 string[] /
    timing ∈ ZONE_CHANGE_TIMINGS。缺失子字段默认放行（细化_3e §2.3）；区间内数值不限制。
    """
    enemies_data = modules.get("enemies")
    if not isinstance(enemies_data, list):
        return  # 模块缺失/形态错误由 enemies 泛型校验负责，本处不重复
    for idx, entry in enumerate(enemies_data):
        if not isinstance(entry, Mapping) or "zone_change" not in entry:
            continue
        base = f"enemies.{idx}"
        zc = entry["zone_change"]
        if not isinstance(zc, Mapping):
            errors.append(PackError(
                module="enemies", field=f"{base}.zone_change", kind="R-1",
                detail={"rule": "zc_type", "expect": "object", "got": type(zc).__name__},
            ))
            continue
        # enabled：bool
        if "enabled" in zc and not isinstance(zc["enabled"], bool):
            errors.append(PackError(
                module="enemies", field=f"{base}.zone_change.enabled", kind="R-1",
                detail={"rule": "zc_enabled_type", "expect": "bool", "got": type(zc["enabled"]).__name__},
            ))
        # hp_threshold：数值 ∈ (0,1)；数值大小只建议不限制
        if "hp_threshold" in zc:
            v = zc["hp_threshold"]
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                errors.append(PackError(
                    module="enemies", field=f"{base}.zone_change.hp_threshold", kind="R-1",
                    detail={"rule": "zc_hp_threshold_type", "expect": "number(0,1)", "got": type(v).__name__},
                ))
            elif v <= 0 or v >= 1:
                errors.append(PackError(
                    module="enemies", field=f"{base}.zone_change.hp_threshold", kind="R-2",
                    detail={"rule": "zc_hp_threshold_range", "value": v, "expect": "(0,1)"},
                ))
        # targets：非空 string[]
        if "targets" in zc:
            tg = zc["targets"]
            if not isinstance(tg, list):
                errors.append(PackError(
                    module="enemies", field=f"{base}.zone_change.targets", kind="R-1",
                    detail={"rule": "zc_targets_type", "expect": "string[]", "got": type(tg).__name__},
                ))
            elif not tg:
                errors.append(PackError(
                    module="enemies", field=f"{base}.zone_change.targets", kind="R-5",
                    detail={"rule": "zc_targets_empty", "note": "候选逃往地图非空（2a2 R4：空=永不换区）"},
                ))
            else:
                for i, t in enumerate(tg):
                    if not isinstance(t, str) or not t:
                        errors.append(PackError(
                            module="enemies", field=f"{base}.zone_change.targets.{i}", kind="R-1",
                            detail={"rule": "zc_targets_element", "expect": "string", "got": type(t).__name__},
                        ))
        # timing：枚举
        if "timing" in zc:
            tm = zc["timing"]
            if not isinstance(tm, str):
                errors.append(PackError(
                    module="enemies", field=f"{base}.zone_change.timing", kind="R-1",
                    detail={"rule": "zc_timing_type", "expect": "string", "got": type(tm).__name__},
                ))
            elif tm not in ZONE_CHANGE_TIMINGS:
                errors.append(PackError(
                    module="enemies", field=f"{base}.zone_change.timing", kind="R-1",
                    detail={"rule": "zc_timing_enum", "value": tm, "expect": list(ZONE_CHANGE_TIMINGS)},
                ))


# -------------------------------------------------------------------------------------
# dungeon.json 校验（M16；供主 agent 收口接 check_pack）
# -------------------------------------------------------------------------------------


def _check_dungeon_entry(
    module_name: str,
    idx: int,
    entry: object,
    map_ids: Optional[Set[str]],
    enemy_ids: Optional[Set[str]],
    errors: list,
    notes: list,
) -> None:
    """单条副本条目 11 字段校验（R-1 类型 / R-2 数值 / R-4 引用 / R-5 结构，硬拦）。"""
    base = f"{module_name}.{idx}"
    if not isinstance(entry, Mapping):
        errors.append(PackError(
            module=module_name, field=base, kind="R-1",
            detail={"rule": "entry_not_object", "got": type(entry).__name__},
        ))
        return
    # id / name：id 必填非空（BaseDef.from_entry 名称缺省回退 id，不拦）
    eid = entry.get("id")
    if not isinstance(eid, str) or not eid:
        errors.append(PackError(
            module=module_name, field=f"{base}.id", kind="R-5",
            detail={"rule": "dungeon_id_required"},
        ))
    # type：explore/boss 枚举（硬拦）
    dtype = entry.get("type")
    if dtype not in DUNGEON_TYPES:
        errors.append(PackError(
            module=module_name, field=f"{base}.type", kind="R-1",
            detail={"rule": "type_enum", "value": dtype, "expect": list(DUNGEON_TYPES)},
        ))
    # entry_item：string 或 null（explore 版 null 不扣；boss 版引用 items.json，引用校验不在本路）
    if "entry_item" in entry:
        ev = entry["entry_item"]
        if ev is not None and not isinstance(ev, str):
            errors.append(PackError(
                module=module_name, field=f"{base}.entry_item", kind="R-1",
                detail={"rule": "entry_item_type", "expect": "string|null", "got": type(ev).__name__},
            ))
    # entry_limit：非负整数（0=不限；硬拦类型/负值）
    if "entry_limit" in entry:
        el = entry["entry_limit"]
        if not isinstance(el, int) or isinstance(el, bool):
            errors.append(PackError(
                module=module_name, field=f"{base}.entry_limit", kind="R-1",
                detail={"rule": "entry_limit_type", "expect": "int", "got": type(el).__name__},
            ))
        elif el < 0:
            errors.append(PackError(
                module=module_name, field=f"{base}.entry_limit", kind="R-2",
                detail={"rule": "entry_limit_negative", "value": el},
            ))
    # maps：非空 string[]（两型共用同一组地图 id，2a3 R4）
    maps = entry.get("maps")
    if not isinstance(maps, list):
        errors.append(PackError(
            module=module_name, field=f"{base}.maps", kind="R-1",
            detail={"rule": "maps_type", "expect": "string[]", "got": type(maps).__name__},
        ))
    else:
        if not maps:
            errors.append(PackError(
                module=module_name, field=f"{base}.maps", kind="R-5",
                detail={"rule": "maps_empty", "note": "副本须引用至少一张地图（2a3 R4 地图共用）"},
            ))
        for i, m in enumerate(maps):
            if not isinstance(m, str) or not m:
                errors.append(PackError(
                    module=module_name, field=f"{base}.maps.{i}", kind="R-1",
                    detail={"rule": "maps_element", "expect": "string", "got": type(m).__name__},
                ))
        # maps 引用存在（硬拦；模块内 maps 键存在时检查；缺失 → 宽松跳过 + 登记）
        if map_ids is not None:
            for m in maps:
                if isinstance(m, str) and m and m not in map_ids:
                    errors.append(PackError(
                        module=module_name, field=f"{base}.maps", kind="R-4",
                        detail={"rule": "maps_ref", "ref": m, "expect": "maps.json 地图 id"},
                    ))
        else:
            notes.append(PackNote(
                module=module_name, field=f"{base}.maps", kind="N-1",
                detail={"rule": "maps_module_absent",
                        "note": "maps 模块未装载（批次0·路A 落地前），地图引用存在性检查宽松跳过",
                        "map_ids": [m for m in maps if isinstance(m, str)]},
            ))
    # safe_zone：string 且 ∈ dungeon.maps（硬拦；缺省=入口区）
    if "safe_zone" in entry:
        sz = entry["safe_zone"]
        if not isinstance(sz, str) or not sz:
            errors.append(PackError(
                module=module_name, field=f"{base}.safe_zone", kind="R-1",
                detail={"rule": "safe_zone_type", "expect": "string", "got": type(sz).__name__},
            ))
        elif isinstance(maps, list) and sz not in maps:
            errors.append(PackError(
                module=module_name, field=f"{base}.safe_zone", kind="R-4",
                detail={"rule": "safe_zone_ref", "ref": sz, "expect": "∈ dungeon.maps"},
            ))
    # boss 版（正式赛）：boss_room / boss 必填且引用存在（硬拦）
    if dtype == "boss":
        br = entry.get("boss_room")
        if not isinstance(br, str) or not br:
            errors.append(PackError(
                module=module_name, field=f"{base}.boss_room", kind="R-5",
                detail={"rule": "boss_room_required", "note": "BOSS 版必配 BOSS 房地图 ID"},
            ))
        else:
            in_self = isinstance(maps, list) and br in maps
            in_maps_mod = map_ids is not None and br in map_ids
            if not in_self and not in_maps_mod:
                errors.append(PackError(
                    module=module_name, field=f"{base}.boss_room", kind="R-4",
                    detail={"rule": "boss_room_ref", "ref": br,
                            "expect": "∈ dungeon.maps 或 maps 模块存在"},
                ))
        boss = entry.get("boss")
        if not isinstance(boss, str) or not boss:
            errors.append(PackError(
                module=module_name, field=f"{base}.boss", kind="R-5",
                detail={"rule": "boss_required", "note": "BOSS 版必配 BOSS 怪物 ID"},
            ))
        elif enemy_ids is not None:
            if boss not in enemy_ids:
                errors.append(PackError(
                    module=module_name, field=f"{base}.boss", kind="R-4",
                    detail={"rule": "boss_enemy_ref", "ref": boss, "expect": "enemies.json 怪物 id"},
                ))
        else:
            notes.append(PackNote(
                module=module_name, field=f"{base}.boss", kind="N-1",
                detail={"rule": "enemies_module_absent",
                        "note": "enemies 模块未装载，BOSS 引用存在性检查宽松跳过"},
            ))
    elif dtype == "explore" and "boss" in entry and entry["boss"] is not None:
        notes.append(PackNote(
            module=module_name, field=f"{base}.boss", kind="N-1",
            detail={"rule": "explore_has_boss",
                    "note": "探索版（练习赛）无 BOSS（2a3 R9：boss:null），建议留空/删除"},
        ))
    # drops：对象；first_clear 结构合法（2a1d §2.4：{items[], title, codex}）
    if "drops" in entry:
        drops = entry["drops"]
        if not isinstance(drops, Mapping):
            errors.append(PackError(
                module=module_name, field=f"{base}.drops", kind="R-1",
                detail={"rule": "drops_type", "expect": "object", "got": type(drops).__name__},
            ))
        elif "first_clear" in drops and drops["first_clear"] is not None:
            _check_first_clear(module_name, f"{base}.drops.first_clear", drops["first_clear"], errors)


def _check_first_clear(
    module_name: str,
    path: str,
    fc: object,
    errors: list,
) -> None:
    """drops.first_clear 首通奖励子段结构校验（2a1d §2.4：items 必填（可空）/ title|null / codex string[]）。"""
    if not isinstance(fc, Mapping):
        errors.append(PackError(
            module=module_name, field=path, kind="R-1",
            detail={"rule": "first_clear_type", "expect": "object", "got": type(fc).__name__},
        ))
        return
    if "items" not in fc:
        errors.append(PackError(
            module=module_name, field=f"{path}.items", kind="R-5",
            detail={"rule": "first_clear_items_required", "note": "first_clear.items 必填（可空）"},
        ))
    else:
        items = fc["items"]
        if not isinstance(items, list):
            errors.append(PackError(
                module=module_name, field=f"{path}.items", kind="R-1",
                detail={"rule": "first_clear_items_type", "expect": "list", "got": type(items).__name__},
            ))
        else:
            for i, it in enumerate(items):
                if not isinstance(it, Mapping):
                    errors.append(PackError(
                        module=module_name, field=f"{path}.items.{i}", kind="R-1",
                        detail={"rule": "first_clear_item_entry", "expect": "object", "got": type(it).__name__},
                    ))
                    continue
                item_id = it.get("item")
                if not isinstance(item_id, str) or not item_id:
                    errors.append(PackError(
                        module=module_name, field=f"{path}.items.{i}.item", kind="R-1",
                        detail={"rule": "first_clear_item", "expect": "string", "got": type(item_id).__name__},
                    ))
                if "count" in it:
                    cnt = it["count"]
                    if not isinstance(cnt, int) or isinstance(cnt, bool):
                        errors.append(PackError(
                            module=module_name, field=f"{path}.items.{i}.count", kind="R-1",
                            detail={"rule": "first_clear_count_type", "expect": "int", "got": type(cnt).__name__},
                        ))
                    elif cnt < 1:
                        errors.append(PackError(
                            module=module_name, field=f"{path}.items.{i}.count", kind="R-2",
                            detail={"rule": "first_clear_count_min", "value": cnt, "expect": ">=1"},
                        ))
    if "title" in fc and fc["title"] is not None and not isinstance(fc["title"], str):
        errors.append(PackError(
            module=module_name, field=f"{path}.title", kind="R-1",
            detail={"rule": "first_clear_title_type", "expect": "string|null", "got": type(fc["title"]).__name__},
        ))
    if "codex" in fc:
        codex = fc["codex"]
        if not isinstance(codex, list) or any(not isinstance(c, str) or not c for c in codex):
            errors.append(PackError(
                module=module_name, field=f"{path}.codex", kind="R-1",
                detail={"rule": "first_clear_codex_type", "expect": "string[]", "got": type(codex).__name__},
            ))


def validate_enemy_zone_change(
    modules: Mapping[str, object],
    report: Optional[ValidationReport] = None,
) -> ValidationReport:
    """enemies.json zone_change 子段独立校验（m3 §3.1）。纯函数，合并既有 report 返回新报告。

    供主 agent 单独接线（若 zone_change 校验想独立于 dungeon 挂接）；validate_dungeons 内亦调用。
    """
    errors = list(report.errors) if report is not None else []
    notes = list(report.notes) if report is not None else []
    _check_zone_change(modules, errors, notes)
    warnings = list(report.warnings) if report is not None else []
    return ValidationReport(errors=tuple(errors), warnings=tuple(warnings), notes=tuple(notes))


def validate_dungeons(
    modules: Mapping[str, object],
    report: Optional[ValidationReport] = None,
) -> ValidationReport:
    """dungeon.json 两型 + enemies zone_change 校验（M16 + M11）。纯函数，无副作用。

    入口：`validate_dungeons(modules, report)` → 合并既有 report（可为 check_pack 产物）返回新
    ValidationReport；errors 非空即阻断（与 check_pack 同一 report.ok 语义）。供主 agent 收口时
    在 check_pack 尾部调用并以返回值替代原 report。

    硬拦（R-1 类型 / R-2 数值 / R-4 引用 / R-5 结构）：
      - type ∈ explore/boss
      - maps 非空 string[]，且引用存在（maps 模块存在时硬拦；缺失 → N1 登记宽松跳过）
      - boss_room ∈ dungeon.maps 或 maps 模块存在（BOSS 版必填）
      - boss 引用 enemies.json 怪物 id 存在（BOSS 版必填；enemies 模块存在时硬拦）
      - entry_limit 非负整数 / safe_zone ∈ dungeon.maps / drops.first_clear 结构合法
      - enemies zone_change：enabled bool / hp_threshold ∈ (0,1) / targets 非空 string[] / timing 枚举
    """
    errors = list(report.errors) if report is not None else []
    warnings = list(report.warnings) if report is not None else []
    notes = list(report.notes) if report is not None else []

    # zone_change 子段（enemies，m3 §3.1）
    _check_zone_change(modules, errors, notes)

    # 引用空间（maps 由批次0·路A 提供；本路「模块内 maps 键存在时检查」）
    map_ids = _collect_map_ids(modules)
    enemy_ids = _collect_enemy_ids(modules)

    dungeon_data = modules.get("dungeon")
    if dungeon_data is None:
        return ValidationReport(errors=tuple(errors), warnings=tuple(warnings), notes=tuple(notes))
    if not isinstance(dungeon_data, list):
        errors.append(PackError(
            module="dungeon", field="dungeon", kind="R-5",
            detail={"rule": "module_structure", "expect": "list", "got": type(dungeon_data).__name__},
        ))
        return ValidationReport(errors=tuple(errors), warnings=tuple(warnings), notes=tuple(notes))
    for idx, entry in enumerate(dungeon_data):
        _check_dungeon_entry("dungeon", idx, entry, map_ids, enemy_ids, errors, notes)

    return ValidationReport(errors=tuple(errors), warnings=tuple(warnings), notes=tuple(notes))


__all__ = [
    "DUNGEON_TYPES",
    "ZONE_CHANGE_TIMINGS",
    "DungeonDef",
    "validate_dungeons",
    "validate_enemy_zone_change",
]
