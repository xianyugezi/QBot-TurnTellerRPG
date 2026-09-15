"""编辑器重写批16 · #7 自动生成 ID（默认「前缀 + 序号」，拼音为可选附加）测试。

覆盖任务书要求（通用，不写死模块名/字段名）：
  · 默认 =「<前缀>_<序号>」：零填充 3 位（可配置宽度）、取同前缀现有最大序号 + 1、冲突继续递增；
  · 前缀来源两条路径：包声明（field_meta.json 的 id_prefix[模块]/预设 id_prefix）优先；
    未声明 → 由模块 id 归一推导（小写、非字母数字转下划线）；
  · 非法字符归一（小写 + 下划线）；查重与既有规则一致；
  · 拼音为**可选附加**：可用时按中文名生成拼音 id；多音字/失败/未装库 → 回落
    「前缀 + 序号」且明确提示；未装库不得报错；
  · 只影响新建：既有 id 一律不动（负向断言：只读接口不写盘、原文件逐字节不变）；
  · 规则与兜底写进 docstring（本测试对生成函数做最小契约断言）。
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
from qbot_rpg.web import api

# 通用合成元数据（不含任何业务包专属名）：
#   things  = 无 kind / 无声明前缀 → 走「模块 id 归一推导」路径
#   gadgets = kind="gadget"        → 走框架 kind 兜底
META = FieldMetaTable(
    modules={
        "things": ModuleMeta(entry_type="list", fields={
            "id": FieldMeta(type="str", required=True, label="标识"),
            "name": FieldMeta(type="str", label="名称"),
        }),
        "gadgets": ModuleMeta(entry_type="list", kind="gadget", fields={
            "id": FieldMeta(type="str", required=True, label="标识"),
            "name": FieldMeta(type="str", label="名称"),
        }),
    },
)

THINGS = [{"id": "mat_001", "name": "甲"}, {"id": "mat_002", "name": "乙"}]
GADGETS = [{"id": "gadget_005", "name": "部件"}]


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture()
def pack_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    pkg = tmp_path / "pack_a"
    pkg.mkdir()
    _write(pkg / "manifest.json", {
        "name": "A", "version": "1", "schema_version": 1,
        "modules": ["things", "gadgets"],
    })
    _write(pkg / "things.json", THINGS)
    _write(pkg / "gadgets.json", GADGETS)
    monkeypatch.setattr(api, "_META_TABLE", META)
    monkeypatch.setattr(api, "default_field_meta_table", lambda: META)
    monkeypatch.setattr(api, "_MERGED_TABLES", {})
    return tmp_path


@pytest.fixture()
def declared_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """带包声明的包：things 声明 id_prefix=mat / id_width=4（包声明优先于模块推导）。"""
    pkg = tmp_path / "pack_decl"
    pkg.mkdir()
    _write(pkg / "manifest.json", {
        "name": "D", "version": "1", "schema_version": 1, "modules": ["things", "gadgets"],
    })
    _write(pkg / "things.json", THINGS)
    _write(pkg / "gadgets.json", GADGETS)
    _write(pkg / "field_meta.json", {
        "schema_version": 1,
        "id_prefix": {"things": "mat"},
        "id_width": {"things": 4},
    })
    monkeypatch.setattr(api, "_META_TABLE", META)
    monkeypatch.setattr(api, "default_field_meta_table", lambda: META)
    monkeypatch.setattr(api, "_MERGED_TABLES", {})
    return tmp_path


# ---------------------------------------------------------------------------
# 一、纯生成函数：前缀 + 序号 / 零填充 / 递增 / 归一
# ---------------------------------------------------------------------------
def test_default_is_prefix_plus_padded_sequence() -> None:
    mm = META.module("things")
    # 模块名归一推导（无 kind/无声明）：小写 + 下划线
    assert api.suggest_entry_id("things", mm, "任意中文名", set()) == "things_001"
    # 同前缀现有最大序号 + 1（不区分零填充）
    assert api.suggest_entry_id("things", mm, "x", {"things_001", "things_002"}) == "things_003"
    assert api.suggest_entry_id("things", mm, "x", {"things_0007"}) == "things_008"
    # 冲突（最大序号之后的候选已被占用）→ 继续递增直到唯一
    assert api.suggest_entry_id("things", mm, "x",
                               {"things_001", "things_002", "things_003"}) == "things_004"


def test_zero_padding_width_configurable() -> None:
    mm = META.module("things")
    assert api.suggest_entry_id("things", mm, "x", set(), id_width=1) == "things_1"
    assert api.suggest_entry_id("things", mm, "x", set(), id_width=5) == "things_00001"
    # 序号超过宽度位数 → 按实际位数输出，不截断
    assert api.suggest_entry_id("things", mm, "x", {"things_999"},
                               id_width=3) == "things_1000"


def test_prefix_normalization_lowercases_and_underscores() -> None:
    mm = META.module("things")
    assert api.suggest_entry_id("things", mm, "x", set(),
                               id_prefix="My Prefix!") == "my_prefix_001"
    assert api.suggest_entry_id("things", mm, "x", set(),
                               id_prefix="A-B__C") == "a_b_c_001"


def test_prefix_source_module_derivation_vs_framework_kind() -> None:
    # 无 kind → 模块 id 推导；有 kind → 框架 kind 兜底
    assert api.suggest_entry_id("things", META.module("things"), "x", set()) == "things_001"
    assert api.suggest_entry_id("gadgets", META.module("gadgets"), "x", set()) == "gadget_001"


def test_declared_slug_rule_keeps_name_slug_behaviour() -> None:
    slug = ModuleMeta(entry_type="list", id_rule="slug", id_prefix="fx")
    assert api.suggest_entry_id("m", slug, "Sword Aura", set()) == "sword_aura"
    assert api.suggest_entry_id("m", slug, "Sword Aura", {"sword_aura"}) == "sword_aura_2"
    assert api.suggest_entry_id("m", slug, "御剑", set()) == "fx_001"


def test_id_rule_spec_reports_default_width() -> None:
    spec = api.id_rule_spec("things", META.module("things"))
    assert spec["width"] == api.ID_WIDTH_DEFAULT == 3
    assert api.ID_HINT and "前缀" in api.ID_HINT


# ---------------------------------------------------------------------------
# 二、包声明前缀优先（两条来源路径）
# ---------------------------------------------------------------------------
def test_pack_declared_prefix_wins(pack_root: Path, declared_pack: Path) -> None:
    # 未声明包 → 模块推导
    assert api.suggest_id("pack_a", "things", root=pack_root, name="x")["suggested_id"] \
        == "things_001"
    # 包声明 id_prefix=mat / id_width=4 → 覆盖模块推导；序号取 mat_ 现有最大 + 1
    out = api.suggest_id("pack_decl", "things", root=declared_pack, name="x")
    assert out["suggested_id"] == "mat_0003"
    assert out["id_rule"]["prefix"] == "mat" and out["id_rule"]["width"] == 4


def test_pack_declared_preset_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pkg = tmp_path / "pack_ps"
    pkg.mkdir()
    _write(pkg / "manifest.json", {"name": "P", "version": "1", "schema_version": 1,
                                   "modules": ["things"]})
    _write(pkg / "things.json", [])
    _write(pkg / "field_meta.json", {
        "schema_version": 1,
        "entry_presets": {"things": [
            {"id": "raw", "label": "原料", "fields": ["name"],
             "defaults": {}, "id_prefix": "ore", "id_width": 2},
        ]},
    })
    monkeypatch.setattr(api, "_META_TABLE", META)
    monkeypatch.setattr(api, "default_field_meta_table", lambda: META)
    monkeypatch.setattr(api, "_MERGED_TABLES", {})
    out = api.suggest_id("pack_ps", "things", root=tmp_path, name="x", preset="raw")
    assert out["suggested_id"] == "ore_01"
    # 不选预设 → 模块推导
    assert api.suggest_id("pack_ps", "things", root=tmp_path,
                          name="x")["suggested_id"] == "things_001"


# ---------------------------------------------------------------------------
# 三、拼音可选附加（桩注入，不依赖真库）
# ---------------------------------------------------------------------------
def _stub_pypinyin(monkeypatch: pytest.MonkeyPatch,
                   result: Any = None, error: Exception | None = None) -> None:
    mod = types.ModuleType("pypinyin")

    class Style:
        NORMAL = 0

    def pinyin(text: str, style: Any = None, heteronym: bool = False) -> Any:
        if error is not None:
            raise error
        return result

    mod.Style = Style  # type: ignore[attr-defined]
    mod.pinyin = pinyin  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypinyin", mod)


def test_pinyin_available_path_generates_pinyin_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "pinyin_available", lambda: True)
    _stub_pypinyin(monkeypatch, result=[["long"], ["lin"], ["jia"]])
    out = api.suggest_pinyin_id("m", None, "龙鳞甲", set(), id_prefix="item")
    assert out["suggested_id"] == "long_lin_jia" and out["used_pinyin"] is True
    # 查重与既有规则一致：重复 → 追加序号
    out2 = api.suggest_pinyin_id("m", None, "龙鳞甲", {"long_lin_jia"}, id_prefix="item")
    assert out2["suggested_id"] == "long_lin_jia_2"


def test_pinyin_multi_reading_falls_back_with_note(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_pypinyin(monkeypatch, result=[["xing", "hang"]])
    out = api.suggest_pinyin_id("m", None, "行", set(), id_prefix="item")
    assert out["used_pinyin"] is False
    assert out["suggested_id"] == "item_001" and "多音字" in out["note"]


def test_pinyin_conversion_error_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_pypinyin(monkeypatch, error=RuntimeError("boom"))
    out = api.suggest_pinyin_id("m", None, "名字", set(), id_prefix="item")
    assert out["used_pinyin"] is False and out["suggested_id"] == "item_001"
    assert "拼音转换失败" in out["note"]


def test_pinyin_missing_library_falls_back_without_error(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pypinyin", None)  # 模拟未装库：from ... import 抛 ImportError
    out = api.suggest_pinyin_id("m", None, "名字", set(), id_prefix="item")
    assert out["used_pinyin"] is False and out["suggested_id"] == "item_001"
    assert "未安装拼音库" in out["note"]


def test_suggest_id_endpoint_pinyin_mode(pack_root: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "pinyin_available", lambda: True)
    _stub_pypinyin(monkeypatch, result=[["jia"], ["cai"]])
    out = api.suggest_id("pack_a", "things", root=pack_root, name="加才", mode="pinyin")
    assert out["mode"] == api.ID_MODE_PINYIN
    assert out["suggested_id"] == "jia_cai" and out["used_pinyin"] is True
    assert out["pinyin_available"] is True and out["note"]


def test_suggest_id_endpoint_never_errors_without_library(
        pack_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pypinyin", None)
    out = api.suggest_id("pack_a", "things", root=pack_root, name="名字", mode="pinyin")
    assert out["suggested_id"] == "things_001"
    assert out["used_pinyin"] is False and "已用「前缀 + 序号」" in out["note"]


# ---------------------------------------------------------------------------
# 四、只影响新建（负向断言：既有 id / 原文件逐字节不变）
# ---------------------------------------------------------------------------
def test_suggest_is_read_only_and_existing_ids_untouched(pack_root: Path) -> None:
    before = (pack_root / "pack_a" / "things.json").read_bytes()
    for name in ("甲", "乙", "丙"):
        api.suggest_id("pack_a", "things", root=pack_root, name=name)
        api.new_entry_detail("pack_a", "things", root=pack_root, name=name)
    assert (pack_root / "pack_a" / "things.json").read_bytes() == before
    assert [e["id"] for e in json.loads(before)] == ["mat_001", "mat_002"]
    # 建议 id 一定落在「未占用」集合里（不会与既有 id 相撞）
    sug = api.suggest_id("pack_a", "things", root=pack_root, name="甲")
    assert sug["suggested_id"] not in {"mat_001", "mat_002"}


def test_new_entry_detail_uses_pack_prefix(declared_pack: Path) -> None:
    d = api.new_entry_detail("pack_decl", "things", root=declared_pack, name="x")
    assert d["suggested_id"] == "mat_0003"
    assert d["id_rule"]["prefix"] == "mat" and d["id_rule"]["width"] == 4
