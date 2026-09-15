"""包展示元数据读取层（`content/<包>/field_meta.json` → 与框架表合并的通用入口）。

依据：`docs/编辑器重写_数据包展示元数据下放方案.md`
  · §三 目标结构：包内 `field_meta.json`（纯 JSON）承载**包专属展示元数据**；
  · §四 批 A：本文件是「读包声明 → 与框架 `field_meta.py` 表合并」的通用入口；
  · §四 批 B：展示文案已真正下放——框架只保留结构，包声明承载 label/help/组显示名；
  · §二 优先级：**包声明 > 框架兜底**——`field_labels` / `field_help` / `group_labels`
    覆盖框架同键值，未声明键保持框架现状。

`field_meta.json` 形态（schema_version = 1，纯 JSON，未知顶层键/形态非法 → 明确报错）：

    {
      "schema_version": 1,
      "module_labels": {"skills": "技能"},
      "module_tree":   [{"module": "items", "children": ["equipment"]}],
      "field_labels":  {"skills": {"power": "威力",
                                   "level": {"_label": "等级", "max": "最大等级"}}},
      "field_help":    {"skills": {"power": "技能倍率，按百分比算。",
                                   "effects": {"_help": "效果表", "type": "类型"}}},
      "group_labels":  {"enemies": {"base": "基本"}},
      "entry_merge":   {"settings": ["stats", "formula"]},
      "id_prefix":     {"items": "material"},
      "id_width":      {"items": 3},
      "entry_presets": {"items": [{"id": "material", "label": "材料",
                                   "fields": ["name", "desc"],
                                   "defaults": {"type": "material"},
                                   "id_prefix": "material"}]},
      "entry_presets_disable": {"items": ["gift_box"]}
    }

`field_labels` / `field_help` 的值可为**非空字符串**（叶子）或**嵌套对象**（含 `_label`/`_help`
节点文案 + 子键递归）；这是批A「扁平键表」的严格超集（旧包只写字符串仍合法）。

优先级细则（与文档同步）：
  · `module_labels` / `module_tree` 属**包级**声明：manifest 里已有同名字段（现状由包声明），
    本文件若也声明则以 **field_meta.json 为准**（`module_labels` 逐键覆盖 manifest，
    `module_tree` 整体替换 manifest 的 `module_tree`/`module_groups`）；
  · `field_labels` / `field_help` / `group_labels` 属**模块级**声明：覆盖框架表同模块同键值，
    未声明键保持框架现状；包为框架未登记的字段声明标签/说明时，补一个 `soft_label`
    纯展示字段（泛型校验短路，零行为变化），声明未覆盖到的字段仍走原兜底；
  · `entry_merge` 属**展示层聚合**声明（批12 #1）：把来源模块的**条目列表**并入目标模块的
    条目列表展示（中栏按来源模块分小节），来源模块默认不再左栏单列。形态：
    `{"<目标模块>": ["<来源模块>", ...]}`（简写，来源不保留单列）或
    `{"<目标模块>": {"sources": [...], "keep_top_level": [...]}}`（保留单列的来源同时出现在
    左栏与聚合视图）。**数据文件 / 模块 id / 加载与校验路径全部不动**——被并入条目的
    编辑与保存仍路由回其所属模块（校验 / 原子写 / 回备用各自的模块链路）。
    被并入模块仍出现在模块树（带 `merged_into` 标记），左栏是否单列由前端按 `keep_top_level`
    决定，`editor_verify_packs.py` 的「模块树 / 条目索引 / 包列表」三处口径保持不变。
  · `id_prefix` / `id_width` / `entry_presets` 属**包级展示/生成声明**（批16 #7 / #11）：
    - `id_prefix`（对象<模块名, 非空字符串>）：新建条目「前缀 + 序号」ID 的前缀来源
      （**包声明优先**；未声明 → 框架 ModuleMeta.id_prefix / kind / 模块名逐级兜底）；
    - `id_width`（对象<模块名, 正整数>）：序号零填充宽度（缺省 3；上限 12）；
    - `entry_presets`（对象<模块名, 预设数组>）：新建条目的「预设（模板）」——
      预设项 = `{id, label, help?, fields, defaults?, id_prefix?, id_width?}`，
      `fields` = 关心的字段键（其余字段进「其他字段」折叠区仍可编辑）、
      `defaults` = 初始值、`id_prefix`/`id_width` = 该预设下的 ID 生成口径。
      **纯新建界面/生成声明**：不改数据文件、不改校验语义；不声明 → 行为与现状完全一致。
      批17 起框架自带**通用默认预设**（`qbot_rpg/content/entry_presets.py`，本次 = 物品六种），
      生效预设 = **框架默认 ∪ 包声明**：同 id 包声明整体覆盖框架默认、包可追加、包可关闭；
      空白包也自带框架默认（合并与关闭口径的权威说明见 `entry_presets.py` docstring）。
    - `entry_presets_disable`（对象<模块名, 非空字符串数组>，批17）：**关闭**该模块下
      指定 id 的预设（框架默认或包自己的），被点名的 id 从生效表移除；这里只校验形态，
      「id 是否真的存在」由合并层按实际预设表过滤（关闭不存在的 id = 无害空操作）。

本模块只依赖 `qbot_rpg.content.models`（零 web 依赖，框架可独立使用）；解析严格、
合并纯函数（不改动传入的框架表），读取按文件 mtime/size/inode 缓存。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

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
    # 批20 C：**二级分组显示名**（模块 → 子分组键 → 中文名）——覆盖框架默认子分组显示名
    # （框架已声明结构：`ModuleMeta.field_subgroups` / `subgroup_order`）。纯展示层。
    "subgroup_labels",
    "entry_merge",
    # 批15 #2：对象模块的「合并页」声明——把若干顶层段合成一个页面展示（纯展示层；
    # 数据文件 / 段 id / 校验路径不动；保存时补丁按键写回同一对象）。
    "segment_pages",
    # 批16 #7/#11：ID 前缀/宽度 + 条目预设（模板）——新建界面的生成与展示声明，
    # 不改数据/校验；不声明 → 与现状完全一致。
    "id_prefix",
    "id_width",
    "entry_presets",
    # 批17：关闭框架默认（或包自己的）条目预设——`{"<模块>": ["<预设 id>", ...]}`。
    "entry_presets_disable",
    # 批19 #8：条目级层级声明——把某模块内的段/条目挂到另一个父节点之下（左栏从
    # 「模块级」扩展到「条目级」）；纯展示层，数据文件 / 段 id / 校验路径全不动。
    "entry_tree",
    # 批20 B：**按条件过滤的条目并入**声明——把某模块里满足条件的条目标签式地并入目标模块
    # 的条目列表展示（装备页 = 自身条目 ∪ items 里带 slot 的条目）。纯展示层：数据文件 /
    # 条目 id / 校验路径全不动，编辑仍写回来源模块。
    "entry_merge_filtered",
    # 批20 C：**中栏条目分组**声明——按某字段取值（或 ID 前缀）把长列表折成可折叠小节；
    # 纯展示层，不声明时行为与现状一致。
    "entry_groups",
)

# 序号零填充宽度：缺省 3 位、上限 12 位（防声明出超长 ID；仅影响建议 ID，不参与校验）。
ID_WIDTH_DEFAULT = 3
ID_WIDTH_MAX = 12


class PackFieldMetaError(ValueError):
    """包声明 `field_meta.json` 形态非法（人话：指出包名与哪个键错）。"""


@dataclass(frozen=True)
class PackFieldMeta:
    """一份通过严格校验的包展示元数据声明（原始值，不含合并结果）。"""

    pack: str
    module_labels: Mapping[str, str]
    module_tree: Any  # None（未声明）| list | Mapping（与 manifest module_tree 同形态）
    field_labels: Mapping[str, Any]   # 值 = str | 嵌套对象（含 _label / 子键）
    field_help: Mapping[str, Any]     # 值 = str | 嵌套对象（含 _help / 子键）
    group_labels: Mapping[str, Mapping[str, str]]
    # 批20 C：二级分组显示名（模块 → 子分组键 → 中文名）——覆盖框架默认（结构归框架）。
    subgroup_labels: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    # entry_merge（批12 #1，展示层聚合）：目标模块 → {"sources": [...], "keep_top_level": [...]}。
    # 语义 = 把 sources 的条目并入目标的条目列表展示；数据/模块 id/校验路径不变。
    entry_merge: Mapping[str, Mapping[str, Tuple[str, ...]]] = field(default_factory=dict)
    # segment_pages（批15 #2，展示层合并页）：模块 → 页面数组；每页 = {id,label,segments,help}。
    # 语义 = 把对象模块的若干顶层段合成一个「页面」展示（中栏一条、右栏同栏多子块）；
    # 数据/段 id/校验路径不变——保存仍按键写回该对象模块。
    segment_pages: Mapping[str, Tuple[Mapping[str, Any], ...]] = field(default_factory=dict)
    # id_prefix / id_width（批16 #7）：模块 → ID 前缀 / 序号零填充宽度（仅影响建议 ID 生成）。
    id_prefix: Mapping[str, str] = field(default_factory=dict)
    id_width: Mapping[str, int] = field(default_factory=dict)
    # entry_presets（批16 #11）：模块 → 预设数组；每项 = {id,label,help,fields,defaults,
    # id_prefix,id_width}（新建按模板初始化 + 收窄显示面；不改数据/校验）。
    entry_presets: Mapping[str, Tuple[Mapping[str, Any], ...]] = field(default_factory=dict)
    # entry_presets_disable（批17）：模块 → 要关闭的预设 id 元组（框架默认或包自己的）；
    # 生效预设由 entry_presets.merge_entry_presets 计算（框架默认 ∪ 包声明 − 关闭）。
    entry_presets_disable: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
    # entry_tree（批19 #8，展示层条目级层级）：挂载数组；每项 =
    #   {"parent": <父节点>, "sections": ({"from": <来源模块>, "id": <条目 id>}, …),
    #    "keep_top_level": bool}
    # 语义 = 把「来源模块」的指定条目挂到父节点之下；默认从原处移走（`keep_top_level=True`
    # 或父节点是虚拟聚合视图时保留原位，做纯显示挂载）。编辑器读取层按包实际声明与
    # 框架登记过滤；数据文件 / 条目 id / 校验路径全不动（编辑仍写回来源模块）。
    entry_tree: Tuple[Mapping[str, Any], ...] = ()
    # entry_merge_filtered（批20 B，按条件过滤的并入）：声明数组，每项 =
    #   {"target": <目标模块>, "from": <来源模块>, "has": (<必须有值的键>, …),
    #    "eq": {<键>: <值>, …}}
    # 语义 = 把「来源模块」里满足全部条件（has 全中 + eq 全等）的条目并入**目标模块的条目
    # 列表**展示；条目带来源标注，点开编辑仍写回来源模块。数据/条目 id/校验路径不动。
    entry_merge_filtered: Tuple[Mapping[str, Any], ...] = ()
    # entry_groups（批20 C，中栏条目分组）：模块 → 分组规则 =
    #   {"by": "field" | "id_prefix", "field": <键>, "labels": {...},
    #    "other_label": "其他", "collapsed": bool}
    # 语义 = 中栏长列表按分组折成可折叠小节（默认展开首节）。纯展示层，不参与校验。
    entry_groups: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


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
    """校验「对象<模块名, 对象<字段键, 非空字符串>>」形态（group_labels 用）。"""
    raw = _require_map(value, pack, key)
    out: Dict[str, Dict[str, str]] = {}
    for mod, body in raw.items():
        if not isinstance(mod, str) or not mod:
            raise _fail(pack, key, f"含非法模块名（应为非空字符串）：{mod!r}")
        out[mod] = _str_map(body, pack, f"{key}.{mod}")
    return out


def _display_map(value: object, pack: str, key: str) -> Dict[str, Any]:
    """校验「对象<模块名, 展示表>」形态；展示表支持**嵌套 children**。

    展示表的一项 = 非空字符串（叶子中文名/说明）| 嵌套对象；嵌套对象里保留键
    `_label`（本节点中文名）/`_help`（本节点说明），其余键递归同形态。这是批A
    「扁平键表」的严格超集（旧包只写字符串仍然合法）。
    """
    raw = _require_map(value, pack, key)
    out: Dict[str, Any] = {}
    for mod, body in raw.items():
        if not isinstance(mod, str) or not mod:
            raise _fail(pack, key, f"含非法模块名（应为非空字符串）：{mod!r}")
        out[mod] = _display_node_map(body, pack, f"{key}.{mod}")
    return out


def _display_node_map(value: object, pack: str, key: str) -> Dict[str, Any]:
    raw = _require_map(value, pack, key)
    out: Dict[str, Any] = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not k:
            raise _fail(pack, key, f"含非法键（键应为非空字符串）：{k!r}")
        if k in ("_label", "_help"):
            if not isinstance(v, str) or not v:
                raise _fail(pack, key, f"保留键 {k} 的值应为非空字符串，实际是{_type_name(v)}")
            out[k] = v
        elif isinstance(v, str):
            if not v:
                raise _fail(pack, key, f"键 {k} 的值应为非空字符串，实际是空串")
            out[k] = v
        elif isinstance(v, Mapping):
            out[k] = _display_node_map(v, pack, f"{key}.{k}")
        else:
            raise _fail(pack, key,
                        f"键 {k} 的值应为非空字符串或嵌套对象，实际是{_type_name(v)}")
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


def _str_list(value: object, pack: str, key: str) -> Tuple[str, ...]:
    """校验「非空字符串数组（元素互不重复）」。"""
    if not isinstance(value, list):
        raise _fail(pack, key, f"应为字符串数组，实际是{_type_name(value)}")
    out: list = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise _fail(pack, key, f"元素应为非空字符串，实际是{item!r}")
        if item in out:
            raise _fail(pack, key, f"元素重复：{item}")
        out.append(item)
    return tuple(out)


def _validate_entry_merge(value: object, pack: str, key: str
                          ) -> Dict[str, Dict[str, Tuple[str, ...]]]:
    """entry_merge 形态校验并归一化（批12 #1）。

    允许两种写法（形态归一后统一为 `{"sources": (…), "keep_top_level": (…)}`）：
      · 简写：`{"<目标>": ["<来源>", …]}`（来源默认不保留单列）；
      · 完整：`{"<目标>": {"sources": [...], "keep_top_level": [...]}}`。
    约束：目标/来源必须是非空字符串且互不相同（目标不能并入自身）；`keep_top_level`
    必须是 `sources` 的子集；只允许 `sources` / `keep_top_level` 两个键（防写法漂移）。
    这里只校验**形态**；「模块是否在 manifest 声明」由编辑器读取层按包实际声明过滤。
    """
    raw = _require_map(value, pack, key)
    out: Dict[str, Dict[str, Tuple[str, ...]]] = {}
    for target, spec in raw.items():
        if not isinstance(target, str) or not target:
            raise _fail(pack, key, f"含非法目标模块名（应为非空字符串）：{target!r}")
        if isinstance(spec, Mapping):
            unknown = [str(k) for k in spec if k not in ("sources", "keep_top_level")]
            if unknown:
                raise _fail(pack, f"{key}.{target}",
                            f"含未知键：{'、'.join(unknown)}；只允许 sources / keep_top_level")
            if "sources" not in spec:
                raise _fail(pack, f"{key}.{target}", "缺少 sources（应为来源模块数组）")
            sources = _str_list(spec["sources"], pack, f"{key}.{target}.sources")
            keep = _str_list(spec.get("keep_top_level", []), pack,
                             f"{key}.{target}.keep_top_level")
        else:
            sources = _str_list(spec, pack, f"{key}.{target}")
            keep = ()
        if target in sources:
            raise _fail(pack, f"{key}.{target}", "目标模块不能并入自身")
        for k in keep:
            if k not in sources:
                raise _fail(pack, f"{key}.{target}.keep_top_level",
                            f"元素 {k} 不在 sources 内（保留单列的模块必须先被并入）")
        out[target] = {"sources": sources, "keep_top_level": keep}
    return out


def _validate_segment_pages(value: object, pack: str, key: str
                            ) -> Dict[str, Tuple[Mapping[str, Any], ...]]:
    """`segment_pages` 形态校验并归一化（批15 #2）。

    形态：`{"<模块>": [{"id": "...", "label": "...", "segments": ["<段>", ...], "help": "..."}]}`。
    约束：模块/页面 id/label/段均为非空字符串；segments 非空且互不重复；同模块内页面 id 唯一；
    只允许 id/label/segments/help 四个键（防写法漂移）。这里只校验**形态**；「模块/段是否真存在」
    由编辑器读取层按框架登记与包实际数据过滤。
    """
    raw = _require_map(value, pack, key)
    out: Dict[str, Tuple[Mapping[str, Any], ...]] = {}
    for mod, pages in raw.items():
        if not isinstance(mod, str) or not mod:
            raise _fail(pack, key, f"含非法模块名（应为非空字符串）：{mod!r}")
        if not isinstance(pages, list) or not pages:
            raise _fail(pack, f"{key}.{mod}", "应为非空页面数组")
        seen_ids: set = set()
        norm: list = []
        for i, page in enumerate(pages):
            where = f"{key}.{mod}[{i}]"
            if not isinstance(page, Mapping):
                raise _fail(pack, where, f"应为对象，实际是{_type_name(page)}")
            unknown = [str(k) for k in page
                       if k not in ("id", "label", "segments", "help")]
            if unknown:
                raise _fail(pack, where,
                            f"含未知键：{'、'.join(unknown)}；只允许 id / label / segments / help")
            pid = page.get("id")
            label = page.get("label")
            if not isinstance(pid, str) or not pid:
                raise _fail(pack, where, f"id 应为非空字符串，实际是{pid!r}")
            if pid in seen_ids:
                raise _fail(pack, where, f"页面 id 重复：{pid}")
            if not isinstance(label, str) or not label:
                raise _fail(pack, where, f"label 应为非空字符串，实际是{label!r}")
            segs = _str_list(page.get("segments"), pack, f"{where}.segments")
            help_text = page.get("help", "")
            if help_text is not None and not isinstance(help_text, str):
                raise _fail(pack, where, "help 应为字符串")
            seen_ids.add(pid)
            norm.append({"id": pid, "label": label, "segments": segs,
                         "help": str(help_text or "")})
        out[mod] = tuple(norm)
    return out


def _validate_id_prefix_map(value: object, pack: str, key: str) -> Dict[str, str]:
    """`id_prefix` 形态：对象<模块名, 非空字符串>（批16 #7，仅影响建议 ID 生成）。"""
    return _str_map(value, pack, key)


def _validate_id_width_map(value: object, pack: str, key: str) -> Dict[str, int]:
    """`id_width` 形态：对象<模块名, 正整数 1..ID_WIDTH_MAX>（序号零填充宽度）。"""
    raw = _require_map(value, pack, key)
    out: Dict[str, int] = {}
    for mod, width in raw.items():
        if not isinstance(mod, str) or not mod:
            raise _fail(pack, key, f"含非法模块名（应为非空字符串）：{mod!r}")
        if isinstance(width, bool) or not isinstance(width, int):
            raise _fail(pack, key,
                        f"模块 {mod} 的宽度应为整数，实际是{_type_name(width)}")
        if not (1 <= width <= ID_WIDTH_MAX):
            raise _fail(pack, key,
                        f"模块 {mod} 的宽度应在 1..{ID_WIDTH_MAX}，实际是 {width}")
        out[mod] = width
    return out


def _validate_entry_presets(value: object, pack: str, key: str
                            ) -> Dict[str, Tuple[Mapping[str, Any], ...]]:
    """`entry_presets` 形态校验并归一化（批16 #11，新建条目「预设 / 模板」）。

    形态：`{"<模块>": [{"id": ..., "label": ..., "help": ..., "fields": [...],
    "defaults": {...}, "id_prefix": ..., "id_width": ...}]}`。
    约束：模块/预设 id/label 非空；同模块内预设 id 唯一；`fields` 非空字符串数组且不重复；
    `defaults` 为对象；`id_prefix` 非空字符串；`id_width` 为 1..ID_WIDTH_MAX 的整数；
    只允许上述七个键（防写法漂移）。这里只校验**形态**；「字段键是否真存在」由编辑器
    读取层按模块实际字段过滤并如实标注（不静默）。
    """
    allowed = ("id", "label", "help", "fields", "defaults", "id_prefix", "id_width")
    raw = _require_map(value, pack, key)
    out: Dict[str, Tuple[Mapping[str, Any], ...]] = {}
    for mod, presets in raw.items():
        if not isinstance(mod, str) or not mod:
            raise _fail(pack, key, f"含非法模块名（应为非空字符串）：{mod!r}")
        if not isinstance(presets, list) or not presets:
            raise _fail(pack, f"{key}.{mod}", "应为非空预设数组")
        seen_ids: set = set()
        norm: list = []
        for i, preset in enumerate(presets):
            where = f"{key}.{mod}[{i}]"
            if not isinstance(preset, Mapping):
                raise _fail(pack, where, f"应为对象，实际是{_type_name(preset)}")
            unknown = [str(k) for k in preset if k not in allowed]
            if unknown:
                raise _fail(pack, where,
                            f"含未知键：{'、'.join(unknown)}；只允许 {' / '.join(allowed)}")
            pid = preset.get("id")
            label = preset.get("label")
            if not isinstance(pid, str) or not pid:
                raise _fail(pack, where, f"id 应为非空字符串，实际是{pid!r}")
            if pid in seen_ids:
                raise _fail(pack, where, f"预设 id 重复：{pid}")
            if not isinstance(label, str) or not label:
                raise _fail(pack, where, f"label 应为非空字符串，实际是{label!r}")
            help_text = preset.get("help", "")
            if help_text is not None and not isinstance(help_text, str):
                raise _fail(pack, where, "help 应为字符串")
            fields = _str_list(preset.get("fields"), pack, f"{where}.fields")
            if not fields:
                raise _fail(pack, f"{where}.fields", "应为非空字段键数组（预设关心的字段）")
            defaults = preset.get("defaults", {})
            if not isinstance(defaults, Mapping):
                raise _fail(pack, f"{where}.defaults",
                            f"应为对象，实际是{_type_name(defaults)}")
            id_prefix = preset.get("id_prefix", "")
            if id_prefix is not None and not isinstance(id_prefix, str):
                raise _fail(pack, f"{where}.id_prefix", "应为字符串")
            id_width = preset.get("id_width")
            if id_width is not None:
                if isinstance(id_width, bool) or not isinstance(id_width, int):
                    raise _fail(pack, f"{where}.id_width",
                                f"应为整数，实际是{_type_name(id_width)}")
                if not (1 <= id_width <= ID_WIDTH_MAX):
                    raise _fail(pack, f"{where}.id_width",
                                f"应在 1..{ID_WIDTH_MAX}，实际是 {id_width}")
            seen_ids.add(pid)
            norm.append({
                "id": pid, "label": label, "help": str(help_text or ""),
                "fields": fields, "defaults": dict(defaults),
                "id_prefix": str(id_prefix or ""),
                "id_width": id_width,
            })
        out[mod] = tuple(norm)
    return out


def _validate_entry_presets_disable(value: object, pack: str, key: str
                                    ) -> Dict[str, Tuple[str, ...]]:
    """`entry_presets_disable` 形态校验并归一化（批17，关闭指定预设）。

    形态：`{"<模块>": ["<预设 id>", ...]}`；模块名非空；数组元素为非空字符串且不重复。
    这里只校验**形态**；「被关闭的 id 是否真的存在」由合并层按实际预设表过滤（关闭
    不存在的 id = 无害空操作，不报错）。
    """
    raw = _require_map(value, pack, key)
    out: Dict[str, Tuple[str, ...]] = {}
    for mod, ids in raw.items():
        if not isinstance(mod, str) or not mod:
            raise _fail(pack, key, f"含非法模块名（应为非空字符串）：{mod!r}")
        out[mod] = _str_list(ids, pack, f"{key}.{mod}")
    return out


def _validate_entry_tree(value: object, pack: str, key: str
                         ) -> Tuple[Mapping[str, Any], ...]:
    """`entry_tree` 形态校验并归一化（批19 #8，条目级层级挂载）。

    形态：数组，每项 `{"parent": "<父节点>", "sections": [{"from": "<来源模块>",
    "id": "<条目 id>"}, …], "keep_top_level": <bool>?}`（简写：`sections` 项也接受
    `"<来源模块>.<条目 id>"` 字符串）。约束：
      · 每项只允许 parent / sections / keep_top_level 三个键（防写法漂移）；
      · parent / from / id 均为非空字符串；sections 非空；
      · 同一 (from, id) 不可在同一项内重复；
    这里只校验**形态**；「父节点/来源模块是否在 manifest 声明、条目 id 是否真存在」
    由编辑器读取层按包实际声明与框架登记过滤（不悬空、不报错）。
    """
    if not isinstance(value, list):
        raise _fail(pack, key, f"应为数组，实际是{_type_name(value)}")
    out: list = []
    for i, mount in enumerate(value):
        where = f"{key}[{i}]"
        if not isinstance(mount, Mapping):
            raise _fail(pack, where, f"应为对象，实际是{_type_name(mount)}")
        unknown = [str(k) for k in mount
                   if k not in ("parent", "sections", "keep_top_level")]
        if unknown:
            raise _fail(pack, where,
                        f"含未知键：{'、'.join(unknown)}；"
                        "只允许 parent / sections / keep_top_level")
        parent = mount.get("parent")
        if not isinstance(parent, str) or not parent:
            raise _fail(pack, where, f"parent 应为非空字符串，实际是{parent!r}")
        raw_sections = mount.get("sections")
        if not isinstance(raw_sections, list) or not raw_sections:
            raise _fail(pack, f"{where}.sections", "应为非空数组")
        sections: list = []
        seen: set = set()
        for j, sec in enumerate(raw_sections):
            swhere = f"{where}.sections[{j}]"
            if isinstance(sec, str) and sec:
                frm, _dot, eid = sec.partition(".")
            elif isinstance(sec, Mapping):
                unknown_s = [str(k) for k in sec if k not in ("from", "id")]
                if unknown_s:
                    raise _fail(pack, swhere,
                                f"含未知键：{'、'.join(unknown_s)}；只允许 from / id")
                frm, eid = sec.get("from"), sec.get("id")
            else:
                raise _fail(pack, swhere,
                            f"应为对象（或 \"<来源>.<条目>\" 字符串），实际是{_type_name(sec)}")
            if not isinstance(frm, str) or not frm:
                raise _fail(pack, swhere, f"from 应为非空字符串，实际是{frm!r}")
            if not isinstance(eid, str) or not eid:
                raise _fail(pack, swhere, f"id 应为非空字符串，实际是{eid!r}")
            if (frm, eid) in seen:
                raise _fail(pack, swhere, f"重复挂载同一条目：{frm}.{eid}")
            seen.add((frm, eid))
            sections.append({"from": frm, "id": eid})
        keep = mount.get("keep_top_level", False)
        if not isinstance(keep, bool):
            raise _fail(pack, where, f"keep_top_level 应为布尔，实际是{_type_name(keep)}")
        out.append({"parent": parent, "sections": tuple(sections), "keep_top_level": keep})
    return tuple(out)


def _validate_entry_merge_filtered(value: object, pack: str, key: str
                                   ) -> Tuple[Mapping[str, Any], ...]:
    """`entry_merge_filtered` 形态校验并归一化（批20 B，按条件过滤的条目并入）。

    形态：数组，每项 `{"target": "<目标模块>", "from": "<来源模块>",
    "where": {"has": ["<键>", …], "eq": {"<键>": <标量>, …}}}`（`where` 可省略 = 全部并入）。
    约束：
      · 每项只允许 target / from / where 三个键（防写法漂移）；
      · target / from 为非空字符串，且不得相同；
      · `where` 只允许 has / eq 两个键；has 为非空字符串数组（不重复）；eq 为非空对象且
        值必须是标量（字符串 / 数字 / 布尔）——「等值」条件不支持深结构比较，避免写法歧义；
      · 条件可组合：has 与 eq 同时给出 = 全部满足（AND）。
    这里只校验**形态**；「模块是否在 manifest 声明」由编辑器读取层按包实际声明过滤。
    """
    if not isinstance(value, list) or not value:
        raise _fail(pack, key, f"应为非空数组，实际是{_type_name(value)}")
    out: List[Mapping[str, Any]] = []
    for i, spec in enumerate(value):
        where = f"{key}[{i}]"
        if not isinstance(spec, Mapping):
            raise _fail(pack, where, f"应为对象，实际是{_type_name(spec)}")
        unknown = [str(k) for k in spec if k not in ("target", "from", "where")]
        if unknown:
            raise _fail(pack, where,
                        f"含未知键：{'、'.join(unknown)}；只允许 target / from / where")
        target = spec.get("target")
        frm = spec.get("from")
        if not isinstance(target, str) or not target:
            raise _fail(pack, where, f"target 应为非空字符串，实际是{target!r}")
        if not isinstance(frm, str) or not frm:
            raise _fail(pack, where, f"from 应为非空字符串，实际是{frm!r}")
        if target == frm:
            raise _fail(pack, where, "target 与 from 不能相同（不得并入自身）")
        raw_where = spec.get("where", {})
        if raw_where is None:
            raw_where = {}
        if not isinstance(raw_where, Mapping):
            raise _fail(pack, f"{where}.where", f"应为对象，实际是{_type_name(raw_where)}")
        unknown_w = [str(k) for k in raw_where if k not in ("has", "eq")]
        if unknown_w:
            raise _fail(pack, f"{where}.where",
                        f"含未知键：{'、'.join(unknown_w)}；只允许 has / eq")
        has = _str_list(raw_where.get("has", []), pack, f"{where}.where.has") \
            if "has" in raw_where else ()
        raw_eq = raw_where.get("eq", {})
        if not isinstance(raw_eq, Mapping):
            raise _fail(pack, f"{where}.where.eq", f"应为对象，实际是{_type_name(raw_eq)}")
        eq: Dict[str, Any] = {}
        for ek, ev in raw_eq.items():
            if not isinstance(ek, str) or not ek:
                raise _fail(pack, f"{where}.where.eq",
                            f"含非法键（应为非空字符串）：{ek!r}")
            if ev is None or isinstance(ev, (Mapping, list)):
                raise _fail(pack, f"{where}.where.eq.{ek}",
                            f"等值条件的值应为标量（字符串 / 数字 / 布尔），"
                            f"实际是{_type_name(ev)}")
            eq[ek] = ev
        if not has and not eq:
            raise _fail(pack, f"{where}.where",
                        "至少要给出一个条件（has 非空 或 eq 非空）；"
                        "无条件并入请用 entry_merge")
        out.append({"target": target, "from": frm, "has": has, "eq": eq})
    return tuple(out)


def _validate_entry_groups(value: object, pack: str, key: str
                           ) -> Dict[str, Mapping[str, Any]]:
    """`entry_groups` 形态校验并归一化（批20 C，中栏条目分组）。

    形态：`{"<模块>": {"by": "field" | "id_prefix", "field": "<键>", "labels": {…},
    "other_label": "…", "collapsed": <bool>}}`。
    约束：模块名为非空字符串；by 为 field / id_prefix；by=field 时 field 必填且非空；
    labels 为「非空字符串 → 非空字符串」；other_label 为非空字符串；
    `collapsed`（首节之后的小节是否默认折叠）为布尔；只允许上述五个键（防写法漂移）。
    这里只校验**形态**；模块是否声明、字段是否登记由编辑器读取层处理（不悬空、不报错）。
    """
    raw = _require_map(value, pack, key)
    out: Dict[str, Mapping[str, Any]] = {}
    for mod, spec in raw.items():
        if not isinstance(mod, str) or not mod:
            raise _fail(pack, key, f"含非法模块名（应为非空字符串）：{mod!r}")
        where = f"{key}.{mod}"
        if not isinstance(spec, Mapping):
            raise _fail(pack, where, f"应为对象，实际是{_type_name(spec)}")
        allowed = ("by", "field", "labels", "other_label", "collapsed")
        unknown = [str(k) for k in spec if k not in allowed]
        if unknown:
            raise _fail(pack, where,
                        f"含未知键：{'、'.join(unknown)}；只允许 {' / '.join(allowed)}")
        by = spec.get("by", "field")
        if by not in ("field", "id_prefix"):
            raise _fail(pack, where, f"by 应为 field 或 id_prefix，实际是{by!r}")
        field_key = spec.get("field", "")
        if by == "field" and (not isinstance(field_key, str) or not field_key):
            raise _fail(pack, where, "by=field 时必须给出非空的 field（分组依据的字段键）")
        labels = spec.get("labels", {})
        if labels is None:
            labels = {}
        labels = _str_map(labels, pack, f"{where}.labels") if labels else {}
        other = spec.get("other_label", "")
        if other is None:
            other = ""
        if other and (not isinstance(other, str)):
            raise _fail(pack, where, f"other_label 应为字符串，实际是{_type_name(other)}")
        collapsed = spec.get("collapsed", True)
        if not isinstance(collapsed, bool):
            raise _fail(pack, where, f"collapsed 应为布尔，实际是{_type_name(collapsed)}")
        out[mod] = {"by": str(by),
                    "field": str(field_key) if by == "field" else "",
                    "labels": labels,
                    "other_label": str(other or ""),
                    "collapsed": collapsed}
    return out


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
    field_labels = (_display_map(raw["field_labels"], pack, "field_labels")
                    if "field_labels" in raw else {})
    field_help = (_display_map(raw["field_help"], pack, "field_help")
                  if "field_help" in raw else {})
    group_labels = (_nested_str_map(raw["group_labels"], pack, "group_labels")
                    if "group_labels" in raw else {})
    subgroup_labels = (_nested_str_map(raw["subgroup_labels"], pack, "subgroup_labels")
                       if "subgroup_labels" in raw else {})
    entry_merge = (_validate_entry_merge(raw["entry_merge"], pack, "entry_merge")
                   if "entry_merge" in raw else {})
    segment_pages = (_validate_segment_pages(raw["segment_pages"], pack, "segment_pages")
                     if "segment_pages" in raw else {})
    id_prefix = (_validate_id_prefix_map(raw["id_prefix"], pack, "id_prefix")
                 if "id_prefix" in raw else {})
    id_width = (_validate_id_width_map(raw["id_width"], pack, "id_width")
                if "id_width" in raw else {})
    entry_presets = (_validate_entry_presets(raw["entry_presets"], pack, "entry_presets")
                     if "entry_presets" in raw else {})
    entry_presets_disable = (
        _validate_entry_presets_disable(
            raw["entry_presets_disable"], pack, "entry_presets_disable")
        if "entry_presets_disable" in raw else {})
    entry_tree = (_validate_entry_tree(raw["entry_tree"], pack, "entry_tree")
                  if "entry_tree" in raw else ())
    entry_merge_filtered = (
        _validate_entry_merge_filtered(
            raw["entry_merge_filtered"], pack, "entry_merge_filtered")
        if "entry_merge_filtered" in raw else ())
    entry_groups = (_validate_entry_groups(raw["entry_groups"], pack, "entry_groups")
                    if "entry_groups" in raw else {})
    return PackFieldMeta(
        pack=pack,
        module_labels=module_labels,
        module_tree=module_tree,
        field_labels=field_labels,
        field_help=field_help,
        group_labels=group_labels,
        subgroup_labels=subgroup_labels,
        entry_merge=entry_merge,
        segment_pages=segment_pages,
        id_prefix=id_prefix,
        id_width=id_width,
        entry_presets=entry_presets,
        entry_presets_disable=entry_presets_disable,
        entry_tree=entry_tree,
        entry_merge_filtered=entry_merge_filtered,
        entry_groups=entry_groups,
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


def _display_node(spec: object, hspec: object) -> FieldMeta:
    """从嵌套声明造「纯展示节点」（obj 容器或叶子）。

    纯 JSON 无法区分 obj 与 list 形态；仅用于框架未登记、包也没给结构的新键——
    已有结构（框架结构表）一律走 `_apply_display` 覆盖，不发生形态变化。
    """
    label = (spec if isinstance(spec, str) else
             (str(spec.get("_label", "")) if isinstance(spec, Mapping) else ""))
    help_text = (hspec if isinstance(hspec, str) else
                 (str(hspec.get("_help", "")) if isinstance(hspec, Mapping) else ""))
    children: Dict[str, FieldMeta] = {}
    if isinstance(spec, Mapping):
        for key, sub in spec.items():
            if key in ("_label", "_help"):
                continue
            hs = hspec.get(key) if isinstance(hspec, Mapping) else None
            children[str(key)] = _display_node(sub, hs)
    return FieldMeta(type=("obj" if children else ""), soft_label=True,
                     label=label, help=help_text, children=children)


def _apply_display(fields: Mapping[str, FieldMeta],
                   labels: Mapping[str, object], helps: Mapping[str, object],
                   add_unknown: bool) -> Dict[str, FieldMeta]:
    """把 labels/helps 叠加到一张字段表（同键覆盖，未声明键原样保留）。

    值可为字符串（叶子中文名/说明）或嵌套声明（`_label` 本节点 + 子键递归）。
    已知键覆盖 label/help 并递归下钻 children / element.children；`add_unknown=True`
    时，包为框架未登记的键声明了展示 → 补 `soft_label` 纯展示节点（校验短路）。
    """
    out: Dict[str, FieldMeta] = dict(fields)
    for key, fm in fields.items():
        kw: Dict[str, object] = {}
        lspec = labels.get(key)
        hspec = helps.get(key)
        if isinstance(lspec, str):
            kw["label"] = lspec
        elif isinstance(lspec, Mapping) and lspec.get("_label"):
            kw["label"] = str(lspec["_label"])
        if isinstance(hspec, str):
            kw["help"] = hspec
        elif isinstance(hspec, Mapping) and hspec.get("_help"):
            kw["help"] = str(hspec["_help"])
        new = replace(fm, **kw) if kw else fm
        new = _apply_display_children(new, lspec, hspec, add_unknown)
        if new is not fm:
            out[key] = new
    if add_unknown:
        for key, lspec in labels.items():
            if key in out or key in ("_label", "_help"):
                continue
            out[str(key)] = _display_node(lspec, helps.get(key))
        for key, hspec in helps.items():
            if key in out or key in ("_label", "_help"):
                continue
            out[str(key)] = _display_node(None, hspec)
    return out


def _apply_display_children(fm: FieldMeta, lspec: object, hspec: object,
                            add_unknown: bool) -> FieldMeta:
    """递归覆盖 obj 子字段 / list 元素对象子字段的 label/help。"""
    lmap = lspec if isinstance(lspec, Mapping) else None
    hmap = hspec if isinstance(hspec, Mapping) else None
    if lmap is None and hmap is None:
        return fm
    new = fm
    if fm.children:
        new = replace(new, children=_apply_display(
            fm.children, lmap or {}, hmap or {}, add_unknown))
    elif add_unknown and fm.type == "obj":
        new = replace(new, children=_apply_display({}, lmap or {}, hmap or {}, True))
    elem = new.element
    if elem is not None and elem.children:
        new = replace(new, element=replace(elem, children=_apply_display(
            elem.children, lmap or {}, hmap or {}, add_unknown)))
    elif add_unknown and elem is not None and elem.type == "obj":
        new = replace(new, element=replace(
            elem, children=_apply_display({}, lmap or {}, hmap or {}, True)))
    return new


def _merge_module(base_mod: Optional[ModuleMeta], mod: str,
                  labels: Mapping[str, str], helps: Mapping[str, str],
                  groups: Mapping[str, str],
                  subgroups: Optional[Mapping[str, str]] = None) -> ModuleMeta:
    """单模块合并：labels/helps 逐键覆盖，groups/subgroups 逐键覆盖（未声明键保持现状）。

    `subgroups`（批20 C）= 二级分组显示名覆盖；**结构**（键→子分组）仍归框架元数据。
    """
    if base_mod is None:
        # 框架未登记该模块：只造「纯展示壳」——entry_type 留空 = api 层按实际数据推断，
        # 行为与「无模块元数据」一致，仅多出包声明的中文名/说明/分组。
        fields: Dict[str, FieldMeta] = {}
        for key in labels:
            if key in ("_label", "_help"):
                continue
            fields[key] = _display_node(labels[key], helps.get(key))
        for key, help_text in helps.items():
            if key not in fields and key not in ("_label", "_help"):
                fields[key] = _display_node(None, help_text)
        return ModuleMeta(entry_type="", fields=fields,
                          group_labels=dict(groups))
    merged_groups: Dict[str, str] = dict(base_mod.group_labels)
    merged_groups.update(groups)
    merged_subgroups: Dict[str, str] = dict(base_mod.subgroup_labels)
    merged_subgroups.update(subgroups or {})
    # map 形态模块（如 stats）：展示表面在 value_meta.children——包声明不落在空顶层 fields，
    # 避免多造幽灵顶层字段（对拍门禁）。
    has_value_surface = (base_mod.value_meta is not None
                         and base_mod.value_meta.type == "obj"
                         and bool(base_mod.value_meta.children))
    kw: Dict[str, object] = {
        "fields": _apply_display(base_mod.fields, labels, helps, not has_value_surface),
        "group_labels": merged_groups,
        "subgroup_labels": merged_subgroups,
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
    mods = (set(decl.field_labels) | set(decl.field_help) | set(decl.group_labels)
            | set(decl.subgroup_labels))
    for mod in mods:
        modules[mod] = _merge_module(
            base.modules.get(mod), mod,
            decl.field_labels.get(mod, {}),
            decl.field_help.get(mod, {}),
            decl.group_labels.get(mod, {}),
            decl.subgroup_labels.get(mod, {}),
        )
    return FieldMetaTable(modules=modules, namespaces=dict(base.namespaces))


__all__ = [
    "FIELD_META_FILENAME",
    "SCHEMA_VERSION",
    "TOP_LEVEL_KEYS",
    "ID_WIDTH_DEFAULT",
    "ID_WIDTH_MAX",
    "PackFieldMeta",
    "PackFieldMetaError",
    "load_field_meta",
    "merge_field_meta_table",
    "parse_field_meta",
]
