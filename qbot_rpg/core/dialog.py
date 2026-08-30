"""对话会话状态机（M4 批次2·路C3 · qbot_rpg/core/dialog.py 唯一实现）——7 态 15 迁移 + 会话路由 + 深度可配 + 恢复简报 + 事件计数。

依据：
  - m4_shared_contract.md §3.1（NPC/对话 B1-B6：会话路由 /对话 列表·序号·名称；对话树
    ≤ max_dialog_depth（可配，0=不限）；退出词三词同义 + 菜单"N.离开"；菜单 ≤6 选项折叠）
  - docs/细化/细化_2b2_对话会话状态机.md（§2.0 七态 S0-S6；§2.1 主迁移表 T01-T15；§2.2 会话路由
    接口；§2.3 中断与恢复；§三 会话路由 R1-R5；§四 菜单 ≤6 折叠；§五 无 NPC 提示；§六 TC-01~TC-21；
    §七 状态机不变量）
  - docs/审查参考/NPC系统设计定稿.md v1.3.1（§二 指令设计 L37-53；§2.1 会话路由规则 L55-71；
    §2.2 当前商店机制 L73-81；§2.3 一次一物 L83-92；§2.4 对话恢复简报 L94-102；
    §3.0 菜单上限 ≤6 L108-113；§3.1 交互流程 L115-123；§三 对话结构 L316-336（深度可配 L324/L328）；
    L289 [事件:NPC对话:ID] 事件计数）
  - 审查_M4实现_批次3_jspace.md P1-1/2/3（本文件修复依据）：
      P1-1：INFO_ACTIONS 去掉 "reply"（对齐同批 npc.py INFO_ACTIONS=("intel","tutorial")）；
            reply 属闲聊不触发一次一物、不置灰可重复（2b1 AC10 / 定稿 L90），_is_info 按
            「显式 info:true 优先、否则 action∈INFO_ACTIONS」判定，reply 需按信息类须显式 "info": true。
      P1-2：_narration_of 叙述提取补 text[] 列表（与 lines 同逻辑），reply 选择流不再空白屏。
      P1-3：to_snapshot 携带 exec_index、from_snapshot 恢复 _exec_index，EXEC 中断续读完成后
            mark_heard 正确（已听置灰不丢，情报不重复领）。
  - 2026-08-27 M4 设计审查裁决③（m4_shared_contract §0 第 3 条 / 细化_2b1 裁决 P1-1）：对话树深度
    恢复可配 settings.max_dialog_depth（默认 2，0=不限），超深软拦（L328 提示不拦截）。

【工程补白 · 显式标注】
  1) NPC 定义消费形态：本模块为纯状态机，不 import content/npc_models.py（并行路，零冲突）。
     按定稿 npc.json schema（L357-379）消费 dict 形态
     {id, name, icon, type, visible, interactions, dialogues}；interactions[] 条目
     {action, text, condition?, info?, ...}。
  2) 事件计数：本模块只产出事件键串（"[事件:NPC对话:{npc_id}]"，L289），实际写入
     longline_counters 由调用方（世界层/装配层）完成（对齐 reward 解析器「只产出结果标记」惯例）。
  3) 已听集合：信息类交付置灰标记落玩家存档（L88，不落会话快照）；本模块经 ctx["heard"] 读取、
     经结果 mark_heard 上报，由调用方持久化（对齐「已交付标记落玩家存档」）。
  4) current_shop_ref：2026-08-27 裁决 T12/T13 修复——商店选购不进子界面，current_shop_ref 记录
     移到商店独立交付路径（2b3）；本模块只在 shop 动作时经结果 shop_refs 上报，由世界层按地图级
     状态记录/离开地图清除（L76-79）。
  5) 子界面层 S5 SUBUI 仅承载 heal 确认 / 任务交付确认 / 领取中（L99-100）；商店选购不在此层（L80）。
  6) 菜单折叠（§四 L110-111 / TC-06/19/20）：首页 ≤6 选项 + 折叠「N.更多…」+ 固定「N.离开」；
     TC-06 口径 8 选项 → 6 项 + 7.更多 + 8.离开（离开 N = 本页可见项数 + 1，折叠页把「更多」算一项）。
     二级页按原序号续显剩余选项 + 本页可见项数+1 的离开（二级页编号定稿未定义，本路收敛）。
  7) 长叙述翻页：T11 用 page_index 快照续段（L47/L101）；叙述段由调用方经 exec_done 注入 narration
     段数组，或由会话从内容节点读取（intel/tutorial/reply 多段）。
  8) 深度守卫（裁决③）：T07 选择选项前按选项目标节点的**内容树深度**（authored_node_depth）与
     settings.max_dialog_depth 比较——超深软拦（留 S3 MENU + 提示 DIALOG_DEPTH_HINT，L328）；
     0=不限不拦。interactions 平铺（深度 1）默认永不触发。会话自身不累积深度（§2.0 状态变量
     无 depth），避免重复选择同选项误拦。
  9) 对话树子节点（sub_dialog/dialog_node，2b1 §1.2 D01-D06）在本七态状态机内以**长叙述形态交付**
     （EXEC 分段翻页），不新增嵌套 MENU 态（2b2 七态约束）；深层树导航与内容校验属 2b1/npc_models 范围。
  10) T15 收尾自动衔接：结束路径（T04/T09/T14）落地 S6 后本步自动执行 T15（打事件计数 + 清理 → S0），
      result.trace 保留两条迁移供断言（对齐「结束路径单点收尾」不变量 §七 6）。
  11) 结束词统一 离开/再见/退出 三词同义（L62）；路由写死不可配（§七 1）。

纯函数约定：零 NoneBot import；无 IO；同参同值确定性；事件/持久化一律经结果上报由调用方落盘。
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

from qbot_rpg.core.message_format import strip_icon_emoji

__all__ = [
    # 七态
    "S_IDLE", "S_LIST", "S_NPCSEL", "S_MENU", "S_EXEC", "S_SUBUI", "S_END", "STATES",
    # 迁移表
    "TRANSITION_IDS", "TRANSITION_COUNT",
    # 会话子词（对齐 commands/router.py SESSION_SUBWORD_* 词表）
    "SUBWORD_DIGIT", "SUBWORD_CONTINUE", "SUBWORD_EXIT", "SUBWORD_SELECT",
    "EXIT_WORDS", "classify_session_input",
    # 会话路由（2b2 §三 R1-R5）
    "route_session_input",
    # 深度配置（2026-08-27 裁决③）
    "DEFAULT_MAX_DIALOG_DEPTH", "SETTINGS_MAX_DIALOG_DEPTH", "DIALOG_DEPTH_HINT",
    "resolve_max_dialog_depth", "authored_node_depth", "is_depth_blocked",
    # /对话 参数解析（2b2 §一）
    "parse_dialog_command",
    # 菜单折叠 + 条件提示 + 列表渲染
    "MENU_MAX_OPTIONS", "INFO_ACTIONS", "render_npc_list", "render_interaction_menu",
    "resolve_menu_selection", "condition_hint",
    # 事件计数（L289）
    "dialog_event_key",
    # 恢复简报（L94-102）
    "build_resume_brief",
    # 状态机
    "DialogSession",
    "DIALOG_EMPTY_MAP_HINT", "DIALOG_NOT_FOUND_HINT", "DIALOG_ALREADY_HEARD_HINT",
]

# -------------------------------------------------------------------------------------
# 七态（2b2 §2.0 S0-S6）
# -------------------------------------------------------------------------------------
S_IDLE = "idle"        # S0 未会话
S_LIST = "list"        # S1 菜单列表
S_NPCSEL = "npcsel"    # S2 选 NPC
S_MENU = "menu"        # S3 交互选择
S_EXEC = "exec"        # S4 交互执行
S_SUBUI = "subui"      # S5 子界面层
S_END = "end"          # S6 会话结束
STATES: tuple = (S_IDLE, S_LIST, S_NPCSEL, S_MENU, S_EXEC, S_SUBUI, S_END)

# 主迁移表 15 条（2b2 §2.1 T01-T15）
TRANSITION_IDS: tuple = (
    "T01", "T02", "T03", "T04", "T05", "T06", "T07", "T08",
    "T09", "T10", "T11", "T12", "T13", "T14", "T15",
)
TRANSITION_COUNT = len(TRANSITION_IDS)

# -------------------------------------------------------------------------------------
# 会话子词（2b2 §三 R1 / 3c §5；与 commands/router.py 词表同构，核心层自持一份避免跨层依赖）
# -------------------------------------------------------------------------------------
SUBWORD_DIGIT = "digit"        # 纯数字 1/2/3
SUBWORD_CONTINUE = "continue"  # 继续（翻下一段，L47）
SUBWORD_EXIT = "exit"          # 退出/离开/再见（三词同义，L62）
SUBWORD_SELECT = "select"      # 选择 N（与纯数字 N 等价映射【工程补白】）

# 结束词三同义（2b2 L62 / R1）
EXIT_WORDS: tuple = ("离开", "再见", "退出")

# 选择 N 形态：`选择 N` / `选择N`（2b2 R1）
_SELECT_RE = re.compile(r"^选择\s*(\d+)$")

# 无 NPC 提示（L50 / TC-08）与未命中提示（L43 / 1.2 步骤 4）
DIALOG_EMPTY_MAP_HINT = "当前地图没有可对话的人"
DIALOG_NOT_FOUND_HINT = "没找到这个人"
DIALOG_ALREADY_HEARD_HINT = "你已经听过了"  # TC-11（L87）

# 深度配置（2026-08-27 裁决③ / 2b1 P1-1）
DEFAULT_MAX_DIALOG_DEPTH = 2
SETTINGS_MAX_DIALOG_DEPTH = "max_dialog_depth"
DIALOG_DEPTH_HINT = "对话太深，拆成多 NPC 或事件牌组"  # L328 超深软拦提示

# 菜单 ≤6 折叠（2b2 §四 / L110-111）
MENU_MAX_OPTIONS = 6

# 信息类动作（交付置灰「已听」，L86-89）；其余功能类不置灰（L90）【工程补白】。
# 对齐同批 npc.py INFO_ACTIONS=("intel","tutorial")（审查_M4实现_批次3_jspace.md P1-1）：
# reply 属闲聊（2b1 AC10：不触发一次一物/不置灰可重复），不列入；如需按信息类须显式 "info": true。
INFO_ACTIONS: frozenset = frozenset({"intel", "tutorial"})


# -------------------------------------------------------------------------------------
# 会话子词分类 + 会话路由（2b2 §三 R1-R5）
# -------------------------------------------------------------------------------------
def classify_session_input(text: object) -> Optional[Tuple[str, Optional[int]]]:
    """会话子词分类（2b2 §三 R1，纯函数）。

    输入 ∈ {纯数字, 继续, 离开/再见/退出, 选择 N} → (category, value)；
    否则 → None（非会话子词，路由走 R2 正常指令解析）。
      - 纯数字 → ("digit", int(N))
      - 继续   → ("continue", None)
      - 结束词 → ("exit", None)
      - 选择 N → ("select", int(N))
    """
    if not isinstance(text, str):
        return None
    t = text.strip()
    if not t:
        return None
    if t.isdigit():
        return (SUBWORD_DIGIT, int(t))
    if t == "继续":
        return (SUBWORD_CONTINUE, None)
    if t in EXIT_WORDS:
        return (SUBWORD_EXIT, None)
    m = _SELECT_RE.match(t)
    if m:
        return (SUBWORD_SELECT, int(m.group(1)))
    return None


def route_session_input(text: object, *, session_active: bool) -> dict:
    """会话路由判定（2b2 §三 R1-R5，纯函数）。

    - 会话激活中（R1/R3）：输入为会话子词 → 送状态机 {"kind":"session","subword":(cat,val)}；
      其余输入 → 正常指令解析 {"kind":"command"}（R2 带指令词照常解析，如 使用1/攻击1/背包2）。
    - 无会话（R4）：一律走快捷表/常规指令 {"kind":"command"}（快捷仅在无会话上下文生效）。
    - 菜单末项固定 N.离开（R5）由状态机 T09 消费，不在此判定。

    返回 {"kind": "session"|"command", "subword": (cat,val)|None}。
    【工程补白】「带指令词」判定（攻击/使用/背包/…前缀匹配）属指令解析层（commands/parsers.py
    白名单匹配）职责；本路由只做「是否会话子词 → 送状态机」与其余 → 正常解析的二选一，
    与 2b2 §2.2「路由层只做二选一判定」一致。
    """
    if not session_active:
        return {"kind": "command", "subword": None}
    sub = classify_session_input(text)
    if sub is not None:
        return {"kind": "session", "subword": sub}
    return {"kind": "command", "subword": None}


# -------------------------------------------------------------------------------------
# 对话树深度可配（2026-08-27 裁决③ / 2b1 P1-1，L324/L328）
# -------------------------------------------------------------------------------------
def resolve_max_dialog_depth(settings: Optional[Mapping[str, Any]] = None) -> int:
    """对话树深度配置解析（裁决③，纯函数）。

    settings.max_dialog_depth → int；缺省/非法（非 int、bool、负）→ 默认 2；0 = 不限。
    【工程补白】非法值按「坏配置惰性回退不崩溃」惯例回退默认 2（对齐 dayroll 口径）。
    """
    if isinstance(settings, Mapping):
        raw = settings.get(SETTINGS_MAX_DIALOG_DEPTH)
        if isinstance(raw, int) and not isinstance(raw, bool):
            if raw >= 0:
                return raw
    return DEFAULT_MAX_DIALOG_DEPTH


def authored_node_depth(option: object) -> int:
    """选项目标节点的**内容树深度**（L316-328，纯函数）。

    根交互菜单选项 = 深度 1；选项携带 sub_dialog/dialog_node（嵌套对话树节点）→
    1 + 其子节点最大深度；无嵌套 → 1。供 T07 超深软拦判定。
    """
    if not isinstance(option, Mapping):
        return 1
    sub = option.get("sub_dialog") or option.get("dialog_node")
    if not isinstance(sub, Mapping):
        return 1
    max_child = 0
    for child in sub.get("options") or []:
        max_child = max(max_child, authored_node_depth(child))
    return 1 + max_child


def is_depth_blocked(node_depth: int, max_depth: int) -> bool:
    """深度软拦判定（裁决③，纯函数）：max_depth==0 → 不限不拦（False）；否则 node_depth > max_depth → 拦。"""
    if max_depth == 0:
        return False
    return node_depth > max_depth


# -------------------------------------------------------------------------------------
# /对话 参数解析（2b2 §一 1.1-1.4，TC-01~08）
# -------------------------------------------------------------------------------------
def parse_dialog_command(args: object, npcs: Sequence[Mapping[str, Any]]) -> dict:
    """/对话 参数解析（2b2 §一 1.2，纯函数）。

    args 为 /对话 后的参数串（去首尾空白后整串判定）：
      - 空/None → {"mode":"list"}（无参列表，TC-01）
      - 整串与某 visible NPC 的 name 精确匹配（名称优先，L42）→ {"mode":"name","value":name}（TC-03/04）
      - 纯数字 → {"mode":"index","value":N}（序号兜底，L42，TC-02/06）
      - 其它 → {"mode":"name","value":raw}（未命中由状态机提示不建会话，TC-05/07）
    名称禁空格：含空格参数必然无法命中任何名称（L49）。
    """
    if args is None:
        return {"mode": "list"}
    t = str(args).strip()
    if not t:
        return {"mode": "list"}
    visible = [n for n in (npcs or []) if n.get("visible", True)]
    for n in visible:
        if str(n.get("name")) == t:
            return {"mode": "name", "value": t}
    # 2026-08-31 QA P2-8：部分名/前缀匹配（「村长」→「村长·老槐」）——唯一命中才采用，
    # 多命中保持原样（由状态机提示不建会话）。
    _pref = [n for n in visible if str(n.get("name")).startswith(t) and len(t) >= 2]
    if len(_pref) == 1:
        return {"mode": "name", "value": str(_pref[0].get("name"))}
    if t.isdigit():
        return {"mode": "index", "value": int(t)}
    return {"mode": "name", "value": t}


# -------------------------------------------------------------------------------------
# 事件计数（L289）
# -------------------------------------------------------------------------------------
def dialog_event_key(npc_id: object) -> str:
    """会话收尾事件计数键（L289）：[事件:NPC对话:{npc_id}]。"""
    return f"[事件:NPC对话:{npc_id}]"


# -------------------------------------------------------------------------------------
# 渲染：NPC 列表 / 交互菜单 ≤6 折叠 / 条件一行提示
# -------------------------------------------------------------------------------------
def render_npc_list(npcs: Sequence[Mapping[str, Any]]) -> List[str]:
    """NPC 列表渲染（L40-41 / TC-01）：「这里的人：1.🔨铁匠·老周 2.🧺杂货商人·林 …」。

    序号 + 名字 + 类型图标；icon 缺省用 type 首字兜底【工程补白】。
    """
    parts = []
    for i, npc in enumerate(npcs, start=1):
        name = str(npc.get("name") or npc.get("id") or "?")
        icon = str(npc.get("icon") or "")
        if not icon:
            icon = str(npc.get("type") or "?")[:1]
        icon = strip_icon_emoji(icon)  # M5 裁决不用 emoji：渲染出口剥离 emoji 字符
        parts.append(f"{i}.{icon}{name}")
    return ["这里的人：" + " ".join(parts)]


# 条件 var → 中文一行提示用（L112「需要：等级 ≥10」示例；定稿未给全量互译表，本路收敛常用项）
_VAR_HINT = {
    "level": "等级", "job": "职业", "item_count": "持有", "has_item": "持有",
    "coins": "金币", "gem": "宝石", "rep": "声望", "quest_done": "完成任务",
    "time": "时间", "event": "事件",
}
_OP_HINT = {"ge": "≥", "gt": ">", "le": "≤", "lt": "<", "eq": "=", "ne": "≠",
            "between": "~", "is": "", "not": "非"}


def condition_hint(cond: object) -> str:
    """条件一行提示（L112「需要：等级 ≥10」风格 / TC-21，纯函数）。

    简单 {var,op,value[,param]} → 「需要：等级 ≥10」；复合/未知 → 「需要：条件未满足」。
    【工程补白】定稿未定义条件 → 文案的统一生成规则（L112 仅示例），本函数为通用兜底；
    内容作者可经 interaction["hint"] 提供定制文案（渲染与 T08 提示时优先）。
    """
    if not isinstance(cond, Mapping):
        return "需要：条件未满足"
    var = str(cond.get("var") or "")
    value = cond.get("value")
    if not var or value is None:
        return "需要：条件未满足"
    op = _OP_HINT.get(str(cond.get("op") or ""), "")
    var_cn = _VAR_HINT.get(var, var)
    param = cond.get("param")
    base = f"需要：{var_cn} {op}{value}"
    if param:
        base += f"（{param}）"
    return base


def render_interaction_menu(
    interactions: Sequence[Mapping[str, Any]],
    *,
    heard: Optional[Iterable[str]] = None,
    conditions: Optional[Mapping[int, bool]] = None,
    page: int = 0,
    max_options: int = MENU_MAX_OPTIONS,
) -> dict:
    """NPC 交互菜单渲染（S3 MENU · §四 ≤6 折叠 + 固定 N.离开，L108-113 / TC-06/19/20/21，纯函数）。

    - 首页显示前 max_options（默认 6）个选项 + 折叠「N.更多…」+ 固定「N.离开」；
      离开 N = 本页可见项数 + 1（折叠页把「更多」算一项，TC-06 口径：8 选项 → 6 项 + 7.更多 + 8.离开）。
    - 二级页（page=1）按原序号续显剩余选项 + 本页可见项数+1 的离开（二级页编号定稿未定义【工程补白】）。
    - 已听（信息类交付，heard 含该选项 info_key）→ 后缀「（已听）」（L86-87）。
    - 条件不满足选项（conditions 0-based idx → False）→ 后缀「（需要：…）」一行提示（L112/L121）。
    - 返回 {lines, page, folded, shown, first_index, more_no, leave_no, option_count}，
      供 resolve_menu_selection 按本页编号解析选择。
    """
    heard = set(heard or ())
    total = len(interactions)
    if page <= 0:
        shown = min(total, max_options)
        folded = total > max_options
        first = 0
        more_no = max_options + 1 if folded else None
        leave_no = shown + (1 if folded else 0) + 1
    else:
        shown = total - max_options
        folded = False
        first = max_options
        more_no = None
        leave_no = shown + 1
    if shown < 0:
        shown = 0

    lines: List[str] = []
    for j in range(first, first + shown):
        it = interactions[j]
        label = str(it.get("text") or it.get("action") or "?")
        info_key = _info_key_of(it, j)
        if info_key and info_key in heard:
            label += "（已听）"
        cond_met = conditions.get(j, True) if conditions is not None else True
        if cond_met is False:
            label += f"（{it.get('hint') or condition_hint(it.get('condition'))}）"
        lines.append(f"{j + 1}.{label}")
    if more_no is not None:
        lines.append(f"{more_no}.更多…")
    lines.append(f"{leave_no}.离开")

    return {
        "lines": lines,
        "page": 0 if page <= 0 else 1,
        "folded": folded,
        "shown": shown,
        "first_index": first + 1,
        "more_no": more_no,
        "leave_no": leave_no,
        "option_count": total,
    }


def resolve_menu_selection(menu: Mapping[str, Any], n: object) -> Tuple[str, Optional[int]]:
    """按菜单页编号解析选择（纯函数）。

    → ("option", idx) 选中选项（0-based interactions 下标）
    → ("more", None)   折叠「更多」（仅首页折叠时）
    → ("leave", None)  固定「N.离开」→ 结束路径（T09）
    → ("invalid", None) 编号不在本页范围
    """
    if not isinstance(n, int) or isinstance(n, bool):
        return ("invalid", None)
    leave_no = menu.get("leave_no")
    more_no = menu.get("more_no")
    first = menu.get("first_index", 1)
    shown = menu.get("shown", 0)
    if n == leave_no:
        return ("leave", None)
    if more_no is not None and n == more_no:
        return ("more", None)
    if first <= n <= first + shown - 1:
        return ("option", n - 1)
    return ("invalid", None)


def _info_key_of(option: Mapping[str, Any], idx: int) -> Optional[str]:
    """信息类选项的已听键（L88 落玩家存档）：interaction["info_key"] 优先，否则 {action}:{index}【工程补白】。"""
    if not isinstance(option, Mapping):
        return None
    if option.get("info_key"):
        return str(option["info_key"])
    action = option.get("action")
    if not action:
        return None
    return f"{action}:{idx + 1}"


# -------------------------------------------------------------------------------------
# 恢复简报（2b2 §2.3 / L94-102）
# -------------------------------------------------------------------------------------
def build_resume_brief(snapshot: Mapping[str, Any], *, npc_name: Optional[str] = None) -> Optional[str]:
    """对话恢复简报（2b2 §2.3 / L94-102，纯函数）。

    - 头部固定「【续·对话】{名字}」（L97）
    - S1 LIST / S2 NPCSEL / S3 MENU → 仅头部（菜单/列表重显，L98）
    - S4 EXEC → 头部 + 长叙述分段位置（「已读第 {page+1} 段，继续阅读」，L101）
    - S5 SUBUI → 头部 + 「上次的『{label}』未完成，请重新选择」（L99-100）
    - S0 IDLE / S6 END → None（无会话不恢复）
    返回 None 表示不可恢复（未激活会话）。
    """
    state = snapshot.get("state")
    if state not in (S_LIST, S_NPCSEL, S_MENU, S_EXEC, S_SUBUI):
        return None
    name = npc_name or snapshot.get("npc_name") or snapshot.get("npc_id") or "?"
    head = f"【续·对话】{name}"
    if state == S_EXEC:
        page = int(snapshot.get("page_index") or 0)
        return f"{head} · 已读第 {page + 1} 段，继续阅读"
    if state == S_SUBUI:
        label = snapshot.get("subui_label") or "该操作"
        return f"{head} · 上次的『{label}』未完成，请重新选择"
    return head


# -------------------------------------------------------------------------------------
# 对话会话状态机（2b2 §二 · 7 态 15 迁移）
# -------------------------------------------------------------------------------------
class DialogSession:
    """对话会话状态机（2b2 §二 · 7 态 / 15 迁移 · 纯对象 · 零 NoneBot）。

    状态变量（§2.0）：{state, npc_id, npc_name, page_index, current_shop_ref, subui_label,
    menu_page, narration}。已听集合不落会话快照（L88 落玩家存档，经 ctx["heard"] 读写）。

    用法（step 返回 dict，见 _result）：
      s = DialogSession()
      r = s.step(("dialog", {"mode": "list"}), ctx)                       # T01 → S1 LIST
      r = s.step(("dialog", {"mode": "index", "value": 1}), ctx)          # T02 → S2 →(T05)→ S3 MENU
      r = s.step(("select", 2), ctx)                                      # T07 → S4 EXEC
      r = s.step(("exec_done", {"shop_refs": ["blacksmith_shop"]}), ctx)  # T10 回菜单（商店移交）
      r = s.step(("continue", None), ctx)                                 # T11 翻段 / 末段 T10
      r = s.step(("exec_done", {"subui": True, "label": "帮忙治疗"}), ctx)  # T12 → S5 SUBUI
      r = s.step(("confirm_done", {"completed": True}), ctx)              # T13 → S3 MENU
      r = s.step(("exit", None), ctx)                                     # T09 → S6 →(T15)→ S0
      r = s.step(("interrupt", None), ctx)                                # 中断：不迁移，落快照即回

    ctx 键（均选填）：
      npcs: Sequence[Mapping] —— 当前地图 visible NPC 列表（T01/T02/T03 解析）
      settings: Mapping —— settings（max_dialog_depth，裁决③）
      heard: Iterable[str] —— 玩家已听集合（读自玩家存档，L88）
      eval_condition: Callable[[object, object], bool] —— 条件求值 hook（缺省懒加载 A2 统一条件引擎）
      condition_ctx: object —— 条件求值上下文（玩家状态）
      npc_interactions: Callable[[str], Sequence] —— 取 NPC interactions 的 hook（缺省从 npc dict 读）
    """

    def __init__(self, *, state: str = S_IDLE, npc_id: Optional[str] = None,
                 npc_name: Optional[str] = None, page_index: int = 0,
                 current_shop_ref: Optional[list] = None, subui_label: Optional[str] = None,
                 menu_page: int = 0, narration: Optional[Sequence[str]] = None) -> None:
        self.state = state
        self.npc_id = npc_id
        self.npc_name = npc_name
        self.page_index = page_index
        self.current_shop_ref = list(current_shop_ref or [])
        self.subui_label = subui_label
        self.menu_page = menu_page
        self.narration = list(narration or [])
        self._exec_option: Optional[Mapping[str, Any]] = None
        self._exec_index: Optional[int] = None
        self._menu: Optional[Mapping[str, Any]] = None

    # -- 快照（JSON 可序列化；已听集合不落快照，L88） ----------------------------------

    def to_snapshot(self) -> dict:
        """会话快照（2b2 §2.3 落盘形态；已听标记不落快照——落玩家存档 L88）。"""
        return {
            "state": self.state,
            "npc_id": self.npc_id,
            "npc_name": self.npc_name,
            "page_index": self.page_index,
            "current_shop_ref": list(self.current_shop_ref),
            "subui_label": self.subui_label,
            "menu_page": self.menu_page,
            "narration": list(self.narration),
            "exec_option": self._exec_option,
            "exec_index": self._exec_index,  # P1-3：EXEC 续读完成需按序号推导 info_key → 已听置灰不丢
        }

    @classmethod
    def from_snapshot(cls, snap: Mapping[str, Any], **overrides) -> "DialogSession":
        """从会话快照恢复（L94-102 断了能续；状态原样重入，不迁移）。"""
        s = cls()
        for k in ("state", "npc_id", "npc_name", "page_index", "current_shop_ref",
                  "subui_label", "menu_page"):
            if k in snap:
                setattr(s, k, snap[k])
        s.narration = list(snap.get("narration") or [])
        s._exec_option = snap.get("exec_option")
        s._exec_index = snap.get("exec_index")  # P1-3：恢复 EXEC 序号，_exec_done 能推导 info_key
        for k, v in overrides.items():
            setattr(s, k, v)
        return s

    # -- 单步迁移入口 ---------------------------------------------------------------

    def step(self, event: object, ctx: Optional[Mapping[str, Any]] = None) -> dict:
        """消费一个事件，执行状态机单步（可自动衔接 T05/T06/T15）。

        event 形态：
          ("dialog", {...})  —— /对话 指令进入（mode: list/index/name，见 parse_dialog_command）
          ("digit", N) / ("select", N) / ("continue", None) / ("exit", None)
          ("exec_done", {...}) —— action handler 完成回调（info_key/is_info/subui/label/shop_refs）
          ("confirm_done", {...}) —— SUBUI 确认完成（completed）
          ("interrupt", None) —— 中断：不迁移状态，落快照即回（2b2 §2.3）
        str 原文自动 classify（非会话子词 → 不消费，返回 kind="command" 走正常解析 R2）。
        """
        ctx = ctx or {}
        if isinstance(event, str):
            sub = classify_session_input(event)
            if sub is None:
                return self._result(None, self.state, self.state, [], "command")
            event = sub
        if not isinstance(event, (tuple, list)) or len(event) < 2:
            return self._result(None, self.state, self.state, [], "bad_event")
        category, value = event[0], event[1]

        if category == "interrupt":
            # 中断不占迁移（2b2 §2.3）：只落快照即回，状态不变
            return self._result(None, self.state, self.state, [], "interrupted")

        if self.state == S_IDLE:
            return self._on_idle(category, value, ctx)
        if self.state == S_LIST:
            return self._on_list(category, value, ctx)
        if self.state == S_NPCSEL:
            return self._result(None, self.state, self.state, [], "npcsel_noop")
        if self.state == S_MENU:
            return self._on_menu(category, value, ctx)
        if self.state == S_EXEC:
            return self._on_exec(category, value, ctx)
        if self.state == S_SUBUI:
            return self._on_subui(category, value, ctx)
        return self._result(None, self.state, self.state, [], "end_noop")

    # -- 各状态事件处理 ---------------------------------------------------------------

    def _on_idle(self, category: str, value: object, ctx: Mapping[str, Any]) -> dict:
        if category != "dialog":
            # IDLE 无会话：纯数字/继续/结束词一律不消费（R4 快捷表/常规指令生效）
            return self._result(None, S_IDLE, S_IDLE, [], "idle_noop")
        mode_value = value if isinstance(value, Mapping) else {}
        mode = mode_value.get("mode")
        npcs = self._visible_npcs(ctx)
        if not npcs:
            # 无 NPC 地图：/对话 仅提示不建会话（L50 / TC-08）
            return self._result(None, S_IDLE, S_IDLE, [DIALOG_EMPTY_MAP_HINT], "empty_map")
        if mode == "list":
            # T01 进入列表
            self.state = S_LIST
            return self._result("T01", S_IDLE, S_LIST, render_npc_list(npcs), "entered_list")
        # T02 序号/名称直进
        npc, _fail = self._resolve_npc(mode_value, npcs)
        if npc is None:
            if mode == "name":
                # 名称未命中：不建会话（1.2 步骤 4 / TC-07）
                return self._result(None, S_IDLE, S_IDLE, [DIALOG_NOT_FOUND_HINT], "name_not_found")
            # 序号超界：失败提示 + 回列表（1.2 步骤 3 / TC-06）
            self.state = S_LIST
            return self._result("T06", S_IDLE, S_LIST,
                                self._index_fail_output(mode_value, npcs), "index_fail",
                                trace=[("T02", S_NPCSEL), ("T06", S_LIST)])
        return self._land_npc(npc, ctx, [("T02", S_NPCSEL)])

    def _on_list(self, category: str, value: object, ctx: Mapping[str, Any]) -> dict:
        npcs = self._visible_npcs(ctx)
        if category == "exit":
            # T04 列表直接结束
            return self._finish([("T04", S_END)], "T04")
        if category == "dialog":
            mode_value = value if isinstance(value, Mapping) else {}
            mode = mode_value.get("mode")
            if mode == "list":
                # 会话激活中 /对话 无参 → 重列列表（自环【工程补白】）
                self._reset_npc()
                return self._result(None, S_LIST, S_LIST, render_npc_list(npcs), "relist")
            return self._pick_from_list(mode_value, npcs, ctx)
        if category in ("digit", "select"):
            # T03 列表选人（纯数字 N / 选择 N）
            return self._pick_from_list({"mode": "index", "value": value}, npcs, ctx)
        return self._result(None, S_LIST, S_LIST, [], "list_noop")

    def _pick_from_list(self, value: Mapping[str, Any], npcs: Sequence[Mapping[str, Any]],
                        ctx: Mapping[str, Any]) -> dict:
        npc, _fail = self._resolve_npc(value, npcs)
        if npc is None:
            if value.get("mode") == "name":
                return self._result("T06", S_LIST, S_LIST,
                                    [DIALOG_NOT_FOUND_HINT] + render_npc_list(npcs),
                                    "name_not_found", trace=[("T03", S_NPCSEL), ("T06", S_LIST)])
            return self._result("T06", S_LIST, S_LIST,
                                self._index_fail_output(value, npcs), "index_fail",
                                trace=[("T03", S_NPCSEL), ("T06", S_LIST)])
        # T03 命中 → S2
        return self._land_npc(npc, ctx, [("T03", S_NPCSEL)])

    def _on_menu(self, category: str, value: object, ctx: Mapping[str, Any]) -> dict:
        if category == "exit":
            # T09 菜单结束（离开/再见/退出）
            return self._finish([("T09", S_END)], "T09")
        if category not in ("digit", "select"):
            return self._result(None, S_MENU, S_MENU, [], "menu_noop")
        n = value
        menu = self._current_menu(ctx)
        kind, idx = resolve_menu_selection(menu, n)
        if kind == "leave":
            # R5 / T09 固定末项 N.离开（N = 选项数 + 1）
            return self._finish([("T09", S_END)], "T09")
        if kind == "more":
            # 折叠「更多」→ 二级页（自环【工程补白】，§四 L111）
            self.menu_page = 1
            return self._result(None, S_MENU, S_MENU, self._menu_lines(ctx), "more_page")
        if kind == "invalid":
            return self._result(None, S_MENU, S_MENU, [f"没有 {n} 号"], "invalid_option")
        # kind == "option" → idx 必为 0-based 下标（resolve_menu_selection 保证）
        assert idx is not None
        interactions = self._npc_interactions(ctx)
        if idx >= len(interactions):
            return self._result(None, S_MENU, S_MENU, [f"没有 {n} 号"], "invalid_option")
        option = interactions[idx]

        # 一次一物：信息类已交付 → 提示「你已经听过了」，留菜单（L87 / TC-11）
        if self._is_info(option):
            info_key = _info_key_of(option, idx)
            if info_key and info_key in self._heard(ctx):
                return self._result(None, S_MENU, S_MENU, [DIALOG_ALREADY_HEARD_HINT],
                                    "already_heard")

        # 条件不满足 → T08 自环留菜单 + 一行提示（L121-122 / TC-10）
        if not self._eval_condition(option.get("condition"), ctx):
            hint = option.get("hint") or condition_hint(option.get("condition"))
            return self._result("T08", S_MENU, S_MENU, [hint], "condition_unmet")

        # 超深软拦（裁决③ / L328）：目标节点内容深度 > max_dialog_depth → 留菜单提示
        node_depth = authored_node_depth(option)
        max_depth = resolve_max_dialog_depth(ctx.get("settings"))
        if is_depth_blocked(node_depth, max_depth):
            return self._result(None, S_MENU, S_MENU, [DIALOG_DEPTH_HINT], "depth_blocked")

        # T07 选交互执行 → S4 EXEC
        self._exec_option = option
        self._exec_index = idx
        self.narration = self._narration_of(option, ctx)
        self.page_index = 0
        self.state = S_EXEC
        out = [self.narration[0]] if self.narration else []
        return self._result("T07", S_MENU, S_EXEC, out, "exec",
                            action=option, handoff=self._handoff_of(option))

    def _on_exec(self, category: str, value: object, ctx: Mapping[str, Any]) -> dict:
        if category == "continue":
            # T11 长叙述翻页（L47 / L101）
            if self.narration and self.page_index < len(self.narration) - 1:
                self.page_index += 1
                return self._result("T11", S_EXEC, S_EXEC,
                                    [self.narration[self.page_index]], "next_page")
            # 末段/无叙述 → 单轮交付回菜单（T10）
            return self._exec_done(ctx, {})
        if category == "exit":
            # 叙述中结束词（L47 继续/退出=翻段/结束）→ 结束
            return self._finish([("T09", S_END)], "T09")
        if category == "exec_done":
            return self._exec_done(ctx, value if isinstance(value, Mapping) else {})
        return self._result(None, S_EXEC, S_EXEC, [], "exec_noop")

    def _on_subui(self, category: str, value: object, ctx: Mapping[str, Any]) -> dict:
        if category == "exit":
            # T14 子界面内结束（L62 / L79；current_shop_ref 离开地图才清——世界层职责）
            return self._finish([("T14", S_END)], "T14")
        if category == "confirm_done":
            payload = value if isinstance(value, Mapping) else {}
            if payload.get("completed") is False:
                label = self.subui_label or "该操作"
                return self._result(None, S_SUBUI, S_SUBUI,
                                    [f"『{label}』未完成，请重新选择"], "subui_unfinished")
            # T13 子界面完成回菜单（L98-100）
            self.state = S_MENU
            return self._result("T13", S_SUBUI, S_MENU, self._menu_lines(ctx),
                                "back_menu", handoff={"type": "subui_done",
                                                      "label": self.subui_label})
        return self._result(None, S_SUBUI, S_SUBUI, [], "subui_noop")

    # -- 内部衔接 --------------------------------------------------------------------

    def _land_npc(self, npc: Mapping[str, Any], ctx: Mapping[str, Any],
                  prefix: List[Tuple[str, str]]) -> dict:
        """T02/T03 解析落地 → S2 →（T05 自动衔接）→ S3 MENU。"""
        self.npc_id = str(npc.get("id"))
        self.npc_name = str(npc.get("name") or self.npc_id)
        self.menu_page = 0
        self.state = S_MENU
        out = self._menu_lines(ctx)
        return self._result("T05", S_NPCSEL, S_MENU, out, "menu",
                            trace=prefix + [("T05", S_MENU)])

    def _exec_done(self, ctx: Mapping[str, Any], payload: Mapping[str, Any]) -> dict:
        """action handler 完成回调：T10 单轮交付回菜单 / T12 进入子界面。"""
        option = self._exec_option or {}
        info_key = payload.get("info_key") or (
            _info_key_of(option, self._exec_index) if self._exec_index is not None else None)
        is_info = bool(payload.get("is_info", self._is_info(option)))
        shop_refs = list(payload.get("shop_refs") or option.get("shop_refs") or [])

        mark_heard: List[str] = []
        if is_info and info_key and info_key not in self._heard(ctx):
            mark_heard.append(info_key)

        if payload.get("subui"):
            # T12 进入子界面（heal 确认 / 任务交付确认 / 领取中，L99-100）
            label = payload.get("label") or option.get("text") or "该操作"
            self.subui_label = str(label)
            self.state = S_SUBUI
            out = [f"请确认：{label}"]
            return self._result("T12", S_EXEC, S_SUBUI, out, "subui",
                                mark_heard=mark_heard, shop_refs=shop_refs,
                                handoff={"type": "subui", "label": self.subui_label})

        # T10 单轮交付回菜单（L86-91 / L98）；商店移交经 shop_refs 上报（裁决 T12/T13 修复）
        self.state = S_MENU
        out: List[str] = []  # type: ignore[no-redef]
        if shop_refs:
            out.append(f"已打开商店：{'、'.join(str(r) for r in shop_refs)}")
        elif is_info:
            out.append("已交付（图鉴可回看）" if info_key else "已交付")
        out += self._menu_lines(ctx, extra_heard=mark_heard)
        handoff = {"type": "shop", "shop_refs": shop_refs} if shop_refs else None
        return self._result("T10", S_EXEC, S_MENU, out, "back_menu",
                            mark_heard=mark_heard, shop_refs=shop_refs, handoff=handoff)

    def _finish(self, prefix: List[Tuple[str, str]], primary: str) -> dict:
        """结束路径单点收尾：落地 S6 →（T15 自动衔接）→ S0 + 事件计数（L289/L98）。"""
        self.state = S_END
        event = dialog_event_key(self.npc_id)
        self._reset_all()
        return self._result("T15", S_END, S_IDLE, [], "ended", events=[event],
                            trace=prefix + [("T15", S_IDLE)], ended=primary)

    # -- 辅助 ------------------------------------------------------------------------

    def _visible_npcs(self, ctx: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        npcs = ctx.get("npcs")
        if not npcs:
            return []
        return [n for n in npcs if n.get("visible", True)]

    def _resolve_npc(self, value: Mapping[str, Any], npcs: Sequence[Mapping[str, Any]]
                     ) -> Tuple[Optional[Mapping[str, Any]], Optional[dict]]:
        mode = value.get("mode")
        if mode == "index":
            n = value.get("value")
            if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= len(npcs):
                return npcs[n - 1], None
            return None, {"kind": "index"}
        # 名称精确匹配（整串，禁空格 L49）
        name = str(value.get("value") or "")
        for n in npcs:
            if str(n.get("name")) == name:
                return n, None
        return None, {"kind": "name"}

    def _npc_interactions(self, ctx: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        hook = ctx.get("npc_interactions")
        if callable(hook):
            try:
                out = hook(self.npc_id)
            except Exception:
                out = []
            if isinstance(out, (list, tuple)):
                return [o for o in out if isinstance(o, Mapping)]
            return []
        npcs = ctx.get("npcs") or []
        for n in npcs:
            if str(n.get("id")) == self.npc_id:
                return [o for o in (n.get("interactions") or []) if isinstance(o, Mapping)]
        return []

    def _current_menu(self, ctx: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._menu is not None:
            return self._menu
        interactions = self._npc_interactions(ctx)
        heard = self._heard(ctx)
        conds = {i: self._eval_condition(it.get("condition"), ctx)
                 for i, it in enumerate(interactions)}
        menu = render_interaction_menu(interactions, heard=heard, conditions=conds,
                                       page=self.menu_page)
        self._menu = menu
        return menu

    def _render_menu(self, ctx: Mapping[str, Any],
                     interactions: Sequence[Mapping[str, Any]],
                     extra_heard: Optional[Iterable[str]] = None) -> List[str]:
        heard = self._heard(ctx) | set(extra_heard or ())
        conds = {i: self._eval_condition(it.get("condition"), ctx)
                 for i, it in enumerate(interactions)}
        menu = render_interaction_menu(interactions, heard=heard, conditions=conds,
                                       page=self.menu_page)
        self._menu = menu
        return menu["lines"]

    def _menu_lines(self, ctx: Mapping[str, Any],
                    extra_heard: Optional[Iterable[str]] = None) -> List[str]:
        """交互菜单完整输出（L117-118「铁匠·老周：1.接任务 …」头部 + 折叠 + 固定 N.离开）。"""
        lines = self._render_menu(ctx, self._npc_interactions(ctx), extra_heard=extra_heard)
        if self.npc_name:
            return [f"{self.npc_name}："] + lines
        return lines

    def _heard(self, ctx: Mapping[str, Any]) -> set:
        heard = ctx.get("heard")
        if isinstance(heard, set):
            return set(heard)
        if isinstance(heard, Iterable) and not isinstance(heard, (str, bytes)):
            return set(heard)
        return set()

    def _is_info(self, option: Mapping[str, Any]) -> bool:
        """信息类判定（L86-89 / 审查_M4实现_批次3_jspace.md P1-1）：显式 info:true 优先，否则 action∈INFO_ACTIONS。

        注意：reply 不在 INFO_ACTIONS（闲聊不触发一次一物/不置灰可重复，2b1 AC10）；
        「info: false」逃生口对 reply 生效；若某 reply 确需按信息类，须显式 "info": true。
        """
        if option.get("info") is True:
            return True
        return option.get("action") in INFO_ACTIONS

    def _eval_condition(self, cond: object, ctx: Mapping[str, Any]) -> bool:
        if not cond:
            return True
        hook = ctx.get("eval_condition")
        if callable(hook):
            try:
                return bool(hook(cond, ctx.get("condition_ctx")))
            except Exception:
                return False
        # 缺省：A2 统一条件引擎（fail-safe → False，D-03 工程补白）
        try:
            from qbot_rpg.engine.condition_engine import eval_condition as _a2
            return bool(_a2(cond, ctx.get("condition_ctx") or {}))
        except Exception:
            return False

    def _narration_of(self, option: Mapping[str, Any], ctx: Mapping[str, Any]) -> List[str]:
        """EXEC 叙述段（intel/tutorial 信息类多段 + reply 闲聊 text[]，sub_dialog 节点以叙述交付【工程补白】）。

        功能类（quest/shop/heal/give_item/buff/repair/teleport/dealer）不产叙述（handler 经
        exec_done 回执）；叙述型动作（信息类 + reply，AC10 text[]）取 lines/narration/content/text
        多段（列表或单字符串，审查_M4实现_批次3_jspace.md P1-2）；sub_dialog 节点取
        子节点 greeting + 各选项文本。
        """
        hook = ctx.get("get_narration")
        if callable(hook):
            try:
                out = hook(self.npc_id, option)
            except Exception:
                out = None
            if isinstance(out, (list, tuple)):
                return [str(x) for x in out]
        sub = option.get("sub_dialog") or option.get("dialog_node")
        if isinstance(sub, Mapping):
            segs = []
            if sub.get("greeting"):
                segs.append(str(sub["greeting"]))
            for opt in sub.get("options") or []:
                segs.append(str(opt.get("text") or opt.get("action") or "…"))
            return segs
        # 叙述型动作才取叙述：信息类（intel/tutorial）置灰交付 + 闲聊 reply（P1-2 补 text[]）；
        # 其余功能类（quest/shop/heal/give_item/buff/repair/teleport）不产叙述。
        if not self._is_info(option) and option.get("action") != "reply":
            return []
        for key in ("lines", "narration", "content", "text"):
            val = option.get(key)
            if isinstance(val, list):
                return [str(x) for x in val]
            if isinstance(val, str) and val.strip():
                return [val]
        return []

    def _handoff_of(self, option: Mapping[str, Any]) -> Optional[dict]:
        shop_refs = option.get("shop_refs")
        if shop_refs:
            return {"type": "shop", "shop_refs": list(shop_refs)}
        return None

    def _index_fail_output(self, value: Mapping[str, Any],
                           npcs: Sequence[Mapping[str, Any]]) -> List[str]:
        n = value.get("value")
        lines = [f"没有 {n} 号"]
        lines += render_npc_list(npcs)
        return lines

    def _reset_npc(self) -> None:
        self.npc_id = None
        self.npc_name = None
        self._exec_option = None
        self._exec_index = None
        self._menu = None
        self.menu_page = 0
        self.narration = []
        self.page_index = 0
        self.subui_label = None

    def _reset_all(self) -> None:
        self._reset_npc()
        self.state = S_IDLE
        self.current_shop_ref = []

    def _result(self, transition: Optional[str], from_state: str, to_state: str,
                output: Sequence[str], kind: str, *, trace: Optional[List[Tuple[str, str]]] = None,
                events: Optional[Iterable[str]] = None, mark_heard: Optional[Iterable[str]] = None,
                shop_refs: Optional[Iterable[str]] = None, action: Optional[Mapping[str, Any]] = None,
                handoff: Optional[dict] = None, ended: Optional[str] = None) -> dict:
        if trace is None:
            trace = [(transition, to_state)] if transition else []
        return {
            "transition": transition,
            "trace": list(trace),
            "from_state": from_state,
            "to_state": to_state,
            "output": list(output),
            "kind": kind,
            "events": list(events or []),
            "mark_heard": list(mark_heard or []),
            "shop_refs": list(shop_refs or []),
            "action": action,
            "handoff": handoff,
            "ended": ended,
            "session_active": self.state not in (S_IDLE, S_END),
            "snapshot": self.to_snapshot(),
        }
