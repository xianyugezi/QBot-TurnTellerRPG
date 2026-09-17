"""只读元数据读取层：把「内容包元数据」翻译成编辑器可直接渲染的 JSON。

编辑器重写批1（docs/编辑器重写_实现方案.md §三）唯一实现点：

  · 模块列表        ← manifest.modules（包数据）
  · 模块显示名      ← manifest.module_labels / module_tree 节点的 label（缺省用模块键名）；
                       包内 field_meta.json 的 module_labels / module_tree 声明优先（批A）
  · 模块层级（父子）← manifest.module_tree（别名 module_groups）；**包不声明就平铺**；
                       包内 field_meta.json 若声明 module_tree 则以其为准
  · 字段清单        ← default_field_meta_table() 的 ModuleMeta.fields，经包内 field_meta.json
                       （field_labels / field_help / group_labels）合并（包声明优先，框架兜底）
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

import copy
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from qbot_rpg.content import entry_presets as entry_presets_mod
from qbot_rpg.content import field_meta_pack as pack_meta
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.web.framework_keys import framework_key_notes, framework_key_source
from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
from qbot_rpg.content.module_catalog import (
    FRAMEWORK_MODULE_CATALOG,
    MODULE_PANEL_HINT,
    ModuleCatalogEntry,
    catalog_entry,
)

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

# 批13.1「段入口」：对象型模块里「框架已登记、包数据尚无」的顶层段，在只读视图里用本
# 哨兵占位。它是**展示层与写链路之间的唯一信号**：读写两处据此把该段当「空槽位」处理
# （已有子字段登记 → 从空对象起建；否则整段一值），而绝不把哨兵本身写进任何数据文件。
# 用独立哨兵而非 None，是为了把「框架段未配置」与「包数据里真的写了 null」区分开。
_UNCONFIGURED = object()
# 批19 #4：map 形态模块「框架有全量键、包尚未覆盖」的条目哨兵（与 _UNCONFIGURED 同族，
# 语义不同：这是「键存在、值用框架默认」，不是「段未配置」）。读写两处把它当「空槽位」，
# 绝不把哨兵写进任何数据文件；保存时写入包覆盖（走既有校验/备份/原子写/回退）。
_FRAMEWORK_DEFAULT = object()
# 未配置段的界面文案（前端按需取；后端只给稳定标记 unconfigured）。
UNCONFIGURED_TAG = "未配置 · 框架支持"
# 批19 #4：框架默认键的界面文案（前端按需取；后端只给稳定标记 framework_default）。
FRAMEWORK_DEFAULT_TAG = "默认（框架）"
# 包已覆盖框架键的界面文案。
PACK_COVERED_TAG = "已覆盖（包）"
# 框架键没有人类可读名/说明时的兜底提示（提示作者「键即名字」）。
KEY_IS_NAME_NOTE = "键 = 名称"
# 批32 B1（框架 §6.12-06）：框架关键模板（框架键全集里包未覆盖的键）在编辑器**只读**——
# 不可直接改框架默认内容；须先「复制为包覆盖」生成包内覆盖条目，之后自由编辑覆盖。
FRAMEWORK_LOCK_NOTE = ("框架关键模板 · 只读：请点「复制为包覆盖」生成本包覆盖条目后再编辑；"
                       "复制后即可自由改动，框架默认内容保持干净。")
# 批14 #4：元数据未登记子字段的兜底标注（前端字段行内展示；不改任何校验语义）。
META_UNREGISTERED_NOTE = "元数据未登记，按实际值推断"
# 批20 C：中栏条目分组的「取不到分组值」兜底分组（稳定机器键 + 中文兜底显示名；包可覆盖名）。
ENTRY_GROUP_OTHER = "@other"
ENTRY_GROUP_OTHER_LABEL = "其他"

# 批15 #8：二级结构（分组页签之下的可折叠子块）——通用机制，不认任何模块/字段名。
# · 子块名来自元数据：FieldMeta.subgroup / ModuleMeta.field_subgroups（键 → 子块）；
# · 分组内既无子块声明、字段数又超过 AUTO_MORE_AFTER 时，按**元数据声明顺序**把超出部分
#   收进一个隐式的「更多字段」折叠块（规则只看 order/数量，**不硬编码字段名**）；
# · 子块默认折叠（主块展开）——首屏先给主要字段，次要/进阶字段点开再看。
AUTO_MORE_AFTER = 8               # 主块最多常驻展示的字段数（其余进「更多字段」折叠块）
AUTO_MORE_BLOCK = "@more"         # 隐式「更多字段」块的稳定机器键（不写进任何数据）
MORE_FIELDS_LABEL = "更多字段"     # 隐式块的中文兜底显示名（包可用 subgroup_labels 覆盖）

# 批15 #9：键值表格（kvtable）——「键 → 标量值/小结构」的密集映射用紧凑表格渲染
# （行内编辑 + 增删行 + 表头），而不是一行一个大块表单。通用判定只看值形态，不认字段名。
KV_KEY_LABEL = "键"
KV_VALUE_LABEL = "值"
KV_MAX_STRUCT_KEYS = 8            # 「小结构」的子键上限（超出视为宽容器，不走键值表格）
# 批20 A：键值表格的第三种行模式——值类型混杂（标量 / 数组 / 对象并存）时，**逐行按实际
# 类型出控件**（数字/布尔/文本/枚举/引用/数组/对象/嵌套映射），可递归任意层。判定只看值
# 形态与元数据，不认任何字段名；行描述符直接复用 `_descriptor`，与顶层字段同一套控件口径。
KV_MODE_TYPED = "typed"
# map 模块的「全表」合成条目标识（仅读列表/详情合成，不进数据、不进条目索引）。
TABLE_ENTRY_ID = "@table"
TABLE_ENTRY_TAG = "全表 · 表格"
# 批15 #2：对象模块「合并页」合成条目前缀（`@page:<包声明的页面 id>`；同样不进数据/索引）。
PAGE_PREFIX = "@page:"
# 批15 #2：曲线控件对「等级 → 数值」映射的约定键（与 id/name 同级的框架约定，不是业务字段名）：
#   use_formula = 启用/禁用公式（缺省 true = 保持现状；关掉则以明细表的显式值为准）；
#   formula     = 公式文本（可选；缺省时按明细推导摘要行）。
CURVE_FLAG_KEY = "use_formula"
CURVE_FORMULA_KEY = "formula"


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


@lru_cache(maxsize=2048)
def _read_json_cached(path_str: str, mtime_ns: int, size: int, ino: int) -> Optional[object]:
    try:
        with Path(path_str).open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:  # 坏 JSON 不炸宿主，转领域异常
        raise EditorError(f"读取/解析 JSON 失败：{path_str}（{exc}）") from exc


def _read_json(path: Path) -> Optional[object]:
    """读 JSON（文件不存在 → None；mtime/size/inode 变化自动失效缓存）。

    批6：缓存键补 `size` + `st_ino`——原子写（os.replace 新临时文件）在同一时间戳刻度内
    可能产生与上一版相同的 `st_mtime_ns`，仅按 mtime 作键会把「刚写的新内容」读成旧内容
    （删除后回退复核曾因此假阴性）。inode/size 一起进键后，同刻度重写不再串味。
    """
    try:
        st = path.stat()
    except OSError:
        return None
    return _read_json_cached(str(path), st.st_mtime_ns, st.st_size, st.st_ino)


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


# 包声明合并表缓存：键 = (field_meta.json 路径, mtime_ns, size, ino)（内容变化自动失效；
# 与 _read_json 同一失效口径——原子写换 inode 也能识别）。
_MERGED_TABLES: Dict[Tuple[str, int, int, int], FieldMetaTable] = {}


def _pack_declaration(pack_dir: Path) -> Optional[pack_meta.PackFieldMeta]:
    """读包展示元数据声明（无文件 → None；形态非法 → 人话 EditorError）。"""
    try:
        return pack_meta.load_field_meta(pack_dir)
    except pack_meta.PackFieldMetaError as exc:
        raise EditorError(str(exc)) from exc


def _pack_meta_table(pack_dir: Path) -> FieldMetaTable:
    """该包的字段元数据表：读包声明与框架表合并（包声明优先）；未声明 → 框架表单例。"""
    decl_path = pack_dir / pack_meta.FIELD_META_FILENAME
    try:
        st = decl_path.stat()
    except OSError:
        return field_meta_table()
    key = (str(decl_path), st.st_mtime_ns, st.st_size, st.st_ino)
    cached = _MERGED_TABLES.get(key)
    if cached is not None:
        return cached
    decl = _pack_declaration(pack_dir)
    if decl is None:
        return field_meta_table()
    table = pack_meta.merge_field_meta_table(field_meta_table(), decl)
    if len(_MERGED_TABLES) > 256:  # 只读进程内缓存，防长期运行累积（多包反复切换）
        _MERGED_TABLES.clear()
    _MERGED_TABLES[key] = table
    return table


def _module_meta(module: str, pack_dir: Optional[Path] = None) -> Optional[ModuleMeta]:
    """模块元数据：给了包目录 → 包声明合并表；否则框架表单例。"""
    table = _pack_meta_table(pack_dir) if pack_dir is not None else field_meta_table()
    return table.module(module)


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


# module_tree 取值哨兵：区分「调用方已给出有效声明」与「回落到 manifest」。
_TREE_UNSET = object()


def _declared_tree_spec(decl: Optional[pack_meta.PackFieldMeta]) -> object:
    """包声明里的 module_tree（未声明 → 哨兵，回落到 manifest 的 module_tree/module_groups）。"""
    if decl is not None and decl.module_tree is not None:
        return decl.module_tree
    return _TREE_UNSET


def _resolve_tree(
    manifest: Mapping[str, Any], declared: List[str], spec: object = _TREE_UNSET
) -> Tuple[Dict[str, List[str]], Dict[str, str], List[str]]:
    """读包的模块层级声明 → (children_map, node_labels, notes)。

    声明键 `module_tree`（别名 `module_groups`），节点形态三种：
      1) 字符串                 → 顶层模块（无子）
      2) {"module": p, "label": "...", "children": ["c", {...}]}
      3) {"p": ["c1", "c2"]}    映射形态（父: 子列表）
    非法/未声明/自环/重复引用一律忽略并记 note（包声明有瑕疵也不让编辑器崩）。
    `spec` 显式给出时以其为准（批A：包内 field_meta.json 的 module_tree 优先于 manifest）。
    """
    declared_set = set(declared)
    children: Dict[str, List[str]] = {}
    labels: Dict[str, str] = {}
    notes: List[str] = []
    seen_child: set = set()
    if spec is _TREE_UNSET:
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


def _display_labels(manifest: Mapping[str, Any], declared: List[str],
                    pack_dir: Optional[Path] = None) -> Dict[str, str]:
    """模块显示名（优先级：manifest → field_meta.json.module_labels → module_tree 节点 label）。"""
    decl = _pack_declaration(pack_dir) if pack_dir is not None else None
    labels = _module_labels(manifest)
    if decl is not None:
        labels.update(decl.module_labels)
    _children, tree_labels, _notes = _resolve_tree(manifest, declared, _declared_tree_spec(decl))
    labels.update(tree_labels)
    return labels


def _module_display_label(module: str, labels: Mapping[str, str]) -> str:
    """模块显示名的**统一回落链**（批19 #6）：包声明 → 框架目录 label → 模块键。

    包声明的 `module_labels` / `manifest.module_labels` / `module_tree` 节点 label 优先；
    包未声明时**不再回落到英文模块键**，而是回落到框架目录 `module_catalog` 的中文默认名
    （一号原则：框架支持的能力，启用后也要有中文名）。目录也没有该模块（包自定义模块）→
    才回落到模块键。纯展示层，不参与校验。
    """
    declared = labels.get(module)
    if declared:
        return declared
    ce = catalog_entry(module)
    if ce is not None and ce.label:
        return ce.label
    return module or ""


# =====================================================================================
# 批12 #1：条目聚合展示声明（`field_meta.json.entry_merge`，通用、包声明驱动）
# =====================================================================================
def _entry_merge_map(
    manifest: Mapping[str, Any], declared: List[str], pack_dir: Path
) -> Tuple[Dict[str, Dict[str, Tuple[str, ...]]], List[str]]:
    """读包声明 `entry_merge` → (聚合表, notes)；不写死任何模块名。

    出参 `{目标模块: {"sources": (...), "keep_top_level": (...)}}`，只保留：
      · 目标与来源都在本包 manifest 声明；（未声明 → note，忽略）
      · 来源不重复并入多个目标（首个声明生效，其余 note）；
      · 目标自身不再作为来源被并入别的目标（防链式/环）。
    **数据文件 / 模块 id / 加载与校验路径全部不动**——本表只驱动展示层聚合。
    """
    decl = _pack_declaration(pack_dir)
    notes: List[str] = []
    out: Dict[str, Dict[str, Tuple[str, ...]]] = {}
    if decl is None or not decl.entry_merge:
        return out, notes
    declared_set = set(declared)
    claimed: Dict[str, str] = {}
    for target, spec in decl.entry_merge.items():
        if target not in declared_set:
            # 批13 D：目标未在 manifest 声明 → 按「虚拟聚合视图」处理（如「生活」把
            # proficiency/enhance/forge/recipe 聚到一个视图节点）。视图不落数据文件、
            # 不参与写入；来源仍必须真实声明（下面逐个过滤）。记 note 让作者知情。
            notes.append(f"entry_merge 目标为虚拟聚合视图（未在 manifest 声明）：{target}")
        srcs: List[str] = []
        for src in spec.get("sources", ()):  # 解析层已归一为元组
            if src not in declared_set:
                notes.append(f"entry_merge 来源模块未在 manifest 声明：{src}")
                continue
            if src == target:
                notes.append(f"entry_merge 忽略把 {src} 并入自身")
                continue
            if src in claimed:
                notes.append(
                    f"entry_merge 来源模块 {src} 已并入 {claimed[src]}（忽略重复声明：{target}）")
                continue
            claimed[src] = target
            srcs.append(src)
        if not srcs:
            continue
        keep = tuple(m for m in spec.get("keep_top_level", ()) if m in srcs)
        out[target] = {"sources": tuple(srcs), "keep_top_level": keep}
    # 目标自身又被并入了别的模块 → 忽略该目标声明（防链式聚合 / 环）
    for target in list(out):
        if target in claimed:
            notes.append(
                f"entry_merge 目标模块 {target} 同时被并入 {claimed[target]}（忽略其目标声明）")
            for src in out[target]["sources"]:
                if claimed.get(src) == target:
                    claimed.pop(src, None)
            out.pop(target)
    return out, notes


# =====================================================================================
# 批19 #8：条目级层级挂载（`field_meta.json.entry_tree`，通用、包声明驱动）
# =====================================================================================
def _entry_tree_map(manifest: Mapping[str, Any], declared: List[str], pack_dir: Path,
                    merge_map: Mapping[str, Any],
                    ) -> Tuple[List[Dict[str, Any]], List[str]]:
    """读包声明 `entry_tree` → (挂载表, notes)；不写死任何模块名/条目名。

    父节点 = 本包 manifest 声明的模块，或 entry_merge 的虚拟聚合视图（如「生活」）——二者
    都允许，其它一律忽略并记 note。来源模块必须在 manifest 声明；条目 id 必须在来源模块的
    「条目全集」（`_entry_rows`：包数据 ∪ 框架登记）内，否则忽略（不悬空）。
    同一条目只能挂到一处（首个声明生效，其余 note）。

    `keep_top_level`：默认 False = **移走**（来源模块的条目列表不再列出，计数/检索改归父节点）；
    True 或父节点是虚拟视图 = **保留原位**（纯显示挂载，计数/检索仍在来源模块）。
    """
    decl = _pack_declaration(pack_dir)
    notes: List[str] = []
    if decl is None or not decl.entry_tree:
        return [], notes
    declared_set = set(declared)
    views = set(merge_map)
    claimed: set = set()
    out: List[Dict[str, Any]] = []
    for mount in decl.entry_tree:
        parent = str(mount["parent"])
        if parent not in declared_set and parent not in views:
            notes.append(f"entry_tree 父节点未声明（忽略）：{parent}")
            continue
        parent_is_view = parent not in declared_set
        sections: List[Dict[str, str]] = []
        for sec in mount["sections"]:
            frm = str(sec["from"])
            eid = str(sec["id"])
            if frm not in declared_set:
                notes.append(f"entry_tree 来源模块未在 manifest 声明：{frm}")
                continue
            fm = frm
            rows = _entry_rows(_read_json(pack_dir / f"{fm}.json"), _module_meta(fm, pack_dir))
            if eid not in {r[0] for r in rows}:
                notes.append(f"entry_tree 条目不存在（忽略）：{frm}.{eid}")
                continue
            if (frm, eid) in claimed:
                notes.append(f"entry_tree 重复挂载（忽略）：{frm}.{eid}")
                continue
            claimed.add((frm, eid))
            sections.append({"from": frm, "id": eid})
        if not sections:
            continue
        keep = bool(mount.get("keep_top_level")) or parent_is_view
        out.append({"parent": parent, "sections": tuple(sections),
                    "keep_top_level": keep, "parent_is_view": parent_is_view})
    return out, notes


def _entry_tree_plan(manifest: Mapping[str, Any], declared: List[str], pack_dir: Path,
                     merge_map: Mapping[str, Any], labels: Mapping[str, str],
                     ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]],
                                Dict[str, set], List[str]]:
    """`entry_tree` 挂载计划 → (mounts, mounted{父: [条目行]}, moved_out{来源: {id}}, notes)。

    `mounted` 每行 = `{from, id, name, source_label, keep_top_level}`（供左栏/中栏展示）；
    `moved_out` 只含「移走」类（keep_top_level=False）的来源条目——计数/检索据此改归父节点。
    """
    mounts, notes = _entry_tree_map(manifest, declared, pack_dir, merge_map)
    mounted: Dict[str, List[Dict[str, Any]]] = {}
    moved_out: Dict[str, set] = {}
    for mount in mounts:
        for sec in mount["sections"]:
            frm = str(sec["from"])
            eid = str(sec["id"])
            rows = _entry_rows(_read_json(pack_dir / f"{frm}.json"), _module_meta(frm, pack_dir))
            name = next((r[1] for r in rows if r[0] == eid), eid)
            mounted.setdefault(str(mount["parent"]), []).append({
                "from": frm,
                "id": eid,
                "name": name,
                "source_label": _module_display_label(frm, labels),
                "keep_top_level": bool(mount["keep_top_level"]),
            })
            if not mount["keep_top_level"]:
                moved_out.setdefault(frm, set()).add(eid)
    return mounts, mounted, moved_out, notes


# =====================================================================================
# 批20 B：**按条件过滤的条目并入**（`field_meta.json.entry_merge_filtered`，通用、包声明驱动）
# =====================================================================================
def _entry_merge_filtered_specs(
    manifest: Mapping[str, Any], declared: List[str], pack_dir: Path
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """读包声明 `entry_merge_filtered` → (并入表, notes)；不写死任何模块名 / 键名。

    每项 = `{"target": 目标模块, "from": 来源模块, "has": (键, …), "eq": {键: 值}}`。
    只保留「目标与来源都在本包 manifest 声明」的项（否则记 note 忽略）；目标与来源相同者
    由解析层拦下。**数据文件 / 条目 id / 校验路径全不动**——本表只驱动展示层聚合。
    """
    decl = _pack_declaration(pack_dir)
    notes: List[str] = []
    out: List[Dict[str, Any]] = []
    if decl is None or not decl.entry_merge_filtered:
        return out, notes
    declared_set = set(declared)
    for spec in decl.entry_merge_filtered:
        target = str(spec["target"])
        frm = str(spec["from"])
        if target not in declared_set:
            notes.append(f"entry_merge_filtered 目标模块未在 manifest 声明：{target}")
            continue
        if frm not in declared_set:
            notes.append(f"entry_merge_filtered 来源模块未在 manifest 声明：{frm}")
            continue
        out.append({"target": target, "from": frm,
                    "has": tuple(spec.get("has", ())),
                    "eq": dict(spec.get("eq", {}))})
    return out, notes


def _entry_matches_where(value: object, has: Sequence[str],
                         eq: Mapping[str, Any]) -> bool:
    """条目是否满足并入条件（`has` 全中 AND `eq` 全等）——只看值形态，不认字段语义。

    `has`：键存在且值不为 null（空串 / 空列表算「有」——声明口径就是「有某键」）；
    `eq`：键的值与声明值相等（标量比较；类型不同即不等）。
    """
    if not isinstance(value, Mapping):
        return False
    for k in has:
        if str(k) not in value or value[str(k)] is None:
            return False
    for k, want in eq.items():
        if str(k) not in value or value[str(k)] != want:
            return False
    return True


def _entry_merge_filtered_rows(
    pack_dir: Path, declared: List[str], labels: Mapping[str, str],
    target: str, specs: Sequence[Mapping[str, Any]],
) -> Tuple[List[Tuple[str, str, object, str, Mapping[str, Any]]], List[Dict[str, Any]]]:
    """目标模块的「过滤并入」条目 → ((id, 名称, 值, 来源模块, spec), 小节元数据)。

    同一个来源模块可能有多条声明（不同条件）→ 各自成小节；同一条目被多条声明命中时**只取首个**
    （不重复列出，也不重复计数）。
    """
    rows: List[Tuple[str, str, object, str, Mapping[str, Any]]] = []
    sections: List[Dict[str, Any]] = []
    seen: set = set()
    for spec in specs:
        if str(spec["target"]) != target:
            continue
        frm = str(spec["from"])
        sdata = _read_json(pack_dir / f"{frm}.json")
        smeta = _module_meta(frm, pack_dir)
        hits: List[Tuple[str, str, object]] = []
        for eid, name, val in _entry_rows(sdata, smeta):
            if eid in seen:
                continue
            if _entry_matches_where(val, spec["has"], spec["eq"]):
                seen.add(eid)
                hits.append((eid, name, val))
                rows.append((eid, name, val, frm, spec))
        sections.append({
            "module": frm,
            "label": _module_display_label(frm, labels),
            "has": list(spec["has"]),
            "eq": dict(spec["eq"]),
            "count": len(hits),
        })
    return rows, sections


# =====================================================================================
# 批20 C：**中栏条目分组**（`field_meta.json.entry_groups`，通用、包声明驱动）
# =====================================================================================
def _entry_group_spec(pack_dir: Path, module: str) -> Optional[Mapping[str, Any]]:
    """读该模块的条目分组声明（无声明 → None = 行为与现状一致）。"""
    decl = _pack_declaration(pack_dir)
    if decl is None or not decl.entry_groups:
        return None
    return decl.entry_groups.get(module)


def _entry_group_of(entry_id: str, value: object, spec: Mapping[str, Any]) -> str:
    """条目 → 分组原始键：`by=id_prefix` 取 ID 首个下划线前缀；`by=field` 取该字段的标量值。

    只看值形态 / 声明，不认任何具体字段语义；取不到（缺键 / 非标量 / 空值）→ 空串（其他）。
    """
    if str(spec.get("by")) == "id_prefix":
        raw = str(entry_id).split("_")[0]
        return raw or str(entry_id)
    key = str(spec.get("field") or "")
    if key and isinstance(value, Mapping):
        v = value.get(key)
        if isinstance(v, (str, int, float, bool)) and str(v) != "":
            return str(v)
    return ""


def _entry_group_plan(mrows: Sequence[Tuple[str, str, object]],
                      spec: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """条目行 → 分组计划 `[{name,label,count,collapsed}]`（顺序 = 首次出现顺序，「其他」置末）。

    首节默认展开，其余按声明 `collapsed`（缺省 true）折叠；显示名 = 包声明 labels →
    原始值；取不到值的条目归「其他」（`ENTRY_GROUP_OTHER`）。
    """
    labels = {str(k): str(v) for k, v in (spec.get("labels") or {}).items()}
    other_label = str(spec.get("other_label") or ENTRY_GROUP_OTHER_LABEL)
    collapsed = bool(spec.get("collapsed", True))
    order: List[str] = []
    counts: Dict[str, int] = {}
    for eid, _name, val in mrows:
        raw = _entry_group_of(str(eid), val, spec)
        if raw and raw not in counts:
            order.append(raw)
        counts[raw] = counts.get(raw, 0) + 1
    # 包声明 labels 的**键顺序优先**（作者可用它排定小节顺序）；未声明 labels 时按
    # **条目数降序**（首屏先给最大的分组），同数按首次出现顺序。
    declared_order = [k for k in labels if counts.get(k, 0) > 0]
    if declared_order:
        order = declared_order + [k for k in order if k not in set(declared_order)]
    else:
        order = sorted(order, key=lambda k: -counts.get(k, 0))
    if "" in counts:
        order.append("")
    plan: List[Dict[str, Any]] = []
    for i, raw in enumerate(order):
        if counts.get(raw, 0) <= 0:
            continue
        name = raw or ENTRY_GROUP_OTHER
        plan.append({
            "name": name,
            "label": labels.get(raw) or (other_label if not raw else raw),
            "count": counts.get(raw, 0),
            "collapsed": bool(collapsed and i > 0),
        })
    return plan


def _segment_pages(manifest: Mapping[str, Any], declared: List[str],
                   pack_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
    """读包声明 `segment_pages` → {对象模块: 页面数组}（批15 #2，通用、不写死段名）。

    出参每页 = `{id, label, help, segments}`（segments 已过滤为「框架登记段 ∪ 包数据键」，
    保证声明写错/段不存在时不产生悬空页面）。**纯展示层**：数据文件/段 id/校验路径不动。
    """
    decl = _pack_declaration(pack_dir)
    out: Dict[str, List[Dict[str, Any]]] = {}
    if decl is None or not decl.segment_pages:
        return out
    for mod, pages in decl.segment_pages.items():
        if mod not in declared:
            continue
        mmeta = _module_meta(mod, pack_dir)
        if mmeta is None or mmeta.entry_type != "object":
            continue
        data = _read_json(pack_dir / f"{mod}.json")
        present = set(data) if isinstance(data, Mapping) else set()
        known = set(mmeta.fields)
        norm: List[Dict[str, Any]] = []
        for page in pages:
            segs = [str(s) for s in page["segments"] if str(s) in known or str(s) in present]
            if not segs:
                continue
            norm.append({"id": str(page["id"]), "label": str(page["label"]),
                         "help": str(page.get("help") or ""), "segments": tuple(segs)})
        if norm:
            out[mod] = norm
    return out


def _find_page(pack_dir: Path, manifest: Mapping[str, Any], declared: List[str],
               mod: str, entry_id: str) -> Optional[Dict[str, Any]]:
    """`@page:<id>` → 页面声明（找不到 → None）。"""
    if not entry_id.startswith(PAGE_PREFIX):
        return None
    pid = entry_id[len(PAGE_PREFIX):]
    for page in _segment_pages(manifest, declared, pack_dir).get(mod, []):
        if page["id"] == pid:
            return page
    return None


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
def _entry_count(data: object, mmeta: Optional[ModuleMeta] = None) -> int:
    """条目计数（与 `_entry_rows` **同一口径**：对象型模块含框架已登记的未配置段）。

    与条目列表 / 全局索引共用同一函数，保证「左栏计数 = 条目列表 count = 全局检索」三处自洽。
    """
    return len(_entry_rows(data, mmeta))


def _module_in_use(data: object) -> bool:
    """模块在当前包是否「已使用」（有实际数据）。批19 #5：空 list / 空 dict / 缺文件 → 未使用。"""
    return bool(data)


def _module_overlap_hints(module: str, pack_dir: Path) -> List[Dict[str, Any]]:
    """模块的功能重叠黄提示（批19 #5，通用：声明来自 `module_catalog` 目录）。

    目录条目声明 `overlap_with`（另一处落点，形如 `模块.段.子键`）时不硬拦，只提示
    「建议归口一处」+ `overlap_note`（各自定位，如实核查）；并如实给出另一处是否已有数据。
    """
    ce = catalog_entry(module)
    if ce is None or not ce.overlap_with:
        return []
    parts = [p for p in str(ce.overlap_with).split(".") if p]
    present = False
    if parts:
        other: object = _read_json(pack_dir / f"{parts[0]}.json")
        for seg in parts[1:]:
            other = other.get(seg) if isinstance(other, Mapping) else None
        present = bool(other)
    return [{
        "level": "yellow",
        "code": "module_overlap",
        "module": module,
        "target": str(ce.overlap_with),
        "target_present": present,
        "message": str(ce.overlap_note or
                       f"该模块与「{ce.overlap_with}」功能重叠，建议归口一处。"),
    }]


def list_modules(pack: object, root: Optional[object] = None) -> Dict[str, Any]:
    """模块分类树（`/api/pack/{pack}/modules`）。

    返回项：{module, label, count(含后代合计), own_count, children[]}。
    `flat=True` 表示包未声明任何层级（平铺）。
    """
    pack_dir = _pack_dir(pack, root)
    manifest = _manifest(pack_dir)
    declared = _declared_modules(manifest)
    decl = _pack_declaration(pack_dir)
    children_map, tree_labels, notes = _resolve_tree(manifest, declared, _declared_tree_spec(decl))
    labels = _module_labels(manifest)
    if decl is not None:
        labels.update(decl.module_labels)
    labels.update(tree_labels)
    # 批13.1：计数与条目列表同一口径（对象型模块的未配置段计入 own_count），
    # 供验收脚本断言「左栏计数 = 条目列表 = 全局索引」。
    meta_table = _pack_meta_table(pack_dir)
    datas = {m: _read_json(pack_dir / f"{m}.json") for m in declared}
    counts = {m: _entry_count(datas[m], meta_table.module(m)) for m in declared}
    child_set = {c for kids in children_map.values() for c in kids}
    merge_map, merge_notes = _entry_merge_map(manifest, declared, pack_dir)
    notes.extend(merge_notes)
    # 批19 #8：条目级层级挂载——「移走」类条目从来源模块计数改归父节点（与条目列表/索引
    # 同一口径）；父节点是虚拟视图或声明 keep_top_level 的走纯显示挂载（计数不动）。
    _tree_mounts, tree_mounted, tree_moved_out, tree_notes = _entry_tree_plan(
        manifest, declared, pack_dir, merge_map, labels)
    notes.extend(tree_notes)
    for _src, _ids in tree_moved_out.items():
        counts[_src] = max(0, counts.get(_src, 0) - len(_ids))
    for _parent, _items in tree_mounted.items():
        _moved_in = [x for x in _items if not x["keep_top_level"]]
        if _moved_in and _parent in counts:
            counts[_parent] = counts.get(_parent, 0) + len(_moved_in)
    # 批20 B：按条件过滤的并入 → 目标模块计数（与条目列表 / 全局索引同一口径）。
    mf_specs, mf_notes = _entry_merge_filtered_specs(manifest, declared, pack_dir)
    notes.extend(mf_notes)
    mf_specs_by_target: Dict[str, List[Dict[str, Any]]] = {}
    for _spec in mf_specs:
        mf_specs_by_target.setdefault(str(_spec["target"]), []).append(_spec)
    mf_sections_by_target: Dict[str, List[Dict[str, Any]]] = {}
    for _target, _specs in mf_specs_by_target.items():
        _mf_rows, _mf_secs = _entry_merge_filtered_rows(
            pack_dir, declared, labels, _target, _specs)
        counts[_target] = counts.get(_target, 0) + len(_mf_rows)
        mf_sections_by_target[_target] = _mf_secs
    # 被并入的来源模块：标记 merged_into（前端默认不在左栏单列）；keep_top_level 的仍单列。
    merged_into: Dict[str, str] = {}
    merged_sources: Dict[str, List[Tuple[str, bool]]] = {}
    keep_sources: set = set()
    for target, spec in merge_map.items():
        for src in spec["sources"]:
            merged_into[src] = target
            keep = src in spec["keep_top_level"]
            if keep:
                keep_sources.add(src)
            merged_sources.setdefault(target, []).append((src, keep))

    def in_subtree(root: str, node_: str, stack: List[str]) -> bool:
        for kid in children_map.get(root, []):
            if kid == node_:
                return True
            if kid not in stack and in_subtree(kid, node_, stack + [kid]):
                return True
        return False

    def agg(mod: str, stack: List[str]) -> int:
        """含后代合计（verify 口径：count = own + Σ子 count）。"""
        return counts.get(mod, 0) + sum(
            agg(c, stack + [c]) for c in children_map.get(mod, []) if c not in stack)

    def node(mod: str, stack: List[str]) -> Dict[str, Any]:
        kids = [node(c, stack + [c]) for c in children_map.get(mod, []) if c not in stack]
        own = counts.get(mod, 0)
        count = agg(mod, [mod])
        info: List[Dict[str, Any]] = []
        for src, keep in merged_sources.get(mod, []):
            already = in_subtree(mod, src, [mod])
            info.append({
                "module": src,
                "label": _module_display_label(src, labels),
                "count": agg(src, [src]),
                "keep_top_level": keep,
                "already_child": already,
            })
        merged_count = sum(x["count"] for x in info)
        # 左栏/中栏统一口径：total_count = 本模块 + 子模块 + 并入条目（已是子模块的不重复计）。
        total_count = count + sum(x["count"] for x in info if not x["already_child"])
        mf_secs = mf_sections_by_target.get(mod, [])
        mf_count = sum(int(s.get("count") or 0) for s in mf_secs)
        return {
            "module": mod,
            "label": _module_display_label(mod, labels),
            "count": count,
            "own_count": own,
            "children": kids,
            # 批13 A：已启用/声明模块带 enabled=True（未启用候选在 `available` 里 enabled=False）。
            "enabled": True,
            # 批19 #5：用途一句话 + 「当前包未使用」态（目录知识；无目录条目 → 空/False）。
            "purpose": (catalog_entry(mod).purpose if catalog_entry(mod) is not None else ""),
            "unused": not _module_in_use(datas.get(mod)),
            # 批12 #1：聚合展示声明（通用；未声明 entry_merge 的包这些字段为空/0，行为与现状一致）
            "merged": info,
            "merged_count": merged_count,
            # 批20 B：按条件过滤的并入（无声明 → 空列表 / 0）；**条目已计入 `count`**，
            # 不再叠加到 `total_count`（避免双计）。
            "merge_filtered": mf_secs,
            "merge_filtered_count": mf_count,
            "total_count": total_count,
            "merged_into": merged_into.get(mod),
            "keep_top_level": (mod in merged_into) and (mod in keep_sources),
            # 批19 #8：挂到本节点下的条目（左栏条目级叶子）；moved_out_ids = 本模块被移走的段。
            "mounted": list(tree_mounted.get(mod, [])),
            "mounted_count": sum(1 for x in tree_mounted.get(mod, [])
                                 if not x["keep_top_level"]),
            "moved_out_ids": sorted(tree_moved_out.get(mod, set())),
        }

    modules = [node(m, [m]) for m in declared if m not in child_set]
    declared_set_all = set(declared)

    # 批13 A（一号原则）：左栏显示集 = 框架能力集 ∪ 包声明。
    #   ① views     = entry_merge 声明的虚拟聚合视图（如「生活」；非 manifest 模块，无数据文件）；
    #   ② available = 框架目录里包尚未启用的模块（「未启用」态；条目数取真实数据文件，
    #                 无文件 = 0；引擎未实装的条目带 implemented=False → 前端标「未实现」）。
    # 二者都只驱动展示，不参与写入 / 校验，也不进 `modules` / 包列表 `module_count`；
    # 检索覆盖另由 `entry_index.available` 提供（不改该接口的 modules / total 口径）。
    def view_node(target: str, spec: Dict[str, Any]) -> Dict[str, Any]:
        info: List[Dict[str, Any]] = []
        for src in spec["sources"]:
            info.append({
                "module": src,
                "label": _module_display_label(src, labels),
                "count": agg(src, [src]),
                "keep_top_level": src in spec["keep_top_level"],
                "already_child": in_subtree(target, src, [target]),
            })
        merged_count = sum(x["count"] for x in info)
        total_count = sum(x["count"] for x in info if not x["already_child"])
        return {
            "module": target,
            "label": _module_display_label(target, labels),
            "count": 0,
            "own_count": 0,
            "children": [],
            "merged": info,
            "merged_count": merged_count,
            "total_count": total_count,
            "merged_into": None,
            "keep_top_level": False,
            "view": True,
            "enabled": True,
            # 批19 #8：挂到本视图下的条目（纯显示挂载，计数仍在来源模块）。
            "mounted": list(tree_mounted.get(target, [])),
            "mounted_count": 0,
            "moved_out_ids": [],
        }

    views = [view_node(t, spec) for t, spec in merge_map.items()
             if t not in declared_set_all]

    view_keys = {v["module"] for v in views}
    top_level_keys = {m["module"] for m in modules}
    available: List[Dict[str, Any]] = []
    for entry in FRAMEWORK_MODULE_CATALOG:
        mod = entry.module
        if mod in declared or mod in view_keys or mod in top_level_keys:
            continue
        data = _read_json(pack_dir / f"{mod}.json")
        cnt = _entry_count(data, meta_table.module(mod))
        available.append({
            "module": mod,
            "label": labels.get(mod) or entry.label,
            "purpose": entry.purpose,
            "entry_type": _entry_type_for_module(pack_dir, mod),
            "enabled": False,
            "in_catalog": True,
            "implemented": bool(entry.implemented),
            "settings_section": entry.settings_section,
            "requires": list(entry.requires),
            "requires_labels": [labels.get(r) or (
                catalog_entry(r).label if catalog_entry(r) is not None else r)
                for r in entry.requires],
            "missing_requires": [r for r in entry.requires if r not in declared],
            "count": cnt,
            "own_count": cnt,
            "children": [],
            "merged": [],
            "merged_count": 0,
            "total_count": cnt,
            "merged_into": None,
            "keep_top_level": False,
            "available": True,
        })

    return {
        "pack": str(pack),
        "pack_name": str(manifest.get("name", "") or pack),
        "modules": modules,
        "views": views,
        "available": available,
        "available_count": len(available),
        "flat": not children_map,
        "notes": notes,
    }


# =====================================================================================
# 只读 API ③：模块条目列表（id + 名称，只名字）
# =====================================================================================
def _key_source_of(mmeta: Optional[ModuleMeta]) -> str:
    """模块声明的框架侧键全集来源名（未声明 → 空串）。"""
    return str(mmeta.key_source) if mmeta is not None and mmeta.key_source else ""


def _framework_keys_of(mmeta: Optional[ModuleMeta]) -> Mapping[str, Any]:
    """模块的框架键全集（无声明 / 未注册 / 提供器异常 → 空表）。"""
    return framework_key_source(_key_source_of(mmeta))


def _entry_rows(data: object, mmeta: Optional[ModuleMeta]) -> List[Tuple[str, str, object]]:
    """条目三元组 (id, 名称, 原始值)。

    list 模块 → 每个元素一条；map 模块 → 每个键一条；object 模块 → 每个顶层段一条
    （名取字段元数据 label，缺省用键名）。无 id 的元素回退 `#i`（不因缺键丢条目）。

    批13.1「段入口」（一号原则）：object 模块的**框架已登记顶层段**里，包数据尚未出现的
    也补一条（值 = `_UNCONFIGURED` 哨兵）——段不因包缺数据而从编辑器消失。本函数是
    条目列表 / 全局索引 / 左栏计数 / 条目详情 / 写链路**共用**的唯一条目口径，故四处自洽。
    机制完全不认模块名/段名：任何 object 模块只要登记了顶层字段即享有。

    批19 #4「框架键全集」（一号原则续）：map 模块声明了框架侧键全集来源（`key_source`）时，
    **包数据键 ∪ 来源键**都要在列——包数据已有的标「已覆盖（包）」，来源里包没有的补一条
    （值 = `_FRAMEWORK_DEFAULT` 哨兵）标「默认（框架）」、可直接编辑后写入包覆盖。
    来源名/键名都不写死：来源来自模块元数据，键来自 `framework_keys` 注册表。
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
        # 批13.1：补齐框架已登记、包数据尚无的顶层段（顺序 = 字段登记顺序；配置过的在前）。
        if etype == "object" and mmeta is not None:
            present = {str(k) for k in data}
            for key, fm in mmeta.fields.items():
                k = str(key)
                if k in present:
                    continue
                name = fm.label if fm is not None and fm.label else k
                out.append((k, name, _UNCONFIGURED))
        # 批19 #4：补齐框架键全集里包数据尚未覆盖的键（键 = 名称；说明由详情给）。
        if etype == "map" and mmeta is not None:
            present = {str(k) for k in data}
            for key in _framework_keys_of(mmeta):
                k = str(key)
                if k in present:
                    continue
                out.append((k, k, _FRAMEWORK_DEFAULT))
    return out


def _entry_brief(eid: str, name: str, val: object) -> Dict[str, Any]:
    """条目列表项 {id, name}；未配置段额外带 `unconfigured=True`（其余条目键集不变）。

    批19 #4：框架键全集里「包未覆盖」的键额外带 `framework_default=True`（展示层标记）。
    """
    out: Dict[str, Any] = {"id": eid, "name": name}
    if val is _UNCONFIGURED:
        out["unconfigured"] = True
    if val is _FRAMEWORK_DEFAULT:
        out["framework_default"] = True
    return out


def list_entries(pack: object, module: object, root: Optional[object] = None) -> Dict[str, Any]:
    """当前模块的条目列表（`/api/pack/{pack}/module/{mod}/entries`；只 id + 名称）。"""
    pack_dir = _pack_dir(pack, root)
    manifest = _manifest(pack_dir)
    declared = _declared_modules(manifest)
    mod = _check_component(module, "模块名")
    # 批13 A/D：模块声明的**虚拟聚合视图**（entry_merge 目标但未在 manifest 声明，如「生活」）
    # 也允许读取（只读展示；写入仍走 api.declared_module → 严格按 manifest）。
    merge_map, _merge_notes = _entry_merge_map(manifest, declared, pack_dir)
    if mod not in declared and mod not in merge_map:
        raise NotFound(f"模块未在包 manifest 中声明：{mod}")
    data = _read_json(pack_dir / f"{mod}.json")
    mmeta = _module_meta(mod, pack_dir)
    rows = _entry_rows(data, mmeta)
    etype = _entry_type(mmeta, data)
    labels = _display_labels(manifest, declared, pack_dir)
    # 批19 #8：条目级层级挂载——「移走」类条目从本模块条目列表移除（计数/检索改归父节点）；
    # 「显示挂载」类（keep_top_level / 父节点是虚拟视图）保留原位。编辑仍按来源模块路由。
    _tree_mounts, tree_mounted, tree_moved_out, _tree_notes = _entry_tree_plan(
        manifest, declared, pack_dir, merge_map, labels)
    rows = [r for r in rows if r[0] not in tree_moved_out.get(mod, set())]
    mounted_here = tree_mounted.get(mod, [])
    mounted_move = [x for x in mounted_here if not x["keep_top_level"]]
    mounted_display = [x for x in mounted_here if x["keep_top_level"]]
    mounted_rows: List[Tuple[str, str, object, str]] = []
    for item in mounted_move:
        _frm, _eid = str(item["from"]), str(item["id"])
        _srows = _entry_rows(_read_json(pack_dir / f"{_frm}.json"),
                             _module_meta(_frm, pack_dir))
        _hit = next((r for r in _srows if r[0] == _eid), None)
        if _hit is not None:
            mounted_rows.append((_hit[0], _hit[1], _hit[2], _frm))
    # 批12 #1：若本模块声明为「聚合目标」，把来源模块的条目按来源分小节一并返回（只读；
    # 编辑/保存仍由前端按 section.module 路由回各自模块，数据文件与校验路径不变）。
    spec = merge_map.get(mod)
    sections: List[Dict[str, Any]] = []
    if spec:
        for src in spec["sources"]:
            sdata = _read_json(pack_dir / f"{src}.json")
            smeta = _module_meta(src, pack_dir)
            srows = _entry_rows(sdata, smeta)
            sections.append({
                "module": src,
                "label": _module_display_label(src, labels),
                "entry_type": _entry_type(smeta, sdata),
                "count": len(srows),
                "keep_top_level": src in spec["keep_top_level"],
                "entries": [_entry_brief(eid, name, _v) for eid, name, _v in srows],
            })
    merged_count = sum(s["count"] for s in sections)
    # 批13.1：计数口径（与条目列表 / 左栏 / 全局索引一致）——
    #   count = 全部条目（含未配置段）；configured_count = 包数据里真有的；
    #   unconfigured_count = 框架已登记但本包未配置的段。
    unconfigured_count = (sum(1 for _e, _n, val in rows if val is _UNCONFIGURED)
                          + sum(1 for _e, _n, val, _f in mounted_rows
                                if val is _UNCONFIGURED))
    # 批19 #4：框架键全集的覆盖口径——covered_count = 包数据已覆盖的框架键；
    # framework_default_count = 框架有、包未覆盖（可直接编辑后写入包覆盖）的键。
    key_source = _key_source_of(mmeta)
    framework_keys = set(_framework_keys_of(mmeta))
    framework_default_count = sum(1 for _e, _n, val in rows if val is _FRAMEWORK_DEFAULT)
    covered_count = sum(
        1 for eid, _n, val in rows
        if val is not _UNCONFIGURED and val is not _FRAMEWORK_DEFAULT and eid in framework_keys)
    # 批15 #9：map 模块（键 → 值）另给一个「全表」合成入口（只读展示，不进计数/索引）——
    # 一把看全 / 编辑整张「键 → 标量/小结构」表，而不是逐个键点开表单。
    table_entry = None
    if etype == "map":
        table_entry = {"id": TABLE_ENTRY_ID,
                       "name": f"{_module_display_label(mod, labels)} · {TABLE_ENTRY_TAG}",
                       "table": True}
    # 批15 #2：包声明的「合并页」——对象模块的若干段合成一个页面（中栏一条、右栏同栏多子块）。
    # 页面是展示层聚合：段条目仍在 `entries` 里（计数/索引不变），前端按 `page` 归到页行下。
    pages: List[Dict[str, Any]] = []
    briefs = [_entry_brief(eid, name, _val) for eid, name, _val in rows]
    # 批20 C：中栏条目分组（包声明驱动；本模块**自身条目**分组，并入/挂载条目另按来源分节）。
    # 无声明 → 空计划 / 条目不带 group 键（前端行为与现状一致）。
    group_spec = _entry_group_spec(pack_dir, mod)
    group_plan: List[Dict[str, Any]] = []
    if group_spec is not None:
        group_plan = _entry_group_plan(rows, group_spec)
        _glabel = {str(g["name"]): str(g["label"]) for g in group_plan}
        for _i, (_eid, _nm, _val) in enumerate(rows):
            _gname = _entry_group_of(str(_eid), _val, group_spec) or ENTRY_GROUP_OTHER
            briefs[_i]["group"] = _gname
            briefs[_i]["group_label"] = _glabel.get(_gname, _gname)
    # 批19 #8：移走类「挂载条目」计入父节点条目列表（`mounted_from` 标出来源模块，
    # 前端据此路由编辑/保存回来源模块；仍走来源模块的校验与原子写链路）。
    for _eid, _nm, _val, _frm in mounted_rows:
        _b = _entry_brief(_eid, _nm, _val)
        _b["mounted_from"] = _frm
        _b["mounted_from_label"] = _module_display_label(_frm, labels)
        briefs.append(_b)
    # 批20 B：**按条件过滤的并入**（目标模块条目 = 自身条目 ∪ 来源模块里满足条件的条目）。
    # 并入条目直接进中栏列表（带 `merged_from` 来源标注），计数计入本模块；编辑/保存仍由
    # 前端按 `merged_from` 路由回来源模块（数据文件 / 校验路径不动）。无声明 → 空表，行为同现状。
    mf_specs, _mf_notes = _entry_merge_filtered_specs(manifest, declared, pack_dir)
    merge_filtered_rows, merge_filtered_sections = _entry_merge_filtered_rows(
        pack_dir, declared, labels, mod, mf_specs)
    for _eid, _nm, _val, _frm, _spec in merge_filtered_rows:
        _b = _entry_brief(_eid, _nm, _val)
        _b["merged_from"] = _frm
        _b["merged_from_label"] = _module_display_label(_frm, labels)
        _b["merge_filtered"] = True
        briefs.append(_b)
    # 批19 #8：显示挂载类（keep_top_level / 虚拟视图）做纯展示小节，不进计数。
    mounted_sections: List[Dict[str, Any]] = []
    for _item in mounted_display:
        _frm, _eid = str(_item["from"]), str(_item["id"])
        _srows = _entry_rows(_read_json(pack_dir / f"{_frm}.json"),
                             _module_meta(_frm, pack_dir))
        _hit = next((r for r in _srows if r[0] == _eid), None)
        entries = [_entry_brief(_hit[0], _hit[1], _hit[2])] if _hit is not None else []
        mounted_sections.append({
            "module": _frm,
            "label": str(_item.get("source_label") or _frm),
            "mounted": True,
            "keep_top_level": True,
            "count": len(entries),
            "entries": entries,
        })
    # 批19 #4：框架键里「包数据已覆盖」的条目标 covered（前端标「已覆盖（包）」；
    # 包自有、框架键集里没有的键不打标——不冒充「覆盖框架」）。
    for _b in briefs:
        if _b["id"] in framework_keys and not _b.get("framework_default"):
            _b["covered"] = True
    for page in _segment_pages(manifest, declared, pack_dir).get(mod, []):
        pid = PAGE_PREFIX + page["id"]
        pages.append({"id": pid, "name": page["label"], "label": page["label"],
                      "help": page["help"], "segments": list(page["segments"]),
                      "page": True})
        for b in briefs:
            if b["id"] in page["segments"]:
                b["page"] = pid
    total_rows = len(rows) + len(mounted_rows) + len(merge_filtered_rows)
    return {
        "pack": str(pack),
        "module": mod,
        "label": _module_display_label(mod, labels),
        "entry_type": etype,
        "count": total_rows,
        "configured_count": total_rows - unconfigured_count,
        "unconfigured_count": unconfigured_count,
        "unconfigured_tag": UNCONFIGURED_TAG,
        # 批19 #4：框架键全集口径（无 key_source 声明时 = 空串 / 0 / 0，键集与现状一致）。
        "key_source": key_source,
        "framework_default_count": framework_default_count,
        "covered_count": covered_count,
        "framework_default_tag": FRAMEWORK_DEFAULT_TAG,
        "pack_covered_tag": PACK_COVERED_TAG,
        "key_is_name_note": KEY_IS_NAME_NOTE,
        "entries": briefs,
        # 批15 #9：整表入口（map 模块；其余模块为 null → 前端不渲染）
        "table_entry": table_entry,
        # 批15 #2：合并页（对象模块；其余模块为 []）——每页列出被合并的段 id
        "pages": pages,
        # 批20 C：中栏条目分组计划（无声明 = []；条目上的 group/group_label 同源）
        "entry_groups": group_plan,
        # 批12 #1：聚合视图（无声明时 = 空列表 / total_count == count，行为与现状一致）
        "merge_sections": sections,
        "merged_count": merged_count,
        # 批20 B：按条件过滤的并入（无声明时 = 空列表 / 0；条目已在中栏 `entries` 里，带
        # `merged_from` 来源标注；计数口径 = count/total_count 均含并入条目）
        "merge_filtered_sections": merge_filtered_sections,
        "merge_filtered_count": len(merge_filtered_rows),
        "total_count": total_rows + merged_count,
        # 批19 #8：本模块被移走的段 / 挂到本模块下的显示挂载小节（计数与检索口径见文档）。
        "moved_out_ids": sorted(tree_moved_out.get(mod, set())),
        "mounted_count": len(mounted_move),
        "mounted_sections": mounted_sections,
        # 批19 #5：模块用途一句话 + 「当前包未使用」态 + 功能重叠黄提示（通用；无声明 → 空）。
        "purpose": (catalog_entry(mod).purpose if catalog_entry(mod) is not None else ""),
        "unused": not _module_in_use(data),
        "overlap_hints": _module_overlap_hints(mod, pack_dir),
    }


def _infer_entry_type(data: object) -> str:
    if isinstance(data, list):
        return "list"
    if isinstance(data, Mapping):
        return "map"
    return "scalar"


def _entry_type(mmeta: Optional[ModuleMeta], data: object) -> str:
    """条目形态：元数据声明优先；未登记 / 纯展示壳（entry_type 空）→ 按实际数据推断。"""
    if mmeta is not None and mmeta.entry_type:
        return mmeta.entry_type
    return _infer_entry_type(data)


# =====================================================================================
# 批8：模块开关（可启用模块清单）——框架通用目录 + 包声明优先
# =====================================================================================
def _entry_type_for_module(pack_dir: Path, module: str) -> str:
    """模块的骨架形态：框架 ModuleMeta 优先 → 框架通用目录 → 已存在数据文件的实际形态。

    只用于「启用时创建什么形态的最小骨架」（list → []；map/object → {}），
    以及面板展示；不参与任何校验判定（校验规则仍由校验器裁定）。
    """
    mmeta = _module_meta(module, pack_dir)
    if mmeta is not None and mmeta.entry_type:
        return mmeta.entry_type
    ce = catalog_entry(module)
    if ce is not None and ce.entry_type:
        return ce.entry_type
    data = _read_json(pack_dir / f"{module}.json")
    if data is not None:
        return _infer_entry_type(data)
    return "list"


def catalog_module_names() -> List[str]:
    """框架通用目录里的模块键（面板基础清单；包声明只做增补与中文名覆盖）。"""
    return [entry.module for entry in FRAMEWORK_MODULE_CATALOG]


def is_enableable_module(module: object) -> bool:
    """模块键是否在框架「可启用模块」通用目录内（写入层用它做白名单）。

    批13：目录里 `implemented=False` 的条目（引擎尚未实装）**不可启用**——仍会在
    左栏/⚙ 面板以「未实现」态显示（一号原则：能力可见，但不产生无法消费的空数据文件）。
    """
    ce = catalog_entry(module)
    return ce is not None and ce.implemented


def module_catalog(pack: object, root: Optional[object] = None) -> Dict[str, Any]:
    """该包「可启用模块」清单（顶栏 ⚙ 模块开关面板的数据源）。

    清单 = **框架通用目录**（各模块键 + 通用中文默认名 + 一句话用途 + 骨架形态 + 前置模块）
    ∪ **该包 manifest 已声明但目录未登记的模块**（如包自定义模块）。
    逐行给出：中文名（**包声明优先**：field_meta.json / manifest / module_tree 节点 label；
    未声明才用框架通用默认名）、模块键、用途、entry_type、是否已启用、缺失的前置模块。

    「不是从当前包已有声明反推」：空白包也有一份完整候选（框架目录），这正是本 API 的意义。
    """
    pack_dir = _pack_dir(pack, root)
    manifest = _manifest(pack_dir)
    declared = _declared_modules(manifest)
    enabled = set(declared)
    pack_labels = _display_labels(manifest, declared, pack_dir)

    def label_of(module: str) -> str:
        ce = catalog_entry(module)
        return pack_labels.get(module) or (ce.label if ce is not None else module)

    keys = [entry.module for entry in FRAMEWORK_MODULE_CATALOG]
    keys += [m for m in declared if catalog_entry(m) is None]

    rows: List[Dict[str, Any]] = []
    for mod in keys:
        ce: Optional[ModuleCatalogEntry] = catalog_entry(mod)
        requires = list(ce.requires) if ce is not None else []
        rows.append({
            "module": mod,
            "label": label_of(mod),
            "label_source": ("pack" if mod in pack_labels else
                             ("framework" if ce is not None else "key")),
            "purpose": ce.purpose if ce is not None else "",
            "entry_type": _entry_type_for_module(pack_dir, mod),
            "enabled": mod in enabled,
            "in_catalog": ce is not None,
            "requires": requires,
            "requires_labels": [label_of(r) for r in requires],
            "missing_requires": [r for r in requires if r not in enabled],
            # 批13：能力可见性（一号原则）——引擎未实装 / 配置实际落点，供面板如实展示。
            "implemented": bool(ce.implemented) if ce is not None else True,
            "settings_section": (ce.settings_section if ce is not None else ""),
            # 批19 #5：功能重叠声明（黄提示；无声明 → 空串，面板不渲染）。
            "overlap_with": (ce.overlap_with if ce is not None else ""),
            "overlap_note": (ce.overlap_note if ce is not None else ""),
        })

    bak = pack_dir / "manifest.json.bak"
    return {
        "pack": str(pack),
        "pack_name": str(manifest.get("name", "") or pack),
        "hint": MODULE_PANEL_HINT,
        "modules": rows,
        "total": len(rows),
        "enabled_count": sum(1 for r in rows if r["enabled"]),
        "manifest_backup": {"path": "manifest.json.bak", "exists": bak.is_file()},
    }



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
#   condition（条件行编辑器）/ maptable（键值对表格）/ objform（对象子字段表单）
# 批4 范围：list 升级为可编辑（元素为 obj/标量 → 可增删行表格 listtable；
# 元素为 ref → 引用多选 reflist）。
# 批14 #4：**对象型子字段可编辑**（`obj` → `objform`）——按框架元数据递归渲染子字段控件
# （布尔→开关 / 数字→数字框 / 文本→输入框 / 枚举→下拉 / 引用→引用选择器）；元数据未登记
# 的子字段走兜底控件（按实际值推断 + 标注）。是否「可增删键」只看元数据：登记了子字段的
# 对象 = 固定 schema（不增删键）；未登记子字段的对象 = 动态键空间（可增删，`open_keys`）。
# map 仍只读展示（宽容器，键→值混合形态，不在本批范围）。
# 批5：字段可用 FieldMeta.editor 显式声明控件（condition / maptable），覆盖默认映射；
# 未声明时行为与批4 完全一致（type → widget → control）。
_EDIT_BY_WIDGET: Dict[str, Tuple[str, bool]] = {
    "text": ("text", True),
    "number": ("number", True),
    "bool": ("bool", True),
    "enum": ("select", True),
    "ref": ("ref", True),
    "formula": ("text", True),  # 表达式文本；值实为对象时按值形态纠偏为 objform
    "list": ("listtable", True),
    "obj": ("objform", True),
    "map": ("kvtable", True),   # 批15 #9：键值表格（键 → 标量/小结构，行内编辑 + 增删行）
    "curve": ("curve", True),   # 批15 #2：曲线控件（等级 → 数值；公式/摘要 + 双击明细）
}
EDIT_CONTROLS: Tuple[str, ...] = (
    "text", "textarea", "number", "bool", "select", "ref",
    "listtable", "reflist", "readonly", "condition", "maptable", "objform",
    "kvtable", "curve",
)
# 批次可编辑控件集：显式声明的 condition / maptable / objform 归为可编辑（前端按 control 渲染）。
_READONLY_CONTROLS: Tuple[str, ...] = ("readonly",)
# 批14 #4：对象「动态键空间」判定（唯一实现点）——登记了子字段 = 固定 schema（不增删键）；
# 未登记子字段（fm 缺失或 children 为空）= 开放键空间（可新增/删除子项，走兜底控件）。
# 纯展示层：只影响是否给「+ 子项 / ✕ 删除」控件，不改 type/required/校验。
def open_keys_of(fm: Optional[FieldMeta]) -> bool:
    return fm is None or (fm.type == "obj" and not fm.children)


def _obj_unregistered_keys(fm: Optional[FieldMeta], value: object) -> bool:
    """对象值里是否含**元数据未登记**的键（批20 A：动态键空间判定，通用、不认字段名）。

    登记了子字段的对象若实际值里多出未登记键（如 `resistance` 的 `stun`、`ai` 的 `states`），
    其键空间就是动态的——按映射表渲染并放开增删键，而不是按固定 schema 只出登记项。
    """
    if not isinstance(value, Mapping):
        return False
    declared = {str(k) for k in (fm.children if fm is not None and fm.children else {})}
    return any(str(k) not in declared for k in value)


def _obj_kv_tableable(fm: Optional[FieldMeta], value: object) -> bool:
    """对象型字段的值是否按**映射表**（kvtable）渲染（批20 A，纯展示层判定）。

    条件（任一，全部只看值形态 + 元数据，不认模块名/字段名）：
      · 元数据声明为 `map`（键 → 值容器）；
      · 动态键空间（未登记子字段，`open_keys_of`）；
      · 值里含元数据未登记的键（登记了子字段但实际多出键）。
    登记了子字段、键集合又完全吻合的对象（如 drop_exp / stats）仍是 objform 表单。
    """
    if not isinstance(value, Mapping):
        return False
    if fm is not None and fm.type == "map":
        return True
    if open_keys_of(fm):
        return True
    return _obj_unregistered_keys(fm, value)


def _kv_open_keys(fm: Optional[FieldMeta], value: object) -> bool:
    """键值表格是否「动态键空间」（键可改名、行可增删；批20 A）。

    元数据显式声明 `editor="kvtable"` 的对象 = 映射语义（键空间由内容定义，如抗性是
    「负面效果 ID → 0-100」）→ 放行增删；其余走既有判定（未登记子字段 / 值含未登记键）。
    **只影响界面上是否给「+ 添加一项 / 改名」控件**——写入仍走原校验与原子写链路。
    """
    if fm is not None and fm.editor == "kvtable":
        return True
    return open_keys_of(fm) or _obj_unregistered_keys(fm, value)



def is_editable_control(control: Optional[str]) -> bool:
    """控件形态是否可编辑（只读形态 = readonly；批5 起按最终 control 判定）。"""
    return (control or "") not in _READONLY_CONTROLS


# 批5.1：控件形态 → 该列的值是否承载**嵌套结构**（对象 / 映射 / 条件 / 嵌套列表）。
# 列表元素只要含这类子字段，前端就改「块状换行」布局：标量列横排成块首行，嵌套字段各自
# 成块、占满容器宽度（不再把条件编辑器/键值表格塞进单元格、不再横向滚动 9 列宽表）。
# 判定只依据 control（§三 映射表的产物），不认任何业务字段名——换包/换模块零改动。
_NESTED_CONTROLS: Tuple[str, ...] = ("condition", "maptable", "readonly", "listtable",
                                     "objform", "kvtable", "curve")


def is_nested_control(control: Optional[str]) -> bool:
    """控件形态是否承载嵌套结构（对象/映射/条件/嵌套列表）→ 列表需块状布局。"""
    return (control or "") in _NESTED_CONTROLS


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


def control_for(fm: Optional[FieldMeta], widget: str, multiline: bool = False) -> str:
    """字段最终编辑控件（§三 映射表唯一实现点；批5 起支持 FieldMeta.editor 显式覆盖）。

    优先序：显式 editor 声明（**必须在已知控件集内**，否则忽略、回退类型映射）→
    list 元素分流（listtable/reflist）→ 类型默认映射。
    只影响界面控件，不改 type/required/enum/children/校验规则。
    """
    if fm is not None and fm.editor and fm.editor in EDIT_CONTROLS:
        return fm.editor
    if widget == "list":
        return list_control(fm)
    return control_of(widget, multiline)


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


# 实际值形态 → 字段类型口径（元数据未登记类型时的唯一推断入口）。
# 与 _infer_type 分开：数值再细分为 int / float（整数 / 小数），说明卡据此标注。
_KIND_TO_FTYPE: Dict[str, str] = {
    "int": "int", "float": "float", "bool": "bool", "str": "str",
    "list": "list", "obj": "obj",
}


def _infer_value_kind(value: object) -> Optional[str]:
    """实际值 → int/float/bool/str/list/obj；判不出（None/未知）返回 None。

    布尔必须先于 int 判定（Python 里 bool 是 int 子类）；浮点整值（如 20.0）
    按「整数」呈现，与 _scalar_display 的 20.0→"20" 展示口径一致。
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "int" if float(value).is_integer() else "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, Mapping):
        return "obj"
    return None


def _effective_widget(fm: Optional[FieldMeta], value: object) -> str:
    """元数据类型 + 实际值形态 → 只读控件形态（元数据优先，值形态纠偏防渲染崩）。"""
    # 批12 #3：字段声明了展示层引用候选来源（options_ref）→ 一律按引用选择器渲染
    # （字段 type/校验口径不变；候选来自 options_ref 指定的内部引用命名空间）。
    if fm is not None and fm.options_ref:
        return "ref"
    base = _widget_for_type(fm.type if fm is not None else None)
    unregistered = fm is None or not fm.type
    # 批15 #2：曲线形态（键为整数序号、值为数字的映射）→ 曲线控件（默认公式/摘要行）。
    # 通用识别，优先于 obj/map；不写死任何字段名。仅当元数据未声明别的编辑器时才生效。
    if (isinstance(value, Mapping) and _is_curve_value(value)
            and base in ("obj", "map", "text") and not (fm is not None and fm.editor)):
        return "curve"
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
        if base == "obj":
            return "obj"
        # 批14 #4：元数据未登记类型的映射 → 按对象（objform）渲染，子字段走兜底控件
        # （按实际值类型推断 + 标注）——一号原则：能编就编，不因缺元数据退化成只读块。
        # 显式声明 map 的字段（base == "map"）仍按键值映射只读展示，不受影响。
        if unregistered:
            return "obj"
        return "map"
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
    rt = _ref_target_of(fm)
    if rt:
        bits.append(f"引用：{rt}")
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


def _registered_type(fm: Optional[FieldMeta]) -> Optional[str]:
    """元数据**真实登记**的字段类型；未登记（fm=None 或 type="" 占位）返回 None。

    批4.5 起「只有中文名、没有类型」的纯展示节点由 _soft_display 生成（type=""），
    这里必须把它当「未登记」——否则说明卡会把数值字段说成文本（实机问题①根因）。
    批12 #3：声明了 options_ref 的字段，展示类型按引用呈现（控件/说明卡一致）。
    """
    if fm is not None and fm.options_ref:
        return "ref"
    ftype = fm.type if fm is not None else None
    return ftype if ftype in _TYPE_SEMANTIC else None


def _ref_target_of(fm: Optional[FieldMeta]) -> Optional[str]:
    """字段在**展示层**的引用候选目标：options_ref（内部键空间，纯展示）优先于 ref_target。"""
    if fm is None:
        return None
    return fm.options_ref or fm.ref_target


def _type_semantic(ftype: Optional[str]) -> str:
    """FieldMeta.type → 中文类型语义（未登记类型如实说「未标注」，不猜）。"""
    return _TYPE_SEMANTIC.get(ftype or "", "未标注")


# 实际值推断出的类型语义（数值细分整数/小数；登记类型仍走 _type_semantic）。
_INFERRED_TYPE_SEMANTIC: Dict[str, str] = {
    "int": "数值（整数）", "float": "数值（小数）",
    "bool": "布尔", "str": "文本", "list": "列表", "obj": "对象",
}


def _resolve_type(fm: Optional[FieldMeta],
                  value: object = None) -> Tuple[str, str]:
    """类型语义 + 推断来源：登记类型优先；未登记则按实际值真实类型推断。

    → (类型文案, 来源文案)。来源文案仅在实际值推断时非空，供卡片显式标注
    （如「数值（整数）· 元数据未登记，按实际值推断」）。
    """
    reg = _registered_type(fm)
    if reg:
        # 登记为 int/float 时也细分整数/小数（说明卡更具体；语义不变）。
        if reg == "int":
            return ("数值（整数）", "")
        if reg == "float":
            return ("数值（小数）", "")
        return (_type_semantic(reg), "")
    kind = _infer_value_kind(value)
    if kind is None:
        return ("未标注", "")
    return (_INFERRED_TYPE_SEMANTIC.get(kind, "未标注"), "元数据未登记，按实际值推断")


def _scale_semantic(fm: Optional[FieldMeta], value: object = None) -> str:
    """「是数值还是比例/百分比」判定。

    依据优先序：probability 旗标 → unit（`%` 为百分比、其余为带单位数值）→
    数值型且区间恰为 0~1（推断可能是比例）→ 当前值落在 0~1（疑似比例）→
    其余数值「未标注单位」→ 非数值「不适用」→ 类型/值都判不出「未标注」。
    数值类型可来自元数据登记，也可由实际值推断（问题①修复）；判不出来如实说。
    """
    reg = _registered_type(fm)
    kind = _infer_value_kind(value)
    numeric = reg in _NUMERIC_TYPES or kind in ("int", "float")
    if not numeric:
        if reg is None and kind is None:
            return "未标注"          # 类型未登记且没有值可推断 → 不臆造
        return "不适用（非数值字段）"
    if fm is not None and fm.probability:
        return "比例（0~1，按百分比表示概率）"
    if fm is not None and fm.unit == "%":
        return "百分比（数值自带 % 单位）"
    if fm is not None and fm.unit:
        return f"数值（单位：{fm.unit}）"
    if fm is not None and fm.range_min == 0 and fm.range_max == 1:
        return "比例（0~1；元数据未标注百分比单位）"
    if (fm is None or (fm.range_min is None and fm.range_max is None)) \
            and kind in ("int", "float") \
            and 0 <= float(value) <= 1:  # type: ignore[arg-type]
        return "疑似比例（当前值在 0~1；元数据未标注单位）"
    return "数值（未标注单位）"


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


def help_card(key: str, fm: Optional[FieldMeta],
              value: object = None) -> Dict[str, Any]:
    """字段说明卡数据（自动拼装 + 人工 help）；全部是可直接展示的中文短语。

    前端只按本结构渲染，不认字段类型、不认任何业务字段名（保持元数据驱动）。
    · 类型：元数据登记优先；未登记（fm=None 或 type 占位为空）→ 按 `value` 实际值
      推断（数值细分整数/小数），并在 `type_source` 显式标注来源；
    · 数值/比例：元数据 unit/probability/0~1 区间优先，未登记时按实际值推断
      （0~1 → 疑似比例），判不出来如实「未标注」，不说「不适用」；
    · 元数据完全未登记（fm=None）且无值可推断 → unregistered=True，如实标「未登记」。
    """
    type_text, type_source = _resolve_type(fm, value)
    if fm is None:
        if value is None:
            type_text, type_source = "未登记", ""
        return {
            "key": key, "label": key, "type": type_text, "type_source": type_source,
            "scale": _scale_semantic(None, value), "range": "未标注",
            "default": "无默认值" if value is not None else "未标注",
            "required": False, "enum": [], "ref_target": None, "unit": "",
            "help": "", "unregistered": True,
            # 批5.2（V1）：行内提示不再常驻撑高字段行，统一收进说明卡（同一 `_hint` 文案）。
            "hint": _hint(None),
        }
    default = _default_text(fm.default)
    out = {
        "key": key,
        "label": fm.label or key,
        "type": type_text,
        "type_source": type_source,
        "scale": _scale_semantic(fm, value),
        "range": _range_semantic(fm),
        "default": default or "无默认值",
        "required": bool(fm.required),
        "enum": [str(x) for x in fm.enum],
        "ref_target": _ref_target_of(fm),
        "unit": fm.unit,
        "help": fm.help,
        "unregistered": False,
        # 批5.2（V1）：`_hint`（必填/候选/引用/范围/0=不限/默认）作为说明卡的一行，
        # 前端不再在字段值下方常驻渲染 `.hint`（行高与无提示字段一致）。
        "hint": _hint(fm),
    }
    # 批16 #10：定义处默认值（引用处可覆盖）→ 说明卡标注（展示层）；仅标注字段才出键，
    # 避免给所有字段加噪音键（对拍门禁的新增项最小化）。
    if getattr(fm, "overridable_default", False):
        out["default_note"] = "默认值（可被引用处覆盖）"
    return out


# =====================================================================================
# 条件结构（批5）：条件行编辑器数据面 + 关联分区路径匹配
# =====================================================================================
# 条件值的通用形态（**键名不写死**）：
#   {"<主体>": {"<比较符>": 值}}                一级（如 {主体:{eq:3}}）
#   {"<主体>": {"<二级键>": {"<比较符>": 值}}}   两级（如 {自身印记:{印记ID:{min:5}}}）
#   {"<组合>": [{条件}, {条件}]}               逻辑组合（and/or，键名由元数据声明）
# 本段提供解析（condition_rows）与序列化（condition_value）的参考实现，
# 前端 JS（EditorCondition）与之同构（node 测试逐条比对）；元数据缺省
# （condition_subjects 为空）时完全按实际值形态推断，spec 里如实标注 declared=False。
def condition_spec(fm: Optional[FieldMeta]) -> Dict[str, Any]:
    """条件行编辑器的主体/比较符声明（来自元数据；缺省 declared=False 如实标注）。"""
    declared = fm.condition_subjects if fm is not None else {}
    subjects: List[Dict[str, Any]] = []
    ops: List[str] = []
    for key, sub in declared.items():
        subjects.append({
            "key": str(key),
            "label": sub.label or str(key),
            "key_ref": sub.key_ref or "",
            "value_ref": sub.value_ref or "",
            "value_enum": [str(v) for v in (sub.value_enum or ())],
            "ops": [str(o) for o in sub.ops],
            "combine": bool(sub.combine),
        })
        for op in sub.ops:
            if str(op) not in ops:
                ops.append(str(op))
    return {"subjects": subjects, "ops": ops, "declared": bool(declared)}


def _is_comparator_group(value: Mapping[str, Any]) -> bool:
    """二级映射是否「比较符 → 标量/列表」（True=一级条件；False=还有更深的二级键）。"""
    vals = list(value.values())
    return bool(vals) and all(not isinstance(v, Mapping) for v in vals)


def _condition_entry_rows(subject: str, val: object) -> List[Dict[str, Any]]:
    if isinstance(val, list):
        groups = [condition_rows(elem) for elem in val]
        return [{"kind": "combine", "subject": subject, "children": groups}]
    if isinstance(val, Mapping):
        if _is_comparator_group(val):
            return [{"kind": "cmp", "subject": subject, "key": "", "op": str(op),
                     "value": v} for op, v in val.items()]
        out: List[Dict[str, Any]] = []
        for sub_key, sub_val in val.items():
            if isinstance(sub_val, Mapping) and _is_comparator_group(sub_val):
                out.extend({"kind": "cmp", "subject": subject, "key": str(sub_key),
                            "op": str(op), "value": v} for op, v in sub_val.items())
            elif isinstance(sub_val, Mapping):
                # 超过两级的深结构：整体保留为只读值，不丢数据
                out.append({"kind": "cmp", "subject": subject, "key": str(sub_key),
                            "op": "", "value": dict(sub_val), "complex": True})
            else:
                out.append({"kind": "cmp", "subject": subject, "key": "",
                            "op": str(sub_key), "value": sub_val})
        return out
    return [{"kind": "cmp", "subject": subject, "key": "", "op": "", "value": val}]


def condition_rows(value: object) -> List[Dict[str, Any]]:
    """条件值 → 条件行模型（参考实现；前端 EditorCondition.parse 与之同构）。"""
    if not isinstance(value, Mapping):
        return [] if value is None else [
            {"kind": "cmp", "subject": "", "key": "", "op": "", "value": value}]
    rows: List[Dict[str, Any]] = []
    for key, val in value.items():
        rows.extend(_condition_entry_rows(str(key), val))
    return rows


def condition_value(rows: object) -> Dict[str, Any]:
    """条件行模型 → 条件值（参考实现；前端 EditorCondition.serialize 与之同构）。"""
    out: Dict[str, Any] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, Mapping):
            continue
        subject = str(row.get("subject") or "")
        if not subject:
            continue
        if row.get("kind") == "combine":
            groups = row.get("children") if isinstance(row.get("children"), list) else []
            out[subject] = [condition_value(g) for g in groups]
            continue
        key = str(row.get("key") or "")
        op = str(row.get("op") or "")
        value = row.get("value")
        if key:
            bucket = out.setdefault(subject, {})
            if not isinstance(bucket, dict):
                continue
            if op == "":
                bucket[key] = value
            else:
                inner = bucket.setdefault(key, {})
                if isinstance(inner, dict):
                    inner[op] = value
        elif op == "":
            out[subject] = value
        else:
            bucket = out.setdefault(subject, {})
            if isinstance(bucket, dict):
                bucket[op] = value
    return out


def _walk_path(subject: object, path: str) -> List[Tuple[str, object]]:
    """按字段路径取值（支持点路径与列表通配 `a[].b`）：→ [(实际路径, 值)]。

    编辑器「关联分区」据此在相关模块条目里找外键（含列表内通配，如 `steps[].to`）；
    路径不写死任何业务键（键名来自包元数据的关联声明）。
    """
    if not path:
        return []
    cur: List[Tuple[str, object]] = [("", subject)]
    for token in str(path).split("."):
        is_list = token.endswith("[]")
        key = token[:-2] if is_list else token
        nxt: List[Tuple[str, object]] = []
        for prefix, val in cur:
            if not isinstance(val, Mapping) or key not in val:
                continue
            child = val[key]
            p = f"{prefix}.{key}" if prefix else key
            if is_list:
                if isinstance(child, list):
                    for i, elem in enumerate(child):
                        nxt.append((f"{p}[{i}]", elem))
            else:
                nxt.append((p, child))
        cur = nxt
    return cur


def _local_values(subject: object, local_field: str, entry_id: str) -> List[object]:
    """本条目用于与关联外键比较的取值（缺省 id；兼容简单路径声明）。"""
    field = local_field or _ID_FIELD
    vals = [v for _p, v in _walk_path(subject, field)]
    if vals:
        return vals
    return [entry_id]


# =====================================================================================
# 关联分区（批5）：元数据声明「本模块条目 ↔ 其他模块条目的外键」→ 条目页相关条目分区
# =====================================================================================
def _path_field_label(mmeta: Optional[ModuleMeta], path: object) -> str:
    """字段路径 → 元数据中文名（关联分区副标题「中文（键）」用；查不到返回空串）。

    路径可含列表通配（如 `steps[].to`）：按 `.` / `[]` 切段，逐段沿
    `FieldMeta.children`（obj）与 `element.children`（list 元素对象）下钻；
    认不出就如实返回空串，前端回退显示原始键，不凭空造词。
    """
    if mmeta is None or not path:
        return ""
    parts = [p for p in re.split(r"[.\[\]]+", str(path)) if p]
    parts = [p for p in parts if not p.isdigit()]  # 列表下标段（steps[0]）不参与下钻
    if not parts:
        return ""
    fm = mmeta.fields.get(parts[0])
    for seg in parts[1:]:
        if fm is None:
            return ""
        if fm.children:
            fm = fm.children.get(seg)
        elif fm.element is not None and fm.element.children:
            fm = fm.element.children.get(seg)
        else:
            return ""
    return fm.label if fm is not None and fm.label else ""


def _association_sections(pack_dir: Path, manifest: Mapping[str, Any],
                          declared: List[str], entry_id: str, entry_subject: object,
                          mmeta: Optional[ModuleMeta],
                          view: "_PackView") -> List[Dict[str, Any]]:
    """条目页「关联分区」数据（全部来自 ModuleMeta.associations 声明）。

    · 可编辑分区：相关条目按该模块自己的字段元数据出完整表单（前端就地编辑，
      保存仍走该模块的校验 + 原子写链路）；
    · 只读分区（editable=False）：只出摘要（id/名称/命中路径）+ 跳转。
    编辑器本段不写死任何模块名/字段名（换包/换模块零改动）。
    """
    if mmeta is None or not mmeta.associations:
        return []
    labels = _display_labels(manifest, declared, pack_dir)
    sections: List[Dict[str, Any]] = []
    for idx, a in enumerate(mmeta.associations):
        if not isinstance(a.module, str) or not a.module or not a.field:
            continue
        section: Dict[str, Any] = {
            "key": f"assoc:{idx}:{a.module}:{a.field}",
            "label": a.label or (_module_display_label(a.module, labels)),
            "module": a.module,
            "module_label": _module_display_label(a.module, labels),
            "field": a.field,
            # 批5.2（V9）：副标题/命中行统一「中文（键）」——中文名来自字段元数据，
            # 查不到则留空，前端回退原始键（不凭空造词）。
            "field_label": _path_field_label(_module_meta(a.module, pack_dir), a.field),
            "local_field": a.local_field or _ID_FIELD,
            "local_field_label": _path_field_label(mmeta, a.local_field or _ID_FIELD),
            "editable": bool(a.editable),
            "hint": a.hint,
            "entries": [],
            "count": 0,
            "declared": a.module in declared,
        }
        if a.module not in declared:
            section["note"] = f"关联模块未在包 manifest 中声明：{a.module}"
            sections.append(section)
            continue
        rel_data = _read_json(pack_dir / f"{a.module}.json")
        rel_mmeta = _module_meta(a.module, pack_dir)
        rel_etype = _entry_type(rel_mmeta, rel_data)
        local_vals = _local_values(entry_subject, a.local_field or _ID_FIELD, entry_id)
        entries: List[Dict[str, Any]] = []
        for eid, name, subject in _entry_rows(rel_data, rel_mmeta):
            matched = [(p, v) for p, v in _walk_path(subject, a.field)
                       if any(v == lv for lv in local_vals)]
            if not matched:
                continue
            entry: Dict[str, Any] = {
                "id": eid, "name": name,
                "matches": [{"path": p, "value": _json_text(v)} for p, v in matched],
            }
            if a.editable:
                base = _entry_base(rel_mmeta, rel_etype, eid, subject)
                fields = _build_fields(base, subject, rel_mmeta, view, 0)
                entry.update({
                    "module": a.module,
                    "module_label": section["module_label"],
                    "fields": fields,
                    "field_count": len(fields),
                    "groups": _group_summary(fields, rel_mmeta),
                })
            entries.append(entry)
        entries.sort(key=lambda e: (str(e["name"]), str(e["id"])))
        section["entries"] = entries
        section["count"] = len(entries)
        sections.append(section)
    return sections


def _resolve_group(key: str, fm: Optional[FieldMeta], mmeta: Optional[ModuleMeta]) -> str:
    """分组解析（缺省兜底）：FieldMeta.group → 模块分组表 → 单一默认分组。"""
    if fm is not None and fm.group:
        return fm.group
    if mmeta is not None and key in mmeta.field_groups:
        return mmeta.field_groups[key]
    return DEFAULT_GROUP


def _resolve_subgroup(key: str, fm: Optional[FieldMeta], mmeta: Optional[ModuleMeta]) -> str:
    """二级分组（折叠子块）解析：FieldMeta.subgroup → 模块二级分组表 → 主块（空串）。

    纯展示层：只决定字段落在哪个折叠块，不改任何校验判定。
    """
    if fm is not None and fm.subgroup:
        return str(fm.subgroup)
    if mmeta is not None and str(key) in mmeta.field_subgroups:
        return str(mmeta.field_subgroups[str(key)])
    return ""


def _block_plan(fields: List[Dict[str, Any]], mmeta: Optional[ModuleMeta],
                collapse_named: bool = True) -> Dict[str, List[Dict[str, Any]]]:
    """分组 → 折叠子块计划（二级结构；元数据/顺序驱动，**不认模块名/字段名**）。

    · 子块顺序：ModuleMeta.subgroup_order → 字段首次落入顺序；
    · 主块（无子块声明）平铺、默认展开；命名子块默认折叠（`collapse_named=False` 时全展开，
      供「合并页」这类需要一次看全的场景复用）；
    · 主块字段数 > AUTO_MORE_AFTER 时，按字段声明顺序把超出部分收进隐式「更多字段」块
      （块键 = AUTO_MORE_BLOCK，显示名 = 包 subgroup_labels 覆盖 → 兜底 MORE_FIELDS_LABEL）。
    只为展示服务：字段不会因折叠而消失（全部仍在 DOM 里，只是默认收起）。
    """
    order: List[str] = []
    by_group: Dict[str, List[Dict[str, Any]]] = {}
    for f in fields:
        g = str(f.get("group") or DEFAULT_GROUP)
        if g not in by_group:
            by_group[g] = []
            order.append(g)
        by_group[g].append(f)
    out: Dict[str, List[Dict[str, Any]]] = {}
    labels: Mapping[str, str] = mmeta.subgroup_labels if mmeta is not None else {}
    for g in order:
        fs = by_group[g]
        declared: List[str] = []

        def _declare(s: str) -> None:
            if s and s not in declared:
                declared.append(s)

        if mmeta is not None:
            for s in mmeta.subgroup_order:
                _declare(str(s))
        for f in fs:
            _declare(str(f.get("subgroup") or ""))
        # 隐式「更多字段」块只在**没有任何命名子块时**参与排序（有命名子块时主块通常很小）
        if not declared and len(fs) > AUTO_MORE_AFTER:
            _declare(AUTO_MORE_BLOCK)
        declared = [s for s in declared if s != ""]

        def _mk(name: str, items: List[Dict[str, Any]],
                label: str, collapsed: bool) -> Dict[str, Any]:
            keys = [str(it.get("key") or "") for it in items]
            for it in items:
                it["block"] = name
            return {"name": name, "label": label, "count": len(items),
                    "collapsed": bool(collapsed), "keys": keys}

        blocks: List[Dict[str, Any]] = []
        main = [f for f in fs if not (f.get("subgroup") or "")]
        if not declared and len(fs) > AUTO_MORE_AFTER:
            # 全平铺且字段多 → 前 AUTO_MORE_AFTER 常驻，其余进隐式「更多字段」
            blocks.append(_mk("", fs[:AUTO_MORE_AFTER], "", False))
            more = fs[AUTO_MORE_AFTER:]
            for f in more:
                f["subgroup"] = AUTO_MORE_BLOCK
            blocks.append(_mk(AUTO_MORE_BLOCK, more,
                              str(labels.get(AUTO_MORE_BLOCK) or MORE_FIELDS_LABEL), True))
        elif not declared:
            if main:
                blocks.append(_mk("", main, "", False))
        else:
            if len(main) > AUTO_MORE_AFTER:
                blocks.append(_mk("", main[:AUTO_MORE_AFTER], "", False))
                more = main[AUTO_MORE_AFTER:]
                for f in more:
                    f["subgroup"] = AUTO_MORE_BLOCK
                blocks.append(_mk(AUTO_MORE_BLOCK, more,
                                  str(labels.get(AUTO_MORE_BLOCK) or MORE_FIELDS_LABEL), True))
            elif main:
                blocks.append(_mk("", main, "", False))
            for s in declared:
                if s == AUTO_MORE_BLOCK:
                    continue
                sfs = [f for f in fs if str(f.get("subgroup") or "") == s]
                if not sfs:
                    continue
                blocks.append(_mk(s, sfs,
                                  str(labels.get(s) or s), bool(collapse_named)))
        out[g] = blocks
    return out


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
            self._names = _build_name_index(self.dir, self.declared, _pack_meta_table(self.dir))
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
    # 批12 #3：模块内**列表/映射字段**的条目登记成 `<模块>.<字段>` 引用命名空间
    # （供 options_ref 声明的展示层引用选择器取候选；通用，不认任何业务字段名）。
    for mod in declared:
        mm = meta.module(mod)
        if mm is None or not mm.fields:
            continue
        data = _read_json(pack_dir / f"{mod}.json")
        if not isinstance(data, Mapping):
            continue
        for fkey, fm in mm.fields.items():
            if fm is None or fm.type not in ("list", "map", "obj"):
                continue
            table = _nested_entry_index(data.get(str(fkey)))
            if table:
                index.setdefault(f"{mod}.{fkey}", {}).update(table)
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


def _nested_entry_index(value: object) -> Dict[str, str]:
    """把「列表/映射字段的值」登记为 {条目 id: 名称}（批12 #3 通用；空/非条目 → {}）。"""
    table: Dict[str, str] = {}
    if isinstance(value, list):
        for i, elem in enumerate(value):
            if not isinstance(elem, Mapping):
                continue
            eid = elem.get(_ID_FIELD)
            eid = eid if isinstance(eid, str) and eid else f"#{i}"
            nm = elem.get(_NAME_FIELD)
            table[eid] = nm if isinstance(nm, str) and nm else eid
    elif isinstance(value, Mapping):
        for key, val in value.items():
            if not isinstance(key, str) or not key:
                continue
            nm = val.get(_NAME_FIELD) if isinstance(val, Mapping) else None
            table[str(key)] = nm if isinstance(nm, str) and nm else str(key)
    return table


# =====================================================================================
# 只读 API ④：条目全字段 + 分组 + 每字段类型
# =====================================================================================
def _column(key: str, fm: Optional[FieldMeta], key_label: Optional[str] = None,
            value: object = None) -> Dict[str, Any]:
    """列表表格的一列：列名/类型来自元素字段元数据（缺省按值推断）。

    批4 起列描述同时携带**编辑**所需信息（control/enum/number_step/default），
    前端按 control 渲染单元格，不认字段类型（映射仍在 api 层唯一实现）。
    批4.6 补：`value`（该列的实际样本值）供类型未登记时推断，说明卡不再误判文本。
    """
    reg = _registered_type(fm)
    if reg:
        ftype = reg
    else:
        ftype = _KIND_TO_FTYPE.get(_infer_value_kind(value) or "", "") or _infer_type(value)
    widget = _effective_widget(fm, value)
    multiline = bool(getattr(fm, "multiline", False)) if fm is not None else False
    control = control_for(fm, widget, multiline)
    col: Dict[str, Any] = {
        "key": key,
        "label": (fm.label if fm is not None and fm.label else (key_label or key)),
        "type": ftype,
        "widget": widget,
        "control": control,
        # 批5.1：本列是否嵌套结构（对象/映射/条件/嵌套列表）→ 列表块状布局的判定依据。
        "nested": is_nested_control(control),
        "ref_target": _ref_target_of(fm),
        "enum": [str(x) for x in fm.enum] if fm is not None and fm.enum else [],
        "number_step": _number_step(ftype),
        "default": fm.default if fm is not None else None,
        # 批4.6：列头也可出说明卡（自动拼装 + 人工 help），与主表单同源。
        "unit": fm.unit if fm is not None else "",
        "help": fm.help if fm is not None else "",
        "help_card": help_card(key, fm, value),
        # 批15 #9：列元数据未登记（键值表格按值推断的列）→ 与主表单同口径的兜底标注。
        "meta_unregistered": fm is None,
        "meta_note": META_UNREGISTERED_NOTE if fm is None else "",
    }
    # 批5：条件行 / 键值对表格单元格的额外声明（主体/比较符/引用目标）
    if control == "condition":
        col["condition"] = condition_spec(fm)
    elif control == "maptable":
        col["key_ref"] = fm.key_ref if fm is not None else ""
        col["value_ref"] = fm.value_ref if fm is not None else ""
    return col


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
    """列表字段的只读表列：元素元数据声明优先；实际行里多出的键按值推断补列。

    批4.6：每列取一个实际样本值（首行出现该键的值），供类型未登记时推断——
    行内 soft 纯展示子字段（只有中文名、无 type）不再被说明卡误判成文本。
    """
    elem = fm.element if fm is not None else None
    cols: List[Dict[str, Any]] = []
    known: set = set()

    def sample(column: str) -> object:
        for row in rows:
            if isinstance(row, Mapping) and column in row:
                return row[column]
        return None

    if elem is not None and elem.type == "obj" and elem.children:
        for ck, cfm in elem.children.items():
            cols.append(_column(str(ck), cfm, value=sample(str(ck))))
        known = set(str(k) for k in elem.children)
    elif elem is not None and elem.type in (
        "ref", "str", "number", "int", "float", "bool", "enum"
    ):
        cols.append(_column("value", elem, key_label="值",
                            value=(rows[0] if rows else None)))
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        for k in row:
            if not isinstance(k, str) or k in known:
                continue
            known.add(k)
            cols.append(_column(k, None, value=sample(k)))
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


# -------------------------------------------------------------------------------------
# 批15 #9：键值表格（kvtable）——「键 → 标量值 / 小结构」的密集映射。
# 判定/列/行全部由**值形态 + 元数据**决定，不认任何字段名；只影响控件，不改校验语义。
# -------------------------------------------------------------------------------------
def _is_scalarish(value: object) -> bool:
    """标量（含 None）：文本/数字/布尔——可放进一个单元格行内编辑。"""
    return value is None or isinstance(value, (str, int, float, bool))


def _is_small_struct(value: object) -> bool:
    """小结构：键数 <= KV_MAX_STRUCT_KEYS 且叶子全为标量（值 → 一排列）。"""
    if not isinstance(value, Mapping) or not value:
        return False
    if len(value) > KV_MAX_STRUCT_KEYS:
        return False
    return all(_is_scalarish(v) for v in value.values())


def _is_curve_value(value: object) -> bool:
    """曲线形态判定（通用）：键为整数序号、值为数字的映射（含可选约定标记键）。

    `use_formula`（布尔）与 `formula`（文本）是曲线控件的-frame 约定键，不参与「整数键」判定；
    其余键必须可解析为整数、值必须是数字（bool 不算数字）。空/单点/非数字 → 不是曲线。
    """
    if not isinstance(value, Mapping):
        return False
    points = 0
    for k, v in value.items():
        ks = str(k)
        if ks in (CURVE_FLAG_KEY, CURVE_FORMULA_KEY):
            if ks == CURVE_FLAG_KEY and not isinstance(v, bool):
                return False
            if ks == CURVE_FORMULA_KEY and not isinstance(v, str):
                return False
            continue
        try:
            int(ks)
        except (TypeError, ValueError):
            return False
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return False
        points += 1
    return points >= 2


def _is_dense_map(value: object) -> bool:
    """「键 → 标量 / 小结构」的密集映射（曲线除外）→ 走键值表格；否则保持既有控件。"""
    if not isinstance(value, Mapping) or len(value) < 2:
        return False
    if _is_curve_value(value):
        return False
    return all(_is_scalarish(v) or _is_small_struct(v) for v in value.values())


def _kv_columns(value: Mapping[str, Any], fm: Optional[FieldMeta],
                view: "_PackView") -> Tuple[bool, List[Dict[str, Any]]]:
    """键值表格的列：值全为映射 → 逐子键出列（元数据 children 优先，缺省按值推断）；
    否则单列「值」（控件按样本值推断）。返回 (是否小结构模式, 列描述)。"""
    vals = [v for v in value.values() if v is not None]
    obj_mode = bool(vals) and all(isinstance(v, Mapping) for v in vals)
    cols: List[Dict[str, Any]] = []
    if obj_mode:
        child_meta: Mapping[str, FieldMeta] = (
            dict(fm.children) if fm is not None and fm.children else {})
        keys: List[str] = [str(k) for k in child_meta]
        for v in vals:
            for k in v:
                if str(k) not in keys:
                    keys.append(str(k))
        for k in keys:
            sample = next((v[k] for v in vals if isinstance(v, Mapping) and k in v), None)
            cols.append(_column(k, child_meta.get(k), value=sample))
    else:
        sample = vals[0] if vals else None
        col = _column("value", None, key_label=KV_VALUE_LABEL, value=sample)
        if isinstance(sample, (Mapping, list)):
            # 宽容器（列表/嵌套映射）不做行内编辑，按 JSON 只读展示（不臆造可编辑形态）
            col["control"] = "readonly"
        cols.append(col)
    return obj_mode, cols


def _kv_rows(value: Mapping[str, Any], cols: List[Dict[str, Any]], obj_mode: bool,
             view: "_PackView") -> List[Dict[str, Any]]:
    """键值表格的行：键 + （小结构 → 各列 / 标量 → 单列）；同时给只读 display 与原始值。

    **缺失的子键不进 cells**（只给 display 空串）：编辑后按 cells 重建整表时，缺失键保持
    缺失（不写入 null）——避免把「可选字段未配置」保存成显式 null 触发类型校验。
    """
    out: List[Dict[str, Any]] = []
    for k, v in value.items():
        cells: Dict[str, Any] = {}
        display: Dict[str, str] = {}
        for col in cols:
            if obj_mode:
                present = isinstance(v, Mapping) and col["key"] in v
                raw = v[col["key"]] if present else None
                display[col["key"]] = (
                    _json_text(raw) if isinstance(raw, (Mapping, list))
                    else _scalar_display(raw, col["widget"], view, col["ref_target"]))
                if present:
                    cells[col["key"]] = raw
                continue
            raw = v
            display[col["key"]] = (
                _json_text(raw) if isinstance(raw, (Mapping, list))
                else _scalar_display(raw, col["widget"], view, col["ref_target"]))
            cells[col["key"]] = raw
        out.append({"key": str(k), "cells": cells, "display": display,
                    "value": None if obj_mode else v})
    return out


def _kv_mode(value: Mapping[str, Any]) -> str:
    """键值表格行模式（判定只看值形态，不认字段名）：obj（值全为映射）/ scalar（值全为标量）
    / typed（混杂或含数组 → 逐行按实际类型出控件）。空表 → scalar（与既有行为一致）。"""
    vals = [v for v in value.values() if v is not None]
    if vals and all(isinstance(v, Mapping) for v in vals):
        return "obj"
    if vals and not all(_is_scalarish(v) for v in vals):
        return KV_MODE_TYPED
    return "scalar"


def _kv_typed_rows(value: Mapping[str, Any], fm: Optional[FieldMeta],
                   mmeta: Optional[ModuleMeta], view: "_PackView",
                   depth: int) -> List[Dict[str, Any]]:
    """typed 模式的行：**每行一个字段描述符**（`_descriptor` 复用）——值按实际类型出控件
    （数字/布尔/文本/枚举/引用/数组/对象/嵌套映射），可递归任意层。

    子键有元数据登记时用登记元数据（中文名/枚举/引用目标/范围），未登记键走兜底控件 +
    既有「元数据未登记，按实际值推断」标注。行的 `key` 即映射键，前端据此渲染键单元格。
    """
    child_meta: Mapping[str, FieldMeta] = (
        dict(fm.children) if fm is not None and fm.children else {})
    rows: List[Dict[str, Any]] = []
    for k, v in value.items():
        row = _descriptor(str(k), child_meta.get(str(k)), v, True, mmeta, view, depth + 1)
        if not row.get("display") and isinstance(v, (Mapping, list)):
            row["display"] = _json_text(v)
        rows.append(row)
    return rows


def _kv_table_spec(value: Mapping[str, Any], fm: Optional[FieldMeta],
                   view: "_PackView", mmeta: Optional[ModuleMeta] = None,
                   depth: int = 0) -> Dict[str, Any]:
    """键值表格描述（前端据 control=kvtable 渲染；列/行全来自值形态 + 元数据）。

    · `mode`：obj / scalar（批15 #9 既有）/ typed（批20 A：值类型混杂 → 逐行按实际类型出
      控件，见 `_kv_typed_rows`）；
    · `open_keys`：动态键空间（未登记子字段 / 值里含未登记键）→ 键可改名、可增删行；固定
      schema → 键只读（不臆造键）。
    """
    mode = _kv_mode(value)
    open_keys = _kv_open_keys(fm, value)
    if mode == KV_MODE_TYPED:
        return {
            "mode": KV_MODE_TYPED,
            "columns": [],
            "rows": _kv_typed_rows(value, fm, mmeta, view, depth),
            "row_count": len(value),
            "key_label": KV_KEY_LABEL,
            "value_label": KV_VALUE_LABEL,
            "open_keys": open_keys,
        }
    obj_mode, cols = _kv_columns(value, fm, view)
    return {
        "mode": "obj" if obj_mode else "scalar",
        "columns": cols,
        "rows": _kv_rows(value, cols, obj_mode, view),
        "row_count": len(value),
        "key_label": KV_KEY_LABEL,
        "value_label": KV_VALUE_LABEL,
        # 动态键空间（元数据未登记子字段 / 值含未登记键）→ 键可改名、可增删；固定 schema → 键只读。
        "open_keys": open_keys,
    }


def _curve_spec(value: Mapping[str, Any], fm: Optional[FieldMeta],
                view: "_PackView") -> Dict[str, Any]:
    """曲线控件描述（批15 #2，通用）：键为整数序号、值为数字的映射。

    **单一来源规则（写死）**：曲线对象里的**整数键明细**是框架引擎读取的持久值；
    `use_formula`（缺省 true）只决定编辑器把哪一方当权威——启用时以公式/摘要为准、明细
    仅供查看；关闭后以明细的显式值为准、可直接编辑。编辑器**不会**在两者间互写（无双写打架）：
    开启公式不重算明细，编辑明细前需先关开关。约定键名 `use_formula` / `formula` 属控件契约
    （与 id/name 同级），不是业务字段名。
    """
    flag = value.get(CURVE_FLAG_KEY, True)
    use_formula = flag if isinstance(flag, bool) else True
    raw_formula = value.get(CURVE_FORMULA_KEY, "")
    formula = raw_formula if isinstance(raw_formula, str) else ""
    points: List[Dict[str, Any]] = []
    for k, v in value.items():
        ks = str(k)
        if ks in (CURVE_FLAG_KEY, CURVE_FORMULA_KEY):
            continue
        try:
            level = int(ks)
        except (TypeError, ValueError):
            continue
        points.append({"level": level, "key": ks, "value": v})
    points.sort(key=lambda p: int(p["level"]))
    for p in points:
        p["display"] = _scalar_display(p["value"], "number", view)
    count = len(points)
    if count:
        summary = (f"共 {count} 级 · {points[0]['level']}→{points[0]['display']}"
                   f" · {points[-1]['level']}→{points[-1]['display']}")
    else:
        summary = "暂无明细"
    return {
        "flag_key": CURVE_FLAG_KEY,
        "formula_key": CURVE_FORMULA_KEY,
        "use_formula": use_formula,
        "formula": formula,
        "entries": points,
        "count": count,
        "summary": summary,
        # 公式启用时明细只读（单一来源：避免与公式双写）；关掉后明细可编。
        "detail_editable": not use_formula,
        "note": ("公式与明细单一来源：启用公式时以公式/摘要为准（明细仅供参考）；"
                 "关闭「启用公式」后以明细的显式值为准，可编辑、可增删。"),
    }


def _descriptor(key: str, fm: Optional[FieldMeta], value: object, present: bool,
                mmeta: Optional[ModuleMeta], view: "_PackView", depth: int) -> Dict[str, Any]:
    widget = _effective_widget(fm, value)
    # 批4.6 补：元数据未登记类型（fm=None 或 type 占位为空）→ 按实际值推断，
    # 表单类型 chip 与说明卡同源，不再把数值字段显示成「文本」。
    ftype = fm.type if fm is not None and fm.type else _infer_type(value)
    label = fm.label if fm is not None and fm.label else (key or ftype)
    multiline = bool(getattr(fm, "multiline", False)) if fm is not None else False
    if not multiline and widget == "text":
        multiline = _is_long_text(value)  # 元数据未声明时的兜底（长文本仍给多行控件）
    control = control_for(fm, widget, multiline)
    # 批15 #9 / 批20 A：**动态键空间 / 键值映射**的对象 → 键值表格（不再是每键一个大块表单）。
    # 登记了子字段且键集合完全吻合的对象保持 objform（如 drop_exp / drop_items / stats）。
    if control == "objform" and _obj_kv_tableable(fm, value):
        control = "kvtable"
    # 批15 #2/#9 回归修复：**对象型字段的结构（children / open_keys）与呈现控件解耦**——
    # 表格化 / 曲线化只改呈现，不删结构（一号原则：框架支持的子字段必须仍然可见可编）。
    # 曲线控件会把 widget 由 obj 纠偏为 curve，故按**元数据**判定对象性，保证 exp_curve
    # 这类字段的嵌套 children / 动态键空间标记仍照常输出。
    obj_like = (widget == "obj"
                or (fm is not None and _widget_for_type(fm.type) == "obj"))
    desc: Dict[str, Any] = {
        "key": key,
        "label": label,
        "type": ftype,
        "widget": widget,
        "control": control,
        "editable": is_editable_control(control),
        "multiline": multiline,
        "group": _resolve_group(key, fm, mmeta),
        # 批15 #8：二级分组（折叠子块）——页签之下再分块，长模块首屏只留主要字段。
        "subgroup": _resolve_subgroup(key, fm, mmeta),
        "required": bool(fm.required) if fm is not None else False,
        "present": present,
        "value": value,
        "display": _scalar_display(value, widget, view, _ref_target_of(fm)),
        "ref_target": _ref_target_of(fm),
        "enum": [str(x) for x in fm.enum] if fm is not None and fm.enum else [],
        "number_step": _number_step(ftype),
        "hint": _hint(fm),
        # 批4.6：说明卡（自动拼装 + 人工 help）——前端悬停/点击中文名时展示。
        "unit": fm.unit if fm is not None else "",
        "help": fm.help if fm is not None else "",
        "help_card": help_card(key, fm, value),
        # 批14 #4：元数据未登记子字段 → 兜底控件（按实际值推断）+ 显式标注（一号原则：
        # 框架登记过就按元数据渲染；数据里多出来、框架没登记的键走兜底也不静默）。
        "meta_unregistered": fm is None,
        "meta_note": META_UNREGISTERED_NOTE if fm is None else "",
        "columns": [],
        "rows": [],
    }
    # 批16 #10：定义处默认值（可被引用处覆盖）→ 前端可标注（展示层，不参与校验）。
    # 仅标注字段才出键（不给所有字段加噪音键）。
    if fm is not None and getattr(fm, "overridable_default", False):
        desc["overridable_default"] = True
    # 批18：展示层候选值（enum_options）→ 前端把该字段渲染成下拉（可自由填写的开放词汇
    # 也保留「当前值不在候选内」选项）。仅声明了候选的字段才出键，不参与任何校验判定。
    if fm is not None and getattr(fm, "enum_options", ()):
        desc["enum_options"] = [str(x) for x in fm.enum_options]
    # 批5：条件行 / 键值对表格字段的额外声明（主体/比较符/引用目标；前端据 control 渲染）
    if control == "condition":
        desc["condition"] = condition_spec(fm)
    elif control == "maptable":
        desc["key_ref"] = fm.key_ref if fm is not None else ""
        desc["value_ref"] = fm.value_ref if fm is not None else ""
    if widget == "ref":
        # 批4：引用值是否指向存在的目标（空值不算非法）→ 前端黄提示、不红拦。
        desc["ref_valid"] = _ref_valid(view, _ref_target_of(fm), value)
    if widget == "list":
        # 值缺失/为 null 也要按元数据出列（空列表仍有列头与「+ 添加一行」的默认值）
        rows_val: List[object] = value if isinstance(value, list) else []
        cols = _list_columns(fm, rows_val)
        desc["columns"] = cols
        # 批5.1：任一列是嵌套结构 → 前端改「块状换行」布局（标量成块首行、嵌套各自成块）。
        # 纯标量列表（如全部是引用/数字/文本的 actions）仍用可增删行表格，不走块布局。
        desc["block_layout"] = any(bool(c.get("nested")) for c in cols)
        desc["rows"] = _table_rows(rows_val, cols, view)
        desc["row_count"] = len(rows_val)
        elem = fm.element if fm is not None else None
        if elem is not None and (elem.type == "ref" or elem.options_ref):
            desc["ref_target"] = _ref_target_of(elem)  # 引用多选的候选目标在元素元数据上
        scalar_element = _is_scalar_element(elem, rows_val)
        desc["scalar_element"] = scalar_element
        desc["row_default"] = _row_default(elem, scalar_element)
        # 批4：非法引用标记（黄提示、不红拦）——元素是引用 → 收集非法值；
        # 元素 obj 内引用子字段 → 逐单元格收集（供前端就地把该格标黄）。
        desc["invalid_refs"] = (
            [str(v) for v in rows_val if not _ref_valid(view, _ref_target_of(elem), v)]
            if elem is not None and (elem.type == "ref" or elem.options_ref) else []
        )
        invalid_cells: List[Dict[str, Any]] = []
        if elem is not None and elem.type == "obj" and elem.children:
            for i, row in enumerate(rows_val):
                if not isinstance(row, Mapping):
                    continue
                for ck, cfm in elem.children.items():
                    if cfm.type != "ref" and not cfm.options_ref:
                        continue
                    rv = row.get(str(ck))
                    if not _ref_valid(view, _ref_target_of(cfm), rv):
                        invalid_cells.append(
                            {"row": i, "key": str(ck), "value": rv})
        desc["invalid_cells"] = invalid_cells
        # 批20 A：列表元素的字段描述符（供前端在对象内递归渲染「数组 → 对象」等更深层结构；
        # 判定与控件仍走同一套映射，不新增特例）。深度不额外 +1：element 是列表自身的元素，
        # 不是树里多出来的一层（否则 `_MAX_DEPTH` 会把元素子字段截断成空）。
        elem = fm.element if fm is not None else None
        if elem is not None:
            _sample = next((r for r in rows_val if isinstance(r, Mapping)), None)
            desc["element"] = _descriptor("element", elem, _sample, bool(rows_val),
                                          mmeta, view, depth)
    elif obj_like:
        # 批14 #4：对象子字段**始终**按元数据出（登记了但数据未配置 → 未配置态可填），
        # 再补实际值里多出的键（fm=None → 兜底控件 + 标注）。值缺失/非映射时按空对象渲染。
        child_value = value if isinstance(value, Mapping) else {}
        desc["children"] = _object_children(fm, child_value, mmeta, view, depth + 1)
        # 动态键空间（元数据未登记子字段）→ 前端给「+ 子项 / ✕ 删除」，可增删键；
        # 登记了子字段 → 固定 schema，只渲染登记项，不增删键（不臆造键）。
        desc["open_keys"] = open_keys_of(fm)
    # 呈现层附加（与上面的结构输出**并列**，不是互斥分支）：表格 / 曲线各自带规格。
    if control == "kvtable":
        # 批15 #9 / 批20 A：键值表格（键 → 标量 / 小结构 / 混杂类型）——列/行来自值形态 +
        # 元数据；前端行内编辑，typed 模式逐行按实际类型出控件（可递归）。
        desc["kv_table"] = _kv_table_spec(
            value if isinstance(value, Mapping) else {}, fm, view, mmeta, depth)
    elif control == "curve":
        # 批15 #2：曲线控件（等级 → 数值）——默认公式/摘要行，双击展开明细表。
        desc["curve"] = _curve_spec(
            value if isinstance(value, Mapping) else {}, fm, view)
    if widget == "map" and isinstance(value, Mapping):
        # 批15 #9 回归修复：map 字段表格化（control → kvtable）后，**旧有的 rows 结构仍照常输出**
        # ——表格化只加呈现，不删结构；前端按 control 渲染 kvtable，rows 供既有消费者/对拍口径。
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
    """按声明顺序出字段（缺失也出，标 present=False）；再补实际值里多出的键。

    未配置段（subject = `_UNCONFIGURED` 哨兵）按**空对象**处理：登记字段全部出、present=False，
    既让作者看得见能填，也不把哨兵当成真值展示。批19 #4 的 `_FRAMEWORK_DEFAULT`（框架键
    包未覆盖）同口径处理。
    """
    if subject is _UNCONFIGURED or subject is _FRAMEWORK_DEFAULT:
        subject = {}
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
    if subject is _UNCONFIGURED or subject is _FRAMEWORK_DEFAULT:
        # 批13.1 未配置段：有登记子字段 → 用子字段出表单（patch 键 = 子字段名）；
        # 否则整段作一个字段（标量 / 宽容器），与「新建段」路径（`_new_entry_base`）同口径。
        fm = mmeta.fields.get(entry_id)
        if fm is not None and fm.type == "obj" and fm.children:
            return fm.children
        if etype == "map":
            # 批19 #4：map 模块的框架默认键（包未覆盖）→ 以 value_meta（或该键的逐键
            # 登记）出「整键一值」控件，作者可直接填写并保存为包覆盖。
            vm = mmeta.value_meta
            chosen = fm if fm is not None else vm
            return {entry_id: chosen} if chosen is not None else {}
        return {entry_id: fm} if fm is not None else {}
    if etype == "list":
        return mmeta.fields
    if etype == "map":
        # 批13 C：map 模块的**逐键 schema**（如 formula.json 的 damage/hit/crit 公式段）
        # 优先于统一 value_meta——按 key 命中的 obj 字段登记渲染子字段（展示层）。
        keyed = mmeta.fields.get(entry_id)
        if keyed is not None and keyed.type == "obj" and keyed.children:
            return keyed.children
        vm = mmeta.value_meta
        if vm is not None and vm.type == "obj" and vm.children:
            return vm.children
        # 批19 #9：逐键登记为非 obj（标量 / 公式）→ 用该键自身的元数据（中文名/说明），
        # 缺登记才回落统一 value_meta。纯展示层，不改校验。
        if keyed is not None:
            return {entry_id: keyed}
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


def _entry_open_keys(mmeta: Optional[ModuleMeta], entry_id: object,
                     subject: object) -> bool:
    """条目是否为「动态键空间」（前端给新增/删除子项控件）。

    条件（通用、不认模块名/段名）：对象型模块 + 该段在框架元数据里登记为 `obj` 且
    **未登记子字段** + 段已配置（未配置段走「整段一值」路径，本身已是可编对象）。
    纯展示层：只影响是否给「+ 子项 / ✕ 删除」，不改 type/required/校验。
    """
    if mmeta is None or subject is _UNCONFIGURED or subject is _FRAMEWORK_DEFAULT \
            or not isinstance(subject, Mapping):
        return False
    fm = mmeta.fields.get(str(entry_id))
    if fm is None or fm.type != "obj" or fm.children:
        return False
    # 批15 #2：曲线（整数序号 → 数值）走曲线控件，不算「动态键空间 + 子项增删」。
    return not _is_curve_value(subject)


def _entry_whole_table(mmeta: Optional[ModuleMeta], etype: str,
                       entry_id: str, subject: object) -> bool:
    """条目是否**整体**渲染为单一专门控件（批15 #9/#2，通用、不认模块/段名）。

    · map 模块的合成全表条目（`@table`）——一把看全模块的「键 → 小结构」；
    · 对象模块里「键 → 标量/小结构」的**动态键空间**条目（如 slot_defs / attr_types）——
      当前是每键一个大块表单（objform），改一张紧凑表格；
    · 对象模块里「整数序号 → 数值」的**曲线**条目（如 exp_curve）→ 曲线控件。
    固定 schema 的对象、宽容器不在此列，行为与既有完全一致。
    """
    if entry_id == TABLE_ENTRY_ID and etype == "map":
        return True
    if subject is _UNCONFIGURED or subject is _FRAMEWORK_DEFAULT \
            or not isinstance(subject, Mapping):
        return False
    fm = mmeta.fields.get(str(entry_id)) if mmeta is not None else None
    if fm is None or fm.type != "obj" or fm.children:
        return False
    return _is_dense_map(subject) or _is_curve_value(subject)


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
    mmeta = _module_meta(mod, pack_dir)
    etype = _entry_type(mmeta, data)
    view = _PackView(pack_dir, manifest)
    labels = _display_labels(manifest, declared, pack_dir)
    associations: List[Dict[str, Any]] = []
    # 批19 #4：仅「框架默认键」条目为真；其余路径保持 False（展示层标记，键集不变语义）。
    framework_default = False
    default_note = ""
    page_spec = _find_page(pack_dir, manifest, declared, mod, entry_id)
    if page_spec is not None:
        # 批15 #2：包声明的「合并页」——同一栏里呈现多个顶层段（各自成一个展开子块）。
        sroot: Mapping[str, Any] = data if isinstance(data, Mapping) else {}
        page_label = str(page_spec["label"])
        fields = []
        for seg in page_spec["segments"]:
            sfm = mmeta.fields.get(seg) if mmeta is not None else None
            present = seg in sroot
            d = _descriptor(seg, sfm, sroot.get(seg) if present else None,
                            present, mmeta, view, 0)
            d["group"] = page_label
            d["subgroup"] = (sfm.label if sfm is not None and sfm.label else seg)
            fields.append(d)
        entry_name = page_label
        subject = sroot
        unconfigured = False
        open_keys = False
        groups = [{"name": page_label, "label": page_label, "count": len(fields)}]
        # 合并页里的子块全部展开（一次看全三段）；折叠机制仍可复用（此处不折叠）。
        blocks = _block_plan(fields, mmeta, collapse_named=False)
    elif entry_id == TABLE_ENTRY_ID and etype == "map":
        # 批15 #9：整个条目就是一张键值表（map 模块全表）→ 单字段表格。
        mapdata = data if isinstance(data, Mapping) else {}
        vm = mmeta.value_meta if mmeta is not None else None
        children = (dict(vm.children) if vm is not None and vm.type == "obj"
                    and vm.children else {})
        fm = FieldMeta(type="map", label=TABLE_ENTRY_TAG, children=children)
        entry_name = f"{_module_display_label(mod, labels)} · {TABLE_ENTRY_TAG}"
        subject = mapdata
        unconfigured = False
        fields = [_descriptor(TABLE_ENTRY_ID, fm, mapdata, True, mmeta, view, 0)]
        open_keys = False
        groups = _group_summary(fields, mmeta)
        blocks = _block_plan(fields, mmeta)
    else:
        rows = _entry_rows(data, mmeta)
        match = next((row for row in rows if row[0] == entry_id), None)
        if match is None:
            raise NotFound(f"条目不存在：{mod}/{entry_id}")
        _eid, entry_name, subject = match
        unconfigured = subject is _UNCONFIGURED or subject is _FRAMEWORK_DEFAULT
        framework_default = subject is _FRAMEWORK_DEFAULT
        if framework_default:
            # 批19 #4：框架默认键——条目名用键，附框架侧说明（有则用，无则「键 = 名称」提示）。
            _notes = framework_key_notes(_key_source_of(mmeta))
            default_note = _notes.get(entry_id) or KEY_IS_NAME_NOTE
        else:
            default_note = ""
        if _entry_whole_table(mmeta, etype, entry_id, subject):
            fm = mmeta.fields.get(entry_id) if mmeta is not None else None
            if fm is None:
                fm = FieldMeta(type="obj")
            fields = [_descriptor(entry_id, fm, subject, True, mmeta, view, 0)]
            open_keys = False
        else:
            base = _entry_base(mmeta, etype, entry_id, subject)
            fields = _build_fields(base, subject, mmeta, view, 0)
            open_keys = _entry_open_keys(mmeta, entry_id, subject)
            if open_keys:
                # 动态键空间的每个子项都可删除（前端给「✕」；删除只改草稿，保存走既有链路）。
                for f in fields:
                    f["deletable"] = True
        associations = _association_sections(pack_dir, manifest, declared, entry_id,
                                             subject, mmeta, view)
        groups = _group_summary(fields, mmeta)
        # 批15 #8：二级结构——每个分组下的折叠子块计划（大段默认折叠；字段不消失）。
        blocks = _block_plan(fields, mmeta)
    # 批32 B1：框架关键模板只读——`_FRAMEWORK_DEFAULT`（框架键全集里包未覆盖）条目不可
    # 直接编辑；字段标 `editable=False`，条目带 `framework_locked` 供前端渲染「复制为包覆盖」。
    # 通用机制：只认哨兵，不认任何模块名/模板键名；包覆盖条目（普通数据）不受影响。
    framework_locked = bool(framework_default)
    if framework_locked:
        for f in fields:
            f["editable"] = False
            f["framework_locked"] = True
    return {
        "pack": str(pack),
        "pack_name": str(manifest.get("name", "") or pack),
        "module": mod,
        "module_label": _module_display_label(mod, labels),
        "entry_type": etype,
        "id": entry_id,
        "name": entry_name,
        # 批13.1：本段框架已登记、包数据尚无 → 前端标「未配置 · 框架支持」，字段全为空待填。
        "unconfigured": unconfigured,
        "unconfigured_tag": UNCONFIGURED_TAG,
        # 批19 #4：框架键全集里「包未覆盖」的键 → 前端标「默认（框架）」，保存即写入包覆盖。
        "framework_default": framework_default,
        "framework_default_tag": FRAMEWORK_DEFAULT_TAG,
        "pack_covered_tag": PACK_COVERED_TAG,
        # 批32 B1：框架关键模板只读（仅锁定条目出键；普通条目键集与现状一致）。
        "framework_locked": framework_locked,
        "framework_lock_note": FRAMEWORK_LOCK_NOTE if framework_locked else "",
        "default_note": default_note,
        # 批14 #6①：动态键空间（如 object 段的 obj 字段未登记子字段）→ 前端给「+ 子项 / ✕」。
        "open_keys": open_keys,
        # 批15 #9：整条目键值表格（保存时按「整值键」写回，见 editor_ops._plan）。
        "whole_table": bool(_entry_whole_table(mmeta, etype, entry_id, subject)),
        "table_entry": entry_id == TABLE_ENTRY_ID,
        # 批15 #2：合并页条目（包声明 segment_pages）——同栏呈现多个段。
        "page": page_spec is not None,
        "page_id": entry_id if page_spec is not None else "",
        "page_segments": list(page_spec["segments"]) if page_spec is not None else [],
        "fields": fields,
        "groups": groups,
        "blocks": blocks,
        "associations": associations,
        "association_count": len(associations),
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
    mmeta = _module_meta(mod, pack_dir)
    etype = _entry_type(mmeta, data)
    # 批15 #2：包声明的「合并页」——subject = 整个对象模块数据，补丁键 = 各段名
    # （`_plan` 用整包视图替换该模块；段 id / 数据文件 / 校验路径不变）。
    page_spec = _find_page(pack_dir, manifest, declared, mod, entry_id)
    if page_spec is not None:
        sroot = data if isinstance(data, Mapping) else {}
        base = {seg: (mmeta.fields.get(seg) if mmeta is not None else None)
                or FieldMeta(type="obj") for seg in page_spec["segments"]}
        return {
            "pack_dir": pack_dir,
            "manifest": manifest,
            "declared": declared,
            "module": mod,
            "entry_type": etype,
            "data": data,
            "slot": None,
            "entry_id": entry_id,
            "name": str(page_spec["label"]),
            "subject": sroot,
            "unconfigured": False,
            "open_keys": False,
            "whole": False,
            "page": True,
            "page_segments": list(page_spec["segments"]),
            "base": base,
            "mmeta": mmeta,
        }
    # 批15 #9：map 模块的合成「全表」条目（@table）→ 整模块一把编辑（键值表格）。
    if entry_id == TABLE_ENTRY_ID and etype == "map":
        mapdata = data if isinstance(data, Mapping) else {}
        vm = mmeta.value_meta if mmeta is not None else None
        children = (dict(vm.children) if vm is not None and vm.type == "obj"
                    and vm.children else {})
        fm = FieldMeta(type="map", label=TABLE_ENTRY_TAG, children=children)
        return {
            "pack_dir": pack_dir,
            "manifest": manifest,
            "declared": declared,
            "module": mod,
            "entry_type": etype,
            "data": data,
            "slot": None,
            "entry_id": entry_id,
            "name": TABLE_ENTRY_TAG,
            "subject": mapdata,
            "unconfigured": False,
            "open_keys": False,
            "whole": True,
            "base": {TABLE_ENTRY_ID: fm},
            "mmeta": mmeta,
        }
    rows = _entry_rows(data, mmeta)
    pos = next((i for i, row in enumerate(rows) if row[0] == entry_id), None)
    if pos is None:
        raise NotFound(f"条目不存在：{mod}/{entry_id}")
    _eid, entry_name, subject = rows[pos]
    if isinstance(data, list):
        slot: object = pos
    elif isinstance(data, Mapping):
        slot = entry_id
    else:
        slot = None
    # 批13.1：未配置段写链路——有登记子字段的 object → 从空对象起建（patch 键 = 子字段名）；
    # 其余（标量/列表/无子字段宽容器/引用）→ 整段一值（subject=None，patch 键 = 段名）。
    # 展示口径（base）仍由 `_entry_base` 按哨兵给出，读写两处键集一致。
    unconfigured = subject is _UNCONFIGURED or subject is _FRAMEWORK_DEFAULT
    framework_default = subject is _FRAMEWORK_DEFAULT
    fm = mmeta.fields.get(entry_id) if mmeta is not None else None
    write_subject = subject
    if unconfigured:
        # 批19 #4：map 模块的框架默认键 → 整键一值（subject=None，patch 键 = 键名），
        # 保存后写入包覆盖；object 未配置段沿用「有子字段 → 空对象，否则整段一值」。
        if framework_default and etype == "map":
            write_subject = None
        else:
            write_subject = {} if (fm is not None and fm.type == "obj" and fm.children) else None
    whole = _entry_whole_table(mmeta, etype, entry_id, subject)
    base = _entry_base(mmeta, etype, entry_id, subject)
    open_keys = _entry_open_keys(mmeta, entry_id, subject)
    if whole:
        base = {entry_id: fm if fm is not None else FieldMeta(type="obj")}
        open_keys = False
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
        "subject": write_subject,
        "unconfigured": unconfigured,
        # 批19 #4：框架默认键（包未覆盖）→ 写链路仍按既有「整值键」补丁落盘为包覆盖。
        "framework_default": framework_default,
        # 批14 #6①：动态键空间 → 写链路放行新键（合法性仍由校验器判定；
        # 见 editor_ops._apply_patch 的 open_keys 参数）。
        "open_keys": open_keys,
        # 批15 #9：整条目键值表格 → patch 用「整值键」（见 editor_ops._plan）。
        "whole": whole,
        "base": base,
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


# =====================================================================================
# 批6：新增/删除条目 + ID 生成 + 检索（通用：规则/默认值/引用全部来自元数据）
# =====================================================================================
# ID 建议规则的元数据词表（ModuleMeta.id_rule）：缺省自动，声明了就依声明。
# 批16 #7 口径（用户拍板）：**默认 =「前缀 + 序号」（前缀_001，序号零填充）**；
# 名称能出英文 slug 时不再是默认（包声明 id_rule="slug" 才走 slug）；
# 拼音为**可选附加**（前端「按中文名生成拼音 id」按钮），默认仍前缀 + 序号。
ID_RULE_AUTO = ""              # 自动：默认「前缀 + 递增序号」（与 prefix_seq 同实现）
ID_RULE_SLUG = "slug"          # 名称 → 英文小写 + 下划线（取不出 slug 才回退前缀+序号）
ID_RULE_PREFIX_SEQ = "prefix_seq"  # 前缀 + 递增序号
ID_RULES: Tuple[str, ...] = (ID_RULE_AUTO, ID_RULE_SLUG, ID_RULE_PREFIX_SEQ)
# 生成模式（`suggest_id?mode=`）：缺省前缀+序号；pinyin=按名称拼音（可选附加）。
ID_MODE_PREFIX_SEQ = "prefix_seq"
ID_MODE_PINYIN = "pinyin"
# 序号零填充宽度：与包声明层同一口径（缺省 3 位）。
ID_WIDTH_DEFAULT = pack_meta.ID_WIDTH_DEFAULT
# 新建条目时给非技术用户的人话说明（框架级文案，不含任何业务字段名）。
ID_HINT = ("ID 是内容之间互相引用的名字；默认按「前缀 + 序号」生成（如 item_001），"
           "也可以在名称填好后点「按中文名生成拼音 id」。它在同模块内必须唯一，"
           "生成结果会直接填进输入框，可自由修改，建好后尽量不要改。")
# ID 形态底线（建议而非硬规则）：非空、无空白、无路径分隔符、长度可控。
_ID_SAFE = re.compile(r"^[^\s/\\]{1,128}$")


def slugify(text: object) -> str:
    """名称 → 英文小写 + 下划线 slug（取不出 ASCII 字符时返回空串，**不臆造拼音**）。"""
    parts = re.findall(r"[A-Za-z0-9]+", str(text or ""))
    return "_".join(p.lower() for p in parts)


def _module_prefix(module: str, mmeta: Optional[ModuleMeta]) -> str:
    """ID 前缀（元数据 id_prefix → kind → 模块名，逐级兜底并 slug 归一）。"""
    if mmeta is not None and mmeta.id_prefix:
        return slugify(mmeta.id_prefix) or str(mmeta.id_prefix)
    if mmeta is not None and mmeta.kind:
        return slugify(mmeta.kind) or str(mmeta.kind)
    return slugify(module) or str(module)


def _id_width_of(value: object) -> Optional[int]:
    """序号零填充宽度归一：1..12 的整数；非法/缺省 → None（由调用方走下一级兜底）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 1 <= value <= pack_meta.ID_WIDTH_MAX else None


def id_rule_spec(module: str, mmeta: Optional[ModuleMeta], *,
                 id_prefix: object = "", id_width: object = None) -> Dict[str, Any]:
    """ID 建议规则（界面展示 + 生成用；未声明/不识别 → 自动规则）。

    前缀来源优先级（批16 #7，**包声明优先**）：
      调用方传入（预设声明）> 包 `field_meta.json.id_prefix[模块]` >
      框架 `ModuleMeta.id_prefix` > `ModuleMeta.kind` > 模块名；
    未声明任何一项时由**模块 id 归一推导**（小写 + 非字母数字转下划线）。
    宽度：预设声明 > 包 `id_width[模块]` > 缺省 3 位。
    """
    raw = str(mmeta.id_rule).strip() if mmeta is not None else ""
    rule = raw if raw in ID_RULES else ID_RULE_AUTO
    prefix = slugify(id_prefix) or _module_prefix(module, mmeta)
    width = _id_width_of(id_width)
    return {
        "rule": rule,
        "declared": bool(raw),
        "prefix": prefix,
        "width": width if width is not None else ID_WIDTH_DEFAULT,
        "rules": list(ID_RULES),
    }


def _unique_slug(base: str, used: set) -> str:
    """slug 查重：重复 → `base_2`、`base_3`…（与既有 ID 规则一致）。"""
    if base and base not in used:
        return base
    n = 2
    while f"{base}_{n}" in used:
        n += 1
    return f"{base}_{n}"


def _sequential_id(prefix: str, used: set, width: int) -> str:
    """「前缀 + 递增序号」：取**同前缀现有 id 的最大序号 + 1**，零填充 `width` 位。

    · 序号识别不区分是否零填充（`mat_1` 与 `mat_001` 都算序号 1）；
    · 生成的候选一旦与既有 id 相同 → 继续递增直到唯一（冲突递增）；
    · 序号超过宽度位数时按实际位数输出（不截断）。
    """
    pat = re.compile(r"^" + re.escape(prefix) + r"_(\d+)$")
    mx = 0
    for eid in used:
        m = pat.match(eid)
        if m:
            mx = max(mx, int(m.group(1)))
    n = mx + 1
    while True:
        cand = f"{prefix}_{n:0{width}d}"
        if cand not in used:
            return cand
        n += 1


def suggest_entry_id(module: str, mmeta: Optional[ModuleMeta], name: object,
                     existing_ids: object = (), *, id_prefix: object = "",
                     id_width: object = None) -> str:
    """按规则生成建议 ID（同模块/同命名空间内保证不重复）。

    · 缺省（auto）与 `prefix_seq` → `<前缀>_<递增序号>`（**包声明前缀优先**，零填充 3 位）；
    · `slug` → 名称转英文 slug；重复 → 追加 `_2`、`_3`…；取不出 slug → 回退前缀+序号。
    生成只依赖元数据/包声明与「现有 ID 集合」，不写死任何业务模块/字段名；
    用户仍可在输入框手改——本函数只给**建议值**，不参与校验。
    """
    spec = id_rule_spec(module, mmeta, id_prefix=id_prefix, id_width=id_width)
    used = {str(x) for x in (existing_ids or ()) if str(x)}
    prefix = spec["prefix"] or "entry"
    if spec["rule"] == ID_RULE_SLUG:
        slug = slugify(name)
        if slug:
            return _unique_slug(slug, used)
    return _sequential_id(prefix, used, spec["width"])


def pinyin_available() -> bool:
    """拼音附加能力是否可用（`pypinyin` 可导入）；不可用不算错误，默认路径照常。"""
    try:
        import importlib.util
        return importlib.util.find_spec("pypinyin") is not None
    except Exception:
        return False


def suggest_pinyin_id(module: str, mmeta: Optional[ModuleMeta], name: object,
                      existing_ids: object = (), *, id_prefix: object = "",
                      id_width: object = None) -> Dict[str, Any]:
    """可选附加：按中文名生成拼音 ID（全拼 + 下划线，重复追加 `_2`…）。

    **多音字取常用读音**（pypinyin 列表首项）继续生成，仅在 note 里提示「含多音字，已取
    常用读音；如不对可直接改 ID」——**不整名回落**（ID 透明可改，落回序号会让该功能形同虚设；
    2026-09-15 主 agent 实测修正：此前「精铁锭/重剑/蚀脉猎师」等常见名均被拒）。
    **真正失败**（名称为空 / 未装库 / 转换异常 / 无可转字符）→ 回落「前缀 + 序号」并带明确
    note（不报错、不静默）。返回 {suggested_id, used_pinyin, note}；默认路径永不走这里。
    """
    spec = id_rule_spec(module, mmeta, id_prefix=id_prefix, id_width=id_width)
    used = {str(x) for x in (existing_ids or ()) if str(x)}
    prefix = spec["prefix"] or "entry"
    fallback = _sequential_id(prefix, used, spec["width"])

    def _fallback(note: str) -> Dict[str, Any]:
        return {"suggested_id": fallback, "used_pinyin": False, "note": note}

    text = str(name or "").strip()
    if not text:
        return _fallback("名称为空，已用「前缀 + 序号」。")
    try:
        from pypinyin import Style, pinyin as _pinyin
    except Exception:
        return _fallback("当前环境未安装拼音库（pypinyin），已用「前缀 + 序号」。")
    try:
        # heteronym=True：逐字给出全部读音 → 多于一个即视为多音字（回落并提示）。
        syllables = _pinyin(text, style=Style.NORMAL, heteronym=True)
    except Exception as exc:  # 转换异常 → 回落，不抛给调用方
        return _fallback(f"拼音转换失败（{exc}），已用「前缀 + 序号」。")
    picked: List[str] = []
    polyphonic = False
    for item in syllables:
        opts = [str(x) for x in (item if isinstance(item, list) else [item]) if str(x).strip()]
        if not opts:
            continue
        if len(opts) > 1:
            # 多音字：取**常用读音**（首项）继续生成，只在 note 里提示，不整名回落。
            polyphonic = True
        picked.append(opts[0])
    base = slugify("_".join(picked))
    if not base:
        return _fallback("名称没有可转成拼音的字符，已用「前缀 + 序号」。")
    note = f"按名称拼音生成：{base}"
    if polyphonic:
        note += "（含多音字，已取常用读音；如不对可直接改 ID）"
    return {"suggested_id": _unique_slug(base, used), "used_pinyin": True, "note": note}


def _effective_presets(decl: Optional[pack_meta.PackFieldMeta], module: str
                       ) -> Tuple[Mapping[str, Any], ...]:
    """某模块的**生效预设表**（批17）：框架默认 ∪ 包声明，包关闭的 id 移除。

    · 无包声明（`decl is None`，如空白包）→ 框架默认（条目六种通用品类）仍可用；
    · 同 id → 包声明整体覆盖框架默认；包新 id 追加；`entry_presets_disable` 关闭。
    合并口径见 `qbot_rpg/content/entry_presets.py` docstring（机制通用，不写死模块名）。
    """
    if decl is None:
        return entry_presets_mod.merge_entry_presets(module)
    return entry_presets_mod.merge_entry_presets(
        module,
        decl.entry_presets.get(module, ()),
        decl.entry_presets_disable.get(module, ()),
    )


def _preset_of(decl: Optional[pack_meta.PackFieldMeta], module: str,
               preset: object) -> Optional[Mapping[str, Any]]:
    """按 id 取**生效预设**（框架默认 ∪ 包声明；无/未命中 → None）；机制通用，不写死模块名。"""
    pid = str(preset or "").strip()
    if not pid:
        return None
    for item in _effective_presets(decl, module):
        if str(item.get("id") or "") == pid:
            return item
    return None


def _pack_id_policy(decl: Optional[pack_meta.PackFieldMeta], module: str,
                    preset: object = "") -> Dict[str, Any]:
    """从**生效预设** / 包声明解析某模块（或某预设）的 ID 前缀/宽度口径；未声明 → 空/None。"""
    item = _preset_of(decl, module, preset)
    if item is not None:
        return {"id_prefix": str(item.get("id_prefix") or ""),
                "id_width": _id_width_of(item.get("id_width"))}
    if decl is None:
        return {"id_prefix": "", "id_width": None}
    return {"id_prefix": decl.id_prefix.get(module, ""),
            "id_width": _id_width_of(decl.id_width.get(module))}


def _id_scope_modules(module: str, mmeta: Optional[ModuleMeta],
                      declared: List[str], table: FieldMetaTable) -> List[str]:
    """ID 唯一性作用域：本模块 + 同命名空间兄弟模块（与校验器 R-5 口径一致）。"""
    mods = [module]
    if mmeta is not None and mmeta.namespace:
        for m in table.namespaces.get(mmeta.namespace, ()):  # 命名空间成员（元数据声明）
            if m in declared and m not in mods:
                mods.append(m)
    return mods


def _id_entries(pack_dir: Path, manifest: Mapping[str, Any], module: str,
                mmeta: Optional[ModuleMeta], table: FieldMetaTable
                ) -> List[Tuple[str, str, str]]:
    """作用域内已有条目 → [(模块, ID, 名称)]（唯一性即时校验的数据源，只读）。"""
    declared = _declared_modules(manifest)
    out: List[Tuple[str, str, str]] = []
    for m in _id_scope_modules(module, mmeta, declared, table):
        data = _read_json(pack_dir / f"{m}.json")
        mm = table.module(m)
        for eid, name, _val in _entry_rows(data, mm):
            out.append((m, eid, name))
    return out


def suggest_id(pack: object, module: object, root: Optional[object] = None,
               name: object = None, mode: object = None,
               preset: object = None) -> Dict[str, Any]:
    """建议 ID（`/…/suggest_id?name=…&mode=…&preset=…`）：名称 → 规则 → 不重复的建议 ID。

    · 默认（`mode` 缺省 / prefix_seq）→ 包声明前缀 + 序号（零填充；见 `suggest_entry_id`）；
    · `mode=pinyin` → **可选附加**：按中文名生成拼音 id；未装库/多音字/失败 → 回落
      前缀+序号并在 `note` 里**明确提示**（不报错）；
    · `preset` 指定时用该预设声明的 id_prefix/id_width（**生效预设** = 框架默认 ∪ 包声明，见
      `qbot_rpg/content/entry_presets.py`；预设 > 包 `id_prefix` > 框架兜底）。
    """
    pack_dir = _pack_dir(pack, root)
    manifest = _manifest(pack_dir)
    mod = declared_module(pack, module, root=root)
    table = _pack_meta_table(pack_dir)
    mmeta = table.module(mod)
    decl = _pack_declaration(pack_dir)
    policy = _pack_id_policy(decl, mod, preset)
    existing = {eid for _m, eid, _n in _id_entries(pack_dir, manifest, mod, mmeta, table)}
    requested = str(mode or "").strip()
    used_pinyin = False
    note = ""
    if requested == ID_MODE_PINYIN:
        picked = suggest_pinyin_id(mod, mmeta, name, existing, **policy)
        suggested = str(picked["suggested_id"])
        used_pinyin = bool(picked["used_pinyin"])
        note = str(picked["note"])
    else:
        suggested = suggest_entry_id(mod, mmeta, name, existing, **policy)
        requested = ID_MODE_PREFIX_SEQ
    return {
        "pack": str(pack), "module": mod,
        "suggested_id": suggested,
        "id_rule": id_rule_spec(mod, mmeta, **policy),
        "id_hint": ID_HINT,
        "existing_count": len(existing),
        "mode": requested,
        "pinyin_available": pinyin_available(),
        "used_pinyin": used_pinyin,
        "note": note,
        "preset": str(preset or ""),
    }


def check_entry_id(pack: object, module: object, entry_id: object,
                   root: Optional[object] = None,
                   meta: Optional[FieldMetaTable] = None) -> Dict[str, Any]:
    """新增条目的 ID 即时校验（只读）：空/非法 → 红；同模块或同命名空间重复 → 红。"""
    pack_dir = _pack_dir(pack, root)
    manifest = _manifest(pack_dir)
    table = meta if meta is not None else _pack_meta_table(pack_dir)
    mod = declared_module(pack, module, root=root)
    mmeta = table.module(mod)
    eid = str(entry_id or "").strip()
    labels = _display_labels(manifest, _declared_modules(manifest), pack_dir)

    def _out(ok: bool, level: str, message: str, how: str,
             conflicts: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        return {"pack": str(pack), "module": mod, "entry_id": eid, "ok": ok,
                "level": level, "status": "red" if not ok else "ok",
                "conflicts": conflicts or [], "message": message,
                "how_to_fix": how, "id_hint": ID_HINT}

    if not eid:
        return _out(False, "red", "ID 不能为空：请填写一个本模块内唯一的标识。",
                    "建议用英文小写 + 下划线（如 sword_aura）；点「按名称生成」可自动取一个。")
    if not _ID_SAFE.match(eid):
        return _out(False, "red", f"ID「{eid}」含空格、斜杠或超长字符，不能用作条目标识。",
                    "请改用不含空格与斜杠的短标识（建议英文小写 + 下划线）。")
    conflicts = [
        {"module": m, "module_label": _module_display_label(m, labels), "id": e, "name": n}
        for m, e, n in _id_entries(pack_dir, manifest, mod, mmeta, table) if e == eid
    ]
    if conflicts:
        where = "、".join(
            f"{c['module_label']}「{c['name']}」" if c["module"] != mod
            else f"本模块「{c['name']}」" for c in conflicts)
        return _out(
            False, "red", f"ID「{eid}」已被占用（{where}），同模块/同命名空间内不能重复。",
            "换一个 ID，或点「按名称生成」让编辑器按规则取一个不重复的。", conflicts)
    return _out(True, "ok", f"ID「{eid}」可用。", "")


def entry_index(pack: object, root: Optional[object] = None) -> Dict[str, Any]:
    """全包条目索引（跨模块检索 + ID 即时唯一性校验的数据源；只读）。

    出参按模块分组：{module, label, entry_type, namespace, count, entries:[{id,name}]}。
    编辑器据此在前端本地过滤（纯前端检索，不逐键请求后端）。
    """
    pack_dir = _pack_dir(pack, root)
    manifest = _manifest(pack_dir)
    declared = _declared_modules(manifest)
    labels = _display_labels(manifest, declared, pack_dir)
    table = _pack_meta_table(pack_dir)
    # 批19 #8：条目级层级挂载——索引与条目列表同口径（移走类改归父节点，全局检索仍可命中）。
    _merge_map, _merge_notes = _entry_merge_map(manifest, declared, pack_dir)
    _tree_mounts, tree_mounted, tree_moved_out, _tree_notes = _entry_tree_plan(
        manifest, declared, pack_dir, _merge_map, labels)
    # 批20 B：按条件过滤的并入——索引与条目列表同口径（目标模块的 count 含并入条目）。
    _mf_specs, _mf_notes = _entry_merge_filtered_specs(manifest, declared, pack_dir)
    mf_specs_by_target: Dict[str, List[Dict[str, Any]]] = {}
    for _spec in _mf_specs:
        mf_specs_by_target.setdefault(str(_spec["target"]), []).append(_spec)
    modules: List[Dict[str, Any]] = []
    total = 0
    for mod in declared:
        data = _read_json(pack_dir / f"{mod}.json")
        mmeta = table.module(mod)
        etype = _entry_type(mmeta, data)
        ns = (mmeta.namespace if mmeta is not None and mmeta.namespace else mod)
        rows = [r for r in _entry_rows(data, mmeta)
                if r[0] not in tree_moved_out.get(mod, set())]
        entries = [_entry_brief(eid, name, val) for eid, name, val in rows]
        # 批19 #8：移到本模块下的条目一并进索引（count 与 list_entries 一致）。
        for item in tree_mounted.get(mod, []):
            if item["keep_top_level"]:
                continue
            _frm, _eid = str(item["from"]), str(item["id"])
            _srows = _entry_rows(_read_json(pack_dir / f"{_frm}.json"),
                                 table.module(_frm))
            _hit = next((r for r in _srows if r[0] == _eid), None)
            if _hit is None:
                continue
            _b = _entry_brief(_hit[0], _hit[1], _hit[2])
            _b["mounted_from"] = _frm
            _b["mounted_from_label"] = _module_display_label(_frm, labels)
            entries.append(_b)
        # 批20 B：按条件过滤的并入条目也进索引（count 与 list_entries 一致；带来源标注）。
        _mf_rows, _mf_secs = _entry_merge_filtered_rows(
            pack_dir, declared, labels, mod, mf_specs_by_target.get(mod, []))
        for _eid, _nm, _val, _frm, _spec in _mf_rows:
            _b = _entry_brief(_eid, _nm, _val)
            _b["merged_from"] = _frm
            _b["merged_from_label"] = _module_display_label(_frm, labels)
            _b["merge_filtered"] = True
            entries.append(_b)
        # 批13.1：未配置段的计数口径与 `list_entries` 一致（全局检索也覆盖未配置段）。
        unc = sum(1 for e in entries if e.get("unconfigured"))
        total += len(entries)
        modules.append({
            "module": mod, "label": _module_display_label(mod, labels), "entry_type": etype,
            "namespace": ns, "count": len(entries),
            "configured_count": len(entries) - unc, "unconfigured_count": unc,
            "entries": entries,
        })
    # 批13 A（一号原则）：包未启用的框架模块也纳入全局检索候选（若有保留数据 → 可搜到；
    # 无数据 → 空组不影响结果）。**不改 `modules`/`total`**：换包验收与 ID 口径按声明集，
    # 未启用模块另置 available 键（前端检索时一并扫描；写入仍走各自模块链路）。
    available: List[Dict[str, Any]] = []
    declared_set = set(declared)
    for entry in FRAMEWORK_MODULE_CATALOG:
        mod = entry.module
        if mod in declared_set:
            continue
        data = _read_json(pack_dir / f"{mod}.json")
        mmeta = table.module(mod)
        etype = _entry_type(mmeta, data)
        ns = (mmeta.namespace if mmeta is not None and mmeta.namespace else mod)
        rows = _entry_rows(data, mmeta)
        entries = [_entry_brief(eid, name, val) for eid, name, val in rows]
        available.append({
            "module": mod, "label": labels.get(mod) or entry.label,
            "entry_type": etype, "namespace": ns,
            "count": len(entries), "entries": entries,
            "enabled": False, "implemented": bool(entry.implemented),
        })
    return {"pack": str(pack), "pack_name": str(manifest.get("name", "") or pack),
            "modules": modules, "available": available, "total": total,
            "meta_source": META_SOURCE}


def _new_entry_base(mmeta: Optional[ModuleMeta], etype: str, entry_id: str,
                    id_field: str) -> Mapping[str, FieldMeta]:
    """新建条目的可编辑字段基表（list 排除 ID 键：ID 在新建界面单独渲染）。"""
    base = _entry_base(mmeta, etype, entry_id, None)
    if etype == "list":
        return {k: v for k, v in base.items() if str(k) != id_field}
    return base


def _new_entry_defaults(mmeta: Optional[ModuleMeta], etype: str, entry_id: str,
                        id_field: str,
                        preset_defaults: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """新条目初始值：其余字段按元数据 default 初始化（缺省无 default → 不写该键）。

    批16 #11：`preset_defaults` = 所选预设声明的初始值，叠加在元数据默认值之上
    （预设 > 字段元数据默认值）；ID 键一律以本次新建的 entry_id 为准。
    """
    out: Dict[str, Any] = {}
    if mmeta is None:
        return out
    if etype == "list":
        for k, fm in mmeta.fields.items():
            if str(k) == id_field:
                continue
            if fm.default is not None:
                out[str(k)] = copy.deepcopy(fm.default)
        for k, v in (preset_defaults or {}).items():
            if str(k) != id_field:
                out[str(k)] = copy.deepcopy(v)
        out[id_field] = entry_id
    else:
        kids: Mapping[str, FieldMeta] = {}
        if etype == "map" and mmeta.value_meta is not None and mmeta.value_meta.children:
            kids = mmeta.value_meta.children
        elif etype == "object":
            fm = mmeta.fields.get(entry_id)
            if fm is not None and fm.children:
                kids = fm.children
        for k, cfm in kids.items():
            if cfm.default is not None:
                out[str(k)] = copy.deepcopy(cfm.default)
        for k, v in (preset_defaults or {}).items():
            out[str(k)] = copy.deepcopy(v)
    return out


def new_entry_slot(pack: object, module: object, entry_id: object = "",
                   root: Optional[object] = None,
                   preset: object = "") -> Dict[str, Any]:
    """新建条目的定位/默认值/字段基表（写链路与新建界面共用；只读）。

    `preset` = **生效预设**（框架默认 ∪ 包声明，批17）的 id；缺省/未命中 → 与现状完全一致：
    命中时把该预设的 `defaults` 叠加到初始值上（写链路与新建界面同源，保证落盘一致）。
    """
    pack_dir = _pack_dir(pack, root)
    manifest = _manifest(pack_dir)
    mod = declared_module(pack, module, root=root)
    data = _read_json(pack_dir / f"{mod}.json")
    table = _pack_meta_table(pack_dir)
    mmeta = table.module(mod)
    decl = _pack_declaration(pack_dir)
    preset_item = _preset_of(decl, mod, preset)
    etype = _entry_type(mmeta, data)
    id_field = (mmeta.id_field if mmeta is not None and mmeta.id_field else _ID_FIELD)
    eid = str(entry_id or "").strip()
    if not eid and etype == "object":
        present = {str(k) for k in data} if isinstance(data, Mapping) else set()
        declared_fields = mmeta.fields if mmeta is not None else {}
        remaining = [str(k) for k in declared_fields if k not in present]
        eid = remaining[0] if remaining else ""
    base = _new_entry_base(mmeta, etype, eid, id_field)
    # 新条目在模块里的「槽位」：list=追加后的下标，map/object=键。写链路据此把
    # 校验红拦/黄提示的作用域收敛到新条目自身（否则 list 模块会把全模块其他条目的黄提示
    # 都算成「相关」——批2 的 _scope_prefix 语义）。
    if etype == "list":
        slot: object = len(data) if isinstance(data, list) else None
    elif etype in ("map", "object"):
        slot = eid
    else:
        slot = None
    return {
        "pack_dir": pack_dir, "manifest": manifest, "module": mod,
        "entry_type": etype, "data": data, "mmeta": mmeta,
        "id_field": id_field, "entry_id": eid, "base": base, "slot": slot,
        "preset_item": preset_item,
        "subject": _new_entry_defaults(
            mmeta, etype, eid, id_field,
            (preset_item or {}).get("defaults") if preset_item else None),
    }


def new_entry_detail(pack: object, module: object, root: Optional[object] = None,
                     name: object = None, entry_id: object = None,
                     preset: object = None) -> Dict[str, Any]:
    """新建条目界面数据（`/…/module/{m}/new`）：建议 ID + 默认值字段 + 分组 + 预设。

    `preset` = **生效预设**（框架默认 ∪ 包声明；批16 #11 / 批17）的 id；缺省/未命中 → 与现状一致：
    · 建议 ID 用该预设声明的 id_prefix/id_width；
    · 初始值叠加该预设 `defaults`；
    · `presets` 列出本模块**生效预设**（框架默认 ∪ 包声明 − 关闭；无 → 空数组，前端不出现预设栏）。
      批17 起框架自带条目通用默认预设（`qbot_rpg/content/entry_presets.py`），空白包同样可用。
    """
    pack_dir = _pack_dir(pack, root)
    manifest = _manifest(pack_dir)
    declared = _declared_modules(manifest)
    table = _pack_meta_table(pack_dir)
    decl = _pack_declaration(pack_dir)
    info = new_entry_slot(pack, module, entry_id or "", root=root, preset=preset)
    mod = info["module"]
    mmeta: Optional[ModuleMeta] = info["mmeta"]
    etype = info["entry_type"]
    id_field = info["id_field"]
    prefill = str(info["entry_id"] or "")
    existing = {eid for _m, eid, _n in _id_entries(pack_dir, manifest, mod, mmeta, table)}
    policy = _pack_id_policy(decl, mod, preset)
    suggested = str(entry_id or "").strip() or prefill or suggest_entry_id(
        mod, mmeta, name, existing, **policy)
    base = info["base"]
    subject = dict(info["subject"])
    subject.pop(id_field, None)  # ID 单独渲染，不混进字段网格
    view = _PackView(pack_dir, manifest)
    # 批16 #11：选了预设 → 只把该预设关心的字段放主区；其余字段归「其他字段」折叠区
    # （**仍可编辑**，不永久隐藏——一号原则）。不选预设 → 行为与现状完全一致。
    # 批17：主区字段顺序按预设声明的 `fields` 顺序（`preset_base` 按 wanted 顺序建）。
    preset_item = info.get("preset_item")
    missing: List[str] = []
    if preset_item is not None:
        wanted = [str(k) for k in preset_item.get("fields", ())]
        wanted_set = set(wanted)
        id_key = str(id_field)
        preset_base = {k: base[k] for k in wanted if k in base and k != id_key}
        other_base = {k: v for k, v in base.items()
                      if str(k) not in wanted_set and str(k) != id_key}
        missing = [k for k in wanted if k != id_key and k not in base]
        # 各分区只喂自己那份值（否则 `_build_fields` 会把另一区的值当成「多出的键」重复渲染）。
        fields = _build_fields(
            preset_base, {k: subject[k] for k in preset_base if k in subject},
            mmeta, view, 0)
        other_fields = _build_fields(
            other_base, {k: subject[k] for k in other_base if k in subject},
            mmeta, view, 0)
        # 预设 defaults 里模块未登记的键 → 兜底控件（如实呈现，不静默丢弃）。
        stray = {k: v for k, v in subject.items()
                 if k not in base and str(k) != id_key}
        if stray:
            other_fields += _build_fields({}, stray, mmeta, view, 0)
    else:
        fields = _build_fields(base, subject, mmeta, view, 0)
        other_fields = []
    groups = _group_summary(fields, mmeta)
    blocks = _block_plan(fields, mmeta)
    labels = _display_labels(manifest, declared, pack_dir)
    preset_items = _effective_presets(decl, mod)
    id_fm = None
    if mmeta is not None:
        id_fm = mmeta.fields.get(id_field)
    return {
        "pack": str(pack),
        "pack_name": str(manifest.get("name", "") or pack),
        "module": mod,
        "module_label": _module_display_label(mod, labels),
        "entry_type": etype,
        "is_new": True,
        "id_field": id_field,
        "id_field_label": (id_fm.label if id_fm is not None and id_fm.label else id_field),
        "suggested_id": suggested,
        "id_rule": id_rule_spec(mod, mmeta, **policy),
        "id_hint": ID_HINT,
        "can_create": bool(suggested) or etype in ("list", "map"),
        "name_field": _NAME_FIELD,
        "fields": fields,
        "groups": groups,
        "blocks": blocks,
        "field_count": len(fields) + len(other_fields),
        "group_count": len(groups),
        # 批16 #7/#11：拼音附加能力 + 预设清单（不声明预设 → 空数组，界面与现状一致）。
        "pinyin_available": pinyin_available(),
        "preset": str(preset or ""),
        "presets": [
            {"id": str(p["id"]), "label": str(p["label"]),
             "help": str(p.get("help") or ""), "field_count": len(p["fields"])}
            for p in preset_items
        ],
        # 选了预设时：其余字段 + 未命中的声明字段（如实标注，不静默）。
        "other_fields": other_fields,
        "other_field_count": len(other_fields),
        "preset_field_count": len(fields),
        "preset_help": str((preset_item or {}).get("help") or "") if preset_item else "",
        "preset_missing_fields": missing,
        "associations": [],
        "association_count": 0,
        "meta_source": META_SOURCE,
    }


def _ref_kind_matches(ref_target: object, kinds: set) -> bool:
    """引用目标的 kind 是否指向被删模块（未标注目标也算：字段类型是 ref 即视为引用）。"""
    t = str(ref_target or "")
    if not t:
        return True
    if t in kinds:
        return True
    if t.endswith("_or_any") and t[: -len("_or_any")] in kinds:
        return True
    return False


def _collect_ref_hits(value: object, fm: Optional[FieldMeta], path: str,
                      target_id: str, kinds: set,
                      out: List[Dict[str, Any]], *, match_all: bool = False) -> None:
    """沿字段元数据递归找「引用字段命中」（键名不写死，全按元数据下钻）。

    · `target_id`：要匹配的条目标识；`match_all=True` → 不按值过滤，收集**全部**引用命中
      （批32 C1：未使用批量判定一次算完，复用同一条元数据遍历，不另造扫描）；
    · 引用字段口径：`type=ref`，或**非容器字段但声明了 `ref_target`**（既有展示层引用
      标注，如 str + ref_target；与 `_collect_target_hits` 同源）。
    """
    if fm is None:
        if isinstance(value, Mapping):
            for k, v in value.items():
                _collect_ref_hits(v, None, f"{path}.{k}" if path else str(k), target_id,
                                  kinds, out, match_all=match_all)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                _collect_ref_hits(v, None, f"{path}[{i}]", target_id, kinds, out,
                                  match_all=match_all)
        return
    if fm.type == "ref" or (fm.type not in ("obj", "list", "map") and _ref_target_of(fm)):
        if (match_all or str(value) == target_id) \
                and (match_all or _ref_kind_matches(_ref_target_of(fm) or "", kinds)):
            out.append({"path": path, "value": value, "ref_target": _ref_target_of(fm) or ""})
        return
    if fm.type == "list":
        if isinstance(value, list):
            for i, v in enumerate(value):
                _collect_ref_hits(v, fm.element, f"{path}[{i}]", target_id, kinds, out,
                                  match_all=match_all)
        return
    if fm.type == "obj":
        if isinstance(value, Mapping):
            for k, v in value.items():
                child = fm.children.get(str(k)) if fm.children else None
                _collect_ref_hits(v, child, f"{path}.{k}" if path else str(k),
                                  target_id, kinds, out, match_all=match_all)
        return
    if fm.type == "map":
        if isinstance(value, Mapping):
            for k, v in value.items():
                _collect_ref_hits(v, fm.element, f"{path}.{k}" if path else str(k),
                                  target_id, kinds, out, match_all=match_all)


def reference_scan(pack: object, module: object, entry_id: object,
                   root: Optional[object] = None,
                   meta: Optional[FieldMetaTable] = None) -> List[Dict[str, Any]]:
    """「谁引用了这个条目」扫描（删除前人话列出引用者；只读，不写盘）。

    两个数据源都来自元数据声明，编辑器不写死模块/字段名：
      ① 各模块字段元数据里 type=ref 的字段（含列表/对象/映射内递归）；
      ② 各模块 ModuleMeta.associations 声明指向本模块的外键路径（含列表通配）。
    """
    pack_dir = _pack_dir(pack, root)
    manifest = _manifest(pack_dir)
    table = meta if meta is not None else _pack_meta_table(pack_dir)
    declared = _declared_modules(manifest)
    mod = declared_module(pack, module, root=root)
    target_mmeta = table.module(mod)
    kinds = {mod}
    if target_mmeta is not None:
        if target_mmeta.kind:
            kinds.add(str(target_mmeta.kind))
        if target_mmeta.namespace:
            kinds.add(str(target_mmeta.namespace))
    labels = _display_labels(manifest, declared, pack_dir)
    tgt = str(entry_id)
    out: List[Dict[str, Any]] = []
    seen: set = set()

    for rel_mod in declared:
        rel_mmeta = table.module(rel_mod)
        rel_data = _read_json(pack_dir / f"{rel_mod}.json")
        rel_etype = _entry_type(rel_mmeta, rel_data)
        for eid, ename, subject in _entry_rows(rel_data, rel_mmeta):
            local: List[Dict[str, Any]] = []
            base = _entry_base(rel_mmeta, rel_etype, eid, subject)
            if isinstance(subject, Mapping):
                for k, v in subject.items():
                    _collect_ref_hits(v, base.get(str(k)), str(k), tgt, kinds, local)
            # 声明式外键路径（可能不是 ref 类型字段）：按关联声明再扫一遍
            if rel_mmeta is not None:
                for a in rel_mmeta.associations:
                    if a.module != mod or not a.field:
                        continue
                    for p, v in _walk_path(subject, a.field):
                        if str(v) == tgt:
                            local.append({"path": p, "value": v, "ref_target": ""})
            for h in local:
                path = str(h.get("path") or "")
                key = (rel_mod, eid, path)
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "module": rel_mod,
                    "module_label": _module_display_label(rel_mod, labels),
                    "entry_id": eid,
                    "entry_name": ename,
                    "field": path,
                    "field_label": _path_field_label(rel_mmeta, path),
                    "value": str(h.get("value")),
                })
    out.sort(key=lambda r: (str(r["module"]), str(r["entry_name"]), str(r["entry_id"]),
                            str(r["field"])))
    return out


def _collect_target_hits(value: object, fm: Optional[FieldMeta], path: str,
                         target: str, out: List[Dict[str, Any]]) -> None:
    """沿字段元数据递归找「引用目标 == target 的字段值」（含 options_ref 展示层引用）。

    与 `_collect_ref_hits` 同源但按**目标命名空间**匹配（不要求 type=ref）——批14 #6 的
    `items.slot`（type=str + options_ref="settings.slot_defs"）据此纳入引用扫描。
    """
    if fm is None:
        return
    tgt = _ref_target_of(fm)
    if tgt == target and fm.type not in ("obj", "list", "map"):
        if isinstance(value, str) and value:
            out.append({"path": path, "value": value})
        return
    if fm.type == "list" and isinstance(value, list):
        for i, v in enumerate(value):
            _collect_target_hits(v, fm.element, f"{path}[{i}]", target, out)
    elif fm.type == "obj" and isinstance(value, Mapping):
        for k, v in value.items():
            child = fm.children.get(str(k)) if fm.children else None
            _collect_target_hits(v, child, f"{path}.{k}" if path else str(k), target, out)
    elif fm.type == "map" and isinstance(value, Mapping):
        for k, v in value.items():
            _collect_target_hits(v, fm.element, f"{path}.{k}" if path else str(k), target, out)


def ref_holders(pack: object, target: object, keys: Optional[object] = None,
                root: Optional[object] = None,
                meta: Optional[FieldMetaTable] = None) -> List[Dict[str, Any]]:
    """列出全包中「引用了命名空间 `target`」的字段（只读；批14 #6③ 删除部位后提示引用者）。

    数据源 = 各模块字段元数据的展示层引用目标（`_ref_target_of`：options_ref 优先于
    ref_target），递归下钻列表/对象/映射。`keys` 非空时只收值命中这些键的引用者。
    返回按模块/条目排序的 [{module, module_label, entry_id, entry_name, field,
    field_label, value}]，供保存/校验链路的黄提示（不硬拦）。
    """
    pack_dir = _pack_dir(pack, root)
    manifest = _manifest(pack_dir)
    table = meta if meta is not None else _pack_meta_table(pack_dir)
    declared = _declared_modules(manifest)
    tgt = str(target or "")
    wanted = {str(k) for k in keys} if keys else None
    labels = _display_labels(manifest, declared, pack_dir)
    out: List[Dict[str, Any]] = []
    for rel_mod in declared:
        rel_mmeta = table.module(rel_mod)
        if rel_mmeta is None:
            continue
        rel_data = _read_json(pack_dir / f"{rel_mod}.json")
        rel_etype = _entry_type(rel_mmeta, rel_data)
        for eid, ename, subject in _entry_rows(rel_data, rel_mmeta):
            local: List[Dict[str, Any]] = []
            base = _entry_base(rel_mmeta, rel_etype, eid, subject)
            if isinstance(subject, Mapping):
                for k, v in subject.items():
                    _collect_target_hits(v, base.get(str(k)), str(k), tgt, local)
            for h in local:
                if wanted is not None and str(h.get("value")) not in wanted:
                    continue
                out.append({
                    "module": rel_mod,
                    "module_label": _module_display_label(rel_mod, labels),
                    "entry_id": eid,
                    "entry_name": ename,
                    "field": str(h.get("path") or ""),
                    "field_label": _path_field_label(rel_mmeta, str(h.get("path") or "")),
                    "value": str(h.get("value")),
                })
    out.sort(key=lambda r: (str(r["module"]), str(r["entry_name"]), str(r["entry_id"]),
                            str(r["field"])))
    return out


# =====================================================================================
# 批32 C1（框架 §6.12-08）：条目级「📍未使用」角标——批量一次算完（不新增扫描机制）
# =====================================================================================
#: 条目级未使用角标文案（前端按稳定标记取；后端只给标记与 id 集合）。
UNUSED_TAG = "📍未使用"


def _collect_ref_targets(fm: Optional[FieldMeta], out: set) -> None:
    """递归收集字段元数据里声明的引用目标（`_ref_target_of`：options_ref 优先 ref_target）。"""
    if fm is None:
        return
    if fm.type == "ref" or (fm.type not in ("obj", "list", "map") and _ref_target_of(fm)):
        t = _ref_target_of(fm)
        if t:
            out.add(str(t))
    if fm.type == "list":
        _collect_ref_targets(fm.element, out)
    elif fm.type == "obj":
        for child in (fm.children or {}).values():
            _collect_ref_targets(child, out)
    elif fm.type == "map":
        _collect_ref_targets(fm.element, out)


def pack_unused(pack: object, root: Optional[object] = None,
                meta: Optional[FieldMetaTable] = None) -> Dict[str, Any]:
    """全包条目级未使用标记（`/api/pack/{pack}/unused`；只读）。

    **复用既有引用扫描**（`_collect_ref_hits`，与 `/entry/{m}/{id}/refs` 的
    `reference_scan` 同一元数据遍历；`match_all` 一次收集全包引用），不另造扫描。
    返回 ``{pack, modules: {mod: {unused:[id...], count, total}}, total, unused_tag}``：
      · 只给**有声明引用目标且数据里至少有 1 条声明引用命中**的模块出角标
        （引用面多由未登记即席字符串引用构成的模块整体不出，避免误标「全部未使用」）；
      · 框架默认键 / 未配置段 / map 合成全表条目不算条目内容，跳过；
      · **提示不拦截**：仅展示层标记，不改任何校验/保存判定。
    """
    pack_dir = _pack_dir(pack, root)
    manifest = _manifest(pack_dir)
    declared = _declared_modules(manifest)
    table = meta if meta is not None else _pack_meta_table(pack_dir)
    ref_targets: set = set()
    assoc_targets: set = set()
    for rel_mod in declared:
        rm = table.module(rel_mod)
        if rm is None:
            continue
        for fm in (rm.fields or {}).values():
            _collect_ref_targets(fm, ref_targets)
        if rm.value_meta is not None:
            _collect_ref_targets(rm.value_meta, ref_targets)
        for a in rm.associations:
            if a.module:
                assoc_targets.add(str(a.module))
    # 一次遍历：全包引用命中（ref_target, value）；associations 记为 @assoc:<目标模块>。
    hits: List[Tuple[str, str]] = []
    for rel_mod in declared:
        rm = table.module(rel_mod)
        rd = _read_json(pack_dir / f"{rel_mod}.json")
        re = _entry_type(rm, rd)
        for eid, _name, subject in _entry_rows(rd, rm):
            if not isinstance(subject, Mapping):
                continue
            base = _entry_base(rm, re, eid, subject)
            for k, v in subject.items():
                local: List[Dict[str, Any]] = []
                _collect_ref_hits(v, base.get(str(k)), str(k), "", set(), local,
                                  match_all=True)
                for h in local:
                    val = str(h.get("value"))
                    if val:
                        hits.append((str(h.get("ref_target") or ""), val))
            if rm is not None:
                for a in rm.associations:
                    if not a.field or not a.module:
                        continue
                    for _p, v in _walk_path(subject, a.field):
                        if isinstance(v, str) and v:
                            hits.append((f"@assoc:{a.module}", v))
    modules_out: Dict[str, Any] = {}
    for mod in declared:
        mm = table.module(mod)
        kinds = {mod}
        if mm is not None:
            if mm.kind:
                kinds.add(str(mm.kind))
            if mm.namespace:
                kinds.add(str(mm.namespace))
        if mod not in assoc_targets and not any(
                _ref_kind_matches(t, kinds) for t in ref_targets):
            continue
        data = _read_json(pack_dir / f"{mod}.json")
        etype = _entry_type(mm, data)
        rows = [(eid, name, subj) for eid, name, subj in _entry_rows(data, mm)
                if subj is not _UNCONFIGURED and subj is not _FRAMEWORK_DEFAULT
                and not (eid == TABLE_ENTRY_ID and etype == "map")]
        if not rows:
            continue
        used: set = set()
        for t, val in hits:
            if t.startswith("@assoc:"):
                if t[len("@assoc:"):] == mod:
                    used.add(val)
            elif _ref_kind_matches(t, kinds):
                used.add(val)
        # 保守显示口径：该模块**至少有 1 条声明引用在数据里真实命中**才出角标。
        # 若一条都没命中，说明该模块的引用面多由未登记的即席字符串引用构成（框架只对
        # 声明面负责）→ 整体不出角标，宁可不提示也不误标「全部未使用」。
        if not used:
            continue
        unused = sorted(eid for eid, _n, _s in rows if eid not in used)
        modules_out[mod] = {"unused": unused, "count": len(unused), "total": len(rows)}
    return {
        "pack": str(pack),
        "modules": modules_out,
        "total": sum(int(m["count"]) for m in modules_out.values()),
        "unused_tag": UNUSED_TAG,
    }


__all__ = [
    "DEFAULT_GROUP",
    "EDIT_CONTROLS",
    "ID_HINT",
    "ID_RULES",
    "ID_RULE_AUTO",
    "ID_RULE_PREFIX_SEQ",
    "ID_RULE_SLUG",
    "ID_MODE_PINYIN",
    "ID_MODE_PREFIX_SEQ",
    "ID_WIDTH_DEFAULT",
    "META_SOURCE",
    "BadRequest",
    "EditorError",
    "Forbidden",
    "NotFound",
    "check_entry_id",
    "content_root",
    "condition_rows",
    "condition_spec",
    "condition_value",
    "control_for",
    "control_of",
    "declared_module",
    "editable_form",
    "entry_detail",
    "entry_index",
    "entry_slot",
    "field_meta_table",
    "id_rule_spec",
    "is_editable_control",
    "is_editable_widget",
    "list_control",
    "list_entries",
    "list_modules",
    "list_packs",
    "load_pack_modules",
    "new_entry_detail",
    "new_entry_slot",
    "open_keys_of",
    "readonly_form",
    "ref_holders",
    "ref_options",
    "reference_scan",
    "pack_unused",
    "UNUSED_TAG",
    "repo_root",
    "slugify",
    "suggest_entry_id",
    "suggest_pinyin_id",
    "pinyin_available",
    "suggest_id",
]
