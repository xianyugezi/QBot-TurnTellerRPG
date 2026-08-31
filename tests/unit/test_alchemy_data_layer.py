"""M8 批0 数据层收口验收：recipe/traits/proficiency/slots 四件套接线 + test_demo/legal 加载。

依据：
  - docs/m8_contract_数据与校验.md §六（四件套 field_meta/loader/validator/manifest）
    + §十 B1~B5（用户 5 项拍板）+ §一~§五（schema 字段表）
  - 批0 派工单（路0A 模型+校验器 / 路0B items·slots·settings 扩展 / 路0C fixtures）
  - 主 agent 收口接线（field_meta.py / loader.py / validator.py，2026-08-29）

验收口径：
  - test_demo（真实内容包）：build_pack 零红拦（黄提示放行）
  - legal（合法基线包）：零红拦 + 零黄（对齐 test_smk08 基线口径）
  - registry 表：recipe/trait/proficiency/slot 四表非空 + 关键 ID resolve
  - 铁律「数据表非空 + validator 生效」（实现层启动手册 §五.4）：空表即失败

零 NoneBot；只读 content/test_demo + tests/fixtures/packs/legal，不触碰生产存档。
"""
from __future__ import annotations

from pathlib import Path

from qbot_rpg.content.loader import build_pack

REPO = Path(__file__).resolve().parents[2]


def _build(rel: str):
    return build_pack(REPO / rel)


def _slots_raw(pack) -> list:
    """pack.modules['slots'] 类型收窄（slots 无 id 字段不注册 registry 表，
    运行期从 raw 解析——同 shop/quest modules_raw 口径）。"""
    raw = pack.modules["slots"]
    assert isinstance(raw, list)
    return raw


def test_m8_test_demo_pack_loads_green() -> None:
    """test_demo 加载零红拦 + M8 四表注册非空 + 关键 ID resolve。"""
    pack, _ = _build("content/test_demo")
    assert pack.report.ok, f"test_demo 不应红拦：{pack.report.errors}"
    assert pack.report.count_errors == 0
    # 数据表非空 + 条目数对齐 0C fixtures（recipe 15 / traits 8 / proficiency 2 / slots 4）
    # recipe/trait/proficiency 有 id 字段 → registry 表计数；slots 条目用 equip_id（无 id 字段，
    # 不注册进 registry 表，运行期从 pack.modules 解析——同 shop/quest modules_raw 口径）
    # proficiency=3：alchemy + forge + fishing（M9 批3 铸造 + M10 批5 钓鱼实例）
    # recipe 10→15：M10 批1 路1A 新增 5 条鱼饵配方（rcp_bait_*，T04 鱼饵体系）
    for kind, expect in (("recipe", 15), ("trait", 8), ("proficiency", 3)):
        ids = pack.registry.all_ids(kind)
        assert len(ids) == expect, f"kind={kind} 期望 {expect} 条，实得 {len(ids)}"
    assert len(_slots_raw(pack)) == 4, f"slots 期望 4 条，实得 {len(_slots_raw(pack))}"
    assert pack.registry.resolve("rcp_flame_bomb", "recipe") is not None
    assert pack.registry.resolve("trait_burn_boost", "trait") is not None
    assert pack.registry.resolve("alchemy", "proficiency") is not None
    assert pack.registry.resolve("fishing", "proficiency") is not None  # M10 批5 路5A
    assert any(s.get("equip_id") == "hunter_blade" for s in _slots_raw(pack))


def test_m8_legal_pack_loads_green() -> None:
    """legal 基线包零红零黄 + M8 表注册（对齐 test_smk08 口径）+ 既有数据未破坏。"""
    pack, _ = _build("tests/fixtures/packs/legal")
    assert pack.report.ok, f"legal 不应红拦：{pack.report.errors}"
    assert pack.report.count_errors == 0
    assert pack.report.count_warnings == 0, f"legal 应为零黄：{pack.report.warnings}"
    for kind, expect in (("recipe", 9), ("trait", 6), ("proficiency", 1)):
        ids = pack.registry.all_ids(kind)
        assert len(ids) == expect, f"legal kind={kind} 期望 {expect} 条，实得 {len(ids)}"
    assert len(_slots_raw(pack)) == 2, f"legal slots 期望 2 条，实得 {len(_slots_raw(pack))}"
    # 既有数据未破坏（test_smk08 依赖）
    assert pack.registry.resolve("potion", "item") is not None
    assert pack.registry.resolve("heal_small", "effect") is not None
    # legal slots 引用 equipment（iron_sword/iron_shield）→ validate_slots 跨 items∪equipment 通过
    assert any(s.get("equip_id") == "iron_sword" for s in _slots_raw(pack))
