"""基础指令组接线 basic_commands.py（M4 批次6·路G1 · qbot_rpg/commands/basic_commands.py）。

依据：m4_shared_contract §2.3 + 4f + 裁决②
  - m4_shared_contract.md §2.3（基础指令组：/角色 /背包 /装备 /技能 /帮助 等，4f RUL-01~34，
    页码夹取口径）+ §2.2（列表 5 条/页上限、页脚固定 TPL-08、页码越界夹取 +「已到最后一页」
    2026-08-27 用户裁决②、0/负数/非数字 → TPL-12、错误模板统一、emoji 纪律：
    icon 字段渲染剥离 emoji（M5 裁决「不用 emoji」；m4 §2.2 数据型功能图标豁免已作废，以 docs/全局图标登记表.md 为准））
  - docs/细化/细化_4f_基础指令组契约.md（RUL-01~34：/状态 面板五区 B4 裁决 → 本路 /角色 承载
    「LV 行固定头部 + 属性三层结构」玩家面板；/背包 RUL-16~19 行格式与分页；/装备 4b §三 装备栏
    穿戴；/技能 6a 技能库字段 + M2 技能卡「LV 行固定头部 + 派生指向」；/帮助 RUL-20~25 分组目录
    与 GM 保密、RUL-08 注册门槛 + B6 /帮助 豁免）
  - docs/细化/细化_3d_消息模板规范.md（TPL-08 页脚 / TPL-12 指令出错 / D-01 emoji 禁令 / D-04 错误
    文案唯一源 / §2.2 页码输入 + 裁决② 尾注）
  - docs/细化/细化_3b_玩家属性三层.md（白值/加成/临时三层结构 → /角色 面板，管线出口
    qbot_rpg/core/player_attributes.calc_all_final_attributes）
  - docs/细化/细化_6a_技能库契约.md（skills.json 字段：type/mp_cost/desc/chain_refs/job_restrict；
    chain_refs → skill_chains.json 派生链 → 「可派生成：XX」指向）
  - docs/细化/细化_4b_物品与背包契约.md（INV-01~07 行结构 + RUL-19 行格式：图标/×数量/品质/绑定；
    icon 字段渲染剥离 emoji（M5 裁决「不用 emoji」，docs/全局图标登记表.md 作废 m4 §2.2 数据型图标豁免）
    排序 acquired_at 倒序 INV-07/RUL-17）
  - 2026-08-27 用户裁决②（列表页码超总页数 → 夹取最后一页 +「已到最后一页」；0/负数/非数字 → TPL-12）

职责（细化_3a §1.3 壳层职责 · 唯一指令执行壳）：把 /角色 /背包 /装备 /技能 /帮助 五条基础指令从
Router 接到 core 层——指令解析（parsers.parse_command 已 token 化 → 本模块取页码/子词/序号）、
玩家面板/背包/装备栏/技能列表渲染（core/message_format/list_render 5 条/页 + 裁决② 夹取；
尾段统一 CakeGame 式「当前页 + Tip」render_cake_tail，2026-08-27 用户拍板）、
装备穿卸委托装备引擎（core/equipment.py，M6 批1 已实装 EquipmentEngine + 适配层，
注入优先 → 懒加载 →【待接线】RuntimeError，与 checkin_commands 同模式）、错误统一
TPL-12（sender.format_tpl12，文案唯一源 errors.py D-04）。

铁律（m4_shared_contract §0 / 3a R1）：**零 NoneBot import**、纯函数、确定性（now/rng 由 ctx
注入）；工程补白一律【工程补白】标注；错误走 TPL-12 统一模板；装饰性 emoji 全局禁用（仅 ✅/❌
功能性标记；icon 字段渲染剥离 emoji（M5 裁决，m4 §2.2 豁免已作废，登记表为准）。本模块只做「装配接线 + 渲染」，状态变更全部委托引擎。

--------------------------------------------------------------------------------
消费接口（core/equipment.py · M6 批次1·路A 已实装 · EQP-12 适配层，注入优先）：
  EquipmentEngineAdapter（本文件）实现 equip_wear(index: int, ctx) -> dict {ok, message}
  / equip_remove(slot_id: str, ctx) -> dict {ok, message}：包装真实
  core.equipment.EquipmentEngine.equip/unequip，从 ctx["player"]（可变 dict）解析背包
  ItemInstance 并就地更新玩家状态，组装中文消息（EQP-E1~E5 边界文案）。
  ctx["equip_engine"] 注入优先（装配层注入适配器 / 测试注入替身）；
  未注入 → _equip_engine 懒加载构造 EquipmentEngineAdapter（EQP-12 兜底）。
  （装备栏渲染由本层纯函数从 ctx["equipment"] 直读，不依赖引擎）

--------------------------------------------------------------------------------
【工程补白 · 显式标注】
  1) **5 条/页横切由本层统一**：/角色 属性三层明细、/背包 物品行、/装备 槽位、/技能 技能行、
     /帮助 目录/组页 全部按 m4 §2.2 5 条/页；尾段统一 CakeGame 式「当前页 + Tip 尾行」
     （render_cake_tail，2026-08-27 用户拍板，替代 TPL-08 页脚）：当前页恒显示 + 各指令定制
     Tip（/角色=查看当前装备、/装备=穿戴、/技能=技能说明、/帮助=翻页查看指令；/背包/背包筛选
     带货币行 + 类型词）。
  2) **4f TPL-4F-06 目录页脚「输入 /帮助 组名 翻页」归一**：2026-08-27 用户拍板后基础指令组
     列表尾段不再用 TPL-08，统一 CakeGame 式（当前页 + Tip）；/帮助 目录/组页 Tip =
     「发送'帮助 组名'翻页查看指令」。
  3) **/角色 = 玩家属性面板（B4 裁决承接）**：4f /状态 面板五区中「前缀行/位置行/效果区」由装配层
     prefix_render 与后续批次承接；本路 /角色 聚焦任务口径「LV 行固定头部 + 属性三层结构
     （白值/加成/临时）」，9 项属性 5 条/页 = 2 页 + CakeGame 尾段（当前页 + Tip）+ 裁决② 夹取。resource 型（生命/魔力）
     显示 当前/上限（当前取 ctx["hp"]/ctx["mp"]）；最终值经 3b 管线 calc_all_final_attributes。
  4) **/装备 不加翻页（意见一同步）**：面板一次性展示全部已装备槽位（头部 `【装备】`、
     槽位行去序号、空槽不显示、Tip「使用 序号」）；切换装备走显式子词
     「穿 <序号>」（背包序号）/「卸 <槽位>」（槽位名/id/序号，本层 resolve_equip_slot 纯
     解析 → 引擎）；槽位名/序号解析失败 = 值域文案「❌ 没有这个装备槽位」（命令合法，不走 TPL-12，
     对齐 quest「任务不存在」口径）。
  5) **/技能 派生指向**：skill.chain_refs → ctx["skill_chains"] 链定义（steps[].from == 本技能 →
     收集 steps[].to → 技能名解析，1c2 派生链语义）；无派生链 → 不输出「可派生成」。技能按
     type 排序 basic→active→passive→trigger（6a §1.5 普攻固定第 1 位），job_restrict 过滤当前职业。
  6) **/帮助 分组目录**：内置分组表（冒险/战斗/成长/制造生活/快捷 + GM 组 B8 仅 GM 渲染）；
     普通玩家 5 组单页；GM 6 组 2 页（带 CakeGame 尾段）；组内指令列表 5 条/页。未注册玩家返回注册引导版
     （B6 豁免）。GM 判定读 ctx["is_gm"]（缺省 False=普通玩家，对齐 RUL-25 静默隐藏）。
  7) **注册门槛（RUL-08）**：/角色 /背包 /装备 /技能 在 ctx["registered"] is False 时统一返回
     「❌ 请先 /注册 创建角色（/注册 名字 职业）」；/帮助 豁免（B6）。ctx 缺省 registered=True
     （未注入时不拦截，保持既有命令壳纯函数可测）。
  8) **/背包 数据源**：ctx["inventory"]（ItemInstance 或 dict 行均可，兼容 4a 存档行形态）优先，
     ctx["player"].inventory 兜底；排序 = acquired_at 倒序（INV-07/RUL-17），无时间字段保持存储序
     （稳定排序）；图标读 items.json 配置（渲染剥离 emoji，M5 裁决；m4 §2.2 数据型图标豁免已作废），缺省不显示。
  9) 本模块的玩家上下文工厂 make_context（NoneBot 事件 + 存储 → ctx dict）由装配层注入
     （register_basic_commands 的 make_context 参数），**批次7 装配待接线**；注入前本层可纯
     函数单测（直接构造 ctx + 注入真实/替身装备引擎）。
  10) **/装备 换真实引擎（EQP-12 / D1 P1-5 ③）**：EquipmentEngineAdapter 包装真实
     core.equipment.EquipmentEngine（M6 路A 已实装），保持 equip_wear/equip_remove 消费接口
     签名（不破坏既有 FakeEquipEngine 注入测试）；未注入时懒加载兜底（_equip_engine）。
  11) **/帮助 别名显示替换（SHC-04 / 4f RUL-24 / TC-17）**：目录行与组页指令名按
     settings.command_aliases 显示层替换（keep_original:false → 仅显别名；true → 双名并显）；
     解析/触发走 router/parsers 别名机制（既有），本层只做显示层替换。
"""

from __future__ import annotations

import importlib
from typing import Any, Callable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from qbot_rpg.core.equipment import EquipmentEngine
from qbot_rpg.core.message_format import strip_icon_emoji
from qbot_rpg.core.message_format.list_render import (
    DEFAULT_PAGE_SIZE,
    LAST_PAGE_HINT,
    render_cake_tail,
    resolve_page,
)
from qbot_rpg.core.player_attributes import calc_all_final_attributes
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.logging_utils import get_logger
from qbot_rpg.data.player import EquipmentSlot, Player, PlayerAttributes

# 同包兄弟模块：相对导入（G0 架构门禁 test_commands_web_not_depended 不产生
# `qbot_rpg.commands` 前缀反向依赖边；同层兄弟引用架构合规，与 sender.py 同口径）。
from .parsers import parse_int
from .router import CommandSpec
from .sender import format_tpl12

__all__ = [
    # 指令名 / 子指令词
    "VIEW_CMD", "BAG_CMD", "BAG_FILTER_CMD", "EQUIP_CMD", "SKILL_CMD", "HELP_CMD",
    "VIEW_DETAIL_CMD", "cmd_view_detail",
    "SUB_WEAR", "SUB_REMOVE",
    # 渲染常量
    "TPL_REGISTER_GATE", "TPL_EMPTY_BAG", "TPL_NO_SLOT", "TPL_EQUIP_NAME_HINT",
    "QUALITY_LABELS", "TYPE_LABELS", "DEFAULT_SLOT_NAMES",
    "HELP_GROUPS", "GM_HELP_GROUP", "GROUP_ORDER",
    # 指令处理器（纯函数：parsed + ctx → 回复正文）
    "cmd_view", "cmd_bag", "cmd_equip", "cmd_skill", "cmd_help",
    # 渲染 / 工具
    "attr_line", "bag_line", "equip_line", "skill_line", "group_page_line",
    "resolve_equip_slot", "parse_page_arg", "view_header", "skill_rows",
    "EquipmentEngineAdapter",
    # 装配
    "register_basic_commands",
]

# ---------------------------------------------------------------------------
# 常量：指令名 / 子指令词 / 业务文案
# ---------------------------------------------------------------------------

VIEW_CMD = "角色"
VIEW_DETAIL_CMD = "角色详细"  # 2026-08-27 用户拍板：/角色 简洁版 + /角色详细 三层明细
BAG_CMD = "背包"
EQUIP_CMD = "装备"
SKILL_CMD = "技能"
MY_SKILL_CMD = "我的技能"  # 2026-08-30 实机反馈：玩家用「我的技能」→ 映射 技能（别名）
HELP_CMD = "帮助"

# 装备子指令词（非解析器固定子词，经 args 位置参数识别；对齐 checkin「状态/补签」模式）
SUB_WEAR = "穿"
SUB_REMOVE = "卸"

# RUL-08 注册门槛（4f §1.4 / TC-05；/帮助 豁免见 B6）
TPL_REGISTER_GATE = "❌ 请先 /注册 创建角色（/注册 名字 职业）"

# /背包 空背包（4f §3.4 边界：对齐 L1353 反向兜底）
TPL_EMPTY_BAG = "❌ 背包空空如也"

# /装备 槽位解析失败（值域问题，命令合法，不走 TPL-12；工程补白 4）
TPL_NO_SLOT = "❌ 没有这个装备槽位"

# /装备 名称形式（如 /装备 铁剑）→ 友好提示引导序号用法（P2-11 QA：名称被泛化
# 拒绝回「❌ 指令不正确」，应提示 /装备 <序号>；命令合法，不走 TPL-12，对齐 TPL_NO_SLOT）
TPL_EQUIP_NAME_HINT = "❌ 装备指令：请用 /装备 穿 <序号> 穿戴（序号见 /背包），如 /装备 穿 3"

# 品质四档（4b GRD-x 唯一注册表；RUL-19：仅非 normal 档标注）
QUALITY_LABELS: Mapping[str, str] = {
    "normal": "",
    "fine": "精良",
    "epic": "史诗",
    "legendary": "传说",
}

# 技能 type 四类中文（6a §1.4）
TYPE_LABELS: Mapping[str, str] = {
    "basic": "普攻",
    "active": "主动",
    "passive": "被动",
    "trigger": "触发",
}

# 装备槽位缺省中文名（slots.json 未配置时兜底；EQP-04 slot_schema 引用）
DEFAULT_SLOT_NAMES: Mapping[str, str] = {
    "weapon": "武器",
    "armor_head": "头部",
    "armor_body": "身体",
    "armor_hand": "手部",
    "armor_leg": "腿部",
    "armor_foot": "脚部",
}

# 槽位缺省顺序（4b §3.1：武器 + 五部位；ctx["slot_order"] 可覆盖）
DEFAULT_SLOT_ORDER: tuple = (
    "weapon", "armor_head", "armor_body", "armor_hand", "armor_leg", "armor_foot",
)

# 属性名兜底（stats.json name 缺失时；4f RUL-12 全中文）
_DEFAULT_STAT_NAMES: Mapping[str, str] = {
    "hp": "生命", "mp": "魔力", "str": "力量", "int": "智力", "con": "体质",
    "spr": "精神", "foc": "专注", "agi": "敏捷", "lck": "幸运",
}

# 属性默认展示顺序（stats.json 键序缺失时；九预置 3b §4.1）
_DEFAULT_STAT_ORDER: tuple = ("hp", "mp", "str", "int", "con", "spr", "foc", "agi", "lck")

# /帮助 分组目录（4f RUL-21 六组顺序：冒险/战斗/成长/制造生活/快捷/GM；组内指令按框架章节顺序）
HELP_GROUPS: Tuple[Tuple[str, Tuple[Tuple[str, str], ...]], ...] = (
    ("冒险", (("角色", "查看角色属性面板"), ("背包", "查看背包物品"), ("装备", "查看/切换装备"),
              ("位置", "查看当前地点"), ("进入", "进入地图"), ("休息", "休息恢复"))),
    ("战斗", (("攻击", "选择技能攻击目标"), ("技能", "查看技能列表"))),
    ("成长", (("使用", "使用物品/穿戴装备"), ("强化", "强化装备"), ("转职", "转职职业"))),
    ("制造生活", (("合成", "合成物品"), ("炼金", "炼金制作"), ("锻造", "锻造装备"),
                   ("采集", "采集资源"))),
    ("快捷", (("快捷绑定", "绑定快捷指令"), ("快捷解绑", "解绑快捷指令"),
              ("快捷列表", "查看快捷列表"))),
)

# GM 组（RUL-25：无 GM 权限不渲染、不提示存在；GM 可见）
GM_HELP_GROUP: Tuple[str, Tuple[Tuple[str, str], ...]] = (
    "GM", (("重载", "重载内容包"), ("封禁", "封禁玩家"), ("日志", "查看日志"),
           ("编辑", "编辑配置"), ("设置", "设置参数")),
)

# 分组名常量（目录页/组页引用）
GROUP_ORDER: Tuple[str, ...] = tuple(g[0] for g in HELP_GROUPS) + (GM_HELP_GROUP[0],)

# /帮助 注册引导版（B6：仅分组目录+注册/状态/背包 三项引导，4f B6 裁决原文；单页无页脚）
_REGISTER_GUIDE: str = "\n".join([
    "【新手引导】发 /注册 名字 职业 创建角色",
    "注册 —— 创建角色（未注册必需）",
    "状态 —— 查看角色状态面板",
    "背包 —— 查看背包物品",
    "装备/技能 等更多指令注册后可用，发 /帮助 查看完整列表",
])

# 目录头（4f TPL-4F-06）
_DIRECTORY_TITLE = "【指令总览】输入 /帮助 组名 查看该组指令"


# ---------------------------------------------------------------------------
# 工具（纯函数）
# ---------------------------------------------------------------------------

def _fragment(parsed: Any) -> str:
    """TPL-12 原文片段（parsed.raw 优先；缺省重构）。"""
    if getattr(parsed, "raw", None):
        return str(parsed.raw)
    cmd = getattr(parsed, "command", None) or ""
    args = getattr(parsed, "args", None) or []
    tail = (" " + " ".join(str(a) for a in args)) if args else ""
    return f"/{cmd}{tail}"


def _fmt_num(v: object) -> str:
    """数值渲染：整数去小数、浮点去尾零、非法原样。"""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v == int(v):
            return str(int(v))
        s = f"{v:.2f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-0") else "0"
    return str(v)


def _fmt_bonus(flat: float, pct: float) -> str:
    """加成/临时层摘要：`+5·+10%`；双零 → `0`。"""
    parts: List[str] = []
    if flat:
        parts.append(f"+{_fmt_num(flat)}")
    if pct:
        parts.append(f"+{_fmt_num(pct)}%")
    return "·".join(parts) if parts else "0"


def parse_page_arg(text: Optional[str]) -> Optional[int]:
    """页码参数归一：None → 1；整数 ≥1 → 原值；0/负数/非数字 → None（壳层转 TPL-12，裁决②）。"""
    if text is None:
        return 1
    n = parse_int(text)
    if n is None or n < 1:
        return None
    return n


def _gate(ctx: Mapping[str, Any]) -> Optional[str]:
    """RUL-08 注册门槛：ctx["registered"] is False → 拦截文案；缺省视为已注册（工程补白 7）。"""
    if ctx.get("registered", True) is False:
        return TPL_REGISTER_GATE
    return None


# ---------------------------------------------------------------------------
# /角色：玩家属性面板（LV 行固定头部 + 属性三层结构，5 条/页 + TPL-08 + 裁决②）
# ---------------------------------------------------------------------------

def _player_fields(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    """玩家基础字段归一（ctx 直取 → ctx["player"] dataclass 兜底）。"""
    p = ctx.get("player")
    if p is not None and not isinstance(p, Mapping):
        return {
            "name": str(getattr(p, "name", None) or ctx.get("name") or "?"),
            "level": int(getattr(p, "level", None) or ctx.get("level") or 1),
            "exp": getattr(p, "exp", None) if getattr(p, "exp", None) is not None else ctx.get("exp"),
            "job_id": str(getattr(p, "job_id", None) or ctx.get("job_id") or ""),
            "hp": getattr(p, "hp", None) if getattr(p, "hp", None) is not None else ctx.get("hp"),
            "mp": getattr(p, "mp", None) if getattr(p, "mp", None) is not None else ctx.get("mp"),
        }
    return {
        "name": str(ctx.get("name") or "?"),
        "level": int(ctx.get("level") or 1),
        "exp": ctx.get("exp"),
        "job_id": str(ctx.get("job_id") or ""),
        "hp": ctx.get("hp"),
        "mp": ctx.get("mp"),
    }


def _job_name(ctx: Mapping[str, Any], job_id: str) -> Optional[str]:
    """职业 id → 中文名（ctx["jobs"] 映射；缺失返回 None）。"""
    if not job_id:
        return None
    jobs = ctx.get("jobs")
    if isinstance(jobs, Mapping):
        d = jobs.get(job_id)
        if isinstance(d, Mapping):
            return str(d.get("name")) if d.get("name") else None
        if d is not None and hasattr(d, "get"):
            n = d.get("name")
            return str(n) if n else None
    return None


def _base_header(ctx: Mapping[str, Any], label: str) -> str:
    """LV 行固定头部基座：`【{label}】Lv3.阿伟（战士）`。"""
    f = _player_fields(ctx)
    job = str(ctx.get("job_name") or _job_name(ctx, f["job_id"]) or "?")
    return f"【{label}】Lv{f['level']}.{f['name']}（{job}）"


def view_header(ctx: Mapping[str, Any]) -> str:
    """LV 行固定头部（4f RUL-11 + 任务口径）：`【角色】Lv3.阿伟（战士） ｜ 经验 320/1000`。"""
    head = _base_header(ctx, "角色")
    f = _player_fields(ctx)
    max_lv = ctx.get("max_level")
    if max_lv is not None and f["level"] >= int(max_lv):
        head += " ｜ 【已满级】"
    elif f["exp"] is not None:
        nxt = ctx.get("exp_next")
        if nxt is not None:
            head += f" ｜ 经验 {_fmt_num(f['exp'])}/{_fmt_num(nxt)}"
        else:
            head += f" ｜ 经验 {_fmt_num(f['exp'])}"
    return head


def _to_attributes(ctx: Mapping[str, Any]) -> PlayerAttributes:
    """属性三层归一为 PlayerAttributes（3b §4.4 三子层键空间；dict 形态兼容，工程补白 3）。"""
    attrs = ctx.get("attributes")
    if isinstance(attrs, PlayerAttributes):
        return attrs
    raw = attrs if isinstance(attrs, Mapping) else ctx.get("attr_layers")
    if raw is None:
        raw = {}
    bonus = dict(raw.get("bonus") or {}) if isinstance(raw.get("bonus"), Mapping) else {}
    temp = dict(raw.get("temp") or {}) if isinstance(raw.get("temp"), Mapping) else {}
    return PlayerAttributes(
        base=dict(raw.get("base") or {}),
        bonus={
            "flat": dict(bonus.get("flat") or {}),
            "pct": dict(bonus.get("pct") or {}),
        },
        temp={
            "pct": dict(temp.get("pct") or {}),
            "flat": dict(temp.get("flat") or {}),
        },
        cond=dict(raw.get("cond") or {}),
    )


def _stat_name(ctx: Mapping[str, Any], attr_id: str) -> str:
    """属性 id → 中文名（stats.json 配置优先；缺省兜底表）。"""
    stats = ctx.get("stats")
    if isinstance(stats, Mapping):
        d = stats.get(attr_id)
        if isinstance(d, Mapping) and d.get("name"):
            return str(d["name"])
        if d is not None and hasattr(d, "get"):
            n = d.get("name")
            if n:
                return str(n)
    return _DEFAULT_STAT_NAMES.get(attr_id, attr_id)


def _stat_order(ctx: Mapping[str, Any], attrs: PlayerAttributes) -> List[str]:
    """属性展示顺序：stats.json 键序优先（含最终键并集），缺省九预置顺序。"""
    stats = ctx.get("stats")
    if isinstance(stats, Mapping) and stats:
        order = [str(k) for k in stats.keys()]
    else:
        order = list(_DEFAULT_STAT_ORDER)
    union = set(attrs.base) | set(attrs.flat_bonus()) | set(attrs.pct_bonus()) \
        | set(attrs.temp_flat()) | set(attrs.temp_pct()) | set(attrs.cond)
    for k in union:
        if k not in order:
            order.append(k)
    return order


def attr_line(attr_id: str, stat_name: str, final: int,
              attrs: PlayerAttributes, current: Optional[int] = None,
              *, detail: bool = False) -> str:
    """属性行（无序号，2026-08-27 用户拍板 /角色 面板属性前不加序号）：
    detail=False（/角色 简洁版）→ `【力量】29` / resource `【生命】30/100`；
    detail=True（/角色详细 完整版）→ `【力量】29（白值 15 ｜ 加成 +5·+10% ｜ 临时 +3·+20%）`。"""
    if not detail:
        if current is not None:
            return f"【{stat_name}】{_fmt_num(current)}/{final}"
        return f"【{stat_name}】{final}"
    base = float(attrs.base.get(attr_id, 0.0))
    flat = float(attrs.flat_bonus().get(attr_id, 0.0))
    pct = float(attrs.pct_bonus().get(attr_id, 0.0))
    tflat = float(attrs.temp_flat().get(attr_id, 0.0))
    tpct = float(attrs.temp_pct().get(attr_id, 0.0))
    bonus = _fmt_bonus(flat, pct)
    temp = _fmt_bonus(tflat, tpct)
    if current is not None:
        return f"【{stat_name}】{_fmt_num(current)}/{final}（白值 {_fmt_num(base)} ｜ 加成 {bonus} ｜ 临时 {temp}）"
    return f"【{stat_name}】{final}（白值 {_fmt_num(base)} ｜ 加成 {bonus} ｜ 临时 {temp}）"


def _render_attr_page(ctx: Mapping[str, Any], page: int, *, detail: bool = False) -> str:
    """/角色 正文：LV 行固定头部 + 属性行 5 条/页 + CakeGame 式尾段 + 裁决② 夹取。

    detail=False（/角色）→ 简洁属性行；detail=True（/角色详细）→ 三层明细行。"""
    attrs = _to_attributes(ctx)
    f = _player_fields(ctx)
    final = calc_all_final_attributes(
        attrs,
        conditional_rules=ctx.get("conditional_rules") or (),
        resource_pct=_resource_pct(ctx),
        attr_types=ctx.get("attr_types"),
    )
    order = _stat_order(ctx, attrs)
    items: List[Tuple[str, Optional[int]]] = []
    for attr_id in order:
        if attr_id not in final:
            continue
        current = None
        if attr_id in ("hp", "mp"):
            cur = f.get(attr_id)
            current = int(cur) if cur is not None else None
        items.append((attr_id, current))
    res = resolve_page(page, len(items), DEFAULT_PAGE_SIZE)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 parse_page_arg 判定并转 TPL-12（3d §2.2/裁决②）"
        )
    assert res.page is not None
    start = (res.page - 1) * DEFAULT_PAGE_SIZE
    slice_items = items[start:start + DEFAULT_PAGE_SIZE]
    lines: List[str] = [view_header(ctx)]
    for i, (attr_id, cur) in enumerate(slice_items):
        lines.append(attr_line(attr_id, _stat_name(ctx, attr_id),
                               final[attr_id], attrs, current=cur, detail=detail))
    if items:
        lines.append(_cake_tail(res.page, res.total_pages, tip=_VIEW_TAIL_TIP, clamped=res.clamped))
    return "\n".join(lines)


def _resource_pct(ctx: Mapping[str, Any]) -> bool:
    """settings.resource_pct（3b ADR-02：resource 型百分比默认关）。"""
    settings = ctx.get("settings")
    if isinstance(settings, Mapping):
        return bool(settings.get("resource_pct", False))
    return False


def cmd_view(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/角色 [页码]：玩家属性面板（LV 行固定头部 + 属性三层结构 5 条/页 + TPL-08 + 裁决② 夹取；
    0/负数/非数字 → TPL-12；超参/未知子词 → TPL-12）。"""
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if getattr(parsed, "fixed_subword", None):
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if len(args) > 1:
        return format_tpl12(_fragment(parsed))
    page = parse_page_arg(args[0] if args else None)
    if page is None:
        return format_tpl12(_fragment(parsed))
    return _render_attr_page(ctx, page)


def cmd_view_detail(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/角色详细 [页码]：完整属性面板（三层明细：白值/加成/临时，2026-08-27 用户拍板
    /角色 简洁、/角色详细 才显示三层；5 条/页 + CakeGame 式尾段 + 裁决② 夹取）。"""
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if getattr(parsed, "fixed_subword", None):
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if len(args) > 1:
        return format_tpl12(_fragment(parsed))
    page = parse_page_arg(args[0] if args else None)
    if page is None:
        return format_tpl12(_fragment(parsed))
    return _render_attr_page(ctx, page, detail=True)


# ---------------------------------------------------------------------------
# /背包：物品列表（5 条/页 + ×数量/品质/绑定 + TPL-08 + 裁决②）
# ---------------------------------------------------------------------------

def _inventory_rows(ctx: Mapping[str, Any]) -> list:
    """背包行归一（ctx["inventory"] 优先 → ctx["player"].inventory 兜底）；按 acquired_at 倒序
    （INV-07/RUL-17），无时间字段保持存储序（稳定排序，工程补白 8）。"""
    # M8 批12 装配层 inventory 双形态（context.py L976/L1053）：ctx["inventory"] =
    # {item_id: count} 计数映射（任务/条件引擎消费），ctx["inventory_items"] =
    # list[ItemInstance] 展示列表。本函数是展示入口 → 必须优先读 inventory_items，
    # 否则把计数映射的 key 当行 → 物品名全 [?]（实机部署反馈「神必bug」，2026-08-30）。
    inv = ctx.get("inventory_items")
    if inv is None:
        inv = ctx.get("inventory")
    if inv is None:
        player = ctx.get("player")
        if player is not None:
            inv = getattr(player, "inventory", None)
    if isinstance(inv, Mapping):
        rows = []
        for _item_id, _count in inv.items():
            if _count <= 0:
                continue
            rows.append({"item_id": _item_id, "count": _count})
    else:
        rows = list(inv) if inv else []

    def _key(r: Any) -> str:
        if isinstance(r, Mapping):
            t = r.get("acquired_at")
            return str(t) if t is not None else ""
        return ""

    try:
        return sorted(rows, key=_key, reverse=True)
    except TypeError:  # 混合类型时间字段 → 保持原序
        return rows


def _item_icon(ctx: Mapping[str, Any], item_id: str) -> str:
    """物品图标（items.json 配置；M5 裁决不用 emoji——渲染出口剥离 emoji 字符，保纯文本
    /自定义文本符号，作者可配「剑」「+」等；缺省空）。"""
    if not item_id:
        return ""
    items = ctx.get("items")
    if isinstance(items, Mapping):
        d = items.get(item_id)
        if isinstance(d, Mapping):
            return strip_icon_emoji(d.get("icon") or "")
        if d is not None and hasattr(d, "get"):
            return strip_icon_emoji(d.get("icon") or "")
    return ""


def _row_fields(row: Any, ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    """背包行字段归一（ItemInstance dataclass 与 dict 行兼容，4a 存档行形态）。"""
    if isinstance(row, Mapping):
        item_id = str(row.get("item_id") or "")
        name = str(row.get("name") or item_id or "?")
        count = row.get("count", 1)
        quality = str(row.get("quality") or "normal")
        bound = bool(row.get("bound"))
        icon = strip_icon_emoji(str(row.get("icon") or "") or _item_icon(ctx, item_id))
    else:
        item_id = str(getattr(row, "item_id", "") or "")
        name = str(getattr(row, "name", None) or item_id or "?")
        count = getattr(row, "count", 1)
        quality = str(getattr(row, "quality", None) or "normal")
        bound = bool(getattr(row, "bound", False))
        icon = strip_icon_emoji(_item_icon(ctx, item_id))
    try:
        count = int(count)
    except (TypeError, ValueError):
        count = 1
    return {
        "item_id": item_id, "name": name, "count": count,
        "quality": quality, "bound": bound, "icon": icon,
    }


def bag_line(index: int, row: Any, ctx: Mapping[str, Any]) -> str:
    """物品行（用户 2026-08-27 自定义模板）：`{序号}.[{名称}]×{数量}`。

    方括号包名称（标识清晰，替代 icon 显示——M5 不用 emoji 后 icon 剥离，用户模板
    无图标）；×数量**恒显示**（含 ×1，对齐用户模板）；非 normal 品质追加 `（精良）`
    （4b GRD-x 注册表，RUL-19 仅非 normal 标注）；绑定追加 `（绑定）`。`×` 为展示
    符号（输入侧一律 `*`，铁律 1）。
    """
    f = _row_fields(row, ctx)
    line = f"{index}.[{f['name']}]×{f['count']}"
    q = QUALITY_LABELS.get(f["quality"])
    if q:
        line += f"（{q}）"
    if f["bound"]:
        line += "（绑定）"
    return line


def _currency_display_name(ctx: Mapping[str, Any], key: str) -> str:
    """货币键 → 中文名（settings currencies[].name 优先；缺省兜底 coins=金币/gem=钻石，
    框架 §8.1 默认模板「金币 + 钻石」）。"""
    settings = ctx.get("settings")
    currencies = settings.get("currencies") if isinstance(settings, Mapping) else None
    if isinstance(currencies, list):
        for e in currencies:
            if (isinstance(e, Mapping) and str(e.get("key", "")) == str(key)
                    and e.get("name")):
                return str(e["name"])
    return {"coins": "金币", "gem": "钻石"}.get(str(key), str(key))


def _currency_lines(ctx: Mapping[str, Any]) -> List[str]:
    """货币行（用户模板：`金币：0` / `钻石：0`）——遍历 ctx["currencies"]（key→余额）。"""
    cur = ctx.get("currencies")
    if not isinstance(cur, Mapping) or not cur:
        return []
    return [f"{_currency_display_name(ctx, str(k))}：{v}" for k, v in cur.items()]


# CakeGame 式尾段 Tip 内容（`Tip:` 之后部分，2026-08-27 用户拍板统一列表尾段；无斜杠指令名）
_BAG_TAIL_TIP = "发送'使用+物品名'即可使用物品"      # /背包（含货币行 + 类型词）
_VIEW_TAIL_TIP = "发送'装备'查看当前装备"           # /角色（属性面板下一步）
_EQUIP_TAIL_TIP = "发送'使用 序号'穿戴装备。"      # /装备（穿戴引导；意见一同步：Tip 改「使用 序号」）
_SKILL_TAIL_TIP = "发送'帮助 技能'查看技能说明"     # /技能（技能说明引导）
_HELP_TAIL_TIP = "发送'帮助 组名'翻页查看指令"      # /帮助 目录/组页


def _cake_tail(page: int, total_pages: int, *, category_word: Optional[str] = None,
               tip: str = "", clamped: bool = False) -> str:
    """CakeGame 式尾段（当前页 + 可选夹取提示 + Tip 尾行）。

    夹取提示（裁决② LAST_PAGE_HINT）由本层按各指令 clamped 逻辑插入「当前页」与「Tip」之间，
    对齐 /背包 尾段顺序：`当前页：X/Y` → `（已到最后一页）` → `Tip:...`。
    """
    tail = render_cake_tail(page, total_pages, category_word=category_word, tip=tip)
    if clamped:
        tail = tail.replace("\n", f"\n{LAST_PAGE_HINT}\n", 1)
    return tail


def _bag_tail_lines(page: int, total_pages: int, total: int, clamped: bool,
                    ctx: Mapping[str, Any], category_word: str = "全部") -> List[str]:
    """/背包 尾段：货币行 + `当前页：{page}/{total_pages}({类型词})` + 夹取提示 + Tip。

    （类型词 = 当前筛选的物品类型，用户 2026-08-27 拍板：/背包 → 全部，/背包筛选
    装备 → 装备、/背包筛选药剂 → 药剂 等；原「共 N 条」改显示筛选类型。）"""
    lines: List[str] = list(_currency_lines(ctx))
    lines.append(_cake_tail(page, total_pages, category_word=category_word,
                            tip=_BAG_TAIL_TIP, clamped=clamped))
    return lines


def _render_bag_page(ctx: Mapping[str, Any], page: int) -> str:
    """/背包 正文（用户自定义模板）：物品行 5 条/页 `{序号}.[{名称}]×{数量}` + 货币行
    + 当前页 + Tip；裁决② 夹取；空背包 → TPL_EMPTY_BAG。"""
    rows = _inventory_rows(ctx)
    if not rows:
        return TPL_EMPTY_BAG
    res = resolve_page(page, len(rows), DEFAULT_PAGE_SIZE)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 parse_page_arg 判定并转 TPL-12（3d §2.2/裁决②）"
        )
    assert res.page is not None
    start = (res.page - 1) * DEFAULT_PAGE_SIZE
    slice_rows = rows[start:start + DEFAULT_PAGE_SIZE]
    lines: List[str] = [bag_line(start + i + 1, r, ctx) for i, r in enumerate(slice_rows)]
    lines.extend(_bag_tail_lines(res.page, res.total_pages, res.total, res.clamped, ctx))
    return "\n".join(lines)


def cmd_bag(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/背包 [页码]：物品列表（5 条/页 + TPL-08 + 裁决② 夹取；0/负数/非数字 → TPL-12）。"""
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if getattr(parsed, "fixed_subword", None):
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if len(args) > 1:
        return format_tpl12(_fragment(parsed))
    page = parse_page_arg(args[0] if args else None)
    if page is None:
        return format_tpl12(_fragment(parsed))
    return _render_bag_page(ctx, page)


# ---------------------------------------------------------------------------
# /背包筛选：筛选链（框架 §7.4 L1336-1344 / 4f RUL-16 / TC-14）
# 语法：背包筛选 <物品类型> [类型 <子类目>] [品质 <品质>] [页码]
# 筛选链：物品类型 → 类型(子类目) → 品质，可叠加；结果 >5 条分页 5 条/页 + TPL-08
# ---------------------------------------------------------------------------

BAG_FILTER_CMD = "背包筛选"

# 物品大类判定（items.json type 键 → 大类键；用户 2026-08-27 拍板类型词体系：
# 装备/药剂/货币袋/材料/技能书/任务/其他）
_EQUIP_SLOT_KEYS = frozenset({
    "weapon", "armor_head", "armor_body", "armor_hand", "armor_leg", "armor_foot",
})
_CATEGORY_BY_TYPE = {
    **{k: "equip" for k in _EQUIP_SLOT_KEYS},
    "consumable": "consumable", "potion": "consumable", "medicine": "consumable",
    "material": "material", "ore": "material", "herb": "material",
    "quest": "quest",
    "currency": "currency", "coin": "currency", "bag": "currency",
    "skill_book": "skill_book", "scroll": "skill_book",
}
# 大类键 → 展示中文（当前页类型词；consumable 用户词「药剂」）
_CATEGORY_CN = {
    "equip": "装备", "consumable": "药剂", "material": "材料", "quest": "任务",
    "currency": "货币袋", "skill_book": "技能书", "other": "其他",
}
# 中文类型词 → 大类键（筛选匹配 + 校验；含别名：消耗品/药水 = 药剂类）
_TYPE_WORD_ALIASES = {
    "装备": "equip", "武器": "equip",
    "消耗品": "consumable", "药剂": "consumable", "药水": "consumable",
    "材料": "material", "素材": "material",
    "任务": "quest",
    "货币袋": "currency", "货币": "currency", "钱袋": "currency",
    "技能书": "skill_book",
    "其他": "other",
}
# 物品类型词表（语料兜底：未知大类词 → 不匹配，展示原分类）
_CATEGORY_WORDS = frozenset(_TYPE_WORD_ALIASES) | frozenset(_CATEGORY_CN.values())


def _item_def(ctx: Mapping[str, Any], item_id: str) -> Optional[Mapping[str, Any]]:
    """items.json 物品定义（ctx[\"items\"]；非 Mapping/缺 id → None）。"""
    if not item_id:
        return None
    items = ctx.get("items")
    if isinstance(items, Mapping):
        d = items.get(item_id)
        if isinstance(d, Mapping):
            return d
    return None


def _row_type_key(row: Any, ctx: Mapping[str, Any], f: Mapping[str, Any]) -> str:
    """物品子类键（type）：row 直接字段优先 → items.json 定义兜底。"""
    if isinstance(row, Mapping):
        t = row.get("type")
        if t:
            return str(t)
    else:
        t = getattr(row, "type", None)
        if t:
            return str(t)
    d = _item_def(ctx, f["item_id"])
    if d is not None:
        return str(d.get("type") or "")
    return ""


def _item_category(type_key: str) -> str:
    """子类键 → 大类键（框架 §7.4 物品类型；未知 → other）。"""
    return _CATEGORY_BY_TYPE.get(type_key, "other")


def _category_key(word: str) -> str:
    """中文类型词 → 大类键（别名归一：消耗品/药水/药剂 均 → consumable；非中文原样）。"""
    return _TYPE_WORD_ALIASES.get(word, word)


def _quality_key(word: str) -> Optional[str]:
    """品质词 → 内部键（中文标签或直接键；未知 → None）。"""
    if word in QUALITY_LABELS:
        return word
    rev = {v: k for k, v in QUALITY_LABELS.items() if v}
    return rev.get(word)


def _subtype_match(word: str, type_key: str) -> bool:
    """子类词匹配：直接键（weapon）或中文部位名（武器）。"""
    if not word:
        return True
    if word == type_key:
        return True
    return DEFAULT_SLOT_NAMES.get(type_key) == word


def _parse_filter_args(args: List[str]) -> Tuple[str, Optional[str], Optional[str], int]:
    """解析筛选链参数 → (物品类型词, 子类词, 品质词, 页码)。

    语法（框架 §7.4）：`<物品类型> [类型 <子类目>] [品质 <品质>] [页码]`；
    末尾纯数字 = 页码；其余按「类型/品质」键值对解析，裸词按 品质→子类 容错。
    """
    if not args:
        return "", None, None, 1
    page = 1
    if args[-1].isdigit():
        page = int(args[-1])
        args = args[:-1]
    if not args:
        return "", None, None, page
    cat_word = args[0]
    sub_word: Optional[str] = None
    qual_word: Optional[str] = None
    rest = args[1:]
    i = 0
    while i < len(rest):
        w = rest[i]
        if w in ("类型", "子类") and i + 1 < len(rest):
            sub_word = rest[i + 1]
            i += 2
        elif w == "品质" and i + 1 < len(rest):
            qual_word = rest[i + 1]
            i += 2
        elif qual_word is None and _quality_key(w) is not None:
            qual_word = w
            i += 1
        elif sub_word is None:
            sub_word = w
            i += 1
        else:
            i += 1  # 无法识别的词跳过（不阻断）
    return cat_word, sub_word, qual_word, page


def _filter_inventory_rows(rows: Sequence[Any], ctx: Mapping[str, Any],
                           cat_word: str, sub_word: Optional[str],
                           qual_word: Optional[str]) -> List[Any]:
    """筛选链逐级过滤（物品类型 → 子类 → 品质 可叠加）。"""
    out: List[Any] = []
    for r in rows:
        f = _row_fields(r, ctx)
        type_key = _row_type_key(r, ctx, f)
        if cat_word and _category_key(cat_word) != _item_category(type_key):
            continue
        if sub_word and not _subtype_match(sub_word, type_key):
            continue
        if qual_word:
            qk = _quality_key(qual_word)
            if qk is None or f["quality"] != qk:
                continue
        out.append(r)
    return out


def _render_rows_page(ctx: Mapping[str, Any], rows: Sequence[Any], cmd: str,
                      page: int, category_word: str = "全部") -> str:
    """通用列表分页渲染（5 条/页 + 用户 /背包 尾段：货币/当前页(类型词)/Tip + 裁决② 夹取；空 → TPL_EMPTY_BAG）。"""
    if not rows:
        return TPL_EMPTY_BAG
    res = resolve_page(page, len(rows), DEFAULT_PAGE_SIZE)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 parse_page_arg 判定并转 TPL-12（3d §2.2/裁决②）"
        )
    assert res.page is not None
    start = (res.page - 1) * DEFAULT_PAGE_SIZE
    slice_rows = rows[start:start + DEFAULT_PAGE_SIZE]
    lines: List[str] = [bag_line(start + i + 1, r, ctx) for i, r in enumerate(slice_rows)]
    lines.extend(_bag_tail_lines(res.page, res.total_pages, res.total, res.clamped, ctx,
                                 category_word=category_word))
    return "\n".join(lines)


def cmd_bag_filter(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/背包筛选 <物品类型> [类型 <子类目>] [品质 <品质>] [页码]：筛选链（4f RUL-16）。

    物品类型（装备/消耗品/材料/任务/其他）→ 类型(子类目) → 品质 可叠加过滤；
    结果 >5 条分页 5 条/页 + TPL-08 + 裁决② 夹取；空筛选 → TPL_EMPTY_BAG。
    """
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    # 裁决②：尾随数字页码 0/负数 → TPL-12（非数字保留为筛选词容错，见 _parse_filter_args）
    if args:
        last = args[-1]
        if last.isdigit() and int(last) < 1:
            return format_tpl12(_fragment(parsed))
        if len(last) > 1 and last[0] == "-" and last[1:].isdigit():
            return format_tpl12(_fragment(parsed))
    cat_word, sub_word, qual_word, page = _parse_filter_args(args)
    if not cat_word:
        # 缺物品类型词 → 提示用法（值域/用法问题，非 TPL-12 指令错误；对齐 4f 提示风）
        return "❌ 背包筛选：输入物品类型（装备/药剂/货币袋/材料/技能书/任务），如「背包筛选装备」"
    if cat_word not in _CATEGORY_WORDS:
        return f"❌ 没有「{cat_word}」这个物品类型（装备/药剂/货币袋/材料/技能书/任务）"
    rows = _filter_inventory_rows(_inventory_rows(ctx), ctx, cat_word, sub_word, qual_word)
    return _render_rows_page(ctx, rows, BAG_FILTER_CMD, page, category_word=cat_word)


# ---------------------------------------------------------------------------
# /装备：装备栏（5 条/页 + TPL-08 + 裁决②）/ 切换（穿 <序号> / 卸 <槽位>）
# ---------------------------------------------------------------------------

def _slot_order(ctx: Mapping[str, Any]) -> List[str]:
    """槽位顺序：ctx["slot_order"] 覆盖；slots.json 包装形态 {"slots":{...}} 取键序；
    缺省武器+五部位（4b §3.1，P2-8 修复对齐 EquipmentEngine 构造形态）。"""
    order = ctx.get("slot_order")
    if isinstance(order, (list, tuple)) and order:
        return [str(s) for s in order]
    slots = ctx.get("slots")
    if isinstance(slots, Mapping) and "slots" in slots and isinstance(slots["slots"], Mapping):
        keys = list(slots["slots"].keys())
        if keys:
            return [str(s) for s in keys]
    return list(DEFAULT_SLOT_ORDER)


def _slot_name(ctx: Mapping[str, Any], slot_id: str) -> str:
    """槽位 id → 中文名（ctx["slots"] 配置优先，含包装形态 {"slots":{...}}；缺省兜底表）。"""
    slots = ctx.get("slots")
    if isinstance(slots, Mapping):
        if "slots" in slots and isinstance(slots["slots"], Mapping):
            slots = slots["slots"]  # P2-8 修复：包装形态取内层
        d = slots.get(slot_id)
        if isinstance(d, Mapping) and d.get("name"):
            return str(d["name"])
        if d is not None and hasattr(d, "get"):
            n = d.get("name")
            if n:
                return str(n)
    return DEFAULT_SLOT_NAMES.get(slot_id, slot_id)


def _equipment_map(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    """玩家装备栏（ctx["equipment"] → ctx["player"].equipment 兜底）。"""
    eq = ctx.get("equipment")
    if eq is None:
        player = ctx.get("player")
        if player is not None:
            eq = getattr(player, "equipment", None)
    return eq if isinstance(eq, Mapping) else {}


def _slot_info(slot: Any) -> Optional[Mapping[str, Any]]:
    """槽位实例归一（EquipmentSlot dataclass / dict）；空槽 → None。"""
    if slot is None:
        return None
    if isinstance(slot, Mapping):
        if not slot.get("item_id") and not slot.get("name"):
            return None
        return {
            "item_id": str(slot.get("item_id") or ""),
            "name": str(slot.get("name") or slot.get("item_id") or "?"),
            "enhance": int(slot.get("slot_level", slot.get("enhance", 0)) or 0),
            "locked": bool(slot.get("locked")),
        }
    item_id = getattr(slot, "item_id", None)
    name = getattr(slot, "name", None)
    if not item_id and not name:
        return None
    return {
        "item_id": str(item_id or ""),
        "name": str(name or item_id or "?"),
        "enhance": int(getattr(slot, "slot_level", 0) or 0),
        "locked": bool(getattr(slot, "locked", False)),
    }


def equip_line(slot_id: str, slot: Any, ctx: Mapping[str, Any]) -> Optional[str]:
    """装备栏行（意见一同步：去序号）：`武器：铁剑 +3`；空槽（部位没有装备）→ None
    （空槽不显示，由 _render_equip_page 过滤）。"""
    slot_name = _slot_name(ctx, slot_id)
    info = _slot_info(slot)
    if info is None:
        return None
    line = f"{slot_name}：{info['name']}"
    if info["enhance"]:
        line += f" +{info['enhance']}"
    return line


def _render_equip_page(ctx: Mapping[str, Any], page: int = 1) -> str:
    """/装备 正文（意见一同步：不加翻页）：头部 `【装备】` + 非空槽位一行一个 + Tip。

    空槽（部位没有装备）不显示；一次性展示全部已装备槽位（无页码/夹取尾段，
    不翻页）；`page` 参数保留仅兼容旧整数参数路径，实际不再分页。
    """
    order = _slot_order(ctx)
    eq = _equipment_map(ctx)
    # 槽位视图 = 顺序槽位全集；ctx 内额外槽位追加（内容包自定义部位 EQP-04）
    items = list(order)
    for sid in eq:
        if sid not in items:
            items.append(sid)
    lines: List[str] = ["【装备】"]
    for sid in items:
        ln = equip_line(sid, eq.get(sid), ctx)
        if ln:
            lines.append(ln)
    lines.append(f"Tip:{_EQUIP_TAIL_TIP}")
    return "\n".join(lines)


def resolve_equip_slot(ctx: Mapping[str, Any], arg: object) -> Optional[str]:
    """槽位参数 → slot_id（槽位 id / 中文名 / 序号）；找不到 → None（值域文案，工程补白 4）。"""
    if arg is None:
        return None
    s = str(arg)
    order = _slot_order(ctx)
    if s in order:
        return s
    for sid in order:
        if _slot_name(ctx, sid) == s:
            return sid
    n = parse_int(s)
    if n is not None and 1 <= n <= len(order):
        return order[n - 1]
    return None


class EquipmentEngineAdapter:
    """真实 EquipmentEngine 适配层（EQP-12 / D1 P1-5 ③：/装备 命令换真实引擎）。

    实现本模块文件头声明的消费接口 equip_wear(index, ctx) / equip_remove(slot_id, ctx)
    -> {ok, message}（对齐 FakeEquipEngine 替身签名，不破坏既有测试注入路径）：
      - 从 ctx 解析玩家（ctx["player"] 可变 dict）与背包（player["inventory"] 元素
        ItemInstance，含 item_id/type(slot)/name/stats_bonus 等）；
      - 调用 core.equipment.EquipmentEngine.equip(player, item, slot) / unequip(player, slot)；
      - 就地更新 ctx["player"]（引擎直接改 equipment/inventory/attributes）；
      - 组装中文消息（✅/❌ + 人话，对齐 EQP-E1~E5 边界文案：这个位置穿不上/互斥冲突/
        该槽位没有装备/战斗中不可更换装备（战前换装））。
    装配层注入 ctx["equip_engine"] = 适配器；本类亦为懒加载兜底（_equip_engine）。

    【工程补白】
      1) equip_wear 的目标槽位取 ItemInstance.slot（可装备槽位类型，data/item.py L34；
         与 EquipmentEngine EQP-02 部位匹配口径一致）。
      2) 失败消息以引擎 message 透传（引擎已按 EQP-E1~E5 合成人话），reason 兜底防漏。
      3) 玩家状态缺失（未注册/未建档）→ 明确提示先 /注册。
    """

    def __init__(
        self,
        slots: Optional[Any] = None,
        mutual_exclusions: Optional[Sequence[Sequence[str]]] = None,
        engine: Optional[EquipmentEngine] = None,
    ) -> None:
        """构造适配器（引擎可注入覆盖；否则以 slots 配置构造真实 EquipmentEngine）。"""
        self._engine = engine if engine is not None else EquipmentEngine(
            slots=slots, mutual_exclusions=mutual_exclusions,
        )

    @staticmethod
    def _player(ctx: Mapping[str, Any]) -> Optional[MutableMapping[str, Any]]:
        p = ctx.get("player")
        if isinstance(p, MutableMapping):
            return p
        # 装配层 make_context 注入 Player dataclass（2026-08-28 部署实测）——
        # asdict 转可变 dict 并写回 ctx（引擎就地修改 + 落档 dict 转换兼容）。
        if isinstance(p, Player):
            import dataclasses  # noqa: PLC0415

            d = dataclasses.asdict(p)
            if isinstance(ctx, MutableMapping):
                ctx["player"] = d
            return d
        return None

    @staticmethod
    def _sorted_inventory(player: MutableMapping[str, Any]) -> list:
        """背包行展示序（P1-2 修复，M6 批1B 审查）：与 /背包 _inventory_rows 同口径——
        按 acquired_at 倒序（RUL-17），无时间字段保持存储序（稳定排序）。适配层按此序
        取穿装序号，避免「/背包 显示第 N 件」与「穿第 N 件」错位。"""
        inv = player.get("inventory")
        if not isinstance(inv, (list, tuple)):
            return []
        rows = list(inv)

        def _key(r: Any) -> str:
            if isinstance(r, Mapping):
                t = r.get("acquired_at")
                return str(t) if t is not None else ""
            return str(getattr(r, "acquired_at", "") or "")

        try:
            return sorted(rows, key=_key, reverse=True)
        except TypeError:  # 混合类型时间字段 → 保持原序
            return rows

    def equip_wear(self, index: int, ctx: MutableMapping[str, Any]) -> dict:
        """装备背包第 index 件（1 起，按 /背包 展示序=acquired_at 倒序）；返回 {ok, message, ...}。"""
        player = self._player(ctx)
        if player is None:
            return {"ok": False, "message": "❌ 玩家状态缺失（请先 /注册 创建角色）"}
        sorted_inv = self._sorted_inventory(player)
        if not (1 <= index <= len(sorted_inv)):
            return {"ok": False, "message": "❌ 背包里没有这件物品"}
        item = sorted_inv[index - 1]
        if not isinstance(item, ItemInstance):
            return {"ok": False, "message": "❌ 这件物品不能装备"}
        if not item.slot:
            return {"ok": False, "message": "❌ 这件物品不能装备（未登记装备槽位）"}
        res = self._engine.equip(player, item, item.slot)
        if res.get("ok"):
            msg = f"✅ 已装备：{item.name}"
            if res.get("replaced"):
                msg += "（已替换原装备并回包）"
            return {"ok": True, "message": msg, "slot": item.slot, **res}
        return {"ok": False, "message": self._fail_message(res, "装备失败")}

    def equip_remove(self, slot_id: str, ctx: MutableMapping[str, Any]) -> dict:
        """卸下槽位装备；返回 {ok, message, ...}。"""
        player = self._player(ctx)
        if player is None:
            return {"ok": False, "message": "❌ 玩家状态缺失（请先 /注册 创建角色）"}
        old = None
        equipment = player.get("equipment")
        if isinstance(equipment, Mapping):
            old = equipment.get(slot_id)
        res = self._engine.unequip(player, slot_id)
        if res.get("ok"):
            old_name = ""
            if old is not None:
                old_name = str(getattr(old, "name", "") or "")
                if not old_name and isinstance(old, Mapping):
                    old_name = str(old.get("name") or "")
            item_id = str(res.get("item_id") or "")
            return {"ok": True, "message": f"✅ 已卸下：{old_name or item_id}", **res}
        return {"ok": False, "message": self._fail_message(res, "卸下失败")}

    @staticmethod
    def _fail_message(res: Mapping[str, Any], fallback: str) -> str:
        """引擎拒绝 → ❌ 文案（message 透传；缺省按 reason 兜底人话）。"""
        msg = res.get("message")
        if msg:
            return f"❌ {msg}"
        reason = str(res.get("reason") or "")
        reason_cn = {
            "slot_mismatch": "这个位置穿不上",
            "mutual_exclusion": "装备冲突：与已穿装备互斥，无法同时穿戴",
            "empty_slot": "该槽位没有装备",
            "in_battle": "战斗中不可更换装备（战前换装）",
            "item_not_found": "背包里没有这件物品",
            "unknown_slot": "没有这个装备槽位",
            "max_reached": "该槽位已达可装备数量上限",
        }
        return f"❌ {reason_cn.get(reason, fallback)}"


_logger = get_logger("basic_commands.equip")


def _equip_engine(ctx: Mapping[str, Any]) -> Any:
    """装备引擎解析（注入优先 → 懒加载真实 EquipmentEngine 适配层（EQP-12）；均不可得 →
    【待接线】RuntimeError，与 checkin_commands 同模式，工程补白 9）。

    - ctx["equip_engine"] 注入优先（装配层/测试注入适配器或替身，equip_wear/equip_remove 消费接口）；
    - 未注入 → importlib 守卫导入 qbot_rpg.core.equipment（路A 已实装）后构造
      EquipmentEngineAdapter（slots 配置取自 ctx["slots"]）——懒加载路径。
    """
    eng = ctx.get("equip_engine")
    if eng is not None:
        return eng
    try:
        importlib.import_module("qbot_rpg.core.equipment")
        return EquipmentEngineAdapter(slots=ctx.get("slots"))
    except Exception as exc:  # ModuleNotFoundError / ImportError / 构造失败
        raise RuntimeError(
            "【待接线】core/equipment.py（M6 批1 已实装 EquipmentEngine + 适配层）装备引擎不可用；"
            "装配时注入 ctx['equip_engine']（equip_wear/equip_remove 消费接口）"
        ) from exc


def _cmd_equip_wear(ctx: Mapping[str, Any], index: int) -> str:
    """/装备 穿 <序号>：切换穿戴背包第 index 件（引擎 equip_wear，消息透传）。"""
    engine = _equip_engine(ctx)
    try:
        res = engine.equip_wear(index, ctx)
    except Exception as exc:  # P2-3 修复：裸吞异常留日志（防故障不可诊断）
        _logger.exception("equip_wear 异常（index=%s）: %s", index, exc)
        res = {}
    return str(res.get("message") or "❌ 装备失败")


def _cmd_equip_remove(ctx: Mapping[str, Any], slot_id: str) -> str:
    """/装备 卸 <槽位>：卸下槽位装备（引擎 equip_remove，消息透传）。"""
    engine = _equip_engine(ctx)
    try:
        res = engine.equip_remove(slot_id, ctx)
    except Exception as exc:  # P2-3 修复：裸吞异常留日志（防故障不可诊断）
        _logger.exception("equip_remove 异常（slot=%s）: %s", slot_id, exc)
        res = {}
    return str(res.get("message") or "❌ 卸下失败")


def cmd_equip(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/装备 [参数] 主入口（4b §三 装备穿戴；意见一同步：不加翻页）：

      无参 / <整数>    → 装备栏一次性展示全部已装备槽位（头部【装备】；空槽不显示；
                        整数页码忽略不再翻页）
      穿 <序号>       → 切换穿戴背包第 N 件（引擎）
      卸 <槽位>       → 卸下槽位装备（槽位名/id/序号；解析失败 → 值域文案 TPL_NO_SLOT）
    """
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if getattr(parsed, "fixed_subword", None):
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return _render_equip_page(ctx, 1)
    first = str(args[0])
    if first == SUB_WEAR:
        seq = args[1] if len(args) > 1 else None
        n = parse_int(seq) if seq is not None else None
        if n is None or n < 1:
            return format_tpl12(_fragment(parsed))
        if len(args) > 2:
            return format_tpl12(_fragment(parsed))
        return _cmd_equip_wear(ctx, n)
    if first == SUB_REMOVE:
        slot_arg = args[1] if len(args) > 1 else None
        if slot_arg is None or len(args) > 2:
            return format_tpl12(_fragment(parsed))
        sid = resolve_equip_slot(ctx, slot_arg)
        if sid is None:
            return TPL_NO_SLOT
        return _cmd_equip_remove(ctx, sid)
    # 名称形式（非数字非子词，如 /装备 铁剑）→ 友好提示引导序号（P2-11 QA；命令合法，
    # 不走 TPL-12，对齐 TPL_NO_SLOT 值域文案口径）
    if parse_int(first) is None:
        return TPL_EQUIP_NAME_HINT
    # 整数 = 页码（0/负数 → parse_page_arg None → TPL-12，保留裁决②）
    page = parse_page_arg(first)
    if page is None:
        return format_tpl12(_fragment(parsed))
    if len(args) > 1:
        return format_tpl12(_fragment(parsed))
    return _render_equip_page(ctx, page)


# ---------------------------------------------------------------------------
# /技能：技能列表（LV 行固定头部 + 类型/MP/描述 + 派生指向「可派生成：XX」）
# ---------------------------------------------------------------------------

def _skill_def(ctx: Mapping[str, Any], sid: str) -> Any:
    """技能定义解析（ctx["skills"] 映射 / resolve_skill 解析器）；查无 → None。"""
    if not sid:
        return None
    skills = ctx.get("skills")
    if isinstance(skills, Mapping):
        d = skills.get(sid)
        if d is not None:
            return d
    resolver = ctx.get("resolve_skill")
    if callable(resolver):
        try:
            return resolver(sid)
        except Exception:
            return None
    return None


def _skill_name(ctx: Mapping[str, Any], sid: str) -> str:
    """技能 id → 显示名（定义 name 冗余；查无 → id 原样）。"""
    d = _skill_def(ctx, sid)
    if d is None:
        return sid
    if isinstance(d, Mapping):
        return str(d.get("name") or sid)
    n = getattr(d, "name", None)
    return str(n or sid)


def _skill_field(defn: Any, key: str, default: Any = None) -> Any:
    """技能定义字段取值（Mapping / Def.get 双兼容）。"""
    if isinstance(defn, Mapping):
        return defn.get(key, default)
    if defn is not None and hasattr(defn, "get"):
        try:
            return defn.get(key, default)
        except Exception:
            return default
    return default


def _chain_def(ctx: Mapping[str, Any], cid: str) -> Any:
    """派生链定义解析（ctx["skill_chains"] 映射 / resolve_chain 解析器）；查无 → None。"""
    if not cid:
        return None
    chains = ctx.get("skill_chains")
    if isinstance(chains, Mapping):
        d = chains.get(cid)
        if d is not None:
            return d
    resolver = ctx.get("resolve_chain")
    if callable(resolver):
        try:
            return resolver(cid)
        except Exception:
            return None
    return None


def _derived_names(ctx: Mapping[str, Any], sid: str, chain_refs: Sequence[Any]) -> List[str]:
    """派生指向（1c2 派生链 + 6a F14 chain_refs）：链 steps[].from == sid → steps[].to 技能名。"""
    out: List[str] = []
    seen: set = set()
    for ref in chain_refs or ():
        cid = str(ref)
        chain = _chain_def(ctx, cid)
        if chain is None:
            continue
        steps = _skill_field(chain, "steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            if str(step.get("from") or "") != sid:
                continue
            to_id = step.get("to")
            if not to_id:
                continue
            to_id = str(to_id)
            if to_id in seen:
                continue
            seen.add(to_id)
            out.append(_skill_name(ctx, to_id))
    return out


def skill_line(index: int, sid: str, ctx: Mapping[str, Any]) -> str:
    """技能行：`{序号}. {名称}（{类型}）{MP} MP ｜ {描述} ｜ 可派生成：XX`（M2 技能卡派生指向）。
    MP 仅 >0 显示；无描述不输出描述段；无派生链不输出指向（工程补白 5）。"""
    defn = _skill_def(ctx, sid)
    name = _skill_name(ctx, sid)
    type_label = TYPE_LABELS.get(str(_skill_field(defn, "type", "active")), "主动")
    parts: List[str] = [f"{index}. {name}（{type_label}）"]
    mp = _skill_field(defn, "mp_cost", 0)
    try:
        mp = int(mp)
    except (TypeError, ValueError):
        mp = 0
    if mp > 0:
        parts[0] += f" {mp} MP"
    desc = _skill_field(defn, "desc")
    if isinstance(desc, str) and desc:
        parts.append(desc)
    chain_refs = _skill_field(defn, "chain_refs")
    if isinstance(chain_refs, (list, tuple)) and chain_refs:
        derived = _derived_names(ctx, sid, chain_refs)
        if derived:
            parts.append("可派生成：" + "、".join(derived))
    return " ｜ ".join(parts)


def _job_visible(ctx: Mapping[str, Any], sid: str) -> bool:
    """技能对当前职业可见性（6a §4.3 装配过滤：job_restrict 空=通用；非空须含当前职业）。"""
    job_id = str(_player_fields(ctx)["job_id"])
    restrict = _skill_field(_skill_def(ctx, sid), "job_restrict", None)
    if isinstance(restrict, (list, tuple)) and restrict:
        return job_id in {str(r) for r in restrict}
    return True


def skill_rows(ctx: Mapping[str, Any]) -> List[str]:
    """当前职业可见技能 id 列表（job_restrict 过滤 + type 排序 basic→active→passive→trigger，
    6a §1.5 普攻固定第 1 位；工程补白 5）。"""
    skills = ctx.get("skills")
    ids: List[str] = []
    if isinstance(skills, Mapping):
        ids = [str(k) for k in skills.keys()]
    else:
        resolver = ctx.get("resolve_skill")
        ids = list(ctx.get("skill_ids") or ()) if callable(resolver) else []
    order_map = {"basic": 0, "active": 1, "passive": 2, "trigger": 3}

    def _key(sid: str) -> tuple:
        t = str(_skill_field(_skill_def(ctx, sid), "type", "active"))
        return (order_map.get(t, 4), sid)

    visible = [sid for sid in ids if _job_visible(ctx, sid)]
    visible.sort(key=_key)
    return visible


def _render_skill_page(ctx: Mapping[str, Any], page: int) -> str:
    """/技能 正文：LV 行固定头部 + 技能行 5 条/页 + TPL-08 + 裁决② 夹取。"""
    sids = skill_rows(ctx)
    res = resolve_page(page, len(sids), DEFAULT_PAGE_SIZE)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 parse_page_arg 判定并转 TPL-12（3d §2.2/裁决②）"
        )
    assert res.page is not None
    start = (res.page - 1) * DEFAULT_PAGE_SIZE
    slice_ids = sids[start:start + DEFAULT_PAGE_SIZE]
    f = _player_fields(ctx)
    job = str(ctx.get("job_name") or _job_name(ctx, f["job_id"]) or "?")
    lines: List[str] = [f"【技能】Lv{f['level']}.{f['name']}（{job}）｜ 技能 {len(sids)} 项"]
    for i, sid in enumerate(slice_ids):
        lines.append(skill_line(start + i + 1, sid, ctx))
    if sids:
        lines.append(_cake_tail(res.page, res.total_pages, tip=_SKILL_TAIL_TIP, clamped=res.clamped))
    return "\n".join(lines)


def cmd_skill(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/技能 [页码]：技能列表（LV 行固定头部 + 类型/MP/描述 + 派生指向「可派生成：XX」；
    5 条/页 + TPL-08 + 裁决② 夹取；0/负数/非数字 → TPL-12）。"""
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if getattr(parsed, "fixed_subword", None):
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if len(args) > 1:
        return format_tpl12(_fragment(parsed))
    page = parse_page_arg(args[0] if args else None)
    if page is None:
        return format_tpl12(_fragment(parsed))
    return _render_skill_page(ctx, page)


# ---------------------------------------------------------------------------
# /帮助：分组目录（5 组单页 / GM 6 组 2 页）+ 组页指令列表（5 条/页）+ 注册引导版（B6）
# ---------------------------------------------------------------------------

def _command_alias_display(ctx: Mapping[str, Any], name: str) -> str:
    """指令显示名别名替换（SHC-04 / 4f RUL-24 / 规范 6.7 L213-215）：

    消费 settings.command_aliases（形态对齐 parsers._normalize_aliases）：
      - {"锻造": "炼器"}（缺省 keep_original:true）→ 双名并显 `锻造/炼器`；
      - {"炼金": {"alias": "炼丹", "keep_original": false}} → 仅显别名 `炼丹`；
      - 无别名配置/原指令不在表 → 原指令名。
    """
    settings = ctx.get("settings")
    if not isinstance(settings, Mapping):
        return name
    aliases = settings.get("command_aliases")
    if not isinstance(aliases, Mapping):
        return name
    entry = aliases.get(name)
    if entry is None:
        return name
    if isinstance(entry, str):
        return f"{name}/{entry}"
    if isinstance(entry, Mapping):
        alias = entry.get("alias")
        if not alias:
            return name
        if entry.get("keep_original", True):
            return f"{name}/{alias}"
        return str(alias)
    return name


def _help_groups(ctx: Mapping[str, Any]) -> Tuple[Tuple[str, Tuple[Tuple[str, str], ...]], ...]:
    """分组目录：普通玩家 5 组；GM 追加第 6 组（B8/RUL-25，GM 判定 ctx["is_gm"]）。"""
    groups = list(HELP_GROUPS)
    if ctx.get("is_gm"):
        groups.append(GM_HELP_GROUP)
    return tuple(groups)


def _group_summary(ctx: Mapping[str, Any], group: Tuple[str, Tuple[Tuple[str, str], ...]]) -> str:
    """目录行（4f RUL-22 + SHC-04/RUL-24 别名显示）：`冒险 —— 角色/背包/装备/位置/进入…（/帮助 冒险）`。"""
    name, cmds = group
    names = [_command_alias_display(ctx, c[0]) for c in cmds]
    shown = "/".join(names[:5])
    if len(names) > 5:
        shown += "…"
    return f"{name} —— {shown}（/帮助 {name}）"


def _render_help_directory(ctx: Mapping[str, Any], page: int) -> str:
    """/帮助 目录：组摘要 5 条/页 + TPL-08 + 裁决② 夹取（普通玩家 5 组单页无页脚；GM 6 组 2 页）。"""
    groups = _help_groups(ctx)
    res = resolve_page(page, len(groups), DEFAULT_PAGE_SIZE)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 parse_page_arg 判定并转 TPL-12（3d §2.2/裁决②）"
        )
    assert res.page is not None
    start = (res.page - 1) * DEFAULT_PAGE_SIZE
    slice_groups = groups[start:start + DEFAULT_PAGE_SIZE]
    lines: List[str] = [_DIRECTORY_TITLE]
    for i, g in enumerate(slice_groups):
        lines.append(_group_summary(ctx, g))
    if groups:
        lines.append(_cake_tail(res.page, res.total_pages, tip=_HELP_TAIL_TIP, clamped=res.clamped))
    return "\n".join(lines)


def group_page_line(index: int, cmd: Tuple[str, str]) -> str:
    """组页指令行（4f RUL-23）：`/状态 —— 查看角色状态与身上效果`。"""
    return f"{index}. {cmd[0]} —— {cmd[1]}"


def _render_help_group(ctx: Mapping[str, Any], group_name: str, page: int) -> str:
    """/帮助 <组名>：组内指令列表 5 条/页 + TPL-08（页脚指令=帮助 <组名>）+ 裁决② 夹取。"""
    groups = _help_groups(ctx)
    group = next((g for g in groups if g[0] == group_name), None)
    if group is None:
        return format_tpl12(f"/{HELP_CMD} {group_name}")
    cmds = list(group[1])
    res = resolve_page(page, len(cmds), DEFAULT_PAGE_SIZE)
    if res.invalid:
        raise ValueError(
            "页码非法（0/负数/非数字）：壳层应经 parse_page_arg 判定并转 TPL-12（3d §2.2/裁决②）"
        )
    assert res.page is not None
    start = (res.page - 1) * DEFAULT_PAGE_SIZE
    slice_cmds = cmds[start:start + DEFAULT_PAGE_SIZE]
    lines: List[str] = [f"【{group_name}】"]
    for i, c in enumerate(slice_cmds):
        # SHC-04/RUL-24：指令名按 settings.command_aliases 显示层替换（TC-17）
        display = _command_alias_display(ctx, c[0])
        lines.append(group_page_line(start + i + 1, (display, c[1])))
    if cmds:
        lines.append(_cake_tail(res.page, res.total_pages, tip=_HELP_TAIL_TIP, clamped=res.clamped))
    return "\n".join(lines)


def cmd_help(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/帮助 [参数] 主入口（4f RUL-20 + B6）：

      无参            → 分组目录（普通 5 组单页；GM 6 组 2 页）
      <组名>          → 指定分组指令列表（5 条/页 + TPL-08；未知组名 → TPL-12）
      <整数>          → 目录页码（裁决②：超页夹取最后一页 + 已到最后一页；0/负数/非数字 → TPL-12）
      未注册（B6）    → 注册引导版（豁免注册门槛）
    """
    # B6 注册引导版（豁免）——P2-6 修复：未注册判定前置到 parsed.error 之前，
    # 未注册玩家任意 /帮助（含解析错误）均返回引导版（B6「/帮助 豁免注册门槛」）。
    if ctx.get("registered", True) is False:
        return _REGISTER_GUIDE
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if getattr(parsed, "fixed_subword", None):
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return _render_help_directory(ctx, 1)
    first = str(args[0])
    if len(args) > 2:
        return format_tpl12(_fragment(parsed))
    if first in GROUP_ORDER:
        page = parse_page_arg(args[1] if len(args) > 1 else None)
        if page is None:
            return format_tpl12(_fragment(parsed))
        return _render_help_group(ctx, first, page)
    page = parse_page_arg(first)
    if page is None:
        return format_tpl12(_fragment(parsed))
    if len(args) > 1:
        return format_tpl12(_fragment(parsed))
    return _render_help_directory(ctx, page)


# ---------------------------------------------------------------------------
# 装配（Router 注册；make_context 由装配层注入，批次7 待接线）
# ---------------------------------------------------------------------------

def register_basic_commands(router: Any, *, make_context: Optional[Callable[[Any], dict]] = None) -> Any:
    """把 /角色 /背包 /装备 /技能 /帮助 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    :param make_context: ParsedCommand → 玩家 ctx dict（name/level/exp/job_id/attributes/inventory/
        equipment/skills/skill_chains/stats/items/jobs/slots/settings/registered/is_gm/equip_engine
        等，见本模块各渲染函数消费契约）。None 时 handler 调用抛 RuntimeError
        （【待接线】批次7 装配注入）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】basic_commands.register_basic_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _wrap(handler: Callable[..., str]) -> Callable[..., str]:
        def _h(parsed: Any, *a: Any, **k: Any) -> str:
            injected = k.get("ctx") if isinstance(k, dict) else None
            if isinstance(injected, MutableMapping):
                return handler(parsed, injected)
            return handler(parsed, _ctx(parsed))
        return _h

    router.register(CommandSpec(VIEW_CMD, handler=_wrap(cmd_view)))
    router.register(CommandSpec(VIEW_DETAIL_CMD, handler=_wrap(cmd_view_detail)))
    router.register(CommandSpec(BAG_CMD, handler=_wrap(cmd_bag)))
    router.register(CommandSpec(BAG_FILTER_CMD, handler=_wrap(cmd_bag_filter)))
    router.register(CommandSpec(EQUIP_CMD, handler=_wrap(cmd_equip)))
    router.register(CommandSpec(SKILL_CMD, handler=_wrap(cmd_skill)))
    router.register(CommandSpec(MY_SKILL_CMD, handler=_wrap(cmd_skill)))  # 我的技能 → 技能
    router.register(CommandSpec(HELP_CMD, handler=_wrap(cmd_help)))
    return router
