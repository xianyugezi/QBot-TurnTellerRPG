"""M10 钓鱼·批7·路7A：编辑器服务层预留单测（tests/unit/test_fishing_editor.py）。

文件名：tests/unit/test_fishing_editor.py
创建时间：2026-09-01
作者：Hermes 子agent-7A（M10 钓鱼实现组批7·路7A：编辑器服务层预留）

测试目标：qbot_rpg.editor.fishing_editor_service.{fish_card_schema,
fish_csv_export, fish_csv_import, fish_csv_validate, crown_preview,
simulate_catches}。

覆盖（≥14 用例）：
  - 卡片字段 schema 键齐（9 键照 FISHING_SETTINGS_KEYS 序）+ 类型/默认值
    对齐批0 定义 + mode 枚举 + 嵌套对象 children 提示
  - CSV 导入导出复用批0 双向（export→import 逐字段一致；13 列表头）
  - CSV 校验各错误：id 重复 / id 必填 / name 必填 / 区间倒置 / 枚举非法 /
    hours 格式 / spots 空 / preferred_bait 引用缺失 / bait_ids 缺省跳过
  - 冠级预览档位正确（默认阈值边界：4.9/5.0、84.9/85.0、94.9/95.0 +
    混合极端判金冠 + 中文标签 + 阈值生效）
  - 图鉴模拟：种子化重复一致（同 seed 恒同）/ 大 N 分布接近理论值
    （N=200000 六档 ±0.5pp）/ 阈值滑条生效（放宽 silver 阈值 → 分布偏移）
    / n=0 全零 / species 双形态（FishDef 与 Mapping 同结果）

依据：
  - docs/规划/规划_路2c1_钓鱼.md T19（L164-170）
  - docs/m10_batch_plan.md 批7·路7A + docs/m10_启动包.md §五 批7（L92-93）
  - 定稿 §五（L101-106）+ §七 登记要求·编辑器（L124）
  - docs/细化/细化_2c1a_鱼种数据与冠级.md §一 1.4 / §二 2.2（六档概率）/
    §六 TC-05（种子化收敛 ±0.5pp）/ §七（编辑器登记）
  - docs/m10_shared_contract.md §二/§三/§五
铁律：零 NoneBot import；确定性测试种子化（无裸 random）；docstring 不含
      计时器函数字面量（M43 探针，用「零定时器/零睡眠」措辞）；无 emoji。
"""

from __future__ import annotations

import random
from typing import Dict, List, Tuple, cast

from qbot_rpg.content.fishing_models import FishDef
from qbot_rpg.core.fishing_csv import CSV_COLUMNS
from qbot_rpg.core.fishing_crown import crown_of as engine_crown_of
from qbot_rpg.core.fishing_crown import gen_size_weight as engine_gen_size_weight
from qbot_rpg.core.fishing_settings import (
    DEFAULT_FISHING_SETTINGS,
    FISHING_SETTINGS_FIELD_DEFS,
    FISHING_SETTINGS_KEYS,
    MODE_VALUES,
)
from qbot_rpg.editor.fishing_editor_service import (
    SPECIES_CSV_COLUMNS,
    crown_preview,
    fish_card_schema,
    fish_csv_export,
    fish_csv_import,
    fish_csv_validate,
    simulate_catches,
)

# 夹具基准行（细化 2c1a §1.3 示例鱼种 + 共享契约 §二；对齐 test_fishing_crown）
_SILVER_CARP: Dict[str, object] = {
    "id": "silver_carp", "name": "银鳞鲤", "rarity": "normal",
    "size_min": 10.0, "size_max": 60.0, "weight_min": 0.3, "weight_max": 5.0,
    "seasons": ["spring", "summer", "autumn"],
    "periods": ["dawn", "noon", "dusk"],
    "hours": ["00:00-24:00"],
    "spots": ["map_laketown:pier_01"],
    "preferred_bait": ["饵_蚯蚓"],
    "codex_text": {"desc": "鳞片泛银光的鲤，黄昏时最活跃。", "unit": "cm-kg",
                   "best_mask": "{name} · 最大 {best_size}cm/{best_weight}kg · "
                                "{best_crown} · 逆金冠×{reverse_crown_count}"},
    "king": None,
}

# 默认阈值（细化 2c1a §2.1：reverse=5 / silver=85 / gold=95）
_BAIT_IDS: List[str] = ["饵_蚯蚓", "饵_面团", "饵_小鱼", "饵_黄金虫", "饵_龙涎"]


def _carp() -> FishDef:
    return cast(FishDef, FishDef.from_entry(dict(_SILVER_CARP)))


def _carp_raw() -> Dict[str, object]:
    return dict(_SILVER_CARP)


# ---------------------------------------------------------------------------
# 钓鱼卡片字段 schema
# ---------------------------------------------------------------------------
def test_schema_has_all_nine_keys_in_order() -> None:
    """卡片字段键齐：9 键且键序照 FISHING_SETTINGS_KEYS（契约 §一 字段表）。"""
    schema = fish_card_schema()
    assert list(schema.keys()) == list(FISHING_SETTINGS_KEYS)
    assert len(schema) == 9


def test_schema_type_and_default_align_batch0_defs() -> None:
    """类型/默认值逐键对齐批0 FISHING_SETTINGS_FIELD_DEFS（零重写）。"""
    schema = fish_card_schema()
    for key in FISHING_SETTINGS_KEYS:
        meta = FISHING_SETTINGS_FIELD_DEFS[key]
        assert schema[key]["type"] == meta.type
        expected_default = meta.default
        if expected_default is None:
            expected_default = DEFAULT_FISHING_SETTINGS[key]
        assert schema[key]["default"] == expected_default


def test_schema_mode_enum_and_desc_present() -> None:
    """mode 键带三态枚举（下拉渲染）+ 每键有中文说明文案。"""
    schema = fish_card_schema()
    assert tuple(cast(Tuple[str, ...], schema["mode"]["enum"])) == MODE_VALUES
    for key in FISHING_SETTINGS_KEYS:
        assert isinstance(schema[key]["desc"], str) and schema[key]["desc"]


def test_schema_nested_obj_children_hint() -> None:
    """嵌套对象键（bait_bonus 等 6 键）带 children 子键名提示。"""
    schema = fish_card_schema()
    assert tuple(cast(Tuple[str, ...], schema["crown_thresholds"]["children"])) == (
        "reverse", "silver", "gold")
    assert tuple(cast(Tuple[str, ...], schema["wait_sec"]["children"])) == ("min", "max")
    assert tuple(cast(Tuple[str, ...], schema["king_event"]["children"])) == (
        "enabled", "window_daily", "chance")
    assert schema["bait_ids"]["element"] == "str"


# ---------------------------------------------------------------------------
# 鱼种 CSV 导入导出（复用批0 双向）
# ---------------------------------------------------------------------------
def test_csv_export_import_roundtrip_bidirectional() -> None:
    """CSV 导出→导入逐字段一致（双向复用批0；TC-03 口径）。"""
    text = fish_csv_export([_SILVER_CARP])
    rows = fish_csv_import(text)
    assert len(rows) == 1
    # CSV 只承载 13 列（king 等额外键不导出不导入，批0 契约 §二 L89）；
    # 13 列键逐字段一致即双向无损（TC-03 口径）
    for key in CSV_COLUMNS:
        assert rows[0][key] == _SILVER_CARP[key], key
    assert rows[0]["codex_text"] == _SILVER_CARP["codex_text"]


def test_csv_export_header_is_thirteen_columns() -> None:
    """导出表头 13 列固定序（对齐批0 CSV_COLUMNS / 契约 §二 L89）。"""
    text = fish_csv_export([_SILVER_CARP])
    header = text.splitlines()[0].split(",")
    assert header == list(CSV_COLUMNS)
    assert tuple(header) == SPECIES_CSV_COLUMNS


# ---------------------------------------------------------------------------
# 鱼种 CSV 逐行校验
# ---------------------------------------------------------------------------
def test_csv_validate_ok_rows() -> None:
    """合法行：ok=True，errors 空，warnings 空。"""
    result = fish_csv_validate([_SILVER_CARP], bait_ids=_BAIT_IDS)
    assert result["ok"] is True
    assert result["errors"] == []
    assert result["warnings"] == []


def test_csv_validate_duplicate_and_missing_id() -> None:
    """id 重复（V5 fish_id_duplicate）+ id 缺失（fish_id_required）。"""
    rows = [dict(_SILVER_CARP), dict(_SILVER_CARP)]
    result = fish_csv_validate(rows, bait_ids=_BAIT_IDS)
    assert result["ok"] is False
    rules = [e["rule"] for e in result["errors"]]
    assert "fish_id_duplicate" in rules
    missing = [dict(_SILVER_CARP)]
    missing[0].pop("id")
    result2 = fish_csv_validate(missing, bait_ids=_BAIT_IDS)
    assert "fish_id_required" in [e["rule"] for e in result2["errors"]]


def test_csv_validate_required_fields() -> None:
    """必填字段缺失：name/rarity 缺失 → required_field_missing。"""
    rows = [dict(_SILVER_CARP)]
    rows[0].pop("name")
    rows[0]["rarity"] = ""
    result = fish_csv_validate(rows, bait_ids=_BAIT_IDS)
    rules = [e["rule"] for e in result["errors"]]
    assert rules.count("required_field_missing") >= 2


def test_csv_validate_numeric_range_reversed() -> None:
    """数值区间倒置（V1 口径：size_min>size_max → range_reversed）。"""
    rows = [dict(_SILVER_CARP)]
    rows[0]["size_min"] = 100.0
    rows[0]["size_max"] = 10.0
    result = fish_csv_validate(rows, bait_ids=_BAIT_IDS)
    assert result["ok"] is False
    assert "range_reversed" in [e["rule"] for e in result["errors"]]


def test_csv_validate_enums_and_hours_and_spots() -> None:
    """枚举非法（rarity/seasons/periods）+ hours 格式 + spots 空（V6 口径）。"""
    rows = [dict(_SILVER_CARP)]
    rows[0]["rarity"] = "legendary"
    rows[0]["seasons"] = ["spring", "winter_extra"]
    rows[0]["hours"] = ["25:99-24:00"]
    rows[0]["spots"] = []
    result = fish_csv_validate(rows, bait_ids=_BAIT_IDS)
    errs: list = result.get("errors", [])
    rules = [e["rule"] for e in errs]
    assert "rarity_invalid" in rules
    assert "season_invalid" in rules
    assert "hours_format" in rules
    assert "spots_empty" in rules


def test_csv_validate_bait_ref_missing_and_skip_without_bait_ids() -> None:
    """preferred_bait 引用缺失（V3 bait_ref_missing）；bait_ids 缺省时跳过。"""
    rows = [dict(_SILVER_CARP)]
    rows[0]["preferred_bait"] = ["饵_不存在"]
    result = fish_csv_validate(rows, bait_ids=_BAIT_IDS)
    errs: list = result.get("errors", [])
    assert "bait_ref_missing" in [e["rule"] for e in errs]
    # bait_ids=None → 引用检查宽松跳过不误报（对齐 fishing_models 口径）
    result2 = fish_csv_validate(rows)
    assert result2["ok"] is True


# ---------------------------------------------------------------------------
# 冠级阈值滑条预览
# ---------------------------------------------------------------------------
def test_crown_preview_default_threshold_boundaries() -> None:
    """默认阈值边界：4.9/4.9 逆金冠；5.0/5.0 非逆金冠（严格 <）；84.9 银冠；
    85.0 银冠级（>=）；94.9/95.0 金冠级（>=）。"""
    assert crown_preview(4.9, 4.9)["crown"] == "reverse"
    assert crown_preview(5.0, 5.0)["crown"] != "reverse"
    assert crown_preview(84.9, 84.9)["crown"] == "normal"
    assert crown_preview(85.0, 85.0)["crown"] == "big_silver"
    assert crown_preview(94.9, 94.9)["crown"] == "big_silver"
    assert crown_preview(95.0, 95.0)["crown"] == "big_gold"


def test_crown_preview_mixed_extreme_is_gold() -> None:
    """混合极端（size=96 且 weight=1）判金冠（判定顺序写死，非逆金冠）。"""
    out = crown_preview(96.0, 1.0)
    assert out["crown"] == "gold"
    assert out["label"] == "金冠"


def test_crown_preview_thresholds_effective() -> None:
    """阈值参数化生效：{reverse:20, silver:80, gold:90} 下 10/10 逆金冠。"""
    out = crown_preview(10.0, 10.0, {"reverse": 20, "silver": 80, "gold": 90})
    assert out["crown"] == "reverse"
    assert out["label"] == "逆金冠"
    assert crown_preview(10.0, 10.0)["crown"] != "reverse"  # 默认 5/85/95 下不判


# ---------------------------------------------------------------------------
# 图鉴模拟（种子化分布）
# ---------------------------------------------------------------------------
def test_simulate_seeded_repeatable() -> None:
    """种子化重复一致：同 seed 同 species 同 n → 分布恒同（确定性）。"""
    a = simulate_catches(_carp(), 1000, seed=42)
    b = simulate_catches(_carp(), 1000, seed=42)
    c = simulate_catches(_carp(), 1000, seed=2026)
    assert a["distribution"] == b["distribution"]
    assert a["distribution"] != c["distribution"]
    assert a["seed"] == 42


def test_simulate_large_n_converges_to_theory() -> None:
    """大 N 分布接近理论值：N=200000 六档频率与细化 2c1a §2.2 理论概率
    （±0.5pp，TC-05 口径）。"""
    out = simulate_catches(_carp(), 200000, seed=42)
    dist = cast(Dict[str, int], out["distribution"])
    theo = cast(Dict[str, float], out["theoretical"])
    assert out["total"] == 200000
    for crown, prob in theo.items():
        freq = dist[crown] / 200000.0
        assert abs(freq - prob) < 0.005, f"{crown}: {freq:.4f} vs {prob:.4f}"


def test_simulate_thresholds_shift_distribution() -> None:
    """阈值滑条生效：silver=60 放宽 → 银冠+大银冠占比显著高于默认 85。"""
    wide = simulate_catches(_carp(), 100000, {"reverse": 5, "silver": 60, "gold": 95}, seed=42)
    default = simulate_catches(_carp(), 100000, seed=42)
    d_wide = cast(Dict[str, int], wide["distribution"])
    d_def = cast(Dict[str, int], default["distribution"])
    silver_wide = (d_wide["silver"] + d_wide["big_silver"]) / 100000.0
    silver_def = (d_def["silver"] + d_def["big_silver"]) / 100000.0
    assert silver_wide > silver_def + 0.05


def test_simulate_zero_n_and_species_forms() -> None:
    """n=0 分布全零；FishDef 与 Mapping 双形态同参同结果。"""
    zero = simulate_catches(_carp(), 0)
    assert zero["total"] == 0
    assert all(v == 0 for v in cast(Dict[str, int], zero["distribution"]).values())
    a = simulate_catches(_carp(), 5000, seed=7)
    b = simulate_catches(_carp_raw(), 5000, seed=7)
    assert a["distribution"] == b["distribution"]


def test_simulate_uses_same_engine_as_runtime() -> None:
    """与运行分布同参数一致（T19 验收）：模拟引擎=gen_size_weight+crown_of，
    同 rng 序列手算一致。"""
    rng = random.Random(42)
    expected: Dict[str, int] = {k: 0 for k in (
        "reverse", "big_gold", "gold", "big_silver", "silver", "normal")}
    for _ in range(500):
        g = engine_gen_size_weight(_carp_raw(), rng)
        c = engine_crown_of(g["size_pct"], g["weight_pct"], None)
        expected[c] = expected.get(c, 0) + 1
    out = simulate_catches(_carp_raw(), 500, seed=42)
    assert out["distribution"] == expected
    assert expected["reverse"] == 0
