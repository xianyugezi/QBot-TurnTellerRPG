"""炼金指令接线 alchemy_commands.py（M8 批2·路2A ·
qbot_rpg/commands/alchemy_commands.py）——本批只注册 /合成。

文件名：qbot_rpg/commands/alchemy_commands.py
创建时间：2026-08-29
作者：Hermes 子agent-2A（并发同仓：仅新建本文件 + qbot_rpg/core/synthesis.py +
  tests/unit/test_synthesis.py + tests/unit/test_synthesis_commands.py）

功能描述：把 `/合成` 指令从 Router 接到 core/synthesis.py 引擎——指令解析（parsers.parse_command 已
  token 化 → 本模块取 args[0] 配方名/序号 + parsed.qty 数量）、配方解析与全部业务文案委托引擎
  （引擎已按契约 M-01 合成 ✅/❌ 文案）、错误统一 TPL-12
  （sender.format_tpl12，errors.py 唯一文案源）、
  register_alchemy_commands 装配入口（仿 shop_commands.register_shop_commands 壳模式）。

本批范围（批2 + **批4B 追加** + **批5 追加** + **批6 追加**）：/合成（SYNTH_CMD）+ **/炼金
  （ALCHEMY_CMD：开会话/自动子词/批量 *N）+ /投料（FEED_CMD：链式投料/追加子词）** +
  **/继承（INHERIT_CMD）/继承超（INHERIT_SUPER_CMD：特性继承，委托 core/trait_inherit.py）** +
  **/确认（CONFIRM_CMD）/放弃（ABANDON_CMD）/调合续（RESUME_CMD）/分解（DECOMPOSE_CMD）：
  终态指令壳（批6 路A——品质结算委托 core/alchemy_settle.py SettleEngine、恢复挂起渲染面板、
  分解委托兄弟路 gem_wallet 鸭子类型消费 ctx[\"wallet\"]）**；其余炼金指令
  （/深度炼金 /进化 /复制 /图鉴 /技能面板 /种植 /收获 /雇工 /教学 等）由后续批次填充
  （批7 /成品合成 /配方合成 /特性合成 /镶嵌 /拆珠 /登记 /复制、批8 /深度炼金
  /进化 /镶核心 /加成 /挑战 /图鉴 /技能面板 /教学、批10 /种植 /收获 /雇工 /收取）——本模块作为
  这些指令壳的统一落点文件，后续批次追加 cmd_xxx + register 项即可。

依据：
  - docs/m8_contract_指令契约.md §1 /合成（P-01 参数解析 / GU-01~04 /
    F-01 / M-01，实现批次批2 路2A）、
    §六 IF 清单（cmd_synth 签名 (parsed, ctx) -> str；register_alchemy_commands(router, *,
    make_context=None) 壳模式，本契约命名 cmd_synthesis 对齐任务清单）、§3.4 数量上限 max_qty 注入。
  - qbot_rpg/commands/shop_commands.py（壳模式参考：cmd_xxx(parsed, ctx) -> str 纯函数、
    register_shop_commands(router, *, make_context=None)、零 NoneBot import、
    错误走 sender.format_tpl12、
    __all__ 导出、装饰性 emoji 禁用仅 ✅/❌ 功能性标记、_target_of 剥离 `+`/`*N`）。
  - qbot_rpg/core/synthesis.py（SynthesisEngine 引擎，本模块为其指令壳接线消费方）。

铁律（3a R1 / m4 §0）：**零 NoneBot import**、纯函数（同刻同参必同值）、
确定性（now/rng 由 ctx 注入）；
工程补白一律【工程补白】标注；错误走 TPL-12 统一模板；装饰性 emoji 全局禁用（仅 ✅/❌ 功能性标记）。
本模块只做「装配接线 + 解析 + 透传」，业务结算全部委托引擎。

【工程补白 · 显式标注】
  1) 引擎构造：cmd_synthesis 每次调用以 `SynthesisEngine(settings=ctx.get("settings"))` 构造——
     配置单源（构造器注入，对齐 core/synthesis.py 工程补白 1）；
     ctx["settings"] 缺失 → 引擎默认值兜底。
  2) 配方目标解析：parsed.args[0] 保留原文含 `*数量`（解析器契约，对齐 shop cmd_buy `_target_of`），
     qty 已结构化 → 剥离前导 `+`（紧凑连接符收敛）与 `*N` 后传引擎；引擎再按名称/序号解析。
  3) 超限提示（拍板⑤）由引擎在 synthesize 内归一 count 时处理（settings.alchemy.max_qty 缺省
     2147483647）；parsers 侧 max_qty 注入属批11 路11A 装配职责，本层不重复。
  4) make_context 玩家上下文工厂由装配层注入（register_alchemy_commands 的 make_context 参数），
     注入前本层可纯函数单测（直接构造 ctx，仿 test_shop_commands.make_ctx）。
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Mapping, MutableMapping, Optional

from qbot_rpg.core.alchemy_auto import DEFAULT_MAX_QTY, AutoFeed
from qbot_rpg.core.alchemy_core import (
    ALCHEMY_JOB_ID,
    ELEMENT_NAMES_CN,
    EXPERT_TIER_INDEX,
    AlchemyCore,
)
from qbot_rpg.core.alchemy_session import (
    SUSPENDED,
    TEMPLATE_ALREADY_ACTIVE,
    TEMPLATE_ALREADY_ACTIVE_ALCHEMY,
    TEMPLATE_IN_PROGRESS,
    TEMPLATE_MESSAGES,
    TEMPLATE_NO_SESSION,
    is_alchemy_session,
    is_conflict,
)
from qbot_rpg.core.alchemy_settle import SettleEngine
from qbot_rpg.core.energy_bar import EnergyBar
from qbot_rpg.core.proficiency import ProficiencyEngine
from qbot_rpg.core.quality import QualitySystem
from qbot_rpg.core.synthesis import SynthesisEngine
from qbot_rpg.core.trait_inherit import TraitInherit

# 同包兄弟模块：相对导入（G0 架构门禁 test_commands_web_not_depended 不产生
# `qbot_rpg.commands` 前缀反向依赖边；同层兄弟引用架构合规，与 shop_commands.py 同口径）。
from .router import CommandSpec
from .sender import format_tpl12

__all__ = [
    # 指令名常量
    "SYNTH_CMD", "ALCHEMY_CMD", "FEED_CMD",
    "INHERIT_CMD", "INHERIT_SUPER_CMD",
    "CONFIRM_CMD", "ABANDON_CMD", "RESUME_CMD", "DECOMPOSE_CMD",
    # 固定子词常量
    "AUTO_SUBWORD", "FEED_APPEND_SUBWORD", "CATALYST_KV_KEY",
    # 指令处理器（纯函数/异步：parsed + ctx → 回复正文）
    "cmd_synthesis", "cmd_alchemy", "cmd_feed",
    "cmd_inherit", "cmd_inherit_super",
    "cmd_confirm", "cmd_abandon", "cmd_resume", "cmd_decompose",
    # 装配
    "register_alchemy_commands",
]

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SYNTH_CMD = "合成"
ALCHEMY_CMD = "炼金"
FEED_CMD = "投料"
INHERIT_CMD = "继承"
INHERIT_SUPER_CMD = "继承超"
# 会话终态指令（P-05/SEP-05：均无参数，独立指令名注册；固定子词表已含 确认/放弃/续，
# 白名单补齐归批11 路11A 装配 IF-34）
CONFIRM_CMD = "确认"      # F-05 品质结算终态（GU-17~19）
ABANDON_CMD = "放弃"      # F-05 会话退出终态（GU-17）
RESUME_CMD = "调合续"     # 挂起(战斗) 恢复（GU-18）
DECOMPOSE_CMD = "分解"    # 分解回炉（GU-32/33，P-10）

# 固定子词（对齐 parsers.py FIXED_SUBWORDS：自动/追加 已在常量内，壳层显式引用防字面量漂移）
AUTO_SUBWORD = "自动"
FEED_APPEND_SUBWORD = "追加"
# 触媒键值键（/炼金 <配方> 触媒=<触媒名>，P-02/SEP-02，`=` 键值修饰）
CATALYST_KV_KEY = "触媒"

# 7 级称号默认名（R-07 触媒解锁档位归一兜底，对齐 alchemy_core.DEFAULT_TIER_NAMES）
_DEFAULT_TIER_NAMES: tuple = ("见习", "正式", "精通", "专家", "大师", "宗师", "王")
# 英文档位别名 → 索引（settings.alchemy.catalyst_unlock_tier 兼容 "expert" 等，R-07）
_TIER_ALIAS_INDEX: Mapping[str, int] = {
    "apprentice": 0, "formal": 1, "proficient": 2, "expert": 3,
    "master": 4, "grandmaster": 5, "king": 6,
}


# ---------------------------------------------------------------------------
# 工具（纯函数）
# ---------------------------------------------------------------------------

def _fragment(parsed: Any) -> str:
    """TPL-12 原文片段（parsed.raw 优先；缺省重构，对齐 shop_commands._fragment）。"""
    if getattr(parsed, "raw", None):
        return str(parsed.raw)
    cmd = getattr(parsed, "command", None) or ""
    args = getattr(parsed, "args", None) or []
    tail = (" " + " ".join(str(a) for a in args)) if args else ""
    return f"/{cmd}{tail}"


def _target_of(parsed: Any) -> str:
    """配方目标名剥离（解析器契约 + 紧凑 `+` 连接符收敛，对齐 shop_commands._target_of）：

    - 解析器契约：args[0] 保留原文含 `*数量`，qty 已结构化 → 剥离 `*N` 后传引擎
      （`/合成 火焰弹配方*10` → args=["火焰弹配方*10"], qty=10 → 目标 "火焰弹配方"）。
    - 【工程补白】紧凑格式 `合成+火焰弹配方` 中 `+` 为紧凑连接符（解析器归等级分隔符
      → args[0]="+火焰弹配方"）；配方名不含 `+`（保留字符，REC-16），故剥离前导 `+` 收敛。
    """
    t = str(parsed.args[0])
    if t.startswith("+"):
        t = t[1:]
    if "*" in t:
        t = t.split("*", 1)[0]
    return t


def _settings_of(ctx: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    """settings dict（ctx["settings"]；非法 → None，引擎缺省默认值兜底）。"""
    s = ctx.get("settings")
    return s if isinstance(s, Mapping) else None


def _player_of(ctx: Mapping[str, Any]) -> MutableMapping[str, Any]:
    """玩家状态 dict（ctx["player"] 优先；缺省 ctx 自身——测试可把 ctx 直接当 player）。

    【工程补白】壳层统一读 `player`，能量/熟练度/金币等就地改写对象为同一 dict 引用
    （对齐 EnergyBar/ProficiencyEngine 操作对象口径）。
    """
    player = ctx.get("player")
    if isinstance(player, MutableMapping):
        return player
    return ctx  # type: ignore[return-value]


def _qid_of(ctx: Mapping[str, Any]) -> Optional[str]:
    """玩家 QQ 号（sessions 表主键，MUT-02 全局互斥键）：ctx["qid"] → ctx["player"] 内
    qid/qq/player_qid。"""
    qid = ctx.get("qid")
    if qid:
        return str(qid)
    player = ctx.get("player")
    if isinstance(player, Mapping):
        for k in ("qid", "qq", "player_qid"):
            v = player.get(k)
            if v:
                return str(v)
    return None


def _alchemy_prof_node(player: Mapping[str, Any]) -> Optional[MutableMapping[str, Any]]:
    """player["proficiency"]["alchemy"] 节点（GU-05 炼金职业判定；M8 决策 4：proficiency dict
    形态，Player dataclass 不加字段）。"""
    prof = player.get("proficiency")
    if isinstance(prof, Mapping):
        node = prof.get(ALCHEMY_JOB_ID)
        if isinstance(node, MutableMapping):
            return node
    return None


def _prof_level(player: Mapping[str, Any]) -> int:
    """炼金职业等级（GU-05；缺节点/非法 → 0 见习兜底）。"""
    node = _alchemy_prof_node(player)
    if node is None:
        return 0
    try:
        return max(0, int(node.get("level", 0)))
    except (TypeError, ValueError):
        return 0


def _find_def(
    ctx: Mapping[str, Any], reg_key: str, resolve_key: str, key: Any
) -> Optional[dict]:
    """注册表 def 解析（id → resolver → name 扫描，对齐 AlchemyCore._find_def 鸭子模式）。"""
    if not isinstance(key, str) or not key:
        return None
    reg = ctx.get(reg_key)
    if isinstance(reg, Mapping) and key in reg:
        val = reg[key]
        return dict(val) if isinstance(val, Mapping) else None
    resolver = ctx.get(resolve_key)
    if callable(resolver):
        try:
            val = resolver(key)
            if isinstance(val, Mapping):
                return dict(val)
        except Exception:
            return None
    if isinstance(reg, Mapping):
        for val in reg.values():
            if isinstance(val, Mapping) and val.get("name") == key:
                return dict(val)
    return None


def _find_item(ctx: Mapping[str, Any], key: Any) -> Optional[dict]:
    """物品 def（items 注册表 / resolve_item / name 扫描）。"""
    return _find_def(ctx, "items", "resolve_item", key)


def _find_recipe(ctx: Mapping[str, Any], key: Any) -> Optional[dict]:
    """配方 def（recipe 注册表 / resolve_recipe / name 扫描）。"""
    return _find_def(ctx, "recipe", "resolve_recipe", key)


def _item_name(ctx: Mapping[str, Any], item_id: Any) -> str:
    """物品中文名（items.name 优先，缺省原 id）。"""
    idef = _find_item(ctx, item_id)
    if idef is not None:
        name = idef.get("name")
        if isinstance(name, str) and name:
            return name
    return str(item_id)


def _count_item(ctx: Mapping[str, Any], item_id: str) -> int:
    """背包持有数（ctx["count_item"](id)->int hook 优先；ctx["inventory"] dict 兜底）。"""
    fn = ctx.get("count_item")
    if callable(fn):
        try:
            return max(0, int(fn(item_id)))
        except Exception:
            return 0
    inv = ctx.get("inventory")
    if isinstance(inv, Mapping):
        try:
            return max(0, int(inv.get(item_id, 0)))
        except (TypeError, ValueError):
            return 0
    return 0


def _remove_item(ctx: MutableMapping[str, Any], item_id: str, count: int) -> Any:
    """扣材料（ctx["remove_item"](id, count) hook 优先；inventory dict 就地扣减兜底）。"""
    fn = ctx.get("remove_item")
    if callable(fn):
        return fn(item_id, count)
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        inv[item_id] = max(0, int(inv.get(item_id, 0)) - count)
    return None


def _add_item(
    ctx: MutableMapping[str, Any], item_id: str, count: int, *, quality: Any = None
) -> Any:
    """入包（ctx["add_item"] hook 优先，透传 quality；inventory dict 就地累加兜底）。"""
    fn = ctx.get("add_item")
    if callable(fn):
        if quality is not None:
            try:
                return fn(item_id, count, quality=quality)
            except TypeError:
                return fn(item_id, count)
        return fn(item_id, count)
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        inv[item_id] = int(inv.get(item_id, 0)) + count
    return None


def _currencies(player: Mapping[str, Any]) -> MutableMapping[str, Any]:
    """玩家货币桶（player["currencies"] dict，缺省空——BATCH-05 金币扣减读写点）。"""
    c = player.get("currencies")
    return c if isinstance(c, MutableMapping) else {}


def _coins_of(player: Mapping[str, Any]) -> int:
    """金币持有（currencies.coins，BATCH-05 原子校验）。"""
    try:
        return max(0, int(_currencies(player).get("coins", 0)))
    except (TypeError, ValueError):
        return 0


def _tier_names_of(prof_engine: Any) -> tuple:
    """职业档位称号名（0~6，内容包可改名；对齐 ProficiencyEngine.tier_name）。"""
    try:
        return tuple(prof_engine.tier_name(ALCHEMY_JOB_ID, i) for i in range(7))
    except Exception:
        return _DEFAULT_TIER_NAMES


def _norm_tier_value(value: Any, prof_engine: Any) -> int:
    """配置档位值（int=索引 / 称号名 / 英文别名）→ 档位索引（CAT-01 R-07，缺省 expert=3）。"""
    if isinstance(value, bool):
        return EXPERT_TIER_INDEX
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, str) and value:
        names = _tier_names_of(prof_engine)
        if value in names:
            return names.index(value)
        return _TIER_ALIAS_INDEX.get(value, EXPERT_TIER_INDEX)
    return EXPERT_TIER_INDEX


def _catalyst_unlock_tier_index(settings: Any, prof_engine: Any) -> int:
    """settings.alchemy.catalyst_unlock_tier → 档位索引（缺省 "expert"=3，R-07 定案）。"""
    alch = settings.get("alchemy") if isinstance(settings, Mapping) else None
    raw: Any = "expert"
    if isinstance(alch, Mapping):
        raw = alch.get("catalyst_unlock_tier", "expert")
    return _norm_tier_value(raw, prof_engine)


def _energy_enabled(settings: Any) -> bool:
    """能量条开关（ENG-01/R-08：默认关；关闭时守卫直通、不扣能量、无能量不足模板）。"""
    alch = settings.get("alchemy") if isinstance(settings, Mapping) else None
    return bool(alch.get("energy_enabled", False)) if isinstance(alch, Mapping) else False


def _max_qty(settings: Any) -> int:
    """批量数量上限（BATCH-04 拍板⑤：默认 2147483647，settings.alchemy.max_qty 可配）。"""
    alch = settings.get("alchemy") if isinstance(settings, Mapping) else None
    if isinstance(alch, Mapping):
        try:
            mq = int(alch.get("max_qty", DEFAULT_MAX_QTY) or DEFAULT_MAX_QTY)
        except (TypeError, ValueError):
            mq = DEFAULT_MAX_QTY
        if mq >= 1:
            return mq
    return DEFAULT_MAX_QTY


def _catalyst_kv(parsed: Any) -> Optional[str]:
    """触媒键值解析（P-02/SEP-02）：parsed.kv 键 `触媒` → value；args 内 `触媒=` 前缀兜底。"""
    for item in getattr(parsed, "kv", None) or []:
        if isinstance(item, Mapping) and item.get("key") == CATALYST_KV_KEY:
            v = item.get("value")
            if v:
                return str(v)
    for a in getattr(parsed, "args", None) or []:
        s = str(a)
        if s.startswith(f"{CATALYST_KV_KEY}="):
            return s.split("=", 1)[1]
    return None


def _shortfall_text(ctx: Mapping[str, Any], shortfall: Any) -> str:
    """差异提示串（AUTO-03/L115 原子口径）：「缺 火药×1」（多条目以「 + 」连接）。

    兼容 {item,count,have}（apply_feed 输出）与 {item,name,need}（AutoFeed 输出）。
    """
    parts: list = []
    for s in shortfall or []:
        if not isinstance(s, Mapping):
            continue
        item = s.get("item") or s.get("id")
        name = s.get("name") or (_item_name(ctx, item) if item else None) or "?"
        if "need" in s and s["need"] is not None:
            try:
                need = max(0, int(s["need"]))
            except (TypeError, ValueError):
                continue
        else:
            try:
                have = int(s.get("have", 0) or 0)
                count = int(s.get("count", 1) or 1)
            except (TypeError, ValueError):
                continue
            need = max(0, count - have)
        if need > 0:
            parts.append(f"缺 {name}×{need}")
    return " + ".join(parts)


def _energy_message(energy: Any, player: Mapping[str, Any], n: int = 1) -> str:
    """能量不足模板（ENG-04/L344）：「能量 0/10，等 30 分钟回 1 格，或 /合成 保底」。

    守卫期已确认不足（current < n），consume(n) 只读返回不足消息（不扣、零副作用）。
    """
    res = energy.consume(player, n)
    return str(res.get("message") or "能量不足")


def _tier_score(qs: QualitySystem, tier_key: Any) -> int:
    """品质档 → 档位代表分（区间中点，批量平均品质 material_scores 折算，BATCH-02）。"""
    rng = qs.tiers.get(str(tier_key))
    if rng is None:
        return 0
    lo, hi = rng
    return (lo + hi) // 2


def _material_entry_text(rec: Mapping[str, Any], ctx: Mapping[str, Any]) -> str:
    """单条投料材料展示：`名称×数量(元素中文+值)`；无主元素 → `名称×数量`（M-02「任意×1」）。"""
    name = rec.get("name") or rec.get("item") or "?"
    count = max(1, int(rec.get("count", 1)))
    main = rec.get("main_element")
    if isinstance(main, str):
        elems = rec.get("elements") or {}
        try:
            val = int(elems.get(main, 0))
        except (TypeError, ValueError):
            val = 0
        cn = ELEMENT_NAMES_CN.get(main, main)
        return f"{name}×{count}({cn}{val})"
    return f"{name}×{count}"


def _recipe_material_text(core: AlchemyCore, recipe: Mapping[str, Any],
                          ctx: Mapping[str, Any]) -> str:
    """配方材料清单展示（开会话空链时用，M-02「材料：火药×1(火2) 矿石×1 任意×1」）。

    复用引擎主元素判定（AlchemyCore._main_element，A-2/FEED-06 同属性判定同源口径）。
    """
    parts: list = []
    for m in recipe.get("materials") or []:
        mid = m.get("id") if isinstance(m, Mapping) else m
        cnt = m.get("count", 1) if isinstance(m, Mapping) else 1
        idef = _find_item(ctx, mid) if isinstance(mid, str) else None
        if idef is None:
            parts.append(f"{mid}×{cnt}")
            continue
        name = idef.get("name") or mid
        elems = idef.get("elements")
        main = core._main_element(elems) if isinstance(elems, Mapping) else None
        if isinstance(main, str):
            try:
                val = int(elems.get(main, 0)) if isinstance(elems, Mapping) else 0
            except (TypeError, ValueError):
                val = 0
            cn = ELEMENT_NAMES_CN.get(main, main)
            parts.append(f"{name}×{cnt}({cn}{val})")
        else:
            parts.append(f"{name}×{cnt}")
    return " ".join(parts) if parts else "（无）"


def _render_scales(recipe: Optional[Mapping[str, Any]]) -> str:
    """属性刻度渲染（M-02「属性刻度：火≥6 显现\"范围爆炸\"」，取每元素最高阈值档，FEED-07）。"""
    req = recipe.get("element_req") if recipe else None
    if not isinstance(req, Mapping) or not req:
        return "（无刻度要求）"
    parts: list = []
    for elem, steps in req.items():
        if not isinstance(steps, (list, tuple)) or not steps:
            continue
        best: Optional[tuple] = None
        for s in steps:
            if isinstance(s, Mapping):
                try:
                    th = int(s.get("threshold", 0))
                except (TypeError, ValueError):
                    th = 0
                if best is None or th > best[0]:
                    best = (th, s.get("effect"))
        if best is None:
            continue
        cn = ELEMENT_NAMES_CN.get(elem, elem)
        parts.append(f'{cn}≥{best[0]} 显现"{best[1]}"')
    return " ".join(parts) if parts else "（无刻度要求）"


def _render_panel(core: AlchemyCore, snap: Mapping[str, Any], ctx: Mapping[str, Any],
                  job_tier_index: int) -> str:
    """开会话面板（M-02 模板结构，**纯文本降级**——全仓 emoji 纪律 test_emoji_discipline 仅
    允许 ✅/❌，📖/⚗️/🔥 等模板标记按「数据型功能图标一律降级纯文本」弃用）：
    `火焰弹（配方Lv5）：材料：火药×1(火2) 矿石×1 任意×1`
    `属性刻度：火≥6 显现"范围爆炸" | 特性位 2/3 | PP 5/5 | 投入次数 4`

    数据全部取自 assemble_panel 渲染结构（element_req_status/pp/traits_inherit）。
    """
    panel = core.assemble_panel(snap, ctx, job_tier_index=job_tier_index)
    recipe = _find_recipe(ctx, snap.get("recipe_id"))
    recipe_name = str(panel.get("recipe_name") or snap.get("recipe_id") or "")
    level = recipe.get("level", "?") if recipe else "?"
    chain = snap.get("materials") or []
    if chain:
        mats = " ".join(_material_entry_text(r, ctx) for r in chain if isinstance(r, Mapping))
        if not mats:
            mats = "（无）"
    else:
        mats = _recipe_material_text(core, recipe, ctx) if recipe else "（无）"
    scales = _render_scales(recipe)
    traits_max = int(panel.get("traits_inherit", 1) or 1)
    traits_used = 0  # 批5 /继承 落位后计（现快照无继承位字段，开会话恒 0）
    pp = panel.get("pp") or {}
    slots = int(recipe.get("slots", 4) or 4) if recipe else 4
    units = sum(max(1, int(r.get("count", 1))) for r in chain if isinstance(r, Mapping))
    return (
        f"{recipe_name}（配方Lv{level}）：材料：{mats}\n"
        f"属性刻度：{scales} | 特性位 {traits_used}/{traits_max} | "
        f"PP {pp.get('used', 0)}/{pp.get('budget', 0)} | 投入次数 {units}/{slots}"
    )


def _feed_feedback(core: AlchemyCore, snap: Mapping[str, Any],
                   ctx: Mapping[str, Any]) -> str:
    """投料成功反馈（M-03 模板结构，**纯文本降级**——emoji 纪律同上，⚗️/🔥/✓ 弃用）：
    `火+7 | 连锁 2 段 | 可继承特性：灼烧强化(PP1) 回复量+5%(PP1)`
    附：连锁 ≥3 段 → `连锁 N 段 → 效果等级 N`；刻度达标 → `火+42（刻度 30·范围爆炸）`。
    """
    chain = snap.get("chain") or {}
    segments = int(chain.get("segments", 0) or 0)
    effect_level = int(chain.get("effect_level", 0) or 0)
    scores = snap.get("element_scores") or {}
    if not isinstance(scores, Mapping):
        scores = {}
    main_elem: Optional[str] = None
    main_score = 0
    for k, v in scores.items():
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        if iv > main_score:
            main_score, main_elem = iv, k
    elem_cn = ELEMENT_NAMES_CN.get(main_elem, main_elem) if main_elem else "无"
    parts = [f"{elem_cn}+{main_score}", f"连锁 {segments} 段"]
    pool = snap.get("pool") or {}
    if not isinstance(pool, Mapping):
        pool = {}
    traits = [f"{name}(PP{pp})" for _tid, name, pp in pool.get("normal") or []]
    gold = [f"{name}(PP{pp})" for _tid, name, pp in pool.get("gold") or []]
    awaken = [f"{name}(PP{pp})" for _tid, name, pp in pool.get("awaken") or []]
    if gold:
        traits.append("金色：" + " ".join(gold))
    if awaken:
        traits.append("觉醒：" + " ".join(awaken))
    if traits:
        parts.append("可继承特性：" + " ".join(traits))
    if segments >= 3:
        parts.append(f"连锁 {segments} 段 → 效果等级 {effect_level}")
    recipe = _find_recipe(ctx, snap.get("recipe_id"))
    if recipe is not None:
        status = core.check_element_req(recipe, scores)
        for st in status.values():
            if st.get("met") and st.get("met_effect") is not None and st.get("thresholds"):
                cn = ELEMENT_NAMES_CN.get(st.get("element"), st.get("element"))
                ths = st.get("thresholds") or []
                th = ths[-1].get("threshold", 0)
                parts.append(
                    f"刻度达标 {cn}+{st.get('score', 0)}"
                    f"（刻度 {th}·{st.get('met_effect')}）"
                )
    return " | ".join(parts)


def _feed_error(res: Mapping[str, Any], ctx: Mapping[str, Any]) -> str:
    """投料失败透传（GU-11/12：超槽位 / 材料不足差异 / 全物入料专家 / 材料不存在 / 无会话）。"""
    reason = res.get("reason")
    msg = res.get("message")
    if reason == "slots_overflow":
        return "投料超槽位"
    if reason == "materials_insufficient":
        diff = _shortfall_text(ctx, res.get("shortfall"))
        return f"材料不足：{diff}" if diff else "材料不足"
    if reason == "expert_required":
        return "全物入料需专家级"
    if reason == "item_not_found":
        return str(msg or "材料不存在")
    if reason == "no_snapshot":
        return TEMPLATE_MESSAGES[TEMPLATE_NO_SESSION]
    return str(msg or "投料失败")


def _auto_diff_message(bal: Mapping[str, Any], ctx: Mapping[str, Any]) -> str:
    """自动配平失败原子拒绝（AUTO-03/L115：全拒+差异，不部分入料、零消耗）。"""
    msg = bal.get("message")
    if isinstance(msg, str) and msg:
        return msg
    diff = _shortfall_text(ctx, bal.get("shortfall"))
    return f"材料不足：{diff}" if diff else "❌ 自动配平失败"


def _batch_material_scores(recipe: Mapping[str, Any], ctx: Mapping[str, Any],
                           qs: QualitySystem) -> list:
    """批量投料材料品质分（BATCH-02：材料 items.json quality 档 → 档位代表分 × count）。"""
    scores: list = []
    for m in recipe.get("materials") or []:
        mid = m.get("id") if isinstance(m, Mapping) else m
        cnt = m.get("count", 1) if isinstance(m, Mapping) else 1
        idef = _find_item(ctx, mid) if isinstance(mid, str) else None
        tier = idef.get("quality") if idef else None
        score = _tier_score(qs, tier) if isinstance(tier, str) else 0
        try:
            ci = max(1, int(cnt))
        except (TypeError, ValueError):
            ci = 1
        scores.extend([score] * ci)
    return scores


def cmd_synthesis(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`/合成 <配方>*<数量>`：配方解析（名称/序号）与守卫/原子校验/标准版产出/熟练经验全部委托引擎；
    结果 `message` 透传（含缺材料差异、等级不足、深度未解锁、数量超限提示不拦截）。
    缺参/解析错误 → TPL-12。

    入参：parsed（ParsedCommand）、ctx（玩家表示 + 配方/物品注册表 + settings）。
    出参：回复正文 str（引擎已按契约 M-01 合成 ✅/❌ 业务文案）。
    """
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if not parsed.args:
        return format_tpl12(f"/{SYNTH_CMD}")
    target = _target_of(parsed)
    qty = parsed.qty if parsed.qty is not None else 1
    settings = ctx.get("settings")
    engine = SynthesisEngine(settings=settings if isinstance(settings, Mapping) else None)
    res = engine.synthesize(ctx, target, qty)
    return str(res.get("message") or "❌ 合成失败")


async def cmd_alchemy(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`/炼金 <配方> [触媒=<触媒名> | 自动]`（P-02/SEP-02，批4 路4A/4C）。

    三条路径：
      - 主路径：开会话（F-02/§7.1 行1：acquire 成功 → 扣能量 → 面板 M-02）；
      - 自动子词 `自动`：一键投料自动配平（AUTO-01~03）→ 入链 → 开会话；
      - 批量 `*N`（N≥2）：单批量一步出结果（BATCH-01~05），**不开会话**。

    守卫链 GU-05~08（合同顺序；能量消耗在 acquire 成功后执行——§7.1 行1「acquire 成功 →
    扣能量 → 面板渲染」，守卫期只读检查防孤儿会话/防配平失败白扣）：
      - GU-05 炼金职业见习+（proficiency.alchemy 节点存在，否则「等级不足」，L344）；
      - GU-06 能量 ≥1 格（仅 energy_enabled=true，ENG-04/R-08；关闭直通不扣）；
      - GU-07 单玩家无活跃调合会话（MUT-02 全局互斥，私聊+多群同）；
      - GU-08 触媒需专家（CAT-01 R-07，settings.alchemy.catalyst_unlock_tier 可配；
        `自动`/不带触媒参数不触发）。
    入参：parsed（ParsedCommand）、ctx（player/session_mgr/items/recipe/settings 等，session_mgr
    为 async SessionManager 或 fake）。
    出参：回复正文 str（面板/错误模板/批量结果）。
    """
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if not parsed.args:
        return format_tpl12(f"/{ALCHEMY_CMD}")
    target = _target_of(parsed)
    qty = parsed.qty if parsed.qty is not None else 1
    auto = bool(getattr(parsed, "fixed_subword", None) == AUTO_SUBWORD) or any(
        str(a) == AUTO_SUBWORD for a in (getattr(parsed, "args", None) or [])
    )
    catalyst_name = _catalyst_kv(parsed)

    player = _player_of(ctx)
    settings = _settings_of(ctx)
    prof_engine = ProficiencyEngine(settings=settings)
    core = AlchemyCore(prof=prof_engine, settings=settings)
    energy = EnergyBar(settings=settings)
    auto_engine = AutoFeed(settings=settings)
    alch = settings.get("alchemy") if isinstance(settings, Mapping) else None
    qs = QualitySystem(
        quality_tiers=alch.get("quality_tiers") if isinstance(alch, Mapping) else None,
        quality_coef=alch.get("quality_coef") if isinstance(alch, Mapping) else None,
        tier_labels=alch.get("tier_labels") if isinstance(alch, Mapping) else None,
    )

    # GU-05 炼金职业见习+（proficiency.alchemy 节点存在；M8 决策 4 dict 形态）
    if _alchemy_prof_node(player) is None:
        return "❌ 等级不足"
    tier_index = prof_engine.tier_index_for_level(ALCHEMY_JOB_ID, _prof_level(player))

    recipe = _find_recipe(ctx, target)
    if recipe is None:
        return f"❌ 配方不存在：{target}"

    # 批量分支（P-02/BATCH-01：N≥2 = 单批量一步出结果，无投料/继承/确认链，不开会话）
    if qty >= 2:
        return _cmd_alchemy_batch(
            player, recipe, qty, ctx, core, energy, auto_engine, qs, prof_engine
        )

    # GU-06 能量可查（ENG-04：read 检查不扣；energy_enabled=false 直通，R-08）
    if _energy_enabled(settings) and energy.current_of(player) < 1:
        return _energy_message(energy, player)

    # GU-07 会话互斥（MUT-02：单玩家 1 调合会话，sessions.player_qid 主键全局互斥）
    session_mgr = ctx.get("session_mgr")
    if session_mgr is None:
        raise RuntimeError(
            "alchemy_commands.cmd_alchemy 需要 ctx['session_mgr']"
            "（SessionManager 或 async fake，批11 装配注入）"
        )
    qid = _qid_of(ctx)
    active = await session_mgr.get_active(qid)
    if active is not None:
        if is_alchemy_session(active):
            return TEMPLATE_MESSAGES[TEMPLATE_IN_PROGRESS]  # 调合进行中！
        return TEMPLATE_MESSAGES[TEMPLATE_ALREADY_ACTIVE]   # 已有活跃会话

    # GU-08 触媒需专家（R-07/CAT-01：仅指定触媒时触发；`自动`/无触媒不触发）
    catalyst: Optional[str] = None
    catalyst_hint: Optional[str] = None
    if catalyst_name:
        if tier_index < _catalyst_unlock_tier_index(settings, prof_engine):
            return "❌ 等级不足"
        cres = core.catalyst_resolve(catalyst_name, ctx)
        if not cres.get("ok"):
            return str(cres.get("message") or "触媒无效")  # CAT-05/L344 触媒无效
        if cres.get("registered"):
            catalyst = catalyst_name
        else:
            catalyst_hint = str(cres.get("message") or "")  # CAT-03 注册制：仅提示不阻断
    else:
        catalyst = None
        catalyst_hint = None

    # 自动子词分支（AUTO-01/02/03）：配平 → 入链 → 开会话；配平失败全拒、零消耗
    if auto:
        snap0 = core.new_snapshot(recipe, catalyst=catalyst, job_tier=tier_index)
        bal = auto_engine.balance(ctx, recipe)
        if not bal.get("ok"):
            return _auto_diff_message(bal, ctx)
        plan = bal.get("plan") or []
        fed = core.apply_feed(
            snap0, [{"item": it, "count": ct} for it, ct in plan], ctx, append=False
        )
        if not fed.get("ok"):
            return _feed_error(fed, ctx)
        snap = fed["snap"]
    else:
        snap = core.new_snapshot(recipe, catalyst=catalyst, job_tier=tier_index)

    # 开会话（F-02/§7.1 行1：acquire 成功 → 扣能量 → 面板渲染）
    try:
        await session_mgr.acquire(qid, "alchemy", payload=snap)
    except Exception as exc:  # SessionConflictError 鸭子判定（MUT-02 全局互斥）
        if is_conflict(exc):
            return TEMPLATE_MESSAGES[TEMPLATE_ALREADY_ACTIVE]
        raise
    econs = energy.consume(player, 1)
    if not econs.get("ok"):
        # 守卫通过后竞态能量不足 → 释放会话防孤儿（ENG-04/08 保底 /合成）
        if hasattr(session_mgr, "release"):
            await session_mgr.release(qid)
        return str(econs.get("message") or "能量不足")
    panel = _render_panel(core, snap, ctx, tier_index)
    if catalyst_hint:
        return f"{catalyst_hint}\n{panel}"
    return panel


def _cmd_alchemy_batch(
    player: MutableMapping[str, Any],
    recipe: Mapping[str, Any],
    qty: int,
    ctx: MutableMapping[str, Any],
    core: AlchemyCore,
    energy: EnergyBar,
    auto_engine: AutoFeed,
    qs: QualitySystem,
    prof_engine: ProficiencyEngine,
) -> str:
    """批量调合（BATCH-01~05，**不开会话**）。

    顺序：数量上限提示不拦截（BATCH-04 拍板⑤）→ 原子校验（材料×N+能量N格+金币全量，
    不足全拒+差异 BATCH-05）→ 平均品质产出（BATCH-02 丢特性）→ 熟练经验（配方等级×N）→
    批量结果消息。能量 N 格按次扣减（ENG-04/BATCH-03），指令执行时一次性原子扣减。
    """
    settings = _settings_of(ctx)
    # BATCH-04 拍板⑤：数量上限超限仅提示不拦截
    qc = auto_engine.check_quantity(qty, max_qty=_max_qty(settings))
    hint = qc.get("message") if qc.get("over_limit") else None

    # BATCH-03 能量 N 格（read 检查；energy_enabled=false 直通）
    energy_note = ""
    if _energy_enabled(settings):
        if energy.current_of(player) < qty:
            return _energy_message(energy, player, qty)
        energy_note = f"能量 -{qty}"

    # BATCH-05 原子校验：材料×N + 金币全量（不足全拒+差异，不部分执行）
    cost = recipe.get("cost")
    coins_per = int(cost.get("coins", 0)) if isinstance(cost, Mapping) else 0
    coins_need = coins_per * qty
    need_mats: list = []
    shortfall: list = []
    for m in recipe.get("materials") or []:
        mid = m.get("id") if isinstance(m, Mapping) else m
        cnt = m.get("count", 1) if isinstance(m, Mapping) else 1
        try:
            ci = max(1, int(cnt))
        except (TypeError, ValueError):
            ci = 1
        need_mats.append((mid, ci))
        have = _count_item(ctx, mid) if isinstance(mid, str) else 0
        if have < ci * qty:
            shortfall.append({"item": mid, "count": ci * qty, "have": have})
    if coins_need > 0 and _coins_of(player) < coins_need:
        shortfall.append({"item": "coins", "name": "金币",
                          "count": coins_need, "have": _coins_of(player)})
    if shortfall:
        diff = _shortfall_text(ctx, shortfall)
        return f"❌ 材料不足：{diff}" if diff else "❌ 材料不足"

    # 原子执行：扣材料 → 扣金币 → 扣能量 N → 平均品质产出 → 熟练经验
    for mid, ci in need_mats:
        _remove_item(ctx, mid, ci * qty)
    if coins_need > 0:
        _currencies(player)["coins"] = max(0, _coins_of(player) - coins_need)
    if _energy_enabled(settings):
        energy.consume(player, qty)
    scores = _batch_material_scores(recipe, ctx, qs)
    bq = auto_engine.batch_quality(scores, quality=qs)
    output = recipe.get("output")
    output_id = output.get("item") if isinstance(output, Mapping) else None
    if not isinstance(output_id, str) or not output_id:
        return "❌ 该配方无法批量调合"
    _add_item(ctx, output_id, qty, quality=bq["tier"])
    level = recipe.get("level")
    if isinstance(level, int) and not isinstance(level, bool) and level > 0:
        prof_engine.gain_prof_exp(player, ALCHEMY_JOB_ID, level * qty, source="craft")

    mats_text = " + ".join(f"{_item_name(ctx, mid)}×{ci * qty}" for mid, ci in need_mats)
    coin_text = f" + 金币 {coins_need}" if coins_need else ""
    output_name = _item_name(ctx, output_id)
    main = (
        f"✅ {output_name} ×{qty}（批量调合：消耗 {mats_text}{coin_text}）｜"
        f"平均品质 {bq['score']}·{qs.tier_label(bq['tier'])}"
    )
    if energy_note:
        main += f"｜{energy_note}"
    if hint:
        main = f"{hint}\n{main}"
    return main


async def cmd_feed(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`/投料 <材料1>,<材料2>,… [追加]`（P-03/SEP-03，链式投料 F-03，批4 路4B）。

    守卫链 GU-09~12：
      - GU-10 战斗拦截（MUT-04/INST-06/L295：战斗中 → 「战斗中使用 /即时调合 <配方>」）
        ——先于会话查询（战斗会话占用槽位，FEED-03）；
      - GU-09 调合会话中（FEED-02/L175：无/非调合会话 → 「当前没有调合会话，先 /炼金
        <配方> 开始」）；
      - GU-11 不超槽位（FEED-04/L344「投料超槽位」）、GU-12 材料持有（FEED-05 逐项校验、
        不足全拒+差异）——由 AlchemyCore.apply_feed 校验链承载。
    流程：取会话快照 → apply_feed(append=...) → suspend 持久化（version 递增，§7.1 行4）→
    反馈 M-03（⚗️ 连锁段数 + 可继承特性清单）。
    入参：parsed（ParsedCommand）、ctx（session_mgr/items/recipe/settings 等，session_mgr
    为 async SessionManager 或 fake）。
    出参：回复正文 str。
    """
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if not parsed.args:
        return format_tpl12(f"/{FEED_CMD}")
    append = bool(getattr(parsed, "fixed_subword", None) == FEED_APPEND_SUBWORD) or any(
        str(a) == FEED_APPEND_SUBWORD for a in (getattr(parsed, "args", None) or [])
    )
    tokens = _feed_tokens(parsed)
    materials: list = []
    for tok in tokens:
        s = str(tok).strip()
        if not s:
            continue
        if "*" in s:
            item, _, cnt = s.partition("*")
            try:
                n = int(cnt)
            except (TypeError, ValueError):
                n = 1
            n = max(1, n)
        else:
            item, n = s, 1
        if not item:
            continue
        # 名称 → 规范 id（apply_feed 按 item id 做持有校验，背包键=id；FEED-05 逐项校验）
        idef = _find_item(ctx, item)
        item_id = idef.get("id") or item if idef else item
        materials.append({"item": item_id, "count": n})
    if not materials:
        return format_tpl12(f"/{FEED_CMD}")

    settings = _settings_of(ctx)
    core = AlchemyCore(prof=ProficiencyEngine(settings=settings), settings=settings)
    session_mgr = ctx.get("session_mgr")
    if session_mgr is None:
        raise RuntimeError(
            "alchemy_commands.cmd_feed 需要 ctx['session_mgr']"
            "（SessionManager 或 async fake，批11 装配注入）"
        )
    qid = _qid_of(ctx)

    # GU-10 战斗拦截（MUT-04：先于会话查询，战斗会话占用槽位）
    if ctx.get("in_battle"):
        return "战斗中使用 /即时调合 <配方>（不进入调合会话）"

    # GU-09 会话中（FEED-02/L175：无会话 / 非调合类会话 → 无会话模板）
    view = await session_mgr.get_active(qid)
    if view is None or not is_alchemy_session(view):
        return TEMPLATE_MESSAGES[TEMPLATE_NO_SESSION]
    snap = _view_payload(view)

    # GU-11/12 apply_feed 校验链（槽位上限 FEED-04 / 材料持有 FEED-05，原子口径）
    res = core.apply_feed(snap, materials, ctx, append=append)
    if not res.get("ok"):
        return _feed_error(res, ctx)
    new_snap = res["snap"]
    await session_mgr.suspend(qid, new_snap)
    return _feed_feedback(core, new_snap, ctx)


def _view_payload(view: Any) -> Mapping[str, Any]:
    """会话视图 payload 鸭子读取（属性 .payload 优先，dict 键兜底——
    对齐 alchemy_session 视图契约）。"""
    if view is None:
        return {}
    payload = getattr(view, "payload", None)
    if payload is None and isinstance(view, Mapping):
        payload = view.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _feed_tokens(parsed: Any) -> list:
    """投料材料 token 列表（P-03/SEP-03：先 `,` 拆列表 → 再 `*` 拆数量 → 再 `=` 拆键值）。

    parsers 把 `,` 列表写入 parsed.targets（单项保留 `*N`）；targets 为空（单材料/追加子词）
    回落 args 逗号拆分（跳过固定子词 `追加`）。
    """
    targets = [str(t) for t in (getattr(parsed, "targets", None) or []) if str(t).strip()]
    if targets:
        return targets
    out: list = []
    for a in getattr(parsed, "args", None) or []:
        s = str(a)
        if s == FEED_APPEND_SUBWORD:
            continue
        out.extend(x for x in s.split(",") if x.strip())
    return out


def _find_trait(ctx: Mapping[str, Any], key: Any) -> Optional[dict]:
    """特性 def（traits 注册表 / resolve_trait / name 扫描，对齐 AlchemyCore._find_trait）。"""
    return _find_def(ctx, "traits", "resolve_trait", key)


def _trait_name(ctx: Mapping[str, Any], trait_id: Any) -> str:
    """特性展示名（traits.name 优先，缺省原 id；STO-07 特性显示）。"""
    tdef = _find_trait(ctx, trait_id)
    if tdef is not None:
        name = tdef.get("name")
        if isinstance(name, str) and name:
            return name
    return str(trait_id)


def _inherit_tokens(parsed: Any) -> list:
    """/继承 /继承超 特性名 token 列表（P-04/SEP-04：`,` 分隔列表；parsed.targets 优先，
    回落 args 逗号拆分，对齐 _feed_tokens 口径）。"""
    targets = [str(t) for t in (getattr(parsed, "targets", None) or []) if str(t).strip()]
    if targets:
        return targets
    out: list = []
    for a in getattr(parsed, "args", None) or []:
        out.extend(x for x in str(a).split(",") if x.strip())
    return out


def _inherit_error(res: Mapping[str, Any]) -> str:
    """/继承 /继承超 失败透传（GU-14 PP 不足 / GU-15 继承超 N 项 / GU-16 互斥组名 +
    INH-01 候选清单 / INH-14 无继承位 / TSC-11 超特性宗师）。"""
    reason = res.get("reason")
    msg = res.get("message")
    if reason == "no_inherit_slot":
        return "❌ 见习无继承位"                     # INH-14/L344
    if reason == "no_snapshot":
        return TEMPLATE_MESSAGES[TEMPLATE_NO_SESSION]
    if reason == "pp_insufficient":
        return "❌ PP 不足"                          # INH-09/L344
    if reason == "slot_overflow":
        limit = res.get("limit")
        return f"❌ 继承超 {limit} 项"               # INH-06/L344
    if reason == "group_conflict":
        g = res.get("group")
        return f"❌ 互斥组内最多 1 项：{g}"          # INH-10
    if reason == "not_repeatable":
        return "❌ 该特性不可重复继承"               # INH-11
    if reason == "gold_slot_occupied":
        return "❌ 第 4 位金色已占用"                # TSC-12
    return f"❌ {msg or '继承失败'}"                 # 候选清单/宗师门槛/特性不存在 等


def _render_inherit_success(ctx: Mapping[str, Any], snap: Mapping[str, Any],
                            res: Mapping[str, Any]) -> str:
    """M-04 成功 → 面板特性位更新（`3 普通 + 第 4 位金色`），**纯文本降级**（emoji 纪律）：
    `已继承：灼烧强化 回复强化 ｜ 特性位 2 普通 + 第 4 位金色（灼烧强化·精） ｜ PP 3/5`。"""
    parts: list = []
    names = [_trait_name(ctx, t) for t in (res.get("traits") or [])]
    if names:
        parts.append("已继承：" + " ".join(names))
    negs = [_trait_name(ctx, n) for n in (res.get("negatives") or [])]
    if negs:
        parts.append("负面特性：" + " ".join(negs))
    normal_used = len(snap.get("traits") or [])
    gold = snap.get("gold_slot")
    slot_text = f"特性位 {normal_used} 普通"
    if isinstance(gold, str) and gold:
        slot_text += f" + 第 4 位金色（{_trait_name(ctx, gold)}）"
    parts.append(slot_text)
    pp = snap.get("pp") or {}
    parts.append(f"PP {pp.get('used', 0)}/{pp.get('budget', 0)}")
    return " ｜ ".join(parts)


async def _run_inherit(ctx: MutableMapping[str, Any], tokens: list,
                       *, super_trait: Optional[str] = None) -> str:
    """/继承 /继承超 共用执行（GU-13 会话中 → select_traits 全校验 → apply → suspend → M-04）。"""
    settings = _settings_of(ctx)
    prof_engine = ProficiencyEngine(settings=settings)
    engine = TraitInherit(prof=prof_engine, settings=settings)
    session_mgr = ctx.get("session_mgr")
    if session_mgr is None:
        raise RuntimeError(
            "alchemy_commands.cmd_inherit 需要 ctx['session_mgr']"
            "（SessionManager 或 async fake，批11 装配注入）"
        )
    qid = _qid_of(ctx)
    # GU-10 战斗拦截（MUT-04：先于会话查询，战斗会话占用槽位）
    if ctx.get("in_battle"):
        return "战斗中使用 /即时调合 <配方>（不进入调合会话）"
    # GU-13 会话中（无会话 / 非调合类会话 → 无会话模板，同 GU-09）
    view = await session_mgr.get_active(qid)
    if view is None or not is_alchemy_session(view):
        return TEMPLATE_MESSAGES[TEMPLATE_NO_SESSION]
    snap = _view_payload(view)
    player = _player_of(ctx)
    tier_index = prof_engine.tier_index_for_level(ALCHEMY_JOB_ID, _prof_level(player))
    # T-1 位上限与配方声明位取小（recipe.traits_inherit 1-3；engine.inherit_slots 等级+SP）
    recipe = _find_recipe(ctx, snap.get("recipe_id"))
    slot_cap: Optional[int] = None
    if recipe is not None:
        try:
            rcap = max(1, int(recipe.get("traits_inherit", 1) or 1))
        except (TypeError, ValueError):
            rcap = 1
        slot_cap = min(engine.inherit_slots(player, tier_index), rcap)
    # F-04 核心：候选清单 → PP → 位 → 互斥 → repeatable → 负面 → 超特性宗师
    res = engine.select_traits(player, snap, tokens, super_trait=super_trait,
                               job_tier_index=tier_index, ctx=ctx, slot_cap=slot_cap)
    if not res.get("ok"):
        return _inherit_error(res)
    new_snap = engine.apply_to_snapshot(
        snap, res["traits"], super_trait=res.get("gold_slot"),
        negatives=res.get("negatives") or [], pp_used=res.get("pp_used"),
    )
    await session_mgr.suspend(qid, new_snap)
    return _render_inherit_success(ctx, new_snap, res)


async def cmd_inherit(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`/继承 <特性1>,<特性2>,…`（P-04/SEP-04，F-04，批5 路5A）。

    守卫链 GU-13~16（会话中 / PP / 位余量 / group+repeatable）+ INH-01 候选清单 +
    INH-14 等级化位 + INH-12 负面 + TSC-11 超特性宗师——全部委托
    TraitInherit.select_traits；成功后 apply_to_snapshot → suspend 持久化 → M-04 渲染。
    入参：parsed（ParsedCommand）、ctx（session_mgr/items/traits/recipe/settings 等，
    session_mgr 为 async SessionManager 或 fake）。出参：回复正文 str。
    """
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if not parsed.args:
        return format_tpl12(f"/{INHERIT_CMD}")
    tokens = _inherit_tokens(parsed)
    if not tokens:
        return format_tpl12(f"/{INHERIT_CMD}")
    return await _run_inherit(ctx, tokens)


async def cmd_inherit_super(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`/继承超 <金色特性>`（独立指令名，非子词，P-04：位置参数 1 = 单一金色特性）。

    F-04/TSC-11~14：超特性继承需宗师、第 4 位独占 gold_slot_exclusive、PP2、金色素材池。
    委托 TraitInherit.select_traits(super_trait=...) → apply → suspend → M-04 渲染。
    入参：parsed、ctx。出参：回复正文 str。
    """
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if not parsed.args:
        return format_tpl12(f"/{INHERIT_SUPER_CMD}")
    tokens = _inherit_tokens(parsed)
    # 【防御 · 收口裁决 2026-08-29】parse_command 白名单未含「继承超」独立指令时（批11A
    #  装配项 IF-34），/继承超 X 会被解析成 command=继承 + args=["超","X"]——
    #  剥离误并入的「超」固定子词，保证独立指令语义（装配前后均可用）。
    if tokens and tokens[0] == "超":
        tokens = tokens[1:]
    if not tokens:
        return format_tpl12(f"/{INHERIT_SUPER_CMD}")
    if len(tokens) > 1:
        return "❌ /继承超 仅支持 1 个金色特性"  # P-04：位置参数 1 = 单一金色特性
    return await _run_inherit(ctx, [], super_trait=tokens[0])


# ---------------------------------------------------------------------------
# 会话终态指令壳（批6 路A：/确认 /放弃 /调合续 /分解）
# ---------------------------------------------------------------------------

def _is_suspended(view: Any) -> bool:
    """挂起(战斗) 判定（§7.1 行6/7）。

    【工程补白 S-1】挂起会话 payload 携带 `state="suspended"` 标记（批3 路3B 战斗打断
    `suspend` 写入会话行时记录；本壳只读判定，缺省无标记视为会话中非挂起）。
    入参：view（SessionView/dict，鸭子类型）。出参：True=挂起(战斗)。
    """
    payload = _view_payload(view)
    if isinstance(payload, Mapping):
        try:
            return str(payload.get("state") or "") == SUSPENDED
        except Exception:
            return False
    return False


def _placement_conflict_text(res: Mapping[str, Any]) -> str:
    """结算复核失败渲染（INH-10/11，TC-18/19）：防会话内绕校验。

    入参：res（TraitInherit.check_placement_conflict 输出 {ok, message, conflicts}）。
    出参：拒绝正文（透传 message 兜底）。
    """
    return str(res.get("message") or "❌ 结算校验：互斥组/repeatable 冲突")


def _confirm_error(res: Mapping[str, Any], ctx: Mapping[str, Any]) -> str:
    """/确认 失败透传（ATO-04 已结算 / GU-19 材料不足差异 / GU-17 无会话 / 其余原样）。

    入参：res（SettleEngine.confirm 输出）、ctx（材料名解析）。出参：拒绝正文 str。
    """
    reason = res.get("reason")
    msg = res.get("message")
    if reason == "already_settled":
        return str(msg or "已结算")                     # ATO-04/M-05 重复确认幂等
    if reason == "no_snapshot":
        return TEMPLATE_MESSAGES[TEMPLATE_NO_SESSION]   # GU-17
    if reason in ("materials_insufficient", "materials_shortfall"):
        diff = _shortfall_text(ctx, res.get("shortfall"))
        return f"材料不足：{diff}" if diff else "材料不足，无法确认"  # GU-19 全量复核差异
    return str(msg or "❌ 确认失败")


def _render_decompose(
    res: Mapping[str, Any], ctx: Mapping[str, Any], *, rate: Optional[float] = None
) -> str:
    """两段式消息渲染（M-10 / GEM-15：材料回收段 + 宝石段，纯文本无装饰 emoji）：

    `✅ 火晶石×2 月光草×1 + 宝石×3（回收 60%）`——宝石 = 平铺基础值不乘回收率（拍板①，
    普通1/精良3/史诗8/传说20，可配 gem.分解）。rate 为回收率小数（None → 不显示）。
    入参：res（gem_wallet.decompose 成功输出 {materials, gem, ...}）、ctx（物品名解析）、
      rate（decompose_rate，可选）。出参：成功正文 str。
    """
    parts: list = []
    for m in res.get("materials") or []:
        if not isinstance(m, Mapping):
            continue
        raw_id = m.get("item_id") or m.get("item") or m.get("id")
        name = m.get("name") or _item_name(ctx, raw_id) or "?"
        try:
            cnt = max(1, int(m.get("count", 1)))
        except (TypeError, ValueError):
            cnt = 1
        parts.append(f"{name}×{cnt}")
    body = "✅ " + " ".join(parts) if parts else "✅ 分解成功"
    gem = 0
    try:
        gem = max(0, int(res.get("gem", 0)))
    except (TypeError, ValueError):
        gem = 0
    if gem > 0:
        body += f" + 宝石×{gem}"
    if rate is not None:
        body += f"（回收 {int(round(rate * 100))}%）"
    return body


async def cmd_confirm(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`/确认`（P-05/SEP-05 无参数，独立指令名注册）：F-05 品质结算终态（批6 路6A）。

    守卫链：
      - GU-10/MUT-04 战斗拦截（先于会话查询，战斗会话占用槽位）；
      - GU-17 调合会话中（无会话/非调合类 → 「当前没有调合会话，先 /炼金 <配方> 开始」）；
      - GU-19 全量复核由 SettleEngine.confirm 承载（verify_snapshot：材料链+触媒在包，
        不足全拒+差异，防过期快照）。
    流程：取会话快照 →（INH-10/11 结算复核）TraitInherit.check_placement_conflict →
      SettleEngine.confirm(ctx, snap, qid, job_tier_index, message_id, session_view=view)
      → 透传 message（成功 M-05「确认成功：火焰弹（品质 72·史诗）」/ 已结算幂等 ATO-04）。
      终态幂等 gate 在引擎内（settle_alchemy command="settle:confirm"，§10 铁律 3；
      message_id 缺失时引擎不落幂等键，保守——批11 装配注入）。
    入参：parsed（ParsedCommand）、ctx（session_mgr/items/recipe/traits/settings +
      count_item/remove_item/add_item hook，SettleEngine 就地改写背包）。
    出参：回复正文 str。
    """
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    session_mgr = ctx.get("session_mgr")
    if session_mgr is None:
        raise RuntimeError(
            "alchemy_commands.cmd_confirm 需要 ctx['session_mgr']"
            "（SessionManager 或 async fake，批11 装配注入）"
        )
    qid = _qid_of(ctx) or ""  # 装配层注入恒非空；缺省空串保守（settle 幂等键要素缺失不落键）
    # GU-10/MUT-04 战斗拦截（先于会话查询，战斗会话占用槽位）
    if ctx.get("in_battle"):
        return "战斗中使用 /即时调合 <配方>（不进入调合会话）"
    # GU-17 会话中（无会话 / 非调合类会话 → 无会话模板）
    view = await session_mgr.get_active(qid)
    if view is None or not is_alchemy_session(view):
        return TEMPLATE_MESSAGES[TEMPLATE_NO_SESSION]
    snap = _view_payload(view)
    settings = _settings_of(ctx)
    prof_engine = ProficiencyEngine(settings=settings)
    player = _player_of(ctx)
    tier_index = prof_engine.tier_index_for_level(ALCHEMY_JOB_ID, _prof_level(player))
    # INH-10/11 结算复核（TraitInherit.check_placement_conflict：group/repeatable，
    # 防会话内绕校验；traits 聚合在复核内部完成）
    trait_engine = TraitInherit(prof=prof_engine, settings=settings)
    placement = trait_engine.check_placement_conflict(snap, [], ctx)
    if not placement.get("ok"):
        return _placement_conflict_text(placement)
    engine = SettleEngine(prof=prof_engine, settings=settings)
    res = await engine.confirm(
        ctx, snap, qid=qid, job_tier_index=tier_index,
        message_id=ctx.get("message_id") or None, session_view=view,
    )
    if not res.get("ok"):
        return _confirm_error(res, ctx)
    return str(res.get("message") or "❌ 确认失败")


async def cmd_abandon(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`/放弃`（P-05/SEP-05 无参数）：F-05 会话退出终态（批6 路6A）。

    守卫 GU-17 调合会话中（无会话/非调合类 → 无会话模板）+ GU-10/MUT-04 战斗拦截。
    流程：SettleEngine.abandon(ctx, snap, qid, message_id, session_view=view)——材料
      不结算（F-05：不扣料不产入），终态结算 settle_alchemy command="settle:abandon"
      （§10 铁律 3；message_id 缺失时引擎不落幂等键，保守）。
    入参：parsed、ctx（session_mgr + remove_item/add_item hook 语义兼容）。
    出参：回复正文 str（成功「已放弃」；重复放弃「已放弃」幂等透传）。
    """
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    session_mgr = ctx.get("session_mgr")
    if session_mgr is None:
        raise RuntimeError(
            "alchemy_commands.cmd_abandon 需要 ctx['session_mgr']"
            "（SessionManager 或 async fake，批11 装配注入）"
        )
    qid = _qid_of(ctx) or ""  # 装配层注入恒非空；缺省空串保守（settle 幂等键要素缺失不落键）
    if ctx.get("in_battle"):
        return "战斗中使用 /即时调合 <配方>（不进入调合会话）"
    view = await session_mgr.get_active(qid)
    if view is None or not is_alchemy_session(view):
        return TEMPLATE_MESSAGES[TEMPLATE_NO_SESSION]
    snap = _view_payload(view)
    settings = _settings_of(ctx)
    prof_engine = ProficiencyEngine(settings=settings)
    engine = SettleEngine(prof=prof_engine, settings=settings)
    res = await engine.abandon(
        ctx, snap, qid=qid,
        message_id=ctx.get("message_id") or None, session_view=view,
    )
    return str(res.get("message") or "❌ 放弃失败")


async def cmd_resume(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`/调合续`（P-05/SEP-05 无参数）：挂起(战斗) 会话恢复（批6 路6A，GU-18）。

    守卫（§7.1 行7/8 + MUT-05）：
      - 无挂起（无会话）→ 「当前没有调合会话，先 /炼金 <配方> 开始」；
      - 已有活跃会话（非调合类占用槽位 或 未挂起的调合会话）→
        「已有一个调合会话进行中」（定稿 L177）；
      - 挂起(战斗) 调合会话 → 恢复渲染面板（行7：特性选择与 PP 状态不丢，快照原样渲染）。
    入参：parsed、ctx（session_mgr/items/recipe/settings）。出参：回复正文 str。
    """
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    session_mgr = ctx.get("session_mgr")
    if session_mgr is None:
        raise RuntimeError(
            "alchemy_commands.cmd_resume 需要 ctx['session_mgr']"
            "（SessionManager 或 async fake，批11 装配注入）"
        )
    qid = _qid_of(ctx)
    view = await session_mgr.get_active(qid)
    if view is None:
        return TEMPLATE_MESSAGES[TEMPLATE_NO_SESSION]            # 无挂起（行2）
    if not is_alchemy_session(view) or not _is_suspended(view):
        return TEMPLATE_MESSAGES[TEMPLATE_ALREADY_ACTIVE_ALCHEMY]  # 已有活跃（行8/L177）
    snap = _view_payload(view)
    if not snap:
        return TEMPLATE_MESSAGES[TEMPLATE_NO_SESSION]
    settings = _settings_of(ctx)
    prof_engine = ProficiencyEngine(settings=settings)
    player = _player_of(ctx)
    tier_index = prof_engine.tier_index_for_level(ALCHEMY_JOB_ID, _prof_level(player))
    core = AlchemyCore(prof=prof_engine, settings=settings)
    return _render_panel(core, snap, ctx, tier_index)


def _star_qty(parsed: Any) -> Optional[int]:
    """壳层防御 `*N` 数量解析（P-10 单件分解 + 任务书扩展 `/分解 <物品>*<数量>`）。

    parsers 未把 分解 登记进 quantity_commands（DEFAULT_QUANTITY_COMMANDS，批11 装配补），
    故 parsed.qty 恒 None——此处按 _target_of 同口径剥离 `*N` 兜底解析（对齐 P-03/SEP-03
    数量语义：`*` 数量，缺失/非法 → None）。
    入参：parsed（ParsedCommand）。出参：N≥1 或 None。
    """
    if not getattr(parsed, "args", None):
        return None
    raw = str(parsed.args[0])
    if "*" not in raw:
        return None
    _, _, cnt = raw.partition("*")
    try:
        n = int(cnt)
    except (TypeError, ValueError):
        return None
    return max(1, n)


async def cmd_decompose(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """`/分解 <道具>*<数量>`（P-10/SEP-10，GU-32/33，批6 路6A）。

    守卫：
      - GU-33 道具在注册表且为分解对象（道具名不存在 → 「❌ 道具不存在：xxx」）；
      - GU-32 仅炼金/深度产出可分解、标准版默认不可分解或回收减半（GEM-13/14）——
        由兄弟路 B gem_wallet.decompose 承载（本壳鸭子类型消费 ctx["wallet"]，勿 import
        勿探查；接口契约见批6 任务书：decompose/decompose_rate/gem_base_value/grant_gem）。
    流程：钱包 decompose 原子扣道具 + 返材料（×回收率向下取整）+ 宝石入账（平铺基础值
      不乘回收率，拍板①）→ 两段式消息渲染（M-10）。
    入参：parsed、ctx（items/recipe/settings + wallet 注入点，批6B 装配）。
    出参：回复正文 str。
    """
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    if not parsed.args:
        return format_tpl12(f"/{DECOMPOSE_CMD}")
    target = _target_of(parsed)
    qty = parsed.qty if parsed.qty is not None else _star_qty(parsed)
    qty = max(1, qty if qty is not None else 1)
    item_def = _find_item(ctx, target)
    if item_def is None:
        return f"❌ 道具不存在：{target}"                        # GU-33 分解对象缺失
    wallet = ctx.get("wallet")
    if wallet is None:
        raise RuntimeError(
            "alchemy_commands.cmd_decompose 需要 ctx['wallet']"
            "（宝石货币引擎 GemWallet 或 fake，实现 decompose/decompose_rate 接口契约）"
        )
    settings = _settings_of(ctx)
    prof_engine = ProficiencyEngine(settings=settings)
    player = _player_of(ctx)
    tier_index = prof_engine.tier_index_for_level(ALCHEMY_JOB_ID, _prof_level(player))
    res = wallet.decompose(ctx, item_def, count=qty, job_tier_index=tier_index)
    if inspect.isawaitable(res):  # 鸭子类型：兄弟路引擎 async 防御（同步引擎亦兼容）
        res = await res
    if not res.get("ok"):
        return str(res.get("message") or "❌ 分解失败")          # GU-32 标准版拒/回收减半透传
    rate: Optional[float] = None
    raw_rate: Any = res.get("rate")
    if raw_rate is not None:
        try:
            rate = float(raw_rate)
        except (TypeError, ValueError):
            rate = None
    if rate is None:
        dr = getattr(wallet, "decompose_rate", None)
        if callable(dr):
            try:
                rate = float(dr(tier_index))                    # 兜底读回收率（可配档位）
            except Exception:
                rate = None
    return _render_decompose(res, ctx, rate=rate)


# ---------------------------------------------------------------------------
# 装配（Router 注册；make_context 由装配层注入，批11 路11A 待接线）
# ---------------------------------------------------------------------------

def register_alchemy_commands(
    router: Any,
    *,
    make_context: Optional[Callable[[Any], dict]] = None,
) -> Any:
    """把 `/合成` `/炼金` `/投料` `/继承` `/继承超` `/确认` `/放弃` `/调合续` `/分解`
    注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    handler 支持 k.get("ctx") 注入（装配层 _invoke_handler 以 ctx=ctx 注入，assembly/runner.py
    L281-302）；全部炼金指令（含本批 4 条终态指令）为 async 处理器，runner 对 isawaitable
    结果自动 await。

    :param make_context: ParsedCommand → 玩家 ctx dict（含 player/session_mgr/items/recipe/
        settings/currencies/proficiency 等，见 core/alchemy_core.py 工程补白）。None 时 handler
        调用抛 RuntimeError（【待接线】批11 路11A 装配入口注入）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】alchemy_commands.register_alchemy_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _synth(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_synthesis(parsed, injected)
        return cmd_synthesis(parsed, _ctx(parsed))

    def _alchemy(parsed: Any, *a: Any, **k: Any):
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_alchemy(parsed, injected)
        return cmd_alchemy(parsed, _ctx(parsed))

    def _feed(parsed: Any, *a: Any, **k: Any):
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_feed(parsed, injected)
        return cmd_feed(parsed, _ctx(parsed))

    def _inherit(parsed: Any, *a: Any, **k: Any):
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_inherit(parsed, injected)
        return cmd_inherit(parsed, _ctx(parsed))

    def _inherit_super(parsed: Any, *a: Any, **k: Any):
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_inherit_super(parsed, injected)
        return cmd_inherit_super(parsed, _ctx(parsed))

    def _confirm(parsed: Any, *a: Any, **k: Any):
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_confirm(parsed, injected)
        return cmd_confirm(parsed, _ctx(parsed))

    def _abandon(parsed: Any, *a: Any, **k: Any):
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_abandon(parsed, injected)
        return cmd_abandon(parsed, _ctx(parsed))

    def _resume(parsed: Any, *a: Any, **k: Any):
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_resume(parsed, injected)
        return cmd_resume(parsed, _ctx(parsed))

    def _decompose(parsed: Any, *a: Any, **k: Any):
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_decompose(parsed, injected)
        return cmd_decompose(parsed, _ctx(parsed))

    router.register(CommandSpec(SYNTH_CMD, handler=_synth))
    router.register(CommandSpec(ALCHEMY_CMD, handler=_alchemy))
    router.register(CommandSpec(FEED_CMD, handler=_feed))
    router.register(CommandSpec(INHERIT_CMD, handler=_inherit))
    router.register(CommandSpec(INHERIT_SUPER_CMD, handler=_inherit_super))
    router.register(CommandSpec(CONFIRM_CMD, handler=_confirm))
    router.register(CommandSpec(ABANDON_CMD, handler=_abandon))
    router.register(CommandSpec(RESUME_CMD, handler=_resume))
    router.register(CommandSpec(DECOMPOSE_CMD, handler=_decompose))
    return router
