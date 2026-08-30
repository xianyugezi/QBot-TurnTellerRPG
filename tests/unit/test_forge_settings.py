"""M9 批次0·路0B：forge_settings 模块单测（settings.forge 读段 + items 字段扩展 + 来源归一）。

文件名：tests/unit/test_forge_settings.py
创建时间：2026-08-30
作者：Hermes 子agent-0B（M9 锻造数据层 路0B）
功能描述：qbot_rpg.content.forge_settings 纯函数直测（零 NoneBot、确定性）：
  - read_forge_settings 缺省合并：settings 无 forge 段 / 段空 / 非 Mapping / None → 全默认值
  - 显式覆盖：各键显式值生效；类型不合法回退默认（运行期兜底不炸）
  - decompose_rate 表：默认 6 档中文档名键；显式 Mapping 合并（覆盖同名、保留缺省档位）
  - ITEMS_FORGE_FIELDS / FORGE_SETTINGS_FIELD_DEFS 字段扩展定义结构
  - resolve_source_text 来源归一优先级（source_override > items.source > fallback）

依据：
  - docs/m9_shared_contract.md §三（ForgeSettings 全字段表默认值）/ §八（items 材料类
    material_tier+source / settings.forge 段形态）
  - docs/细化/细化_2c2a_锻造派生树schema.md §1.4（S-01~S-05）
  - docs/细化/细化_2c2c_锻造素材经济.md §2.1（TIER-03a）/ SOUR-00（来源标签总则）
  - 锻造系统设计定稿 v1.0.1 §12.4（L351-358）
  - 炼金系统设计定稿 v2.3 L418（decompose_rate 默认 6 档表，forge 复用）
"""

from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.content.forge_settings import (
    DEFAULT_DECOMPOSE_RATE,
    DEFAULT_UNKNOWN_SOURCE,
    FORGE_SETTINGS_DEFAULTS,
    FORGE_SETTINGS_FIELD_DEFS,
    FORGE_SETTINGS_KEYS,
    ITEMS_FORGE_FIELDS,
    MATERIAL_TIER_VALUES,
    forge_settings_meta,
    read_forge_settings,
    resolve_source_text,
)


# ---------------------------------------------------------------------------
# read_forge_settings：缺省合并
# ---------------------------------------------------------------------------
def test_defaults_when_no_forge_section() -> None:
    """settings 无 forge 段 → 全默认值（对齐 alchemy_settings P-6 兜底，不报错）。"""
    cases: list[object] = [
        {}, {"currencies": []}, {"forge": None}, {"forge": {}}, None, "not-a-map", 42,
    ]
    for raw in cases:
        got = read_forge_settings(raw)
        assert isinstance(got, dict)
        assert set(got) == set(FORGE_SETTINGS_KEYS)
        for key in FORGE_SETTINGS_KEYS:
            assert got[key] == FORGE_SETTINGS_DEFAULTS[key], key
        # 默认表对象不被调用方改动污染（深拷贝隔离）
        assert got["decompose_rate"] == DEFAULT_DECOMPOSE_RATE
        assert got["decompose_rate"] is not DEFAULT_DECOMPOSE_RATE


def test_defaults_values() -> None:
    """默认值逐键断言（共享契约 §三 ForgeSettings）。"""
    got = read_forge_settings({})
    assert got["forge_fee"] == "节点等级×10"
    assert got["synth_ratio_3to1"] is True
    assert got["straight_forge"] is True
    assert got["exp_per_forge"] == "节点等级×2"
    assert got["sets_enabled"] is True
    assert got["augments_enabled"] is True
    assert got["decompose_rate"] == {
        "正式": 0.4, "精通": 0.45, "专家": 0.5, "大师": 0.55, "宗师": 0.6, "王": 0.65,
    }


# ---------------------------------------------------------------------------
# read_forge_settings：显式覆盖 + 类型容错
# ---------------------------------------------------------------------------
def test_explicit_overrides() -> None:
    """显式设置 → 覆盖默认值（全键一次覆盖）。"""
    raw = {
        "forge": {
            "forge_fee": 500,
            "synth_ratio_3to1": False,
            "straight_forge": False,
            "exp_per_forge": 4,
            "sets_enabled": False,
            "augments_enabled": False,
        },
    }
    got = read_forge_settings(raw)
    assert got["forge_fee"] == 500
    assert got["synth_ratio_3to1"] is False
    assert got["straight_forge"] is False
    assert got["exp_per_forge"] == 4
    assert got["sets_enabled"] is False
    assert got["augments_enabled"] is False
    # 未显式键保留默认
    assert got["decompose_rate"] == DEFAULT_DECOMPOSE_RATE


def test_str_or_int_forge_fee_exp() -> None:
    """forge_fee / exp_per_forge 支持 str 公式 或 int（定稿 §12.4 str|int 联合）。"""
    got = read_forge_settings({"forge": {"forge_fee": "节点等级×10", "exp_per_forge": 3}})
    assert got["forge_fee"] == "节点等级×10"
    assert got["exp_per_forge"] == 3


def test_invalid_type_falls_back_to_default() -> None:
    """类型不合法 → 回退默认（运行期兜底不炸，校验器硬拦）。"""
    got = read_forge_settings({
        "forge": {
            "forge_fee": 12.5,            # 非 str 非 int
            "synth_ratio_3to1": "yes",    # 非 bool
            "straight_forge": 1,          # bool 是 int 子类，1 非 bool
            "exp_per_forge": -3,          # 负 int 非法
            "sets_enabled": None,
            "augments_enabled": [],
            "decompose_rate": "0.4",      # 非 Mapping
        },
    })
    for key in FORGE_SETTINGS_KEYS:
        assert got[key] == FORGE_SETTINGS_DEFAULTS[key], key


def test_bool_is_not_int_for_fee() -> None:
    """bool 值不得被当作 forge_fee 的 int 接受（bool 是 int 子类陷阱）。"""
    got = read_forge_settings({"forge": {"forge_fee": True}})
    assert got["forge_fee"] == "节点等级×10"  # True 被拒绝 → 回退默认


# ---------------------------------------------------------------------------
# decompose_rate 表（中文档名键）
# ---------------------------------------------------------------------------
def test_decompose_rate_merge_overrides_same_keys() -> None:
    """显式 decompose_rate 与默认表合并：覆盖同名中文档名键，缺省档位保留默认。"""
    got = read_forge_settings({"forge": {"decompose_rate": {"正式": 0.5, "王": 0.7}}})
    assert got["decompose_rate"] == {
        "正式": 0.5, "精通": 0.45, "专家": 0.5, "大师": 0.55, "宗师": 0.6, "王": 0.7,
    }


def test_decompose_rate_extra_keys_kept() -> None:
    """显式表含默认表外新键 → 保留（宽松合并，校验器负责档位完整性）。"""
    got = read_forge_settings({"forge": {"decompose_rate": {"见习": 0.3}}})
    dr = got["decompose_rate"]
    assert isinstance(dr, dict)
    assert dr["见习"] == 0.3
    assert dr["正式"] == 0.4  # 默认档位仍在


def test_decompose_rate_default_unchanged() -> None:
    """多次调用相互独立：默认表常量不被合并污染。"""
    read_forge_settings({"forge": {"decompose_rate": {"正式": 0.9}}})
    assert DEFAULT_DECOMPOSE_RATE["正式"] == 0.4


# ---------------------------------------------------------------------------
# 字段扩展定义结构
# ---------------------------------------------------------------------------
def test_items_forge_fields_structure() -> None:
    """ITEMS_FORGE_FIELDS：material_tier enum normal/rare + source str（宽松登记）。"""
    assert set(ITEMS_FORGE_FIELDS) == {"material_tier", "source"}

    mt = ITEMS_FORGE_FIELDS["material_tier"]
    assert mt.type == "enum"
    assert set(mt.enum) == set(MATERIAL_TIER_VALUES) == {"normal", "rare"}
    assert mt.default == "normal"          # 缺省普通（基础材料）
    assert mt.required is False            # 宽松登记：既有包无此字段不误拦
    assert mt.soft_label is False

    src = ITEMS_FORGE_FIELDS["source"]
    assert src.type == "str"
    assert src.required is False
    assert src.enum == ()                  # 不设枚举防误拦（来源文本自由文本）


def test_forge_settings_field_defs_structure() -> None:
    """FORGE_SETTINGS_FIELD_DEFS：settings.forge 段全字段（含 2c2d 补白键）。"""
    assert set(FORGE_SETTINGS_FIELD_DEFS) == set(FORGE_SETTINGS_KEYS)
    assert FORGE_SETTINGS_FIELD_DEFS["synth_ratio_3to1"].type == "bool"
    assert FORGE_SETTINGS_FIELD_DEFS["straight_forge"].type == "bool"
    assert FORGE_SETTINGS_FIELD_DEFS["sets_enabled"].type == "bool"
    assert FORGE_SETTINGS_FIELD_DEFS["augments_enabled"].type == "bool"
    assert FORGE_SETTINGS_FIELD_DEFS["decompose_rate"].type == "obj"
    # str|int 联合 → soft_label 永不红拦（【工程补白 F-2】，防 R-1 误拦）
    assert FORGE_SETTINGS_FIELD_DEFS["forge_fee"].soft_label is True
    assert FORGE_SETTINGS_FIELD_DEFS["exp_per_forge"].soft_label is True


def test_forge_settings_meta_shape() -> None:
    """forge_settings_meta()：type=obj + children=FORGE_SETTINGS_FIELD_DEFS（收口合并口径）。"""
    meta = forge_settings_meta()
    assert meta.type == "obj"
    assert dict(meta.children) == dict(FORGE_SETTINGS_FIELD_DEFS)


# ---------------------------------------------------------------------------
# resolve_source_text：来源归一
# ---------------------------------------------------------------------------
def test_source_override_beats_item_source() -> None:
    """M-04 source_override（行覆写）> items.source（双源仲裁风格）。"""
    material_row: Dict[str, Any] = {"item": "ore", "count": 5, "source_override": "挖掘点"}
    items_entry: Dict[str, Any] = {"id": "ore", "source": "采集点"}
    assert resolve_source_text(material_row, items_entry) == "挖掘点"


def test_item_source_fallback() -> None:
    """行无覆写 → items.source 来源标签。"""
    assert resolve_source_text(
        {"item": "ore", "count": 5}, {"id": "ore", "source": "火龙掉落"}
    ) == "火龙掉落"
    # 行存在但无 source_override
    assert resolve_source_text({"item": "ore", "count": 5}, {"source": "商店"}) == "商店"


def test_source_all_missing_uses_fallback() -> None:
    """两者皆缺/空 → 默认兜底文本（【工程补白 F-3】）。"""
    assert resolve_source_text(None, None) == DEFAULT_UNKNOWN_SOURCE == "来源未知"
    assert resolve_source_text({}, {}) == DEFAULT_UNKNOWN_SOURCE
    assert resolve_source_text({"source_override": "  "}, {"source": ""}) == DEFAULT_UNKNOWN_SOURCE
    # 自定义 fallback
    assert resolve_source_text(None, None, fallback="") == ""


def test_source_whitespace_trimmed() -> None:
    """非空文本 trim 返回（确定性）。"""
    assert resolve_source_text({"source_override": "  火龙掉落  "}, None) == "火龙掉落"
    assert resolve_source_text(None, {"source": "  采集点  "}) == "采集点"
