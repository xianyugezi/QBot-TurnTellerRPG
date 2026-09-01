"""M10 批3·路3A：出鱼结算（qbot_rpg/core/fishing_settle.py）——settle_catch。

文件名：qbot_rpg/core/fishing_settle.py
创建时间：2026-08-31
作者：Hermes 子agent-3A（M10 钓鱼实现组批3·路3A：出鱼结算 T10）

功能描述（T10 / 细化_2c1b §四 4.4 出鱼结算接线）：
  settle_catch(ctx, last_snapshot) -> dict：出鱼结算（被指令壳调用，消费 reel_in
  写入的 fish_state["last"] 快照）——纯收藏约束下完成：
    ① 解析快照（target_species_id / roll / reel_ts）；
    ② 调兄弟路3B 的 gen_size_weight（百分位生成+线性插值）与 crown_of（六档判定）
       ——fishing_crown 已落盘直接 import；
    ③ 图鉴点亮：调 fish_codex_update（路4A 才落盘——本路先做本地薄实现，
       S-3 防 mark_seen 覆盖：更新 caught_count/best_crown/best_size/best_weight/
       min_size/min_weight/reverse_crown_count，首获 mark_seen 点亮；写
       codex_state["fish"][species_id]）；
    ④ 熟练经验：调 ProficiencyEngine.gain_prof_exp(player, "fishing", amount,
       source="gather")（job_id=fishing，批5 才加 proficiency 实例——本路先标
       source=gather + job_id="fishing"，引擎缺省容错；amount 用常数 10，
       工程补白 F-1）；
    ⑤ 奖励：dispatch_reward(entries, ctx)（金币/物品，reward 发放器直接复用；
       entries 默认金币少量，内容包可配，工程补白 F-2）；
    ⑥ 返回 {ok, species_id, name, size, weight, size_pct, weight_pct, crown,
       rarity, message}；结算记录含三要素 size/weight/crown（TC-24）。
  纯收藏约束：结算计算不读取冠级字段进数值（价值/经验/售价与冠级无关——crown
  只入图鉴与展示，R-05 / TC-25 差分=0）。

依据：
  - docs/细化/细化_2c1b_钓鱼流程状态机.md §四 4.4（出鱼结算接线 M6：鱼种×大小×
    重量×冠级 → 图鉴点亮+熟练经验+奖励；size/weight/crown 三要素落结算记录）
  - docs/细化/细化_2c1a_鱼种数据与冠级.md §四（图鉴记录 G-01~G-07 更新规则 +
    4.2 首获点亮）/ §2.4（纯收藏约束）
  - docs/m10_接口摸底.md §三（codex mark_seen 覆盖陷阱 → 专用入册函数防覆盖）/
    §四（reward 发放器一条调用）/ §六（proficiency fishing 实例批5 才加）/
    §九（rng 注入、种子化确定性）
  - docs/m10_shared_contract.md §五 铁律
  - 定稿 §1 M6（出鱼结算 L20）/ §2.3（冠级纯收藏 L46-48 / L132）
模式参考：
  - qbot_rpg/core/fishing_crown.py（批3 路3B：gen_size_weight/crown_of 同源供给）
  - qbot_rpg/core/reward.py（dispatch_reward：coins 入 ctx["currencies"] 就地累加）
  - qbot_rpg/core/proficiency.py（gain_prof_exp：player["proficiency"][job] 就地改）
  - qbot_rpg/core/codex.py（mark_seen 整条目覆盖陷阱——本路专用入册防覆盖）

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查）：
  S-1  快照来源与校验：last_snapshot 显式传参（指令壳读 fish_state["last"] 传入；
       批1 B-6 骨架快照无 roll 键、批2 路2C 注入 roll 后含 roll 键——本路兼容两
       形态）。快照缺 target_species_id / 非 str → 拒绝 reason=missing_snapshot
       （止损/跑鱼/无结算路径不产生 last，指令壳不会调用；防御兜底不炸）。
  S-2  species 解析：快照 target_species_id → ctx["fish_table"]（Def→raw dict
       装配形态）→ ctx["fishing"]["species"]（raw list）→ ctx["species"] 兜底；
       查无 → 拒绝 reason=species_not_found（不结算不落账，防静默丢结算）。
  S-3  图鉴入册：fish_codex_update 为**本地薄实现**（路4A 落盘后由主 agent 收口
       替换为路4A 专用入册函数，签名保持 (ctx, species_id, catch) 不变）。实现
       防 mark_seen 覆盖：codex_state["fish"][species_id] 整条目按七键更新
       （G-01~G-07），首获同步 mark_seen(category="fish") 点亮（name/seen/killed/
       lore_unlocked 由 mark_seen 落；扩展键不覆盖）；无条目时建默认七键条目。
       best_crown 优先级链 big_gold > gold > big_silver > silver > normal（逆金冠
       不入链，单独 reverse_crown_count，2c1a §4.2）。
  S-4  mark_seen 接线：codex.CATEGORIES 尚无 "fish" 分册（摸底 §三 批4 才加）——
       本路 fish_codex_update 内置最小 mark_seen 等价逻辑（见 _mark_fish_seen），
       不 import codex.mark_seen（避免未知分册拒绝）。路4A 落盘后收口替换。
  S-5  奖励默认：金币少量（coins=20）+ 无物品（内容包可配键
       settings.fishing.settle_reward 覆盖；可配形态见 _settle_entries，缺省
       {"coins": 20}）。经验不发 reward 的 exp（熟练经验单独走 gain_prof_exp，
       防双轨入账）。金额为工程默认非定稿值。
  S-6  熟练经验：amount=10 常数（工程默认，批5 路5A 接入 proficiency fishing
       实例/来源倍率后由主 agent 收口可配化）。引擎缺省容错：ctx["prof_engine"]
       缺失/无 gain_prof_exp → 静默跳过（返回 exp_granted=False），不阻断结算
       （批5 装配注入后才生效）；ctx["proficiency"] 缺失 → 跳过（同上）。
       source="gather"（采集来源，2c1c 钓鱼熟练度归 gather 系）。
  S-7  结算幂等：ctx["tx_id"] + ctx["ledger"] 存在时结算前登记 tx_id（消费快照
       一次）；重复调用同 tx_id → 直接返回 {ok:False, reason:"already_settled"}
       不重复入账（对齐 reward 发放器幂等闸；指令壳在事务内单次调用，双保险）。
       无 tx_id/ledger（测试直调）→ 每次独立结算（确定性可测）。
  S-8  纯收藏约束实现：结算计算的奖励金额/熟练经验/消息组装**均不读取 crown
       字段**（crown 仅入图鉴与展示返回）；TC-25 差分=0 由本实现保证（reward
       条目与 prof amount 与 crown 无关，测试直证）。
  S-9  结算记录：返回 dict 含 size/weight/crown 三要素（TC-24）；文案常量 TODO
       批6 模板化（本路返回结构化 dict，message 为骨架占位）。

铁律：零 NoneBot import；纯函数确定性零 IO 零定时器/零睡眠（时间戳只读，无实时
      倒计时）；rng 必须注入（ctx["rng"] 或参数 rng，禁裸 random 破坏确定性）；
      输出文案不写死模板（批6 模板化，本路返回结构化 dict）；零 emoji；本路独占
      qbot_rpg/core/fishing_settle.py + tests/unit/test_fishing_settle.py，不碰
      core/fishing.py（批1 已定稿）/ commands/（批2/批6）/ proficiency.json（批5）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, MutableSet, Optional, cast

from qbot_rpg.content.fishing_models import FishDef
from qbot_rpg.core.fishing_codex import (  # 批4 正式入册 + 链常量（A4 P2-7 去重复定义）
    CROWN_PRIORITY,
    fish_codex_update,
)
from qbot_rpg.core.fishing_crown import crown_of, gen_size_weight
from qbot_rpg.core.fishing_settings import fishing_cfg

# =====================================================================================
# 常量：奖励默认 / 熟练经验默认（工程默认，内容包可配，S-5/S-6）
# =====================================================================================

# 熟练经验默认量（工程补白 S-6：批5 路5A 接入 proficiency fishing 实例后收口可配化）
DEFAULT_PROF_EXP_AMOUNT: int = 10

# 出鱼奖励默认（工程补白 S-5：金币少量，内容包可配键 settings.fishing.settle_reward）
DEFAULT_SETTLE_REWARD: Dict[str, int] = {"coins": 20}

# 奖励可配键（settings.fishing 段下；形态对齐 reward 发放器条目：金币/物品）
_SETTLE_REWARD_KEY: str = "settle_reward"

# 熟练职业 id（2c1c：钓鱼熟练度归 gather 系；批5 才加 proficiency fishing 实例）
_PROF_JOB_ID: str = "fishing"

# 熟练经验来源（采集系，2c1c 钓鱼熟练度归 gather 源）
_PROF_SOURCE: str = "gather"

# 图鉴分册名（codex type=fish，摸底 §三；路4A 落盘 CATEGORIES 后同键）
CODEX_CATEGORY_FISH: str = "fish"

# 图鉴条目七键（细化 2c1a §4.1 G-01~G-07）
CODEX_FISH_KEYS: tuple = (
    "caught_count",
    "best_crown",
    "best_size",
    "best_weight",
    "min_size",
    "min_weight",
    "reverse_crown_count",
)

# 结算消息文案常量（TODO 模板化：批6 fishing_tpl 分区接管，本路返回结构化 dict）
MSG_SETTLED: str = "出鱼成功：{name} · {size}cm/{weight}kg · {crown}"
MSG_NO_SNAPSHOT: str = "无可结算的收杆记录"
MSG_SPECIES_NOT_FOUND: str = "鱼种数据缺失，无法结算"
MSG_ALREADY_SETTLED: str = "该次收杆已结算过"


# =====================================================================================
# 工具：持久化 / 快照 / species / 奖励归一
# =====================================================================================
def _persistent_state_of(ctx: Mapping[str, Any]) -> Optional[MutableMapping[str, Any]]:
    """persistent_state 可变容器定位（对齐 fishing._persistent_state_of 口径）。"""
    ps = ctx.get("persistent_state")
    if isinstance(ps, MutableMapping):
        return ps
    player = ctx.get("player")
    if isinstance(player, Mapping):
        ps2 = player.get("persistent_state")
        if isinstance(ps2, MutableMapping):
            return ps2
    if isinstance(ctx, MutableMapping):
        return ctx
    return None


def _codex_state_of(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """codex_state 可变引用（ctx 直键；缺省建空 dict 挂回，对齐 codex._state_of）。"""
    st = ctx.get("codex_state")
    if not isinstance(st, MutableMapping):
        st = {}
        ctx["codex_state"] = st
    return st


def _fish_state_of(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """fish_state 可变引用（ctx 直键；缺省建空 dict 挂回，对齐 fishing._fish_state_of）。"""
    fs = ctx.get("fish_state")
    if isinstance(fs, MutableMapping):
        return fs
    node: MutableMapping[str, Any] = {}
    ps = _persistent_state_of(ctx)
    if isinstance(ps, MutableMapping):
        ps["fish_state"] = node
    ctx["fish_state"] = node
    return node


def _species_of(ctx: Mapping[str, Any], species_id: str) -> Optional[object]:
    """按 id 查鱼种（FishDef / raw dict）：ctx["fish_table"] → ctx["fishing"] 池 →
    ctx["species"] 兜底；查无 → None（S-2，不炸）。"""
    ft = ctx.get("fish_table")
    if isinstance(ft, Mapping):
        entry = ft.get(species_id)
        if entry is not None:
            return entry
    fishing = ctx.get("fishing")
    if isinstance(fishing, Mapping):
        species = fishing.get("species")
        if isinstance(species, list):
            for s in species:
                if isinstance(s, Mapping) and s.get("id") == species_id:
                    return s
    pool = ctx.get("species")
    if isinstance(pool, (list, tuple)):
        for s in pool:
            if isinstance(s, Mapping) and s.get("id") == species_id:
                return s
    return None


def _name_of(species: object) -> str:
    """鱼种显示名（FishDef.name / Mapping name；缺省回落 id）。"""
    if isinstance(species, FishDef):
        return str(species.name or getattr(species, "id", "") or "")
    if isinstance(species, Mapping):
        name = species.get("name")
        if isinstance(name, str) and name:
            return name
        rid = species.get("id")
        return str(rid) if isinstance(rid, str) else ""
    return ""


def _rarity_of(species: object) -> str:
    """鱼种基础稀有度（normal/rare/gold；缺省回落 normal，对齐引擎口径）。"""
    if isinstance(species, FishDef):
        r = species.rarity
        return r if isinstance(r, str) and r else "normal"
    if isinstance(species, Mapping):
        r = species.get("rarity")
        return r if isinstance(r, str) and r else "normal"
    return "normal"


def _settle_entries(cfg: Mapping[str, object]) -> List[object]:
    """出鱼奖励条目归一（工程补白 S-5：内容包可配键 settings.fishing.settle_reward）。

    - 缺省 → [{"coins": 20}]（金币少量，工程默认非定稿值）。
    - 显式配置形态：list[dict]（reward 发放器条目数组，逐条照发）/ dict（单条目）/
      内联键值串（如 "coins=30"，dispatch_reward 支持 list 内 str 元素等价展开）；
      非法/空 → 回落默认。零副作用纯函数。
    """
    raw = cfg.get(_SETTLE_REWARD_KEY)
    if isinstance(raw, Mapping):
        return [dict(raw)]
    if isinstance(raw, list) and raw:
        out: List[object] = []
        for e in raw:
            if isinstance(e, Mapping):
                out.append(dict(e))
        return out if out else [dict(DEFAULT_SETTLE_REWARD)]
    if isinstance(raw, str) and raw.strip():
        # 内联键值串（如 "coins=30"）→ 原样作为 str 条目（dispatch 等价展开）
        return [raw]
    return [dict(DEFAULT_SETTLE_REWARD)]


def _raw_fishing_segment(ctx: Mapping[str, Any]) -> Mapping[str, object]:
    """原始 settings.fishing 段（S-8：不过 fishing_cfg 归一，保留全部键）。

    三态同构（对齐 pull_odds_of 修复）：ctx 含 settings 键 → 解包；settings 含
    fishing 键 → 取段；否则视为段本身。非 Mapping → 空段。
    """
    raw: object = ctx
    if isinstance(raw, Mapping) and isinstance(raw.get("settings"), Mapping):
        raw = raw["settings"]
    if not isinstance(raw, Mapping):
        return {}
    if "fishing" in raw:
        seg = raw["fishing"]
        return seg if isinstance(seg, Mapping) else {}
    return raw


def _prof_exp_amount(cfg: Mapping[str, object]) -> int:
    """熟练经验量（工程补白 S-6：默认 10；内容包可配键 settings.fishing.settle_prof_exp）。"""
    raw = cfg.get("settle_prof_exp")
    if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
        return raw
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and float(raw) > 0:
        return int(float(raw))
    return DEFAULT_PROF_EXP_AMOUNT


# =====================================================================================
# 图鉴点亮（批4 路4A 正式版 fishing_codex.fish_codex_update，签名不变 (ctx, species_id,
# catch)——收口替换本地薄实现；防 mark_seen 覆盖由正式版承载）
# =====================================================================================
# 正式版导出：fish_codex_update / fish_meta / render_fish_entry_line / CODEX_CATEGORY_FISH
# / CROWN_PRIORITY / KING_VICTORY_COUNT_KEY（见 qbot_rpg/core/fishing_codex.py）



# =====================================================================================
# 熟练经验（source=gather + job_id="fishing"，批5 才加 proficiency 实例，S-6）
# =====================================================================================
def _grant_prof_exp(
    ctx: MutableMapping[str, Any],
    amount: int,
) -> dict:
    """熟练经验入账（T10 ④）：ProficiencyEngine.gain_prof_exp(player, "fishing",
    amount, source="gather")——job_id=fishing，批5 才加 proficiency 实例，引擎
    缺省容错；amount 用配置或常数 10（S-6）。

    - ctx["prof_engine"] 缺省/无 gain_prof_exp → 静默跳过 {ok:False,
      reason:"missing_prof_engine"}（批5 装配注入后才生效，不阻断结算）。
    - player 形态：ctx["player"] 为 MutableMapping 且含 proficiency 键 → 直用；
      ctx["proficiency"] 直键（_ps_init 挂 ps 形态）→ 包装
      {"proficiency": ctx["proficiency"]} 传引用（对齐 reward._grant_prof 包装，
      引擎就地改写即落档）。
    - 返回 {ok, exp_gained, level, level_ups, tier_from, tier_to}；失败跳过不抛。
    """
    pe = ctx.get("prof_engine")
    if pe is None or not callable(getattr(pe, "gain_prof_exp", None)):
        return {"ok": False, "reason": "missing_prof_engine"}
    player: Optional[MutableMapping[str, Any]] = None
    p = ctx.get("player")
    if isinstance(p, MutableMapping):
        prof = p.get("proficiency")
        if isinstance(prof, MutableMapping):
            player = p
    if player is None:
        prof_bucket = ctx.get("proficiency")
        if isinstance(prof_bucket, MutableMapping):
            player = {"proficiency": prof_bucket}
    if player is None:
        return {"ok": False, "reason": "missing_proficiency"}
    try:
        r = pe.gain_prof_exp(player, _PROF_JOB_ID, amount, source=_PROF_SOURCE)
    except Exception:
        return {"ok": False, "reason": "grant_failed"}
    if not isinstance(r, Mapping) or not r.get("ok"):
        detail = r.get("reason") if isinstance(r, Mapping) else None
        return {"ok": False, "reason": "grant_failed", "detail": detail}
    return {
        "ok": True,
        "exp_gained": r.get("exp_gained", amount),
        "level": r.get("level"),
        "level_ups": r.get("level_ups", 0),
        "tier_from": r.get("tier_from"),
        "tier_to": r.get("tier_to"),
    }


# =====================================================================================
# 主入口：出鱼结算
# =====================================================================================
def settle_catch(
    ctx: MutableMapping[str, Any],
    last_snapshot: Optional[Mapping[str, object]] = None,
    *,
    rng: Any = None,
) -> dict:
    """出鱼结算主入口（T10 / 细化_2c1b §四 4.4：被指令壳调用，消费 reel_in 写入的
    fish_state["last"] 快照）。

    入参：
      ctx           —— 结算上下文（codex_state / currencies / proficiency /
                       prof_engine / now / rng / items / registry 等，make_context
                       已注入；player 写路径走 ctx["codex_state"] / ctx["proficiency"]
                       就地改，_ps_init 挂 ps 形态即落档）。
      last_snapshot —— reel_in 写入的 last 快照（dict）；None → 自动读
                       ctx["fish_state"]["last"]。快照键（批1 B-6 / 批2 路2C）：
                       target_species_id / target_rarity / choice / kind / golden /
                       spot_id / bite_ts / reel_ts / roll（roll 骨架快照可缺，S-1）。
      rng           —— 注入 rng（Random 实例，种子 42/2026 确定性）；None →
                       ctx["rng"] → random 模块兜底（对齐 fishing._resolve_rng）。
    出参：
      {ok, species_id, name, size, weight, size_pct, weight_pct, crown, rarity,
       message, ...}——结算记录含三要素 size/weight/crown（TC-24）；附 first_seen /
      caught_count / best_crown / reverse_crown_count / exp_gained / reward /
      granted / skipped 明细供指令壳组装消息。
      拒绝：{ok:False, reason:"missing_snapshot"|"species_not_found"|
      "already_settled", message}——不抛异常（对齐引擎惯例）。

    结算链路（4.4）：
      ① 快照解析（target_species_id / reel_ts，S-1 校验）；
      ② 兄弟路3B gen_size_weight（百分位+线性插值）+ crown_of（六档判定）——
         fishing_crown 已落盘直接 import（本文件顶部）；
      ③ fish_codex_update 图鉴点亮（七键更新 + 首获点亮，S-3/S-4）；
      ④ _grant_prof_exp 熟练经验（source=gather，job_id=fishing，S-6）；
      ⑤ dispatch_reward 奖励（金币/物品，默认 coins=20，S-5）；
      ⑥ 组装返回（size/weight/crown 三要素 + message 骨架）。
    纯收藏约束（R-05 / TC-25）：④⑤ 的计算入参均不读取 crown 字段——奖励金额/
      熟练经验与冠级无关，crown 只入图鉴与展示；差分=0 由实现保证。
    确定性：同 seed 同 ctx 同快照 → 恒同结果（注入 rng 单源）；零 IO 零定时器/
      零睡眠（时间戳只读，无实时倒计时）。
    """
    if not isinstance(ctx, MutableMapping):
        return {"ok": False, "reason": "invalid_ctx", "message": ""}

    # ① 快照解析（S-1：显式传参优先，缺省读 fish_state["last"]）
    snap: Optional[Mapping[str, object]] = last_snapshot
    if snap is None:
        fs = _fish_state_of(ctx)
        raw_last = fs.get("last")
        snap = raw_last if isinstance(raw_last, Mapping) else None
    if snap is None:
        return {"ok": False, "reason": "missing_snapshot", "message": MSG_NO_SNAPSHOT}
    species_id = snap.get("target_species_id")
    if not isinstance(species_id, str) or not species_id.strip():
        return {"ok": False, "reason": "missing_snapshot", "message": MSG_NO_SNAPSHOT}

    # 幂等闸（S-7）：同 tx_id 已结算 → 拒绝不重复入账（防双花）。
    # 注意：只检查不占位——ledger 记账交给 dispatch_reward（它自身幂等闸在结算成功
    # 后 add；此处若先 add 会导致 reward 幂等闸误判「已结算」跳过入账，金币永不落账）
    tx_id = ctx.get("tx_id")
    ledger = ctx.get("ledger")
    if tx_id is not None:
        # 审查 A4 P1-1：tx_id 存在但 ledger 缺失（装配漏注入/测试直调）→ 拒绝，
        # 宁可失败不可双花（中间态明确拒绝，不静默放行）
        if not isinstance(ledger, MutableSet):
            return {"ok": False, "reason": "missing_ledger",
                    "species_id": species_id, "message": MSG_NO_SNAPSHOT}
        if tx_id in ledger:
            return {"ok": False, "reason": "already_settled",
                    "species_id": species_id, "message": MSG_ALREADY_SETTLED}

    # species 解析（S-2：查无 → 拒绝不结算）
    species = _species_of(ctx, species_id)
    if species is None:
        return {"ok": False, "reason": "species_not_found",
                "species_id": species_id, "message": MSG_SPECIES_NOT_FOUND}

    # ② 大小/重量 + 冠级（兄弟路3B 同源供给；rng 注入确定性）
    r = rng
    if r is None:
        r = ctx.get("rng")
    sw = gen_size_weight(species, rng=r, ctx=ctx)
    # crown 阈值参数化（C-3 三态：显式 dict / settings 全量 / fishing_cfg 段 /
    # None 默认 5/85/95；crown_of 内部经 fishing_cfg 归一读段，纯函数零 IO）
    thresholds_raw: object = None
    if isinstance(ctx.get("settings"), Mapping):
        thresholds_raw = ctx["settings"]
    elif isinstance(ctx.get("fishing_cfg"), Mapping):
        thresholds_raw = ctx["fishing_cfg"]
    crown = crown_of(sw["size_pct"], sw["weight_pct"], cast(Dict[str, int], thresholds_raw))

    cfg = fishing_cfg(ctx.get("settings") if isinstance(ctx.get("settings"), Mapping) else ctx)
    # 工程补白 S-8：settle_reward/settle_prof_exp 不在 fishing_cfg 9 契约键内（fishing_cfg
    # 归一会过滤），须从原始段读取（对齐批2 pull_odds 同款修复）——_settle_entries /
    # _prof_exp_amount 读原始段，缺键回落默认
    raw_seg = _raw_fishing_segment(ctx)
    settle_ctx: Dict[str, object] = dict(cfg)
    settle_ctx[_SETTLE_REWARD_KEY] = raw_seg.get(_SETTLE_REWARD_KEY)
    settle_ctx["settle_prof_exp"] = raw_seg.get("settle_prof_exp")

    # ③ 图鉴点亮（七键更新 + 首获点亮，防 mark_seen 覆盖）——A4 P1-2：首获写中文名
    catch = {"size": sw["size"], "weight": sw["weight"], "crown": crown}
    codex_r = fish_codex_update(ctx, species_id, catch, name=_name_of(species))

    # ④ 熟练经验（source=gather；amount 配置或常数 10，S-6）——读 settle_ctx（含原始段键）
    prof_r = _grant_prof_exp(ctx, _prof_exp_amount(settle_ctx))
    # ⑤ 奖励（reward 发放器直接复用；默认金币少量，S-5）——纯收藏约束：entries
    #    与 crown 无关（不读取 crown 字段，R-05/TC-25 差分=0）——读 settle_ctx（含原始段键）
    #    审查 A4 P1-3：只吞 ImportError（装配缺失可明示）；dispatch 自身异常透出 detail
    #    （reason=dispatch_error + detail=异常类型），不静默吞掉奖励丢失
    reward_r = {}
    try:
        from qbot_rpg.core.reward import dispatch_reward

        reward_r = dispatch_reward(_settle_entries(settle_ctx), ctx)
    except ImportError:
        reward_r = {"ok": False, "granted": [],
                    "skipped": [{"type": "batch", "reason": "dispatch_unavailable"}]}
    except Exception as exc:  # noqa: BLE001 - 奖励发放兜底，异常透出可观测
        reward_r = {"ok": False, "granted": [],
                    "skipped": [{"type": "batch", "reason": "dispatch_error",
                                "detail": f"{type(exc).__name__}: {exc}"}]}

    # ⑥ 组装返回（三要素 size/weight/crown，TC-24）
    name = _name_of(species)
    rarity = _rarity_of(species)
    return {
        "ok": True,
        "species_id": species_id,
        "name": name,
        "size": sw["size"],
        "weight": sw["weight"],
        "size_pct": sw["size_pct"],
        "weight_pct": sw["weight_pct"],
        "crown": crown,
        "rarity": rarity,
        "first_seen": bool(codex_r.get("first_seen")),
        "caught_count": codex_r.get("caught_count"),
        "best_crown": codex_r.get("best_crown"),
        "reverse_crown_count": codex_r.get("reverse_crown_count"),
        "exp_gained": prof_r.get("exp_gained") if prof_r.get("ok") else 0,
        "prof_level": prof_r.get("level"),
        "reward": reward_r.get("granted", []),
        "reward_skipped": reward_r.get("skipped", []),
        "message": MSG_SETTLED.format(name=name, size=sw["size"], weight=sw["weight"], crown=crown),
    }


__all__ = [
    # 常量
    "DEFAULT_PROF_EXP_AMOUNT",
    "DEFAULT_SETTLE_REWARD",
    "CODEX_CATEGORY_FISH",
    "CODEX_FISH_KEYS",
    "CROWN_PRIORITY",
    # 图鉴入册
    "fish_codex_update",
    # 主入口
    "settle_catch",
]
