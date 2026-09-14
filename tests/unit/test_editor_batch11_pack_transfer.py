"""编辑器重写批11 · 内容包导出 / 导入（分享内容包；安全防护逐条回归）。

覆盖任务书要求：
  A. **导出**：包目录全部 `*.json` + `*.md` → 一个 `.ttrpack`（zip）+ `export_meta.json`
     （包 id / 名称 / 版本 / TTR 版本或提交号 / 导出时间 / 文件清单与 sha256）；
     文件名含包名与日期；导出只读、不改内容包。
  B. **导入**：结构安全 → `export_meta`/`manifest` 合法 → 过内容校验器 → 冲突处理
     （改名 / 覆盖且先备份）；落盘 = 临时目录写全 → 原子搬成 `content/<id>`。
  C. **安全（逐条）**：Zip Slip（`../`、绝对路径、盘符、符号链接）/ 文件类型白名单
     （只收 `.json`/`.md`）/ 体积上限（压缩包、单文件、解压总量、条目数、压缩比）/
     完整性（sha256 不符、缺文件、多文件）/ 失败不留半成品目录。
  D. **权限**：导出 GM 只读也允许；导入必须 owner（GM → Forbidden 403，HTTP 403）。
  E. **HTTP 端点**：`GET …/export` 下载 + `POST /api/pack/import` 上传（原始字节）+
     冲突人话结果 + 导入后 `/api/packs` 立即可见。
  F. **通用性**：不写死任何包名；两个真实包拷贝各自往返等价。

纪律：**所有写入都在 tmp_path**（真实内容包只读拷贝）；跑完断言真实 `content/` 未变。
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pytest

from qbot_rpg.content import pack_transfer as pt
from qbot_rpg.web import api, editor_ops

_REPO = Path(api.repo_root())
_REAL_CONTENT = _REPO / "content"
FIXED_NOW = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
_SYS_PATH_READY = False


def _ensure_scripts_on_path() -> None:
    global _SYS_PATH_READY
    if _SYS_PATH_READY:
        return
    for p in (str(_REPO), str(_REPO / "scripts")):
        if p not in sys.path:
            sys.path.insert(0, p)
    _SYS_PATH_READY = True


# =====================================================================================
# 构造工具（全部在 tmp_path）
# =====================================================================================
def _write_pack(root: Path, pid: str = "pack_a", name: str = "测试包A",
                modules: Tuple[str, ...] = (), files: Optional[Dict[str, str]] = None,
                field_meta: Optional[object] = None) -> Path:
    """写一个最小内容包目录（默认零模块 → 过校验器）。"""
    root.mkdir(parents=True, exist_ok=True)
    d = root / pid
    d.mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "version": "1.0.0", "schema_version": 1,
                "modules": list(modules)}
    (d / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    for fname, text in (files or {}).items():
        (d / fname).write_text(text, encoding="utf-8")
    if field_meta is not None:
        (d / "field_meta.json").write_text(
            json.dumps(field_meta, ensure_ascii=False), encoding="utf-8")
    return d


def _export(tmp: Path, pid: str = "pack_a", name: str = "测试包A") -> bytes:
    d = _write_pack(tmp / "src", pid, name)
    res = pt.export_pack_dir(d, now=FIXED_NOW, ttr_commit_hash="deadbeef")
    assert res["ok"], res
    return res["data"]


def _zip_entries(data: bytes) -> Dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {zi.filename: zf.read(zi)
                for zi in zf.infolist() if not zi.is_dir()}


def _repackage(entries: Dict[str, bytes],
               symlinks: Optional[Dict[str, bytes]] = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, raw in entries.items():
            zf.writestr(name, raw)
        for name, blob in (symlinks or {}).items():
            zi = zipfile.ZipInfo(name)
            zi.external_attr = 0o120777 << 16
            zi.create_system = 3   # Unix：文件类型位可被识别为符号链接
            zf.writestr(zi, blob)
    return buf.getvalue()


def _resign(entries: Dict[str, bytes]) -> Dict[str, bytes]:
    """重算 export_meta.json 的文件清单（让改动后的包在完整性上自洽）。"""
    out = dict(entries)
    meta = json.loads(out["export_meta.json"])
    rows: List[Dict[str, Any]] = []
    for name in sorted(out):
        if name == pt.EXPORT_META_NAME:
            continue
        raw = out[name]
        rows.append({"path": name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    meta["files"] = rows
    meta["file_count"] = len(rows)
    meta["total_bytes"] = sum(r["size"] for r in rows)
    out[pt.EXPORT_META_NAME] = json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")
    return out


def _dst(tmp_path: Path) -> Path:
    """导入目标内容根（存在即可；import_archive 要求它是已存在目录）。"""
    d = tmp_path / "dst"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _tree(root: Path) -> List[str]:
    """内容根下全部路径（相对、排序）——用于断言「失败不留残留」。"""
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def _no_residue(root: Path, before: List[str]) -> None:
    assert _tree(root) == before, "失败后留下了残留（临时目录 / 半成品包 / 备份）"
    assert not list(root.glob(pt.TMP_PREFIX + "*")), "临时目录未清理"


def _error_codes(res: Dict[str, Any]) -> List[str]:
    return [str(e.get("code") or "") for e in res.get("errors") or []]


def _codes_include(res: Dict[str, Any], *codes: str) -> bool:
    got = set(_error_codes(res))
    return any(c in got for c in codes)


# =====================================================================================
# A. 导出
# =====================================================================================
def test_export_meta_fields_and_filename(tmp_path: Path) -> None:
    d = _write_pack(tmp_path / "src", "my_pack", "我的包",
                    files={"skills.json": "[]", "README.md": "# hi\n"})
    res = pt.export_pack_dir(d, now=FIXED_NOW, ttr_commit_hash="cafebabe")
    assert res["ok"] and res["data"][:2] == b"PK"
    meta = res["meta"]
    assert meta["format"] == pt.FORMAT_NAME and meta["format_version"] == pt.FORMAT_VERSION
    assert meta["pack_id"] == "my_pack" and meta["pack_name"] == "我的包"
    assert meta["pack_version"] == "1.0.0"
    assert meta["ttr_version"] and meta["ttr_commit"] == "cafebabe"
    assert meta["exported_at"].startswith("2026-09-14T12:00:00")
    assert meta["file_count"] == len(meta["files"]) == 3
    names = {f["path"] for f in meta["files"]}
    assert names == {"manifest.json", "skills.json", "README.md"}
    for f in meta["files"]:
        raw = (d / f["path"]).read_bytes()
        assert f["size"] == len(raw) and f["sha256"] == hashlib.sha256(raw).hexdigest()
    # 文件名含包 id 与日期（中文名取不出 ASCII → 回退包 id）
    assert res["filename"] == "my_pack-20260914.ttrpack"
    assert "20260914" in res["filename"] and "my_pack" in res["filename"]


def test_export_filename_includes_ascii_pack_name() -> None:
    assert pt.export_filename("alpha", "Alpha Pack", now=FIXED_NOW) == \
        "Alpha-Pack-alpha-20260914.ttrpack"


def test_export_does_not_touch_pack_dir(tmp_path: Path) -> None:
    d = _write_pack(tmp_path / "src", "pack_a", files={"x.json": "{}", "y.md": "y"})
    (d / "manifest.json.bak").write_text("{}", encoding="utf-8")
    (d / "sub").mkdir()
    (d / "sub" / "nested.json").write_text("{}", encoding="utf-8")
    (d / "notes.txt").write_text("nope", encoding="utf-8")
    before = _tree(d)
    res = pt.export_pack_dir(d, now=FIXED_NOW, ttr_commit_hash="x")
    assert res["ok"]
    # 只收顶层 .json/.md：不含 .bak / 子目录 / .txt
    assert {f["path"] for f in res["files"]} == {"manifest.json", "x.json", "y.md"}
    assert _tree(d) == before, "导出不得改动内容包目录"


def test_export_rejects_missing_manifest(tmp_path: Path) -> None:
    d = tmp_path / "src" / "no_manifest"
    d.mkdir(parents=True)
    res = pt.export_pack_dir(d, now=FIXED_NOW, ttr_commit_hash="x")
    assert not res["ok"] and _codes_include(res, "manifest_invalid")


def test_export_pack_dir_symlink_skipped(tmp_path: Path) -> None:
    d = _write_pack(tmp_path / "src", "pack_a", files={"x.json": "{}"})
    target = tmp_path / "outside.json"
    target.write_text("SECRET", encoding="utf-8")
    try:
        (d / "link.json").symlink_to(target)
    except OSError:
        pytest.skip("本环境不支持符号链接")
    res = pt.export_pack_dir(d, now=FIXED_NOW, ttr_commit_hash="x")
    assert res["ok"] and "link.json" not in {f["path"] for f in res["files"]}


# =====================================================================================
# B. 正常往返：导出 → 导入 → 逐字节等价
# =====================================================================================
@pytest.mark.parametrize("real_pack", ["demo_full", "demo_lv30"])
def test_round_trip_bytewise(tmp_path: Path, real_pack: str) -> None:
    """真实内容包拷贝到 tmp → 导出 → 导入到空内容根 → 每个文件逐字节等价。"""
    src_root = tmp_path / "src_content"
    shutil.copytree(_REAL_CONTENT / real_pack, src_root / real_pack)
    before = _tree(src_root)
    res = pt.export_pack_dir(src_root / real_pack, now=FIXED_NOW, ttr_commit_hash="rt")
    assert res["ok"]
    assert _tree(src_root) == before, "导出不得改动源包"

    dst_root = tmp_path / "dst_content"
    dst_root.mkdir()
    imp = pt.import_archive(res["data"], dst_root, now=FIXED_NOW)
    assert imp["ok"], imp
    assert imp["pack_id"] == real_pack and imp["file_count"] == len(res["files"])
    # 目标包目录不含 export_meta.json（它是传输元信息，不是包内容）
    assert not (dst_root / real_pack / pt.EXPORT_META_NAME).exists()
    src_files = sorted(p.relative_to(src_root / real_pack)
                       for p in (src_root / real_pack).iterdir() if p.is_file())
    dst_files = sorted(p.relative_to(dst_root / real_pack)
                       for p in (dst_root / real_pack).iterdir() if p.is_file())
    assert src_files == dst_files
    for rel in src_files:
        assert (dst_root / real_pack / rel).read_bytes() == \
            (src_root / real_pack / rel).read_bytes(), f"字节不等价：{rel}"


def test_round_trip_manifest_and_field_meta_preserved(tmp_path: Path) -> None:
    d = _write_pack(tmp_path / "src", "meta_pack", "元数据包", modules=(),
                    field_meta={"schema_version": 1, "module_labels": {"skills": "技能"}})
    res = pt.export_pack_dir(d, now=FIXED_NOW, ttr_commit_hash="x")
    assert res["ok"] and "field_meta.json" in {f["path"] for f in res["files"]}
    imp = pt.import_archive(res["data"], _dst(tmp_path), now=FIXED_NOW)
    assert imp["ok"], imp
    got = json.loads((_dst(tmp_path) / "meta_pack" / "field_meta.json").read_text("utf-8"))
    assert got["module_labels"] == {"skills": "技能"}


def test_import_manual_zip_with_single_top_dir(tmp_path: Path) -> None:
    """手动把包目录压成 zip（所有条目在同一个顶层目录下）也能导入。"""
    entries = _zip_entries(_export(tmp_path, "pack_a"))
    prefixed = {"wrapper/" + k: v for k, v in _resign(entries).items()}
    imp = pt.import_archive(_repackage(prefixed), _dst(tmp_path), now=FIXED_NOW)
    assert imp["ok"], imp
    assert (_dst(tmp_path) / "pack_a" / "manifest.json").is_file()


# =====================================================================================
# C1. Zip Slip（越出目标目录的条目一律拒绝）
# =====================================================================================
@pytest.mark.parametrize("evil", [
    "../evil.json",
    "../../evil.json",
    "a/../../evil.json",
    "/abs_evil.json",
    "C:/evil.json",
    "sub/dir/evil.json",       # 非扁平：混层
])
def test_zip_slip_rejected(tmp_path: Path, evil: str) -> None:
    root = _dst(tmp_path)
    before = _tree(root)
    entries = _zip_entries(_export(tmp_path, "pack_a"))
    entries[evil] = json.dumps({"pwned": True}).encode()
    res = pt.import_archive(_repackage(_resign(entries)), root, now=FIXED_NOW)
    assert not res["ok"]
    assert _codes_include(res, "zip_slip", "nested_path", "bad_entry"), res
    _no_residue(root, before)
    # 任何地方都不得出现 evil.json（临时目录之外或之内）
    assert not list(root.rglob("evil.json"))
    assert not list(tmp_path.rglob("abs_evil.json"))
    assert not list(tmp_path.rglob("evil.json"))


def test_symlink_entry_rejected(tmp_path: Path) -> None:
    root = _dst(tmp_path)
    before = _tree(root)
    entries = _zip_entries(_export(tmp_path, "pack_a"))
    data = _repackage(_resign(entries), symlinks={"evil.json": b"/etc/passwd"})
    res = pt.import_archive(data, root, now=FIXED_NOW)
    assert not res["ok"] and _codes_include(res, "symlink"), res
    _no_residue(root, before)


# =====================================================================================
# C2. 文件类型白名单（只收 .json / .md）
# =====================================================================================
@pytest.mark.parametrize("bad", ["evil.py", "run.sh", "tool.exe", "lib.so",
                                  "payload", "a.json.exe"])
def test_unexpected_file_type_rejected(tmp_path: Path, bad: str) -> None:
    root = _dst(tmp_path)
    before = _tree(root)
    entries = _zip_entries(_export(tmp_path, "pack_a"))
    entries[bad] = b"\x7fELF..." if "." in bad else b"data"
    res = pt.import_archive(_repackage(_resign(entries)), root, now=FIXED_NOW)
    assert not res["ok"] and _codes_include(res, "bad_file_type"), res
    _no_residue(root, before)


# =====================================================================================
# C3. 体积上限
# =====================================================================================
def test_archive_too_large(tmp_path: Path) -> None:
    data = _export(tmp_path)
    res = pt.import_archive(data, _dst(tmp_path), now=FIXED_NOW,
                            limits=pt.TransferLimits(max_archive_bytes=8))
    assert not res["ok"] and _codes_include(res, "archive_too_large")
    assert not (_dst(tmp_path) / "pack_a").exists()


def test_file_too_large(tmp_path: Path) -> None:
    entries = _zip_entries(_export(tmp_path))
    entries["big.json"] = b"x" * 5000
    res = pt.import_archive(_repackage(_resign(entries)), _dst(tmp_path), now=FIXED_NOW,
                            limits=pt.TransferLimits(max_file_bytes=1000))
    assert not res["ok"] and _codes_include(res, "file_too_large")


def test_total_too_large(tmp_path: Path) -> None:
    entries = _zip_entries(_export(tmp_path))
    entries["a.json"] = b"a" * 600
    entries["b.json"] = b"b" * 600
    res = pt.import_archive(_repackage(_resign(entries)), _dst(tmp_path), now=FIXED_NOW,
                            limits=pt.TransferLimits(max_total_bytes=1000))
    assert not res["ok"] and _codes_include(res, "total_too_large")


def test_too_many_entries(tmp_path: Path) -> None:
    entries = _zip_entries(_export(tmp_path))
    for i in range(5):
        entries[f"f{i}.json"] = b"{}"
    res = pt.import_archive(_repackage(_resign(entries)), _dst(tmp_path), now=FIXED_NOW,
                            limits=pt.TransferLimits(max_entries=3))
    assert not res["ok"] and _codes_include(res, "too_many_entries")


def test_compression_ratio_guard(tmp_path: Path) -> None:
    """高压缩比（疑似 zip bomb）即使体积不大也拒绝。"""
    entries = _zip_entries(_export(tmp_path))
    entries["bomb.md"] = b"0" * 200000
    res = pt.import_archive(_repackage(_resign(entries)), _dst(tmp_path), now=FIXED_NOW,
                            limits=pt.TransferLimits(max_ratio=5))
    assert not res["ok"] and _codes_include(res, "ratio_too_high")


# =====================================================================================
# C4. 元信息 / 完整性
# =====================================================================================
def test_not_a_zip(tmp_path: Path) -> None:
    res = pt.import_archive(b"this is not a zip at all", _dst(tmp_path), now=FIXED_NOW)
    assert not res["ok"] and _codes_include(res, "bad_zip")


def test_empty_file(tmp_path: Path) -> None:
    res = pt.import_archive(b"", _dst(tmp_path), now=FIXED_NOW)
    assert not res["ok"] and _codes_include(res, "empty")


def test_missing_export_meta(tmp_path: Path) -> None:
    entries = _zip_entries(_export(tmp_path))
    entries.pop(pt.EXPORT_META_NAME)
    res = pt.import_archive(_repackage(entries), _dst(tmp_path), now=FIXED_NOW)
    assert not res["ok"] and _codes_include(res, "export_meta_missing")


@pytest.mark.parametrize("bad_format,code", [
    ("zip", "export_meta_invalid"),
    (None, "export_meta_invalid"),
])
def test_bad_format_field(tmp_path: Path, bad_format: object, code: str) -> None:
    entries = _zip_entries(_export(tmp_path))
    meta = json.loads(entries[pt.EXPORT_META_NAME])
    meta["format"] = bad_format
    entries[pt.EXPORT_META_NAME] = json.dumps(meta).encode()
    res = pt.import_archive(_repackage(entries), _dst(tmp_path), now=FIXED_NOW)
    assert not res["ok"] and _codes_include(res, code)


def test_unsupported_format_version(tmp_path: Path) -> None:
    entries = _zip_entries(_export(tmp_path))
    meta = json.loads(entries[pt.EXPORT_META_NAME])
    meta["format_version"] = 99
    entries[pt.EXPORT_META_NAME] = json.dumps(meta).encode()
    res = pt.import_archive(_repackage(entries), _dst(tmp_path), now=FIXED_NOW)
    assert not res["ok"] and _codes_include(res, "format_version")


def test_integrity_mismatch(tmp_path: Path) -> None:
    entries = _zip_entries(_export(tmp_path))
    entries["manifest.json"] = b'{"name":"tampered","modules":[]}'
    res = pt.import_archive(_repackage(entries), _dst(tmp_path), now=FIXED_NOW)
    assert not res["ok"] and _codes_include(res, "integrity_mismatch")


def test_integrity_missing(tmp_path: Path) -> None:
    entries = _zip_entries(_export(tmp_path))
    entries["extra.json"] = b"{}"
    refreshed = _resign(entries)             # 清单含 extra.json …
    refreshed.pop("extra.json")              # … 但实际文件缺失
    res = pt.import_archive(_repackage(refreshed), _dst(tmp_path), now=FIXED_NOW)
    assert not res["ok"] and _codes_include(res, "integrity_missing")


def test_integrity_extra(tmp_path: Path) -> None:
    entries = _zip_entries(_export(tmp_path))
    entries["sneaky.json"] = b"{}"           # 未登记在清单里
    res = pt.import_archive(_repackage(entries), _dst(tmp_path), now=FIXED_NOW)
    assert not res["ok"] and _codes_include(res, "integrity_extra")


def test_bad_manifest_and_field_meta(tmp_path: Path) -> None:
    root = _dst(tmp_path)
    before = _tree(root)
    # manifest 形态非法
    entries = _zip_entries(_export(tmp_path))
    entries["manifest.json"] = b"[1, 2, 3]"
    res = pt.import_archive(_repackage(_resign(entries)), root, now=FIXED_NOW)
    assert not res["ok"] and _codes_include(res, "manifest_invalid")
    _no_residue(root, before)
    # manifest.modules 非法
    entries = _zip_entries(_export(tmp_path))
    entries["manifest.json"] = b'{"name":"x","modules":"skills"}'
    res = pt.import_archive(_repackage(_resign(entries)), root, now=FIXED_NOW)
    assert not res["ok"] and _codes_include(res, "manifest_invalid")
    # field_meta.json 含未知顶层键
    entries = _zip_entries(_export(tmp_path))
    entries["field_meta.json"] = json.dumps({"schema_version": 1, "bogus": {}}).encode()
    res = pt.import_archive(_repackage(_resign(entries)), root, now=FIXED_NOW)
    assert not res["ok"] and _codes_include(res, "field_meta_invalid"), res
    _no_residue(root, before)


def test_bad_json_module(tmp_path: Path) -> None:
    entries = _zip_entries(_export(tmp_path))
    entries["broken.json"] = b"{not json"
    res = pt.import_archive(_repackage(_resign(entries)), _dst(tmp_path), now=FIXED_NOW)
    assert not res["ok"] and _codes_include(res, "bad_json")


# =====================================================================================
# C5. 内容校验器红拦 → 不落盘
# =====================================================================================
def test_validator_red_blocks_import(tmp_path: Path) -> None:
    """`{"skills": []}` 触发技能库 V-7 红拦 → 拒绝且不留任何东西。"""
    src = tmp_path / "src"
    d = _write_pack(src, "red_pack", "红拦包", modules=("skills",),
                    files={"skills.json": "[]"})
    res = pt.export_pack_dir(d, now=FIXED_NOW, ttr_commit_hash="x")
    assert res["ok"]
    root = _dst(tmp_path)
    before = _tree(root)
    imp = pt.import_archive(res["data"], root, now=FIXED_NOW)
    assert not imp["ok"]
    assert _codes_include(imp, "V-7"), imp
    assert "未写入任何文件" in imp["message"]
    assert all(e["how_to_fix"] for e in imp["errors"])
    _no_residue(root, before)


def test_validator_warnings_pass(tmp_path: Path) -> None:
    """黄提示不拦：真实 veinborn 包导入成功且带回 warnings（不阻断）。"""
    src = tmp_path / "src_content"
    shutil.copytree(_REAL_CONTENT / "veinborn", src_root := src / "veinborn")
    res = pt.export_pack_dir(src_root, now=FIXED_NOW, ttr_commit_hash="x")
    imp = pt.import_archive(res["data"], _dst(tmp_path), now=FIXED_NOW)
    assert imp["ok"], imp
    assert imp["warnings"], "veinborn 有已知黄提示，应如实带回"


# =====================================================================================
# D. 冲突：默认报错 / 改名 / 覆盖（覆盖先备份）
# =====================================================================================
def test_conflict_default_reports_choice(tmp_path: Path) -> None:
    root = _dst(tmp_path)
    _write_pack(root, "pack_a", "旧包", files={"old.json": "{}"})
    before = _tree(root)
    data = _export(tmp_path, "pack_a", "新包")
    res = pt.import_archive(data, root, now=FIXED_NOW)
    assert not res["ok"] and res.get("conflict") is True and res["pack_id"] == "pack_a"
    assert "换个名字导入" in res["errors"][0]["how_to_fix"]
    _no_residue(root, before)


def test_conflict_rename(tmp_path: Path) -> None:
    root = _dst(tmp_path)
    _write_pack(root, "pack_a", "旧包", files={"old.json": "{}"})
    data = _export(tmp_path, "pack_a", "新包")
    res = pt.import_archive(data, root, on_conflict="rename", new_id="pack_copy",
                            now=FIXED_NOW)
    assert res["ok"], res
    assert res["pack_id"] == "pack_copy" and res["overwritten"] is False
    assert (root / "pack_copy" / "manifest.json").is_file()
    assert (root / "pack_a" / "old.json").is_file(), "改名导入不得动原包"
    assert res["backup"] == ""


def test_conflict_rename_invalid_and_taken(tmp_path: Path) -> None:
    root = _dst(tmp_path)
    _write_pack(root, "pack_a", "旧包")
    _write_pack(root, "pack_b", "占位")
    data = _export(tmp_path, "pack_a")
    for bad, code in (("../x", "rename_invalid"), ("pack_b", "rename_exists"),
                      ("pack_a", "rename_same")):
        res = pt.import_archive(data, root, on_conflict="rename", new_id=bad, now=FIXED_NOW)
        assert not res["ok"] and _codes_include(res, code), (bad, res)
    res = pt.import_archive(data, root, on_conflict="rename", new_id="", now=FIXED_NOW)
    assert not res["ok"] and _codes_include(res, "rename_required")


def test_conflict_overwrite_backs_up(tmp_path: Path) -> None:
    root = _dst(tmp_path)
    _write_pack(root, "pack_a", "旧包", files={"old.json": '{"v":1}'})
    data = _export(tmp_path, "pack_a", "新包")
    res = pt.import_archive(data, root, on_conflict="overwrite", now=FIXED_NOW)
    assert res["ok"] and res["overwritten"] is True and res["backup"]
    assert (root / "pack_a" / "manifest.json").is_file()
    assert not (root / "pack_a" / "old.json").exists(), "覆盖后应是新包内容"
    backup_dir = root / res["backup"]
    assert (backup_dir / "old.json").read_text("utf-8") == '{"v":1}'
    assert "备份" in res["message"]


def test_overwrite_failure_restores_old_pack(tmp_path: Path, monkeypatch) -> None:
    """覆盖过程中搬新包失败 → 旧包自动复原、不留半成品。"""
    root = _dst(tmp_path)
    _write_pack(root, "pack_a", "旧包", files={"old.json": '{"v":1}'})
    data = _export(tmp_path, "pack_a", "新包")
    real_replace = pt.os.replace

    def _boom(src, dst, *a, **k):  # type: ignore[no-untyped-def]
        if pt.TMP_PREFIX in str(src):   # 只让「临时目录 → 目标包」这一步失败
            raise OSError("simulated rename failure")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(pt.os, "replace", _boom)
    res = pt.import_archive(data, root, on_conflict="overwrite", now=FIXED_NOW)
    assert not res["ok"] and _codes_include(res, "write_failed"), res
    monkeypatch.undo()
    # 旧包复原、无临时目录残留
    assert (root / "pack_a" / "old.json").read_text("utf-8") == '{"v":1}'
    assert not list(root.glob(pt.TMP_PREFIX + "*"))


# =====================================================================================
# E. 权限：导出允许 GM；导入必须 owner
# =====================================================================================
def test_gm_cannot_import_but_can_export(tmp_path: Path) -> None:
    root = _dst(tmp_path)
    data = _export(tmp_path, "pack_a")
    before = _tree(root)
    with pytest.raises(api.Forbidden) as ei:
        editor_ops.import_pack(data, root=str(root), role="gm")
    assert ei.value.status_code == 403
    _no_residue(root, before)

    src_root = tmp_path / "src"
    _write_pack(src_root, "gm_pack")
    out = editor_ops.export_pack("gm_pack", root=str(src_root))
    assert out["ok"] and out["data"][:2] == b"PK" and out["filename"]


def test_unknown_role_defaults_readonly(tmp_path: Path) -> None:
    with pytest.raises(api.Forbidden):
        editor_ops.import_pack(b"x", root=str(tmp_path), role="player")


# =====================================================================================
# F. HTTP 端点（导出下载 + 导入上传 + 冲突 + 即时可用）
# =====================================================================================
@pytest.fixture()
def http_env(tmp_path: Path) -> Iterator[Tuple[Any, Path]]:
    _ensure_scripts_on_path()
    from fastapi.testclient import TestClient
    from editor_host import create_app

    content = tmp_path / "content"
    content.mkdir()
    for pid in ("pack_a", "pack_b"):
        _write_pack(content, pid, f"包{pid[-1]}")
    with TestClient(create_app(pack="pack_a", root=str(content), role="owner")) as client:
        yield client, content


def test_http_export_download(http_env: Tuple[Any, Path]) -> None:
    client, content = http_env
    r = client.get("/api/pack/pack_a/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/zip")
    cd = r.headers["content-disposition"]
    assert "attachment" in cd and "pack_a-" in cd and ".ttrpack" in cd
    # 下载内容 = 直接调核心层导出的字节（同一实现）
    direct = pt.export_pack_dir(content / "pack_a", now=FIXED_NOW, ttr_commit_hash="x")
    assert r.content[:2] == b"PK" and _zip_entries(r.content).keys() == \
        _zip_entries(direct["data"]).keys()


def test_http_export_missing_pack_404(http_env: Tuple[Any, Path]) -> None:
    client, _ = http_env
    assert client.get("/api/pack/nope/export").status_code == 404


def test_http_import_success_visible_in_packs(http_env: Tuple[Any, Path]) -> None:
    client, content = http_env
    data = _export(tmp_path_fixture_dir(content), "shared_pack", "分享包")
    r = client.post("/api/pack/import", content=data,
                    headers={"Content-Type": "application/zip"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["pack_id"] == "shared_pack"
    assert body["file_count"] >= 1
    assert (content / "shared_pack" / "manifest.json").is_file()
    ids = [p["id"] for p in client.get("/api/packs").json()["packs"]]
    assert "shared_pack" in ids


def test_http_import_conflict_then_rename(http_env: Tuple[Any, Path]) -> None:
    client, content = http_env
    data = _export(tmp_path_fixture_dir(content), "pack_a", "新版A")
    r = client.post("/api/pack/import", content=data)
    assert r.status_code == 200 and r.json()["ok"] is False
    assert r.json()["conflict"] is True
    r2 = client.post("/api/pack/import?on_conflict=rename&new_id=pack_a_v2", content=data)
    assert r2.status_code == 200 and r2.json()["ok"] is True
    assert (content / "pack_a_v2" / "manifest.json").is_file()


def test_http_import_gm_forbidden(http_env: Tuple[Any, Path]) -> None:
    client, content = http_env
    client.post("/api/session/role", json={"role": "gm"})
    data = _export(tmp_path_fixture_dir(content), "from_gm")
    r = client.post("/api/pack/import", content=data)
    assert r.status_code == 403
    assert not (content / "from_gm").exists()
    # 导出（读操作）在只读身份下仍可用
    assert client.get("/api/pack/pack_a/export").status_code == 200


def test_http_import_rejects_zip_slip(http_env: Tuple[Any, Path]) -> None:
    client, content = http_env
    entries = _zip_entries(_export(tmp_path_fixture_dir(content), "slip_pack"))
    entries["../evil.json"] = b"{}"
    r = client.post("/api/pack/import", content=_repackage(_resign(entries)))
    assert r.status_code == 200
    assert r.json()["ok"] is False and _codes_include(r.json(), "zip_slip")
    assert not (content.parent / "evil.json").exists()
    assert not list(content.glob(pt.TMP_PREFIX + "*"))


def tmp_path_fixture_dir(anchor: Path) -> Path:
    """给 HTTP 测试一个「源包」暂存目录（与内容根同级，避免被当成内容包）。"""
    d = anchor.parent / "_src"
    d.mkdir(parents=True, exist_ok=True)
    return d


# =====================================================================================
# G. 通用性 / 只读护栏
# =====================================================================================
def test_source_has_no_pack_or_module_hardcoding() -> None:
    src = (_REPO / "qbot_rpg" / "content" / "pack_transfer.py").read_text("utf-8")
    for forbidden in ("veinborn", "demo_full", "demo_blank", "zz_probe", "skills", "equipment"):
        assert forbidden not in src, f"pack_transfer.py 不得写死 {forbidden!r}"


def test_real_content_untouched_by_export_import() -> None:
    """真实 `content/` 只读：导出不改源包；把它当导入目标（冲突 / 恶意 zip）也一个字节不动。"""
    def snap() -> Dict[str, str]:
        return {str(p.relative_to(_REAL_CONTENT)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(_REAL_CONTENT.rglob("*")) if p.is_file()}

    before = snap()
    assert "veinborn/manifest.json" in before and len(before) > 20
    data = pt.export_pack_dir(_REAL_CONTENT / "veinborn", now=FIXED_NOW,
                              ttr_commit_hash="x")["data"]
    conflict = pt.import_archive(data, _REAL_CONTENT, now=FIXED_NOW)
    assert not conflict["ok"] and conflict["conflict"] is True
    entries = _zip_entries(data)
    entries["../evil.json"] = b"{}"
    slip = pt.import_archive(_repackage(_resign(entries)), _REAL_CONTENT, now=FIXED_NOW)
    assert not slip["ok"] and _codes_include(slip, "zip_slip")
    assert not list(_REAL_CONTENT.glob(pt.TMP_PREFIX + "*"))
    assert snap() == before, "真实内容包目录不得被改动"
