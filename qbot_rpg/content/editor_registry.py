"""编辑器页面注册表（M12 路1A · 细化_5a2 可插拔页面注册表 PR-01~PR-06 数据层）。

文件名：qbot_rpg/content/editor_registry.py
创建时间：2026-09-03
作者：Hermes 子agent（M12 批1 路1A：editor.json 注册表数据层）

功能描述：
  - EditorPage：注册表条目模型（page_id/title/icon/module_file/meta_source/
    tabs/enabled/extends/validator，字段语义见 细化_5a2 PR-02 5a2 L51）。
  - load_editor_registry(registry)：从内容包 registry.modules_raw["editor"]
    （editor.json 解析产物）读页表；无 editor 模块 → 返回默认六页兜底
    （细化_5a2 M-06 5a2 L239：缺失 editor.json → 按 5a 六页默认值启动，
    向后兼容——test_demo 等旧内容包未声明 editor.json 也能渲染六页）。
  - pages()/get_page(page_id)/enabled_pages()：PR-03 启停语义 5a2 L52
    （enabled:false → 侧边栏不渲染、/api/pages/{page} 404、不纳入编辑器
    校验——引擎侧加载不受编辑器启停影响）。
  - page_for_module(module_file)：按模块文件取页（extends 解析，如 ai
    extends=monster → 与怪物页共享 enemies.json，5a2 L71/L79）。
  - validate_validators(page_ids)：校验器钩子名存在性登记（PR-05 5a2 L54；
    钩子名 → 校验函数映射表当前由 web 路由/装配层提供，本模块只做
    「登记名集合」校验——缺省 None 不硬拦）。

依据：
  - docs/细化/细化_5a2_编辑器扩展页.md 一、可插拔页面注册表（PR-01~PR-06，
    5a2 L44-79；editor.json 配置样例 L59-77；六页默认登记项 L46）
  - docs/细化/细化_5a_编辑器契约.md 二、页面结构（P-06 六页归口 5a L80；
    P-07 元数据唯一数据源 5a L81）
  - docs/m12_编辑器摸底.md 一/二（PR-01~06 现状核对）/ 三（field_meta
    正式表缺口）/ 五（Registry.modules_raw 复用资产清单）
  - docs/m12_启动包.md 批1·路1A（L78：editor.json 模型 + fixture）

铁律：零 NoneBot import；纯函数确定性（同刻同参同值，零 IO 零随机
      零定时器/零睡眠）；content 层仅依赖 content/models + content/registry
      兄弟模块（不 import web/commands/assembly，不反向依赖 engine/core）；
      文件头标注依据（含契约行号）；全中文注释；零 emoji（配置样例外）。

G0 边界：本模块消费 Registry.modules_raw（registry.py L106-108 只读视图，
  内容包解析产物）——registry 已在 loader D 阶段构建完成，零文件 IO。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from qbot_rpg.content.registry import Registry

# =====================================================================================
# 常量：默认六页 + 校验器钩子登记（细化_5a P-06 六页归口 5a L80 / 细化_5a2 PR-01 5a2 L46）
# =====================================================================================

# 六页默认登记项（5a P-06 六页归口 + 5a2 L63-68 样例的六页行；meta_source 对齐
# 5a2 M-03 19 页 meta_source 口径）。模块文件与 field_meta 登记/loader 映射对齐：
#   skills.json（field_meta skills 模块）/ jobs.json（jobs 模块）/ enemies.json /
#   maps.json / quest.json（loader 登记单数 quest——5a 契约 P-06 写 quests.json 为
#   文档笔误，实测 loader._KIND_FOR_MODULE「quest」+ test_demo 实文件 quest.json）/
#   shop.json。tabs 为 None = 单标签页（5a2 样例中 skill/job/quest/shop 未列 tabs）。
# 元组不可变，兜底实例共享安全。
_DEFAULT_PAGE_SPECS: Tuple[Mapping[str, object], ...] = (
    {
        "page_id": "skill",
        "title": "技能",
        "icon": "⚔️",
        "module_file": "skills.json",
        "meta_source": "meta/skill",
        "enabled": True,
        "validator": "skill",
    },
    {
        "page_id": "job",
        "title": "职业",
        "icon": "🎖️",
        "module_file": "jobs.json",
        "meta_source": "meta/job",
        "enabled": True,
        "validator": "job",
    },
    {
        "page_id": "monster",
        "title": "怪物",
        "icon": "👹",
        "module_file": "enemies.json",
        "meta_source": "meta/monster",
        "enabled": True,
        "validator": "monster",
        # 9 标签页（5a P-06 怪物行）+ AI×6（5a2 样例 L65，AI 并入怪物标签栏 5a2 M-02）
        "tabs": ["基本信息", "属性", "弱点", "PV", "抗性", "行动", "特殊行动",
                 "掉落", "图鉴", "AI×6"],
    },
    {
        "page_id": "map",
        "title": "地图",
        "icon": "🗺️",
        "module_file": "maps.json",
        "meta_source": "meta/map",
        "enabled": True,
        "validator": "map",
        # 5a2 样例 L66：[基础][通道][怪物][NPC]（NPC 标签 = NPC 挂点双向登记 N-02）
        "tabs": ["基础", "通道", "怪物", "NPC"],
    },
    {
        "page_id": "quest",
        "title": "任务",
        "icon": "📜",
        # loader 登记为 quest.json（单数；5a P-06 契约写 quests.json 是文档笔误——
        # 1C 勘察实测 loader._KIND_FOR_MODULE L192「quest」+ test_demo 实文件 quest.json）
        "module_file": "quest.json",
        "meta_source": "meta/quest",
        "enabled": True,
        "validator": "quest",
    },
    {
        "page_id": "shop",
        "title": "商店",
        "icon": "🏪",
        "module_file": "shop.json",
        "meta_source": "meta/shop",
        "enabled": True,
        "validator": "shop",
    },
)

# 默认校验器钩子名集合（PR-05：每 page_id 登记一个校验器钩子；本模块侧只登记
# 钩子名存在性——钩子到 validate_* 函数的分派归 web/装配层，见模块 docstring）。
DEFAULT_VALIDATORS: Tuple[str, ...] = (
    "skill", "job", "monster", "map", "quest", "shop",
)


# =====================================================================================
# 条目模型（细化_5a2 PR-02 5a2 L51）
# =====================================================================================
@dataclass(frozen=True)
class EditorPage:
    """注册表单页条目（细化_5a2 PR-02 5a2 L51 字段语义逐列对齐）。

    - page_id：API 枚举名（/api/pages/{page}，5a §6.3；5a2 M-03 扩展枚举）
    - title：侧边栏中文名（PR-02，5a P-05 顶栏/侧边栏清单数据源）
    - icon：侧边栏图标 emoji（PR-02）
    - module_file：模块 JSON 文件名（P-06 归口；编辑器读写该文件）
    - meta_source：字段元数据表名（P-07 唯一数据源；5a2 M-03 19 页口径）
    - tabs：子标签页名列表（None = 无子标签/单页签；AI×6/hidden×3 挂载页携带）
    - enabled：启停（PR-03：false → 侧边栏不渲染 / API 404 / 不纳入编辑器校验）
    - extends：挂载进既有页的 page_id（如 ai extends=monster 共享 enemies.json，
      5a2 L71/L79；None = 独立页）
    - validator：校验器钩子名（PR-05；None = 无校验器钩子登记，不硬拦）
    """

    page_id: str
    title: str
    icon: str = ""
    module_file: str = ""
    meta_source: str = ""
    tabs: Tuple[str, ...] = ()
    enabled: bool = True
    extends: Optional[str] = None
    validator: Optional[str] = None
    # M12.5 批1 路1B（审计点 #3/#31）：可选扩展字段——缺省 None 向后兼容，
    # 既有构造（默认六页/既有内容包 editor.json/测试）零改动零语义变化
    id_prefix: Optional[str] = None  # ID 自动生成前缀（缺省回退 page_id）
    group: Optional[str] = None      # 侧边栏分组名（缺省 None=不分）
    page_kind: Optional[str] = None  # 页面形态 list/map/object/view（缺省 None=推导）


@dataclass(frozen=True)
class EditorRegistry:
    """页面注册表：页表 + schema 版本（内容包 editor.json 解析产物）。"""

    pages: Tuple[EditorPage, ...] = ()
    schema_version: Optional[int] = None

    # ---- 页表访问（PR-03 启停语义：get_page 含停用页；enabled_pages 只含启用页）----
    def pages_by_id(self) -> Mapping[str, EditorPage]:
        """page_id → EditorPage 映射（停用页也含；重复 page_id 后者覆盖前者）。"""
        return {p.page_id: p for p in self.pages}

    def get_page(self, page_id: str) -> Optional[EditorPage]:
        """按 page_id 取页（含 enabled:false 页；找不到返回 None）。

        PR-03 语义（5a2 L52）：停用页仍可被 get_page 取到——上层用它做
        「页面存在但已停用」判定（如 /api/pages/{page} 对停用页返回 404，
        需先确认 page_id 是否登记过）。
        """
        return self.pages_by_id().get(page_id)

    def enabled_pages(self) -> Tuple[EditorPage, ...]:
        """只含 enabled=True 的页（侧边栏渲染/路由白名单数据源，PR-03）。"""
        return tuple(p for p in self.pages if p.enabled)

    def page_for_module(self, module_file: str) -> Optional[EditorPage]:
        """按模块文件取页；extends 页优先解析回宿主页（如 ai → monster）。

        共享同一 module_file 的多页（ai/hidden 挂载进 enemies.json/maps.json）
        只返回一个「代表页」：extends 链末端的宿主页优先（monster/map），
        独立页其次——与 PR-03「模块文件不纳入编辑器校验」语义配合，
        供校验器按页聚合模块时避免重复。
        """
        host: Optional[EditorPage] = None
        fallback: Optional[EditorPage] = None
        for p in self.pages:
            if p.module_file != module_file:
                continue
            if fallback is None:
                fallback = p
            if p.extends is None:
                host = p  # 宿主页（非挂载页）优先；同 module_file 独立页取首个
        return host if host is not None else fallback

    # ---- 校验器钩子名登记（PR-05 5a2 L54）----
    def validator_names(self) -> Tuple[str, ...]:
        """登记的全部校验器钩子名（含停用页；None 钩子跳过）。"""
        return tuple(v for p in self.pages if (v := p.validator) is not None)

    def has_validator(self, name: str) -> bool:
        """校验器钩子名是否已登记（None 钩子不登记，不硬拦 5a2 L51 末尾）。"""
        return name in self.validator_names()


# =====================================================================================
# 加载（细化_5a2 M-06 5a2 L239：缺失 editor.json → 按 5a 六页默认值启动）
# =====================================================================================
def default_editor_pages() -> Tuple[EditorPage, ...]:
    """5a 六页默认登记项（缺省兜底；每次调用返回全新实例防共享可变引用）。"""
    return tuple(_page_from_spec(spec) for spec in _DEFAULT_PAGE_SPECS)


def _page_from_spec(spec: Mapping[str, object]) -> EditorPage:
    """条目原始 dict → EditorPage（宽容解析：缺失键回落默认，类型不符回落默认）。"""
    page_id = spec.get("page_id")
    pid = str(page_id) if isinstance(page_id, str) and page_id else ""
    title = spec.get("title")
    ptitle = str(title) if isinstance(title, str) else ""
    icon = spec.get("icon")
    picon = str(icon) if isinstance(icon, str) else ""
    module_file = spec.get("module_file")
    pmodule = str(module_file) if isinstance(module_file, str) else ""
    meta_source = spec.get("meta_source")
    pmeta = str(meta_source) if isinstance(meta_source, str) else ""
    # tabs：字符串列表（元素取 str，过滤非字符串）
    raw_tabs = spec.get("tabs")
    tabs: Tuple[str, ...] = ()
    if isinstance(raw_tabs, (list, tuple)):
        tabs = tuple(t for t in raw_tabs if isinstance(t, str))
    # enabled：布尔；缺省 true（样例缺省即为启用，5a2 L63-74 全 true）
    raw_enabled = spec.get("enabled", True)
    enabled = bool(raw_enabled) if isinstance(raw_enabled, bool) else True
    # extends/validator：可空字符串（None/缺省 → None；非字符串 → None）
    raw_extends = spec.get("extends")
    extends: Optional[str] = str(raw_extends) if isinstance(raw_extends, str) else None
    raw_validator = spec.get("validator")
    validator: Optional[str] = (
        str(raw_validator) if isinstance(raw_validator, str) else None
    )
    # M12.5 批1 路1B：扩展三字段（id_prefix/group/page_kind）可空字符串解析
    raw_id_prefix = spec.get("id_prefix")
    id_prefix: Optional[str] = (
        str(raw_id_prefix) if isinstance(raw_id_prefix, str) else None
    )
    raw_group = spec.get("group")
    group: Optional[str] = str(raw_group) if isinstance(raw_group, str) else None
    raw_kind = spec.get("page_kind")
    page_kind: Optional[str] = (
        str(raw_kind) if isinstance(raw_kind, str) else None
    )
    return EditorPage(
        page_id=pid,
        title=ptitle,
        icon=picon,
        module_file=pmodule,
        meta_source=pmeta,
        tabs=tabs,
        enabled=enabled,
        extends=extends,
        validator=validator,
        id_prefix=id_prefix,
        group=group,
        page_kind=page_kind,
    )


def load_editor_registry(registry: Registry) -> EditorRegistry:
    """从内容包 registry 读 editor.json 解析产物，构建页面注册表。

    入参：registry —— 已构建的内容包 Registry（loader D 阶段产物）。
    出参：EditorRegistry。
    核心逻辑（纯函数确定性）：
      - registry.modules_raw 含 "editor" 键 → editor.json 顶层 dict：
          - "schema_version"：int（缺省 None）
          - "pages"：条目列表 → EditorPage（逐条宽容解析 _page_from_spec；
            条目非 dict 跳过；缺 page_id/page_id 非字符串 → 丢弃该条并计入
            invalid 计数——PR-02 条目标识字段必填）
        editor 模块缺失 → 返回默认六页兜底（M-06：内容包未声明页面 →
        只显示总览/数据包管理，但默认六页登记保证向后兼容 5a 六页壳）。
      - 页序 = editor.json 声明顺序（5a2 L62-75 样例序；侧边栏渲染按此序）。
    确定性：同 registry 恒同结果（零 IO 零随机）。
    """
    raw_editor = registry.modules_raw.get("editor")
    if not isinstance(raw_editor, Mapping):
        # PR-01/M-06（5a2 L50/L239）：内容包未声明 editor.json → 默认六页兜底
        return EditorRegistry(pages=default_editor_pages())

    schema_raw = raw_editor.get("schema_version")
    schema: Optional[int] = (
        schema_raw if isinstance(schema_raw, int) and not isinstance(schema_raw, bool) else None
    )
    raw_pages = raw_editor.get("pages")
    pages: List[EditorPage] = []
    if isinstance(raw_pages, list):
        for entry in raw_pages:
            if not isinstance(entry, Mapping):
                continue  # 条目非对象：跳过（宽容解析，R-5 结构错误交内容包校验器）
            page = _page_from_spec(entry)
            if page.page_id:
                pages.append(page)
    return EditorRegistry(pages=tuple(pages), schema_version=schema)


# =====================================================================================
# 校验器钩子名存在性校验（PR-05 5a2 L54；缺省 None 不硬拦——5a2 L51「validator 钩子名」
# 为可空登记，装配层未接线钩子的页照常可渲染，仅 validate 端点无钩子时返回空校验）
# =====================================================================================
def validate_validators(
    editor: EditorRegistry,
    known: Optional[Sequence[str]] = None,
) -> Tuple[str, ...]:
    """校验器钩子名一致性校验：返回有问题的 page_id 列表（空 = 全部合规）。

    入参：
      editor —— EditorRegistry（load_editor_registry 产物）。
      known  —— 外部已知的校验器实现名集合（web/装配层注入：它持有
        validator 名 → 校验函数的分派表，如 content/validator 实际能跑的
        钩子名清单）。缺省 None → 只做页表内部一致性检查（重复名/空名）。
    出参：tuple[str]，问题 page_id 列表。
    判定口径：
      - known 提供时：页表登记的非 None validator 名不在 known → 该页计入
        （黄提示级不阻断；PR-05 校验挂载由 /api/pages/{page}/validate 按钩子
        执行，缺钩子的页 validate 端点降级为空校验清单）。
      - known 缺省：只报页表内重复 validator 名（同名登记 >1 次 → 计入；
        幽灵名无法自证，交上层注入 known 后校验——本层不自举）。
    纯函数确定性：同入参恒同结果。
    """
    problems: List[str] = []
    if known is None:
        # 页表内部一致性：重复名报出（幽灵名无法自证，交上层 known 校验）
        seen: Dict[str, int] = {}
        for p in editor.pages:
            if p.validator is None:
                continue
            seen[p.validator] = seen.get(p.validator, 0) + 1
            if seen[p.validator] == 2:
                problems.append(p.page_id)
        return tuple(problems)
    known_set = set(known)
    return tuple(
        p.page_id
        for p in editor.pages
        if p.validator is not None and p.validator not in known_set
    )


# editor.json 模块名常量（Registry.modules_raw 键；content/registry.py 只读视图）
EDITOR_MODULE: str = "editor"

__all__ = [
    "EDITOR_MODULE",
    "EditorPage",
    "EditorRegistry",
    "default_editor_pages",
    "load_editor_registry",
    "validate_validators",
]
