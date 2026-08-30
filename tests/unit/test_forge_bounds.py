"""M9 锻造·批6·路6A：边界铁律接口契约单测（确定性 / 带孔唯一来源 / 炼金接口契约点 / 费用公式）。

文件：tests/unit/test_forge_bounds.py
创建：2026-08-30
作者：Hermes 子agent-6A（M9 锻造实现组批6·路6A：并发同仓，仅新建本文件 +
qbot_rpg/core/forge_bounds.py；不改动任何已有实现文件）

测试目标：qbot_rpg.core.forge_bounds.{determinism_check, slotted_source_check,
alchemy_interface, forge_fee_check}——对应规划_路2c2_锻造.md T18「三系统边界与联动闭环」。

依据：定稿 §1.1/§1.2 边界铁律（100% 成功 / 无随机 / 带孔唯一来源 / 随机性不同源）、§八
锻造×装饰珠联动、§九 锻造×8属性弱点制、§十二.4 settings forge_fee、§十六 三系统对比；
细化_2c2b §1.2（原子扣减）/§1.3（失败零副作用）。

覆盖规则：
  - 确定性：合法全量节点零随机字段 → ok + violations=0；人为加 random/chance/rand 字段 →
    报违规（node_id/field/reason 齐备）；序依赖引用（item 非字符串 / branch 含非字符串）→ 违规；
    描述字段含「概率」文案 → W 级 warnings 不拦截（不翻转 ok）。
  - 带孔唯一来源：test_demo slots 仅由 forge 节点产出（items 无 slots、recipe/shop/drops 不产出）
    → ok；人为在 shop/recipe/enemies drops 产出带孔 item → 违规（source/item_id/reason）。
  - 炼金接口契约点：contracts 含 alchemy_mount / enhance_numeric / element_weakness 三契约点，
    每项带 id/name/consumers/inputs/ok/details/issues；元素通道对齐 alchemy ELEMENT_NAMES_CN
    （thunder vs lightning 口径差异如实上报 → element_weakness ok=False）；装饰珠镶嵌源存在
    → alchemy_mount ok=True；monster 弱点对齐登记。
  - 费用公式：forge_fee "节点等级×10" → base_fee_per_level=10 + formula + deterministic +
    gold_insufficient_reject；int 直接作系数；含随机 token → 违规；缺省 10。

测试风格对齐 test_forge_models.py / test_forge_commands.py（真实 content/test_demo 数据 +
纯函数直测）。铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠调用；不引入随机。
"""
from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, Mapping

from qbot_rpg.core.forge_bounds import (
    alchemy_interface,
    determinism_check,
    forge_fee_check,
    slotted_source_check,
)

# 真实 test_demo 数据路径
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DEMO = _REPO_ROOT / "content" / "test_demo"


def _load(name: str) -> Any:
    return json.loads((_DEMO / f"{name}.json").read_text(encoding="utf-8"))


def _modules() -> Dict[str, object]:
    """test_demo 全模块（forge/items/enemies/shop/recipe）。"""
    return {
        "forge": _load("forge"),
        "items": _load("items"),
        "enemies": _load("enemies"),
        "shop": _load("shop"),
        "recipe": _load("recipe"),
    }


def _settings() -> Mapping[str, object]:
    v = _load("settings")
    return v if isinstance(v, Mapping) else {}


def _base_forge() -> Dict[str, Any]:
    """test_demo forge.json（深拷贝复用：改装不污染夹具）。"""
    import copy
    v = _load("forge")
    return dict(copy.deepcopy(v)) if isinstance(v, Mapping) else {}


def _set_node_field(forge: Dict[str, Any], node_id: str, field: str,
                    value: object) -> None:
    """给指定 forge 节点写入字段（深拷贝后的可变 dict 就地改）。"""
    for tree in forge.get("trees", []):
        for node in tree.get("nodes", []):
            if node.get("id") == node_id:
                node[field] = value
                return


# ---------------------------------------------------------------------------
# 1) determinism_check：确定性校验
# ---------------------------------------------------------------------------

def test_determinism_legal_ok() -> None:
    """test_demo 全量节点零随机字段 → ok=True + violations=0（定稿 §1.2 铁律 1/4）。"""
    res = determinism_check(_modules(), _settings())
    assert res["ok"] is True
    assert res["violations"] == []
    assert res["scanned_nodes"] == 9  # 铁剑主干 7 + 冰剑/雷剑 2 分支
    assert res["scanned_fields"] > 0


def test_determinism_random_field_violation() -> None:
    """人为给节点加 random 字段 → 违规（node_id/field/reason 齐备）。"""
    forge = _base_forge()
    _set_node_field(forge, "node_iron_sword", "random", {"rate": 0.5})
    res = determinism_check({"forge": forge}, _settings())
    assert res["ok"] is False
    assert len(res["violations"]) == 1
    v = res["violations"][0]
    assert v["node_id"] == "node_iron_sword"
    assert v["field"] == "random"
    assert "random" in v["reason"]


def test_determinism_chance_and_rand_violation() -> None:
    """chance/rand 字段亦报违规（B-2 token 全覆盖）。"""
    forge = _base_forge()
    _set_node_field(forge, "node_flame_sword", "chance", 30)
    _set_node_field(forge, "node_ice_sword", "rand_key", "x")
    res = determinism_check({"forge": forge}, _settings())
    assert res["ok"] is False
    fields = {v["field"] for v in res["violations"]}
    assert "chance" in fields
    assert "rand_key" in fields


def test_determinism_nested_random_in_materials() -> None:
    """嵌套结构（materials 行内 chance）也报违规——概率分支不留锻造。"""
    forge = _base_forge()
    _set_node_field(forge, "node_iron_sword", "materials",
                    [{"item": "ore", "count": 3, "chance": 100}])
    res = determinism_check({"forge": forge}, _settings())
    assert res["ok"] is False
    assert any("chance" in v["field"] for v in res["violations"])


def test_determinism_order_dependent_ref() -> None:
    """item 非静态字符串（序依赖引用）→ 违规（B-3）。"""
    forge = _base_forge()
    _set_node_field(forge, "node_iron_sword_1", "item", ["iron_sword_1", "iron_sword_2"])
    res = determinism_check({"forge": forge}, _settings())
    assert res["ok"] is False
    assert any(v["field"] == "item" for v in res["violations"])


def test_determinism_branch_non_string() -> None:
    """branch 含非字符串项（概率分支候选）→ 违规（B-3）。"""
    forge = _base_forge()
    _set_node_field(forge, "node_flame_sword_2", "branch",
                    ["node_ice_sword", {"id": "node_lightning_sword", "weight": 0.5}])
    res = determinism_check({"forge": forge}, _settings())
    assert res["ok"] is False
    assert any("branch" in v["field"] for v in res["violations"])


def test_determinism_desc_mention_warning_not_blocking() -> None:
    """描述字段值含「概率」文案 → W 级 warnings 不拦截（B-2：文案非机制随机）。"""
    forge = _base_forge()
    _set_node_field(forge, "node_iron_sword", "name", "概率之刃")
    res = determinism_check({"forge": forge}, _settings())
    # 字段名 name 不在随机 token → 不报违规；但值是描述字段 → W 级 warnings
    assert res["ok"] is True
    assert len(res["warnings"]) == 1
    assert res["warnings"][0]["field"] == "name"


def test_determinism_missing_forge_pass() -> None:
    """forge 模块缺失 → 扫描 0 节点 ok=True（防御放行，对齐既有校验器惯例）。"""
    res = determinism_check({"items": []}, _settings())
    assert res["ok"] is True
    assert res["scanned_nodes"] == 0


# ---------------------------------------------------------------------------
# 2) slotted_source_check：带孔唯一来源
# ---------------------------------------------------------------------------

def test_slotted_legal_ok() -> None:
    """test_demo：slots 仅由 forge 节点产出，recipe/shop/drops 均不产出带孔装备 → ok。"""
    res = slotted_source_check(_settings(), _modules())
    assert res["ok"] is True
    assert res["violations"] == []
    assert res["slotted_items"] == ["flame_king_sword", "flame_sword_2", "iron_sword_2"]
    assert set(res["forge_slotted"]) == {"iron_sword_2", "flame_sword_2", "flame_king_sword"}
    assert res["routes"]["recipe"] == []
    assert res["routes"]["shop"] == []
    assert res["routes"]["drops"] == []


def test_slotted_shop_violation() -> None:
    """商店出售带孔装备 → 违规（source=shop）。"""
    forge = _base_forge()
    shop = [
        {"id": "s1", "items": [{"item": "flame_sword_2", "price": 100, "stock": 1}]},
    ]
    res = slotted_source_check(_settings(), {"forge": forge, "items": _load("items"),
                                             "shop": shop})
    assert res["ok"] is False
    assert any(v["source"] == "shop" and v["item_id"] == "flame_sword_2"
               for v in res["violations"])
    assert "flame_sword_2" in res["routes"]["shop"]


def test_slotted_recipe_output_violation() -> None:
    """合成配方产出带孔装备 → 违规（source=recipe）。"""
    forge = _base_forge()
    recipe = [
        {"id": "r1", "output": {"item": "iron_sword_2", "count": 1}},
    ]
    res = slotted_source_check(_settings(), {"forge": forge, "items": _load("items"),
                                             "recipe": recipe})
    assert res["ok"] is False
    assert any(v["source"] == "recipe" and v["item_id"] == "iron_sword_2"
               for v in res["violations"])


def test_slotted_drop_violation() -> None:
    """怪物掉落带孔装备 → 违规（source=drops）。"""
    forge = _base_forge()
    enemies = [
        {"id": "m1", "drops": {"battle": [], "special": [],
                               "death": [{"item": "flame_king_sword", "chance": 50,
                                          "count": 1}]}},
    ]
    res = slotted_source_check(_settings(), {"forge": forge, "items": _load("items"),
                                             "enemies": enemies})
    assert res["ok"] is False
    assert any(v["source"] == "drops" and v["item_id"] == "flame_king_sword"
               for v in res["violations"])


def test_slotted_items_no_forge_source_violation() -> None:
    """items 自带 slots 非空但无 forge 产出 → 违规（唯一来源=锻造被绕过）。"""
    forge = _base_forge()
    items = list(_load("items"))
    items.append({"id": "rogue_slot_sword", "name": "野路子剑", "type": "weapon",
                  "atk": 1, "slots": [{"level": 1}]})
    res = slotted_source_check(_settings(), {"forge": forge, "items": items})
    assert res["ok"] is False
    assert any(v["source"] == "items" and v["item_id"] == "rogue_slot_sword"
               for v in res["violations"])


def test_slotted_augment_slot_not_violation() -> None:
    """客制开孔（augments kind=slot）不判违规——追加孔非新产出（B-4，定稿 §八 开孔道具可配）。"""
    forge = _base_forge()
    augments = forge.get("augments")
    assert isinstance(augments, dict)
    has_slot = any(a.get("kind") == "slot" for a in augments.get("augments", []))
    assert has_slot is True  # test_demo aug_slot 存在
    res = slotted_source_check(_settings(), {"forge": forge, "items": _load("items")})
    assert res["ok"] is True  # 客制开孔不产生带孔装备新来源违规


def test_slotted_missing_route_tables_pass() -> None:
    """缺 recipe/shop/enemies 表 → 途径不判违规（防御放行）。"""
    res = slotted_source_check(_settings(), {"forge": _base_forge(),
                                             "items": _load("items")})
    assert res["ok"] is True


# ---------------------------------------------------------------------------
# 3) alchemy_interface：炼金/强化/属性弱点接口契约点
# ---------------------------------------------------------------------------

def test_alchemy_contracts_shape() -> None:
    """contracts 含三契约点（alchemy_mount/enhance_numeric/element_weakness），
    每项带 id/name/consumers/inputs/ok/details/issues（供批6B 冒烟消费）。"""
    res = alchemy_interface(_modules())
    ids = [c["id"] for c in res["contracts"]]
    assert ids == ["alchemy_mount", "enhance_numeric", "element_weakness"]
    for c in res["contracts"]:
        assert set(c.keys()) >= {"id", "name", "consumers", "inputs", "ok",
                                 "details", "issues"}
        assert isinstance(c["ok"], bool)


def test_alchemy_mount_ok() -> None:
    """炼金镶嵌契约点：锻造带孔节点存在 + items 装饰珠存在 → ok=True。"""
    res = alchemy_interface(_modules())
    cp = next(c for c in res["contracts"] if c["id"] == "alchemy_mount")
    assert cp["ok"] is True
    assert set(cp["details"]["slot_levels"]) == {1, 2, 3}
    assert cp["details"]["jewel_count"] >= 1  # jewel_burn_* 装饰珠


def test_alchemy_mount_no_jewel_fail() -> None:
    """无装饰珠（type=装饰珠 缺失）→ 炼金镶嵌闭环断裂 → ok=False。"""
    items = [e for e in _load("items")
             if e.get("type") != "装饰珠"]
    res = alchemy_interface({"forge": _load("forge"), "items": items})
    cp = next(c for c in res["contracts"] if c["id"] == "alchemy_mount")
    assert cp["ok"] is False
    assert any("装饰珠" in i for i in cp["issues"])


def test_alchemy_enhance_numeric_ok() -> None:
    """强化数值层契约点：锻造 stats 数值键 ∈ 数值层键空间 → ok=True（定稿 §十六）。"""
    res = alchemy_interface(_modules())
    cp = next(c for c in res["contracts"] if c["id"] == "enhance_numeric")
    assert cp["ok"] is True
    assert "atk" in cp["details"]["stat_key_usage"]
    assert cp["details"]["unknown_keys"] == []


def test_alchemy_enhance_unknown_key_fail() -> None:
    """锻造 stats 含数值层外键 → 强化不可消费 → ok=False。"""
    forge = _base_forge()
    _set_node_field(forge, "node_iron_sword", "stats", {"atk": 12, "wow": 99})
    res = alchemy_interface({"forge": forge, "items": _load("items"),
                             "enemies": _load("enemies")})
    cp = next(c for c in res["contracts"] if c["id"] == "enhance_numeric")
    assert cp["ok"] is False
    assert "wow" in cp["details"]["unknown_keys"]


def test_alchemy_element_weakness_reports_thunder_mismatch() -> None:
    """元素通道契约点：forge 雷=thunder 不在 alchemy ELEMENT_NAMES_CN（雷=lightning）
    → 如实上报 ok=False（B-5 不静默归一，暴露口径漂移）。"""
    res = alchemy_interface(_modules())
    cp = next(c for c in res["contracts"] if c["id"] == "element_weakness")
    assert cp["ok"] is False  # test_demo 雷剑 element=thunder 与 alchemy lightning 未对齐
    assert "thunder" in cp["details"]["misaligned"]
    assert any("thunder" in i for i in cp["issues"])
    # 火/水 在注册表内且火/水/void 有弱点怪
    assert "fire" in cp["details"]["aligned"]
    assert "water" in cp["details"]["aligned"]
    # W 级：fire/water 有弱点怪不提示；monster weakness 登记
    assert "fire" in res["element_registry"]["monster_weakness"]


def test_alchemy_element_aligned_when_normalized() -> None:
    """元素键对齐注册表（把 thunder 归一为 lightning）→ element_weakness ok=True。"""
    forge = _base_forge()
    _set_node_field(forge, "node_lightning_sword", "stats",
                    {"atk": 38, "element": "lightning", "element_value": 8})
    res = alchemy_interface({"forge": forge, "items": _load("items"),
                             "enemies": _load("enemies")})
    cp = next(c for c in res["contracts"] if c["id"] == "element_weakness")
    assert cp["ok"] is True
    assert "lightning" in cp["details"]["aligned"]
    assert cp["details"]["misaligned"] == []


def test_alchemy_element_registry_mirror() -> None:
    """element_registry 镜像：alchemy（ELEMENT_NAMES_CN 键）/ forge（FORGE_ELEMENTS）/
    monster_weakness（enemies weakness.elements）。"""
    res = alchemy_interface(_modules())
    reg = res["element_registry"]
    assert "lightning" in reg["alchemy"]  # 炼金雷键
    assert "thunder" in reg["forge"]      # 锻造雷键
    assert set(reg["monster_weakness"]) == {"fire", "void", "water"}


# ---------------------------------------------------------------------------
# 4) forge_fee_check：费用公式确定性
# ---------------------------------------------------------------------------

def test_fee_formula_default() -> None:
    """test_demo forge_fee "节点等级×10" → base_fee_per_level=10 + formula +
    deterministic=True + gold_insufficient_reject=True（细化_2c2b §1.2/§1.3）。"""
    res = forge_fee_check(_settings())
    assert res["ok"] is True
    assert res["base_fee_per_level"] == 10
    assert res["formula"] == "节点等级×10"
    assert res["fee_kind"] == "formula"
    assert res["deterministic"] is True
    assert res["gold_insufficient_reject"] is True
    assert res["violations"] == []


def test_fee_int_direct() -> None:
    """forge_fee 为 int → 直接作每级系数（B-6）。"""
    res = forge_fee_check({"forge_fee": 10})
    assert res["ok"] is True
    assert res["base_fee_per_level"] == 10
    assert res["formula"] == "节点等级×10"
    assert res["fee_kind"] == "int"


def test_fee_int_custom() -> None:
    """forge_fee 自定义 int（如 5）→ base=5（可配，定稿 §12.4）。"""
    res = forge_fee_check({"forge": {"forge_fee": 5}})
    assert res["ok"] is True
    assert res["base_fee_per_level"] == 5
    assert res["formula"] == "节点等级×5"


def test_fee_missing_default_10() -> None:
    """forge_fee 缺失 → 缺省 10（S-01 节点等级×10）。"""
    res = forge_fee_check({})
    assert res["ok"] is True
    assert res["base_fee_per_level"] == 10
    assert res["fee_kind"] == "default"


def test_fee_random_formula_violation() -> None:
    """forge_fee 含随机 token → 违规（费用确定性铁律）。"""
    res = forge_fee_check({"forge_fee": "随机"})
    assert res["ok"] is False
    assert any("随机" in v["reason"] for v in res["violations"])


def test_fee_negative_violation() -> None:
    """forge_fee 负系数 → 违规。"""
    res = forge_fee_check({"forge_fee": -5})
    assert res["ok"] is False
    assert any("负" in v["reason"] for v in res["violations"])
