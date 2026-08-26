"""M3 批次0·路B：dungeon.json 副本两型装载校验（M16）+ enemies zone_change 换区配置校验（M11）schema 测试。

依据：m3_shared_contract §3（zone_change）/ §4.1（dungeon.json 11 字段）+ 细化_2a3（副本两型 R1-R12）+
细化_2a2（换区追击 zone_change）+ 细化_2a1d §2.4（drops.first_clear 结构）。校验入口：qbot_rpg.content.dungeon_models
.validate_dungeons（纯函数，直接喂 modules 字典；供主 agent 收口接 check_pack）。

登记（供主 agent 收口）：
  1. legal/dungeon.json 已就位，但 manifest.json 未声明 `dungeon` 模块（零冲突原则：不碰共享 manifest；
     build_pack 只加载声明模块，未声明文件不加载）。主 agent 接线 check_pack + 注册 registry 时，
     将 `dungeon` 加入 legal/manifest.json 的 modules 即可（dungeon 无 FieldMeta → 默认放行，零黄零拦）。
  2. legal/enemies.json ember_drake 已加 zone_change 样例（BOSS 残血换区，targets 用副本 mock 地图 id）；
     现有 enemies 八段校验器对未知字段默认放行（细化_3e §2.3），不破坏合法包零黄基线。
  3. maps 模块由批次0·路A 提供（legal fixtures 暂不含 maps.json）：本测试以 mock 3 张图 id 作引用基线；
     validate_dungeons 在 maps 模块缺失时宽松跳过引用检查并登记 N1 提示（已覆盖）。

断言级别：errors=红拦（硬拦）/ warnings=黄提示（不拦截）/ notes=提示（信息）。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Mapping, cast

from qbot_rpg.content.dungeon_models import (
    DUNGEON_TYPES,
    ZONE_CHANGE_TIMINGS,
    DungeonDef,
    validate_dungeons,
)
from qbot_rpg.content.models import PackError, PackNote, ValidationReport

PACKS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "packs"
LEGAL_DIR = PACKS_DIR / "legal"

# 副本 mock 地图 id（对齐 2a3 R4 熔岩洞窟示例；maps.json 由批次0·路A 提供，测试用 mock 引用基线）
MOCK_MAP_IDS = ("rubble_field", "crag_den", "lava_tunnel")


# ---------------------------------------------------------------------------
# 夹具辅助：构造输入 → 跑校验器
# ---------------------------------------------------------------------------
def _load_pack_json(pack_dir: Path, name: str) -> object:
    return json.loads((pack_dir / f"{name}.json").read_text(encoding="utf-8"))


def _legal_dungeons() -> list:
    data = _load_pack_json(LEGAL_DIR, "dungeon")
    assert isinstance(data, list)
    return data


def _legal_enemies() -> list:
    data = _load_pack_json(LEGAL_DIR, "enemies")
    assert isinstance(data, list)
    return data


def _mock_maps() -> list:
    """mock maps 模块（3 张熔岩洞窟图，id 与 legal/dungeon.json 的 maps 引用一致）。"""
    return [
        {"id": "rubble_field", "name": "碎石原野"},
        {"id": "crag_den", "name": "岩巢"},
        {"id": "lava_tunnel", "name": "熔岩隧道"},
    ]


def _dungeon_by_id(did: str) -> dict:
    for d in _legal_dungeons():
        if d.get("id") == did:
            return copy.deepcopy(d)
    raise AssertionError(f"legal/dungeon.json 缺少 {did}")


def _base_boss(**overrides: object) -> dict:
    """合法 BOSS 版副本深拷贝（TC 合法形状），用于单条校验用例的构造输入。"""
    boss = _dungeon_by_id("molten_dungeon_boss")
    boss.update(overrides)
    return boss


def _base_explore(**overrides: object) -> dict:
    """合法探索版副本深拷贝（TC 合法形状）。"""
    explore = _dungeon_by_id("molten_dungeon_explore")
    explore.update(overrides)
    return explore


def _enemies_with_zone_change(**zc: object) -> list:
    """深拷贝合法 enemies，覆盖 ember_drake 的 zone_change 子段。"""
    enemies = _legal_enemies()
    for e in enemies:
        if e.get("id") == "ember_drake":
            e["zone_change"] = zc
            return enemies
    raise AssertionError("legal/enemies.json 缺少 ember_drake")


def _check(
    dungeons: list,
    *,
    with_maps: bool = True,
    with_enemies: bool = True,
    extra: dict | None = None,
) -> ValidationReport:
    """标准模块上下文（maps mock + enemies legal 含 zone_change 样例）+ 传入 dungeons 跑 validate_dungeons。"""
    modules: dict = {}
    if with_maps:
        modules["maps"] = _mock_maps()
    if with_enemies:
        modules["enemies"] = _legal_enemies()
    modules["dungeon"] = dungeons
    if extra:
        modules.update(extra)
    return validate_dungeons(modules)


def _errs(rep: ValidationReport, rule: str | None = None) -> list:
    return [e for e in rep.errors if rule is None or e.detail.get("rule") == rule]


def _notes(rep: ValidationReport, rule: str | None = None) -> list:
    return [n for n in rep.notes if rule is None or n.detail.get("rule") == rule]


def _warns(rep: ValidationReport, rule: str | None = None) -> list:
    return [w for w in rep.warnings if rule is None or w.detail.get("rule") == rule]


# ---------------------------------------------------------------------------
# 1. 合法包零红拦（两型 + zone_change 样例；maps 装载/缺失两口径）
# ---------------------------------------------------------------------------
def test_legal_dungeons_zero_errors_with_maps() -> None:
    """合法 dungeon.json（explore + boss 两型，共用 3 张 mock 地图 id）+ enemies zone_change 样例
    + maps 模块装载 → 零红拦零黄提示；boss 版 BOSS 引用 ember_drake 命中。"""
    rep = _check(_legal_dungeons())
    assert rep.ok, f"合法副本包不应有红拦：{rep.errors}"
    assert not _warns(rep), f"合法副本包应为零黄提示：{rep.warnings}"
    assert not rep.errors
    assert not _errs(rep, "maps_module_absent"), "maps 装载时不应登记 maps 缺失提示"


def test_legal_dungeons_zero_errors_maps_absent_lenient() -> None:
    """maps 模块缺失（批次0·路A 落地前）→ 地图引用检查宽松跳过 + 每副本登记 N1 提示，不红拦。"""
    rep = _check(_legal_dungeons(), with_maps=False)
    assert rep.ok, f"maps 缺失时合法副本应零红拦：{rep.errors}"
    notes = _notes(rep, "maps_module_absent")
    assert len(notes) == 2, f"两型副本各应登记一条 maps 缺失提示，实际 {len(notes)}"
    assert notes[0].detail["map_ids"] == list(MOCK_MAP_IDS)


# ---------------------------------------------------------------------------
# 2. type 非法（硬拦）
# ---------------------------------------------------------------------------
def test_type_invalid_blocked() -> None:
    """type: raid（非 explore/boss）→ 拦截 R-1 type_enum。"""
    rep = _check([_base_boss(type="raid")])
    errs = _errs(rep, "type_enum")
    assert len(errs) == 1 and errs[0].detail.get("value") == "raid"
    assert DUNGEON_TYPES == ("explore", "boss")


# ---------------------------------------------------------------------------
# 3. maps 悬空（硬拦；模块内 maps 键存在时检查）
# ---------------------------------------------------------------------------
def test_maps_dangling_blocked() -> None:
    """maps 引用 maps.json 不存在的 id → 拦截 R-4 maps_ref（maps 模块装载时硬拦）。"""
    rep = _check([_base_boss(maps=["rubble_field", "molten_ghost"])])
    errs = _errs(rep, "maps_ref")
    assert len(errs) == 1 and errs[0].detail.get("ref") == "molten_ghost"


def test_maps_empty_blocked() -> None:
    """maps 空数组 → 拦截 R-5 maps_empty（两型共用同一组地图，2a3 R4）。"""
    rep = _check([_base_boss(maps=[])])
    assert _errs(rep, "maps_empty")


# ---------------------------------------------------------------------------
# 4. boss 悬空（硬拦）
# ---------------------------------------------------------------------------
def test_boss_enemy_dangling_blocked() -> None:
    """boss 引用 enemies.json 不存在的 id → 拦截 R-4 boss_enemy_ref（enemies 装载时硬拦）。"""
    rep = _check([_base_boss(boss="ghost_dragon")])
    errs = _errs(rep, "boss_enemy_ref")
    assert len(errs) == 1 and errs[0].detail.get("ref") == "ghost_dragon"


def test_boss_room_dangling_blocked() -> None:
    """boss_room 不在 dungeon.maps 且不在 maps 模块 → 拦截 R-4 boss_room_ref。"""
    rep = _check([_base_boss(boss_room="molten_ghost")])
    errs = _errs(rep, "boss_room_ref")
    assert len(errs) == 1 and errs[0].detail.get("ref") == "molten_ghost"


def test_boss_room_required_for_boss_type() -> None:
    """BOSS 版缺 boss_room → 拦截 R-5 boss_room_required。"""
    boss = _base_boss()
    del boss["boss_room"]
    rep = _check([boss])
    assert _errs(rep, "boss_room_required")


# ---------------------------------------------------------------------------
# 5. entry_limit 非负整数（硬拦类型/负值）
# ---------------------------------------------------------------------------
def test_entry_limit_negative_blocked() -> None:
    """entry_limit: -1 → 拦截 R-2 entry_limit_negative。"""
    rep = _check([_base_boss(entry_limit=-1)])
    errs = _errs(rep, "entry_limit_negative")
    assert len(errs) == 1 and errs[0].detail.get("value") == -1


def test_entry_limit_type_blocked() -> None:
    """entry_limit: 3.5（非整数）→ 拦截 R-1 entry_limit_type。"""
    rep = _check([_base_boss(entry_limit=3.5)])
    assert _errs(rep, "entry_limit_type")


# ---------------------------------------------------------------------------
# 6. enemies zone_change 子段（M11：enabled/hp_threshold/targets/timing）
# ---------------------------------------------------------------------------
def test_zone_change_hp_threshold_out_of_range_blocked() -> None:
    """zone_change.hp_threshold: 1.5 超出 (0,1) → 拦截 R-2 zc_hp_threshold_range。"""
    rep = _check(_legal_dungeons(), with_enemies=True,
                 extra={"enemies": _enemies_with_zone_change(hp_threshold=1.5)})
    errs = _errs(rep, "zc_hp_threshold_range")
    assert len(errs) == 1 and errs[0].detail.get("value") == 1.5


def test_zone_change_hp_threshold_zero_blocked() -> None:
    """zone_change.hp_threshold: 0（开区间下界）→ 拦截 R-2 zc_hp_threshold_range。"""
    rep = _check(_legal_dungeons(),
                 extra={"enemies": _enemies_with_zone_change(hp_threshold=0)})
    assert _errs(rep, "zc_hp_threshold_range")


def test_zone_change_enabled_type_blocked() -> None:
    """zone_change.enabled: \"yes\"（非 bool）→ 拦截 R-1 zc_enabled_type。"""
    rep = _check(_legal_dungeons(),
                 extra={"enemies": _enemies_with_zone_change(enabled="yes")})
    assert _errs(rep, "zc_enabled_type")


def test_zone_change_targets_empty_blocked() -> None:
    """zone_change.targets: [] → 拦截 R-5 zc_targets_empty（2a2 R4：空=永不换区）。"""
    rep = _check(_legal_dungeons(),
                 extra={"enemies": _enemies_with_zone_change(targets=[])})
    assert _errs(rep, "zc_targets_empty")


def test_zone_change_targets_element_type_blocked() -> None:
    """zone_change.targets 含非 string 元素 → 拦截 R-1 zc_targets_element。"""
    rep = _check(_legal_dungeons(),
                 extra={"enemies": _enemies_with_zone_change(targets=["molten_core", 42])})
    assert _errs(rep, "zc_targets_element")


def test_zone_change_timing_enum_blocked() -> None:
    """zone_change.timing: \"battle_end\"（非枚举）→ 拦截 R-1 zc_timing_enum。"""
    rep = _check(_legal_dungeons(),
                 extra={"enemies": _enemies_with_zone_change(timing="battle_end")})
    errs = _errs(rep, "zc_timing_enum")
    assert len(errs) == 1 and errs[0].detail.get("value") == "battle_end"
    assert ZONE_CHANGE_TIMINGS == ("after_action", "phase_changed")


def test_zone_change_valid_passes() -> None:
    """合法 zone_change（enabled bool / hp_threshold 0.3 / targets 非空 string[] / timing 枚举）→ 通过。"""
    rep = _check(_legal_dungeons())
    assert not _errs(rep, "zc_")
    assert rep.ok


# ---------------------------------------------------------------------------
# 7. 补充：safe_zone / first_clear / explore 语义 / report 合并 / Def 访问器
# ---------------------------------------------------------------------------
def test_safe_zone_dangling_blocked() -> None:
    """safe_zone 不在 dungeon.maps → 拦截 R-4 safe_zone_ref（硬拦）。"""
    rep = _check([_base_boss(safe_zone="molten_ghost")])
    errs = _errs(rep, "safe_zone_ref")
    assert len(errs) == 1 and errs[0].detail.get("ref") == "molten_ghost"


def test_first_clear_malformed_item_blocked() -> None:
    """drops.first_clear.items[].item 缺失/空 → 拦截 R-1 first_clear_item（2a1d §2.4 结构）。"""
    drops = {
        "first_clear": {"items": [{"count": 1}], "title": "T", "codex": []},
    }
    rep = _check([_base_boss(drops=drops)])
    assert _errs(rep, "first_clear_item")


def test_first_clear_type_blocked() -> None:
    """drops.first_clear 非对象（list）→ 拦截 R-1 first_clear_type。"""
    rep = _check([_base_boss(drops={"first_clear": [{"item": "x"}]})])
    assert _errs(rep, "first_clear_type")


def test_first_clear_items_required_blocked() -> None:
    """drops.first_clear 缺 items 键 → 拦截 R-5 first_clear_items_required。"""
    rep = _check([_base_boss(drops={"first_clear": {"title": "T"}})])
    assert _errs(rep, "first_clear_items_required")


def test_explore_with_boss_notes_not_blocking() -> None:
    """探索版误配 boss → N1 提示（2a3 R9 探索版无 BOSS），不红拦。"""
    rep = _check([_base_explore(boss="ember_drake")])
    assert rep.ok
    assert _notes(rep, "explore_has_boss")


def test_report_merging_preserves_prior_errors() -> None:
    """既有 report（如 check_pack 产物）传入 → 新报告合并保留既有错误 + 追加 dungeon 错误。"""
    prior = ValidationReport(
        errors=(PackError("items", "items.0", "R-5", dict(rule="prior_error")),),
        warnings=(),
        notes=(PackNote("items", "items.0", "N-1", dict(rule="prior_note")),),
    )
    rep = validate_dungeons({"dungeon": [_base_boss(type="raid")]}, prior)
    assert any(e.detail.get("rule") == "prior_error" for e in rep.errors)
    assert _errs(rep, "type_enum")
    assert any(n.detail.get("rule") == "prior_note" for n in rep.notes)


def test_dungeon_def_accessors_both_types() -> None:
    """DungeonDef 11 字段访问器读取（boss 版全字段 / explore 版 entry_item:null + entry_limit:0）。"""
    boss = cast(DungeonDef, DungeonDef.from_entry(_base_boss()))
    assert boss.id == "molten_dungeon_boss"
    assert boss.name == "熔岩洞窟·讨伐"
    assert boss.type == "boss"
    assert boss.entry_item == "potion"
    assert boss.entry_limit == 3.0
    assert boss.maps == MOCK_MAP_IDS
    assert boss.boss_room == "lava_tunnel"
    assert boss.boss == "ember_drake"
    assert boss.subquests == ()
    assert boss.safe_zone == "rubble_field"
    first_clear = boss.drops.get("first_clear")
    assert isinstance(first_clear, Mapping) and first_clear["title"] == "熔岩征服者"

    explore = cast(DungeonDef, DungeonDef.from_entry(_base_explore()))
    assert explore.id == "molten_dungeon_explore"
    assert explore.type == "explore"
    assert explore.entry_item is None
    assert explore.entry_limit == 0.0
    assert explore.maps == MOCK_MAP_IDS
    assert explore.boss is None and explore.boss_room is None
    assert len(explore.subquests) == 3
    assert explore.safe_zone == "rubble_field"
    explore_fc = explore.drops.get("first_clear")
    assert isinstance(explore_fc, Mapping) and explore_fc["codex"] == ["item:first_clear_badge"]
