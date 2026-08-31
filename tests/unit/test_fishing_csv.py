"""M10 钓鱼·批0·路0B：fishing.json 鱼种 CSV 双向单测。

文件名：tests/unit/test_fishing_csv.py
创建时间：2026-08-31
作者：Hermes 子agent-0B（M10 钓鱼实现组批0·路0B：并发同仓，仅新建本文件 +
qbot_rpg/core/fishing_csv.py + content/test_demo/fishing.json +
tests/fixtures/packs/legal/fishing.json）

依据：docs/m10_shared_contract.md §二（13 列固定序 / 空数组语义 / 夹具基准行）
+ docs/细化/细化_2c1a_鱼种数据与冠级.md §一 1.3（示例行）/ §一 1.4（CSV 列）
+ 细化 TC-03（导出→导入逐字段一致）/ TC-02（空数组=不限制）。

测试目标：qbot_rpg.core.fishing_csv.{CSV_COLUMNS, fishing_to_csv, csv_to_fishing}。

覆盖：
  - 夹具基准行 silver_carp 导出→导入逐字段一致（TC-03）
  - 表头行存在且 13 列固定序
  - 空数组语义保留（seasons/periods=[] 往返后仍为 []，TC-02）
  - codex_text 单 JSON 单元格（往返 dict 一致）
  - 数组列逗号分隔（spots/preferred_bait/hours）
  - 多行 round trip（顺序保持）
  - 空输入 → []
  - 非法行容错（列数不符跳过；strict=True 抛错）
  - 数值 float 往返精度
  - 确定性（同输入同输出）
  - legal 夹具可加载且 round trip 一致

铁律：零 NoneBot import；纯函数确定性零 IO 零定时器（零睡眠调用）；无随机。
"""
from __future__ import annotations

import csv
import json
import pathlib
from typing import Any, Dict, List

import pytest

from qbot_rpg.core.fishing_csv import CSV_COLUMNS, csv_to_fishing, fishing_to_csv

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DEMO = _REPO_ROOT / "content" / "test_demo"
_LEGAL = _REPO_ROOT / "tests" / "fixtures" / "packs" / "legal"


def _load_demo_fishing() -> Dict[str, Any]:
    return json.loads((_DEMO / "fishing.json").read_text(encoding="utf-8"))


def _load_legal_fishing() -> Dict[str, Any]:
    return json.loads((_LEGAL / "fishing.json").read_text(encoding="utf-8"))


def _demo_species() -> List[Dict[str, Any]]:
    data = _load_demo_fishing()
    return list(data.get("species", []))


# ---------------------------------------------------------------------------
# TC-01 / TC-03：夹具行字段齐全 + 导出→导入逐字段一致
# ---------------------------------------------------------------------------
def test_csv_columns_13_fixed_order() -> None:
    """13 列固定序（2c1a §1.4 / 定稿 §五 L104）。"""
    assert CSV_COLUMNS == (
        "id", "name", "rarity",
        "size_min", "size_max", "weight_min", "weight_max",
        "seasons", "periods", "hours", "spots", "preferred_bait",
        "codex_text",
    )


def test_demo_fixture_species_fields_complete() -> None:
    """夹具基准行字段齐全（TC-01：§1.3 全字段落库）。"""
    rows = _demo_species()
    assert len(rows) >= 1
    row = rows[0]
    assert row["id"] == "silver_carp"
    assert row["name"] == "银鳞鲤"
    assert row["rarity"] == "normal"
    for key in ("size_min", "size_max", "weight_min", "weight_max"):
        assert isinstance(row[key], (int, float))
    assert row["seasons"] == ["spring", "summer", "autumn"]
    assert row["periods"] == ["dawn", "noon", "dusk"]
    assert row["hours"] == ["00:00-24:00"]
    assert row["spots"] == ["gp_moon_grass"]
    assert row["preferred_bait"] == ["饵_蚯蚓"]
    assert row["codex_text"]["unit"] == "cm-kg"
    assert row["king"] is None


def test_fixture_row_roundtrip_field_consistent_tc03() -> None:
    """夹具基准行导出→导入逐字段一致（TC-03：13 列双向无损）。"""
    for row in _demo_species():
        text = fishing_to_csv([row])
        back = csv_to_fishing(text)
        assert len(back) == 1
        parsed = back[0]
        for col in CSV_COLUMNS:
            assert parsed[col] == row[col], f"列 {col} 往返不一致"


def test_legal_fixture_roundtrip_field_consistent() -> None:
    """legal 夹具导出→导入逐字段一致（对齐 legal 包形态）。"""
    data = _load_legal_fishing()
    assert data["schema_version"] == "1.0"
    assert data["king"] == []
    for row in data.get("species", []):
        text = fishing_to_csv([row])
        back = csv_to_fishing(text)
        assert len(back) == 1
        for col in CSV_COLUMNS:
            assert back[0][col] == row[col], f"legal 列 {col} 往返不一致"


# ---------------------------------------------------------------------------
# 表头 / 数组 / codex_text 序列化
# ---------------------------------------------------------------------------
def test_header_present_first_line() -> None:
    """导出 CSV 首行为表头且为 13 列固定序。"""
    text = fishing_to_csv(_demo_species())
    first = text.splitlines()[0]
    assert first == ",".join(CSV_COLUMNS)


def test_header_skipped_on_import() -> None:
    """导入时表头行自动跳过，不产出数据行。"""
    rows = _demo_species()
    text = fishing_to_csv(rows)
    back = csv_to_fishing(text)
    assert len(back) == len(rows)


def test_array_columns_comma_joined() -> None:
    """数组列序列化为逗号分隔字符串（seasons/spots/preferred_bait）。"""
    row: Dict[str, Any] = {
        "id": "test_fish", "name": "测试鱼", "rarity": "normal",
        "size_min": 1.0, "size_max": 2.0, "weight_min": 0.1, "weight_max": 0.5,
        "seasons": ["spring", "winter"], "periods": ["night"],
        "hours": ["00:00-24:00"], "spots": ["gp_a", "gp_b"],
        "preferred_bait": ["饵_蚯蚓", "饵_面包"], "codex_text": None,
    }
    text = fishing_to_csv([row])
    # 用 csv.reader 正规解析单元格（含逗号字段会被标准引用包裹）
    parsed = list(csv.reader(text.splitlines()))
    assert parsed[1][7] == "spring,winter"
    assert parsed[1][10] == "gp_a,gp_b"
    assert parsed[1][11] == "饵_蚯蚓,饵_面包"
    back = csv_to_fishing(text)
    assert back[0]["seasons"] == ["spring", "winter"]
    assert back[0]["spots"] == ["gp_a", "gp_b"]
    assert back[0]["preferred_bait"] == ["饵_蚯蚓", "饵_面包"]


def test_codex_text_single_json_cell() -> None:
    """codex_text 为单个 JSON 单元格（往返 dict 逐键一致）。"""
    row: Dict[str, Any] = {
        "id": "test_fish", "name": "测试鱼", "rarity": "rare",
        "size_min": 1.0, "size_max": 2.0, "weight_min": 0.1, "weight_max": 0.5,
        "seasons": [], "periods": [], "hours": ["00:00-24:00"],
        "spots": ["gp_a"], "preferred_bait": [],
        "codex_text": {
            "desc": "测试描述，含逗号，与引号\"。",
            "unit": "cm-kg",
            "best_mask": "{name} · 最大 {best_size}cm/{best_weight}kg",
        },
    }
    text = fishing_to_csv([row])
    back = csv_to_fishing(text)
    assert back[0]["codex_text"] == row["codex_text"]


def test_codex_text_none_roundtrip() -> None:
    """codex_text=None 往返后仍为 None。"""
    row: Dict[str, Any] = {
        "id": "test_fish", "name": "测试鱼", "rarity": "normal",
        "size_min": 1.0, "size_max": 2.0, "weight_min": 0.1, "weight_max": 0.5,
        "seasons": [], "periods": [], "hours": ["00:00-24:00"],
        "spots": ["gp_a"], "preferred_bait": [], "codex_text": None,
    }
    text = fishing_to_csv([row])
    back = csv_to_fishing(text)
    assert back[0]["codex_text"] is None


def test_numeric_float_precision_roundtrip() -> None:
    """数值列 float 往返精度保持（10.0/60.0/0.3/5.0）。"""
    row: Dict[str, Any] = {
        "id": "test_fish", "name": "测试鱼", "rarity": "gold",
        "size_min": 10.0, "size_max": 60.0, "weight_min": 0.3, "weight_max": 5.0,
        "seasons": [], "periods": [], "hours": ["00:00-24:00"],
        "spots": ["gp_a"], "preferred_bait": [], "codex_text": None,
    }
    back = csv_to_fishing(fishing_to_csv([row]))[0]
    assert back["size_min"] == 10.0
    assert back["size_max"] == 60.0
    assert back["weight_min"] == 0.3
    assert back["weight_max"] == 5.0
    assert isinstance(back["size_min"], float)


# ---------------------------------------------------------------------------
# 空数组语义（TC-02）/ 多行 / 空输入
# ---------------------------------------------------------------------------
def test_empty_arrays_preserved_tc02() -> None:
    """seasons/periods 空数组=不限制：往返后仍为 []（TC-02）。"""
    row: Dict[str, Any] = {
        "id": "all_season", "name": "四季鱼", "rarity": "normal",
        "size_min": 1.0, "size_max": 3.0, "weight_min": 0.1, "weight_max": 0.4,
        "seasons": [], "periods": [],
        "hours": ["00:00-24:00"], "spots": ["gp_a"],
        "preferred_bait": [], "codex_text": None,
    }
    text = fishing_to_csv([row])
    assert text.splitlines()[1].split(",")[7] == ""  # seasons 空串
    assert text.splitlines()[1].split(",")[8] == ""  # periods 空串
    back = csv_to_fishing(text)
    assert back[0]["seasons"] == []
    assert back[0]["periods"] == []
    assert back[0]["preferred_bait"] == []


def test_multiple_rows_roundtrip_order_preserved() -> None:
    """多行 round trip：行数与顺序保持。"""
    rows = _demo_species()
    row2: Dict[str, Any] = {
        "id": "extra_fish", "name": "额外鱼", "rarity": "rare",
        "size_min": 5.0, "size_max": 9.0, "weight_min": 0.5, "weight_max": 2.0,
        "seasons": [], "periods": [], "hours": ["06:00-18:00"],
        "spots": ["gp_b"], "preferred_bait": [], "codex_text": None,
    }
    all_rows = rows + [row2]
    back = csv_to_fishing(fishing_to_csv(all_rows))
    assert [r["id"] for r in back] == ["silver_carp", "extra_fish"]
    assert back[1]["hours"] == ["06:00-18:00"]


def test_empty_input_returns_empty_list() -> None:
    """空输入/纯表头 → []。"""
    assert csv_to_fishing("") == []
    assert csv_to_fishing(",".join(CSV_COLUMNS) + "\n") == []
    assert csv_to_fishing("\n\n\n") == []


# ---------------------------------------------------------------------------
# 非法行容错 / strict
# ---------------------------------------------------------------------------
def test_malformed_row_skipped_tolerant() -> None:
    """列数不符的非法行默认跳过（容错），合法行保留。"""
    header = ",".join(CSV_COLUMNS)
    valid = (
        "silver_carp,银鳞鲤,normal,10.0,60.0,0.3,5.0,"
        "spring,dawn,00:00-24:00,gp_moon_grass,饵_蚯蚓,{}"
    )
    bad_short = "a,b,c"  # 3 列
    bad_long = ",".join(["x"] * 20)  # 20 列
    text = "\n".join([header, valid, bad_short, bad_long, ""])
    back = csv_to_fishing(text)
    assert [r["id"] for r in back] == ["silver_carp"]


def test_strict_mode_raises_on_malformed() -> None:
    """strict=True 时非法行抛 ValueError。"""
    header = ",".join(CSV_COLUMNS)
    text = "\n".join([header, "a,b,c"])
    with pytest.raises(ValueError):
        csv_to_fishing(text, strict=True)


def test_illegal_numeric_row_skipped_tolerant() -> None:
    """非数值 size 列默认跳过（容错）；合法行保留。"""
    header = ",".join(CSV_COLUMNS)
    bad = "bad_fish,坏鱼,normal,abc,60.0,0.3,5.0,,,00:00-24:00,gp_a,,{}"
    valid = (
        "ok_fish,好鱼,normal,1.0,2.0,0.1,0.5,,,00:00-24:00,gp_a,,{}"
    )
    back = csv_to_fishing("\n".join([header, bad, valid]))
    assert [r["id"] for r in back] == ["ok_fish"]


def test_deterministic_output() -> None:
    """同输入两次导出文本一致（确定性）。"""
    rows = _demo_species()
    assert fishing_to_csv(rows) == fishing_to_csv(rows)


def test_demo_fishing_json_top_structure() -> None:
    """test_demo fishing.json 顶层结构（schema_version/species/king）。"""
    data = _load_demo_fishing()
    assert data["schema_version"] == "1.0"
    assert isinstance(data["species"], list) and len(data["species"]) >= 1
    # M10 批4 路4B：king 表已有 1 条鱼王（king_carp → lake_leech）
    assert isinstance(data["king"], list)
    assert len(data["king"]) >= 1
    assert data["king"][0]["species_id"] == "silver_carp"
    assert data["king"][0]["enemy_id"] == "lake_leech"
