"""状态指令接线 status_commands.py（M6 批次1·路B · qbot_rpg/commands/status_commands.py）。

依据：
  - docs/细化/细化_M6_三引擎与基础指令.md（M6 子细化 D1）§五 /状态 契约：STT-01~STT-05、
    TC-STT-01~03（承接 4f TC-07/09/10）；§七 P1-2（DELAYED 收口）
  - docs/细化/细化_4f_基础指令组契约.md（母契约）§二：CMD-02 / RUL-10~15 / TPL-4F-02/03；
    B4 裁决（/状态 = 战斗外总览面板，/角色 职责不变）
  - docs/细化/细化_3b_玩家属性三层.md（最终层数值 = calc_all_final_attributes 管线出口）
  - docs/细化/细化_3d_消息模板规范.md（TPL-12 / D-01 emoji 禁令 / D-04 文案唯一源）
  - M6 LVL-11（exp_next 口径：满级 = 0，经验阈值=内容包曲线）

职责（细化_3a §1.3 壳层职责 · 唯一指令执行壳）：把 /状态 从 Router 接到玩家状态数据源——
渲染五区（① 前缀行 → ② 等级/经验行 → ③ 属性行（最终层数值）→ ④ 位置行 → ⑤ 效果区；
战斗内追加【目标】行，RUL-15），纯函数（parsed + ctx → 回复正文），零 NoneBot / 零 IO。
属性/等级/经验/效果/位置/目标 数据全部由 ctx 注入（装配层 make_context 组装），本层只渲染。

铁律（m4_shared_contract §0 / 3a R1）：**零 NoneBot import**、纯函数、确定性；工程补白一律
【工程补白】标注；错误走 TPL-12 统一模板；装饰性 emoji 全局禁用（仅 ✅/❌）。

--------------------------------------------------------------------------------
ctx 消费契约（装配层 make_context 注入；未注入字段按缺省兜底）：
  player: dict|dataclass        玩家状态（level/exp/hp/mp；hp/mp 供资源当前值）
  attr_final: dict              最终层属性 {attr_id: int}（calc_all_final_attributes 结果，
                                直接消费优先）
  attributes: PlayerAttributes  属性三层（attr_final 缺省时经 calc_all_final_attributes 计算）
  resolve_attr_final: callable  attributes 与 attr_final 均缺省时兜底取最终层（可选）
  exp_next: int                 升级所需经验（LVL-11 口径：满级 = 0）
  level_cap: int                等级上限（level ≥ cap → 【已满级】）
  location: str                 当前地点（【位置】行）
  effects: list[{name, remaining, duration?, source}]
                                效果区（无 → 【效果】无；前 5 个 + 还有 N 个状态）
  target: dict{name, hp, max_hp, turn}
                                战斗内目标（【目标】行，RUL-15，可选）
  title: str                    当前称号（前缀行 -[称号]-；无 → "-"）
--------------------------------------------------------------------------------

【工程补白 · 显式标注】
  1) 首行 = 前缀行 `Lv{等级}.{玩家名} -{称号}-`（对齐 TPL-4F-02/03 与 STT-01「前缀行」；
     与 basic_commands /角色 的「LV 行固定头部」同模式——handler 直出可纯函数单测；
     装配层 message_prefix 是否叠加由批次7 装配裁决，本层不重复注入）。
  2) 属性行固定四值（4f RUL-12 模板：生命/魔力/攻击/防御，全中文）：生命=hp、魔力=mp
     （当前/最终上限），攻击=str（力量）、防御=con（体质）——映射采用框架战斗数值口径
     （damage 公式 atk 出自力量、防御系数出自有效体质），统计表属性名为「力量/体质」。
  3) 满级判定：level ≥ level_cap 或 exp_next == 0（LVL-11 口径）→ 【已满级】。
  4) 效果行格式 `{名} {剩余}/{持续}（来源：{来源}）`：remaining 必填；duration/total 缺省
     时仅显 `{剩余}回合`；source 缺省时省略「（来源：…）」；>5 个追加 `还有 N 个状态`。
  5) 未注册拦截走 RUL-08 门槛（STT-05 ④，非豁免）：复用 basic_commands.TPL_REGISTER_GATE。
"""

from __future__ import annotations

from typing import Any, Callable, List, Mapping, MutableMapping, Optional

from qbot_rpg.core.player_attributes import calc_all_final_attributes
from qbot_rpg.core.templates import tpl_of  # 消息模板配置化（2026-08-31 用户拍板）
from qbot_rpg.data.player import PlayerAttributes

# 同包兄弟模块：相对导入（G0 架构门禁不产生 `qbot_rpg.commands` 前缀反向依赖边；
# 同层兄弟引用架构合规，与 sender.py 同口径）。
from .basic_commands import TPL_REGISTER_GATE
from .basic_commands import _stat_name, _stat_order  # 属性全量渲染 helper（对齐 /角色 口径）
from .router import CommandSpec
from .sender import format_tpl12

__all__ = [
    "STATUS_CMD",
    # 指令处理器（纯函数：parsed + ctx → 回复正文）
    "cmd_status",
    # 渲染 / 工具
    "prefix_line",
    "level_line",
    "attr_line",
    "location_line",
    "effects_line",
    "imprints_line",
    "target_line",
    # 装配
    "register_status_commands",
]

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

STATUS_CMD = "状态"
MY_STATUS_CMD = "我的状态"  # 2026-08-31 QA P1-3：玩家口语变体「我的状态」→ 映射 /状态

# 效果区最多展示数量（STT-03 / RUL-13：默认前 5 个 + 还有 N 个状态）
EFFECTS_SHOWN = 5


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


def _gate(ctx: Mapping[str, Any]) -> Optional[str]:
    """RUL-08 注册门槛（STT-05 ④ 非豁免）：ctx["registered"] is False → 拦截文案；
    缺省视为已注册（对齐 basic_commands 工程补白 7）。"""
    if ctx.get("registered", True) is False:
        return TPL_REGISTER_GATE
    return None


def _player_fields(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    """玩家基础字段归一（ctx["player"] dict/dataclass → ctx 顶层兜底）。

    优先读 ctx["player"]（dict 或 dataclass 形态均可，M6 路B 修复：dict 形态
    之前被忽略走顶层兜底导致 name/level 读不到），再回退 ctx 顶层字段。
    """
    p = ctx.get("player")
    if p is not None:
        if isinstance(p, Mapping):
            return {
                "name": str(p.get("name") or ctx.get("name") or "?"),
                "level": int(p.get("level") or ctx.get("level") or 1),
                "exp": p.get("exp") if p.get("exp") is not None else ctx.get("exp"),
                "hp": p.get("hp") if p.get("hp") is not None else ctx.get("hp"),
                "mp": p.get("mp") if p.get("mp") is not None else ctx.get("mp"),
            }
        return {
            "name": str(getattr(p, "name", None) or ctx.get("name") or "?"),
            "level": int(getattr(p, "level", None) or ctx.get("level") or 1),
            "exp": getattr(p, "exp", None) if getattr(p, "exp", None) is not None else ctx.get("exp"),
            "hp": getattr(p, "hp", None) if getattr(p, "hp", None) is not None else ctx.get("hp"),
            "mp": getattr(p, "mp", None) if getattr(p, "mp", None) is not None else ctx.get("mp"),
        }
    return {
        "name": str(ctx.get("name") or "?"),
        "level": int(ctx.get("level") or 1),
        "exp": ctx.get("exp"),
        "hp": ctx.get("hp"),
        "mp": ctx.get("mp"),
    }


def _to_attributes(ctx: Mapping[str, Any]) -> PlayerAttributes:
    """属性三层归一为 PlayerAttributes（dict 形态兼容，对齐 basic_commands._to_attributes）。"""
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


def _final_attrs(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    """最终层属性 {attr_id: int}（STT-03 属性行数值口径）：

    ctx["attr_final"] 直接消费（装配层已跑 calc_all_final_attributes）→ ctx["attributes"]
    兜底计算 → ctx["resolve_attr_final"] 兜底（可选）。
    """
    final = ctx.get("attr_final")
    if isinstance(final, Mapping):
        return final
    attrs = _to_attributes(ctx)
    # 有实质属性数据才跑管线（注意：bonus/temp 恒含 {"flat","pct"} 空子结构，
    # 不能以 attrs.bonus 真值判定——否则空 PlayerAttributes 也会误入管线返回 {}，
    # 吞掉 resolve_attr_final 兜底。M6 路B 修复）
    if (
        attrs.base
        or attrs.cond
        or any(attrs.bonus.values())
        or any(attrs.temp.values())
    ):
        try:
            return calc_all_final_attributes(
                attrs,
                conditional_rules=ctx.get("conditional_rules") or (),
                resource_pct=bool(
                    (ctx.get("settings") or {}).get("resource_pct")
                    if isinstance(ctx.get("settings"), Mapping) else False
                ),
                attr_types=ctx.get("attr_types"),
            )
        except Exception:
            pass
    resolver = ctx.get("resolve_attr_final")
    if callable(resolver):
        try:
            r = resolver()
            if isinstance(r, Mapping):
                return r
        except Exception:
            pass
    return {}


def prefix_line(ctx: Mapping[str, Any]) -> str:
    """① 前缀行（STT-01/TPL-4F-02）：`Lv3.阿伟 -斩龙者-`；空称号 → `Lv3.阿伟 - -`
    （对齐 prefix_render 空称号三态默认：` -[称号]-` 空称号渲染为 ` - -`，TPL-02）。"""
    f = _player_fields(ctx)
    title = ctx.get("title")
    if title:
        return f"Lv{f['level']}.{f['name']} -{title}-"
    return f"Lv{f['level']}.{f['name']} - -"


def _fmt_exp(v: object) -> str:
    """经验值渲染归一（P2-9 修复）：None → 空串；float 整数 → int（320.0 → 320）。"""
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def level_line(ctx: Mapping[str, Any]) -> str:
    """② 等级/经验行（RUL-11/STT-02，意见一同步：等级/经验各占一行，去 `｜`；
    模板配置化 2026-08-31：来自 ctx[templates] status_level/status_exp）：
    `【等级】3`\\n`【经验】20/1000`；满级 → `【等级】45【已满级】`（LVL-11 口径，工程补白 3）。"""
    f = _player_fields(ctx)
    level = f["level"]
    cap = ctx.get("level_cap")
    if cap is not None:
        try:
            if level >= int(cap):
                return tpl_of(ctx, "status_level", {"level": level}) + tpl_of(ctx, "status_max_hint", {})
        except (TypeError, ValueError):
            pass
    if ctx.get("exp_next") == 0:
        return tpl_of(ctx, "status_level", {"level": level}) + tpl_of(ctx, "status_max_hint", {})
    nxt = ctx.get("exp_next")
    exp = _fmt_exp(f["exp"])
    lv = tpl_of(ctx, "status_level", {"level": level})
    if nxt is not None:
        return f"{lv}\n" + tpl_of(ctx, "status_exp", {"exp": exp, "exp_next": nxt})
    return f"{lv}\n" + tpl_of(ctx, "status_exp_only", {"exp": exp})


def attr_line(ctx: Mapping[str, Any]) -> str:
    """③ 属性行（RUL-12/STT-03，最终层数值，全中文，意见一同步：每项独立一行）。
    2026-08-31 修复：此前硬编码仅渲染 生命/魔力/攻击/防御 四值（漏掉 stats.json 其余
    属性），改为遍历 stats.json 全部属性（对齐 /角色 _stat_order 口径），每项一行；
    resource 型（hp/mp）显示 `当前/上限`。"""
    final = _final_attrs(ctx)
    f = _player_fields(ctx)
    attrs = _to_attributes(ctx)
    order = _stat_order(ctx, attrs)
    lines: List[str] = []
    for attr_id in order:
        if attr_id not in final:
            continue
        # 状态面板显示名：str→攻击、con→防御（保留原四值语义），其余用 stats.json 中文名
        if attr_id == "str":
            name = "攻击"
        elif attr_id == "con":
            name = "防御"
        else:
            name = _stat_name(ctx, attr_id)
        if attr_id in ("hp", "mp"):
            cur = f.get(attr_id)
            cur_i = int(cur) if cur is not None else int(final[attr_id])
            lines.append(tpl_of(ctx, "status_attr_resource",
                                {"attr_name": name, "cur": cur_i, "max": int(final[attr_id])}))
        else:
            lines.append(tpl_of(ctx, "status_attr",
                                {"attr_name": name, "value": int(final[attr_id])}))
    return "\n".join(lines) if lines else tpl_of(ctx, "status_no_attr", {})


def _map_name_for(ctx: Mapping[str, Any], loc: str) -> str:
    """位置 id → 地图中文名（P2-2 修复：/状态 【位置】显示中文名而非原始 id）。

    用 maps 索引查 name（对齐 explore_commands._maps_index_for 口径：ctx["maps"] 的
    list/容器/MapDef 归一；未知/未注入 → 原样返回 id 兜底，零失败）。
    """
    try:
        from qbot_rpg.world.movement import _maps_index  # noqa: PLC0415
    except ImportError:
        return loc
    index = _maps_index(ctx.get("maps"))
    entry = index.get(loc) if isinstance(index, Mapping) else None
    if entry is None:
        return loc
    nm = entry.get("name") if isinstance(entry, Mapping) else getattr(entry, "name", None)
    return nm if isinstance(nm, str) and nm else loc


def location_line(ctx: Mapping[str, Any]) -> str:
    """④ 位置行（RUL-14；模板配置化 2026-08-31）：`【位置】晨风村`（P2-2：id → 中文名）；
    缺省 → `【位置】未知`。"""
    loc = ctx.get("location")
    if not loc:
        return tpl_of(ctx, "status_location", {"location": "未知"})
    return tpl_of(ctx, "status_location", {"location": _map_name_for(ctx, str(loc))})


def _effect_text(e: Mapping[str, Any]) -> Optional[str]:
    """单条效果文案（工程补白 4）：`中毒 2/3（来源：剧毒史莱姆）`。"""
    if not isinstance(e, Mapping):
        return None
    name = str(e.get("name") or "?")
    seg = name
    remaining = e.get("remaining")
    if remaining is not None:
        total = e.get("duration", e.get("total"))
        if total is not None:
            seg += f" {remaining}/{total}"
        else:
            seg += f" {remaining}回合"
    src = e.get("source")
    if src:
        seg += f"（来源：{src}）"
    return seg


def effects_line(ctx: Mapping[str, Any]) -> str:
    """⑤ 效果区（RUL-13/STT-03；模板配置化 2026-08-31）：`【效果】中毒 2/3（来源：剧毒史莱姆）`；
    无效果 → `【效果】无`；>5 个 → 前 5 个 + `还有 N 个状态`。"""
    effects = ctx.get("effects")
    if not effects:
        return tpl_of(ctx, "status_effects", {"effects": "无"})
    parts: List[str] = []
    for e in effects[:EFFECTS_SHOWN]:
        seg = _effect_text(e)
        if seg:
            parts.append(seg)
    if len(effects) > EFFECTS_SHOWN:
        parts.append(f"还有 {len(effects) - EFFECTS_SHOWN} 个状态")
    if not parts:
        return tpl_of(ctx, "status_effects", {"effects": "无"})
    return tpl_of(ctx, "status_effects", {"effects": " ｜ ".join(parts)})


def imprints_line(ctx: Mapping[str, Any]) -> Optional[str]:
    """印记区（RUL-13/STT-01⑤，P2-1 修复）：`【印记】火焰印记×2（敌方施放）`；
    ctx["imprints"]（[{name, count?, source?}]）缺省/空 → None（不渲染印记行）。
    count 缺省 1 不显 ×；source 缺省省略来源。"""
    imprints = ctx.get("imprints")
    if not imprints:
        return None
    segs: List[str] = []
    for imp in imprints:
        if not isinstance(imp, Mapping):
            continue
        name = str(imp.get("name") or "?")
        count = imp.get("count")
        seg = f"{name}×{count}" if count not in (None, 1) else name
        src = imp.get("source")
        if src:
            seg += f"（{src}）"
        segs.append(seg)
    if not segs:
        return None
    return tpl_of(ctx, "status_imprints", {"imprints": " ｜ ".join(segs)})


def target_line(ctx: Mapping[str, Any]) -> Optional[str]:
    """战斗内【目标】行（RUL-15/STT-04）：`【目标】史莱姆 18/30（第 3 回合）`；
    ctx["target"] 缺省或字段不全（hp/max_hp/turn 任一 None）→ 整行降级 None（P2-9 修复，
    防 `【目标】xx None/None（第 None 回合）`）。"""
    t = ctx.get("target")
    if not isinstance(t, Mapping):
        return None
    name = str(t.get("name") or "?")
    hp = t.get("hp")
    mx = t.get("max_hp")
    turn = t.get("turn")
    if hp is None or mx is None or turn is None:
        return None
    return tpl_of(ctx, "status_target", {"name": name, "hp_cur": hp, "hp_max": mx, "round": turn})


# ---------------------------------------------------------------------------
# 指令处理器（纯函数：ParsedCommand + ctx → 回复正文）
# ---------------------------------------------------------------------------

def cmd_status(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/状态（STT-01~05 / RUL-10~15 / TPL-4F-02/03）：

      无参             → 渲染五区（前缀行 → 等级/经验行 → 属性行 → 位置行 → 效果区）；
                        战斗内（ctx["target"]）追加【目标】行（RUL-15）
      解析错误/带参     → TPL-12（面板无分页；多余参数按格式错误）
      未注册            → RUL-08 拦截（STT-05 ④，非豁免）
    """
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if getattr(parsed, "fixed_subword", None):
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if args:
        return format_tpl12(_fragment(parsed))

    lines: List[str] = [
        level_line(ctx),
        attr_line(ctx),
        location_line(ctx),
    ]
    tgt = target_line(ctx)
    if tgt is not None:
        lines.append(tgt)
    lines.append(effects_line(ctx))
    imp = imprints_line(ctx)
    if imp is not None:
        lines.append(imp)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 装配（Router 注册；make_context 由装配层注入，批次7 待接线）
# ---------------------------------------------------------------------------

def register_status_commands(
    router: Any, *, make_context: Optional[Callable[[Any], dict]] = None
) -> Any:
    """把 /状态 注册进 Router（CommandSpec.handler 消费 ParsedCommand；STT-05 ②）。

    :param make_context: ParsedCommand → 玩家 ctx dict（player/attr_final|attributes/exp_next/
        level_cap/location/effects/target 等，见本模块各渲染函数消费契约）。None 时 handler
        调用抛 RuntimeError（【待接线】批次7 装配注入）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】status_commands.register_status_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _status(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_status(parsed, injected)
        return cmd_status(parsed, _ctx(parsed))

    router.register(CommandSpec(STATUS_CMD, handler=_status))
    router.register(CommandSpec(MY_STATUS_CMD, handler=_status))  # 我的状态 → 状态
    return router
