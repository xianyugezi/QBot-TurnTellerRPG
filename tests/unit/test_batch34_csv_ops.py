"""批34 · 通用 CSV 导入 / 导出编排层（`qbot_rpg/web/csv_ops.py`）。

覆盖：
  · 导出只读（不改内容包、不生成 .bak）+ UTF-8 BOM + 列头 = 元数据字段；
  · 往返等价（临时内容根清空 → 导入 → 与原始数据逐字段一致）；
  · 行序（append 保持 CSV 行序；insert 插入指定位置）；
  · 逐行引用缺失 → 整批拒绝 + 文件未动 + 不生成备份；
  · 冲突默认跳过（列明细）/ 显式覆盖才写；
  · 公式注入（恶意样例：=cmd|... / +1+1 / -2 / @SUM(A1)）导出/导入中和；
  · 编码自动检测（UTF-8 BOM / GBK）；
  · object 模块如实不支持。

全部写盘只在 tmp_path（自建通用包），绝不触碰仓库 content/（批19.1 防污染门禁）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, List

import pytest

from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
from qbot_rpg.web import api, csv_ops

# 通用元数据（不写死任何真实内容包模块/字段名）：alpha 含列表/对象/引用字段
META = FieldMetaTable(modules={
    "alpha": ModuleMeta(entry_type="list", id_field="id", kind="alpha", fields={
        "id": FieldMeta(type="str", required=True, label="标识"),
        "name": FieldMeta(type="str", label="名称"),
        "price": FieldMeta(type="number", label="价格"),
        "tags": FieldMeta(type="list", element=FieldMeta(type="str"), label="标签"),
        "size": FieldMeta(type="obj", soft_label=True, children={
            "w": FieldMeta(type="number", label="宽"),
            "h": FieldMeta(type="number", label="高"),
        }, label="尺寸"),
        "effect": FieldMeta(type="ref", ref_target="effect", label="效果"),
        "note": FieldMeta(type="str", soft_label=True, label="备注"),
    }),
    "effect": ModuleMeta(entry_type="list", id_field="id", kind="effect", fields={
        "id": FieldMeta(type="str", required=True, label="标识"),
        "name": FieldMeta(type="str", label="名称"),
    }),
    "beta": ModuleMeta(entry_type="map", id_field="id", kind="beta",
                       value_meta=FieldMeta(type="obj", children={
                           "name": FieldMeta(type="str", label="名称"),
                           "base": FieldMeta(type="number", label="基础"),
                       })),
    "gamma": ModuleMeta(entry_type="object", fields={"a": FieldMeta(type="str")}),
})

ALPHA = [
    {"id": "a1", "name": "甲", "price": 1.5, "tags": ["x", "y"],
     "size": {"w": 1, "h": 2}, "effect": "e1"},
    {"id": "a2", "name": "", "price": 0, "tags": [], "size": None, "note": None},
]
EFFECT = [{"id": "e1", "name": "效果一"}]
BETA = {"b1": {"name": "力", "base": 10}, "b2": {"name": "敏", "base": 12}}


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _pack(tmp_path: Path, modules: List[str]) -> Path:
    pkg = tmp_path / "pack_csv"
    pkg.mkdir()
    _write(pkg / "manifest.json", {
        "name": "C", "version": "1", "schema_version": 1, "modules": modules})
    if "alpha" in modules:
        _write(pkg / "alpha.json", ALPHA)
    if "effect" in modules:
        _write(pkg / "effect.json", EFFECT)
    if "beta" in modules:
        _write(pkg / "beta.json", BETA)
    if "gamma" in modules:
        _write(pkg / "gamma.json", {"a": "x"})
    return tmp_path


@pytest.fixture()
def pack_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(api, "_META_TABLE", META)
    return _pack(tmp_path, ["alpha", "effect", "beta", "gamma"])


# =====================================================================================
# 导出
# =====================================================================================
def test_export_is_read_only_and_has_bom(pack_root: Path) -> None:
    pkg = pack_root / "pack_csv"
    before = (pkg / "alpha.json").read_bytes()
    res = csv_ops.export_csv("pack_csv", "alpha", root=pack_root)
    assert res["ok"] and res["count"] == 2
    assert res["text"].startswith("\ufeff")
    assert res["filename"] == "pack_csv-alpha.csv"
    assert res["columns"][0] == "标识(id)"
    # 只读：文件未动、没有 .bak
    assert (pkg / "alpha.json").read_bytes() == before
    assert not (pkg / "alpha.json.bak").exists()


def test_export_object_module_is_reported_unsupported(pack_root: Path) -> None:
    res = csv_ops.export_csv("pack_csv", "gamma", root=pack_root)
    assert res["ok"] is False
    assert res["errors"][0]["code"] == "csv_module_unsupported"


# =====================================================================================
# 往返等价（含列表/对象字段；临时内容根）
# =====================================================================================
@pytest.mark.parametrize("module", ["alpha", "beta"])
def test_roundtrip_equals_original(pack_root: Path, module: str) -> None:
    pkg = pack_root / "pack_csv"
    original = _read(pkg / f"{module}.json")
    text = csv_ops.export_csv("pack_csv", module, root=pack_root)["text"]
    # 清空（临时内容根）
    _write(pkg / f"{module}.json", [] if isinstance(original, list) else {})
    res = csv_ops.import_csv("pack_csv", module, text, root=pack_root)
    assert res["ok"] is True, res
    assert res["summary"]["success"] == len(original)
    after = _read(pkg / f"{module}.json")
    assert after == original, "往返应逐字段一致"


# =====================================================================================
# 行序
# =====================================================================================
def test_import_keeps_csv_row_order_append(pack_root: Path) -> None:
    pkg = pack_root / "pack_csv"
    csv_text = ("标识(id),名称(name),备注(note)\n"
                "z1,一,1\nz2,二,2\nz3,三,3\n")
    res = csv_ops.import_csv("pack_csv", "alpha", csv_text, root=pack_root)
    assert res["ok"] and res["added"] == ["z1", "z2", "z3"]
    ids = [e["id"] for e in _read(pkg / "alpha.json")]
    assert ids == ["a1", "a2", "z1", "z2", "z3"]


def test_import_insert_at_position_keeps_row_order(pack_root: Path) -> None:
    pkg = pack_root / "pack_csv"
    csv_text = "标识(id),名称(name)\nz1,一\nz2,二\n"
    res = csv_ops.import_csv("pack_csv", "alpha", csv_text, mode="insert",
                             position=1, root=pack_root)
    assert res["ok"], res
    ids = [e["id"] for e in _read(pkg / "alpha.json")]
    assert ids == ["a1", "z1", "z2", "a2"]


def test_import_map_keeps_row_order(pack_root: Path) -> None:
    pkg = pack_root / "pack_csv"
    csv_text = "id,名称(name),基础(base)\nz1,一,1\nz2,二,2\n"
    res = csv_ops.import_csv("pack_csv", "beta", csv_text, root=pack_root)
    assert res["ok"], res
    assert list(_read(pkg / "beta.json").keys()) == ["b1", "b2", "z1", "z2"]


# =====================================================================================
# 引用缺失 → 整批拒绝 + 文件未动 + 不生成备份
# =====================================================================================
def test_missing_ref_rejects_whole_batch_without_touching_disk(pack_root: Path) -> None:
    pkg = pack_root / "pack_csv"
    before = (pkg / "alpha.json").read_bytes()
    csv_text = ("标识(id),名称(name),效果(effect)\n"
                "z1,一,e1\n"
                "z2,二,e_missing\n")
    res = csv_ops.import_csv("pack_csv", "alpha", csv_text, root=pack_root)
    assert res["ok"] is False
    assert res["summary"]["failed"] >= 1
    bad = [e for e in res["errors"] if e["code"] == "csv_ref_missing"]
    assert bad and bad[0]["line"] == 3
    assert bad[0]["field"] == "effect" and bad[0]["target"] == "effect"
    assert bad[0]["missing"] == "e_missing"
    # 写盘四断言：文件未动 / 不生成备份 / 无写入 / 明确失败
    assert (pkg / "alpha.json").read_bytes() == before
    assert not (pkg / "alpha.json.bak").exists()
    assert res["written"] == []


def test_missing_ref_message_is_human_with_line_and_field(pack_root: Path) -> None:
    res = csv_ops.import_csv(
        "pack_csv", "alpha",
        "标识(id),效果(effect)\nz1,e_missing\n", root=pack_root)
    msg = res["errors"][0]["message"]
    assert "第 2 行" in msg and "效果" in msg and "e_missing" in msg


# =====================================================================================
# 冲突
# =====================================================================================
def test_conflict_default_skip_lists_rows(pack_root: Path) -> None:
    pkg = pack_root / "pack_csv"
    before = _read(pkg / "alpha.json")
    csv_text = "标识(id),名称(name)\na1,改名了\nz9,新的\n"
    res = csv_ops.import_csv("pack_csv", "alpha", csv_text, root=pack_root)
    assert res["ok"] is True
    assert res["summary"] == {"total": 2, "success": 1, "skipped": 1, "failed": 0}
    assert res["skipped"][0]["entry_id"] == "a1"
    after = _read(pkg / "alpha.json")
    assert after[0] == before[0], "默认跳过不得覆盖同 id 条目"
    assert [e["id"] for e in after] == ["a1", "a2", "z9"]


def test_conflict_overwrite_writes_in_place(pack_root: Path) -> None:
    pkg = pack_root / "pack_csv"
    csv_text = "标识(id),名称(name),备注(note)\na1,改名了,新备注\n"
    res = csv_ops.import_csv("pack_csv", "alpha", csv_text,
                             on_conflict="overwrite", root=pack_root)
    assert res["ok"] and res["overwritten"] == ["a1"]
    after = _read(pkg / "alpha.json")
    assert after[0]["id"] == "a1" and after[0]["name"] == "改名了"
    assert after[1]["id"] == "a2", "覆盖是原地替换，不改行序"


def test_duplicate_id_in_csv_is_rejected(pack_root: Path) -> None:
    csv_text = "标识(id),名称(name)\nz1,一\nz1,二\n"
    res = csv_ops.import_csv("pack_csv", "alpha", csv_text, root=pack_root)
    assert res["ok"] is False
    assert any(e["code"] == "csv_id_duplicate" for e in res["errors"])


# =====================================================================================
# 公式注入（恶意样例；贴原始输出）
# =====================================================================================
DANGEROUS = ["=cmd|' /C calc'!A0", "+1+1", "-2", "@SUM(A1)"]


def test_export_neutralizes_dangerous_cells_raw_output(pack_root: Path) -> None:
    pkg = pack_root / "pack_csv"
    _write(pkg / "alpha.json", [{"id": f"d{i}", "name": "恶意", "note": d}
                                for i, d in enumerate(DANGEROUS)])
    res = csv_ops.export_csv("pack_csv", "alpha", root=pack_root)
    raw = res["text"]
    print("\n=== 导出原始输出（前 3 行）===")
    print("\n".join(raw.splitlines()[:4]))
    for danger in DANGEROUS:
        assert ("'" + danger) in raw, f"{danger} 未被中和"
    # 往返：中和仅在 CSV 边界，导入后还原为原文（内容包本身不存 `'`）
    out = csv_ops.export_csv("pack_csv", "alpha", root=pack_root)["text"]
    _write(pkg / "alpha.json", [])
    imp = csv_ops.import_csv("pack_csv", "alpha", out, root=pack_root)
    assert imp["ok"]
    assert [e["note"] for e in _read(pkg / "alpha.json")] == DANGEROUS


def test_import_raw_dangerous_cells_are_neutralized_before_write(pack_root: Path) -> None:
    pkg = pack_root / "pack_csv"
    # 裸危险 CSV（不是我们导出的）→ 写包前中和为 `'` 前缀
    body = "\n".join(f"r{i},{d}" for i, d in enumerate(DANGEROUS))
    csv_text = "标识(id),备注(note)\n" + body + "\n"
    res = csv_ops.import_csv("pack_csv", "alpha", csv_text, root=pack_root)
    assert res["ok"], res
    notes = [e.get("note") for e in _read(pkg / "alpha.json") if e["id"].startswith("r")]
    print("\n=== 导入写包后的 note（原始输出）===")
    print(notes)
    assert notes == ["'" + d for d in DANGEROUS]


# =====================================================================================
# 编码自动检测（§6.11）
# =====================================================================================
def test_import_detects_gbk(pack_root: Path) -> None:
    pkg = pack_root / "pack_csv"
    body = "标识(id),名称(name)\nz1,中文名\n"
    res = csv_ops.import_csv("pack_csv", "alpha", body.encode("gb18030"), root=pack_root)
    assert res["ok"] and res["encoding"] == "gb18030"
    assert _read(pkg / "alpha.json")[-1]["name"] == "中文名"


def test_import_utf8_bom(pack_root: Path) -> None:
    body = "\ufeff标识(id),名称(name)\nz1,甲\n"
    res = csv_ops.import_csv("pack_csv", "alpha", body.encode("utf-8"), root=pack_root)
    assert res["ok"] and res["encoding"] == "utf-8-sig"


def test_import_unknown_encoding_rejected(pack_root: Path) -> None:
    with pytest.raises(api.BadRequest):
        csv_ops.import_csv("pack_csv", "alpha", b"\xff\xfe\x00\x01\x02", root=pack_root)


# =====================================================================================
# 权限位
# =====================================================================================
def test_import_requires_edit_role(pack_root: Path) -> None:
    with pytest.raises(api.Forbidden):
        csv_ops.import_csv("pack_csv", "alpha", "标识(id)\nz1\n",
                           root=pack_root, role="gm")


# =====================================================================================
# 性能（大模块：339 条）
# =====================================================================================
def test_export_import_timing_on_large_module(pack_root: Path) -> None:
    pkg = pack_root / "pack_csv"
    big = [{"id": f"k{i:04d}", "name": f"技能{i}", "price": i * 0.5,
            "tags": [f"t{i % 7}", f"t{i % 3}"], "size": {"w": i, "h": i + 1},
            "effect": "e1"} for i in range(339)]
    _write(pkg / "alpha.json", big)
    t0 = time.perf_counter()
    exported = csv_ops.export_csv("pack_csv", "alpha", root=pack_root)
    t1 = time.perf_counter()
    assert exported["ok"] and exported["count"] == 339
    _write(pkg / "alpha.json", [])
    t2 = time.perf_counter()
    imported = csv_ops.import_csv("pack_csv", "alpha", exported["text"], root=pack_root)
    t3 = time.perf_counter()
    assert imported["ok"] and imported["summary"]["success"] == 339
    assert _read(pkg / "alpha.json") == big
    print(f"\n=== 339 条：导出 {t1 - t0:.3f}s / 导入 {t3 - t2:.3f}s ===")
    assert (t1 - t0) < 5.0 and (t3 - t2) < 15.0
