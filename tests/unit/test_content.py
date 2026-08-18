"""content 管线单测（细化_3e_loader校验接线.md#TC-01~30 / 细化_3a#TC-09/10/12/22 / MIG-1）。

覆盖：红拦 R-1~R-5、黄提示 Y-1~Y-7、默认放行 §2.3、热重载回退与增量（3e2）、
fixtures 四件套行为（细化_5d TC-5d-13）。
零 NoneBot；全部 tmp_path 建包，不触碰生产存档。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pytest

from qbot_rpg.content.hot_reload import HotReloadWatcher
from qbot_rpg.content.loader import PackLoadError, build_pack
from qbot_rpg.content.validator import check_formula
from qbot_rpg.content.models import PackError

FIX_DIR = Path(__file__).resolve().parents[1] / "fixtures"


# ---------------------------------------------------------------------------
# fixtures 四件套结构（细化_5d TC-5d-13）
# ---------------------------------------------------------------------------
def test_fixtures_four_packs_ok(packs_dir: Path) -> None:
    """细化_5d#TC-5d-13：packs/ 有且仅有四包，且各带 README 说明破坏点。"""
    subdirs = sorted(d.name for d in packs_dir.iterdir() if d.is_dir())
    assert subdirs == ["badref", "legal", "missing_mod", "old_schema"], (
        f"packs/ 目录必须恰好四包，实际 {subdirs}"
    )
    for name in ("legal", "badref", "missing_mod", "old_schema"):
        readme = packs_dir / name / "README.md"
        assert readme.is_file(), f"{name}/README.md 必须存在（TC-5d-13 每包带 README）"
        assert "破坏点" in readme.read_text(encoding="utf-8"), (
            f"{name}/README.md 必须说明破坏点"
        )


# ---------------------------------------------------------------------------
# 合法包：全绿基线（3e#TC-30 / 3a#TC-09/22）
# ---------------------------------------------------------------------------
def test_legal_pack_full_green(legal_pack_dir: Path) -> None:
    """细化_3e#TC-30 / 3a#TC-09：合法包 validator 全绿 + registry 全量注册且 ID 唯一。"""
    pack, changed = build_pack(legal_pack_dir)
    assert changed  # 首载即全模块变更
    assert pack.report.ok, f"合法包不应有红拦：{pack.report.errors}"
    assert not pack.report.warnings, f"合法包应为零黄提示：{pack.report.warnings}"
    assert pack.registry.generation == 1
    assert set(pack.registry.all_ids("item")) == {"potion", "hi_potion"}
    assert set(pack.registry.all_ids("effect")) == {"heal_small", "power_slash", "rage_up"}
    assert set(pack.registry.all_ids("enemy")) == {"slime", "forest_wolf", "oak_golem"}
    # ID 唯一（效果家族三表统一命名空间）：max_stack 不重复
    assert pack.registry.resolve("heal_small", "effect") is not None
    assert pack.registry.resolve("potion", "item") is not None
    # formula 模块也能注册
    assert pack.registry.resolve("damage_base", "formula") is not None


def test_legal_manifest_registration_order(legal_pack_dir: Path) -> None:
    """细化_3e §1.3：注册顺序 effect 家族先注册 —— registry 含 status/mark。"""
    pack, _ = build_pack(legal_pack_dir)
    assert pack.registry.resolve("regen", "status") is not None
    assert pack.registry.resolve("berserk", "status") is not None
    assert pack.registry.resolve("fire_mark", "mark") is not None


# ---------------------------------------------------------------------------
# 坏引用包：R-4 红拦 + registry 不污染（3e#TC-05 / 3a#TC-10 / 5d§5.1）
# ---------------------------------------------------------------------------
def test_badref_pack_blocked(badref_pack_dir: Path) -> None:
    """细化_3e#TC-05 / 3a#TC-10：坏引用 → PackLoadError(R-4)，定位到 items.1.effects.0。"""
    with pytest.raises(PackLoadError) as ei:
        build_pack(badref_pack_dir)
    errs = ei.value.errors
    assert any(e.kind == "R-4" and e.detail.get("ref") == "ghost_effect" for e in errs), (
        f"应含 R-4 ref_missing(ghost_effect)，实际 {[(e.kind, dict(e.detail)) for e in errs]}"
    )
    hit = next(e for e in errs if e.kind == "R-4" and e.detail.get("ref") == "ghost_effect")
    assert hit.field == "items.1.effects.0", f"错误应精确定位，实际 {hit.field}"


# ---------------------------------------------------------------------------
# 红拦 R-1~R-5（3e#TC-01~08）
# ---------------------------------------------------------------------------
def _write_pack(tmp_path: Path, manifest: dict, modules: Dict[str, object]) -> Path:
    (tmp_path / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    for name, data in modules.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _manifest(modules: List[str]) -> dict:
    return {"name": "t", "version": "1.0.0", "schema_version": 1, "modules": modules}


def test_invalid_json_red_block(tmp_path: Path) -> None:
    """细化_3e#TC-01：items.json JSON 语法坏 → PackLoadError R-5 invalid_json。"""
    (tmp_path / "manifest.json").write_text(json.dumps(_manifest(["items"])), encoding="utf-8")
    (tmp_path / "items.json").write_text('{"id": "potion", broken', encoding="utf-8")
    with pytest.raises(PackLoadError) as ei:
        build_pack(tmp_path)
    assert any(e.kind == "R-5" and e.detail.get("rule") == "invalid_json" for e in ei.value.errors)


def test_type_error_red(tmp_path: Path) -> None:
    """细化_3e#TC-02：数字填成文字 → R-1 type；字符串数字也算 R-1（【规则】L153）。"""
    p = _write_pack(tmp_path, _manifest(["effects"]), {"effects": [{"id": "e", "power": "很贵"}]})
    with pytest.raises(PackLoadError) as ei:
        build_pack(p)
    kinds = {e.kind for e in ei.value.errors}
    assert "R-1" in kinds, f"应为 R-1，实际 {kinds}"


def test_negative_red(tmp_path: Path) -> None:
    """细化_3e#TC-03：enemies[].hp=-100 → R-2 negative。"""
    p = _write_pack(
        tmp_path, _manifest(["enemies"]),
        {"enemies": [{"id": "slime", "name": "史莱姆", "hp": -100}]},
    )
    with pytest.raises(PackLoadError) as ei:
        build_pack(p)
    kinds = {e.kind for e in ei.value.errors}
    assert "R-2" in kinds, f"应为 R-2，实际 {kinds}"


def test_nan_red(tmp_path: Path) -> None:
    """细化_3e#TC-04：NaN → R-3 not_a_number。"""
    p = _write_pack(
        tmp_path, _manifest(["effects"]),
        {"effects": [{"id": "e", "name": "e", "power": float("nan")}]},
    )
    with pytest.raises(PackLoadError) as ei:
        build_pack(p)
    kinds = {e.kind for e in ei.value.errors}
    assert "R-3" in kinds, f"应为 R-3，实际 {kinds}"


def test_required_missing_red(tmp_path: Path) -> None:
    """细化_3e#TC-06：manifest 缺 modules → R-5 required_missing。"""
    (tmp_path / "manifest.json").write_text(
        json.dumps({"name": "t", "version": "1.0.0", "schema_version": 1}), encoding="utf-8"
    )
    with pytest.raises(PackLoadError) as ei:
        build_pack(tmp_path)
    assert any(e.kind == "R-5" and e.detail.get("rule") == "required_missing" for e in ei.value.errors)


def test_dead_range_red(tmp_path: Path) -> None:
    """细化_3e#TC-07：maps 区域 min>max 死配置 → R-5 dead_range。"""
    p = _write_pack(
        tmp_path, _manifest(["maps"]),
        {"maps": [{"id": "zone", "name": "区域", "min": 10, "max": 5}]},
    )
    with pytest.raises(PackLoadError) as ei:
        build_pack(p)
    assert any(e.kind == "R-5" and e.detail.get("rule") == "dead_range" for e in ei.value.errors)


def test_mutex_cycle_red(tmp_path: Path) -> None:
    """细化_3e#TC-08：装备部位互斥三件成环 → R-5 slot_mutex_cycle。"""
    p = _write_pack(
        tmp_path, _manifest(["equipment"]),
        {
            "equipment": [
                {"id": "a", "name": "A", "slot": "weapon", "excludes": ["shield"]},
                {"id": "b", "name": "B", "slot": "shield", "excludes": ["hand"]},
                {"id": "c", "name": "C", "slot": "hand", "excludes": ["weapon"]},
            ]
        },
    )
    with pytest.raises(PackLoadError) as ei:
        build_pack(p)
    assert any(e.kind == "R-5" and e.detail.get("rule") == "slot_mutex_cycle" for e in ei.value.errors)


def test_blocked_collects_all_errors(tmp_path: Path) -> None:
    """细化_3e#TC-10：一处包含 3 处红拦 → 一次抛错携带 3 条 errors（D-01 一次给全）。"""
    p = _write_pack(
        tmp_path, _manifest(["items", "enemies"]),
        {
            "items": [
                {"id": "a", "name": "A", "effects": ["ghost"]},       # R-4
                {"id": "a", "name": "dup", "price": -1},              # id 重复 R-5 + 负数 R-2
            ],
            "enemies": [{"id": "slime", "name": "史莱姆", "hp": -5}],  # R-2
        },
    )
    with pytest.raises(PackLoadError) as ei:
        build_pack(p)
    assert len(ei.value.errors) >= 3, f"应一次给全 ≥3 条错误，实际 {len(ei.value.errors)}"


def test_all_or_none_not_mounted(tmp_path: Path) -> None:
    """细化_3e#TC-11：整包含红拦 → 0 个 ID 注册（D-02 半挂载禁止，build_pack 不返回 Pack）。"""
    p = _write_pack(tmp_path, _manifest(["items"]), {"items": [{"id": "x", "effects": ["none"]}]})
    with pytest.raises(PackLoadError):
        build_pack(p)


# ---------------------------------------------------------------------------
# 黄提示 Y-1/Y-2/Y-4/Y-6/Y-7（3e#TC-12/13/15/17/18） + 默认放行 §2.3
# ---------------------------------------------------------------------------
def test_y1_out_of_range_yellow(tmp_path: Path) -> None:
    """细化_3e#TC-12：HP 999999 超出常见区间 → 加载成功 + Y-1 黄提示。"""
    p = _write_pack(
        tmp_path, _manifest(["enemies"]),
        {"enemies": [{"id": "big", "name": "极大", "hp": 999999}]},
    )
    pack, _ = build_pack(p)
    assert pack.report.ok
    assert any(w.kind == "Y-1" and w.detail.get("rule") == "out_of_common_range"
               for w in pack.report.warnings), f"应有 Y-1，实际 {[w.kind for w in pack.report.warnings]}"
    assert pack.registry.resolve("big", "enemy") is not None


def test_y2_probability_yellow(tmp_path: Path) -> None:
    """细化_3e#TC-13：掉落率 0.001 极低 → 加载成功 + Y-2 黄提示。"""
    p = _write_pack(
        tmp_path, _manifest(["enemies"]),
        {"enemies": [{"id": "rare", "name": "稀有", "hp": 10, "drop_rate": 0.001}]},
    )
    pack, _ = build_pack(p)
    assert pack.report.ok
    assert any(w.kind == "Y-2" for w in pack.report.warnings)


def test_y4_zero_unlimited(tmp_path: Path) -> None:
    """细化_3e#TC-15：max_stack=0 → 加载成功 + Y-4 黄提示（0=不限）。"""
    p = _write_pack(
        tmp_path, _manifest(["marks"]),
        {"marks": [{"id": "m", "name": "印", "type": "mark", "max_stack": 0}]},
    )
    pack, _ = build_pack(p)
    assert pack.report.ok
    assert any(w.kind == "Y-4" and w.detail.get("rule") == "zero_unlimited"
               for w in pack.report.warnings)


def test_missing_mod_pack_y6(missing_mod_pack_dir: Path) -> None:
    """细化_3e#TC-17 / 3a#TC-12：声明缺失 statuses → Y-6 不拒绝；未声明 npc 不加载。"""
    pack, _ = build_pack(missing_mod_pack_dir)
    assert pack.report.ok
    assert any(
        w.kind == "Y-6" and w.detail.get("rule") == "module_missing"
        and w.detail.get("module") == "statuses"
        for w in pack.report.warnings
    ), f"应有 Y-6(statuses)，实际 {[dict(w.detail) for w in pack.report.warnings]}"
    # 未声明文件不加载（3e#TC-09）：npc.json 存在但 manifest 未声明 → 不注册
    assert pack.registry.resolve("villager", "npc") is None
    assert pack.registry.resolve("potion", "item") is not None


def test_old_schema_tolerated(old_schema_pack_dir: Path) -> None:
    """细化_5d§5.1 / 细化_3e §2.3 / MIG-1：旧 schema 包缺补默认/多忽略，不红拦。"""
    pack, _ = build_pack(old_schema_pack_dir)
    assert pack.report.ok, f"旧 schema 包不应红拦：{pack.report.errors}"
    # 缺字段 → 默认（EnemyDef.hp 取 raw.get 缺失 → None）
    old_enemy = pack.registry.resolve("old_slime", "enemy")
    assert old_enemy is not None
    assert old_enemy.hp is None  # 缺补默认：无 hp 字段 → 默认 None（业务侧按 0 兜底）
    # 多忽略：x_future_field 未知字段默认放行（§2.3）
    assert pack.registry.resolve("old_potion", "item") is not None


def test_unknown_x_field_passthrough(tmp_path: Path) -> None:
    """细化_3e#TC-19 / §2.3：x_ 自定义字段放行；引用不存在的 x_ 字段按 R-4 查。"""
    p = _write_pack(
        tmp_path, _manifest(["effects"]),
        {"effects": [{"id": "e", "name": "e", "x_my_field": "任意值"}]},
    )
    pack, _ = build_pack(p)
    assert pack.report.ok
    assert pack.registry.resolve("e", "effect") is not None


def test_y7_unregistered_stat_key(tmp_path: Path) -> None:
    """细化_3e#TC-18：stat 引用未注册键空间 → 加载成功 + Y-7 黄提示（不红拦）。

    默认字段元数据表未声明任何 ref_stat 字段，故用自定义 meta 把 enemies.key_ref
    声明为 stat 引用（校验资源由表注入，不点改实现 —— 正是 3f 可达性钩子同款机制）。
    """
    from qbot_rpg.content.models import FieldMeta, ModuleMeta, FieldMetaTable  # noqa: PLC0415
    from qbot_rpg.content.field_meta import default_field_meta_table  # noqa: PLC0415

    base = default_field_meta_table()
    enemies_meta = base.module("enemies")
    fields = dict(enemies_meta.fields)
    fields["key_ref"] = FieldMeta(type="ref", ref_target="stat")
    meta = FieldMetaTable(
        modules={**base.modules, "enemies": ModuleMeta(
            entry_type="list", fields=fields, kind="enemy", namespace="enemy_lib",
        )},
        namespaces=base.namespaces,
    )
    p = _write_pack(
        tmp_path, _manifest(["stats", "enemies"]),
        {
            "stats": {"atk": {"name": "攻击", "type": "combat", "base": 10},
                      "lck": {"name": "幸运", "type": "combat", "base": 10}},
            "enemies": [{"id": "slime", "name": "史莱姆", "key_ref": "nostalgia_points"}],
        },
    )
    pack, _ = build_pack(p, meta=meta)
    assert pack.report.ok, f"未注册 stat 键应仅黄提示，实际红拦：{pack.report.errors}"
    assert any(
        w.kind == "Y-7" and w.detail.get("rule") == "stat_key_unregistered"
        and w.detail.get("ref") == "nostalgia_points"
        for w in pack.report.warnings
    ), f"应有 Y-7，实际 {[(w.kind, dict(w.detail)) for w in pack.report.warnings]}"


# ---------------------------------------------------------------------------
# formula 安全例外（3e#TC-29 / §3.3）
# ---------------------------------------------------------------------------
def test_formula_blacklist_red(tmp_path: Path) -> None:
    """细化_3e#TC-29：formula 含 eval / new Function → R-5 formula_safety（不受只建议限制覆盖）。"""
    for bad in ("eval(1)", "new Function('x')", "globalThis.process.exit()"):
        p = _write_pack(tmp_path, _manifest(["formula"]), {"formula": {"danger": bad}})
        with pytest.raises(PackLoadError) as ei:
            build_pack(p)
        assert any(e.kind == "R-5" and e.detail.get("rule") == "formula_safety"
                   for e in ei.value.errors), f"{bad!r} 应红拦 formula_safety"


def test_formula_too_long_red(tmp_path: Path) -> None:
    """细化_3e §3.3 L449：公式长度 >4KB → 红拦。"""
    long_formula = "x + " + "1 + " * 3000
    hit = check_formula(long_formula)
    assert hit is not None and hit["rule"] == "formula_too_long"


def test_formula_blacklist_hidden_in_string_ok() -> None:
    """细化_3e §3.3：黑名单词藏在字符串字面量里不应误报（eval 作为普通词）。"""
    assert check_formula("'eval' + x") is None


# ---------------------------------------------------------------------------
# 热重载（3e2 TRG 系列 / 3a#TC-13/14 / 3e#TC-22/23）
# ---------------------------------------------------------------------------
def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


async def test_hot_reload_success_incremental(tmp_path: Path) -> None:
    """细化_3e2 TRG-3 / 3e#TC-22/24：改单文件 → ok 且仅该模块变更（mtime 增量）。"""
    _write_json(tmp_path / "manifest.json", _manifest(["items", "effects"]))
    _write_json(tmp_path / "items.json", [{"id": "p1", "name": "药水", "price": 100}])
    _write_json(tmp_path / "effects.json", [{"id": "heal", "name": "小回复", "power": 50}])
    watcher = HotReloadWatcher(tmp_path, poll_interval_s=0.05, max_consecutive_failures=3)
    first = await watcher.start()
    assert first.ok, first.note
    assert not first.restored

    _write_json(tmp_path / "items.json", [{"id": "p1", "name": "药水", "price": 150}])
    result = await watcher.reload()
    assert result.ok, f"重载失败: {result.note}"
    assert result.changed_modules == ("items",), f"应仅 items 重载，实际 {result.changed_modules}"
    assert result.generation == 2
    assert watcher.registry.resolve("p1", "item").get("price") == 150


async def test_hot_reload_failure_rollback(tmp_path: Path) -> None:
    """细化_3e#TC-23 / 3a#TC-13 / 5d§5.1：非法 JSON → 回退上一份快照，服务不崩，无半套配置。"""
    _write_json(tmp_path / "manifest.json", _manifest(["items"]))
    _write_json(tmp_path / "items.json", [{"id": "p1", "name": "药水", "price": 100}])
    watcher = HotReloadWatcher(tmp_path, poll_interval_s=0.05, max_consecutive_failures=3)
    first = await watcher.start()
    assert first.ok
    before_ids = frozenset(watcher.registry.all_ids("item"))

    (tmp_path / "items.json").write_text('{"id": "broken",', encoding="utf-8")  # 非法 JSON
    result = await watcher.reload()
    assert not result.ok
    assert result.restored is True, "失败必须回退"
    assert any(e.kind == "R-5" for e in result.errors)
    after_ids = frozenset(watcher.registry.all_ids("item"))
    assert after_ids == before_ids, "registry 必须保持加载前状态（无半套配置）"
    assert watcher.consecutive_failures == 1


async def test_hot_reload_consecutive_failure_pauses(tmp_path: Path) -> None:
    """细化_3e2 BLK-5：连续失败 ≥3 → 自动暂停轮询转手动。"""
    _write_json(tmp_path / "manifest.json", _manifest(["items"]))
    _write_json(tmp_path / "items.json", [{"id": "p1", "name": "药水", "price": 100}])
    watcher = HotReloadWatcher(tmp_path, poll_interval_s=0.05, max_consecutive_failures=3)
    await watcher.start()
    (tmp_path / "items.json").write_text('{bad json', encoding="utf-8")
    r1 = await watcher.reload()
    r2 = await watcher.reload()
    r3 = await watcher.reload()
    assert not r1.ok and not r2.ok and not r3.ok
    assert watcher.paused is True, "连续失败达阈值应暂停轮询"
    assert watcher.consecutive_failures == 3
    # 文件恢复合法 → 手动重载成功 → 取消暂停（BLK-5 恢复条件）
    _write_json(tmp_path / "items.json", [{"id": "p1", "name": "药水", "price": 80}])
    r4 = await watcher.reload()
    assert r4.ok, f"恢复后重载应成功: {r4.note}"
    assert watcher.paused is False, "重载成功后应恢复自动轮询"


def test_parse_cache_incremental(tmp_path: Path) -> None:
    """细化_3e2 TRG-3：parse_cache 复用未变动模块解析结果。"""
    _write_json(tmp_path / "manifest.json", _manifest(["items", "effects"]))
    _write_json(tmp_path / "items.json", [{"id": "p1", "name": "药水", "price": 100}])
    _write_json(tmp_path / "effects.json", [{"id": "heal", "name": "小回复", "power": 50}])
    cache: dict = {}
    _, ch1 = build_pack(tmp_path, parse_cache=cache)
    assert set(ch1) == {"items", "effects"}
    _write_json(tmp_path / "items.json", [{"id": "p1", "name": "药水", "price": 200}])
    pack, ch2 = build_pack(tmp_path, parse_cache=cache, generation=2)
    assert ch2 == ("items",), f"增量应仅 items，实际 {ch2}"
    assert pack.registry.resolve("p1", "item").get("price") == 200
