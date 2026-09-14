"""编辑器重写批11 · 内容包导出/导入 CLI（scripts/pack_transfer.py）。

覆盖：export / import 两个子命令（`--pack` / `--file` / `--content-root`）、
逐字节往返、同名冲突（默认拒绝 / --rename / --overwrite 先备份）、恶意 zip 拒绝、
默认文件名、--json 输出、--rename 与 --overwrite 互斥、失败不留残留。

纪律：全部写入 tmp_path；不碰真实内容包。
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.content import pack_transfer as pt
from qbot_rpg.web import api

_REPO = Path(api.repo_root())
_REAL_CONTENT = _REPO / "content"
_SPEC = importlib.util.spec_from_file_location(
    "pack_transfer_cli", _REPO / "scripts" / "pack_transfer.py")
cli = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(cli)


def _copy_pack(tmp_path: Path, real_pack: str = "demo_lv15") -> Path:
    root = tmp_path / "src_content"
    shutil.copytree(_REAL_CONTENT / real_pack, root / real_pack)
    return root


def _zip_entries(data: bytes) -> Dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {zi.filename: zf.read(zi) for zi in zf.infolist() if not zi.is_dir()}


def _repackage(entries: Dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, raw in entries.items():
            zf.writestr(name, raw)
    return buf.getvalue()


def _resign(entries: Dict[str, bytes]) -> Dict[str, bytes]:
    out = dict(entries)
    meta = json.loads(out[pt.EXPORT_META_NAME])
    rows = []
    for name in sorted(out):
        if name == pt.EXPORT_META_NAME:
            continue
        raw = out[name]
        rows.append({"path": name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    meta["files"] = rows
    meta["file_count"] = len(rows)
    meta["total_bytes"] = sum(r["size"] for r in rows)
    out[pt.EXPORT_META_NAME] = json.dumps(meta, ensure_ascii=False, indent=2).encode()
    return out


def _tree(root: Path) -> Any:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def test_cli_export_then_import_round_trip(tmp_path: Path, capsys: Any) -> None:
    src = _copy_pack(tmp_path, "demo_lv15")
    out = tmp_path / "share.ttrpack"
    assert cli.main(["export", "--pack", "demo_lv15",
                     "--content-root", str(src), "--file", str(out)]) == 0
    assert out.is_file() and out.read_bytes()[:2] == b"PK"
    printed = capsys.readouterr().out
    assert "已导出" in printed and "TTR 版本" in printed

    dst = tmp_path / "dst_content"
    dst.mkdir()
    assert cli.main(["import", "--file", str(out), "--content-root", str(dst)]) == 0
    assert "已导入" in capsys.readouterr().out
    src_files = sorted(p.relative_to(src / "demo_lv15")
                       for p in (src / "demo_lv15").iterdir() if p.is_file())
    for rel in src_files:
        assert (dst / "demo_lv15" / rel).read_bytes() == \
            (src / "demo_lv15" / rel).read_bytes(), f"字节不等价：{rel}"


def test_cli_export_default_filename(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    src = _copy_pack(tmp_path, "demo_lv15")
    monkeypatch.chdir(tmp_path)
    assert cli.main(["export", "--pack", "demo_lv15", "--content-root", str(src)]) == 0
    made = list(tmp_path.glob("*.ttrpack"))
    assert len(made) == 1
    assert made[0].name.startswith("demo_lv15-") and made[0].name.endswith(pt.TTRPACK_EXT)
    assert "已导出" in capsys.readouterr().out


def test_cli_export_missing_pack(tmp_path: Path, capsys: Any) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    assert cli.main(["export", "--pack", "nope", "--content-root", str(root)]) == 1
    err = capsys.readouterr().err
    assert "找不到内容包" in err and "怎么处理" in err


def test_cli_import_conflict_rename_overwrite(tmp_path: Path, capsys: Any) -> None:
    src = _copy_pack(tmp_path, "demo_lv15")
    out = tmp_path / "share.ttrpack"
    cli.main(["export", "--pack", "demo_lv15", "--content-root", str(src), "--file", str(out)])
    dst = tmp_path / "dst_content"
    dst.mkdir()
    assert cli.main(["import", "--file", str(out), "--content-root", str(dst)]) == 0
    capsys.readouterr()
    # 再来一次：默认拒绝，并提示 --rename / --overwrite
    assert cli.main(["import", "--file", str(out), "--content-root", str(dst)]) == 1
    err = capsys.readouterr().err
    assert "--rename" in err and "--overwrite" in err
    # 换个名字
    assert cli.main(["import", "--file", str(out), "--content-root", str(dst),
                     "--rename", "demo_copy"]) == 0
    assert (dst / "demo_copy" / "manifest.json").is_file()
    assert (dst / "demo_lv15" / "manifest.json").is_file()
    capsys.readouterr()
    # 覆盖：原包进备份目录
    assert cli.main(["import", "--file", str(out), "--content-root", str(dst),
                     "--overwrite"]) == 0
    out_text = capsys.readouterr().out
    assert "备份" in out_text
    backups = list((dst / pt.BACKUP_DIRNAME / "demo_lv15").glob("*/manifest.json"))
    assert backups, "覆盖前必须自动备份原包"


def test_cli_rename_overwrite_mutually_exclusive(tmp_path: Path, capsys: Any) -> None:
    assert cli.main(["import", "--file", str(tmp_path / "x.ttrpack"),
                     "--rename", "a", "--overwrite"]) == 1
    assert "只能选一个" in capsys.readouterr().err


def test_cli_import_rejects_zip_slip(tmp_path: Path, capsys: Any) -> None:
    src = _copy_pack(tmp_path, "demo_lv15")
    data = pt.export_pack_dir(src / "demo_lv15", now=None, ttr_commit_hash="x")["data"]
    entries = _zip_entries(data)
    entries["../evil.json"] = b"{}"
    bad = tmp_path / "bad.ttrpack"
    bad.write_bytes(_repackage(_resign(entries)))
    dst = tmp_path / "dst_content"
    dst.mkdir()
    before = _tree(dst)
    assert cli.main(["import", "--file", str(bad), "--content-root", str(dst)]) == 1
    err = capsys.readouterr().err
    assert "越出目标目录" in err or "危险" in err
    assert _tree(dst) == before and not list(dst.glob(pt.TMP_PREFIX + "*"))
    assert not (tmp_path / "evil.json").exists()


def test_cli_import_missing_file(tmp_path: Path, capsys: Any) -> None:
    assert cli.main(["import", "--file", str(tmp_path / "nope.ttrpack"),
                     "--content-root", str(tmp_path)]) == 1
    assert "找不到导入文件" in capsys.readouterr().err


def test_cli_json_output(tmp_path: Path, capsys: Any) -> None:
    src = _copy_pack(tmp_path, "demo_lv15")
    out = tmp_path / "share.ttrpack"
    assert cli.main(["export", "--pack", "demo_lv15", "--content-root", str(src),
                     "--file", str(out), "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["ok"] is True and body["pack_id"] == "demo_lv15"
    assert "data" not in body and body["files"]
    dst = tmp_path / "dst_content"
    dst.mkdir()
    assert cli.main(["import", "--file", str(out), "--content-root", str(dst),
                     "--json"]) == 0
    body2 = json.loads(capsys.readouterr().out)
    assert body2["ok"] is True and body2["pack_id"] == "demo_lv15"


def test_cli_requires_subcommand() -> None:
    with pytest.raises(SystemExit) as ei:
        cli.main([])
    assert ei.value.code != 0
