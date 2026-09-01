"""M10 钓鱼·批2·路2A：/钓鱼 钓点列举指令壳（qbot_rpg/commands/fishing_commands.py）。

文件名：qbot_rpg/commands/fishing_commands.py
创建时间：2026-08-31
作者：Hermes 子agent-2A（M10 钓鱼实现组批2·路2A：/钓鱼 钓点列举指令壳；
      独占本文件 + tests/unit/test_fishing_commands.py；不碰 fishing_reel_commands
      （路2C 独占）与 core/fishing_cast.py（路2B 独占））

功能描述：
  /钓鱼 指令壳（T05 · 细化_2c1b §一 1.1 列钓点 / 1.2 下钩）：
  ① 无参：列出当前地图全部可钓鱼点——垂钓点 = maps 采集点变体（读 ctx["maps"]
     当前地图节点 gather_points + 鱼种 spots 引用匹配）；候选规则 = 当前季节/时段
     存在候选鱼种的钓点（消费 2c1a §1.4 时段匹配契约：seasons/periods 偏好白名单，
     空=不限）；每点展示 名称 / 时段偏好 / 稀有度标记（候选鱼种最高 rarity）。
  ② 固定附注鱼讯参考说明：「微动=小鱼 / 拉扯=中鱼 / 猛烈=大鱼或鱼王！」（逐字三组
     关键词，TC-01）。
  ③ 无钓点地图 → 空态文案（含「本图暂无可钓鱼点」，不输出任何钓点实体，TC-02）。
  ④ off 模式：/钓鱼 一律拒绝（GU-01，TC-09）。
  ⑤ 有参：转发 core.fishing_cast.cast_fishing（路2B 落盘）——本路以 try/except
     ImportError 探活，sibling 未落盘 → 本地兜底返回【工程补白】文案；无参缺省默认
     选中第一个可钓点（细化 1.2 实现层约定，供路2B cast 缺省位）。

依据（文件头标注）：
  - docs/细化/细化_2c1b_钓鱼流程状态机.md §一（1.1 列钓点：当前地图全部可钓鱼点、
    名称/时段偏好/（当前时段命中性）/稀有度标记、候选规则=当前季节/时段存在候选
    鱼种的钓点、鱼讯参考说明逐字三组关键词、空态文案、off 拒绝）+ 1.2 下钩（缺省
    参数默认选中第一个可钓点）+ §2.3 守卫 GU-01（off 全部钓鱼指令拒绝）+ §六
    验收 TC-01（有钓点列出）/ TC-02（无钓点空态）/ TC-09（off 拒绝）
  - 定稿（钓鱼玩法设计定稿）§6 L110（/钓鱼 列当前地图钓点 + 鱼讯参考说明）/
    L15（垂钓点=地图采集点变体）/ L103 / L121（指令表）
  - docs/m10_shared_contract.md §二（FishDef 访问器 + spots 引用形态：maps 采集点
    id 或 map 名+钓点 id 组合）/ §五 铁律
  - docs/m10_接口摸底.md §八-3（ctx 注入形态：fish_table/fishing_cfg）/ §八-5
    （指令注册：REGISTER_GROUPS 加 register_fishing_commands + 白名单 钓鱼/收杆/鱼讯
    三词）/ §九（qid 注入勿再造键、tpl_of 模板化）
  - 模式参考：qbot_rpg/commands/forge_commands.py（M9 指令壳模式：register_* +
    cmd_* + _fail/tpl 模板 + 守卫链 + tokens[1:] 优先 args 兜底参数提取）

【工程补白 · 显式标注】（契约/细化未显式定义处的实现口径，标 F-x）：
  F-1  垂钓点解析：垂钓点 = maps 采集点（gather_points）中「被 ≥1 鱼种 spots 引用」
       的变体。spots 引用两种形态兼容（共享契约 §二 备注）：① 直接采集点 id
       （如 "gp_moon_grass"）；② "map:spot" 组合 id（如 "map_laketown:pier_01"，
       spot 段按 ":" 后段匹配采集点 id）。两种形态同判为垂钓点。
  F-2  候选规则：spot 候选 = 引用该采集点的鱼种中，seasons（空=全年）含当前季节
       且 periods（空=全天）含当前时段的鱼种（2c1a §1.4 白名单语义）；hours 硬时钟
       约束不参与列钓点候选（结算期应用，列钓点只看季节/时段，细化 1.1 明示）。
       季节/时段缺失或不可识别（ctx 注入 "--" 等）→ 视为不限（不误杀，宁多勿少）。
  F-3  季节/时段双形态归一：ctx["season"]/ctx["period"] 可为英文枚举键（spring/
       dawn，worldtime 引擎形态）或中文名（秋/黄昏，bridge 环境快照形态）——归一
       到英文枚举再对照鱼种偏好（中文别名表：春/夏/秋/冬、晨/午/昏/夜/午夜/
       黎明/黄昏/昼）。
  F-4  稀有度标记 = 该钓点候选鱼种最高 rarity（gold > rare > normal）中文标记
       （金色/稀有/普通）；候选无 rarity → 按 normal 兜底。
  F-5  时段偏好 = 候选鱼种 periods 并集中文名（晨/午/昏/夜/午夜，序照枚举），
       并集空 → "全天"。
  F-6  消息输出走 tpl_of(ctx, "fish_*", {...})——批6 才建 fishing_tpl 分区，本路
       key 占位 + 本地 fallback 常量兜底（tpl_of 无分区 key 返回空串 → 用本地
       fallback），全部 TODO 标注批6 迁移。
  F-7  有参下钩转发：try/except ImportError 探活 core.fishing_cast.cast_fishing
       （路2B 独占文件，本路不触碰）；未落盘 → 本地兜底返回【工程补白】文案
       （FISH_CAST_FALLBACK），待路2B 落盘后本路 forward 直接生效（无需改动）。
       转发时 spot 缺省位传 None → 由路2B 按「无参缺省默认选中第一个可钓点」兜底。
  F-8  off 拒绝文案对齐引擎 MSG_OFF（core/fishing.py「钓鱼功能已关闭」）；本壳层
       先判 off（GU-01 全拒绝，含无参列举与有参下钩，TC-09）。
  F-9  /收杆 /鱼讯 指令注册归各自路（路2C fishing_reel_commands 等）；本路
       register_fishing_commands 只注册 /钓鱼。白名单「钓鱼/收杆/鱼讯」三词与
       REGISTER_GROUPS 接线由主 agent 装配收口（对齐接口摸底 §八-5）。

铁律：零 NoneBot import（commands 层只用 parsed/ctx 契约）；纯函数确定性（同刻
      同参必同值）；零定时器/零睡眠（本壳层零等待判定，无任何实时计时）；渲染输出
      零 emoji（仅功能性标记与排版符号）；每功能可追溯（文件头标注依据）。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Tuple, cast

from qbot_rpg.content.fishing_models import FishDef
from qbot_rpg.core.fishing_settings import fishing_cfg
from qbot_rpg.core.templates import tpl_of  # 消息模板配置化（批6 fishing_tpl 分区接管）

from .router import CommandSpec

__all__ = [
    # 指令名常量
    "FISH_CMD",
    # 鱼讯参考说明（逐字三组关键词，TC-01）
    "FISH_INTENT_REF",
    # 有参下钩转发兜底（工程补白 F-7）
    "FISH_CAST_FALLBACK",
    # 纯函数工具（供测试/后续路直接消费）
    "normalize_season",
    "normalize_period",
    "list_fishable_spots",
    "first_fishable_spot",
    # 指令处理器（纯函数：parsed + ctx → 回复正文）
    "cmd_fishing",
    # 装配
    "register_fishing_commands",
]

# ---------------------------------------------------------------------------
# 指令名 / 常量
# ---------------------------------------------------------------------------

# 指令名（接口摸底 §八-5：白名单「钓鱼」由主 agent 装配收口登记）
FISH_CMD: str = "钓鱼"

# 鱼讯参考说明（细化 2c1b §一 1.1 原话语义，逐字保留三类关键词，TC-01）：
#   微动=小鱼 / 拉扯=中鱼 / 猛烈=大鱼或鱼王！
FISH_INTENT_REF: str = "微动=小鱼 / 拉扯=中鱼 / 猛烈=大鱼或鱼王！"

# 有参下钩转发兜底（工程补白 F-7：路2B 未落盘时本地兜底；待 sibling 落盘后本
# forward 直接生效，无需改动）
FISH_CAST_FALLBACK: str = "【工程补白】下钩流程尚未接线（本批仅列出钓点；抛竿功能待路2B 落盘）"

# 稀有度中文标记（gold > rare > normal；F-4 最高 rarity 标记）
_RARITY_CN: Mapping[str, str] = {
    "normal": "普通",
    "rare": "稀有",
    "gold": "金色",
}
# 稀有度序（用于最高 rarity 判定）
_RARITY_RANK: Mapping[str, int] = {"normal": 1, "rare": 2, "gold": 3}

# 时段中文名（对齐 engine/worldtime._PERIOD_CN：晨/午/昏/夜/午夜）
_PERIOD_CN: Mapping[str, str] = {
    "dawn": "晨",
    "noon": "午",
    "dusk": "昏",
    "night": "夜",
    "midnight": "午夜",
}
# 时段枚举序（展示用）
_PERIOD_ORDER: Tuple[str, ...] = ("dawn", "noon", "dusk", "night", "midnight")

# 季节中文名（对齐 engine/time_query.SEASON_NAMES：春/夏/秋/冬）
_SEASON_CN: Mapping[str, str] = {
    "spring": "春",
    "summer": "夏",
    "autumn": "秋",
    "winter": "冬",
}

# 中文别名 → 英文枚举（F-3 双形态归一；ctx 注入可能为中文名或英文键）
_CN_SEASON: Mapping[str, str] = {
    "春": "spring",
    "夏": "summer",
    "秋": "autumn",
    "冬": "winter",
}
_CN_PERIOD: Mapping[str, str] = {
    "晨": "dawn",
    "午": "noon",
    "昏": "dusk",
    "夜": "night",
    "午夜": "midnight",
    "黎明": "dawn",
    "黄昏": "dusk",
    "昼": "noon",
}

# ---------------------------------------------------------------------------
# 本地 fallback 文案（F-6：tpl_of 无 fish_* 分区 key 返回空串 → 本地兜底；
# TODO 批6：fishing_tpl 分区接管后删除 fallback，统一走 tpl_of）
# ---------------------------------------------------------------------------
_DEF_FISH_SPOT_LIST_HEADER: str = "【垂钓点】当前地图：{map_name}"
_DEF_FISH_SPOT_LINE: str = "- {spot_name}｜时段：{periods}｜稀有度：{rarity}"
_DEF_FISH_SPOT_EMPTY: str = "【垂钓点】本图暂无可钓鱼点"
_DEF_FISH_OFF: str = "钓鱼功能已关闭"
_DEF_FISH_INTENT_REF_LINE: str = "鱼讯参考：" + FISH_INTENT_REF


# ---------------------------------------------------------------------------
# 工具（纯函数，确定性）
# ---------------------------------------------------------------------------

def _render(ctx: Mapping[str, Any], key: str, fallback: str, data: Mapping[str, Any]) -> str:
    """模板渲染：tpl_of 优先（批6 fishing_tpl 分区覆盖）；空串 → 本地 fallback 兜底。

    tpl_of 对无分区 key 返回空串（render_template 缺失 key → ""），此时回退本地
    fallback（F-6）。fallback 内含 {占位符}，用 data format_map 填充；占位符缺键 →
    原样保留不崩（防御兜底）。
    """
    rendered = tpl_of(ctx, key, data)
    if rendered:
        return rendered
    try:
        return fallback.format_map(data)
    except (KeyError, ValueError):
        return fallback


def _to_fishdef(entry: Any) -> FishDef:
    """raw dict / FishDef → FishDef（cast 消 mypy BaseDef 返回型，对齐 fishing 引擎）。"""
    if isinstance(entry, FishDef):
        return entry
    if isinstance(entry, Mapping):
        return cast(FishDef, FishDef.from_entry(entry))
    raise TypeError(f"species entry must be FishDef or Mapping, got {type(entry)!r}")


def _species_pool(ctx: Mapping[str, Any]) -> List[FishDef]:
    """鱼种池：ctx[\"fish_table\"]（Def→raw dict，装配注入）优先；回退 ctx[\"fishing\"]
    [\"species\"]（raw list）。无可解析 → []（宽松不炸，对齐 fishing 引擎 _species_pool）。"""
    ft = ctx.get("fish_table")
    if isinstance(ft, Mapping):
        out: List[FishDef] = []
        for entry in ft.values():
            if isinstance(entry, Mapping):
                out.append(_to_fishdef(entry))
        return out
    fishing = ctx.get("fishing")
    if isinstance(fishing, Mapping):
        species = fishing.get("species")
        if isinstance(species, list):
            return [_to_fishdef(e) for e in species if isinstance(e, Mapping)]
    return []


def _mode_of(ctx: Mapping[str, Any]) -> str:
    """三态模式：ctx[\"fishing_cfg\"]（装配注入）优先；缺省自兜底 fishing_cfg(ctx)
    （settings.fishing 段归一，缺省合并默认值）。非枚举 → full 兜底（V4 归校验器）。"""
    cfg = ctx.get("fishing_cfg")
    if not isinstance(cfg, Mapping):
        cfg = fishing_cfg(ctx)
    mode = cfg.get("mode")
    return mode if isinstance(mode, str) and mode in ("full", "simple", "off") else "full"


def normalize_season(value: object) -> Optional[str]:
    """季节双形态归一（F-3）：英文枚举（spring/...）原样；中文名（春/...）→ 英文；
    缺失/不可识别 → None（候选判定视为全年不限）。纯函数确定性。"""
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s in _SEASON_CN:
        return s
    return _CN_SEASON.get(s)


def normalize_period(value: object) -> Optional[str]:
    """时段双形态归一（F-3）：英文枚举（dawn/...）原样；中文名（晨/昏/...）→ 英文；
    缺失/不可识别 → None（候选判定视为全天不限）。纯函数确定性。"""
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s in _PERIOD_CN:
        return s
    return _CN_PERIOD.get(s)


def _current_map_node(ctx: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    """当前地图节点：ctx[\"maps\"]（list 形态，装配注入）按 ctx[\"location\"] 定位；
    Mapping 形态兼容（防御）；缺失/未定位 → None（→ 空态，不崩）。"""
    location = ctx.get("location")
    maps = ctx.get("maps")
    if isinstance(maps, Mapping):
        node = maps.get(location) if isinstance(location, str) else None
        return node if isinstance(node, Mapping) else None
    if isinstance(maps, (list, tuple)):
        loc = str(location or "")
        for e in maps:
            if isinstance(e, Mapping) and str(e.get("id") or "") == loc:
                return e
        return None
    return None


def _spot_matches(gp_id: str, species_spot: str) -> bool:
    """spots 引用双形态匹配（F-1）：① 直接采集点 id 相等；② \"map:spot\" 组合 id 的
    \":\" 后段与采集点 id 相等。纯函数。"""
    if species_spot == gp_id:
        return True
    return species_spot.endswith(":" + gp_id)


def _season_ok(species: FishDef, season: Optional[str]) -> bool:
    """季节偏好白名单（2c1a §1.4）：seasons 空=全年；否则须含当前季节。
    season 不可识别（None）→ 全年不限（F-2 宁多勿少）。"""
    if season is None:
        return True
    ss = species.seasons
    return (not ss) or (season in ss)


def _period_ok(species: FishDef, period: Optional[str]) -> bool:
    """时段偏好白名单（2c1a §1.4）：periods 空=全天；否则须含当前时段。
    period 不可识别（None）→ 全天不限（F-2 宁多勿少）。"""
    if period is None:
        return True
    pp = species.periods
    return (not pp) or (period in pp)


def _max_rarity(cands: List[FishDef]) -> str:
    """候选鱼种最高 rarity（F-4：gold > rare > normal）；候选无 rarity → normal 兜底。"""
    best: str = "normal"
    best_rank: int = 1
    for s in cands:
        r = s.rarity
        rank = _RARITY_RANK.get(r or "", 1)
        if rank > best_rank:
            best_rank = rank
            best = r or "normal"
    return best


def _union_periods(cands: List[FishDef]) -> str:
    """候选鱼种 periods 并集中文名（F-5：序照枚举，/ 连接）；并集空 → 全天。"""
    seen: set = set()
    for s in cands:
        seen.update(p for p in s.periods if p in _PERIOD_CN)
    if not seen:
        return "全天"
    return "/".join(_PERIOD_CN[p] for p in _PERIOD_ORDER if p in seen)


def list_fishable_spots(ctx: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """当前地图可钓鱼点列举（T05 · 细化 1.1，纯函数确定性）。

    入参 ctx：season/period（当前季节/时段，双形态归一）/ maps（list 形态）/
      location（当前地图 id）/ fish_table 或 fishing（鱼种池）。
    出参：可钓鱼点列表（按 gather_points 原序），每项 {id, name, periods, rarity,
      rarity_cn}：
      - id/name：采集点 id 与展示名（gather_point.name 缺省回退 id）
      - periods：候选鱼种时段偏好并集中文（晨/午/昏/夜/午夜；空=全天）
      - rarity/rarity_cn：候选鱼种最高稀有度（英文键 + 中文标记）
    候选规则：① 采集点被 ≥1 鱼种 spots 引用（垂钓点变体）；② 当前季节/时段存在
    候选鱼种（seasons/periods 白名单命中或空=不限）。无钓点 → []（调用方转空态）。
    """
    season = normalize_season(ctx.get("season"))
    period = normalize_period(ctx.get("period"))
    pool = _species_pool(ctx)
    node = _current_map_node(ctx)
    if node is None:
        return []
    gps = node.get("gather_points")
    if not isinstance(gps, list):
        return []

    out: List[Dict[str, Any]] = []
    for gp in gps:
        if not isinstance(gp, Mapping):
            continue
        gp_id = gp.get("id")
        if not isinstance(gp_id, str) or not gp_id.strip():
            continue
        # ① 垂钓点变体：被 ≥1 鱼种 spots 引用
        spot_species = [
            s for s in pool
            if any(_spot_matches(gp_id, sp) for sp in s.spots)
        ]
        if not spot_species:
            continue
        # ② 候选规则：当前季节/时段存在候选鱼种
        cands = [
            s for s in spot_species
            if _season_ok(s, season) and _period_ok(s, period)
        ]
        if not cands:
            continue
        name = gp.get("name")
        display_name = name if isinstance(name, str) and name else gp_id
        rarity = _max_rarity(cands)
        out.append({
            "id": gp_id,
            "name": display_name,
            "periods": _union_periods(cands),
            "rarity": rarity,
            "rarity_cn": _RARITY_CN.get(rarity, "普通"),
        })
    return out


def first_fishable_spot(ctx: Mapping[str, Any]) -> Optional[str]:
    """无参缺省默认选中第一个可钓点（细化 1.2 实现层约定）：首个可钓点 id；
    无可钓点 → None（供路2B cast 缺省位 / 转发兜底）。纯函数。"""
    spots = list_fishable_spots(ctx)
    if not spots:
        return None
    return str(spots[0].get("id") or "")


def _body_args(parsed: Any) -> List[str]:
    """参数提取（对齐 M9 cmd_forge）：parsed.tokens[1:]（跳过指令名）优先，args 兜底；
    无参时 tokens 长度 1 → 空列表（走列钓点）。"""
    raw_tokens = list(getattr(parsed, "tokens", None) or [])
    if raw_tokens:
        return [str(t) for t in raw_tokens[1:]]
    args = list(getattr(parsed, "args", None) or [])
    return [str(a) for a in args]


def _cast_forward(ctx: MutableMapping[str, Any], spot_arg: str) -> str:
    """有参下钩转发（细化 1.2 / 工程补白 F-7）：try/except ImportError 探活
    core.fishing_cast.cast_fishing（路2B 独占文件，本路不触碰）。

    sibling 未落盘 → 本地兜底返回 FISH_CAST_FALLBACK（【工程补白】文案）；
    已落盘 → 转发 cast_fishing(ctx, spot_id)：spot_arg 空白时缺省默认选中第一个
    可钓点（细化 1.2 实现层约定，first_fishable_spot）。本壳层零守卫（守卫归路2B
    引擎 GU-01~04，对齐 F3 嵌套事务——壳层不做任何资源写入）。
    """
    try:
        from qbot_rpg.core.fishing_cast import cast_fishing
    except ImportError:
        return FISH_CAST_FALLBACK
    spot_id = spot_arg if spot_arg.strip() else first_fishable_spot(ctx)
    result = cast_fishing(ctx, spot_id)
    if isinstance(result, Mapping):
        # P0-1（批8 审查 A5）：simple 直出（settle_pending=True）→ 接结算出鱼
        # （引擎 M-1 已落 last 快照）；full 走等待流程（消息已含等待语义）
        if result.get("mode") == "simple" or result.get("settle_pending"):
            from qbot_rpg.commands.fishing_reel_commands import _settle_after_reel

            settle_msg = _settle_after_reel(ctx, result)
            if settle_msg is not None:
                return settle_msg
        msg = result.get("message")
        if isinstance(msg, str) and msg:
            return msg
    return str(result)


def cmd_fishing(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/钓鱼 主入口（T05 · 细化 2c1b §一 1.1/1.2，纯函数确定性）。

    路由：
      - GU-01（off 模式）→ 拒绝「钓鱼功能已关闭」（TC-09；无参/有参全拒绝）；
      - 有参 → 转发 core.fishing_cast.cast_fishing（路2B；未落盘 → 工程补白兜底
        F-7），spot 缺省位传 None → 默认选中第一个可钓点（细化 1.2）；
      - 无参 → 列当前地图全部可钓鱼点（list_fishable_spots）+ 固定附注鱼讯参考说明
        （TC-01）；无钓点 → 空态文案含「本图暂无可钓鱼点」（TC-02，不输出实体）。

    parsed：ParsedCommand（tokens/args）；ctx：玩家上下文（见 list_fishable_spots
    与 F-6 ctx 契约）。返回：回复正文（消息输出走 tpl_of fish_* + 本地 fallback）。
    """
    # GU-01：mode 路由（off 全拒绝，对齐细化 1.1 / §2.3）
    if _mode_of(ctx) == "off":
        return _render(ctx, "fish_off", _DEF_FISH_OFF, {})

    body = _body_args(parsed)
    if body:
        # 有参下钩转发（路2B）；空参防御 → 传 None 走「默认第一可钓点」缺省位
        return _cast_forward(ctx, body[0])

    # 无参：列钓点（TC-01/TC-02）
    spots = list_fishable_spots(ctx)
    if not spots:
        return _render(ctx, "fish_spot_empty", _DEF_FISH_SPOT_EMPTY, {})

    node = _current_map_node(ctx)
    map_name = str((node or {}).get("name") or ctx.get("location") or "--")
    lines = [_render(ctx, "fish_spot_list_header", _DEF_FISH_SPOT_LIST_HEADER,
                     {"map_name": map_name})]
    for sp in spots:
        lines.append(_render(ctx, "fish_spot_line", _DEF_FISH_SPOT_LINE, {
            "spot_name": str(sp["name"]),
            "periods": str(sp["periods"]),
            "rarity": str(sp["rarity_cn"]),
        }))
    lines.append(_render(ctx, "fish_intent_ref", _DEF_FISH_INTENT_REF_LINE, {}))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 装配：register_fishing_commands（/钓鱼 单指令注册；收杆/鱼讯 归各自路 F-9）
# ---------------------------------------------------------------------------
def register_fishing_commands(
    router: Any,
    *,
    make_context: Optional[Callable[[Any], dict]] = None,
) -> Any:
    """把 /钓鱼 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    :param make_context: ParsedCommand → 玩家 ctx dict（含 maps/location/season/
        period/fish_table/fishing_cfg 等，见 cmd_fishing ctx 契约）。None 时 handler
        调用抛 RuntimeError（【待接线】装配层注入，对齐 shop/forge_commands 口径）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "fishing_commands.register_fishing_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _fishing(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_fishing(parsed, injected)
        return cmd_fishing(parsed, _ctx(parsed))

    # /钓鱼（白名单「钓鱼」由主 agent 装配收口登记，对齐接口摸底 §八-5）
    router.register(CommandSpec(FISH_CMD, handler=_fishing))
    return router
