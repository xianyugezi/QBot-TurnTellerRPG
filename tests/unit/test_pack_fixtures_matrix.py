"""M6 批4·路B：D4 validator 四件套矩阵 + verify_m0 修正 + 五档数据包契约测试。

依据：
  - D4《细化_M6_内容包冒烟》§三（SMK-12~15 四件套矩阵）/ §四（SMK-16 归档 F-01~05）/ §五（PCK-01~12）
  - 细化_5d §5.1（L200-202 坏包矩阵）/ 细化_3e TC-30 / 3a TC-09/22 / 框架 §4.3 + §15（content/ 五目录）
  - 承载范本：tests/unit/test_content.py L286-309（missing_mod/old_schema 断言）
  - verify_m0 修正验证：TC-SMK-12（importlib 导入 scripts/verify/verify_m0.py 跑 _validate_fixtures）

零 NoneBot；全部只读 tests/fixtures/packs 四件套 + content/ 五档包，不触碰生产存档。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from qbot_rpg.content.loader import PackLoadError, build_pack

REPO = Path(__file__).resolve().parents[2]
CONTENT_DIR = REPO / "content"
PACKS_DIR = REPO / "tests" / "fixtures" / "packs"
FIVE_TIERS = ("demo_blank", "demo_lv15", "demo_lv30", "demo_lv45", "demo_full")


# ---------------------------------------------------------------------------
# TC-SMK-08：四件套 legal 全绿（0 红 0 黄 + registry 全注册）
# ---------------------------------------------------------------------------
def test_smk08_legal_full_green(legal_pack_dir: Path) -> None:
    """细化_M6 D4#TC-SMK-08 / SMK-12：legal 全过（0 红 0 黄 + registry 全量注册）。"""
    pack, _ = build_pack(legal_pack_dir)
    assert pack.report.ok, f"legal 不应红拦：{pack.report.errors}"
    assert pack.report.count_errors == 0
    assert pack.report.count_warnings == 0, f"legal 应为零黄：{pack.report.warnings}"
    # registry 全量注册且 ID 唯一（SMK-12）
    assert set(pack.registry.all_ids("enemy")) == {
        "rock_weasel", "stone_skink", "ember_drake", "training_dummy",
    }
    assert pack.registry.resolve("potion", "item") is not None
    assert pack.registry.resolve("heal_small", "effect") is not None


# ---------------------------------------------------------------------------
# TC-SMK-09：四件套 badref 红拦（PackLoadError + registry 未污染）
# ---------------------------------------------------------------------------
def test_smk09_badref_red_blocked(badref_pack_dir: Path, legal_pack_dir: Path) -> None:
    """细化_M6 D4#TC-SMK-09 / SMK-12：badref 红拦（PackLoadError + registry 未被污染）。"""
    with pytest.raises(PackLoadError) as ei:
        build_pack(badref_pack_dir)
    errs = ei.value.errors
    assert any(e.kind == "R-4" for e in errs), f"应含 R-4 引用缺失：{[(e.kind, dict(e.detail)) for e in errs]}"
    # registry 未被污染（5d L201 / 原子快照替换）：红拦后 legal 重载仍全绿
    pack, _ = build_pack(legal_pack_dir)
    assert pack.report.ok
    assert pack.registry.resolve("potion", "item") is not None


# ---------------------------------------------------------------------------
# TC-SMK-10：四件套 missing_mod 软放行（加载成功 + Y-6(statuses) + 未声明不加载）
# ---------------------------------------------------------------------------
def test_smk10_missing_mod_soft_allow(missing_mod_pack_dir: Path) -> None:
    """细化_M6 D4#TC-SMK-10 / SMK-13：missing_mod 软放行——加载成功 + Y-6 黄提示 + 未声明不加载。"""
    pack, _ = build_pack(missing_mod_pack_dir)
    assert pack.report.ok, f"missing_mod 不应红拦（软放行）：{pack.report.errors}"
    assert any(
        w.kind == "Y-6" and w.detail.get("rule") == "module_missing"
        and w.detail.get("module") == "statuses"
        for w in pack.report.warnings
    ), f"应有 Y-6(statuses)：{[dict(w.detail) for w in pack.report.warnings]}"
    # 未声明文件不加载（3e#TC-09）：npc.json 存在但 manifest 未声明 → 不注册
    assert pack.registry.resolve("villager", "npc") is None
    # 挂载（SMK-12/13）：items.potion 可 resolve
    assert pack.registry.resolve("potion", "item") is not None


# ---------------------------------------------------------------------------
# TC-SMK-11：四件套 old_schema 容忍加载（不红拦 + 缺补默认 + 多忽略）
# ---------------------------------------------------------------------------
def test_smk11_old_schema_tolerated(old_schema_pack_dir: Path) -> None:
    """细化_M6 D4#TC-SMK-11 / SMK-14：old_schema 容忍加载——缺补默认 + 多忽略，不红拦。"""
    pack, _ = build_pack(old_schema_pack_dir)
    assert pack.report.ok, f"old_schema 不应红拦（容忍加载）：{pack.report.errors}"
    # 缺补默认：EnemyDef.hp 取 raw.get 缺失 → None（SMK-14）
    old_enemy = pack.registry.resolve("old_slime", "enemy")
    assert old_enemy is not None
    assert old_enemy.hp is None
    # 多忽略：x_future_field 未知字段默认放行（3e §2.3）
    assert pack.registry.resolve("old_potion", "item") is not None


# ---------------------------------------------------------------------------
# TC-SMK-12：verify_m0 修正生效（missing_mod 分支产生真实断言，不再双分支皆过）
# ---------------------------------------------------------------------------
def _import_verify_m0():
    spec = importlib.util.spec_from_file_location("verify_m0", REPO / "scripts" / "verify" / "verify_m0.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_smk12_verify_m0_missing_mod_real_assertion() -> None:
    """细化_M6 D4#TC-SMK-12 / SMK-13：verify_m0 修正生效。

    _validate_fixtures() 带真实断言（任一失败即抛 AssertionError）；能返回 notes
    即证明 missing_mod 分支的「加载成功 + Y-6(statuses) + 未声明不加载」断言通过。
    """
    mod = _import_verify_m0()
    # 修正落盘自检：docstring 不再把 missing_mod 误标为「必须被红拦」，改标「软放行」
    doc = mod._validate_fixtures.__doc__ or ""
    assert "软放行" in doc and "missing_mod" in doc
    assert "badref / missing_mod：必须被红拦" not in doc, "SMK-13 应修正误标 docstring"
    # 真实断言执行：抛错即失败；返回 notes 且 missing_mod 分支带 Y-6 记录
    notes = mod._validate_fixtures()
    assert any("missing_mod" in n and "Y-6" in n for n in notes), (
        f"missing_mod 分支应产生真实断言记录（Y-6），实际 notes={notes}"
    )


# ---------------------------------------------------------------------------
# TC-PCK-01：五档包目录齐全 + TC-PCK-07：四件套分离
# ---------------------------------------------------------------------------
def test_pck01_five_tiers_dirs_exist() -> None:
    """细化_M6 D4#TC-PCK-01 / PCK-01/02：content/ 五档目录齐全（F-08 命名）。"""
    dirs = sorted(d.name for d in CONTENT_DIR.iterdir() if d.is_dir())
    assert set(FIVE_TIERS) <= set(dirs), f"content/ 五档演示包须齐全：{dirs}"


def test_pck07_four_packs_separated(packs_dir: Path) -> None:
    """细化_M6 D4#TC-PCK-03 / PCK-07 + 5d L200：fixtures 仍四件套，五包不落 fixtures。"""
    subdirs = sorted(d.name for d in packs_dir.iterdir() if d.is_dir())
    assert subdirs == ["badref", "legal", "missing_mod", "old_schema"]
    assert not any((packs_dir / t).exists() for t in FIVE_TIERS), "五档包不得落 fixtures"


# ---------------------------------------------------------------------------
# TC-PCK-02 / PCK-03 / PCK-04：逐档 validator 全绿 + manifest 与磁盘一一对应
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("tier", FIVE_TIERS)
def test_pck02_pck03_each_tier_green_and_manifest_matches_disk(tier: str) -> None:
    """细化_M6 D4#TC-PCK-02/04 + PCK-03/04：逐档 load 全绿（0 红，黄记录在案）+ manifest↔磁盘一一对应。"""
    d = CONTENT_DIR / tier
    assert d.is_dir(), f"{tier} 目录缺失"
    # PCK-03：manifest.modules 与磁盘 JSON 文件一一对应（无缺失无未声明）
    manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    declared = set(manifest["modules"])
    on_disk = {p.stem for p in d.iterdir()
               if p.is_file() and p.suffix == ".json" and p.name != "manifest.json"}
    assert declared == on_disk, (
        f"{tier} manifest 声明与磁盘不一致：仅声明={sorted(declared - on_disk)}"
        f" 仅磁盘={sorted(on_disk - declared)}"
    )
    # PCK-04：逐档 validator 全绿（0 红拦；黄提示记录在案可接受）
    pack, _ = build_pack(d)
    assert pack.report.ok, f"{tier} 不应红拦：{pack.report.errors}"
    assert pack.report.count_errors == 0
    # 黄记录在案（规则 L426）：warnings 打印供归档（此处仅断言可枚举，不阻断）
    print(f"{tier}: warnings={[w.kind for w in pack.report.warnings]}")


# ---------------------------------------------------------------------------
# TC-PCK-05/PCK-06：模块集递增 + demo_blank 空包语义（无怪物只装配）
# ---------------------------------------------------------------------------
def test_pck05_module_sets_increasing() -> None:
    """细化_M6 D4 PCK-05：五档模块集单调递增（blank ⊂ lv15 ⊂ lv30 ⊂ lv45 ⊆ full）。"""
    sets = []
    for tier in FIVE_TIERS:
        m = json.loads((CONTENT_DIR / tier / "manifest.json").read_text(encoding="utf-8"))
        sets.append(set(m["modules"]))
    # 模块集单调不减（lv45 已含全 16 模块；lv45→full 的内容递增由 registry 增长断言承接）
    for prev, cur in zip(sets, sets[1:]):
        assert prev <= cur, f"模块集应单调递增：{sorted(prev)} !< {sorted(cur)}"
    assert sets[0] < sets[1] < sets[2] < sets[3], "前四档模块集应严格递增"
    # demo_blank = 最小可玩模块集（PCK-05）：含 manifest/settings/stats/formula
    assert {"settings", "stats", "formula"} <= sets[0]


def test_pck06_demo_blank_no_battle() -> None:
    """细化_M6 D4#TC-PCK-06 / PCK-06：demo_blank 无怪物 → 不跑战斗，只装配 + registry 成功。"""
    pack, _ = build_pack(CONTENT_DIR / "demo_blank")
    assert pack.report.ok
    assert set(pack.registry.all_ids("enemy")) == set(), "demo_blank 无怪物（PCK-06）"
    # 装配成功：最小可玩表已挂载
    assert pack.registry.resolve("potion", "item") is not None
    assert pack.registry.resolve("heal_small", "effect") is not None
    assert pack.registry.resolve("damage_base", "formula") is not None


def test_pck05_registry_growth_across_tiers() -> None:
    """细化_M6 D4 PCK-05/10：五档 registry 内容量逐档递增（怪物/行动/交互系统）。"""
    enemy_ids = {t: set(build_pack(CONTENT_DIR / t)[0].registry.all_ids("enemy"))
                 for t in FIVE_TIERS}
    assert enemy_ids["demo_blank"] == set()
    assert enemy_ids["demo_lv15"] == {"rock_weasel", "training_dummy"}
    assert enemy_ids["demo_lv30"] == {"rock_weasel", "stone_skink", "training_dummy"}
    assert enemy_ids["demo_lv45"] == {"rock_weasel", "stone_skink", "training_dummy"}
    assert enemy_ids["demo_full"] == {"rock_weasel", "stone_skink", "ember_drake", "training_dummy"}
    # PCK-10：至少 demo_lv15 起含合法可战斗怪（demo_blank 无怪只装配）
    assert enemy_ids["demo_lv15"] >= {"rock_weasel"}
    # 交互系统：lv45 起出现（M4 四模块），full 为全量
    lv45 = build_pack(CONTENT_DIR / "demo_lv45")[0].registry
    assert lv45.resolve("village_shop", "shop") is not None
    assert lv45.resolve("q_potion_supply", "quest") is not None
    full = build_pack(CONTENT_DIR / "demo_full")[0].registry
    assert full.resolve("ember_drake", "enemy") is not None
    assert full.resolve("molten_dungeon_boss", "dungeon") is not None


def test_pck11_demo_full_mirrors_legal(legal_pack_dir: Path) -> None:
    """细化_M6 D4 PCK-11：五档包以 legal 为共同基线——demo_full 怪物集 = legal 怪物集；
    物品集 demo_full ⊆ legal。

    【M8 收口调整 2026-08-29】legal 是校验器红拦零命中基线包，M8 数据层新增了炼金专项物品
    （装饰珠/触媒/炼金材料/炼金成品，覆盖 recipe/traits/slots 引用），而五档包（demo_*）是
    战斗向内容档、不含炼金层数据——严格相等不再成立，改为 demo_full ⊆ legal
    （legal 仍为共同基线超集，demo_full 全部物品在 legal 中可寻）。
    """
    legal, _ = build_pack(legal_pack_dir)
    full, _ = build_pack(CONTENT_DIR / "demo_full")
    assert set(full.registry.all_ids("enemy")) == set(legal.registry.all_ids("enemy"))
    assert set(full.registry.all_ids("item")) <= set(legal.registry.all_ids("item"))


# ---------------------------------------------------------------------------
# TC-SMK-14：归档落盘（docs/verify/m6_smoke.md 模板含 F-02~05 四段内容物）
# ---------------------------------------------------------------------------
def test_smk14_archive_template_sections() -> None:
    """细化_M6 D4#TC-SMK-14 / SMK-16：docs/verify/m6_smoke.md 存在且含 F-02~05 段。"""
    archive = REPO / "docs" / "verify" / "m6_smoke.md"
    assert archive.is_file(), "归档物 docs/verify/m6_smoke.md 缺失（SMK-16 模板）"
    text = archive.read_text(encoding="utf-8")
    for section in ("F-01", "F-02", "F-03", "F-04", "F-05"):
        assert section in text, f"归档模板缺 {section} 段（F-01~05 五段内容物）"
