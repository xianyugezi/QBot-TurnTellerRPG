"""包展示元数据读取层（`content/<包>/field_meta.json` → 与框架表合并的通用入口）。

依据：`docs/编辑器重写_数据包展示元数据下放方案.md`
  · §三 目标结构：包内 `field_meta.json`（纯 JSON）承载**包专属展示元数据**；
  · §四 批 A：本文件是「读包声明 → 与框架 `field_meta.py` 表合并」的通用入口，
    框架侧现有声明**不动**，未声明该文件的包行为零变化；
  · §二 优先级：**包声明 > 框架兜底**——`field_labels` / `field_help` / `group_labels`
    覆盖框架同键值，未声明键保持框架现状。

`field_meta.json` 形态（schema_version = 1，纯 JSON，未知顶层键/形态非法 → 明确报错）：

    {
      "schema_version": 1,
      "module_labels": {"skills": "技能"},
      "module_tree":   [{"module": "items", "children": ["equipment"]}],
      "field_labels":  {"skills": {"power": "威力"}},
      "field_help":    {"skills": {"power": "技能倍率，按百分比算。"}},
      "group_labels":  {"enemies": {"base": "基本"}}
    }

优先级细则（与文档同步）：
  · `module_labels` / `module_tree` 属**包级**声明：manifest 里已有同名字段（现状由包声明），
    本文件若也声明则以 **field_meta.json 为准**（`module_labels` 逐键覆盖 manifest，
    `module_tree` 整体替换 manifest 的 `module_tree`/`module_groups`）；
  · `field_labels` / `field_help` / `group_labels` 属**模块级**声明：覆盖框架表同模块同键值，
    未声明键保持框架现状；包为框架未登记的字段声明标签/说明时，补一个 `soft_label`
    纯展示字段（泛型校验短路，零行为变化），声明未覆盖到的字段仍走原兜底。

本模块只依赖 `qbot_rpg.content.models`（零 web 依赖，框架可独立使用）；解析严格、
合并纯函数（不改动传入的框架表），读取按文件 mtime/size/inode 缓存。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta

# 包内声明的文件名（固定；包不放该文件 = 完全按现状走）。
FIELD_META_FILENAME = "field_meta.json"
# 当前支持的声明版本（写进《编辑器重写_需求与约束》做契约）。
SCHEMA_VERSION = 1
# 允许的顶层键（未知键一律报错，不静默吞掉——防各家包写法漂移）。
TOP_LEVEL_KEYS: Tuple[str, ...] = (
    "schema_version",
    "module_labels",
    "module_tree",
    "field_labels",
    "field_help",
    "group_labels",
)


class PackFieldMetaError(ValueError):
    """包声明 `field_meta.json` 形态非法（人话：指出包名与哪个键错）。"""


@dataclass(frozen=True)
class PackFieldMeta:
    """一份通过严格校验的包展示元数据声明（原始值，不含合并结果）。"""

    pack: str
    module_labels: Mapping[str, str]
    module_tree: Any  # None（未声明）| list | Mapping（与 manifest module_tree 同形态）
    field_labels: Mapping[str, Mapping[str, str]]
    field_help: Mapping[str, Mapping[str, str]]
    group_labels: Mapping[str, Mapping[str, str]]


# -------------------------------------------------------------------------------------
# 严格解析
# -------------------------------------------------------------------------------------
def _type_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "布尔"
    if isinstance(value, (int, float)):
        return "数字"
    if isinstance(value, str):
        return "字符串"
    if isinstance(value, list):
        return "数组"
    if isinstance(value, Mapping):
        return "对象"
    return type(value).__name__


def _fail(pack: str, key: str, msg: str) -> "PackFieldMetaError":
    return PackFieldMetaError(f"内容包 {pack} 的 {FIELD_META_FILENAME} 键 {key} {msg}")


def _require_map(value: object, pack: str, key: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail(pack, key, f"形态非法：应为对象，实际是{_type_name(value)}")
    return value


def _str_map(value: object, pack: str, key: str) -> Dict[str, str]:
    """校验「对象<字符串, 非空字符串>」形态（module_labels / 模块内 labels·help）。"""
    raw = _require_map(value, pack, key)
    out: Dict[str, str] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not k:
            raise _fail(pack, key, f"含非法键（键应为非空字符串）：{k!r}")
        if not isinstance(v, str) or not v:
            raise _fail(pack, key, f"键 {k} 的值应为非空字符串，实际是{_type_name(v)}")
        out[k] = v
    return out


def _nested_str_map(value: object, pack: str, key: str) -> Dict[str, Dict[str, str]]:
    """校验「对象<模块名, 对象<字段键, 非空字符串>>」形态。"""
    raw = _require_map(value, pack, key)
    out: Dict[str, Dict[str, str]] = {}
    for mod, body in raw.items():
        if not isinstance(mod, str) or not mod:
            raise _fail(pack, key, f"含非法模块名（应为非空字符串）：{mod!r}")
        out[mod] = _str_map(body, pack, f"{key}.{mod}")
    return out


def _validate_tree_node(node: object, pack: str, key: str, where: str) -> None:
    if isinstance(node, str):
        if not node:
            raise _fail(pack, key, f"{where}含空模块名字符串")
        return
    if not isinstance(node, Mapping):
        raise _fail(pack, key, f"{where}节点形态非法：应为字符串或对象，实际是{_type_name(node)}")
    mod = node.get("module", node.get("id", node.get("name")))
    if not isinstance(mod, str) or not mod:
        raise _fail(pack, key, f"{where}节点缺少合法的 module 键：{dict(node)!r}")
    label = node.get("label")
    if label is not None and not isinstance(label, str):
        raise _fail(pack, key, f"{where}节点 {mod} 的 label 应为字符串，实际是{_type_name(label)}")
    kids = node.get("children", node.get("modules"))
    if kids is None:
        return
    if not isinstance(kids, list):
        raise _fail(pack, key, f"{where}节点 {mod} 的 children 应为数组，实际是{_type_name(kids)}")
    for child in kids:
        _validate_tree_node(child, pack, key, f"{where}{mod} ▸ ")


def _validate_module_tree(value: object, pack: str, key: str) -> Any:
    """module_tree 形态：数组（节点字符串/对象）或对象（父: 子列表/对象）。"""
    if isinstance(value, list):
        for node in value:
            _validate_tree_node(node, pack, key, "")
        return value
    if isinstance(value, Mapping):
        for parent, kid_spec in value.items():
            if not isinstance(parent, str) or not parent:
                raise _fail(pack, key, f"含非法父模块名（应为非空字符串）：{parent!r}")
            if not isinstance(kid_spec, (list, Mapping)):
                raise _fail(pack, key,
                            f"父模块 {parent} 的子项应为数组或对象，实际是{_type_name(kid_spec)}")
        return value
    raise _fail(pack, key,
                f"形态非法：应为数组或对象（父: 子项），实际是{_type_name(value)}")


def _validate_schema_version(value: object, pack: str, key: str) -> int:
    if value is None:
        raise _fail(pack, key, f"缺失：应为整数 {SCHEMA_VERSION}")
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(pack, key, f"类型非法：应为整数，实际是{_type_name(value)}")
    if value != SCHEMA_VERSION:
        raise _fail(pack, key,
                    f"版本不受支持：{value}（本框架支持 {SCHEMA_VERSION}）")
    return value


def parse_field_meta(raw: object, pack: str) -> PackFieldMeta:
    """严格解析一份包声明（未知顶层键 / 形态非法 → PackFieldMetaError）。"""
    if not isinstance(raw, Mapping):
        raise PackFieldMetaError(
            f"内容包 {pack} 的 {FIELD_META_FILENAME} 形态非法：顶层应为对象，"
            f"实际是{_type_name(raw)}")
    unknown = [str(k) for k in raw if k not in TOP_LEVEL_KEYS]
    if unknown:
        allowed = " / ".join(TOP_LEVEL_KEYS)
        raise PackFieldMetaError(
            f"内容包 {pack} 的 {FIELD_META_FILENAME} 含未知顶层键：{'、'.join(unknown)}；"
            f"允许的键：{allowed}")
    _validate_schema_version(raw.get("schema_version"), pack, "schema_version")
    module_labels = (_str_map(raw["module_labels"], pack, "module_labels")
                     if "module_labels" in raw else {})
    module_tree = (_validate_module_tree(raw["module_tree"], pack, "module_tree")
                   if "module_tree" in raw else None)
    field_labels = (_nested_str_map(raw["field_labels"], pack, "field_labels")
                    if "field_labels" in raw else {})
    field_help = (_nested_str_map(raw["field_help"], pack, "field_help")
                  if "field_help" in raw else {})
    group_labels = (_nested_str_map(raw["group_labels"], pack, "group_labels")
                    if "group_labels" in raw else {})
    return PackFieldMeta(
        pack=pack,
        module_labels=module_labels,
        module_tree=module_tree,
        field_labels=field_labels,
        field_help=field_help,
        group_labels=group_labels,
    )


@lru_cache(maxsize=1024)
def _load_cached(path_str: str, mtime_ns: int, size: int, ino: int) -> PackFieldMeta:
    path = Path(path_str)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PackFieldMetaError(
            f"读取包声明失败：{path_str}（{exc}）") from exc
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise PackFieldMetaError(
            f"内容包 {path.parent.name} 的 {FIELD_META_FILENAME} 不是合法 JSON：{exc}") from exc
    return parse_field_meta(raw, path.parent.name)


def load_field_meta(pack_dir: object) -> Optional[PackFieldMeta]:
    """读一个内容包的 `field_meta.json`（不存在 → None；非法 → PackFieldMetaError）。

    按 mtime/size/inode 缓存：包文件被改写（含原子写新 inode）后自动失效重读。
    """
    path = Path(str(pack_dir)) / FIELD_META_FILENAME
    try:
        st = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    return _load_cached(str(path), st.st_mtime_ns, st.st_size, st.st_ino)


# -------------------------------------------------------------------------------------
# 合并（包声明 > 框架兜底；纯函数，不改动传入的 base 表）
# -------------------------------------------------------------------------------------
def _display_field(label: str, help_text: str) -> FieldMeta:
    """纯展示字段（soft_label=True → 泛型校验短路；type 留空 = 类型未登记，按实际值推断）。"""
    return FieldMeta(type="", soft_label=True, label=label, help=help_text)


def _apply_display(fields: Mapping[str, FieldMeta],
                   labels: Mapping[str, str], helps: Mapping[str, str],
                   add_unknown: bool) -> Dict[str, FieldMeta]:
    """把 labels/helps 叠加到一张字段表（同键覆盖，未声明键原样保留）。

    已知键覆盖 label/help；`add_unknown=True` 时，包为框架未登记的键声明了标签/说明 →
    补一个 `soft_label` 纯展示字段（校验短路）。对 obj 子字段递归下钻（同一顶层键
    在外层与嵌套层都出现时都覆盖——包声明是「模块内扁平键表」）。
    """
    out: Dict[str, FieldMeta] = dict(fields)
    for key, fm in fields.items():
        kw: Dict[str, object] = {}
        if key in labels:
            kw["label"] = labels[key]
        if key in helps:
            kw["help"] = helps[key]
        new = replace(fm, **kw) if kw else fm
        new = _apply_display_children(new, labels, helps)
        if new is not fm:
            out[key] = new
    if add_unknown:
        for key, label in labels.items():
            if key not in out:
                out[key] = _display_field(label, helps.get(key, ""))
        for key, help_text in helps.items():
            if key not in out:
                out[key] = _display_field("", help_text)
    return out


def _apply_display_children(fm: FieldMeta,
                            labels: Mapping[str, str],
                            helps: Mapping[str, str]) -> FieldMeta:
    """递归覆盖 obj 子字段 / list 元素对象子字段的 label/help（不新增嵌套键）。"""
    new = fm
    if fm.children:
        new = replace(new, children=_apply_display(fm.children, labels, helps, False))
    if fm.element is not None and fm.element.children:
        new = replace(new, element=replace(
            fm.element, children=_apply_display(fm.element.children, labels, helps, False)))
    return new


def _merge_module(base_mod: Optional[ModuleMeta], mod: str,
                  labels: Mapping[str, str], helps: Mapping[str, str],
                  groups: Mapping[str, str]) -> ModuleMeta:
    """单模块合并：labels/helps 逐键覆盖，groups 逐键覆盖（未声明键保持现状）。"""
    if base_mod is None:
        # 框架未登记该模块：只造「纯展示壳」——entry_type 留空 = api 层按实际数据推断，
        # 行为与「无模块元数据」一致，仅多出包声明的中文名/说明/分组。
        fields: Dict[str, FieldMeta] = {}
        for key in labels:
            fields[key] = _display_field(labels[key], helps.get(key, ""))
        for key, help_text in helps.items():
            if key not in fields:
                fields[key] = _display_field("", help_text)
        return ModuleMeta(entry_type="", fields=fields,
                          group_labels=dict(groups))
    merged_groups: Dict[str, str] = dict(base_mod.group_labels)
    merged_groups.update(groups)
    kw: Dict[str, object] = {
        "fields": _apply_display(base_mod.fields, labels, helps, True),
        "group_labels": merged_groups,
    }
    if base_mod.value_meta is not None and base_mod.value_meta.type == "obj":
        # map 形态模块（如 stats）：字段表面在 value_meta.children——一并覆盖，
        # 且包声明的新键补到该表面（否则声明了也不显示）。
        kw["value_meta"] = replace(base_mod.value_meta, children=_apply_display(
            base_mod.value_meta.children, labels, helps, True))
    return replace(base_mod, **kw)


def merge_field_meta_table(base: FieldMetaTable,
                           decl: PackFieldMeta) -> FieldMetaTable:
    """把包声明叠加到框架表（**包声明优先，框架兜底**）；返回新表，不改 base。"""
    modules: Dict[str, ModuleMeta] = dict(base.modules)
    mods = set(decl.field_labels) | set(decl.field_help) | set(decl.group_labels)
    for mod in mods:
        modules[mod] = _merge_module(
            base.modules.get(mod), mod,
            decl.field_labels.get(mod, {}),
            decl.field_help.get(mod, {}),
            decl.group_labels.get(mod, {}),
        )
    return FieldMetaTable(modules=modules, namespaces=dict(base.namespaces))


__all__ = [
    "FIELD_META_FILENAME",
    "SCHEMA_VERSION",
    "TOP_LEVEL_KEYS",
    "PackFieldMeta",
    "PackFieldMetaError",
    "load_field_meta",
    "merge_field_meta_table",
    "parse_field_meta",
]
