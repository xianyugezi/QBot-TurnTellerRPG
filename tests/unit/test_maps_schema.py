"""M3 批次0·路A：maps.json 地图装载（M01）+ 刷怪配置（M07）schema 校验测试。

依据：细化_2a1a（节点 8 字段）+ 细化_2a1b（通道规则/刷怪 R14-R26）+ m3_shared_contract §2
（地图层 §2.1-2.3：exits 校验器 ①-④ / spawn 行 7 字段）+ 细化_2a1c（dungeon_entrances）。
测试目标：qbot_rpg.content.map_models.validate_maps（独立模块专项校验，供主 agent 收口接 check_pack）。

测试口径（对齐 test_enemies_schema）：构造输入 → 跑校验器 → 断言级别/结果。
  - validate_maps(modules, report) 为纯函数；report 鸭子类型（本文件 _Report 收集器；
    另含一条真实 _Checker 收口兼容测试——validate_maps 直传 validator._Checker 实例）。
  - 断言级别：errors=拦截（硬拦）/ warnings=黄提示（不拦截）。
  - 合法包全绿：tests/fixtures/packs/legal（已声明 maps 模块）整包零红拦零黄（契约 §2.2 ④ 双向对称）。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.loader import build_pack
from qbot_rpg.content.map_models import (
    EXIT_DIRECTIONS,
    EXIT_MODES,
    PERIODS_ENUM,
    SEASONS_ENUM,
    MapDef,
    SpawnDef,
    parse_maps,
    validate_maps,
)
from qbot_rpg.content.validator import _Checker, check_pack

PACKS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "packs"
LEGAL_DIR = PACKS_DIR / "legal"


# ---------------------------------------------------------------------------
# 夹具辅助：构造输入 → 跑校验器
# ---------------------------------------------------------------------------
class _Report:
    """validate_maps 收集器（鸭子类型：error/warning 与 validator._Checker._err/_warn 签名一致）。"""

    def __init__(self) -> None:
        self.errors: list = []
        self.warnings: list = []
        self.notes: list = []

    def error(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def warning(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})


def _load_pack_json(pack_dir: Path, name: str) -> object:
    return json.loads((pack_dir / f"{name}.json").read_text(encoding="utf-8"))


def _legal_enemies() -> list:
    data = _load_pack_json(LEGAL_DIR, "enemies")
    assert isinstance(data, list)
    return data


def _base_maps() -> list:
    """legal/maps.json 的深拷贝（3 图：rubble_field/crag_den/lava_tunnel），供用例构造输入。"""
    data = _load_pack_json(LEGAL_DIR, "maps")
    assert isinstance(data, list)
    assert len(data) == 3
    return copy.deepcopy(data)


def _map_by_id(maps: list, mid: str) -> dict:
    for m in maps:
        if m.get("id") == mid:
            return m
    raise AssertionError(f"maps.json 缺少地图 {mid}")


def _check(maps: object, enemies: object = None):
    """标准模块上下文（maps + legal enemies 引用基线）跑 validate_maps。"""
    modules: dict = {"maps": maps}
    if enemies is not None:
        modules["enemies"] = enemies
    rep = _Report()
    validate_maps(modules, rep)
    return rep


def _errs(rep, rule: str | None = None) -> list:
    return [e for e in rep.errors if rule is None or e["detail"].get("rule") == rule]


def _warns(rep, rule: str | None = None) -> list:
    return [w for w in rep.warnings if rule is None or w["detail"].get("rule") == rule]


# ---------------------------------------------------------------------------
# 合法包零红拦 + 8 字段访问器（M01 装载形状）
# ---------------------------------------------------------------------------
def test_legal_maps_full_green() -> None:
    """合法 maps.json（3 图：双向/单向/隐藏 exits、spawn 2 行、gate_guard、dungeon_entrances）
    整包零红拦零黄（契约 §2.2 ④ 双向对称）→ 全绿。"""
    maps = _base_maps()
    rep = _check(maps, enemies=_legal_enemies())
    assert not rep.errors, f"合法 maps 不应有红拦：{rep.errors}"
    assert not rep.warnings, f"合法 maps 应为零黄提示（双向对称）：{rep.warnings}"


def test_legal_maps_pack_green_via_checker_integration() -> None:
    """收口兼容：validate_maps 直传真实 validator._Checker（_err/_warn 鸭子路径）零红拦；
    且 legal 整包（manifest 已声明 maps）build_pack 全绿零黄。"""
    maps = _base_maps()
    modules = {"maps": maps, "enemies": _legal_enemies()}
    checker = _Checker(modules, default_field_meta_table())
    validate_maps(modules, checker)
    assert not checker.errors, f"直传 _Checker 应零红拦：{checker.errors}"
    assert not checker.warnings, f"直传 _Checker 应零黄：{checker.warnings}"
    # 整包回归：maps 已声明进 legal manifest → 泛型校验 + 挂载 registry 全绿
    pack, changed = build_pack(LEGAL_DIR)
    assert changed
    assert pack.report.ok, f"合法包不应有红拦：{pack.report.errors}"
    assert not pack.report.warnings, f"合法包应为零黄提示：{pack.report.warnings}"
    assert pack.registry.resolve("rubble_field", "map") is not None


def test_map_def_8_field_accessors() -> None:
    """MapDef 8 字段访问器 + SpawnDef/ExitDef 派生访问器（风格对齐 EnemyDef）。"""
    maps = _base_maps()
    defs = parse_maps({"maps": maps})
    assert len(defs) == 3 and all(isinstance(m, MapDef) for m in defs)

    rubble = next(m for m in defs if m.id == "rubble_field")
    assert rubble.name == "乱石滩入口"
    assert isinstance(rubble.desc, str) and rubble.desc
    # exits：up 双向 / down 单向 / right 隐藏（含 condition）→ 4 方向键枚举
    assert rubble.exit_dirs == ("up", "down", "right")
    up_exit = rubble.exit("up")
    down_exit = rubble.exit("down")
    hidden = rubble.exit("right")
    assert up_exit is not None and down_exit is not None and hidden is not None
    assert up_exit.mode == "bidirectional" and up_exit.to == "crag_den"
    assert down_exit.mode == "one_way"
    assert hidden.mode == "hidden" and hidden.condition == {"var": "subquest_done", "op": "eq",
                                                            "param": "learn_mechanic"}
    assert rubble.exit("left") is None  # 未配置方向 = 死路
    # spawn：2 行 → SpawnDef 七字段访问器
    spawns = rubble.spawn_defs()
    assert len(spawns) == 2 and all(isinstance(s, SpawnDef) for s in spawns)
    weasel = spawns[0]
    assert weasel.enemy == "rock_weasel" and weasel.count == 3 and weasel.respawn_minutes == 10
    assert weasel.active_from == "20:00" and weasel.active_to == "06:00"  # 跨夜窗口
    assert weasel.seasons == ("autumn", "winter") and weasel.periods == ("night", "midnight")
    assert weasel.weather_weights == {"fog": 2, "rain": 0.5}  # 概率小数 0.5
    assert spawns[1].count == 1 and spawns[1].respawn_minutes == 30  # 缺省 active_time/seasons 空
    # gate_guard + dungeon_entrances（引用将来 dungeon 的合法样例，2a1c）
    lava = next(m for m in defs if m.id == "lava_tunnel")
    assert lava.gate_guard == "ember_drake"
    assert rubble.dungeon_entrances == ({"dungeon": "molten_dungeon", "name": "熔岩洞窟·讨伐"},)
    # mechanics（场地效果承载）
    crag = next(m for m in defs if m.id == "crag_den")
    assert crag.mechanics and crag.mechanics[0]["id"] == "rockfall"


# ---------------------------------------------------------------------------
# 契约 §2.2 ①-③：to 悬空 / mode 非法 / hidden 缺 condition（硬拦）
# ---------------------------------------------------------------------------
def test_exit_to_dangling_red() -> None:
    """① exits.<方向>.to 目标地图 ID 不存在 → 硬拦（R-4 map_exit_target_missing）。"""
    maps = _base_maps()
    _map_by_id(maps, "rubble_field")["exits"]["up"]["to"] = "nowhere_land"
    rep = _check(maps, enemies=_legal_enemies())
    errs = _errs(rep, "map_exit_target_missing")
    assert len(errs) == 1 and errs[0]["detail"]["ref"] == "nowhere_land"
    assert errs[0]["kind"] == "R-4" and errs[0]["field"] == "maps.0.exits.up.to"


def test_exit_mode_invalid_red() -> None:
    """② mode ∉ {bidirectional, one_way, hidden} → 硬拦（R-1 map_exit_mode_invalid）。"""
    maps = _base_maps()
    _map_by_id(maps, "rubble_field")["exits"]["down"]["mode"] = "portal"
    rep = _check(maps, enemies=_legal_enemies())
    errs = _errs(rep, "map_exit_mode_invalid")
    assert len(errs) == 1 and errs[0]["detail"]["mode"] == "portal"
    assert errs[0]["detail"]["allowed"] == list(EXIT_MODES)
    assert not rep.warnings, f"mode 非法不应牵连黄提示：{rep.warnings}"


def test_exit_mode_missing_red() -> None:
    """mode 缺省 → 硬拦（R-1 map_exit_mode_required；契约 §2.2 mode 必填）。"""
    maps = _base_maps()
    del _map_by_id(maps, "rubble_field")["exits"]["down"]["mode"]
    rep = _check(maps, enemies=_legal_enemies())
    assert _errs(rep, "map_exit_mode_required"), f"缺 mode 应硬拦，实际 {rep.errors}"


def test_exit_direction_invalid_red() -> None:
    """方向键 ∉ {up/down/left/right} → 硬拦（R-5 map_exit_direction_invalid；2a1b R2 每图 ≤4 方向）。"""
    maps = _base_maps()
    _map_by_id(maps, "rubble_field")["exits"]["diagonal"] = {"to": "crag_den", "mode": "one_way"}
    rep = _check(maps, enemies=_legal_enemies())
    errs = _errs(rep, "map_exit_direction_invalid")
    assert len(errs) == 1 and errs[0]["detail"]["direction"] == "diagonal"
    assert errs[0]["detail"]["allowed"] == list(EXIT_DIRECTIONS)


def test_hidden_missing_condition_red() -> None:
    """③ hidden 必带 condition → 硬拦（R-5 map_exit_hidden_condition_required）。"""
    maps = _base_maps()
    del _map_by_id(maps, "rubble_field")["exits"]["right"]["condition"]
    rep = _check(maps, enemies=_legal_enemies())
    errs = _errs(rep, "map_exit_hidden_condition_required")
    assert len(errs) == 1 and errs[0]["detail"]["direction"] == "right"


def test_hidden_condition_malformed_red() -> None:
    """hidden 的 condition 非条件表达式对象 → 硬拦（R-5 map_exit_condition_invalid）。"""
    maps = _base_maps()
    _map_by_id(maps, "rubble_field")["exits"]["right"]["condition"] = "just_a_string"
    rep = _check(maps, enemies=_legal_enemies())
    assert _errs(rep, "map_exit_condition_invalid"), f"condition 非对象应硬拦，实际 {rep.errors}"


def test_condition_on_non_hidden_yellow() -> None:
    """condition 配在非 hidden 通道（双向/单向不可配置，2a1b §1.4）→ 黄提示不拦截。"""
    maps = _base_maps()
    _map_by_id(maps, "rubble_field")["exits"]["up"]["condition"] = {
        "var": "season", "op": "eq", "param": "winter"}
    rep = _check(maps, enemies=_legal_enemies())
    assert not rep.errors, f"condition-not-hidden 不应红拦：{rep.errors}"
    warns = _warns(rep, "map_exit_condition_not_hidden")
    assert len(warns) == 1 and warns[0]["detail"]["mode"] == "bidirectional"


# ---------------------------------------------------------------------------
# 契约 §2.2 ④：双向不对称 → 黄提示
# ---------------------------------------------------------------------------
def test_bidirectional_asymmetry_yellow() -> None:
    """④ A→B 双向而 B→A 单向 → 黄提示"双向不对称"（不拦截，允许作者刻意不对称）。

    拓扑：rubble_field.up→crag_den 双向；把对侧 crag_den.down→rubble_field 改为 one_way。"""
    maps = _base_maps()
    _map_by_id(maps, "crag_den")["exits"]["down"]["mode"] = "one_way"
    rep = _check(maps, enemies=_legal_enemies())
    assert not rep.errors, f"双向不对称仅为黄提示，实际 {rep.errors}"
    warns = _warns(rep, "map_exit_bidirectional_asymmetry")
    assert len(warns) == 1
    w = warns[0]
    assert w["field"] == "maps.0.exits.up" and w["kind"] == "Y-8"
    assert w["detail"]["to"] == "crag_den" and w["detail"]["back_missing"] is False
    assert w["detail"]["back_mode"] == "one_way"


def test_bidirectional_asymmetry_back_missing_yellow() -> None:
    """④ 变体：A→B 双向而对侧完全无回边 → 黄提示（back_missing=True）。"""
    maps = _base_maps()
    del _map_by_id(maps, "crag_den")["exits"]["down"]  # 删掉回边
    rep = _check(maps, enemies=_legal_enemies())
    assert not rep.errors, f"缺回边仅为黄提示，实际 {rep.errors}"
    warns = _warns(rep, "map_exit_bidirectional_asymmetry")
    assert len(warns) == 1 and warns[0]["detail"]["back_missing"] is True


# ---------------------------------------------------------------------------
# 刷怪（M07）：spawn[].enemy 引用存在（2a1b R24 硬拦）
# ---------------------------------------------------------------------------
def test_spawn_enemy_dangling_red() -> None:
    """spawn[].enemy 引用 enemies.json 不存在的 ID → 硬拦（R-4 map_spawn_enemy_missing）。"""
    maps = _base_maps()
    _map_by_id(maps, "rubble_field")["spawn"][0]["enemy"] = "ghost_spirit"
    rep = _check(maps, enemies=_legal_enemies())
    errs = _errs(rep, "map_spawn_enemy_missing")
    assert len(errs) == 1 and errs[0]["detail"]["ref"] == "ghost_spirit"
    assert errs[0]["kind"] == "R-4" and errs[0]["field"] == "maps.0.spawn.0.enemy"


def test_spawn_enemy_by_name_passes() -> None:
    """spawn[].enemy 用 enemies.json 的 name（契约 §2.3「id/name 均可」）→ 通过。"""
    maps = _base_maps()
    _map_by_id(maps, "rubble_field")["spawn"][0]["enemy"] = "岩皮鼬"  # rock_weasel 的 name
    rep = _check(maps, enemies=_legal_enemies())
    assert not _errs(rep, "map_spawn_enemy_missing"), f"name 引用应通过，实际 {rep.errors}"


def test_spawn_enemy_required_red() -> None:
    """spawn 行缺 enemy → 硬拦（R-5 map_spawn_enemy_required；契约 §2.3 必填）。"""
    maps = _base_maps()
    del _map_by_id(maps, "rubble_field")["spawn"][0]["enemy"]
    rep = _check(maps, enemies=_legal_enemies())
    assert _errs(rep, "map_spawn_enemy_required"), f"缺 enemy 应硬拦，实际 {rep.errors}"


# ---------------------------------------------------------------------------
# 刷怪（M07）：count / respawn_minutes 非负整数（2a1b R26 硬拦）
# ---------------------------------------------------------------------------
def test_spawn_count_non_negative_integer_red() -> None:
    """count 负数 / 非整数 → 硬拦（R-2 map_spawn_count_invalid）；缺省（=1）通过。"""
    for bad in (-1, 2.5, "3", True):
        maps = _base_maps()
        _map_by_id(maps, "rubble_field")["spawn"][0]["count"] = bad
        rep = _check(maps, enemies=_legal_enemies())
        errs = _errs(rep, "map_spawn_count_invalid")
        assert len(errs) == 1 and errs[0]["detail"]["value"] == bad, (
            f"count={bad!r} 应硬拦，实际 {rep.errors}")
    # count 缺省 = 1【工程补白】不拦
    maps = _base_maps()
    del _map_by_id(maps, "rubble_field")["spawn"][0]["count"]
    rep = _check(maps, enemies=_legal_enemies())
    assert not _errs(rep, "map_spawn_count_invalid")


def test_spawn_respawn_minutes_validation_red() -> None:
    """respawn_minutes 缺省 / 0 / 非整数 → 硬拦（契约 §2.3 必填且 ≥1）。"""
    maps = _base_maps()
    del _map_by_id(maps, "rubble_field")["spawn"][0]["respawn_minutes"]
    rep = _check(maps, enemies=_legal_enemies())
    assert _errs(rep, "map_spawn_respawn_required"), f"缺 respawn 应硬拦，实际 {rep.errors}"
    for bad in (0, -5, 2.5, "10"):
        maps = _base_maps()
        _map_by_id(maps, "rubble_field")["spawn"][0]["respawn_minutes"] = bad
        rep = _check(maps, enemies=_legal_enemies())
        errs = _errs(rep, "map_spawn_respawn_invalid")
        assert len(errs) == 1 and errs[0]["detail"]["value"] == bad, (
            f"respawn={bad!r} 应硬拦，实际 {rep.errors}")


# ---------------------------------------------------------------------------
# 刷怪（M07）：出没条件枚举/结构（2a1b R25-R26）
# ---------------------------------------------------------------------------
def test_spawn_seasons_periods_enum_red() -> None:
    """seasons ∉ 四季 / periods ∉ 五时段 → 硬拦（R-1，2a1b R25）。"""
    maps = _base_maps()
    _map_by_id(maps, "rubble_field")["spawn"][0]["seasons"] = ["monday"]
    rep = _check(maps, enemies=_legal_enemies())
    errs = _errs(rep, "map_spawn_seasons_invalid")
    assert len(errs) == 1 and errs[0]["detail"]["allowed"] == list(SEASONS_ENUM)
    maps = _base_maps()
    _map_by_id(maps, "rubble_field")["spawn"][0]["periods"] = ["noon_extra"]
    rep = _check(maps, enemies=_legal_enemies())
    assert _errs(rep, "map_spawn_periods_invalid") and \
        _errs(rep, "map_spawn_periods_invalid")[0]["detail"]["allowed"] == list(PERIODS_ENUM)


def test_spawn_active_time_structure_red() -> None:
    """active_time 缺 from/to 或非 {from,to} 结构 → 硬拦（R-1 map_spawn_active_time_invalid）。"""
    maps = _base_maps()
    _map_by_id(maps, "rubble_field")["spawn"][0]["active_time"] = {"from": "20:00"}  # 缺 to
    rep = _check(maps, enemies=_legal_enemies())
    errs = _errs(rep, "map_spawn_active_time_invalid")
    assert len(errs) == 1 and errs[0]["detail"]["key"] == "to"


def test_spawn_weather_weights_non_negative_red() -> None:
    """weather_weights 值为负/非数 → 硬拦（R-2 map_spawn_weather_weight_invalid；0=不刷合法）。
    key ∈ 注册天气集归 M41（契约 §6.2 V5/V6），此处不校验。"""
    for bad in (-1, -0.5, "foggy"):
        maps = _base_maps()
        _map_by_id(maps, "rubble_field")["spawn"][0]["weather_weights"] = {"fog": bad}
        rep = _check(maps, enemies=_legal_enemies())
        errs = _errs(rep, "map_spawn_weather_weight_invalid")
        assert len(errs) == 1 and errs[0]["detail"]["value"] == bad, (
            f"weight={bad!r} 应硬拦，实际 {rep.errors}")
    # 0 = 该天气不刷（合法）；小数倍率合法
    maps = _base_maps()
    _map_by_id(maps, "rubble_field")["spawn"][0]["weather_weights"] = {"storm": 0, "fog": 0.25}
    rep = _check(maps, enemies=_legal_enemies())
    assert not _errs(rep, "map_spawn_weather_weight_invalid")


# ---------------------------------------------------------------------------
# gate_guard 引用存在（契约 §2.1 守门怪 = enemies.json 怪物 ID，硬拦）
# ---------------------------------------------------------------------------
def test_gate_guard_dangling_red() -> None:
    """gate_guard 引用不存在怪物 → 硬拦（R-4 map_gate_guard_missing）。"""
    maps = _base_maps()
    _map_by_id(maps, "lava_tunnel")["gate_guard"] = "ghost_boss"
    rep = _check(maps, enemies=_legal_enemies())
    errs = _errs(rep, "map_gate_guard_missing")
    assert len(errs) == 1 and errs[0]["detail"]["ref"] == "ghost_boss"


# ---------------------------------------------------------------------------
# 结构护栏：spawn 非数组 / 模块结构
# ---------------------------------------------------------------------------
def test_spawn_not_list_red() -> None:
    """spawn 非数组 → 硬拦（R-1 map_spawn_not_list）。"""
    maps = _base_maps()
    _map_by_id(maps, "rubble_field")["spawn"] = {"enemy": "rock_weasel"}
    rep = _check(maps, enemies=_legal_enemies())
    assert _errs(rep, "map_spawn_not_list"), f"spawn 非数组应硬拦，实际 {rep.errors}"


def test_maps_module_not_list_red() -> None:
    """maps 模块非数组 → 硬拦（R-5 module_structure expect=list）。"""
    rep = _check({"not_a_list": True}, enemies=_legal_enemies())
    assert _errs(rep, "module_structure"), f"maps 非数组应硬拦，实际 {rep.errors}"


def test_maps_missing_module_default_allow() -> None:
    """未声明 maps 模块 → 默认放行（细化_3e §2.3，零红拦零黄）。"""
    rep = _check(None, enemies=_legal_enemies())
    assert not rep.errors and not rep.warnings
    # enemies 未声明时跳过 enemy 引用检查（不误拦）
    maps = _base_maps()
    _map_by_id(maps, "rubble_field")["spawn"][0]["enemy"] = "ghost_spirit"
    rep2 = _check(maps, enemies=None)
    assert not _errs(rep2, "map_spawn_enemy_missing"), "enemies 未声明应跳过引用检查"


def test_check_pack_generic_ignores_new_maps_fields() -> None:
    """泛型 check_pack（收口前的现有行为）：新 schema 字段（spawn/exits/mechanics/...）按未知字段
    默认放行，不产生红拦/黄提示——确保合法 maps 并入 legal 包不破坏既有零黄基线。"""
    modules = {
        "action": _load_pack_json(LEGAL_DIR, "action"),
        "effects": _load_pack_json(LEGAL_DIR, "effects"),
        "statuses": _load_pack_json(LEGAL_DIR, "statuses"),
        "items": _load_pack_json(LEGAL_DIR, "items"),
        "enemies": _legal_enemies(),
        "maps": _base_maps(),
    }
    rep = check_pack(modules)
    assert not rep.errors, f"泛型校验不应有红拦：{rep.errors}"
    assert not rep.warnings, f"泛型校验不应有黄提示：{rep.warnings}"
