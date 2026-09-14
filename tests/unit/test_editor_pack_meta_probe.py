"""编辑器重写批D · 新包零改动验证（包内声明展示元数据 → 编辑器/框架零改动显示中文）。

依据：`docs/编辑器重写_数据包展示元数据下放方案.md`
  · §一 判断标准 1：新建一个内容包，在包内声明中文名/说明/分组 → **编辑器与框架均零改动**，
    界面即显示中文；
  · §四 批D：造一个**新包**只在包内声明展示元数据 → 编辑器零改动显示中文；纳入验收脚本；
    未声明中文名的字段走兜底（显示原始键）**不报错**。

本文件**不写死探针包名**：从 `content/` 动态发现「声明了框架从未登记模块」的包
（本批新增的探针包即此类），再断言：
  A. 该包被 `scripts/editor_verify_packs.py` 动态发现且 PASS；
  B. 模块树（含层级）/ 条目字段 label·help·分组显示名 全部与包内声明一致；
  C. 包内未声明的字段 → label 为原始键、说明卡标「未登记」，不抛异常；
  D. 框架源码（`qbot_rpg/`）与验收脚本（`scripts/`）**零耦合**：不含包名/新模块名，
     证明效果完全由包内数据驱动（零改动）。

全程只读真实内容包（不写盘）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

import pytest

from qbot_rpg.content import field_meta_pack as fmp
from qbot_rpg.web import api

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import editor_verify_packs as evp  # noqa: E402  （路径注入后导入，避免 E402）

CONTENT = _REPO / "content"
FRAMEWORK_DIR = _REPO / "qbot_rpg"
SCRIPTS_DIR = _REPO / "scripts"
# 批D 之前的内容包基线（批A 提交）：批D 新增的包 = 当前有、该基线没有。
PRIOR_REF = "995e91b"


# =====================================================================================
# 动态发现（不写死任何包名 / 模块名）
# =====================================================================================
def _pack_dirs() -> set:
    return {d.name for d in CONTENT.iterdir()
            if d.is_dir() and (d / "manifest.json").is_file()}


def _prior_pack_dirs(ref: str = PRIOR_REF):
    """批D 之前基线已有内容包名集合；无 git / 无基线 ref → None。"""
    if not (_REPO / ".git").exists():
        return None
    proc = subprocess.run(["git", "ls-tree", "--name-only", f"{ref}:content"],
                          cwd=str(_REPO), capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    return set(proc.stdout.split())


def _new_pack_ids() -> List[str]:
    """本批新增的内容包 id（当前 content/ 有、前置基线没有）；动态发现，不写死包名。"""
    prior = _prior_pack_dirs()
    if prior is None:
        pytest.skip("无 git 工作树或前置基线 ref，无法动态定位新增包")
    return sorted(_pack_dirs() - prior)


def _new_packs() -> List[Tuple[str, fmp.PackFieldMeta, List[str]]]:
    """(新包名, 声明, 框架未登记模块名) —— 新包必须自带 field_meta.json 声明。"""
    fw = _framework_modules()
    out: List[Tuple[str, fmp.PackFieldMeta, List[str]]] = []
    for pid in _new_pack_ids():
        decl = fmp.load_field_meta(CONTENT / pid)
        assert decl is not None, f"新增包 {pid} 未声明 {fmp.FIELD_META_FILENAME}"
        unknown = sorted(m for m in decl.module_labels if m not in fw)
        out.append((pid, decl, unknown))
    return out


def _framework_modules() -> set:
    return set(api.field_meta_table().modules)


def _flatten(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for n in nodes:
        out.append(n)
        out.extend(_flatten(n.get("children", [])))
    return out


def _first_entry(pid: str, mod: str) -> Dict[str, Any]:
    entries = api.list_entries(pid, mod, root=CONTENT)["entries"]
    assert entries, f"{pid}/{mod} 无条目"
    return api.entry_detail(pid, mod, entries[0]["id"], root=CONTENT)


def _assert_labels(fields: List[Dict[str, Any]], spec: object, where: str) -> None:
    """按包内 `field_labels` 声明递归断言字段 label（嵌套对象走 children）。"""
    by = {str(f["key"]): f for f in fields}
    if not isinstance(spec, Mapping):
        return
    for key, val in spec.items():
        if key in ("_label", "_help"):
            continue
        assert str(key) in by, f"{where}: 包内声明了 {key}，接口未产出该字段"
        node = by[str(key)]
        if isinstance(val, str):
            assert node["label"] == val, f"{where}.{key}: {node['label']!r} != {val!r}"
        elif isinstance(val, Mapping):
            if val.get("_label"):
                assert node["label"] == val["_label"], f"{where}.{key}"
            _assert_labels(node.get("children") or [], val, f"{where}.{key}")


def _assert_help(fields: List[Dict[str, Any]], spec: object, where: str) -> None:
    """按包内 `field_help` 声明递归断言字段 help。"""
    by = {str(f["key"]): f for f in fields}
    if not isinstance(spec, Mapping):
        return
    for key, val in spec.items():
        if key in ("_label", "_help"):
            continue
        if str(key) not in by:
            continue
        node = by[str(key)]
        if isinstance(val, str):
            assert node["help"] == val, f"{where}.{key}: {node['help']!r} != {val!r}"
        elif isinstance(val, Mapping):
            if val.get("_help"):
                assert node["help"] == val["_help"], f"{where}.{key}"
            _assert_help(node.get("children") or [], val, f"{where}.{key}")


# =====================================================================================
# A. 新包存在 + 纳入验收脚本（动态发现）
# =====================================================================================
def test_new_pack_exists_and_is_discovered_by_verify_script() -> None:
    """content/ 下存在「声明框架未登记模块」的新包；验收脚本自动发现且 PASS。"""
    new_packs = _new_packs()
    assert new_packs, "content/ 下应有声明了框架未登记模块的新包（批D 探针包）"
    discovered = set(evp._discover_packs(root=CONTENT))
    for pid, _decl, _unknown in new_packs:
        assert pid in discovered, f"验收脚本未自动发现新包：{pid}"
        report = evp.verify_pack(pid, root=CONTENT)
        assert report.result == "PASS", (pid, report.errors)
        assert report.modules > 0 and report.entries > 0 and report.fields > 0


# =====================================================================================
# B. 模块树（含层级）+ 字段 label / help / 分组显示名 全部按包内声明
# =====================================================================================
def test_new_pack_module_labels_and_hierarchy_from_declaration() -> None:
    """模块显示名 = 包内 `module_labels`；层级 = 包内 `module_tree`（含父 ▸ 子 形态）。"""
    for pid, decl, _unknown in _new_packs():
        mods = api.list_modules(pid, root=CONTENT)
        nodes = {str(n["module"]): n for n in _flatten(mods["modules"])}
        for mod, label in decl.module_labels.items():
            if mod in nodes:
                assert nodes[mod]["label"] == label, f"{pid}.{mod}: {nodes[mod]['label']!r}"
        if decl.module_tree is not None:
            assert mods["flat"] is False, f"{pid} 声明了层级，接口不应平铺"
            for node in decl.module_tree if isinstance(decl.module_tree, list) else []:
                if not isinstance(node, Mapping) or "children" not in node:
                    continue
                parent = str(node.get("module") or "")
                kids = [str(c) if isinstance(c, str) else str(c.get("module"))
                        for c in node["children"] if isinstance(c, (str, Mapping))]
                got = [k["module"] for k in nodes[parent]["children"]]
                for kid in kids:
                    assert kid in got, f"{pid}: {parent} 应含子模块 {kid}，实际 {got}"


def test_new_pack_field_labels_help_and_group_display() -> None:
    """条目字段的中文名/说明/分组显示名全部来自包内 field_meta.json（框架零改动）。"""
    checked = 0
    for pid, decl, _unknown in _new_packs():
        for mod in decl.field_labels:
            detail = _first_entry(pid, mod)
            _assert_labels(detail["fields"], decl.field_labels[mod], f"{pid}/{mod}")
            _assert_help(detail["fields"], decl.field_help.get(mod, {}), f"{pid}/{mod}")
            glabels = decl.group_labels.get(mod, {})
            for g in detail["groups"]:
                if g["name"] in glabels:
                    assert g["label"] == glabels[g["name"]], (
                        f"{pid}/{mod}: 分组 {g['name']} 显示名 {g['label']!r}"
                        f" != 包声明 {glabels[g['name']]!r}")
            checked += 1
    assert checked > 0, "新包没有任何模块声明字段展示元数据"


def test_new_pack_module_unknown_to_framework_shows_chinese() -> None:
    """框架从未登记的模块：仅凭包声明即显示中文模块名 / 字段名 / 说明 / 分组名。"""
    for pid, decl, unknown in _new_packs():
        for mod in unknown:
            tree = api.list_modules(pid, root=CONTENT)["modules"]
            nodes = {str(n["module"]): n for n in _flatten(tree)}
            assert nodes[mod]["label"] == decl.module_labels[mod]
            detail = _first_entry(pid, mod)
            assert detail["module_label"] == decl.module_labels[mod]
            _assert_labels(detail["fields"], decl.field_labels.get(mod, {}), f"{pid}/{mod}")
            _assert_help(detail["fields"], decl.field_help.get(mod, {}), f"{pid}/{mod}")
            for g in detail["groups"]:
                if g["name"] in decl.group_labels.get(mod, {}):
                    assert g["label"] == decl.group_labels[mod][g["name"]]


# =====================================================================================
# C. 包内未声明字段 → 兜底（原始键）不报错
# =====================================================================================
def test_new_pack_undeclared_field_falls_back_to_raw_key_without_error() -> None:
    """数据里有、包内未命名的字段：label 为原始键、说明卡标「未登记」，不抛异常。"""
    found = 0
    for pid, _decl, _unknown in _new_packs():
        for node in _flatten(api.list_modules(pid, root=CONTENT)["modules"]):
            mod = str(node["module"])
            for ent in api.list_entries(pid, mod, root=CONTENT)["entries"]:
                detail = api.entry_detail(pid, mod, ent["id"], root=CONTENT)
                for f in detail["fields"]:
                    if f["help_card"].get("unregistered"):
                        assert f["label"] == f["key"], (
                            f"{pid}/{mod}.{f['key']}: 兜底 label 应为原始键，实际 {f['label']!r}")
                        found += 1
    assert found > 0, "应有「包内未声明 → 原始键兜底」的实例（本批探针包）"


def test_new_pack_registered_type_without_label_uses_raw_key() -> None:
    """框架登记了类型、包内未声明中文名 → label 仍为原始键（框架侧批B 已无文案），不报错。"""
    framework = api.field_meta_table()
    checked = 0
    for pid, decl, _unknown in _new_packs():
        for mod, spec in decl.field_labels.items():
            mmeta = framework.module(mod)
            if mmeta is None:  # 框架未登记模块 → 走「纯展示壳」，不在本用例口径
                continue
            declared = {str(k) for k in spec if str(k) not in ("_label", "_help")}
            detail = _first_entry(pid, mod)
            for f in detail["fields"]:
                fm = mmeta.fields.get(str(f["key"]))
                # 框架登记了类型但**自身也无中文名**（批B 已删展示表；个别内联 label 除外），
                # 且包内未声明 → label 必须回落到原始键。
                if fm is not None and not fm.label and str(f["key"]) not in declared:
                    assert f["label"] == f["key"], (
                        f"{pid}/{mod}.{f['key']}: 包内未声明中文名，label 应为原始键，"
                        f"实际 {f['label']!r}")
                    checked += 1
    assert checked > 0, "应有「框架登记类型、包内未声明中文名」的实例"


# =====================================================================================
# D. 零改动 / 零耦合护栏：框架与验收脚本不含包名或新模块名
# =====================================================================================
def test_framework_and_scripts_have_zero_knowledge_of_new_pack() -> None:
    """`qbot_rpg/` 与 `scripts/` 源码不含新包包名 / 新模块名 → 效果完全由包内数据驱动。"""
    fw_src = "\n".join(p.read_text(encoding="utf-8") for p in FRAMEWORK_DIR.rglob("*.py"))
    sc_src = "\n".join(p.read_text(encoding="utf-8") for p in SCRIPTS_DIR.rglob("*.py"))
    for pid, _decl, unknown in _new_packs():
        for token in [pid, *unknown]:
            assert token not in fw_src, f"框架源码写死了新包信息：{token}"
            assert token not in sc_src, f"脚本写死了新包信息：{token}"
