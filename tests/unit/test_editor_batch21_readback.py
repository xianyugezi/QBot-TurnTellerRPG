"""编辑器批21 · F 段：**写入后回读校验**（写盘 → 重新加载 → 比对）。

依据：CakeGame 实测教训「落库必须 decode 回读校验」（曾出现「史莱姆行缺 1 字节」）。
批21 在既有「校验 → 备份 → 原子写 → 复核」链路上补**逐模块内容比对**：

  · `atomic_store.read_back_modules`：只读**被写模块**文件 → 解析 → 与「应写内容」比对；
    三态失败 = 文件缺失 / 解析失败（半写、截断）/ 内容不一致（篡改），绝不静默成功；
  · `editor_ops._verify_after_write(expected=...)`：回读失败 → 明确报错 + 自动回退备份；
  · 覆盖：`save_entry` / `create_entry` / 模块启停骨架 / `.ttrpack` 导入（前两处 + 后两处）；
  · 负向自证：人为制造「写后文件被篡改 / 半写」→ 回读必须检出；
  · 性能：回读只针对被写模块（不整包重载），实测耗时对比见 `test_readback_timing`。

全部写盘只在 tmp_path（自建通用包），绝不触碰仓库 content/（批19.1 防污染门禁）。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.content import atomic_store
from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
from qbot_rpg.web import api, editor_ops

META = FieldMetaTable(modules={
    "widgets": ModuleMeta(entry_type="list", fields={
        "id": FieldMeta(type="str", required=True, label="标识"),
        "name": FieldMeta(type="str", label="名称"),
        "count": FieldMeta(type="int", range_min=0, range_max=100, label="数量"),
    }),
    "settings": ModuleMeta(entry_type="object", fields={
        "enabled": FieldMeta(type="bool", label="启用"),
    }),
})


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture()
def pack_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    pkg = tmp_path / "pack_u"
    pkg.mkdir()
    _write(pkg / "manifest.json", {
        "name": "U", "version": "1", "schema_version": 1,
        "modules": ["widgets", "settings"],
    })
    _write(pkg / "widgets.json", [{"id": "w1", "name": "甲", "count": 1}])
    _write(pkg / "settings.json", {"enabled": True})
    monkeypatch.setattr(api, "_META_TABLE", META)
    return tmp_path


# =====================================================================================
# 1. read_back_modules：通过 / 解析失败 / 内容不一致 / 文件缺失
# =====================================================================================
def test_read_back_modules_passes_on_exact_content(tmp_path: Path) -> None:
    atomic_store.write_modules(tmp_path, {"widgets": [{"id": "a"}]})
    res = atomic_store.read_back_modules(tmp_path, {"widgets": [{"id": "a"}]})
    assert res["ok"] is True and res["verified"] == ["widgets"] and res["errors"] == []


def test_read_back_modules_detects_broken_json(tmp_path: Path) -> None:
    """半写 / 截断：写盘后文件不是合法 JSON → 必须检出。"""
    (tmp_path / "widgets.json").write_text('{"id": "a"', encoding="utf-8")
    res = atomic_store.read_back_modules(tmp_path, {"widgets": [{"id": "a"}]})
    assert res["ok"] is False
    assert res["errors"][0]["code"] == "read_back_parse_failed"


def test_read_back_modules_detects_content_mismatch(tmp_path: Path) -> None:
    """篡改：文件仍是合法 JSON，但内容与应写内容不一致 → 必须检出。"""
    (tmp_path / "widgets.json").write_text(json.dumps([{"id": "a", "count": 999}]),
                                           encoding="utf-8")
    res = atomic_store.read_back_modules(tmp_path, {"widgets": [{"id": "a", "count": 1}]})
    assert res["ok"] is False
    assert res["errors"][0]["code"] == "read_back_mismatch"


def test_read_back_modules_detects_missing_file(tmp_path: Path) -> None:
    res = atomic_store.read_back_modules(tmp_path, {"widgets": [{"id": "a"}]})
    assert res["ok"] is False
    assert res["errors"][0]["code"] == "read_back_read_failed"


# =====================================================================================
# 2. 接线：save_entry / create_entry 回读失败 → 明确报错 + 回退备份
# =====================================================================================
def _tampering_write(orig: Any) -> Any:
    """把「写盘」换成「写盘后偷偷改一个字节/一个值」——模拟写后文件被篡改。"""
    def _inner(content_dir: Path, files: Dict[str, Any]) -> Dict[str, Any]:
        res = orig(content_dir, files)
        if res.get("ok"):
            for module in files:
                path = content_dir / f"{module}.json"
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list) and data:
                    data[0]["count"] = 424242
                elif isinstance(data, dict):
                    data["_tampered"] = True
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        return res
    return _inner


def test_save_entry_tamper_is_detected_and_rolled_back(pack_root: Path,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    import qbot_rpg.web.editor_ops as ops
    pkg = pack_root / "pack_u"
    before = (pkg / "widgets.json").read_bytes()
    monkeypatch.setattr(atomic_store, "write_modules",
                        _tampering_write(atomic_store.write_modules))
    monkeypatch.setattr(ops.atomic_store, "write_modules",
                        _tampering_write(ops.atomic_store.write_modules))
    res = editor_ops.save_entry("pack_u", "widgets", "w1", {"count": 2},
                                root=pack_root, meta=META)
    assert res["ok"] is False
    assert res["rolled_back"] is True
    codes = [e["code"] for e in res["errors"]]
    assert "read_back_mismatch" in codes, res["errors"]
    assert "复核未通过" in res["message"]
    # 回退到备份 → 文件逐字节复原（篡改不生效、不静默成功）
    assert (pkg / "widgets.json").read_bytes() == before


def test_create_entry_tamper_is_detected_and_rolled_back(pack_root: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    import qbot_rpg.web.editor_ops as ops
    pkg = pack_root / "pack_u"
    before = (pkg / "widgets.json").read_bytes()
    monkeypatch.setattr(ops.atomic_store, "write_modules",
                        _tampering_write(ops.atomic_store.write_modules))
    res = editor_ops.create_entry("pack_u", "widgets", "w9", {"name": "新"},
                                  root=pack_root, meta=META)
    assert res["ok"] is False and res["rolled_back"] is True
    assert any(e["code"] == "read_back_mismatch" for e in res["errors"])
    assert (pkg / "widgets.json").read_bytes() == before


def test_module_toggle_skeleton_read_back(pack_root: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """模块启停带来的骨架写入同样回读（expected = 实际写入文件）。"""
    import qbot_rpg.web.editor_ops as ops
    calls: Dict[str, Any] = {}
    orig = atomic_store.read_back_modules

    def _spy(content_dir: Path, expected: Dict[str, Any]) -> Dict[str, Any]:
        calls["expected"] = dict(expected)
        return orig(content_dir, expected)

    # 启用一个「框架可启用、包未声明」的模块 → 走骨架写入路径，expected = manifest + 骨架。
    monkeypatch.setattr(ops.atomic_store, "read_back_modules", _spy)
    res = editor_ops.set_module_enabled("pack_u", "achievements", True,
                                        root=pack_root, meta=META)
    assert res["ok"] is True, res.get("errors")
    assert "achievements" in calls.get("expected", {}), calls
    assert "manifest" in calls["expected"]


def test_module_toggle_read_back_failure_rolls_back(pack_root: Path,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """骨架写入被篡改 → 回读失败 → 复原 manifest（不静默成功）。"""
    import qbot_rpg.web.editor_ops as ops
    pkg = pack_root / "pack_u"
    before_manifest = (pkg / "manifest.json").read_bytes()
    monkeypatch.setattr(ops.atomic_store, "read_back_modules", lambda cd, exp: {
        "ok": False, "verified": [], "errors": [{
            "level": "red", "code": "read_back_mismatch", "module": "achievements",
            "message": "回读失败：内容不一致（模拟）。", "how_to_fix": "重试。"}]})
    res = editor_ops.set_module_enabled("pack_u", "achievements", True,
                                        root=pack_root, meta=META)
    assert res["ok"] is False and res["rolled_back"] is True
    assert any(e["code"] == "read_back_mismatch" for e in res["errors"])
    assert (pkg / "manifest.json").read_bytes() == before_manifest


# =====================================================================================
# 3. .ttrpack 导入回读：字节比对
# =====================================================================================
def test_import_read_back_mismatch_helper(tmp_path: Path) -> None:
    from qbot_rpg.content import pack_transfer
    target = tmp_path / "pack"
    target.mkdir()
    (target / "widgets.json").write_bytes(b'[{"id": "a"}]')
    (target / "settings.json").write_bytes(b'{"enabled": true}')
    payload = {"widgets.json": b'[{"id": "a"}]', "settings.json": b'{"enabled": false}'}
    bad = pack_transfer._read_back_mismatches(
        target, payload, ["widgets.json", "settings.json"])
    assert bad == ["settings.json"]


def test_import_read_back_missing_file_helper(tmp_path: Path) -> None:
    from qbot_rpg.content import pack_transfer
    target = tmp_path / "pack"
    target.mkdir()
    assert pack_transfer._read_back_mismatches(target, {"a.json": b"x"}, ["a.json"]) == [
        "a.json"]


# =====================================================================================
# 4. 性能：回读只针对被写模块（不整包重载），耗时对比（实测数字打印）
# =====================================================================================
def test_readback_timing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    big = [{"id": f"w{i:04d}", "name": f"条目{i}", "count": i % 100} for i in range(800)]
    small = [{"id": f"w{i:04d}", "name": f"条目{i}", "count": i % 100} for i in range(50)]
    # 原语计时落点（tmp_path 根）
    _write(tmp_path / "widgets.json", [{"id": "old"}])
    # 端到端计时用的自建包
    pkg = tmp_path / "pack_u"
    pkg.mkdir()
    _write(pkg / "manifest.json", {
        "name": "U", "version": "1", "schema_version": 1,
        "modules": ["widgets", "settings"],
    })
    _write(pkg / "widgets.json", big)
    _write(pkg / "settings.json", {"enabled": True})
    monkeypatch.setattr(api, "_META_TABLE", META)

    def _best(fn: Any, rounds: int = 15) -> float:
        best = float("inf")
        for _ in range(rounds):
            t0 = time.perf_counter()
            fn()
            best = min(best, time.perf_counter() - t0)
        return best

    # ① 回读原语：写盘 vs 写盘 + 逐模块回读（800 条 = 模拟本仓最大模块量级）
    write_only = _best(lambda: atomic_store.write_modules(tmp_path, {"widgets": big}))
    write_plus_read = _best(lambda: (
        atomic_store.write_modules(tmp_path, {"widgets": big}),
        atomic_store.read_back_modules(tmp_path, {"widgets": big}),
    ))
    overhead = write_plus_read - write_only
    small_read = _best(lambda: atomic_store.read_back_modules(tmp_path, {"widgets": small}))
    small_write = _best(lambda: atomic_store.write_modules(tmp_path, {"widgets": small}))
    print(f"\n[F 耗时·原语] 800 条：写盘={write_only*1000:.3f}ms "
          f"写盘+回读={write_plus_read*1000:.3f}ms "
          f"回读净增={overhead*1000:.3f}ms；50 条：写盘={small_write*1000:.3f}ms "
          f"回读={small_read*1000:.3f}ms")

    # ② 端到端 save_entry：有回读 vs 关掉回读（证明整链路的净增很小）
    e2e_with = _best(lambda: editor_ops.save_entry(
        "pack_u", "widgets", "w0001", {"count": 7}, root=tmp_path, meta=META), rounds=8)
    orig_rb = atomic_store.read_back_modules
    atomic_store.read_back_modules = lambda cd, exp: {
        "ok": True, "verified": list(exp), "errors": []}
    try:
        e2e_without = _best(lambda: editor_ops.save_entry(
            "pack_u", "widgets", "w0001", {"count": 7}, root=tmp_path, meta=META), rounds=8)
    finally:
        atomic_store.read_back_modules = orig_rb
    print(f"[F 耗时·端到端 save_entry] 无回读={e2e_without*1000:.2f}ms "
          f"有回读={e2e_with*1000:.2f}ms 净增={(e2e_with-e2e_without)*1000:.2f}ms")

    assert small_read < small_write + 0.02, (small_write, small_read)
    # 回读只读 1 个模块（800 条），净增远小于既有整包校验；给宽松上界防环境抖动
    assert overhead < 0.2, overhead
    assert e2e_with < e2e_without * 3 + 0.1, (e2e_without, e2e_with)
