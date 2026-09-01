"""统一 reward 解析器（M4 批次0·路A1 · dispatch_reward 唯一实现）——任务/签到/NPC/怪物掉落四系统共用发放器。

依据：
  - m4_shared_contract.md §1 A1（单一入口 dispatch_reward(entries, ctx) -> dict；条目形态
    {item,count} 入包默认绑定 / coins·gem 货币表（键空间 settings 货币键）/ exp 数值直入 /
    rep 入 reputation_state 不入货币表；内联键值串 = 序列化糖等价展开；逐条目失败黄字跳过不中断
    整批；幂等 version/tx id；返回 {ok, granted, skipped}）
  - docs/细化/细化_2b4_任务引擎契约.md §三（奖励统一条目 3 型；逐键入账管线；D-05 内联串=
    序列化糖解析器等价展开；TC-13~TC-17）
  - docs/审查参考/任务系统设计定稿.md L100-126（reward 字段；发放器唯一实现；rep 不入货币表 L118/L226）
  - docs/审查参考/NPC系统设计定稿.md L153（give_item 经框架 reward 解析器入账；items[]{id,count}
    的 id ≡ item 键，同一发放器）
  - M4 设计审查裁决 P1-2（reward 发放器逐条目失败黄字跳过、不中断整批结算；单事务=结算簿记
    原子性（main_progress/移出/quest_daily），条目失败不触发整单回滚）
  - M4 实现审查批次1（审查_M4实现_批次1_jspace.md P1-1）：物品入包失败（无 add_item hook 或 hook
    返回 False/抛错）→ 条目级 skip(item_add_failed) 而非静默 granted(applied=False)（现状把
    "未入包"伪装成"已发放"是静默丢奖根源）；"不封口幂等"由消费方（quest.py）整单回滚兜底。

【工程补白 · 显式标注】
  1) 货币表来源：ctx["currencies"]（玩家货币表 dict，就地累加）；货币键空间 = ctx["settings"]
     ["currencies"][].id，缺省 = 默认模板 ("coins","diamond")（对齐 battle_boundary
     DEFAULT_CURRENCY_IDS / content/validator._settings_currency_ids）。键不在键空间 → 该条
     skip（unknown_currency），不硬拦（P1-2 逐条目跳过）。
  2) reputation_state 落点：ctx["reputation_state"]（按板独立 dict，就地累加）；rep 条目入账键 =
     板 ID，取值 entry.board > entry.param > ctx["rep_board"] > "global"（缺省全局，任务定稿 L226）。
     rep 不入货币表。
  3) 入包落点：ctx["add_item"] hook（由调用方/背包引擎提供，签名 add_item(item_id, count, bound)）；
     hook 缺失或返回 False/抛错 → 该条目 skip(item_add_failed)（P1-1：不把"未入包"伪装成"已发放"，
     防静默丢奖）；item 条目 granted 恒 applied=True。消费方（quest/checkin 等）对 item_add_failed
     负责"不封口幂等"（quest.py 已整单回滚兜底）。
  4) 物品存在性：ctx["items"] 注册表（dict）或 ctx["resolve_item"] 解析器；注册表缺失或查无 →
     该条 skip（item_registry_missing / item_not_found）。
  5) 幂等：ctx["tx_id"]（结算唯一 id）与 ctx["ledger"]（已结算集合，调用方持有）同给才生效；
     同 tx 重复调用 → 直接返回 {ok, granted:[], skipped:[], idempotent:True}，不重复入账。
     批次完成（含普通 skipped 条目）即记 ledger；batch 级失败（ok=False）不记；含 item_add_failed
     （物品未实际入包，P1-1）不记 → 不封口幂等，由消费方整单回滚兜底、可重试。
  6) 黄字渲染不属于本解析器（纯函数，零 NoneBot import）：skipped[].reason 由调用方渲染黄字提示。

纯函数约定：ctx dict 进出——就地改写其可变子结构（currencies / exp / reputation_state / ledger），
存储与持久化由调用方完成。
"""

from __future__ import annotations

import re
from typing import Any, List, Mapping, MutableMapping, MutableSet, Optional

__all__ = [
    "dispatch_reward",
    "expand_inline_reward",
    "normalize_reward",
    "DEFAULT_CURRENCY_IDS",
]

# 默认货币键空间（对齐 battle_boundary.DEFAULT_CURRENCY_IDS / 3h §5.1）
DEFAULT_CURRENCY_IDS: tuple = ("coins", "diamond")

# 标量键值条目键（货币/经验/声望）
_SCALAR_KEYS: tuple = ("coins", "gem", "exp", "rep")
# 物品条目键：`item` 为主键，`id` 为等价别名（NPC give_item items[]{id,count} / 签到 items[]{id,count}）
_ITEM_KEYS: tuple = ("item", "id")
# 称号条目键（M11 4c §3.1 ④）：{title: "称号ID"}——仅成就系统使用，不扩散到任务/签到/NPC/掉落
_TITLE_KEYS: tuple = ("title",)

# 内联键值串单段语法：key[:=]value，物品支持 item:名称*N 数量后缀
_PAIR_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(.+?)\s*$")


def _settings_currency_space(ctx: Mapping[str, Any]) -> tuple:
    """已配置货币键空间（settings.currencies[].id）；缺省 = 默认模板（对齐 content/validator）。"""
    settings = ctx.get("settings")
    if isinstance(settings, Mapping):
        raw = settings.get("currencies")
        if isinstance(raw, list):
            ids = [
                e["id"] for e in raw
                if isinstance(e, Mapping) and isinstance(e.get("id"), str) and e["id"]
            ]
            if ids:
                return tuple(ids)
    return DEFAULT_CURRENCY_IDS


def expand_inline_reward(text: str) -> List[dict]:
    """内联键值串 → 结构化条目数组（D-05 序列化糖等价展开，解析器等价）。

    "exp=50,coins=80,item:铁矿*3" ≡ [{exp:50},{coins:80},{item:"铁矿",count:3}]

    - 逗号分隔多段；段语法 key[:=]value；物品段支持 item:名称*N 数量后缀（缺省 *1）。
    - 非法段（未知键 / 空值 / 非整数数值）→ 抛 ValueError（加载期=内容错误，由导入器/校验器拦截；
      dispatch_reward 运行时捕获并整串 skip）。
    """
    if not isinstance(text, str):
        raise TypeError(f"内联奖励串必须是 str，收到 {type(text).__name__}")
    entries: List[dict] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        m = _PAIR_RE.match(part)
        if not m:
            raise ValueError(f"无法解析的内联奖励段: {part!r}")
        key, raw = m.group(1), m.group(2)
        if key in _ITEM_KEYS:
            name, sep, count_s = raw.rpartition("*")
            if sep:
                item = name.strip()
                try:
                    count = int(count_s)
                except ValueError as exc:
                    raise ValueError(f"物品数量非法: {part!r}") from exc
            else:
                item, count = raw.strip(), 1
            if not item:
                raise ValueError(f"物品名为空: {part!r}")
            entries.append({"item": item, "count": count})
        elif key in _SCALAR_KEYS:
            try:
                value = int(raw)
            except ValueError as exc:
                raise ValueError(f"数值非法: {part!r}") from exc
            entries.append({key: value})
        else:
            raise ValueError(f"未知奖励键: {key!r}（段 {part!r}）")
    return entries


def normalize_reward(entries: Any) -> List[dict]:
    """任意 reward 形态 → 结构化条目数组。

    - str：内联键值串（序列化糖，D-05 展开）
    - dict：单条目包装为数组
    - list/tuple：逐元素归一（元素可为 dict 或内联 str，混用允许）
    - 其它形态 → 抛 TypeError（batch 级错误）
    """
    if isinstance(entries, str):
        return expand_inline_reward(entries)
    if isinstance(entries, Mapping):
        return [dict(entries)]
    if isinstance(entries, (list, tuple)):
        out: List[dict] = []
        for e in entries:
            if isinstance(e, str):
                out.extend(expand_inline_reward(e))
            elif isinstance(e, Mapping):
                out.append(dict(e))
            else:
                raise ValueError(f"非法奖励条目（期望 dict 或内联串）: {e!r}")
        return out
    raise TypeError(f"非法 reward 形态: {type(entries).__name__}")


def _valid_amount(value: Any) -> bool:
    """标量条目数值合法：int（非 bool）且 >= 0（负数为数值非法 → skip）。"""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _item_exists(item_id: str, ctx: Mapping[str, Any]) -> tuple:
    """物品存在性：ctx["items"] 注册表（dict）或 ctx["resolve_item"] 解析器。

    返回 (exists, source)；source ∈ {"registry", "resolver", "missing"}。
    """
    items = ctx.get("items")
    if isinstance(items, Mapping):
        return (item_id in items), "registry"
    resolver = ctx.get("resolve_item")
    if callable(resolver):
        try:
            return bool(resolver(item_id)), "resolver"
        except Exception:
            return False, "resolver"
    return False, "missing"


def _item_name_of(ctx: Mapping[str, Any], item_id: str) -> str:
    """物品显示名（图鉴点亮用）：ctx["items"][id].name / Def.name；兜底 item_id。"""
    items = ctx.get("items")
    if isinstance(items, Mapping):
        entry = items.get(item_id)
        if isinstance(entry, Mapping):
            nm = entry.get("name")
            if isinstance(nm, str) and nm:
                return nm
        elif entry is not None:
            nm = getattr(entry, "name", None)
            if isinstance(nm, str) and nm:
                return nm
    resolver = ctx.get("resolve_item")
    if callable(resolver):
        try:
            d = resolver(item_id)
            nm = getattr(d, "name", None)
            if isinstance(nm, str) and nm:
                return nm
            if isinstance(d, Mapping):
                nm = d.get("name")
                if isinstance(nm, str) and nm:
                    return nm
        except Exception:
            pass
    return item_id


def _grant_item(entry: Mapping[str, Any], ctx: Mapping[str, Any]) -> Optional[dict]:
    """物品条目 {item|id, count, bound} → 入包（默认绑定）。失败=skip 黄字，不抛错。"""
    key = "item" if "item" in entry else "id"
    item_id = entry[key]
    count = entry.get("count", 1)
    bound = entry.get("bound", True)

    if not isinstance(item_id, str) or not item_id.strip():
        return {"ok": False, "skip": {"type": "item", "item": item_id, "count": count,
                                      "reason": "invalid_value"}}
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        return {"ok": False, "skip": {"type": "item", "item": item_id, "count": count,
                                      "reason": "invalid_value"}}
    if not isinstance(bound, bool):
        return {"ok": False, "skip": {"type": "item", "item": item_id, "count": count,
                                      "reason": "invalid_value"}}

    exists, source = _item_exists(item_id, ctx)
    if source == "missing":
        return {"ok": False, "skip": {"type": "item", "item": item_id, "count": count,
                                      "reason": "item_registry_missing"}}
    if not exists:
        return {"ok": False, "skip": {"type": "item", "item": item_id, "count": count,
                                      "reason": "item_not_found"}}

    # 入包（工程补白③ + M4 实现审查批次1 P1-1）：经 ctx["add_item"] hook 实际入包；
    # hook 缺失或返回 False/抛错 → 该条 skip(item_add_failed)（不伪装 granted，防静默丢奖）
    add_item = ctx.get("add_item")
    if not callable(add_item):
        return {"ok": False, "skip": {"type": "item", "item": item_id, "count": count,
                                      "reason": "item_add_failed"}}
    try:
        result = add_item(item_id, count, bound)
    except Exception:
        result = False
    if result is False:
        return {"ok": False, "skip": {"type": "item", "item": item_id, "count": count,
                                      "reason": "item_add_failed"}}

    return {"ok": True, "grant": {"type": "item", "item": item_id, "count": count,
                                  "bound": bound, "applied": True}}


def _write_ctx_int(ctx: Mapping[str, Any], key: str, value: int) -> bool:
    """就地改写 ctx 标量槽（exp）。ctx 需为可变 dict；不可写 → False（该条 skip missing_bucket）。"""
    try:
        ctx[key] = value  # type: ignore[index]
        return True
    except (TypeError, KeyError):
        return False


def _grant_scalar(key: str, value: Any, entry: Mapping[str, Any], ctx: Mapping[str, Any]) -> Optional[dict]:
    """标量条目 coins/gem/exp/rep → 入账。失败=skip，不抛错。"""
    if not _valid_amount(value):
        return {"ok": False, "skip": {"type": key, "amount": value, "reason": "invalid_value"}}

    if key in ("coins", "gem"):
        if not isinstance(ctx.get("currencies"), MutableMapping):
            return {"ok": False, "skip": {"type": key, "amount": value, "reason": "missing_bucket"}}
        space = _settings_currency_space(ctx)
        if key not in space:
            return {"ok": False, "skip": {"type": key, "amount": value, "reason": "unknown_currency",
                                          "currency_space": list(space)}}
        ctx["currencies"][key] = ctx["currencies"].get(key, 0) + value
        return {"ok": True, "grant": {"type": "currency", "currency": key, "amount": value}}

    if key == "exp":
        cur = ctx.get("exp")
        if not isinstance(cur, int) or isinstance(cur, bool):
            return {"ok": False, "skip": {"type": "exp", "amount": value, "reason": "missing_bucket"}}
        if not _write_ctx_int(ctx, "exp", cur + value):
            return {"ok": False, "skip": {"type": "exp", "amount": value, "reason": "missing_bucket"}}
        return {"ok": True, "grant": {"type": "exp", "amount": value}}

    if key == "rep":
        if not isinstance(ctx.get("reputation_state"), MutableMapping):
            return {"ok": False, "skip": {"type": "rep", "amount": value, "reason": "missing_bucket"}}
        # 板 ID：entry.board > entry.param > ctx["rep_board"] > "global"（工程补白②）
        board = entry.get("board", entry.get("param", ctx.get("rep_board", "global")))
        if not isinstance(board, str) or not board:
            board = "global"
        ctx["reputation_state"][board] = ctx["reputation_state"].get(board, 0) + value
        return {"ok": True, "grant": {"type": "rep", "amount": value, "board": board}}

    return {"ok": False, "skip": {"type": key, "amount": value, "reason": "invalid_entry"}}


def _grant_title(entry: Mapping[str, Any], ctx: Mapping[str, Any]) -> Optional[dict]:
    """称号条目 {title: 称号ID} → 写入 title_state.owned（4c §3.1 ④ / §3.3，仅成就使用）。

    - 校验：ctx[\"titles\"] 注册表（proficiency.json titles 段映射 {id: 条目}）——
      引用不存在 → skip(title_not_registered)（4c 硬拦口径，条目级黄字跳过）；
      注册表缺失 → skip(title_registry_missing)（fail-safe，不硬崩）。
    - 写入：ctx[\"title_state\"][\"owned\"] 可佩戴列表（就地，append 去重；equipped 键
      不触碰——佩戴由 ProficiencyEngine.equip_title 单独管理）。写入即落档（ctx 注入
      为就地引用，对齐 context.py title_state 收口 L1098-1104）。
    - 重复授予（已在 owned）→ 幂等 granted（不重复 append）。
    """
    title_id = entry.get("title")
    if not isinstance(title_id, str) or not title_id.strip():
        return {"ok": False, "skip": {"type": "title", "title": title_id,
                                      "reason": "invalid_value"}}
    tid = title_id.strip()
    titles = ctx.get("titles")
    if not isinstance(titles, Mapping):
        return {"ok": False, "skip": {"type": "title", "title": tid,
                                      "reason": "title_registry_missing"}}
    if tid not in titles:
        return {"ok": False, "skip": {"type": "title", "title": tid,
                                      "reason": "title_not_registered"}}
    ts = ctx.get("title_state")
    if not isinstance(ts, MutableMapping):
        return {"ok": False, "skip": {"type": "title", "title": tid,
                                      "reason": "missing_title_state"}}
    owned = ts.get("owned")
    if not isinstance(owned, list):
        owned = []
        ts["owned"] = owned
    if tid not in owned:
        owned.append(tid)
    return {"ok": True, "grant": {"type": "title", "title": tid, "applied": True}}


def _dispatch_one(entry: Mapping[str, Any], ctx: Mapping[str, Any]) -> Optional[dict]:
    """单条目分发。返回 {"ok", "grant"|"skip"} 或 None（不处理）。"""
    if not isinstance(entry, Mapping):
        return {"ok": False, "skip": {"type": "invalid", "reason": "invalid_entry", "entry": entry}}

    if "item" in entry or "id" in entry:
        return _grant_item(entry, ctx)

    if "title" in entry:  # M11 4c §3.1 ④：称号型（仅成就系统使用，G2）
        return _grant_title(entry, ctx)

    if "rep" in entry:  # rep 允许可选 board/param 扩展键
        return _grant_scalar("rep", entry["rep"], entry, ctx)

    if "prof" in entry:  # M8 批14 测试探针：熟练度奖励 {prof:{job, exp}} → 任务引导解锁炼金
        return _grant_prof(entry, ctx)

    if len(entry) == 1:
        key = next(iter(entry))
        if key in _SCALAR_KEYS:
            return _grant_scalar(key, entry[key], entry, ctx)

    return {"ok": False, "skip": {"type": "invalid", "reason": "invalid_entry", "entry": dict(entry)}}


def _grant_prof(entry: Mapping[str, Any], ctx: Mapping[str, Any]) -> Optional[dict]:
    """熟练度奖励（M8 批14：任务奖励炼金熟练度，玩家完成引导任务解锁炼金玩法）。

    条目形态：{"prof": {"job": "alchemy", "exp": 150}}——exp 为熟练经验
    （ProficiencyEngine.gain_prof_exp 入账 → 升级 → SP 发放，source=quest 默认倍率）。
    ctx 消费：prof_engine（ProficiencyEngine 实例）+ proficiency（persistent_state 引用，
    批13 注入——引擎就地改写即落档）。失败=skip，不抛错。
    """
    prof_spec = entry.get("prof")
    if not isinstance(prof_spec, Mapping):
        return {"ok": False, "skip": {"type": "prof", "reason": "invalid_prof",
                                      "entry": dict(entry)}}
    job = prof_spec.get("job") or prof_spec.get("id")
    amount = prof_spec.get("exp")
    if not isinstance(job, str) or not job:
        return {"ok": False, "skip": {"type": "prof", "reason": "missing_job"}}
    if not _valid_amount(amount):
        return {"ok": False, "skip": {"type": "prof", "reason": "invalid_amount"}}
    pe = ctx.get("prof_engine")
    if not callable(getattr(pe, "gain_prof_exp", None)):
        return {"ok": False, "skip": {"type": "prof", "reason": "missing_prof_engine"}}
    prof_bucket = ctx.get("proficiency")
    if not isinstance(prof_bucket, MutableMapping):
        return {"ok": False, "skip": {"type": "prof", "reason": "missing_proficiency"}}
    # 包装 player 引用（gain_prof_exp 就地改写 player["proficiency"][job]；
    # 传引用 → 落档 persistent_state.proficiency 直接更新，与 ctx["player"] dataclass 解耦）
    player_wrap = {"proficiency": prof_bucket}
    r = pe.gain_prof_exp(player_wrap, job, amount, source="quest")  # type: ignore[union-attr]
    if not r.get("ok"):
        return {"ok": False, "skip": {"type": "prof", "reason": "grant_failed",
                                      "detail": r.get("reason")}}
    return {"ok": True, "grant": {"type": "prof", "job": job, "amount": amount,
                                  "level": r.get("level"), "level_ups": r.get("level_ups")}}


def _iter_entries(entries: Any):
    """逐条目产出（内容级错误不抛错：产 (None, err) 标记 skip，P1-2 不中断整批）。

    - 顶层形态错误（entries 非 str/dict/list）由调用方先行判 batch 失败；
    - 内容级错误：非法内联串 / 列表内非映射元素 → 该条 skip，批次继续。
    """
    if isinstance(entries, str):
        try:
            for e in expand_inline_reward(entries):
                yield e, None
        except ValueError as exc:
            yield None, str(exc)
    elif isinstance(entries, Mapping):
        yield dict(entries), None
    else:  # list / tuple
        for e in entries:
            if isinstance(e, str):
                try:
                    for x in expand_inline_reward(e):
                        yield x, None
                except ValueError as exc:
                    yield None, str(exc)
            elif isinstance(e, Mapping):
                yield dict(e), None
            else:
                yield None, f"非法奖励条目（期望 dict 或内联串）: {e!r}"


def dispatch_reward(entries: Any, ctx: Optional[Mapping[str, Any]] = None) -> dict:
    """统一 reward 解析器唯一入口（A1）——四系统共用发放器。

    参数：
      entries: 结构化条目数组 / 单条目 dict / 内联键值串（序列化糖，等价展开）
      ctx:     结算上下文 dict（就地改写）：currencies / exp / reputation_state 为入账桶，
               settings（货币键空间）/ items|resolve_item（物品存在性）/ add_item（入包 hook）/
               tx_id + ledger（幂等）/ rep_board（rep 缺省板 ID）。

    返回：{"ok": bool, "granted": [grant...], "skipped": [skip...], [idempotent]: bool}
      - ok=True：批次完成（内容级失败已逐条 skip，不中断整批，P1-2）；ok=False 仅顶层/ctx 级
        失败（ctx 非法 / entries 顶层形态非法）。
      - granted：按数组顺序的入账记录；item 恒 applied=True（入包失败走 skip(item_add_failed)，
        P1-1 不伪装"已发放"）。
      - skipped：逐条失败记录，携带 reason（调用方渲染黄字提示）。
      - idempotent=True：同 tx_id 已在 ledger（重复调用不重复入账）。
    """
    if ctx is None:
        ctx = {}
    if not isinstance(ctx, Mapping):
        return {"ok": False, "granted": [], "skipped": [{"type": "batch", "reason": "invalid_ctx"}]}

    # 顶层形态校验（编程/加载错误 → batch 失败，非内容级 skip）
    if not isinstance(entries, (str, Mapping, list, tuple)):
        return {"ok": False, "granted": [],
                "skipped": [{"type": "batch", "reason": "invalid_entries",
                             "detail": f"非法 reward 形态: {type(entries).__name__}"}]}

    # 幂等闸（工程补白⑤）：同 tx_id 已结算 → 直接返回，不重复入账
    tx_id = ctx.get("tx_id")
    ledger = ctx.get("ledger")
    if tx_id is not None and isinstance(ledger, MutableSet) and tx_id in ledger:
        return {"ok": True, "granted": [], "skipped": [], "idempotent": True}

    granted: List[dict] = []
    skipped: List[dict] = []
    for e, err in _iter_entries(entries):
        if err is not None:
            skipped.append({"type": "invalid", "reason": "invalid_entry", "detail": err})
            continue
        if e is None:  # 防御：内容级失败已由 err 分支处理
            continue
        out = _dispatch_one(e, ctx)
        if out is None:
            continue
        if out["ok"]:
            granted.append(out["grant"])
        else:
            skipped.append(out["skip"])

    # M11 批2 路2C（4d G-9）：item 首获图鉴点亮——granted 中 type=item 逐条
    # mark_seen(ctx,"item",...)；幂等早退天然防双 mark；try/except 防图鉴异常
    # 吞奖励（图鉴为辅助钩子）；ctx 需可变（mark_seen 写 codex_state）。
    if granted and isinstance(ctx, MutableMapping):
        try:
            from qbot_rpg.core.codex import item_craft_relation
            from qbot_rpg.core.codex import mark_seen as _codex_mark_seen

            for g in granted:
                if not isinstance(g, Mapping) or g.get("type") != "item":
                    continue
                iid = g.get("item") or g.get("item_id")
                if not isinstance(iid, str) or not iid:
                    continue
                name = _item_name_of(ctx, iid)
                # M11 批4 A2 P1-1 修复：制造品归属 craft 册 → 不点亮 item 册
                # （item 分母已反向减除制造品，点亮悬空条目无意义；craft 点亮由
                #  炼金/锻造结算点负责）
                if item_craft_relation(ctx, iid) == "craft":
                    continue
                _codex_mark_seen(ctx, "item", iid, name)
        except Exception:
            pass
        # M11 批2 路2C（4d D-06）：图鉴点亮结算点 → 里程碑阶梯检查（幂等已授不重授）
        try:
            from qbot_rpg.core.codex_milestones import check_milestones

            check_milestones(ctx)
        except Exception:
            pass

    # 幂等落账：批次完成（含普通 skipped 条目）即记 ledger；ok=False（batch 级失败）不记；
    # item_add_failed（物品未实际入包，P1-1）不记 → 不封口幂等，可重试（防静默丢奖）
    if tx_id is not None and isinstance(ledger, MutableSet):
        if not any(
            isinstance(s, Mapping) and s.get("type") == "item"
            and s.get("reason") == "item_add_failed"
            for s in skipped
        ):
            ledger.add(tx_id)

    return {"ok": True, "granted": granted, "skipped": skipped}
