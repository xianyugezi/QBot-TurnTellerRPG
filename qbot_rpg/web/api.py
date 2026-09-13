"""只读元数据读取层：把「内容包元数据」翻译成编辑器可直接渲染的 JSON。

编辑器重写批1（docs/编辑器重写_实现方案.md §三）唯一实现点：

  · 模块列表        ← manifest.modules（包数据）
  · 模块显示名      ← manifest.module_labels / module_tree 节点的 label（缺省用模块键名）
  · 模块层级（父子）← manifest.module_tree（别名 module_groups）；**包不声明就平铺**
  · 字段清单        ← default_field_meta_table() 的 ModuleMeta.fields
                      （FieldMeta.type / label / required / enum / ref_target / range）
  · 字段分组        ← FieldMeta.group → ModuleMeta.field_groups[key] → 单一默认分组（兜底）
  · 分组页签        ← ModuleMeta.group_order（顺序）/ group_labels（显示名，缺省用组键）/
                       field_groups（成员）；声明了但本条目无字段的组也保留（count=0，前端空态）
  · 字段类型 → 控件形态 ← _WIDGET_BY_TYPE + _EDIT_BY_WIDGET + list_control（本文件唯一映射点；
>    前端只按 descriptor.control 渲染，不认字段类型）；批4 起 list 可编辑（listtable/reflist）
  · 引用的显示名    ← 引用目标 kind 的名称索引（扫描各模块条目 id→name 构建；命名空间合并）

铁律：本文件不得出现任何内容包的模块名或业务字段名（举例本身就会污染这条判断，故不举例）；
换一个内容包，本层零改动可用（判断标准见 docs/编辑器重写_需求与约束.md 第〇节）。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta

# 无任何分组声明时的单一默认分组（缺省兜底；编辑器不因包缺元数据而空白）。
DEFAULT_GROUP = "默认"
# 面板顶部「元数据来源」标注（前端展示；来源 = 字段元数据表）。
META_SOURCE = "qbot_rpg/content/field_meta.py · FieldMetaTable"
# loader/BaseDef 的框架级约定字段（不是业务字段名）：显示名 / 标识。
_NAME_FIELD = "name"
_ID_FIELD = "id"
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")
_MAX_DEPTH = 3  # 只读视图嵌套深度上限（防递归爆栈/响应过大）
_MAX_TABLE_ROWS = 200  # 列表字段只读表格最多渲染行数（超出截断并标注 row_count）


class EditorError(Exception):
    """编辑器读取层领域异常基类（宿主 scripts/editor_host.py 映射为 HTTP JSON）。"""

    status_code = 500


class BadRequest(EditorError):
    """请求参数非法（400）。"""

    status_code = 400


class NotFound(EditorError):
    """内容包/模块/条目不存在（404）。"""

    status_code = 404


class Forbidden(EditorError):
    """当前身份只读、拒绝写入（403）。"""

    status_code = 403


# =====================================================================================
# 路径与文件读取（含 mtime 缓存；只读，不写盘）
# =====================================================================================
def repo_root() -> Path:
    """仓库根目录（本文件位于 <root>/qbot_rpg/web/api.py）。"""
    return Path(__file__).resolve().parents[2]


def content_root(root: Optional[object] = None) -> Path:
    """内容包根目录：显式传入则用之，否则默认 <仓库根>/content。"""
    if root is None:
        return repo_root() / "content"
    return Path(str(root))


def _check_component(name: object, what: str) -> str:
    """校验包名/模块名（防路径穿越；只用它们拼文件路径）。"""
    if not isinstance(name, str) or not _SAFE_COMPONENT.match(name):
        raise BadRequest(f"非法{what}：{name!r}")
    return name


def _pack_dir(pack: object, root: Optional[object]) -> Path:
    pid = _check_component(pack, "内容包名")
    d = content_root(root) / pid
    if not (d / "manifest.json").is_file():
        raise NotFound(f"内容包不存在或缺少 manifest.json：{pid}")
    return d


@lru_cache(maxsize=1024)
def _read_json_cached(path_str: str, mtime_ns: int) -> Optional[object]:
    try:
        with Path(path_str).open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:  # 坏 JSON 不炸宿主，转领域异常
        raise EditorError(f"读取/解析 JSON 失败：{path_str}（{exc}）") from exc


def _read_json(path: Path) -> Optional[object]:
    """读 JSON（文件不存在 → None；mtime 变化自动失效缓存）。"""
    try:
        st = path.stat()
    except OSError:
        return None
    return _read_json_cached(str(path), st.st_mtime_ns)


def _manifest(pack_dir: Path) -> Dict[str, Any]:
    raw = _read_json(pack_dir / "manifest.json")
    if not isinstance(raw, Mapping):
        raise EditorError(f"manifest 形态非法（应为对象）：{pack_dir.name}")
    return dict(raw)


# =====================================================================================
# 元数据表（进程内单例，只读）
# =====================================================================================
_META_TABLE: Optional[FieldMetaTable] = None


def field_meta_table() -> FieldMetaTable:
    """缺省字段元数据表单例（只读；全部字段/分组/类型的唯一来源）。"""
    global _META_TABLE
    if _META_TABLE is None:
        _META_TABLE = default_field_meta_table()
    return _META_TABLE


def _module_meta(module: str) -> Optional[ModuleMeta]:
    return field_meta_table().module(module)


# =====================================================================================
# manifest 读取（模块清单 / 显示名 / 层级声明）
# =====================================================================================
def _declared_modules(manifest: Mapping[str, Any]) -> List[str]:
    raw = manifest.get("modules")
    out: List[str] = []
    for m in raw if isinstance(raw, list) else []:
        if isinstance(m, str) and m and m not in out:
            out.append(m)
    return out


def _module_labels(manifest: Mapping[str, Any]) -> Dict[str, str]:
    raw = manifest.get("module_labels")
    out: Dict[str, str] = {}
    if isinstance(raw, Mapping):
        for k, v in raw.items():
            if isinstance(k, str) and isinstance(v, str) and v:
                out[k] = v
    return out


def _resolve_tree(
    manifest: Mapping[str, Any], declared: List[str]
) -> Tuple[Dict[str, List[str]], Dict[str, str], List[str]]:
    """读包的模块层级声明 → (children_map, node_labels, notes)。

    声明键 `module_tree`（别名 `module_groups`），节点形态三种：
      1) 字符串                 → 顶层模块（无子）
      2) {"module": p, "label": "...", "children": ["c", {...}]}
      3) {"p": ["c1", "c2"]}    映射形态（父: 子列表）
    非法/未声明/自环/重复引用一律忽略并记 note（包声明有瑕疵也不让编辑器崩）。
    """
    declared_set = set(declared)
    children: Dict[str, List[str]] = {}
    labels: Dict[str, str] = {}
    notes: List[str] = []
    seen_child: set = set()
    spec = manifest.get("module_tree")
    if spec is None:
        spec = manifest.get("module_groups")

    def walk(node: object, path: List[str]) -> Optional[str]:
        if isinstance(node, str):
            if node not in declared_set:
                notes.append(f"层级声明引用未声明模块：{node}")
                return None
            return node
        if not isinstance(node, Mapping):
            notes.append(f"层级声明非法节点：{node!r}")
            return None
        mod = node.get("module") or node.get("id") or node.get("name")
        if not isinstance(mod, str) or mod not in declared_set:
            notes.append(f"层级声明节点缺少合法 module：{dict(node)!r}")
            return None
        lbl = node.get("label")
        if isinstance(lbl, str) and lbl:
            labels[mod] = lbl
        kids = node.get("children")
        if kids is None:
            kids = node.get("modules")
        for child in kids if isinstance(kids, list) else []:
            cid = walk(child, path + [mod])
            if not cid:
                continue
            if cid == mod or cid in path or cid in (path + [mod]):
                notes.append(f"层级声明忽略自环/回环：{mod} ▸ {cid}")
                continue
            if cid in seen_child:
                notes.append(f"层级声明重复子项（忽略）：{cid}")
                continue
            children.setdefault(mod, []).append(cid)
            seen_child.add(cid)
        return mod

    if isinstance(spec, list):
        for node in spec:
            walk(node, [])
    elif isinstance(spec, Mapping):
        for parent, kid_spec in spec.items():
            if not isinstance(parent, str) or parent not in declared_set:
                notes.append(f"层级声明引用未声明模块：{parent!r}")
                continue
            body = dict(kid_spec) if isinstance(kid_spec, Mapping) else {"children": kid_spec}
            walk({"module": parent, **body}, [])
    elif spec is not None:
        notes.append("module_tree 形态非法（应为数组/对象），已按平铺处理")
    return children, labels, notes


def _display_labels(manifest: Mapping[str, Any], declared: List[str]) -> Dict[str, str]:
    labels = _module_labels(manifest)
    _children, tree_labels, _notes = _resolve_tree(manifest, declared)
    labels.update(tree_labels)
    return labels


# =====================================================================================
# 只读 API ①：内容包发现
# =====================================================================================
def list_packs(root: Optional[object] = None, preferred: Optional[str] = None) -> Dict[str, Any]:
    """可用内容包清单（`/api/packs`）。preferred 命中时作为 default 返回。"""
    base = content_root(root)
    packs: List[Dict[str, Any]] = []
    if base.is_dir():
        for entry in sorted(base.iterdir(), key=lambda p: p.name):
            if not entry.is_dir():
                continue
            man = _read_json(entry / "manifest.json")
            if not isinstance(man, Mapping):
                continue
            packs.append({
                "id": entry.name,
                "name": str(man.get("name", "") or entry.name),
                "version": str(man.get("version", "") or ""),
                "module_count": len(_declared_modules(man)),
            })
    ids = [p["id"] for p in packs]
    if isinstance(preferred, str) and preferred in ids:
        default = preferred
    else:
        default = ids[0] if ids else ""
    return {"packs": packs, "default": default}


# =====================================================================================
# 只读 API ②：模块层级（父子；包不声明即平铺）
# =====================================================================================
def _entry_count(data: object) -> int:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, Mapping):
        return len(data)
    return 0


def list_modules(pack: object, root: Optional[object] = None) -> Dict[str, Any]:
    """模块分类树（`/api/pack/{pack}/modules`）。

    返回项：{module, label, count(含后代合计), own_count, children[]}。
    `flat=True` 表示包未声明任何层级（平铺）。
    """
    pack_dir = _pack_dir(pack, root)
    manifest = _manifest(pack_dir)
    declared = _declared_modules(manifest)
    children_map, tree_labels, notes = _resolve_tree(manifest, declared)
    labels = _module_labels(manifest)
    labels.update(tree_labels)
    counts = {m: _entry_count(_read_json(pack_dir / f"{m}.json")) for m in declared}
    child_set = {c for kids in children_map.values() for c in kids}

    def node(mod: str, stack: List[str]) -> Dict[str, Any]:
        kids = [node(c, stack + [c]) for c in children_map.get(mod, []) if c not in stack]
        own = counts.get(mod, 0)
        return {
            "module": mod,
            "label": labels.get(mod) or mod,
            "count": own + sum(k["count"] for k in kids),
            "own_count": own,
            "children": kids,
        }

    modules = [node(m, [m]) for m in declared if m not in child_set]
    return {
        "pack": str(pack),
        "pack_name": str(manifest.get("name", "") or pack),
        "modules": modules,
        "flat": not children_map,
        "notes": notes,
    }


# =====================================================================================
# 只读 API ③：模块条目列表（id + 名称，只名字）
# =====================================================================================
def _entry_rows(data: object, mmeta: Optional[ModuleMeta]) -> List[Tuple[str, str, object]]:
    """条目三元组 (id, 名称, 原始值)。

    list 模块 → 每个元素一条；map 模块 → 每个键一条；object 模块 → 每个顶层段一条
    （名取字段元数据 label，缺省用键名）。无 id 的元素回退 `#i`（不因缺键丢条目）。
    """
    id_field = (mmeta.id_field if mmeta is not None and mmeta.id_field else _ID_FIELD)
    etype = mmeta.entry_type if mmeta is not None else None
    out: List[Tuple[str, str, object]] = []
    if isinstance(data, list):
        for i, elem in enumerate(data):
            if isinstance(elem, Mapping):
                eid = elem.get(id_field)
                if not isinstance(eid, str) or not eid:
                    eid = elem.get(_ID_FIELD)
                eid = eid if isinstance(eid, str) and eid else f"#{i}"
                nm = elem.get(_NAME_FIELD)
                name = nm if isinstance(nm, str) and nm else eid
            else:
                eid, name = f"#{i}", str(elem)
            out.append((eid, name, elem))
        return out
    if isinstance(data, Mapping):
        for key, val in data.items():
            k = str(key)
            if etype == "object":
                fm = mmeta.fields.get(k) if mmeta is not None else None
                name = fm.label if fm is not None and fm.label else k
            else:
                nm = val.get(_NAME_FIELD) if isinstance(val, Mapping) else None
                name = nm if isinstance(nm, str) and nm else k
            out.append((k, name, val))
    return out


def list_entries(pack: object, module: object, root: Optional[object] = None) -> Dict[str, Any]:
    """当前模块的条目列表（`/api/pack/{pack}/module/{mod}/entries`；只 id + 名称）。"""
    pack_dir = _pack_dir(pack, root)
    manifest = _manifest(pack_dir)
    declared = _declared_modules(manifest)
    mod = _check_component(module, "模块名")
    if mod not in declared:
        raise NotFound(f"模块未在包 manifest 中声明：{mod}")
    data = _read_json(pack_dir / f"{mod}.json")
    mmeta = _module_meta(mod)
    rows = _entry_rows(data, mmeta)
    etype = mmeta.entry_type if mmeta is not None else _infer_entry_type(data)
    labels = _display_labels(manifest, declared)
    return {
        "pack": str(pack),
        "module": mod,
        "label": labels.get(mod) or mod,
        "entry_type": etype,
        "count": len(rows),
        "entries": [{"id": eid, "name": name} for eid, name, _val in rows],
    }


def _infer_entry_type(data: object) -> str:
    if isinstance(data, list):
        return "list"
    if isinstance(data, Mapping):
        return "map"
    return "scalar"


# =====================================================================================
# 字段类型 → 只读形态（唯一映射点；前端只按 widget 渲染）
# =====================================================================================
_WIDGET_BY_TYPE: Dict[str, str] = {
    "str": "text", "text": "text",
    "int": "number", "float": "number", "number": "number",
    "bool": "bool",
    "enum": "enum",
    "ref": "ref",
    "list": "list",
    "obj": "obj",
    "map": "map",
    "formula": "formula",
}


def _widget_for_type(ftype: Optional[str]) -> str:
    return _WIDGET_BY_TYPE.get(ftype or "", "text")


def readonly_form(field_type: Optional[str]) -> str:
    """FieldMeta.type → 只读控件形态（§三 映射表唯一实现点；前端只按返回值渲染）。"""
    return _widget_for_type(field_type)


# 控件形态 → (编辑控件, 是否可编辑)：§三 映射表第二级（唯一实现点）。
# control 取值（前端只认这个，不认字段类型）：
#   text / textarea / number / bool / select / ref / listtable / reflist / readonly
# 批4 范围：list 升级为可编辑（元素为 obj/标量 → 可增删行表格 listtable；
# 元素为 ref → 引用多选 reflist）；obj（除列表内联对象）与 map 仍只读展示。
_EDIT_BY_WIDGET: Dict[str, Tuple[str, bool]] = {
    "text": ("text", True),
    "number": ("number", True),
    "bool": ("bool", True),
    "enum": ("select", True),
    "ref": ("ref", True),
    "formula": ("text", True),  # 表达式文本；值实为对象时按值形态纠偏为 obj → 只读
    "list": ("listtable", True),
    "obj": ("readonly", False),
    "map": ("readonly", False),
}
EDIT_CONTROLS: Tuple[str, ...] = (
    "text", "textarea", "number", "bool", "select", "ref",
    "listtable", "reflist", "readonly",
)


def list_control(fm: Optional[FieldMeta]) -> str:
    """列表字段的控件形态判定（§三 映射表；前端只认 control，不认元素类型）。

    · 元素为引用（`element.type == "ref"`）→ `reflist`（引用多选：可搜、名称显示、逐个清除）；
    · 其余（元素为 obj / 标量 / 无元数据）→ `listtable`（可增删行表格）。
    """
    elem = fm.element if fm is not None else None
    if elem is not None and elem.type == "ref":
        return "reflist"
    return "listtable"


def control_of(widget: Optional[str], multiline: bool = False) -> str:
    """控件形态 → 编辑控件（multiline 仅对文本生效：text → textarea）。"""
    control, _editable = _EDIT_BY_WIDGET.get(widget or "", ("text", True))
    if control == "text" and multiline:
        return "textarea"
    return control


def is_editable_widget(widget: Optional[str]) -> bool:
    """控件形态是否本批可编辑（只读形态 = list/obj/map）。"""
    return _EDIT_BY_WIDGET.get(widget or "", ("text", True))[1]


def editable_form(field_type: Optional[str], *, multiline: bool = False) -> Dict[str, Any]:
    """FieldMeta.type → {widget, control, editable}（§三 映射表唯一实现点）。

    编辑器（只读渲染与编辑控件）一律经本函数 + control_of 取形态；
    业务模块不得新增映射特例（判断标准见 docs/编辑器重写_需求与约束.md 第〇节）。
    """
    widget = _widget_for_type(field_type)
    return {
        "widget": widget,
        "control": control_of(widget, multiline),
        "editable": is_editable_widget(widget),
    }


def _is_long_text(value: object) -> bool:
    """长文本启发式（元数据未声明 multiline 时的兜底）：含换行或超长 → 多行控件。"""
    return isinstance(value, str) and ("\n" in value or len(value) > 80)


def _number_step(ftype: str) -> str:
    """数字控件的步进（int 整数步进 / float·number 任意小数），仅作前端提示不硬拦。"""
    return "1" if ftype == "int" else "any"


def _infer_type(value: object) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, Mapping):
        return "obj"
    return "str"


def _effective_widget(fm: Optional[FieldMeta], value: object) -> str:
    """元数据类型 + 实际值形态 → 只读控件形态（元数据优先，值形态纠偏防渲染崩）。"""
    base = _widget_for_type(fm.type if fm is not None else None)
    if value is None:
        return base
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number" if base in ("text", "number") else base
    if isinstance(value, str):
        return "text" if base in ("bool", "number", "list", "obj", "map") else base
    if isinstance(value, list):
        return "list"
    if isinstance(value, Mapping):
        return "obj" if base == "obj" else "map"
    return base


def _scalar_display(value: object, widget: str, view: "_PackView",
                    ref_target: Optional[str] = None) -> str:
    if value is None:
        return ""
    if widget == "bool":
        return "是" if value else "否"
    if widget == "ref" and isinstance(value, str):
        name = view.resolve(ref_target, value)
        if name and name != value:
            return f"{name}（{value}）"
        return name or value
    if widget == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(int(value)) if float(value).is_integer() else str(value)
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return ""


def _hint(fm: Optional[FieldMeta]) -> str:
    """字段元数据的人话提示（面向非技术用户；无声明时如实标注）。"""
    if fm is None:
        return "内容包里有这个键、元数据未登记（类型按实际值推断）"
    bits: List[str] = []
    if fm.required:
        bits.append("必填")
    if fm.enum:
        bits.append("可选：" + " / ".join(str(x) for x in fm.enum))
    if fm.ref_target:
        bits.append(f"引用：{fm.ref_target}")
    if fm.range_min is not None or fm.range_max is not None:
        lo = "" if fm.range_min is None else f"{fm.range_min:g}"
        hi = "" if fm.range_max is None else f"{fm.range_max:g}"
        if lo and hi:
            bits.append(f"建议范围 {lo}~{hi}")
        elif lo:
            bits.append(f"建议 ≥{lo}")
        else:
            bits.append(f"建议 ≤{hi}")
    if fm.zero_unlimited:
        bits.append("0 = 不限")
    if fm.default is not None:
        bits.append(f"默认 {fm.default}")
    return "；".join(bits)


# =====================================================================================
# 字段说明卡（批4.6）：自动拼装（全部来自既有元数据）+ 人工 help（qbot_rpg/content/field_meta）
# =====================================================================================
# 分工（用户原话：「点击中文名/鼠标悬停显示这个字段的详细解释」）：
#   · **自动拼装**（本段，一定能出，换包零改动）：字段名（中文+原始键）、类型语义、
#     数值还是比例/百分比、建议范围、默认值、是否必填、枚举候选、引用目标；
#   · **人工补充**：`FieldMeta.help`（元数据层撰写的一句话说明）——可选，缺省不报错。
# 本段只做展示拼装，不触碰任何校验判定（type/required/default/enum/range 均只读）。
_TYPE_SEMANTIC: Dict[str, str] = {
    "str": "文本", "text": "文本",
    "int": "数字", "float": "数字", "number": "数字",
    "bool": "布尔", "enum": "枚举", "ref": "引用",
    "list": "列表", "obj": "对象", "map": "映射", "formula": "公式",
}
_NUMERIC_TYPES: Tuple[str, ...] = ("int", "float", "number")


def _type_semantic(ftype: Optional[str]) -> str:
    """FieldMeta.type → 中文类型语义（未登记类型如实说「未标注」，不猜）。"""
    return _TYPE_SEMANTIC.get(ftype or "", "未标注")


def _scale_semantic(fm: Optional[FieldMeta]) -> str:
    """「是数值还是比例/百分比」判定。

    依据优先序：probability 旗标 → unit（`%` 为百分比、其余为带单位数值）→
    数值型且区间恰为 0~1（推断可能是比例）→ 其余数值「未标注单位」→ 非数值「不适用」。
    判不出来的如实说「未标注」/「未标注单位」，不臆造。
    """
    if fm is None:
        return "未标注"
    if fm.probability:
        return "比例（0~1，按百分比表示概率）"
    if fm.unit == "%":
        return "百分比（数值自带 % 单位）"
    if fm.unit:
        return f"数值（单位：{fm.unit}）"
    if fm.type in _NUMERIC_TYPES:
        if fm.range_min == 0 and fm.range_max == 1:
            return "比例（0~1；元数据未标注百分比单位）"
        return "数值（未标注单位）"
    return "不适用（非数值字段）"


def _range_semantic(fm: Optional[FieldMeta]) -> str:
    """建议范围人话（range_min~range_max；zero_unlimited 写明「0 = 不限」）。"""
    if fm is None or (fm.range_min is None and fm.range_max is None):
        return "未标注"
    if fm.range_min is None:
        text = f"建议 ≤ {fm.range_max:g}"
    elif fm.range_max is None:
        text = f"建议 ≥ {fm.range_min:g}"
    else:
        text = f"建议 {fm.range_min:g} ~ {fm.range_max:g}"
    if fm.zero_unlimited:
        text += "；0 = 不限"
    return text


def _default_text(value: object) -> str:
    """默认值的人话展示（布尔用是/否；复合值转紧凑 JSON）。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (list, tuple)):
        return "、".join(str(x) for x in value) if value else "（空列表）"
    if isinstance(value, Mapping):
        return _json_text(value)
    return str(value)


def help_card(key: str, fm: Optional[FieldMeta]) -> Dict[str, Any]:
    """字段说明卡数据（自动拼装 + 人工 help）；全部是可直接展示的中文短语。

    前端只按本结构渲染，不认字段类型、不认任何业务字段名（保持元数据驱动）。
    元数据未登记（fm=None）→ unregistered=True，自动拼装如实标注「未登记」。
    """
    if fm is None:
        return {
            "key": key, "label": key, "type": "未登记", "scale": "未标注",
            "range": "未标注", "default": "未标注", "required": False,
            "enum": [], "ref_target": None, "unit": "", "help": "",
            "unregistered": True,
        }
    default = _default_text(fm.default)
    return {
        "key": key,
        "label": fm.label or key,
        "type": _type_semantic(fm.type),
        "scale": _scale_semantic(fm),
        "range": _range_semantic(fm),
        "default": default or "无默认值",
        "required": bool(fm.required),
        "enum": [str(x) for x in fm.enum],
        "ref_target": fm.ref_target,
        "unit": fm.unit,
        "help": fm.help,
        "unregistered": False,
    }


def _resolve_group(key: str, fm: Optional[FieldMeta], mmeta: Optional[ModuleMeta]) -> str:
    """分组解析（缺省兜底）：FieldMeta.group → 模块分组表 → 单一默认分组。"""
    if fm is not None and fm.group:
        return fm.group
    if mmeta is not None and key in mmeta.field_groups:
        return mmeta.field_groups[key]
    return DEFAULT_GROUP


def _json_text(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)


# =====================================================================================
# 引用名称解析（ref_target kind → {id: 名称}）
# =====================================================================================
class _PackView:
    """一次读取的内容包视图：模块元数据 + 引用名称索引（惰性构建）。"""

    def __init__(self, pack_dir: Path, manifest: Mapping[str, Any]) -> None:
        self.dir = pack_dir
        self.manifest = manifest
        self.declared = _declared_modules(manifest)
        self._names: Optional[Dict[str, Dict[str, str]]] = None

    def name_index(self) -> Dict[str, Dict[str, str]]:
        if self._names is None:
            self._names = _build_name_index(self.dir, self.declared, field_meta_table())
        return self._names

    def resolve(self, ref_target: Optional[str], value: object) -> Optional[str]:
        if not isinstance(ref_target, str) or not isinstance(value, str):
            return None
        idx = self.name_index()
        table = idx.get(ref_target)
        if table is None and ref_target.endswith("_or_any"):
            table = idx.get(ref_target[: -len("_or_any")])
        if table is None:
            return None
        return table.get(value)


def _build_name_index(pack_dir: Path, declared: List[str],
                      meta: FieldMetaTable) -> Dict[str, Dict[str, str]]:
    collected: Dict[str, Dict[str, str]] = {}
    kinds: Dict[str, str] = {}
    for mod in declared:
        mm = meta.module(mod)
        kinds[mod] = mm.kind if mm is not None and mm.kind else mod
        data = _read_json(pack_dir / f"{mod}.json")
        table: Dict[str, str] = {}
        if isinstance(data, list):
            for i, elem in enumerate(data):
                if not isinstance(elem, Mapping):
                    continue
                eid = elem.get(_ID_FIELD)
                eid = eid if isinstance(eid, str) and eid else f"#{i}"
                nm = elem.get(_NAME_FIELD)
                table[eid] = nm if isinstance(nm, str) and nm else eid
        elif isinstance(data, Mapping):
            for key, val in data.items():
                nm = val.get(_NAME_FIELD) if isinstance(val, Mapping) else None
                table[str(key)] = nm if isinstance(nm, str) and nm else str(key)
        collected[mod] = table
    index: Dict[str, Dict[str, str]] = {}
    for mod in declared:
        index.setdefault(kinds[mod], {}).update(collected[mod])
        index.setdefault(mod, {}).update(collected[mod])
    # 命名空间（跨模块 ID 空间）合并：如共享同一 namespace 的多个模块互相可解析。
    for _ns, mods in (meta.namespaces or {}).items():
        members = [m for m in mods if m in collected]
        if len(members) < 2:
            continue
        merged: Dict[str, str] = {}
        for mod in members:
            merged.update(collected[mod])
        for mod in members:
            index.setdefault(kinds[mod], {}).update(merged)
    return index


# =====================================================================================
# 只读 API ④：条目全字段 + 分组 + 每字段类型
# =====================================================================================
def _column(key: str, fm: Optional[FieldMeta], key_label: Optional[str] = None) -> Dict[str, Any]:
    """列表表格的一列：列名/类型来自元素字段元数据（缺省按值推断）。

    批4 起列描述同时携带**编辑**所需信息（control/enum/number_step/default），
    前端按 control 渲染单元格，不认字段类型（映射仍在 api 层唯一实现）。
    """
    ftype = fm.type if fm is not None else _infer_type(None)
    widget = _widget_for_type(fm.type if fm is not None else None)
    multiline = bool(getattr(fm, "multiline", False)) if fm is not None else False
    return {
        "key": key,
        "label": (fm.label if fm is not None and fm.label else (key_label or key)),
        "type": ftype,
        "widget": widget,
        "control": control_of(widget, multiline) if widget != "list" else list_control(fm),
        "ref_target": fm.ref_target if fm is not None else None,
        "enum": [str(x) for x in fm.enum] if fm is not None and fm.enum else [],
        "number_step": _number_step(ftype),
        "default": fm.default if fm is not None else None,
        # 批4.6：列头也可出说明卡（自动拼装 + 人工 help），与主表单同源。
        "unit": fm.unit if fm is not None else "",
        "help": fm.help if fm is not None else "",
        "help_card": help_card(key, fm),
    }


def _row_default(elem: Optional[FieldMeta], scalar_element: bool) -> object:
    """新增行的初始值（元数据 default 驱动；未声明 default 的键不写，保持「未填」）。"""
    if elem is None:
        return None
    if not scalar_element and elem.type == "obj":
        out: Dict[str, Any] = {}
        for ck, cfm in (elem.children or {}).items():
            if cfm.default is not None:
                out[str(ck)] = cfm.default
        return out
    return elem.default


def _is_scalar_element(elem: Optional[FieldMeta], rows: List[object]) -> bool:
    """列表元素是否为标量行（obj 元素 → False；无元数据时按实际行形态推断）。"""
    if elem is not None:
        return elem.type != "obj"
    if rows:
        return not any(isinstance(r, Mapping) for r in rows)
    return True


def _ref_valid(view: "_PackView", ref_target: Optional[str], value: object) -> bool:
    """引用值是否存在（空值视为「未填」不算非法；未知目标/找不到名称 → 非法）。"""
    if value is None or value == "":
        return True
    if not isinstance(value, str):
        return False
    return view.resolve(ref_target, value) is not None


def _list_columns(fm: Optional[FieldMeta], rows: List[object]) -> List[Dict[str, Any]]:
    """列表字段的只读表列：元素元数据声明优先；实际行里多出的键按值推断补列。"""
    elem = fm.element if fm is not None else None
    cols: List[Dict[str, Any]] = []
    known: set = set()
    if elem is not None and elem.type == "obj" and elem.children:
        for ck, cfm in elem.children.items():
            cols.append(_column(str(ck), cfm))
        known = set(str(k) for k in elem.children)
    elif elem is not None and elem.type in (
        "ref", "str", "number", "int", "float", "bool", "enum"
    ):
        cols.append(_column("value", elem, key_label="值"))
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for k in row:
            if not isinstance(k, str) or k in known:
                continue
            known.add(k)
            cols.append(_column(k, None))
    if not cols:
        # 元素声明为 obj 但没有子字段、也没有数据行可推断键 → 不出列（前端提示补元数据），
        # 不臆造「value」键（否则会把对象行改写成 {"value": …} 破坏原形态）。
        if elem is not None and elem.type == "obj":
            return []
        cols.append(_column("value", None, key_label="值"))
    return cols


def _table_rows(rows: List[object], cols: List[Dict[str, Any]],
                view: "_PackView") -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for row in rows[:_MAX_TABLE_ROWS]:
        cells: Dict[str, str] = {}
        for col in cols:
            if isinstance(row, Mapping):
                raw = row.get(col["key"])
            elif col is cols[0]:
                raw = row
            else:
                raw = None
            if isinstance(raw, (Mapping, list)):
                cells[col["key"]] = _json_text(raw)
            else:
                cells[col["key"]] = _scalar_display(raw, col["widget"], view, col["ref_target"])
        out.append(cells)
    return out


def _object_children(fm: Optional[FieldMeta], value: Mapping[str, Any],
                     mmeta: Optional[ModuleMeta], view: "_PackView",
                     depth: int) -> List[Dict[str, Any]]:
    if depth >= _MAX_DEPTH:
        return []
    base = dict(fm.children) if fm is not None and fm.children else {}
    return _build_fields(base, value, mmeta, view, depth)


def _descriptor(key: str, fm: Optional[FieldMeta], value: object, present: bool,
                mmeta: Optional[ModuleMeta], view: "_PackView", depth: int) -> Dict[str, Any]:
    widget = _effective_widget(fm, value)
    ftype = fm.type if fm is not None else _infer_type(value)
    label = fm.label if fm is not None and fm.label else (key or ftype)
    multiline = bool(getattr(fm, "multiline", False)) if fm is not None else False
    if not multiline and widget == "text":
        multiline = _is_long_text(value)  # 元数据未声明时的兜底（长文本仍给多行控件）
    desc: Dict[str, Any] = {
        "key": key,
        "label": label,
        "type": ftype,
        "widget": widget,
        "control": (list_control(fm) if widget == "list"
                    else control_of(widget, multiline)),
        "editable": is_editable_widget(widget),
        "multiline": multiline,
        "group": _resolve_group(key, fm, mmeta),
        "required": bool(fm.required) if fm is not None else False,
        "present": present,
        "value": value,
        "display": _scalar_display(value, widget, view, fm.ref_target if fm is not None else None),
        "ref_target": fm.ref_target if fm is not None else None,
        "enum": [str(x) for x in fm.enum] if fm is not None and fm.enum else [],
        "number_step": _number_step(ftype),
        "hint": _hint(fm),
        # 批4.6：说明卡（自动拼装 + 人工 help）——前端悬停/点击中文名时展示。
        "unit": fm.unit if fm is not None else "",
        "help": fm.help if fm is not None else "",
        "help_card": help_card(key, fm),
        "columns": [],
        "rows": [],
    }
    if widget == "ref":
        # 批4：引用值是否指向存在的目标（空值不算非法）→ 前端黄提示、不红拦。
        desc["ref_valid"] = _ref_valid(view, fm.ref_target if fm is not None else None, value)
    if widget == "list":
        # 值缺失/为 null 也要按元数据出列（空列表仍有列头与「+ 添加一行」的默认值）
        rows_val: List[object] = value if isinstance(value, list) else []
        cols = _list_columns(fm, rows_val)
        desc["columns"] = cols
        desc["rows"] = _table_rows(rows_val, cols, view)
        desc["row_count"] = len(rows_val)
        elem = fm.element if fm is not None else None
        if elem is not None and elem.type == "ref":
            desc["ref_target"] = elem.ref_target  # 引用多选的候选目标在元素元数据上
        scalar_element = _is_scalar_element(elem, rows_val)
        desc["scalar_element"] = scalar_element
        desc["row_default"] = _row_default(elem, scalar_element)
        # 批4：非法引用标记（黄提示、不红拦）——元素是引用 → 收集非法值；
        # 元素 obj 内引用子字段 → 逐单元格收集（供前端就地把该格标黄）。
        desc["invalid_refs"] = (
            [str(v) for v in rows_val if not _ref_valid(view, elem.ref_target, v)]
            if elem is not None and elem.type == "ref" else []
        )
        invalid_cells: List[Dict[str, Any]] = []
        if elem is not None and elem.type == "obj" and elem.children:
            for i, row in enumerate(rows_val):
                if not isinstance(row, Mapping):
                    continue
                for ck, cfm in elem.children.items():
                    if cfm.type != "ref":
                        continue
                    rv = row.get(str(ck))
                    if not _ref_valid(view, cfm.ref_target, rv):
                        invalid_cells.append(
                            {"row": i, "key": str(ck), "value": rv})
        desc["invalid_cells"] = invalid_cells
    elif widget == "obj" and isinstance(value, Mapping):
        desc["children"] = _object_children(fm, value, mmeta, view, depth + 1)
    elif widget == "map" and isinstance(value, Mapping):
        desc["rows"] = [
            {"key": str(k), "value": v,
             "display": _scalar_display(v, _effective_widget(None, v), view)}
            for k, v in value.items()
        ]
        desc["row_count"] = len(value)
    return desc


def _build_fields(base: Mapping[str, FieldMeta], subject: object,
                  mmeta: Optional[ModuleMeta], view: "_PackView",
                  depth: int) -> List[Dict[str, Any]]:
    """按声明顺序出字段（缺失也出，标 present=False）；再补实际值里多出的键。"""
    if not isinstance(subject, Mapping):
        if base:
            key, fm = next(iter(base.items()))
        else:
            key, fm = "", None
        return [_descriptor(str(key), fm, subject, True, mmeta, view, depth)]
    fields: List[Dict[str, Any]] = []
    seen: set = set()
    for key, fm in base.items():
        present = key in subject
        fields.append(_descriptor(str(key), fm, subject.get(key) if present else None,
                                  present, mmeta, view, depth))
        seen.add(key)
    for key, val in subject.items():
        if not isinstance(key, str) or key in seen:
            continue
        fields.append(_descriptor(key, None, val, True, mmeta, view, depth))
    return fields


def _entry_base(mmeta: Optional[ModuleMeta], etype: str, entry_id: str,
                subject: object) -> Mapping[str, FieldMeta]:
    """条目值的「字段元数据基表」：list 模块=条目顶层字段，map/object=值字段或段子字段。"""
    if mmeta is None:
        return {}
    if etype == "list":
        return mmeta.fields
    if etype == "map":
        vm = mmeta.value_meta
        if vm is not None and vm.type == "obj" and vm.children:
            return vm.children
        return {entry_id: vm} if vm is not None else {}
    fm = mmeta.fields.get(entry_id)
    if fm is not None and fm.type == "obj" and fm.children:
        return fm.children
    if isinstance(subject, Mapping) and (fm is None or fm.type == "obj"):
        return {}
    return {entry_id: fm} if fm is not None else {}


def _group_summary(fields: List[Dict[str, Any]],
                   mmeta: Optional[ModuleMeta]) -> List[Dict[str, Any]]:
    """分组摘要（页签数据源）：顺序 + 显示名 + 计数，全部来自元数据。

    · 顺序：ModuleMeta.group_order 优先；再按 field_groups（声明顺序）→ group_labels →
      字段中首次出现的顺序补齐。缺省（模块无声明）→ 只有字段兜底组。
    · 显示名：group_labels[组] → 缺省用组键本身（编辑器不写死任何分组词）。
    · **元数据声明了但本条目没有字段落进去的组也保留**（count=0）→ 前端渲染空态文案。
    """
    counts: Dict[str, int] = {}
    for f in fields:
        g = str(f["group"])
        counts[g] = counts.get(g, 0) + 1
    declared: List[str] = []

    def _declare(g: str) -> None:
        if g and g not in declared:
            declared.append(g)

    labels: Mapping[str, str] = {}
    if mmeta is not None:
        for g in mmeta.group_order:
            _declare(str(g))
        for g in mmeta.field_groups.values():
            _declare(str(g))
        labels = mmeta.group_labels
        for g in labels:
            _declare(str(g))
    order: List[str] = list(declared)
    for g in counts:
        if g not in order:
            order.append(g)
    return [
        {"name": g, "label": str(labels.get(g, g)), "count": counts.get(g, 0)}
        for g in order
    ]


def entry_detail(pack: object, module: object, entry_id: object,
                 root: Optional[object] = None) -> Dict[str, Any]:
    """条目只读详情（`/api/pack/{pack}/entry/{mod}/{id}`）：全字段 + 分组 + 每字段类型。"""
    pack_dir = _pack_dir(pack, root)
    manifest = _manifest(pack_dir)
    declared = _declared_modules(manifest)
    mod = _check_component(module, "模块名")
    if mod not in declared:
        raise NotFound(f"模块未在包 manifest 中声明：{mod}")
    if not isinstance(entry_id, str):
        raise BadRequest(f"非法条目标识：{entry_id!r}")
    data = _read_json(pack_dir / f"{mod}.json")
    mmeta = _module_meta(mod)
    rows = _entry_rows(data, mmeta)
    match = next((row for row in rows if row[0] == entry_id), None)
    if match is None:
        raise NotFound(f"条目不存在：{mod}/{entry_id}")
    _eid, entry_name, subject = match
    etype = mmeta.entry_type if mmeta is not None else _infer_entry_type(data)
    view = _PackView(pack_dir, manifest)
    base = _entry_base(mmeta, etype, entry_id, subject)
    fields = _build_fields(base, subject, mmeta, view, 0)
    groups = _group_summary(fields, mmeta)
    labels = _display_labels(manifest, declared)
    return {
        "pack": str(pack),
        "pack_name": str(manifest.get("name", "") or pack),
        "module": mod,
        "module_label": labels.get(mod) or mod,
        "entry_type": etype,
        "id": entry_id,
        "name": entry_name,
        "fields": fields,
        "groups": groups,
        "field_count": len(fields),
        "group_count": len(groups),
        "meta_source": META_SOURCE,
    }


# =====================================================================================
# 只读 API ⑤：写链路数据源（保存前定位条目 / 读整包 / 引用候选）
# =====================================================================================
def declared_module(pack: object, module: object, root: Optional[object] = None) -> str:
    """校验模块已在包 manifest 中声明（否则 NotFound），返回规范化模块名。"""
    pack_dir = _pack_dir(pack, root)
    manifest = _manifest(pack_dir)
    mod = _check_component(module, "模块名")
    if mod not in _declared_modules(manifest):
        raise NotFound(f"模块未在包 manifest 中声明：{mod}")
    return mod


def load_pack_modules(pack: object, root: Optional[object] = None) -> Tuple[Path, Dict[str, Any]]:
    """整包模块原始数据（写链路 + 校验的数据源；只读）。

    出参 (包目录, {模块名: parsed JSON})。只收 manifest 已声明且文件存在的模块；
    读盘经 mtime 缓存，写盘后 mtime 变化自动失效 → 保存后回读即最新。
    """
    pack_dir = _pack_dir(pack, root)
    manifest = _manifest(pack_dir)
    modules: Dict[str, Any] = {}
    for mod in _declared_modules(manifest):
        data = _read_json(pack_dir / f"{mod}.json")
        if data is not None:
            modules[mod] = data
    return pack_dir, modules


def entry_slot(pack: object, module: object, entry_id: object,
               root: Optional[object] = None) -> Dict[str, Any]:
    """定位条目在模块数据中的槽位（编辑链路用；只读）。

    出参含：pack_dir / manifest / module / entry_type / data（模块原数据）/
    slot（list=下标 int，map·object=键 str）/ subject（条目原值）/ base（字段元数据基表）。
    条目不存在 → NotFound；模块未声明 → NotFound；包非法 → BadRequest。
    """
    pack_dir = _pack_dir(pack, root)
    manifest = _manifest(pack_dir)
    declared = _declared_modules(manifest)
    mod = _check_component(module, "模块名")
    if mod not in declared:
        raise NotFound(f"模块未在包 manifest 中声明：{mod}")
    if not isinstance(entry_id, str):
        raise BadRequest(f"非法条目标识：{entry_id!r}")
    data = _read_json(pack_dir / f"{mod}.json")
    mmeta = _module_meta(mod)
    rows = _entry_rows(data, mmeta)
    pos = next((i for i, row in enumerate(rows) if row[0] == entry_id), None)
    if pos is None:
        raise NotFound(f"条目不存在：{mod}/{entry_id}")
    _eid, entry_name, subject = rows[pos]
    etype = mmeta.entry_type if mmeta is not None else _infer_entry_type(data)
    if isinstance(data, list):
        slot: object = pos
    elif isinstance(data, Mapping):
        slot = entry_id
    else:
        slot = None
    return {
        "pack_dir": pack_dir,
        "manifest": manifest,
        "declared": declared,
        "module": mod,
        "entry_type": etype,
        "data": data,
        "slot": slot,
        "entry_id": entry_id,
        "name": entry_name,
        "subject": subject,
        "base": _entry_base(mmeta, etype, entry_id, subject),
        "mmeta": mmeta,
    }


def ref_options(pack: object, target: object, root: Optional[object] = None,
                query: Optional[object] = None, limit: int = 500) -> Dict[str, Any]:
    """引用字段候选（`/api/pack/{pack}/refs/{target}`）：目标 kind → [{id, name}]。

    名称索引与只读视图同一构建逻辑（含命名空间合并、`_or_any` 后缀兼容）；
    未知 target 返回空候选 + known=false（前端据此提示「该引用目标暂无候选」）。
    排序按名称（同名前缀一致），可按 id/名称模糊过滤（query），超出 limit 截断并标注。
    """
    pack_dir = _pack_dir(pack, root)
    manifest = _manifest(pack_dir)
    tgt = str(target or "")
    index = _PackView(pack_dir, manifest).name_index()
    table = index.get(tgt)
    if table is None and tgt.endswith("_or_any"):
        table = index.get(tgt[: -len("_or_any")])
    if not table:
        return {"pack": str(pack), "target": tgt, "options": [], "total": 0,
                "truncated": False, "known": False}
    rows = [{"id": str(k), "name": str(v)} for k, v in table.items()]
    rows.sort(key=lambda r: (r["name"], r["id"]))
    q = str(query or "").strip().lower()
    if q:
        rows = [r for r in rows if q in r["id"].lower() or q in r["name"].lower()]
    total = len(rows)
    return {"pack": str(pack), "target": tgt, "options": rows[:limit],
            "total": total, "truncated": total > limit, "known": True}


__all__ = [
    "DEFAULT_GROUP",
    "EDIT_CONTROLS",
    "META_SOURCE",
    "BadRequest",
    "EditorError",
    "Forbidden",
    "NotFound",
    "content_root",
    "control_of",
    "declared_module",
    "editable_form",
    "entry_detail",
    "entry_slot",
    "field_meta_table",
    "is_editable_widget",
    "list_control",
    "list_entries",
    "list_modules",
    "list_packs",
    "load_pack_modules",
    "readonly_form",
    "ref_options",
    "repo_root",
]
