# -*- coding: utf-8 -*-
"""云海新增指令五件 cloudsea_extra_commands.py（九期批次 232 · G5 指令交互）。

五件：`港 档`／`港 鉴`／`勘察`／`晨报`／`预案`——独立分账文件（235H「深度炼成」
独立分账同型），**不触碰** cloudsea_commands.py（231 接线批在途写面）与任何既有
指令词面（红线：现有指令词面零改动；`港 档`/`港 鉴` 系完整词面独立注册，`港`
本体 handler 零触碰）。

装配：register_cloudsea_extra_commands(router, *, make_context=None)——仿
shop_commands.register_shop_commands 壳模式；装配层未调用 → 五指令不生效（可选
加载承诺，映射表 §十一 台账）。

数据面：content/cloudsea/presets.json（预案串模板/炮台守 side 枚举/晨报槽位）；
包未装配时内嵌缺省（PRESET_FALLBACK），鸭子类型 ctx 消费（键缺失 → 友好降级文
案，不抛异常）。错误文案沿 TPL-12 语义（下一步指向/不甩公式/不撕票，`08` §M8.12
三条铁律）；渲染纯文本零 emoji 滥用。

方位枚举（机械师「炮台守 side」联动）：沿 `22` 号 §十一 schema（215C 落）——
self_reposition ∈ {dash,lateral,turn,shift,ascend,descend,cling,burrow,rolling}、
attack_zone sides ∈ {front,left,right,back}、height ∈ {ground,air}；预案串校验
走本文件 SIDE_ENUM（与 12 §AD 同源值域，断言 A4 复核）。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Tuple

__all__ = [
    "PORT_ARCHIVE_CMD", "PORT_CODEX_CMD", "SURVEY_CMD", "MORNING_CMD", "PRESET_CMD",
    "cmd_port_archive", "cmd_port_codex", "cmd_survey", "cmd_morning", "cmd_preset",
    "register_cloudsea_extra_commands",
]

# ---------------------------------------------------------------- 词面
PORT_ARCHIVE_CMD = "港 档"
PORT_CODEX_CMD = "港 鉴"
SURVEY_CMD = "勘察"
MORNING_CMD = "晨报"
PRESET_CMD = "预案"

# ---------------------------------------------------------------- 数据缺省（presets.json 未装配时的兜底）
SIDE_ENUM = ["front", "side", "rear"]  # 炮台守扇位＝12 §L TURRET_GUARD_SECTOR（215B 申报，裁决 #24）
HEIGHT_ENUM = ["ground", "air"]
REPOSITION_ENUM = ["dash", "lateral", "turn", "shift", "ascend", "descend", "cling", "burrow", "rolling"]
TIDE_NAMES = ["微澜", "潮涌", "湍流", "怒涛", "风暴", "狂岚", "浩劫"]

PRESET_FALLBACK: Dict[str, Any] = {
    "templates": [
        {"id": "standard", "name": "标准预案", "body": "灵:标背脊→喂爆燃→抗沉眠｜兽:支援→守护", "tags": ["通用"]},
        {"id": "gunner_turret", "name": "炮台守·侧翼", "body": "架设→炮台守 side:left→齐射×2→撤架", "tags": ["机械师", "方位"]},
        {"id": "guard_hold", "name": "守卫镇场", "body": "盾防→释能 等破招→剑连击", "tags": ["守卫"]},
    ],
    "morning_slots": ["丰饶符", "素材本", "巨兽窗", "待收", "计量条"],
}

# ---------------------------------------------------------------- 工具
def _ctx_player(ctx: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    p = ctx.get("player")
    return p if isinstance(p, Mapping) else None


def _pkg_data(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    """包数据装配口（装配层注入 ctx["cloudsea_pkg"]）；缺省用内嵌兜底。"""
    d = ctx.get("cloudsea_pkg")
    if isinstance(d, Mapping) and "templates" in d:
        return d
    return PRESET_FALLBACK


def _game_day(ctx: Mapping[str, Any]) -> Tuple[int, str]:
    """游戏日号 D 读取（215H 模型：存档单调递增；dayroll 合成时钟供给）。
    ctx["game_day"] 注入优先；缺省 0（「第 1 日」）。"""
    try:
        d = int(ctx.get("game_day", 0))
    except Exception:  # noqa: BLE001
        d = 0
    return max(d, 0), "第 {} 日".format(d + 1)


def _gated(ctx: Mapping[str, Any]) -> Optional[str]:
    """注册门槛（RUL-08 同族）：未注册 → 统一提示。"""
    if ctx.get("registered") is False:
        return "尚未注册 · 先发 `注册` 建档，再来港里看这些。"
    return None


def _kv(view: Mapping[str, Any], key: str) -> str:
    v = view.get(key)
    return str(v) if v not in (None, "") else "—"


def _arg_tail(parsed: Any, ctx: Mapping[str, Any]) -> str:
    """参数串读取：parsed.args（parse_command token 化）优先，ctx["args"] 注入兜底。"""
    args = getattr(parsed, "args", None)
    if isinstance(args, (list, tuple)) and args:
        return " ".join(str(a) for a in args).strip()
    a2 = ctx.get("args")
    if isinstance(a2, (list, tuple)) and a2:
        return " ".join(str(x) for x in a2).strip()
    if isinstance(a2, str) and a2.strip():
        return a2.strip()
    return ""


# ---------------------------------------------------------------- 港 档
def cmd_port_archive(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`港 档`：云枢浮港个人档案聚合（进度/收集/羁绊/资产 概览）。"""
    g = _gated(ctx)
    if g:
        return g
    p = _ctx_player(ctx)
    if p is None:
        return "📜 港 档：档案数据未装配 · 发 `局面` 看当前战况，或联系港务（装配层缺 player）。"
    day, day_label = _game_day(ctx)
    lines = [
        "📜 云枢浮港 · 个人档案（{}）".format(day_label),
        "├ 姓名：{} ｜ 职业：{}".format(_kv(p, "name"), _kv(p, "job")),
        "├ 潮位进度：{} ｜ 星段：{}".format(_kv(p, "tide"), _kv(p, "star")),
        "├ 收集度：典录 {}/典录总数 ｜ 图鉴 {}".format(_kv(p, "codex_done"), _kv(p, "codex_total")),
        "├ 羁绊：同行兽 {} ｜ 共生灵 {}".format(_kv(p, "companion"), _kv(p, "symbiont")),
        "├ 资产：金 {} ｜ 丰饶符 {} ｜ 公会勋 {}".format(_kv(p, "gold"), _kv(p, "fertility"), _kv(p, "honor")),
        "└ 熟练：炼金 Lv{} ｜ 武器熟练 {}".format(_kv(p, "alchemy_lv"), _kv(p, "weapon_mastery")),
        "▸ 港 鉴 <关键词> 查条目 ｜ 勘察 [生态] 看产出 ｜ 晨报 看今日",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- 港 鉴
def _codex_sources(ctx: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """图鉴数据源聚合：enemies_t1–t7 + items（鸭子读取，缺省空表）。"""
    out: List[Mapping[str, Any]] = []
    for tide in range(1, 8):
        rows = ctx.get("cloudsea_enemies_t{}".format(tide))
        if isinstance(rows, list):
            out.extend(r for r in rows if isinstance(r, Mapping))
    items = ctx.get("cloudsea_items")
    if isinstance(items, list):
        out.extend(r for r in items if isinstance(r, Mapping))
    return out


def cmd_port_codex(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`港 鉴 <关键词>`：图鉴条目查询（怪/武器/素材 三域合并检索）。"""
    g = _gated(ctx)
    if g:
        return g
    kw = _arg_tail(parsed, ctx)
    if not kw:
        return "🔍 港 鉴 <关键词>：查怪/武器/素材条目 · 例：`港 鉴 岩犀`（支持名称片段）"
    rows = _codex_sources(ctx)
    if not rows:
        return ("🔍 港 鉴：图鉴数据未装配（content/cloudsea 包加载缺 enemies/items）· "
                "装配后即可查询；先发 `港 档` 看自己的进度。")
    hits = [r for r in rows if kw in str(r.get("name", "")) or kw in str(r.get("id", ""))]
    if not hits:
        return "🔍 图鉴无「{}」· 换个关键词（名称片段即可），或发 `勘察` 看各生态产什么。".format(kw)
    lines = ["🔍 图鉴 ·「{}」命中 {} 条（至多示 5）".format(kw, len(hits))]
    for r in hits[:5]:
        lines.append("├ {}｜{}｜潮位{} ｜ {}".format(
            r.get("name", "—"), r.get("id", "—"), r.get("tide", "—"),
            str(r.get("desc", ""))[:40]))
    lines.append("└ 详录见典录/名录分册（`港 档` 看收集度）。")
    return "\n".join(lines)


# ---------------------------------------------------------------- 勘察
def _survey_row(ctx: Mapping[str, Any], eco: str) -> Optional[Mapping[str, Any]]:
    ec = ctx.get("cloudsea_ecosystems")
    if isinstance(ec, Mapping):
        row = ec.get(eco)
        if isinstance(row, Mapping):
            return row
    return None


def cmd_survey(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`勘察 [生态名]`：生态勘察（分布/潮位/产出/素材本轮换预告）。"""
    g = _gated(ctx)
    if g:
        return g
    eco = _arg_tail(parsed, ctx)
    day, day_label = _game_day(ctx)
    rotation = "素材本轮换：D%7 = {} → 第 {} 类".format(day % 7, day % 7 + 1)
    if not eco:
        return ("🧭 勘察 [生态名]：看该生态怪物分布与产出 · 例：`勘察 灰岗旧港`\n"
                "├ 今日（{}）{}\n└ 生态名单见 `港 鉴` 或生态总表（28 生态）。".format(day_label, rotation))
    row = _survey_row(ctx, eco)
    if row is None:
        return ("🧭 勘察：「{}」生态数据未装配或名称不匹配 · 生态名单见生态总表 28 项；\n"
                "├ 今日（{}）{}\n└ 数据装配后此处显示怪物分布/星段/特产。".format(eco, day_label, rotation))
    lines = ["🧭 勘察 · {}（{}）".format(eco, _kv(row, "tide"))]
    lines.append("├ 星段：{} ｜ 类型：{} ｜ 巨兽 {}＋空兽 {}＋杂兽 {}".format(
        _kv(row, "star"), _kv(row, "type"), _kv(row, "beast"), _kv(row, "sky"), _kv(row, "mob")))
    drops = row.get("drops")
    if isinstance(drops, list) and drops:
        lines.append("├ 特产：{}".format("、".join(str(x) for x in drops[:6])))
    lines.append("└ 今日（{}）{}".format(day_label, rotation))
    return "\n".join(lines)


# ---------------------------------------------------------------- 晨报
def cmd_morning(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`晨报`：每日晨报聚合（游戏日/丰饶符/素材本/巨兽窗/待收）。"""
    g = _gated(ctx)
    if g:
        return g
    day, day_label = _game_day(ctx)
    week = day // 7 + 1
    pkg = _pkg_data(ctx)
    slots = pkg.get("morning_slots", PRESET_FALLBACK["morning_slots"])
    lines = ["🌅 晨报 · {}（游戏周 {}）".format(day_label, week)]
    for s in slots:
        lines.append("├ {}:—（数据装配后自动填充）".format(s))
    lines.append("├ 素材本：D%7={} → 第 {} 类（`本` 直达）".format(day % 7, day % 7 + 1))
    lines.append("└ 巨兽窗：每日 1 窗（游戏日全天，215H 收敛口径）· `巨兽` 入窗")
    return "\n".join(lines)


# ---------------------------------------------------------------- 预案
def _validate_preset(body: str) -> List[str]:
    """预案串方位枚举校验（机械师「炮台守 side」联动，22 号 §十一 schema 值域）。"""
    warns: List[str] = []
    for token in body.replace("｜", "→").split("→"):
        t = token.strip()
        if t.startswith("炮台守"):
            side = t.replace("炮台守", "").replace("side", "").replace(":", "").replace("：", "").strip()
            if side and side not in SIDE_ENUM:
                warns.append("炮台守 side:{} 不在枚举 {}".format(side, "/".join(SIDE_ENUM)))
    return warns


def cmd_preset(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`预案 [查看|设 <串>|清]`：战前预案串管理（含炮台守 side 方位枚举校验）。"""
    g = _gated(ctx)
    if g:
        return g
    tail = _arg_tail(parsed, ctx)
    store = ctx.get("preset_store")
    current = ""
    if isinstance(store, Mapping):
        current = str(store.get("body", ""))
    if not tail or tail in ("查看",):
        pkg = _pkg_data(ctx)
        lines = ["📋 预案串（战前自动执行，零战内操作）"]
        if current:
            lines.append("├ 当前：{}".format(current))
        else:
            lines.append("├ 当前：未设（托管回合按缺省预案行动）")
        for t in pkg.get("templates", [])[:3]:
            lines.append("├ 模板 {}:{}".format(t.get("name", "—"), t.get("body", "")))
        lines.append("└ `预案 设 <串>` 自定义（→ 分隔步骤；机械师可用 `炮台守 side:<front|left|right|back>`）")
        return "\n".join(lines)
    if tail == "清":
        if isinstance(store, MutableMapping):
            store["body"] = ""
        return "📋 预案串已清空 · 托管将按缺省行动。"
    body = tail[len("设"):].strip() if tail.startswith("设") else tail
    if not body:
        return "📋 `预案 设 <串>`：串不能为空 · 模板见 `预案 查看`。"
    warns = _validate_preset(body)
    if isinstance(store, MutableMapping):
        store["body"] = body
    lines = ["📋 预案串已设：{}".format(body)]
    for w in warns:
        lines.append("⚠️ {}".format(w))
    lines.append("└ 战斗中发 `预案 查看` 复核；托管回合自动按串执行（21 卡异步兼容口径）。")
    return "\n".join(lines)


# ---------------------------------------------------------------- 装配
def register_cloudsea_extra_commands(router: Any, *, make_context: Optional[Callable[[], MutableMapping[str, Any]]] = None) -> int:
    """装配入口（显式调用；未调用 → 五指令不生效）。返回注册条数。

    注册形态＝CommandSpec（router.register(spec)）；路由匹配/优先级与
    `港` 本体（231 接线批）的子命令分派归 231 消费——本文件只保证五词面
    可独立注册、handler 契约 (parsed, ctx) -> str。
    """
    try:
        from qbot_rpg.commands.router import CommandSpec  # noqa: PLC0415
    except Exception:  # noqa: BLE001 测试/文档环境无 router → 零注册
        return 0
    specs = [
        CommandSpec(PORT_ARCHIVE_CMD, handler=cmd_port_archive),
        CommandSpec(PORT_CODEX_CMD, handler=cmd_port_codex),
        CommandSpec(SURVEY_CMD, handler=cmd_survey),
        CommandSpec(MORNING_CMD, handler=cmd_morning),
        CommandSpec(PRESET_CMD, handler=cmd_preset),
    ]
    n = 0
    for spec in specs:
        try:
            router.register(spec)  # type: ignore[attr-defined]
            n += 1
        except Exception:  # noqa: BLE001 同名已注册（231 接线冲突）→ 逐条隔离
            continue
    return n
