"""M9 锻造·批4·路4A+路4B：/锻造 原子流程 + 直锻/预览双流 + /确认 一次性窗口。

文件名：qbot_rpg/commands/forge_commands.py
创建时间：2026-08-30
作者：Hermes 子agent-4B（M9 锻造实现组批4·路4B：直锻/预览双流 + /确认 一次性窗口）

【批内协作状态】路4A（原子流程引擎：守卫 GU-01~06 + 成功/失败模板）与路4B 同批并行。
本工作区收口时 forge_commands.py 尚未落盘（批4 拆 4A+4B 子批并行，4A 未先提交），
为保证交付可运行且自测可过，本文件一次性承载路4A 原子流程（_forge_atomic）+ 路4B
双流/确认窗——文件名/入口签名（register_forge_commands + cmd_forge + cmd_confirm）
对齐任务派工单，主 agent 收口时若路4A 另行落盘可按契约合并。

功能描述（路4B 主体）：
  ① 双流路由：cmd_forge 入口先判 settings.forge.straight_forge（缺省 true）——
     - true（直锻）：无「预览」参数 → 原子流程直接成功（小白 1 步，TC-09）；
     - 显式「预览」参数 → 预览流 2 步（TC-10）；
     - false（深度模式）：全部 /锻造 强制预览（前台无直锻入口，TC-13）；
     - 双流并存：直锻开时仍可显式带「预览」切深度流（预览参数不依赖开关，2c2b §3.1）。
  ② 预览卡片（2c2b §3.2 / TC-10）：`<节点名>（<属性摘要>）` 标题 + 素材行
     （前置节点名 + 各行素材 + 需求档位级）+ 孔位/后续行（slots + 主线 child → ■终结）；
     **预览不扣任何资源**（0 副作用）。
  ③ 确认窗（2c2b §3.3 / TC-11~14）：
     - 预览发出后登记一次性待确认上下文（单键：qid → {node_id, ts} 字段快照），
       ctx 内存窗（ctx["forge_preview"] = {qid: {node_id, ts}}）；
     - /确认 cmd_confirm：重跑 GU-03~06 守卫再扣素材发经验（复用 _forge_atomic 原子执行）
       → `✅ <节点> 锻造完成！`（TC-12）；未确认/超时（carry_sec 缺省 90，0=不限）
       → 上下文作废，无锻造无扣款无经验（TC-11）；
     - 同一玩家同时仅 1 个待确认窗；新 /锻造 或 /图纸 不覆盖既有窗（保持可感知）；
     - **边界**：超短期一次性引导，非框架 3.18 会话（不持久化、不可跨指令续接）；
     - 无进行中预览时 /确认 → 拒绝「当前无可确认的锻造预览」（TC-14）。
  ④ register_forge_commands 追加 /确认 CommandSpec（白名单标记）。
  ⑤ 路4A 原子流程（_forge_atomic）：守卫 GU-01~06 顺序链（系统注册/参数/节点存在可锻/
     前置已锻/素材足够/等级足够）+ 成功路径（扣素材/扣金币/实例化入包/发经验原子写）+
     失败零副作用（2c2b §1.1~1.3）。

依据（文件头标注）：
  - docs/细化/细化_2c2b_锻造流程契约.md §三（3.1 双流开关语义 / 3.2 预览卡片 / 3.3 确认窗
    与会话边界 / 3.4 双流差异对照）+ §1.1（守卫 GU-01~06）/ §1.2（成功路径）/ §1.3（失败模板）
    + §六 C（验收 TC-09~14）。
  - 定稿（锻造系统设计定稿 v1.0.1）§3.1 L74-79（直锻）/ §3.3 L89-97（预览+/确认）/
    §2.1 #7 L57（双流）/ settings straight_forge L355 / 零会话 L239（不使用框架 3.18）。
  - docs/m9_shared_contract.md §三（S-03 straight_forge 缺省 true）/ §二（ForgeNode 字段）。

【工程补白 · 显式标注】（契约/细化未显式定义处的实现口径，标 F-x）：
  F-1  预览卡片渲染：2c2b §3.2 卡片示意含 📖 图标（定稿 L92），本仓 emoji 纪律
       （用户拍板「不用 emoji」，tests/unit/test_emoji_discipline.py 全仓扫描）只允许
       ✅/❌ + 排版符号 → 卡片标题降级纯文本 `<节点名>（<属性摘要>）`（对齐 M5 裁决
       「数据型功能图标一律降级纯文本」；alchemy_commands 同口径弃用 📖）。
  F-2  ctx 契约（对齐 synthesis.py / alchemy_commands）：ctx 为 MutableMapping，含
       ctx["forge"]（forge.json 顶层 raw，含 trees/settings）/ ctx["items"]（items 表，
       Mapping 或 list）/ ctx["player"]（玩家状态 MutableMapping，就地改写
       proficiency/currencies/inventory）/ ctx["inventory"]（背包计数 in-memory 兜底）/
       ctx["count_item"]/ctx["remove_item"]/ctx["add_item"] hooks / ctx["settings"]
       （完整 settings dict 含 forge 段）/ ctx["qid"]（玩家 id，确认窗单键）。
       ctx["now"]：确认窗超时判定时钟（装配层注入；缺省 time.time 兜底，对齐
       alchemy_commands 种植/收获 now 兜底口径；零定时器/零睡眠，仅读时钟）。
  F-3  确认窗内存窗形态：ctx["forge_preview"] = {qid: {"node_id": str, "ts": float}}，
       装配层/测试注入共享 ctx 即共享窗；不持久化（非 3.18 会话，定稿 L239）。
       carry_sec 读 settings.forge.carry_sec（缺省 90，0=不限；非 FORGE_SETTINGS_KEYS
       标准键，本壳层读段兜底）。
  F-4  需求档位名：素材行「需求：铸造 <档位> 级」——<档位> = ProficiencyEngine
       tier_name(FORGE_JOB_ID, node.level)（与 forge_job.rank_name 同源；level 越界钳末档）。
  F-5  品质中文映射：normal→普通 / fine→精良 / epic→史诗 / legendary→传说（对齐
       formula_engine 品质类字符串映射 + 定稿 L78「品质：X（固定）」）。
  F-6  属性摘要：stats.element 存在 → `<元素中文>属性+<element_value>`（元素中文用
       alchemy_core.ELEMENT_NAMES_CN 同表）；无 element → 用 stats 首项 `atk`/`def`
       摘要（`攻击+<atk>`）；均无 → 空摘要。
  F-7  孔位渲染：slots 非空 → `孔位：<Lv> 级槽 ×<n> | ...`（同 level 合并计数）；
       空 → 略去孔位段。后续段：主线 child（非 branch 的 children 首项）→
       line_endpoint（■终结名）；无主线 child → 略去。
  F-8  确认窗超时边界：carry_sec=0 表示不限（永不因超时作废，仅 /确认 时重跑守卫）。
       超时判定在 cmd_confirm 内用 ctx now 比较（now - ts > carry_sec），不 sleep。

铁律：零 NoneBot import（3a R1）；纯函数确定性（同刻同参必同值）；不写定时器/睡眠调用
      （确认窗超时用 ctx now 比较，不 sleep）；渲染输出无 emoji（仅 ✅/❌ + 排版符号
      | → × / 【】 ■）；确认窗不持久化（非 3.18 会话）；每功能可追溯（文件头标注依据）。
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional

from qbot_rpg.core.alchemy_core import ELEMENT_NAMES_CN
from qbot_rpg.core.codex import mark_seen
from qbot_rpg.core.forge_cascade import is_redflagged
from qbot_rpg.core.forge_job import (
    _tier_name,
    exp_to_next,
    gain_forge_exp,
    level_gate_met,
)
from qbot_rpg.core.forge_progress import material_holdings, shortfall
from qbot_rpg.core.forge_tree import ForgeTreeEngine

# 同包兄弟模块：相对导入（G0 架构门禁，与 alchemy_commands/shop_commands 同口径）
from .router import CommandSpec
from .sender import format_tpl12

__all__ = [
    # 指令名常量
    "FORGE_CMD",
    "CONFIRM_CMD",
    "PREVIEW_SUBWORD",
    # 窗口常量
    "DEFAULT_CARRY_SEC",
    "PREVIEW_WINDOW_KEY",
    # 指令处理器（纯函数：parsed + ctx → 回复正文）
    "cmd_forge",
    "cmd_confirm",
    # 原子流程（路4A 承载；确认窗复用）
    "forge_atomic",
    # 装配
    "register_forge_commands",
]

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 指令名（白名单已含：DEFAULT_WHITELIST「锻造」「确认」；「预览」为 FIXED_SUBWORDS）
FORGE_CMD: str = "锻造"
CONFIRM_CMD: str = "确认"
# 预览子词（2c2b §3.1：`/锻造 <节点> 预览`；parsers FIXED_SUBWORDS 已含「预览」）
PREVIEW_SUBWORD: str = "预览"

# 确认窗超时缺省（2c2b §3.3：carry_sec 缺省 90s，0=不限）
DEFAULT_CARRY_SEC: int = 90
# 确认窗内存窗键（ctx["forge_preview"] = {qid: {"node_id", "ts"}}；F-3）
PREVIEW_WINDOW_KEY: str = "forge_preview"

# 品质四档中文（F-5：normal→普通 / fine→精良 / epic→史诗 / legendary→传说）
_RARITY_CN: Mapping[str, str] = {
    "normal": "普通",
    "fine": "精良",
    "epic": "史诗",
    "legendary": "传说",
}
# 部位中文（对齐 basic_commands._SLOT_NAME 口径：weapon→武器）
_SLOT_CN: Mapping[str, str] = {"weapon": "武器"}


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


def _player_of(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """玩家状态 dict（ctx["player"] 优先；缺省 ctx 自身——测试可把 ctx 直接当 player）。"""
    player = ctx.get("player")
    if isinstance(player, MutableMapping):
        return player
    return ctx


def _qid_of(ctx: Mapping[str, Any]) -> Optional[str]:
    """玩家 id（确认窗单键；ctx["qid"] → ctx["player"] 内 qid/qq/player_qid）。"""
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


def _forge_raw(ctx: Mapping[str, Any]) -> Mapping[str, object]:
    """forge.json 顶层 raw dict（ctx["forge"]；非 Mapping → {}，GU-01 系统未启用兜底）。"""
    forge = ctx.get("forge")
    return forge if isinstance(forge, Mapping) else {}


def _settings_of(ctx: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    """完整 settings dict（ctx["settings"]；非 Mapping → None，引擎缺省兜底）。"""
    s = ctx.get("settings")
    return s if isinstance(s, Mapping) else None


def _engine(ctx: Mapping[str, Any]) -> ForgeTreeEngine:
    """ForgeTreeEngine（构造器注入 forge raw + items + settings；缺省兜底）。"""
    return ForgeTreeEngine(
        forge=_forge_raw(ctx),
        items=ctx.get("items"),
        settings=_settings_of(ctx),
    )


def _straight_forge(ctx: Mapping[str, Any]) -> bool:
    """straight_forge 开关（S-03 缺省 true；归一取 settings.forge 段）。"""
    seg = _forge_settings(ctx)
    v = seg.get("straight_forge")
    return v if isinstance(v, bool) else True


def _forge_settings(ctx: Mapping[str, Any]) -> Mapping[str, object]:
    """settings.forge 段（完整 settings dict 取段；forge 段本身直接消费；无 → {}）。"""
    settings = _settings_of(ctx)
    if settings is None:
        return {}
    seg = settings.get("forge")
    return seg if isinstance(seg, Mapping) else {}


def _carry_sec(ctx: Mapping[str, Any]) -> int:
    """确认窗超时秒数（settings.forge.carry_sec 缺省 90，0=不限；F-3）。"""
    v = _forge_settings(ctx).get("carry_sec")
    if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
        return v
    return DEFAULT_CARRY_SEC


def _now(ctx: Mapping[str, Any]) -> float:
    """当前时钟（ctx["now"] 注入优先；缺省 time.time 兜底，仅读时钟零睡眠，F-2）。"""
    v = ctx.get("now")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return time.time()


def _count_item(ctx: Mapping[str, Any], item_id: str) -> int:
    """持有计数（对齐 synthesis._count_item：hook 优先；inventory 兜底）。"""
    hook = ctx.get("count_item")
    if callable(hook):
        try:
            v: Any = hook(item_id)
            return int(v)
        except Exception:
            return 0
    inv = ctx.get("inventory")
    if isinstance(inv, Mapping):
        return int(inv.get(item_id, 0))
    return 0


def _remove_item(ctx: MutableMapping[str, Any], item_id: str, count: int) -> bool:
    """扣减（不部分扣减，对齐 synthesis._remove_item：hook 优先；inventory 兜底）。"""
    hook = ctx.get("remove_item")
    if callable(hook):
        try:
            return bool(hook(item_id, count))
        except Exception:
            return False
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        have = int(inv.get(item_id, 0))
        if have < count:
            return False
        inv[item_id] = have - count
        return True
    return False


def _add_item(ctx: MutableMapping[str, Any], item_id: str, count: int, bound: bool) -> bool:
    """入包（对齐 synthesis._add_item：hook 优先；inventory 兜底）。"""
    hook = ctx.get("add_item")
    if callable(hook):
        try:
            return bool(hook(item_id, count, bound))
        except Exception:
            return False
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        inv[item_id] = int(inv.get(item_id, 0)) + count
        return True
    return False


def _item_name(ctx: Mapping[str, Any], item_id: str) -> str:
    """物品 id → 显示名（items 表 name；缺省回退原 id，对齐 forge_progress._item_name）。"""
    items = ctx.get("items")
    if isinstance(items, Mapping):
        hit = items.get(item_id)
        if isinstance(hit, Mapping):
            name = hit.get("name")
            if isinstance(name, str) and name:
                return name
    elif isinstance(items, (list, tuple)):
        for e in items:
            if isinstance(e, Mapping) and e.get("id") == item_id:
                name = e.get("name")
                if isinstance(name, str) and name:
                    return name
    return item_id


def _material_text(ctx: Mapping[str, Any], node: Any) -> str:
    """素材段文本：`<前置节点名> + <素材名>×<count> + ...`（2c2b §3.2 素材行）。"""
    raw = node.raw if hasattr(node, "raw") else node
    parent_id = raw.get("parent") if isinstance(raw, Mapping) else None
    parts: List[str] = []
    if isinstance(parent_id, str) and parent_id:
        eng = _engine(ctx)
        pnode = eng.node(parent_id)
        if pnode is not None:
            parts.append(pnode.name or parent_id)
    holdings = material_holdings(ctx, node)
    for _iid, h in holdings.items():
        parts.append(f"{h.get('name', _iid)}×{h.get('need', 0)}")
    return " + ".join(parts)


def _req_text(ctx: Mapping[str, Any], node_level: object) -> str:
    """需求档位文本：`需求：铸造 <档位> 级`（F-4：档位名 = forge_job._tier_name(node.level)，
    与 rank_name 同源；level 越界钳末档）。"""
    lv = node_level if isinstance(node_level, int) and not isinstance(node_level, bool) else 1
    return f"需求：铸造 {_tier_name(lv)} 级"


def _element_summary(stats: Mapping[str, object]) -> str:
    """属性摘要（F-6）：element → `<元素中文>属性+<element_value>`；无 element → `攻击+N`。"""
    elem = stats.get("element")
    if isinstance(elem, str) and elem:
        ev = stats.get("element_value")
        val = f"+{ev}" if isinstance(ev, (int, float)) and not isinstance(ev, bool) else ""
        cn = ELEMENT_NAMES_CN.get(elem, elem)
        return f"{cn}属性{val}"
    atk = stats.get("atk")
    if isinstance(atk, (int, float)) and not isinstance(atk, bool):
        return f"攻击+{atk}"
    return ""


def _slots_text(slots: object) -> Optional[str]:
    """孔位段（F-7）：`孔位：<Lv> 级槽 ×<n> | ...`；空 slots → None。"""
    if not isinstance(slots, (list, tuple)):
        return None
    counts: Dict[int, int] = {}
    for s in slots:
        if isinstance(s, Mapping):
            lv = s.get("level")
            if isinstance(lv, int) and not isinstance(lv, bool) and lv >= 1:
                counts[lv] = counts.get(lv, 0) + 1
    if not counts:
        return None
    seg = " | ".join(f"{lv} 级槽 ×{counts[lv]}" for lv in sorted(counts))
    return f"孔位：{seg}"


def _continue_text(ctx: Mapping[str, Any], node_id: str) -> Optional[str]:
    """后续段（F-7）：主线 child → ■终结名；无主线 child → None。"""
    eng = _engine(ctx)
    node = eng.node(node_id)
    if node is None:
        return None
    children = eng.children_of(node_id)
    branch = set(eng.branch_of(node_id))
    main = [c for c in children if c not in branch]
    if not main:
        return None
    child = eng.node(main[0])
    child_name = child.name if child is not None else main[0]
    endpoint = eng.line_endpoint(node_id)
    ep_name = ""
    if endpoint:
        ep = eng.node(endpoint)
        ep_name = ep.name if ep is not None else endpoint
    return f"可继续锻造：{child_name} → {ep_name}" if ep_name else f"可继续锻造：{child_name}"


# ---------------------------------------------------------------------------
# 路4A 原子流程（守卫 GU-01~06 + 成功/失败模板；确认窗复用）
# ---------------------------------------------------------------------------

def forge_atomic(ctx: MutableMapping[str, Any], key: object, *, preview: bool = False) -> str:
    """/锻造 原子流程（路4A 承载；路4B 直锻/预览/确认 复用同一执行路径）。

    入参：
      - ctx：玩家表示（MutableMapping；forge/items/settings/inventory/player + hooks）。
      - key：节点名/id（2c2b §5.2 匹配：精确→唯一前缀→歧义列表）。
      - preview：True = 预览流（渲染卡片 + 登记确认窗，不扣任何资源，TC-10/11）；
                 False = 执行流（守卫全过即原子扣素材/扣金币/产装/发经验，TC-09/12）。
    出参：回复正文 str。

    守卫链（2c2b §1.1 GU-01~06，顺序固定）：
      GU-01 指令存在（forge.json 有效注册）；GU-02 参数可解析（名禁空格）；
      GU-03 节点存在 & 可锻（红名失效拒绝）；GU-04 前置已锻；GU-05 素材足够；
      GU-06 等级足够。
    失败零副作用（§1.3：不扣素材/不扣金币/不加经验/不建确认窗）。预览登记确认窗后
    仍不扣资源（3.3：预览 0 副作用）。
    """
    # GU-01 指令存在（forge.json trees 有效注册，2c2b §1.1）
    eng = _engine(ctx)
    if not eng.load_trees():
        return "❌ 锻造系统未启用（内容包 forge.json 未注册）"

    # GU-02 参数可解析（P-01：节点名禁空格；含空格 → 参数错误，不匹配任何节点）
    if not isinstance(key, str) or not key.strip():
        return format_tpl12(_fragment_fallback(key))
    if any(ch.isspace() for ch in key):
        return "参数错误：节点名不含空格"

    # GU-03 节点存在 & 可锻（resolve：精确→唯一前缀→歧义列表，2c2b §5.2）
    res = eng.resolve_node(key)
    if not res.get("ok"):
        match = res.get("match")
        if match == "ambiguous":
            cands = res.get("candidates") or []
            lines = []
            for nid in cands:
                nd = eng.node(nid)
                nm = nd.name if nd is not None else nid
                lv = nd.level if nd is not None else 0
                lines.append(f"{nm}（Lv{lv}）")
            return "候选多个节点：" + " | ".join(lines) + " → /锻造树 查看可锻装备"
        return f"未找到「{key}」→ /锻造树 查看可锻装备"
    node = res.get("node")
    node_id = res.get("node_id")
    if node is None or not isinstance(node_id, str):
        return f"未找到「{key}」→ /锻造树 查看可锻装备"
    player = _player_of(ctx)

    # GU-03b 红名失效节点拒绝（级联删除①，2c2a §五 V15 / 定稿 L296「已失效：物品已删除」）
    if is_redflagged(node):
        return "❌ 已失效：物品已删除"

    # GU-04 前置已锻（沿 parent 链；缺 → 报缺前置 + /图纸 指引，§1.3）
    if not eng.parent_forged(player, node_id):
        chain = eng.path_to_root(node_id)
        first_unforged = ""
        for nid in chain:
            if nid == node_id:
                break
            if not eng.already_forged(player, nid):
                nd = eng.node(nid)
                first_unforged = nd.name if nd is not None else nid
                break
        hint = f"需先锻造：{first_unforged}" if first_unforged else "需先锻造：前置节点"
        return f"❌ {hint} → /图纸 查看全链"

    # GU-05 素材足够（material_holdings + shortfall，§1.3 缺件模板 + 来源提示）
    holdings = material_holdings(ctx, node)
    short = shortfall(holdings)
    if short.get("items"):
        need = _material_text(ctx, node)
        deficits = []
        for (name, deficit, src) in short["items"]:
            base = f"{name}×{deficit}"
            deficits.append(base if not src else f"{base}（来源：{src}）")
        return (
            f"❌ 素材不足：需要 {need}；缺：{'、'.join(deficits)}"
            f" → /图纸 查看全链"
        )

    # GU-06 等级足够（可锻节点上限=职业等级，§1.3 L240 模板：熟练缺口 = exp_to_next）
    node_level = node.level
    gate = level_gate_met(player, node_level)
    if not gate.get("ok"):
        need_rank = _tier_name(int(gate.get("need", 0)))
        cur_rank = _tier_name(int(gate.get("current", 0)))
        # 还差 N 熟练：熟练缺口来自 §4.1 计价（exp_to_next 缺口，非等级差）
        missing = int(exp_to_next(player).get("missing", 0))
        return f"需要 {need_rank} 级，当前 {cur_rank}（还差 {missing} 熟练）"

    # ---- 守卫全过 ----
    if preview:
        # 预览流：渲染卡片 + 登记一次性待确认窗（不覆盖既有窗，3.3）；0 资源副作用
        window = _register_preview(ctx, node_id)
        card = _render_preview(ctx, node)
        if not window:
            return "已有待确认的锻造预览，请先 /确认 或等待超时\n" + card
        return card

    # 执行流（直锻 / 确认复用）：成功路径 §1.2 原子写（扣素材/扣金币/产装/发经验）
    return _execute(ctx, player, node, node_id)


def _fragment_fallback(key: object) -> str:
    """无参数时 TPL-12 片段兜底（/锻造 空参）。"""
    return f"/{FORGE_CMD} {key}" if key not in (None, "") else f"/{FORGE_CMD}"


def _render_preview(ctx: Mapping[str, Any], node: Any) -> str:
    """预览卡片（2c2b §3.2 / TC-10；F-1 无 emoji 纯文本）。

    三行：`<节点名>（<属性摘要>）` / `素材：<前置 + 素材行> | <需求档位级>` /
    `孔位：<slots> | 可继续锻造：<主线 child → ■终结>`（孔位/后续为空段略去）。
    """
    name = node.name if hasattr(node, "name") and node.name else (node.get("name") or "")
    stats = node.stats if hasattr(node, "stats") else (node.get("stats") or {})
    title = f"{name}（{_element_summary(stats)}）" if _element_summary(stats) else name
    lines: List[str] = [title]

    mats = _material_text(ctx, node)
    req = _req_text(ctx, node.level if hasattr(node, "level") else node.get("level"))
    lines.append(f"素材：{mats} | {req}")

    tail: List[str] = []
    slots = node.slots if hasattr(node, "slots") else (node.get("slots") or [])
    slots_seg = _slots_text(slots)
    if slots_seg:
        tail.append(slots_seg)
    node_id = node.id if hasattr(node, "id") else node.get("id")
    cont = _continue_text(ctx, node_id) if node_id else None
    if cont:
        tail.append(cont)
    if tail:
        lines.append(" | ".join(tail))
    return "\n".join(lines)


def _register_preview(ctx: MutableMapping[str, Any], node_id: str) -> bool:
    """登记一次性待确认窗（3.3：同一玩家仅 1 窗；新预览不覆盖既有窗）。

    入参：ctx（MutableMapping；窗落 ctx[PREVIEW_WINDOW_KEY][qid]）、node_id。
    出参：True=登记成功；False=已有待确认窗（不覆盖，保持可感知）。
    qid 缺失（无 ctx qid / player qid）→ 不登记（返回 True：预览仍可出卡片，
    但 /确认 无窗可确认——装配层应恒注入 qid）。
    """
    qid = _qid_of(ctx)
    if qid is None:
        return True
    window = ctx.get(PREVIEW_WINDOW_KEY)
    if not isinstance(window, MutableMapping):
        window = {}
        ctx[PREVIEW_WINDOW_KEY] = window
    existing = window.get(qid)
    if isinstance(existing, Mapping) and not _window_expired(ctx, existing):
        return False  # 不覆盖既有窗
    window[qid] = {"node_id": node_id, "ts": _now(ctx)}
    return True


def _window_expired(ctx: Mapping[str, Any], window: Mapping[str, object]) -> bool:
    """确认窗是否超时（carry_sec=0 不限；now - ts > carry_sec 判定，零 sleep，F-8）。"""
    carry = _carry_sec(ctx)
    if carry == 0:
        return False
    ts = window.get("ts")
    if not isinstance(ts, (int, float)):
        return True  # 无时间戳 → 视为过期（保守作废）
    return (_now(ctx) - float(ts)) > carry


def _execute(
    ctx: MutableMapping[str, Any],
    player: MutableMapping[str, Any],
    node: Any,
    node_id: str,
) -> str:
    """成功路径（2c2b §1.2 原子写：扣素材/扣金币/实例化入包/发经验 + 成功行渲染）。

    扣减顺序：先扣素材（remove_item 全量，任一失败回滚已扣项）→ 扣金币（node.cost
    coins 或 settings forge_fee=节点等级×10）→ 实例化合并（merge_forge_instance）→
    add_item 入包 → 熟练经验入账（gain_forge_exp，节点等级×2）。全链零中间态
    （失败即回滚已扣项，失败零副作用 §1.3）。
    """
    eng = _engine(ctx)

    # 扣素材（先校验可扣，再全量扣；失败零副作用）
    holdings = material_holdings(ctx, node)
    for item_id, h in holdings.items():
        if int(h.get("have", 0)) < int(h.get("need", 0)):
            # 素材不足（确认窗期间素材变化导致 → 拒绝，失败零副作用）
            name = str(h.get("name", item_id))
            deficit = int(h.get("need", 0)) - int(h.get("have", 0))
            src = str(h.get("source", ""))
            base = f"❌ 素材不足：需要 {_material_text(ctx, node)}；缺：{name}×{deficit}"
            base = base if not src else f"{base}（来源：{src}）"
            return f"{base} → /图纸 查看全链"
    deducted: List[str] = []
    for item_id, h in holdings.items():
        if not _remove_item(ctx, item_id, int(h.get("need", 0))):
            # 扣减失败 → 回滚已扣项（原子性，失败零副作用）
            for done in deducted:
                _add_item(ctx, done, int(holdings[done]["need"]), bound=False)
            return "❌ 素材扣减失败，本次锻造未执行（零副作用）"
        deducted.append(item_id)

    # 扣金币（node.cost.coins 显式覆盖 > settings forge_fee=节点等级×10，2c2a N-11）
    cost = _resolve_cost(ctx, node)
    currencies = player.get("currencies") if isinstance(player, MutableMapping) else None
    coins_have = 0
    if isinstance(currencies, MutableMapping):
        coins_have = int(currencies.get("coins", 0))
    if cost > 0 and coins_have < cost:
        # 金币不足 → 回滚素材，失败零副作用
        for done in deducted:
            _add_item(ctx, done, int(holdings[done]["need"]), bound=False)
        return f"❌ 金币不足：需要 {cost}，当前 {coins_have}"
    if cost > 0 and isinstance(currencies, MutableMapping):
        currencies["coins"] = coins_have - cost

    # 实例化并入包（AR-1~5 合并：items 基础 + 节点改造 → 属性快照入存档）
    item_ref = node.item if hasattr(node, "item") else (node.get("item") or node.get("output_item"))
    if isinstance(item_ref, str) and item_ref:
        items_def = _resolve_items_def(ctx, item_ref)
        inst = eng.merge_forge_instance(items_def, node)
        if not _add_item(ctx, item_ref, 1, bound=False):
            # 入包失败 → 回滚素材+金币（原子性）
            for done in deducted:
                _add_item(ctx, done, int(holdings[done]["need"]), bound=False)
            if cost > 0 and isinstance(currencies, MutableMapping):
                currencies["coins"] = coins_have
            return "❌ 装备入包失败，本次锻造未执行（零副作用）"
        player["forge_last"] = inst  # 属性快照入存档（AR-5）

    # 标记已锻造（forge_guard F-1：player["forged"] 追加节点 id；set/frozenset → 转 list）
    forged = player.get("forged")
    if not isinstance(forged, list):
        forged = list(forged) if isinstance(forged, (set, frozenset, tuple)) else []
        player["forged"] = forged
    if node_id not in forged:
        forged.append(node_id)

    # 熟练经验入账（EXP-01 craft 来源；节点等级×2 可配）
    node_lv = node.level if hasattr(node, "level") else 1
    gain_forge_exp(player, node_lv if isinstance(node_lv, int) else 1,
                   settings=_settings_of(ctx))

    # 首次锻造图鉴点亮（2c2b §1.2 步骤 5：mark_seen weapon 分册，ref=装备 item id，名=节点名）
    #   图鉴 weapon 册 total 来自 registry equipment 表（codex._total_of），ref 必须与
    #   items 装备条目 id 对齐（node.item），不能用 forge 节点 id（node_* 非装备条目 id）。
    try:
        item_ref = getattr(node, "item", None) or node_id
        node_name = getattr(node, "name", None) or node_id
        mark_seen(ctx, "weapon", item_ref, node_name)
    except Exception:
        pass  # 图鉴回写失败不阻断锻造结算（图鉴为辅助钩子）

    return _success_line(ctx, node)


def _resolve_cost(ctx: Mapping[str, Any], node: Any) -> int:
    """锻造金币开销（2c2a N-11 cost 显式 > settings forge_fee；forge_fee 缺省 节点等级×10）。"""
    raw = node.raw if hasattr(node, "raw") else node
    cost = raw.get("cost") if isinstance(raw, Mapping) else None
    if isinstance(cost, Mapping):
        coins = cost.get("coins")
        if isinstance(coins, int) and not isinstance(coins, bool) and coins >= 0:
            return coins
    seg = _forge_settings(ctx)
    fee = seg.get("forge_fee")
    lv = node.level if hasattr(node, "level") else node.get("level")
    lv = lv if isinstance(lv, int) and not isinstance(lv, bool) and lv > 0 else 1
    if isinstance(fee, int) and not isinstance(fee, bool) and fee >= 0:
        return fee
    if isinstance(fee, str):
        for token in fee.split("×"):
            t = token.strip()
            if t.isdigit():
                return lv * int(t)
    return lv * 10  # 缺省 节点等级×10（S-01）


def _resolve_items_def(ctx: Mapping[str, Any], item_id: str) -> Mapping[str, object]:
    """items 条目解析（id→条目 Mapping 或条目 list/tuple；缺 → {}，merge 兜底）。"""
    items = ctx.get("items")
    if isinstance(items, Mapping):
        hit = items.get(item_id)
        return hit if isinstance(hit, Mapping) else {}
    if isinstance(items, (list, tuple)):
        for e in items:
            if isinstance(e, Mapping) and e.get("id") == item_id:
                return e
    return {}


def _success_line(ctx: Mapping[str, Any], node: Any) -> str:
    """成功行（2c2b §1.2 / 定稿 L78：`✅ <节点名> 锻造完成！` + 属性行）。

    属性行：`攻击 N | 部位：武器 | 槽位：无 | 品质：<四档>（固定）`；
    带孔装备 槽位 显示 `1 级槽 ×1`（2c2a N-09 / 定稿 L190）。
    """
    name = node.name if hasattr(node, "name") and node.name else (node.get("name") or "")
    stats = node.stats if hasattr(node, "stats") else (node.get("stats") or {})
    node_type = node.node_type if hasattr(node, "node_type") else node.get("type")
    atk = stats.get("atk")
    atk_text = f"攻击 {atk}" if isinstance(atk, (int, float)) and not isinstance(atk, bool) else ""
    slot_cn = _SLOT_CN.get(str(node_type or ""), str(node_type or ""))
    slots = node.slots if hasattr(node, "slots") else (node.get("slots") or [])
    slots_seg = _slots_text(slots)
    slot_text = slots_seg.replace("孔位：", "") if slots_seg else "无"
    rarity_raw = node.rarity if hasattr(node, "rarity") else node.get("rarity")
    rarity_cn = _RARITY_CN.get(str(rarity_raw or "normal"), "普通")
    fields = []
    if atk_text:
        fields.append(atk_text)
    fields.append(f"部位：{slot_cn}")
    fields.append(f"槽位：{slot_text}")
    fields.append(f"品质：{rarity_cn}（固定）")
    return f"✅ {name} 锻造完成！\n" + " | ".join(fields)


# ---------------------------------------------------------------------------
# 路4B 双流路由 + /确认 窗口
# ---------------------------------------------------------------------------

def cmd_forge(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/锻造 主入口（路4A 原子流程 + 路4B 双流路由）。

    双流路由（2c2b §3.1 / TC-09~13）：
      - 显式「预览」参数（parsed.fixed_subword=预览 或 args 含 预览）→ 预览流 2 步；
      - 无「预览」参数 且 straight_forge=true（缺省）→ 直锻 1 步（原子成功）；
      - 无「预览」参数 且 straight_forge=false（深度模式）→ 强制预览流（前台无直锻入口）。

    GU-01 系统注册 / GU-02 参数解析（名禁空格）由 forge_atomic 承载；无节点参数 →
    TPL-12（对齐 shop cmd_buy 缺参模板）。
    """
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return format_tpl12(_fragment(parsed))
    # 显式「预览」子词：fixed_subword 或 args 中的「预览」标记（P-05 顺序兼容 `预览 *N`）
    fixed = getattr(parsed, "fixed_subword", None)
    has_preview = fixed == PREVIEW_SUBWORD or PREVIEW_SUBWORD in args
    node_args = [a for a in args if a != PREVIEW_SUBWORD]
    # P-01 节点名禁空格：多参数拆分（`/锻造 炎剑 Ⅱ` → args=[炎剑, Ⅱ]）→ 参数错误
    # （定稿 L232 语法约束，不匹配任何节点、不产生锻造）
    if len(node_args) > 1:
        return "参数错误：节点名不含空格"
    key = _target_of(parsed) if node_args else ""
    if not key or any(ch.isspace() for ch in key):
        return format_tpl12(_fragment(parsed)) if not key else "参数错误：节点名不含空格"

    # 双流路由：预览参数不依赖开关（3.1 双流并存）；straight_forge=false → 强制预览
    if not has_preview and _straight_forge(ctx):
        return forge_atomic(ctx, key, preview=False)  # 直锻 1 步（TC-09）
    return forge_atomic(ctx, key, preview=True)  # 预览流（TC-10/13）


def cmd_confirm(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/确认（2c2b §3.3 / TC-12~14）：预览 → /确认 一次性窗口终态。

    流程：
      ① 无进行中预览（qid 无窗 / 窗已超时作废）→ 拒绝「当前无可确认的锻造预览」
         （TC-14；无锻造、无扣款、无经验）；
      ② 有未过期窗 → 取 node_id，作废窗口（一次性），重跑 GU-03~06 守卫再扣素材发经验
         （复用 forge_atomic 执行路径）→ `✅ <节点> 锻造完成！`（TC-12）；
      ③ 失败（确认窗期间素材/前置/等级变化）→ 失败模板（失败零副作用，§1.3）。

    边界：本确认窗为超短期一次性引导，非框架 3.18 会话（不持久化、不可跨指令续接，
    L239）；窗口仅存在于单条指令→下一条指令之间。
    """
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    qid = _qid_of(ctx)
    if qid is None:
        return "当前无可确认的锻造预览"
    window = ctx.get(PREVIEW_WINDOW_KEY)
    if not isinstance(window, MutableMapping):
        return "当前无可确认的锻造预览"
    entry = window.get(qid)
    if not isinstance(entry, Mapping):
        return "当前无可确认的锻造预览"
    if _window_expired(ctx, entry):
        window.pop(qid, None)  # 超时 → 上下文作废（无锻造无扣款无经验，TC-11）
        return "预览已过期，请重新 /锻造 <节点> 预览"
    node_id = entry.get("node_id")
    window.pop(qid, None)  # 一次性：取走即作废（成功或失败均不再可确认）

    if not isinstance(node_id, str) or not node_id:
        return "当前无可确认的锻造预览"
    return forge_atomic(ctx, node_id, preview=False)  # 复用原子执行（重跑守卫再扣素材发经验）


def _join_node_args(args: List[str]) -> str:
    """节点名多参数拼接（P-01：`/锻造 炎剑 Ⅱ` → args=[炎剑, Ⅱ] → 拼接 `炎剑Ⅱ`）。

    非「预览」子词的多参数按紧凑拼接（节点名无空格，args 拆分来自空格输入）；
    拼接后仍含空格 → 由调用方 P-01 校验拒绝（参数错误）。"""
    return "".join(str(a) for a in args)


def _target_of(parsed: Any) -> str:
    """节点名剥离（解析器契约 + 紧凑 `+` 连接符收敛 + `*N` 剥离，对齐 alchemy _target_of）。

    `/锻造 炎剑Ⅱ*2` → args=["炎剑Ⅱ*2"], qty=2 → 目标 "炎剑Ⅱ"（P-05 数量）。"""
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return ""
    t = str(args[0])
    if t.startswith("+"):
        t = t[1:]
    if "*" in t:
        t = t.split("*", 1)[0]
    return t.strip()


# ---------------------------------------------------------------------------
# 装配（Router 注册；make_context 由装配层注入，对齐 shop/alchemy 壳模式）
# ---------------------------------------------------------------------------

def register_forge_commands(
    router: Any,
    *,
    make_context: Optional[Callable[[Any], dict]] = None,
) -> Any:
    """把 /锻造 /确认 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    :param make_context: ParsedCommand → 玩家 ctx dict（含 forge/items/settings/player/
        inventory/qid/now 等，见 _forge_atomic ctx 契约）。None 时 handler 调用抛
        RuntimeError（【待接线】装配层注入，对齐 shop_commands 口径）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "forge_commands.register_forge_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _forge(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_forge(parsed, injected)
        return cmd_forge(parsed, _ctx(parsed))

    def _confirm(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_confirm(parsed, injected)
        return cmd_confirm(parsed, _ctx(parsed))

    # /锻造（白名单已含「锻造」）；/确认（白名单已含「确认」，2c2b §5.3 登记指令）
    router.register(CommandSpec(FORGE_CMD, handler=_forge))
    router.register(CommandSpec(CONFIRM_CMD, handler=_confirm))
    return router
