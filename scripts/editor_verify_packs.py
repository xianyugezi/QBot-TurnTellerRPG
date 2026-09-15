#!/usr/bin/env python3
"""换包零改动验收脚本（编辑器重写批7 · 最高原则「编辑器 = 通用工具」）。

判断标准（docs/编辑器重写_需求与约束.md 第〇节）：
**把当前内容包换成另一个内容包，编辑器是否零改动可用。**

本脚本对内容目录下**动态发现**的每个内容包（不写死任何包名/模块名），只调用编辑器
只读 API 层（`qbot_rpg/web/api.py`）的六个入口——包列表 / 模块树 / 条目列表 / 条目详情 /
条目索引 / 引用候选——并断言：

  ① 不抛异常；
  ② 返回结构完整：modules / entries / fields / groups 计数自洽
     （模块树 count = own + Σ子、条目数三处口径一致、字段数 = Σ分组计数）；
  ③ 字段全部可渲染：每个字段都有 type，widget 落在可渲染集合、control 是已知控件，
     group 归属完整（每个字段都能落进一个声明的分组）；
  ④ 未知 / 缺元数据键走兜底不崩：元数据未登记的字段按实际值推断类型与控件、分组兜底；
     引用候选对未知 target 返回空候选 + known=false，不报错。

再用**临时目录里的合成包**（绝不触碰真实内容包）做反向探针：缺 modules 声明、
声明了模块但文件缺失、条目含未知键/非对象元素、非法 module_tree（幽灵模块/自环/非法节点）
等——全部不得让编辑器崩。

输出逐包报告表（包名 / 模块数 / 条目数 / 字段数 / 警告数 / 结果）；
退出码 0 = 全包 PASS，1 = 存在失败。

用法：
  python scripts/editor_verify_packs.py                    # 扫描 <仓库根>/content
  python scripts/editor_verify_packs.py --content-root DIR
  python scripts/editor_verify_packs.py --quiet            # 只出汇总与被删的成功行
  python scripts/editor_verify_packs.py --json             # 机器可读报告

铁律：**只读**——真实内容包一个字节都不写；合成探针只写 tempfile 临时目录。
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from qbot_rpg.web import api  # noqa: E402  （路径注入后导入，避免 E402）

# 框架能力全集（批13 一号原则：左栏显示集 ⊇ 本集合）。
_FRAMEWORK_CATALOG = frozenset(e.module for e in api.FRAMEWORK_MODULE_CATALOG)

# 可渲染控件形态（api.EDIT_CONTROLS 是「字段类型 → 控件」映射表的唯一产物）。
RENDERABLE_WIDGETS = frozenset({
    "text", "textarea", "number", "bool", "enum", "ref", "list", "obj", "map", "formula",
})
RENDERABLE_CONTROLS = frozenset(api.EDIT_CONTROLS)
# 模块条目形态（list 数组 / map 键值 / object 单对象分段）。
# "scalar" = 模块文件缺失/形态无法归类时的兜底（不崩；编辑器按空列表渲染）。
KNOWN_ENTRY_TYPES = frozenset({"list", "map", "object", "scalar"})
# 列表列描述必须携带的键（列不需要 group —— 分组只属于顶层字段）。
_COLUMN_KEYS = ("key", "label", "type", "widget", "control", "nested")
_FIELD_KEYS = ("key", "label", "type", "widget", "control", "group", "present", "help_card")


# =====================================================================================
# 报告与告警收集
# =====================================================================================
@dataclass
class PackReport:
    """单个内容包的验收结果（逐包报告表的一行）。"""

    pack: str
    name: str = ""
    source: str = "真实"
    modules: int = 0
    entries: int = 0
    fields: int = 0
    errors: List[str] = field(default_factory=list)
    warning_notes: List[str] = field(default_factory=list)

    @property
    def warnings(self) -> int:
        return len(self.warning_notes)

    @property
    def result(self) -> str:
        return "PASS" if not self.errors else "FAIL"


class _Warnings:
    """按 key 去重的告警收集器（同一条元数据缺口在 1000 个条目里只算 1 条）。"""

    def __init__(self) -> None:
        self._seen: Dict[str, str] = {}

    def add(self, key: str, note: str) -> None:
        if key not in self._seen:
            self._seen[key] = note

    @property
    def notes(self) -> List[str]:
        return sorted(self._seen.values())

    def __len__(self) -> int:
        return len(self._seen)


def _need(report: PackReport, obj: object, keys: Sequence[str], where: str) -> bool:
    """断言对象存在且含全部键；缺失即记错（不抛异常，继续扫）。"""
    if not isinstance(obj, Mapping):
        report.errors.append(f"{where}: 期望对象，实际 {type(obj).__name__}")
        return False
    missing = [k for k in keys if k not in obj]
    if missing:
        report.errors.append(f"{where}: 缺少键 {missing}")
        return False
    return True


# =====================================================================================
# 字段 / 列描述校验（递归）
# =====================================================================================
def _check_column(report: PackReport, col: object, where: str,
                  ref_targets: Optional[Set[str]] = None) -> None:
    if not _need(report, col, _COLUMN_KEYS, where):
        return
    assert isinstance(col, Mapping)
    if col["widget"] not in RENDERABLE_WIDGETS:
        report.errors.append(f"{where}/{col['key']}: 不可渲染 widget={col['widget']!r}")
    if col["control"] not in RENDERABLE_CONTROLS:
        report.errors.append(f"{where}/{col['key']}: 未知 control={col['control']!r}")
    if ref_targets is not None and col.get("widget") == "ref" and col.get("ref_target"):
        ref_targets.add(str(col["ref_target"]))
    if not isinstance(col["type"], str) or not col["type"]:
        report.errors.append(f"{where}/{col['key']}: 列 type 缺失")
    if not isinstance(col["nested"], bool):
        report.errors.append(f"{where}/{col['key']}: nested 应为布尔")


def _check_descriptor(report: PackReport, warns: _Warnings, f: object,
                      where: str, in_groups: Optional[Set[str]],
                      ref_targets: Optional[Set[str]] = None, depth: int = 0) -> int:
    """校验一个字段描述；返回该层字段计数（顶层 = 1，用于与 field_count 对齐）。"""
    if not _need(report, f, _FIELD_KEYS, where):
        return 0
    assert isinstance(f, Mapping)
    key = f["key"]
    scope = where.split("/", 1)[0]  # 模块名（告警按「模块+字段」去重，不条目级重复）
    if not isinstance(key, str) or not key:
        # 标量条目（值不是对象）走「单字段兜底」：键为空但仍可渲染——记警告不判失败。
        warns.add(f"empty-key:{scope}", f"{scope}: 存在无键名的兜底字段（值不是对象）")
    widget = f["widget"]
    group = f["group"]
    if not isinstance(f["type"], str) or not f["type"]:
        report.errors.append(f"{where}/{key}: 字段 type 缺失")
    if widget not in RENDERABLE_WIDGETS:
        report.errors.append(f"{where}/{key}: 不可渲染 widget={widget!r}")
    if f["control"] not in RENDERABLE_CONTROLS:
        report.errors.append(f"{where}/{key}: 未知 control={f['control']!r}")
    if not isinstance(group, str) or not group:
        report.errors.append(f"{where}/{key}: 分组缺失（group={group!r}）")
    elif in_groups is not None and group not in in_groups:
        report.errors.append(f"{where}/{key}: 分组「{group}」不在 groups 声明内")
    # 说明卡（悬停/点击看解释）：未登记元数据 = 走兜底，记 1 条警告（不判失败）。
    card = f.get("help_card")
    if isinstance(card, Mapping) and card.get("unregistered"):
        warns.add(f"unregistered:{scope}.{key}",
                  f"{scope} · 字段「{key}」元数据未登记（按实际值推断类型/控件）")
    if widget == "ref":
        if ref_targets is not None and f.get("ref_target"):
            ref_targets.add(str(f["ref_target"]))
        if f.get("ref_valid") is False and f.get("value") not in (None, ""):
            warns.add(f"dangling:{scope}.{key}",
                      f"{scope} · 字段「{key}」存在找不到目标的引用值（编辑器黄提示）")
    if widget == "obj" and depth < 4:
        for child in f.get("children") or []:
            _check_descriptor(report, warns, child, f"{where}.{key}", None, ref_targets, depth + 1)
    if widget == "list":
        cols = f.get("columns")
        if not isinstance(cols, list):
            report.errors.append(f"{where}/{key}: 列表字段 columns 非数组")
        else:
            for col in cols:
                _check_column(report, col, f"{where}/{key}", ref_targets)
        if not isinstance(f.get("block_layout"), bool):
            report.errors.append(f"{where}/{key}: 列表字段缺 block_layout 布尔")
    return 1


def _check_groups(report: PackReport, groups: object, field_count: int,
                  top_groups: Set[str], where: str) -> None:
    if not isinstance(groups, list) or not groups:
        report.errors.append(f"{where}: groups 为空或非数组")
        return
    names: List[str] = []
    total = 0
    for g in groups:
        if not _need(report, g, ("name", "label", "count"), f"{where}.groups[]"):
            continue
        assert isinstance(g, Mapping)
        names.append(str(g["name"]))
        top_groups.add(str(g["name"]))
        if not isinstance(g["count"], int) or g["count"] < 0:
            report.errors.append(f"{where}: 分组「{g['name']}」count 非法：{g['count']!r}")
        else:
            total += g["count"]
    if len(set(names)) != len(names):
        report.errors.append(f"{where}: 分组名重复：{names}")
    if total != field_count:
        report.errors.append(f"{where}: 分组计数合计 {total} != 字段数 {field_count}")


# =====================================================================================
# 单包验收
# =====================================================================================
def verify_pack(pack: str, root: object = None) -> PackReport:
    """对一个内容包跑完六个只读入口并逐项断言（任何异常都记为该包失败，不冒泡）。"""
    report = PackReport(pack=pack)
    warns = _Warnings()
    # —— ① 包必须出现在包列表（且元数据可读） ——
    try:
        packs = api.list_packs(root=root)
        meta = next((p for p in packs["packs"] if p["id"] == pack), None)
        if meta is None:
            report.errors.append("包列表未包含该包（list_packs）")
        else:
            report.name = str(meta.get("name", ""))
    except Exception as exc:  # noqa: BLE001 （验收脚本：任何异常都算该包失败）
        report.errors.append(f"list_packs 异常：{type(exc).__name__}: {exc}")
        report.warning_notes = warns.notes
        return report

    # —— ② 模块树 ——
    tree_modules: Set[str] = set()
    module_own: Dict[str, int] = {}
    try:
        mods = api.list_modules(pack, root=root)
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"list_modules 异常：{type(exc).__name__}: {exc}")
        report.warning_notes = warns.notes
        return report
    if _need(report, mods, ("pack", "pack_name", "modules", "flat", "notes"), "list_modules"):
        for note in mods.get("notes") or []:
            warns.add(f"tree-note:{note}", f"模块层级声明：{note}")

        def walk(nodes: object) -> None:
            for node in nodes if isinstance(nodes, list) else []:
                if not _need(report, node, ("module", "label", "count", "own_count", "children"),
                             "list_modules.modules[]"):
                    continue
                assert isinstance(node, Mapping)
                mid = str(node["module"])
                if mid in tree_modules:
                    report.errors.append(f"模块在树中重复出现：{mid}")
                tree_modules.add(mid)
                kids = node.get("children") or []
                own = node.get("own_count")
                if isinstance(own, int) and own >= 0:
                    module_own[mid] = own
                else:
                    report.errors.append(f"模块 {mid} own_count 非法：{own!r}")
                kid_sum = sum(
                    k.get("count", 0) for k in kids if isinstance(k, Mapping)
                )
                if isinstance(node.get("count"), int) and isinstance(own, int) \
                        and node["count"] != own + kid_sum:
                    report.errors.append(
                        f"模块 {mid} count（{node['count']}）!= own（{own}）+ 子项（{kid_sum}）")
                walk(kids)

        walk(mods["modules"])
        if isinstance(meta, Mapping) and isinstance(meta.get("module_count"), int) \
                and meta["module_count"] != len(tree_modules):
            report.errors.append(
                f"包列表 module_count（{meta['module_count']}）"
                f"!= 模块树模块数（{len(tree_modules)}）")
        # 批13 A（一号原则）：左栏显示集 = 框架能力集 ∪ 包声明——modules ∪ views ∪
        # available 必须覆盖框架目录全集；三组模块键互不重复；未启用候选结构完整。
        views = mods.get("views")
        avail = mods.get("available")
        if not isinstance(views, list) or not isinstance(avail, list):
            report.errors.append("list_modules 缺 views / available（批13 能力可见性）")
        else:
            view_keys = {str(v.get("module")) for v in views if isinstance(v, Mapping)}
            avail_keys = {str(a.get("module")) for a in avail if isinstance(a, Mapping)}
            shown = set(tree_modules) | view_keys | avail_keys
            missing_cat = sorted(_FRAMEWORK_CATALOG - shown)
            if missing_cat:
                report.errors.append(f"左栏未显示框架能力：{missing_cat}")
            if (set(tree_modules) & view_keys) or (set(tree_modules) & avail_keys) \
                    or (view_keys & avail_keys):
                report.errors.append("modules / views / available 三组模块键存在重复")
            for a in avail:
                if not _need(report, a, ("module", "label", "enabled", "in_catalog",
                                          "implemented", "count"), "list_modules.available[]"):
                    continue
                if a.get("enabled") is not False or a.get("in_catalog") is not True:
                    report.errors.append(
                        f"未启用候选 {a.get('module')} 的 enabled/in_catalog 非法")
    report.modules = len(tree_modules)

    # —— ③ 条目索引（全包口径） ——
    idx_total = None
    idx_by_module: Dict[str, int] = {}
    try:
        idx = api.entry_index(pack, root=root)
        if _need(report, idx, ("pack", "modules", "total", "meta_source"), "entry_index"):
            for m in idx.get("modules") or []:
                if not _need(report, m, ("module", "label", "entry_type", "namespace",
                                         "count", "entries"), "entry_index.modules[]"):
                    continue
                assert isinstance(m, Mapping)
                idx_by_module[str(m["module"])] = int(m.get("count") or 0)
                if m.get("entry_type") not in KNOWN_ENTRY_TYPES:
                    report.errors.append(
                        f"entry_index 模块 {m['module']} entry_type 非法：{m['entry_type']!r}")
                if not isinstance(m.get("entries"), list) or len(m["entries"]) != m.get("count"):
                    report.errors.append(
                        f"entry_index 模块 {m['module']} entries 长度 != count")
            idx_total = int(idx.get("total") or 0)
            if idx_total != sum(idx_by_module.values()):
                report.errors.append(
                    f"entry_index total（{idx_total}）"
                    f"!= Σ模块 count（{sum(idx_by_module.values())}）")
            # 批13 A：未启用模块也进检索候选（保留数据可搜到）；不改变 total 口径。
            if not isinstance(idx.get("available"), list):
                report.errors.append("entry_index 缺 available（批13 检索覆盖）")
        if set(idx_by_module) != tree_modules:
            report.errors.append(
                f"entry_index 模块集合与模块树不一致：树多 {tree_modules - set(idx_by_module)}，"
                f"索引多 {set(idx_by_module) - tree_modules}")
    except Exception as exc:  # noqa: BLE001
        report.errors.append(f"entry_index 异常：{type(exc).__name__}: {exc}")

    # —— ④ 逐模块：条目列表 + 逐条目详情 ——
    ref_targets: Set[str] = set()
    tree_order = sorted(tree_modules)
    for mod in tree_order:
        entries: List[Any] = []
        try:
            le = api.list_entries(pack, mod, root=root)
            if _need(report, le, ("pack", "module", "label", "entry_type", "count", "entries"),
                     f"list_entries({mod})"):
                entries = list(le.get("entries") or [])
                if le.get("entry_type") not in KNOWN_ENTRY_TYPES:
                    report.errors.append(
                        f"list_entries({mod}) entry_type 非法：{le.get('entry_type')!r}")
                if le.get("count") != len(entries):
                    report.errors.append(
                        f"list_entries({mod}) count（{le.get('count')}）"
                        f"!= entries 长度（{len(entries)}）")
                own = module_own.get(mod)
                if own is not None and le.get("count") != own:
                    report.errors.append(
                        f"list_entries({mod}) 条数（{le.get('count')}）"
                        f"!= 模块树 own_count（{own}）")
                if idx_by_module and idx_by_module.get(mod) != le.get("count"):
                    report.errors.append(
                        f"list_entries({mod}) 条数（{le.get('count')}）"
                        f"!= entry_index（{idx_by_module.get(mod)}）")
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"list_entries({mod}) 异常：{type(exc).__name__}: {exc}")
            continue

        for ent in entries:
            if not _need(report, ent, ("id", "name"), f"list_entries({mod}).entries[]"):
                continue
            assert isinstance(ent, Mapping)
            eid = ent.get("id")
            if not isinstance(eid, str) or not eid:
                report.errors.append(f"list_entries({mod})：条目 id 非法：{eid!r}")
                continue
            where = f"{mod}/{eid}"
            try:
                det = api.entry_detail(pack, mod, eid, root=root)
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"entry_detail({where}) 异常：{type(exc).__name__}: {exc}")
                continue
            _detail_keys = ("pack", "module", "entry_type", "id", "name", "fields", "groups",
                            "associations", "association_count", "field_count", "group_count",
                            "meta_source")
            if not _need(report, det, _detail_keys, f"entry_detail({where})"):
                continue
            fields = det.get("fields")
            if not isinstance(fields, list):
                report.errors.append(f"entry_detail({where}): fields 非数组")
                continue
            if det.get("field_count") != len(fields):
                report.errors.append(
                    f"entry_detail({where}): field_count（{det.get('field_count')}）"
                    f"!= fields 长度（{len(fields)}）")
            if det.get("group_count") != len(det.get("groups") or []):
                report.errors.append(
                    f"entry_detail({where}): group_count 与 groups 长度不一致")
            if det.get("association_count") != len(det.get("associations") or []):
                report.errors.append(f"entry_detail({where}): association_count 不一致")
            if det.get("entry_type") not in KNOWN_ENTRY_TYPES:
                report.errors.append(
                    f"entry_detail({where}): entry_type 非法：{det.get('entry_type')!r}")
            top_groups: Set[str] = set()
            _check_groups(report, det.get("groups"), len(fields), top_groups,
                          f"entry_detail({where})")
            for f in fields:
                report.fields += _check_descriptor(
                    report, warns, f, where, top_groups, ref_targets)
            # 关联分区：可编辑分区内的字段同样必须可渲染、分组自洽。
            for a in det.get("associations") or []:
                if not isinstance(a, Mapping) or not a.get("editable"):
                    continue
                for ae in a.get("entries") or []:
                    if not isinstance(ae, Mapping):
                        continue
                    afields = ae.get("fields") or []
                    agroups: Set[str] = set()
                    _check_groups(report, ae.get("groups"), len(afields), agroups,
                                  f"assoc({where})")
                    for f in afields:
                        report.fields += _check_descriptor(
                            report, warns, f, f"{where}·关联", agroups, ref_targets)

    report.entries = idx_total if idx_total is not None else 0

    # —— ⑤ 引用候选（对每个出现过的 ref_target 都取一次） ——
    for target in sorted(ref_targets):
        try:
            opts = api.ref_options(pack, target, root=root)
            if _need(report, opts, ("pack", "target", "options", "total", "truncated", "known"),
                     f"ref_options({target})"):
                options = opts.get("options")
                if not isinstance(options, list):
                    report.errors.append(f"ref_options({target}): options 非数组")
                else:
                    for o in options:
                        if not _need(report, o, ("id", "name"), f"ref_options({target}).options[]"):
                            continue
                if not isinstance(opts.get("known"), bool):
                    report.errors.append(f"ref_options({target}): known 应为布尔")
                elif opts["known"] is False:
                    warns.add(f"ref-unknown:{target}",
                              f"引用目标「{target}」在本包内无候选（编辑器显示空候选，不报错）")
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"ref_options({target}) 异常：{type(exc).__name__}: {exc}")

    report.warning_notes = warns.notes
    return report


# =====================================================================================
# 合成兜底探针（只写 tempfile，绝不触碰真实内容包）
# =====================================================================================
def _write_json(path: Path, body: object) -> None:
    path.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")


def verify_synthetic() -> List[PackReport]:
    """临时目录合成包：未知/缺元数据键、缺文件、非法层级声明 → 兜底不崩。"""
    reports: List[PackReport] = []
    with tempfile.TemporaryDirectory(prefix="editor_verify_packs_") as tmp:
        root = Path(tmp)
        # 探针包 A：正常模块 + 未知键 + 非对象元素 + 缺文件 + 非法 module_tree。
        a = root / "zz_probe_fallback"
        a.mkdir()
        _write_json(a / "manifest.json", {
            "name": "兜底探针（合成）",
            "version": "9.9.9",
            "modules": ["zz_probe_things", "zz_probe_map", "zz_probe_missing"],
            "module_tree": [
                {"module": "zz_probe_things",
                 "children": [{"module": "zz_probe_things"}, "zz_probe_ghost", 123]},
            ],
        })
        _write_json(a / "zz_probe_things.json", [
            {"id": "known_id", "name": "有 ID 条目", "mystery": {"deep": [1, 2, 3]}},
            {"name": "无 ID 条目", "typo_key": True},
            3,
        ])
        _write_json(a / "zz_probe_map.json", {
            "map_one": {"name": "映射一", "extra_flag": True},
            "map_two": "纯标量值",
        })
        # zz_probe_missing.json 故意不创建：声明了模块但文件缺失 → 条目数 0，不崩。
        reports.append(verify_pack("zz_probe_fallback", root=root))

        # 探针包 B：manifest 连 modules 都不声明 → 空模块树、条目索引为空，不崩。
        b = root / "zz_probe_nomodules"
        b.mkdir()
        _write_json(b / "manifest.json", {"name": "无模块声明（合成）", "version": "0.0.1"})
        reports.append(verify_pack("zz_probe_nomodules", root=root))

        for r in reports:
            r.source = "合成"
    return reports


# =====================================================================================
# 汇总 / 输出
# =====================================================================================
def _discover_packs(root: object = None) -> List[str]:
    return [str(p["id"]) for p in api.list_packs(root=root)["packs"]]


def run_verification(root: object = None, include_synthetic: bool = True) -> List[PackReport]:
    """扫描全部真实内容包（+ 合成探针），返回逐包报告。"""
    reports = [verify_pack(pid, root=root) for pid in _discover_packs(root)]
    if include_synthetic:
        reports.extend(verify_synthetic())
    return reports


def _print_table(reports: Sequence[PackReport], quiet: bool) -> None:
    header = ("包名", "来源", "模块数", "条目数", "字段数", "警告数", "结果")
    rows = [
        (r.pack, r.source, str(r.modules), str(r.entries), str(r.fields),
         str(r.warnings), r.result)
        for r in reports
    ]
    if quiet:
        rows = [r for r in rows if r[6] != "PASS"]
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) if rows else len(header[i])
              for i in range(len(header))]
    line = "  ".join(h.center(widths[i]) for i, h in enumerate(header))
    print(line)
    print("-" * len(line))
    for r in rows:
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="编辑器换包零改动验收（只读全包扫描）")
    parser.add_argument("--content-root", default=None,
                        help="内容包根目录（缺省 <仓库根>/content）")
    parser.add_argument("--quiet", action="store_true", help="只打印失败行与失败明细")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = parser.parse_args(argv)

    root = Path(args.content_root) if args.content_root else None
    reports = run_verification(root=root)

    if args.json:
        # 机器可读：stdout 只出 JSON（不掺人类摘要），退出码仍反映失败。
        print(json.dumps([
            {"pack": r.pack, "name": r.name, "source": r.source, "modules": r.modules,
             "entries": r.entries, "fields": r.fields, "warnings": r.warnings,
             "result": r.result, "errors": r.errors,
             "warning_notes": r.warning_notes}
            for r in reports
        ], ensure_ascii=False, indent=2))
        return 0 if not any(r.result != "PASS" for r in reports) else 1

    print("换包零改动验收 · 逐包报告")
    _print_table(reports, quiet=args.quiet)
    failed = [r for r in reports if r.result != "PASS"]
    total_warn = sum(r.warnings for r in reports)
    print()
    print(f"汇总：{len(reports)} 个包（真实 {sum(1 for r in reports if r.source == '真实')}"
          f" + 合成 {sum(1 for r in reports if r.source == '合成')}）"
          f" · PASS {len(reports) - len(failed)} · FAIL {len(failed)} · 警告 {total_warn} 条")
    for r in failed:
        print(f"\n[{r.result}] {r.pack}（{r.name or r.pack}）：")
        for e in r.errors[:40]:
            print(f"  - {e}")
        if len(r.errors) > 40:
            print(f"  … 其余 {len(r.errors) - 40} 条省略")
    print()
    print("换包零改动验收：" + ("全包 PASS" if not failed else f"{len(failed)} 个包 FAIL"))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
