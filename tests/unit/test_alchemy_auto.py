"""一键投料自动配平 + 批量单测（M8 批4·路2）——细化 TC-10~TC-14 引擎可承载部分。

文件：tests/unit/test_alchemy_auto.py
创建：2026-08-29
作者：Hermes 子agent-2（路2）
功能：AutoFeed 一键投料/批量引擎单测——自动配平成功（优先 element_req 达标，AUTO-02）、
      配平失败原子拒绝 + 差异（AUTO-03/TC-11）、批量平均品质（BATCH-02 复用 QualitySystem
      均值口径）、数量上限超限提示不拦截（BATCH-04/TC-14）、配平/复核差异 plan_shortfall
      （TC-11/TC-13 原子口径）。

依据：docs/细化/细化_2c4f_投料触媒与能量条.md 1.2/1.3 + 五（TC-10~14）+
      docs/m8_contract_核心机制.md 6.2（AUTO-01~03）/6.3（BATCH-01~05）+ 批0
      content/test_demo/recipe.json（materials [{id,count}] / element_req {元素:[{threshold}]}）/
      items.json（elements 贡献值）/settings.json alchemy（max_qty）。

覆盖矩阵（每条正例 + 负例，断言精确 plan/数值/文本；背包经 count_item hook 与
inventory 双口径注入）：
  TC-10 自动配平成功（优先 element_req 达标组合，mode=element_req；回落基础材料 mode=materials）
  TC-11 配平失败原子拒绝 + 差异「缺 火药×1」（AUTO-03，不部分入料）
  BATCH-02 批量平均品质（复用 QualitySystem.aggregate_quality/batch_tier 均值口径 + 空投料防御）
  TC-14 数量上限超限提示不拦截（BATCH-04 拍板⑤：默认 2147483647；超限标记不拦截）
  TC-13 原子口径 plan_shortfall（复核差异：缺量全拒 + 差异提示；全满足 ok）
  补充：持有封顶（A-2：plan 不超持有）、确定性排序、构造缺省兜底

测试风格对齐 tests/unit/test_quality.py：纯 pytest、零 NoneBot、断言具体 plan/数值/文本。
"""

from __future__ import annotations

from qbot_rpg.core.alchemy_auto import DEFAULT_MAX_QTY, AutoFeed
from qbot_rpg.core.quality import QualitySystem

# ---------------------------------------------------------------------------
# 场景构建工具
# ---------------------------------------------------------------------------

# 物品注册表：{id: {name, elements{元素: 贡献值}, quality}}
ITEMS = {
    "fire_gem": {"name": "火晶石", "elements": {"fire": 3}},
    "ice_gem": {"name": "冰晶", "elements": {"ice": 4}},
    "moon_grass": {"name": "月光草", "elements": {}},
    "base_a": {"name": "基础材料", "elements": {}},
    "huoyao": {"name": "火药", "elements": {"fire": 2}},
    "ember": {"name": "余烬", "elements": {"fire": 2}},
}


def _ctx(inventory: dict, *, count_item=None, settings=None) -> dict:
    """玩家上下文：items 注册表 + 背包（count_item hook 优先，缺省走 inventory）。"""
    ctx: dict = {"items": ITEMS}
    if count_item is not None:
        ctx["count_item"] = count_item
    if settings is not None:
        ctx["settings"] = settings
    ctx["inventory"] = inventory
    return ctx


def _flame_recipe() -> dict:
    """火焰弹配方（对齐 content 形态）：element_req 火 6 + 基础材料。"""
    return {
        "id": "rcp_flame_bomb",
        "materials": [{"id": "moon_grass", "count": 2}],
        "element_req": {"fire": [{"threshold": 6, "effect": "burn_dot"}]},
    }


# ---------------------------------------------------------------------------
# TC-10 一键投料自动配平成功（AUTO-02：优先 element_req 达标组合）
# ---------------------------------------------------------------------------
def test_tc10_auto_balance_prefers_element_req() -> None:
    """TC-10 正例：背包有火系材料 → 自动配平优先 element_req 达标组合（不回落到基础材料）。"""
    auto = AutoFeed()
    # 火晶石(fire:3)×3 → 火 6 ≥ 阈值 6；基础材料月光草×2 也在背包但不被选
    ctx = _ctx({"fire_gem": 3, "moon_grass": 5, "ice_gem": 2})
    r = auto.balance(ctx, _flame_recipe())
    assert r["ok"] is True
    assert r["mode"] == "element_req"
    assert r["plan"] == [("fire_gem", 2)]  # ceil(6/3)=2 火晶石即达标
    assert r["shortfall"] == []


def test_tc10_auto_balance_held_capped() -> None:
    """TC-10 工程补白 A-2：element_req 阶段计划数量不超持有（持有 1 火晶石 → 只取 1）。"""
    auto = AutoFeed()
    ctx = _ctx({"fire_gem": 1, "moon_grass": 5})
    r = auto.balance(ctx, _flame_recipe())
    # 火晶石×1（fire 3 < 6）无法达标 → 回落基础材料
    assert r["ok"] is True
    assert r["mode"] == "materials"
    assert r["plan"] == [("moon_grass", 2)]
    for item_id, cnt in r["plan"]:
        assert cnt <= ctx["inventory"][item_id]  # 持有封顶不超


def test_tc10_auto_balance_element_take_cover_need() -> None:
    """TC-10 补充：按元素缺口贪心，多次取料直到达标（余烬×3 → fire 6）。"""
    auto = AutoFeed()
    ctx = _ctx({"ember": 3, "moon_grass": 5})
    r = auto.balance(ctx, _flame_recipe())
    assert r["ok"] is True and r["mode"] == "element_req"
    assert r["plan"] == [("ember", 3)]


def test_tc10_auto_balance_no_element_req_uses_materials() -> None:
    """TC-10 负例：无 element_req 配方 → 直接按配方基础材料配平（配方清单序，确定性）。"""
    auto = AutoFeed()
    recipe = {"materials": [{"id": "moon_grass", "count": 2}, {"id": "base_a", "count": 1}]}
    ctx = _ctx({"moon_grass": 5, "base_a": 1})
    r = auto.balance(ctx, recipe)
    assert r["ok"] is True and r["mode"] == "materials"
    assert r["plan"] == [("moon_grass", 2), ("base_a", 1)]  # 配方 materials 顺序（确定性）


def test_tc10_auto_balance_deterministic() -> None:
    """TC-10 工程补白 A-1：同刻同参必同值（plan 确定性，多次调用结果一致）。"""
    auto = AutoFeed()
    ctx = _ctx({"ember": 3, "fire_gem": 2, "moon_grass": 5})
    a = auto.balance(ctx, _flame_recipe())
    b = auto.balance(ctx, _flame_recipe())
    assert a["plan"] == b["plan"]
    assert a == b


# ---------------------------------------------------------------------------
# TC-11 配平失败原子拒绝 + 差异（AUTO-03）
# ---------------------------------------------------------------------------
def test_tc11_balance_failure_atomic_reject_with_diff() -> None:
    """TC-11 正例：背包缺火药 → 全拒 + 差异「缺 火药×1」；不部分入料（原子）。"""
    auto = AutoFeed()
    recipe = {"materials": [{"id": "moon_grass", "count": 2}, {"id": "huoyao", "count": 1}]}
    ctx = _ctx({"moon_grass": 5})  # 火药 0
    r = auto.balance(ctx, recipe)
    assert r["ok"] is False
    assert r["reason"] == "shortfall"
    assert r["plan"] is None  # 不部分入料
    assert r["message"] == "缺 火药×1"
    assert r["shortfall"] == [{"item": "huoyao", "name": "火药", "need": 1}]


def test_tc11_balance_failure_multi_diff() -> None:
    """TC-11 负例补充：多材料缺量 → 多差异以「 + 」连接（L115 同款口径）。"""
    auto = AutoFeed()
    recipe = {
        "materials": [
            {"id": "moon_grass", "count": 3},
            {"id": "huoyao", "count": 2},
            {"id": "base_a", "count": 1},
        ]
    }
    ctx = _ctx({"moon_grass": 1, "base_a": 1})  # 月光草缺 2、火药缺 2
    r = auto.balance(ctx, recipe)
    assert r["ok"] is False
    assert r["message"] == "缺 月光草×2 + 缺 火药×2"


def test_tc11_balance_invalid_recipe() -> None:
    """TC-11 工程补白：recipe 非法（非 Mapping）→ 防御拒绝。"""
    auto = AutoFeed()
    r = auto.balance(_ctx({}), None)
    assert r["ok"] is False and r["reason"] == "invalid_recipe"


# ---------------------------------------------------------------------------
# BATCH-02 批量平均品质（复用 QualitySystem 均值口径）
# ---------------------------------------------------------------------------
def test_batch_quality_average_uses_quality_mean() -> None:
    """BATCH-02 正例：批量平均品质复用 QualitySystem 均值口径（70/70/80→73 精良→rare 档）。"""
    auto = AutoFeed()
    r = auto.batch_quality([70, 70, 80])
    assert r["score"] == 73  # QLT-06 均值四舍五入（同 QualitySystem.aggregate_quality）
    assert r["tier"] == "rare"  # 60-79 → 史诗
    # 与 QualitySystem 直算一致（复用口径验证）
    qs = QualitySystem()
    assert r["score"] == qs.aggregate_quality([70, 70, 80])
    assert r["tier"] == qs.batch_tier([70, 70, 80])


def test_batch_quality_half_up_and_tier() -> None:
    """BATCH-02 补充：半值上取整 85/90→88 传说；单材料原样。"""
    auto = AutoFeed()
    assert auto.batch_quality([85, 90]) == {"score": 88, "tier": "legendary"}
    assert auto.batch_quality([50]) == {"score": 50, "tier": "uncommon"}


def test_batch_quality_empty_defensive() -> None:
    """BATCH-02 工程补白 A-5：空/全非法投料 → score 0 / common（QLT-06 空列表防御，不吞材料）。"""
    auto = AutoFeed()
    r = auto.batch_quality([])
    assert r == {"score": 0, "tier": "common"}
    assert auto.batch_quality(["bad", None]) == {"score": 0, "tier": "common"}


# ---------------------------------------------------------------------------
# TC-14 数量上限超限提示不拦截（BATCH-04 拍板⑤）
# ---------------------------------------------------------------------------
def test_tc14_quantity_over_limit_hint_not_block() -> None:
    """TC-14 正例：超配置上限 → over_limit + 提示「最多一次使用 N 个」，不拦截（ok 恒 True）。"""
    auto = AutoFeed()
    r = auto.check_quantity(120, max_qty=100)
    assert r["ok"] is True  # 只提示不拦截
    assert r["over_limit"] is True
    assert r["count"] == 120 and r["max_qty"] == 100
    assert r["message"] == "最多一次使用 100 个"


def test_tc14_quantity_within_limit() -> None:
    """TC-14 负例：未超上限 → 无提示、正常执行。"""
    auto = AutoFeed()
    r = auto.check_quantity(99, max_qty=100)
    assert r["ok"] is True and r["over_limit"] is False and r["message"] is None


def test_tc14_quantity_default_int32_max() -> None:
    """TC-14 拍板⑤：默认上限 2147483647（int32 max，覆盖 ≤99）；120 不超默认上限直接执行。"""
    auto = AutoFeed()
    assert auto.check_quantity(120) == {
        "ok": True,
        "count": 120,
        "max_qty": DEFAULT_MAX_QTY,
        "over_limit": False,
        "message": None,
    }
    # settings.alchemy.max_qty 可配
    auto2 = AutoFeed({"alchemy": {"max_qty": 50}})
    r2 = auto2.check_quantity(60)
    assert r2["over_limit"] is True and r2["max_qty"] == 50


# ---------------------------------------------------------------------------
# TC-13 原子口径 plan_shortfall（配平/复核差异）
# ---------------------------------------------------------------------------
def test_tc13_plan_shortfall_atomic() -> None:
    """TC-13 正例：复核时背包缺量 → 全拒差异（缺 火药×1），原子口径对齐 TC-11/TC-13。"""
    auto = AutoFeed()
    ctx = _ctx({"moon_grass": 2})  # 火药 0
    r = auto.plan_shortfall([("moon_grass", 2), ("huoyao", 1)], ctx)
    assert r["ok"] is False
    assert r["message"] == "缺 火药×1"
    assert r["shortfall"] == [{"item": "huoyao", "name": "火药", "need": 1}]


def test_tc13_plan_shortfall_ok() -> None:
    """TC-13 负例：全量满足 → ok True、无差异（BATCH-05 材料 ×N 全量满足才执行）。"""
    auto = AutoFeed()
    ctx = _ctx({"moon_grass": 2, "huoyao": 1})
    r = auto.plan_shortfall([("moon_grass", 2), ("huoyao", 1)], ctx)
    assert r["ok"] is True and r["shortfall"] == [] and r["message"] is None


def test_tc13_plan_shortfall_mapping_form() -> None:
    """TC-13 补充：plan 兼容 {item, count} 字典形态（FEED-10 /确认 全量复核同口径）。"""
    auto = AutoFeed()
    ctx = _ctx({"moon_grass": 1})
    r = auto.plan_shortfall([{"item": "moon_grass", "count": 2}], ctx)
    assert r["ok"] is False and r["message"] == "缺 月光草×1"


# ---------------------------------------------------------------------------
# 构造缺省兜底 / count_item hook 口径
# ---------------------------------------------------------------------------
def test_default_construction_and_count_item_hook() -> None:
    """补充：无 settings 构造兜底；count_item hook 优先于 inventory 读取。"""
    auto = AutoFeed()  # 无 settings → 默认上限/默认品质引擎
    # count_item hook 生效：返回 2，覆盖 inventory 的 5
    ctx = _ctx({"fire_gem": 5}, count_item=lambda item_id: 2 if item_id == "fire_gem" else 0)
    r = auto.balance(ctx, _flame_recipe())
    assert r["ok"] is True and r["mode"] == "element_req"
    assert r["plan"] == [("fire_gem", 2)]  # ceil(6/3)=2 ≤ 持有 2


def test_balance_empty_materials_ok() -> None:
    """补充：无 materials 无 element_req 配方 → 空 plan 成功（防御，不抛异常）。"""
    auto = AutoFeed()
    r = auto.balance(_ctx({}), {"materials": []})
    assert r["ok"] is True and r["plan"] == []
