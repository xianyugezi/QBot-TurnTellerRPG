"""特性继承引擎（M8 批5·路1 · qbot_rpg/core/trait_inherit.py）——位上限等级化+SP 叠加 /
PP 预算 / 互斥 / repeatable / 负面 / 超特性第 4 位 / 写入快照。

文件名：qbot_rpg/core/trait_inherit.py
创建时间：2026-08-29
作者：Hermes 子agent-5A-1（并发同仓：本路独占本文件 + tests/unit/test_trait_inherit.py +
      tests/unit/test_inherit_commands.py，只改 commands/alchemy_commands.py（追加）；
      兄弟路 2 在写 core/alchemy_settle.py（结算引擎），本文件零 import 之，只读勿探查）

功能描述：TraitInherit —— 特性继承引擎（纯逻辑零 IO 零 NoneBot）。承载「/继承 /继承超」
  F-04 全部核心判定：继承位等级化（INH-14/15：正式1→精通2→专家3 见习0 + SP 特性位+1
  叠加）、PP 预算（INH-09/TSC-14：普通1/超2，会话内累计，pp_refresh=会话重置）、特性位余量
  （INH-06：普通位默认≤3 可配 1-6 + 超特性第 4 位独占 gold_slot_exclusive）、group 互斥
  （INH-10）、repeatable（INH-11）、负面特性（INH-12：宗师继承强力特性自动附带同源负面）、
  超特性宗师门槛（TSC-11）、投料候选清单来源校验（INH-01）、写入会话快照（INH-08/STO-03）。
  供批5 指令壳（cmd_inherit/cmd_inherit_super）与批6A 结算复核（check_placement_conflict，
  INH-10/11 防会话内绕校验）消费。

依据：
  - docs/细化/细化_2c4e_品质与特性.md：INH-01~16（来源/传递/冲突/等级化四规则族）、
    TSC-11~14（超特性：super=金色/第 4 位独占 gold_slot_exclusive/PP2/素材继承）、
    TC-12~24。
  - docs/m8_contract_核心机制.md：§五（TSC/INH 全文）+ §十 10.3 默认值速查（pp_cost
    normal1/super2、pp_refresh 会话重置）。
  - docs/m8_contract_指令契约.md：§4 /继承 /继承超（P-04/GU-13~16/F-04/M-04）。
  - docs/m8_contract_数据与校验.md：L48/L140（traits_inherit 1-3 / unlocks trait_slot_1）、
    REC-12（继承位总上限 1-6）。
  - 已落地：qbot_rpg/core/alchemy_core.py（AlchemyCore.build_feature_pool 特性候选池
    {normal,gold,awaken}、pp_budget/pp_cost_of/can_afford_pp、new_snapshot/apply_feed）、
    qbot_rpg/core/proficiency.py（ProficiencyEngine.unlock_count SP 解锁计数）、
    content/test_demo/traits.json（真实形态：rarity/group/repeatable/source）。

【工程补白 · 显式标注】（定稿/细化未给口径处，本引擎最小必要推导，不得新增定稿外行为）：
  T-1  继承位计算口径（INH-14/15/06，TC-12/13）：普通特性位预算 =
       min(tier_slots, trait_slot_max) + SP 特性位+1 次数，总上限 6（REC-12）——
       tier_slots = {见习:0, 正式:1, 精通:2, 专家+:3}；settings.alchemy.trait_slot_max
       （默认 3，钳制 1-6）为等级位的上限钳制；SP 解锁次数经
       ProficiencyEngine.unlock_count(player, "alchemy", panel_id) 读取，panel_id 默认
       "trait_slot_1"（对齐数据与校验 L140 unlocks 示例），settings.alchemy.trait_slot_panel_id
       可配。见习（tier<正式）为硬门槛：继承位恒 0，任何继承拒绝「无继承位」。
  T-2  特性 def 解析 ctx 注入（select_traits/check_placement_conflict）：签名按任务书
       （player, snap, trait_ids, *, super_trait, job_tier_index）保留，另增可选 ctx=None
       用于解析 traits def（group/repeatable/source/negative/rarity 字段）；缺省无 ctx →
       仅以池内信息（id/name/pp）校验（PP/位/候选清单仍生效），group/repeatable/负面
       校验按保守放行降级（指令壳恒传 ctx）。
  T-3  强力特性→同源负面 判定口径（INH-12，TC-20）：trait def 字段 `negative`（traits.json
       标记，值为负面特性 id）优先；回落 settings.alchemy.negative_traits 映射
       {强力特性id: 负面特性id}（配置同源负面映射）。负面特性继承需宗师（tier≥5）——
       宗师以下选择带负面配置的强力特性 → 拒绝「负面特性需宗师」。
  T-4  负面特性占位不耗 PP（INH-12「占特性位/效果生效」）：自动附带的负面特性占 1 个普通
       特性位（计入位余量），但不计 PP（PP 计价唯一依据 = rarity，TSC-14；负面为自动附带
       非用户选择，按最小必要不额外计价）。负面特性不参与 group/repeatable 复核（自动附带
       负担，内容包配置控制）。负面特性引用失效（ctx 解析不到）→ 跳过附带不报错
       （STO-05 引用失效兜底）。
  T-5  超特性需宗师（TSC-11）：rarity=super 特性继承门槛 = 炼金职业 ≥ 宗师（tier≥5）；
       gold_slot_exclusive=true（默认，settings.alchemy.gold_slot_exclusive 可配）时超特性
       独占第 4 位（已占用 → 拒绝）；gold_slot_exclusive=false 时超特性与普通共用位池
       （计入普通位预算，写入快照普通 traits 列表，不占第 4 位字段）。
  T-6  错误模板（对齐定稿 L344 错误模板全集 + 细化 INH 编号）：见习 →「见习无继承位」；
       PP 不足 →「PP 不足」；位余量 →「继承超 N 项」（N=实际预算）；互斥 →「互斥组内最多
       1 项：<组名>」；repeatable →「该特性不可重复继承」；候选清单 →「特性须来自投料候选
       清单（不可凭空继承）」；超特性宗师 →「超特性继承需宗师」；负面宗师 →「负面特性需宗师」；
       第 4 位已占 →「第 4 位金色已占用」。

铁律：零 NoneBot import；纯函数（同刻同参必同值，snap 只读不改写——select_traits 返回结果、
      apply_to_snapshot 返回新快照，写库由壳层 suspend）；不抛异常（防御降级返回 dict）；
      每条规则注释标注出处（INH/TSC 编号 + 细化行号）；不得新增定稿外机制行为。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from qbot_rpg.core.alchemy_core import ALCHEMY_JOB_ID, DEFAULT_PP_COST, STEP_INHERIT

__all__ = [
    "FORMAL_TIER_INDEX",
    "GRANDMASTER_TIER_INDEX",
    "INHERIT_TOTAL_SLOT_CAP",
    "DEFAULT_TRAIT_SLOT_MAX",
    "DEFAULT_TRAIT_SLOT_PANEL_ID",
    "TraitInherit",
]

# ---------------------------------------------------------------------------
# 常量（档位索引锚点对齐 alchemy_core：见习0/正式1/精通2/专家3/大师4/宗师5/王6）
# ---------------------------------------------------------------------------
FORMAL_TIER_INDEX: int = 1        # 正式：特性继承 1 项（INH-14/L81-84）
GRANDMASTER_TIER_INDEX: int = 5   # 宗师：超特性/负面特性门槛（TSC-11/INH-12）
INHERIT_TOTAL_SLOT_CAP: int = 6   # 继承位总上限（REC-12：普通位总上限 1-6，SP/等级扩展承载）
DEFAULT_TRAIT_SLOT_MAX: int = 3   # 等级位默认上限（INH-06：普通位默认 ≤3）
DEFAULT_TRAIT_SLOT_PANEL_ID: str = "trait_slot_1"  # SP 特性位+1 面板 id（数据与校验 L140 示例）

# 档位→继承位 逐级开放表（INH-14：见习0/正式1/精通2/专家+3；受 trait_slot_max 钳制 T-1）
_TIER_SLOTS: Tuple[int, ...] = (0, 1, 2, 3)


class TraitInherit:
    """特性继承引擎（INH-01~16 / TSC-11~14 纯函数承载）。

    构造器配置注入（proficiency 引擎 + settings）+ 缺省默认值兜底（对齐
    alchemy_core.py / proficiency.py 模式）。纯函数零 IO 零 NoneBot，不抛异常；
    snap 只读不改写——select_traits 返回结果 dict，apply_to_snapshot 返回新快照，
    落库由指令壳 suspend 完成。
    """

    def __init__(
        self,
        prof: Optional[Any] = None,
        settings: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """构造特性继承引擎（配置注入 + 缺省默认值兜底）。

        入参：
          - prof：ProficiencyEngine 实例（可选注入；用于 SP 特性位+1 解锁计数
            unlock_count，缺省 → SP 加成 0）。
          - settings：settings dict（读 alchemy 段 trait_slot_max/trait_slot_panel_id/
            gold_slot_exclusive/negative_traits/pp_cost）；None/缺 alchemy 段 →
            默认模板兜底（对齐 m8_contract §10.3 默认值速查）。
        """
        self._prof = prof
        self._settings: Mapping[str, Any] = settings if isinstance(settings, Mapping) else {}

    # ------------------------------------------------------------------
    # 配置读取（缺省默认值兜底）
    # ------------------------------------------------------------------
    def _alchemy_settings(self) -> Mapping[str, Any]:
        """settings.alchemy 段（缺省空 Mapping，调用方各自兜底）。"""
        alch = self._settings.get("alchemy")
        if isinstance(alch, Mapping):
            return alch
        return {}

    def _trait_slot_max(self) -> int:
        """普通位等级上限（INH-06/T-1：settings.alchemy.trait_slot_max 默认 3，钳制 1-6）。"""
        raw = self._alchemy_settings().get("trait_slot_max", DEFAULT_TRAIT_SLOT_MAX)
        try:
            v = int(raw)
        except (TypeError, ValueError):
            v = DEFAULT_TRAIT_SLOT_MAX
        return max(1, min(6, v))

    def _trait_slot_panel_id(self) -> str:
        """SP 特性位+1 面板 id（T-1：settings.alchemy.trait_slot_panel_id 默认 trait_slot_1）。"""
        raw = self._alchemy_settings().get("trait_slot_panel_id", DEFAULT_TRAIT_SLOT_PANEL_ID)
        return str(raw) if isinstance(raw, str) and raw else DEFAULT_TRAIT_SLOT_PANEL_ID

    def _gold_slot_exclusive(self) -> bool:
        """第 4 位独占开关（TSC-12：settings.alchemy.gold_slot_exclusive 默认 true）。"""
        raw = self._alchemy_settings().get("gold_slot_exclusive", True)
        return bool(raw)

    def _negative_map(self) -> Mapping[str, Any]:
        """同源负面映射（T-3：settings.alchemy.negative_traits {强力特性id: 负面id}）。"""
        raw = self._alchemy_settings().get("negative_traits")
        if isinstance(raw, Mapping):
            return raw
        return {}

    def _pp_cost(self) -> Dict[str, int]:
        """特性继承 PP 消耗表（TSC-14/L414：settings.alchemy.pp_cost 可配；
        缺省 normal=1/super=2）。"""
        raw = self._alchemy_settings().get("pp_cost")
        out: Dict[str, int] = {}
        if isinstance(raw, Mapping):
            for k in ("normal", "super"):
                try:
                    out[k] = max(0, int(raw.get(k, DEFAULT_PP_COST[k])))
                except (TypeError, ValueError):
                    out[k] = DEFAULT_PP_COST[k]
        else:
            out = dict(DEFAULT_PP_COST)
        return out

    def pp_cost_of(self, trait_def: Mapping[str, Any]) -> int:
        """特性继承 PP 消耗（TSC-14：rarity 是唯一计价依据——super=pp_cost.super(2)、
        其余 normal(1)）。"""
        cost = self._pp_cost()
        if trait_def.get("rarity") == "super":
            return max(0, int(cost.get("super", 2)))
        return max(0, int(cost.get("normal", 1)))

    # ------------------------------------------------------------------
    # 档位归一（int 索引 / 称号名 / 英文别名，对齐 alchemy_core._norm_tier_index）
    # ------------------------------------------------------------------
    def _tier_names(self) -> Tuple[str, ...]:
        """7 级称号名（prof 注入则优先其 tier_names，否则默认 7 级）。"""
        prof = self._prof
        if prof is not None:
            try:
                names = tuple(prof.tier_name(ALCHEMY_JOB_ID, i) for i in range(7))
                if len(names) >= 2:
                    return names
            except Exception:
                pass
        from qbot_rpg.core.alchemy_core import DEFAULT_TIER_NAMES
        return DEFAULT_TIER_NAMES

    def _norm_tier_index(self, job_tier: Any) -> int:
        """job_tier 归一为档位索引 int（见习0/正式1/精通2/专家3/大师4/宗师5/王6）。"""
        if isinstance(job_tier, bool):
            return 0
        if isinstance(job_tier, int):
            return max(0, job_tier)
        if isinstance(job_tier, str) and job_tier:
            names = self._tier_names()
            if job_tier in names:
                return names.index(job_tier)
            alias: Dict[str, int] = {
                "apprentice": 0, "formal": 1, "proficient": 2, "expert": 3,
                "master": 4, "grandmaster": 5, "king": 6,
            }
            return alias.get(job_tier, 0)
        return 0

    # ------------------------------------------------------------------
    # 特性 def 解析（ctx 注册表 / resolver / 名称扫描 / 池内兜底，T-2）
    # ------------------------------------------------------------------
    @staticmethod
    def _find_trait_def(
        key: Any,
        ctx: Optional[Mapping[str, Any]],
        pool: Optional[Sequence[Any]] = None,
    ) -> Optional[dict]:
        """特性 def 解析（id → 注册表 → resolver → 名称扫描 → 池内 id/name 兜底，T-2）。

        入参：key=特性 id 或 name；ctx（traits 注册表 / resolve_trait 解析器）；pool=
        候选池条目列表（[(tid, name, pp)] 或 dict）。出参：def dict 或 None。
        """
        if not isinstance(key, str) or not key:
            return None
        reg = ctx.get("traits") if isinstance(ctx, Mapping) else None
        if isinstance(reg, Mapping):
            val = reg.get(key)
            if isinstance(val, Mapping):
                return dict(val)
            for val in reg.values():
                if isinstance(val, Mapping) and val.get("name") == key:
                    return dict(val)
        resolver = ctx.get("resolve_trait") if isinstance(ctx, Mapping) else None
        if callable(resolver):
            try:
                val = resolver(key)
                if isinstance(val, Mapping):
                    return dict(val)
            except Exception:
                pass
        for entry in pool or []:
            if isinstance(entry, Mapping):
                if entry.get("id") == key or entry.get("name") == key:
                    return dict(entry)
            elif isinstance(entry, (tuple, list)) and len(entry) >= 2:
                if entry[0] == key or entry[1] == key:
                    return {"id": str(entry[0]), "name": str(entry[1])}
        return None

    @staticmethod
    def _pool_ids(pool: Optional[Sequence[Any]]) -> set:
        """候选池条目 id 集合（条目形态 [(tid, name, pp)] 或 dict）。"""
        out: set = set()
        for entry in pool or []:
            if isinstance(entry, Mapping):
                tid = entry.get("id")
            elif isinstance(entry, (tuple, list)) and entry:
                tid = entry[0]
            else:
                tid = None
            if isinstance(tid, str) and tid:
                out.add(tid)
        return out

    # ------------------------------------------------------------------
    # 继承位（INH-14/15/06，TC-12/13，T-1）
    # ------------------------------------------------------------------
    def inherit_slots(self, player: Any, job_tier_index: Any) -> int:
        """普通特性位预算（INH-14/15，TC-12/13，T-1）。

        入参：player（读 SP 特性位+1 解锁次数）、job_tier_index（档位索引/称号名）。
        出参：普通特性位预算 int（见习 0 硬门槛；总上限 6，REC-12）。
        核心逻辑：等级位（正式1/精通2/专家+3，受 trait_slot_max 钳制）+ SP 特性位+1
          次数（unlock_count，可多次 INH-15），叠加后钳制总上限 6。
        """
        tier = self._norm_tier_index(job_tier_index)
        if tier < FORMAL_TIER_INDEX:
            return 0  # INH-14 见习无继承位（硬门槛，即使有 SP）
        cap = self._trait_slot_max()
        tier_slots = _TIER_SLOTS[min(tier, len(_TIER_SLOTS) - 1)]
        tier_slots = min(tier_slots, cap)  # INH-06 普通位默认≤3 可配 1-6（T-1）
        sp_bonus = 0
        prof = self._prof
        if prof is not None:
            try:
                sp_bonus = max(0, int(prof.unlock_count(
                    player, ALCHEMY_JOB_ID, self._trait_slot_panel_id()
                )))
            except Exception:
                sp_bonus = 0
        return min(tier_slots + sp_bonus, INHERIT_TOTAL_SLOT_CAP)

    # ------------------------------------------------------------------
    # 候选池读取（AlchemyCore.build_feature_pool 已产，INH-01/03/TSC-13）
    # ------------------------------------------------------------------
    @staticmethod
    def pool_normal(snap: Optional[Mapping[str, Any]]) -> list:
        """普通候选池（INH-01/03：source=素材/成品 特性；快照 pool.normal 条目列表）。"""
        if not isinstance(snap, Mapping):
            return []
        pool = snap.get("pool")
        if not isinstance(pool, Mapping):
            return []
        return list(pool.get("normal") or [])

    @staticmethod
    def pool_gold(snap: Optional[Mapping[str, Any]]) -> list:
        """金色超特性候选池（TSC-13：source=金色素材 特性；快照 pool.gold 条目列表）。"""
        if not isinstance(snap, Mapping):
            return []
        pool = snap.get("pool")
        if not isinstance(pool, Mapping):
            return []
        return list(pool.get("gold") or [])

    # ------------------------------------------------------------------
    # 负面特性（INH-12，TC-20，T-3/T-4）
    # ------------------------------------------------------------------
    def _negative_of(self, trait_def: Mapping[str, Any]) -> Optional[str]:
        """强力特性 → 同源负面特性 id（T-3：traits.json `negative` 字段优先，回落
        settings.alchemy.negative_traits 映射）。无负面配置 → None。"""
        raw = trait_def.get("negative")
        if isinstance(raw, str) and raw:
            return raw
        tid = trait_def.get("id")
        if isinstance(tid, str):
            m = self._negative_map().get(tid)
            if isinstance(m, str) and m:
                return m
        return None

    def _resolve_negatives(
        self, neg_ids: Sequence[str], ctx: Optional[Mapping[str, Any]]
    ) -> List[str]:
        """负面特性 id 去重解析（T-4：引用失效跳过附带不报错，STO-05 兜底）。"""
        out: List[str] = []
        for nid in neg_ids:
            nid = str(nid)
            if not nid or nid in out:
                continue
            ndef = self._find_trait_def(nid, ctx)
            if ndef is None:
                continue  # STO-05 引用失效兜底：跳过不报错
            out.append(nid)
        return out

    # ------------------------------------------------------------------
    # F-04 核心：select_traits（INH-01/06/09/10/11/12/14/15 + TSC-11~14，TC-12~24）
    # ------------------------------------------------------------------
    def select_traits(
        self,
        player: Any,
        snap: Optional[Mapping[str, Any]],
        trait_ids: Optional[Sequence[Any]],
        *,
        super_trait: Optional[Any] = None,
        job_tier_index: Any,
        ctx: Optional[Mapping[str, Any]] = None,
        slot_cap: Optional[int] = None,
    ) -> dict:
        """F-04 核心：继承选择原子判定（INH-01/06/09/10/11/12/14/15 + TSC-11~14）。

        入参：
          - player：玩家状态 dict（SP 特性位+1 解锁计数）。
          - snap：会话快照（含 pool{normal,gold} / pp{used,budget} / traits / gold_slot）。
          - trait_ids：普通特性 id/name 列表（指令壳按 name 传，引擎解析并校验候选清单）。
          - super_trait：超特性 id/name（/继承超 单一项；None=无）。
          - job_tier_index：职业档位（int 索引 / 称号名）。
          - ctx：可选；traits def 解析（group/repeatable/negative/rarity/source，T-2）。
          - slot_cap：可选；位上限覆盖（指令壳取 min(继承位, 配方 traits_inherit)，T-1）。
        出参：
          - 成功 {ok, traits:[普通特性 id...], gold_slot: 超特性 id 或 None, negatives:[...],
            pp_used: 会话累计 PP used, message}；
          - 拒绝 {ok:False, reason, message, ...}（reason: no_inherit_slot / pp_insufficient /
            slot_overflow / group_conflict / not_repeatable / not_in_pool / trait_not_found /
            super_not_found / not_super / grandmaster_required / gold_slot_occupied /
            empty_selection / no_snapshot）。
        核心逻辑（F-04 顺序）：候选清单来源（INH-01）→ PP 逐项扣除（INH-09）→ 特性位余量
          （INH-06 + 超特性第 4 位）→ group 互斥（INH-10）→ repeatable（INH-11）→
          负面特性（INH-12）→ 超特性宗师（TSC-11）。原子判定：任一步失败全拒零副作用。
        """
        if not isinstance(snap, Mapping):
            return {"ok": False, "reason": "no_snapshot",
                    "message": "当前没有调合会话，先 /炼金 <配方> 开始"}
        tier = self._norm_tier_index(job_tier_index)
        # ① 见习硬门槛（INH-14：见习无继承位，L344 错误模板）
        if self.inherit_slots(player, tier) <= 0:
            return {"ok": False, "reason": "no_inherit_slot", "message": "见习无继承位"}
        if not trait_ids and super_trait is None:
            return {"ok": False, "reason": "empty_selection", "message": "未选择特性"}

        pool = snap.get("pool") or {}
        if not isinstance(pool, Mapping):
            pool = {}
        normal_pool = list(pool.get("normal") or [])
        gold_pool = list(pool.get("gold") or [])
        normal_ids = self._pool_ids(normal_pool)
        gold_ids = self._pool_ids(gold_pool)

        # ② 普通特性解析 + 候选清单来源校验（INH-01 不可凭空继承；STO-05 引用失效拒绝）
        chosen: List[dict] = []
        for raw in trait_ids or []:
            tdef = self._find_trait_def(raw, ctx, normal_pool)
            if tdef is None:
                return {"ok": False, "reason": "trait_not_found",
                        "message": f"特性不存在：{raw}"}
            tid = str(tdef.get("id") or raw)
            if tid not in normal_ids:
                return {"ok": False, "reason": "not_in_pool",
                        "message": "特性须来自投料候选清单（不可凭空继承）"}
            chosen.append({**tdef, "id": tid})

        # ③ 超特性解析（TSC-11~13：金色池 + rarity=super + 宗师门槛）
        super_def: Optional[dict] = None
        super_tid: Optional[str] = None
        if super_trait is not None and str(super_trait):
            super_def = self._find_trait_def(super_trait, ctx, gold_pool)
            if super_def is None:
                return {"ok": False, "reason": "super_not_found",
                        "message": f"超特性不存在：{super_trait}"}
            super_tid = str(super_def.get("id") or super_trait)
            if super_tid not in gold_ids:
                return {"ok": False, "reason": "not_in_pool",
                        "message": "超特性须来自金色素材投料候选清单"}
            if super_def.get("rarity") != "super":
                return {"ok": False, "reason": "not_super",
                        "message": f"{super_trait} 不是超特性（金色超特性）"}

        # ④ 超特性/负面特性宗师门槛（TSC-11 / INH-12，T-3）
        if super_def is not None and tier < GRANDMASTER_TIER_INDEX:
            return {"ok": False, "reason": "grandmaster_required",
                    "message": "超特性继承需宗师"}
        neg_cfg: List[str] = []
        for tdef in chosen:
            neg = self._negative_of(tdef)
            if neg is not None:
                if tier < GRANDMASTER_TIER_INDEX:
                    return {"ok": False, "reason": "grandmaster_required",
                            "message": "负面特性需宗师"}
                neg_cfg.append(neg)
        if super_def is not None:
            sneg = self._negative_of(super_def)
            if sneg is not None:
                if tier < GRANDMASTER_TIER_INDEX:
                    return {"ok": False, "reason": "grandmaster_required",
                            "message": "负面特性需宗师"}
                neg_cfg.append(sneg)

        # ⑤ PP 逐项扣除（INH-09/TSC-14：普通1/超2，会话内累计，pp_refresh=会话重置）
        pp = snap.get("pp")
        pp_used = 0
        pp_budget = 0
        if isinstance(pp, Mapping):
            try:
                pp_used = max(0, int(pp.get("used", 0)))
            except (TypeError, ValueError):
                pp_used = 0
            try:
                pp_budget = max(0, int(pp.get("budget", 0)))
            except (TypeError, ValueError):
                pp_budget = 0
        need = sum(self.pp_cost_of(t) for t in chosen)
        if super_def is not None:
            need += self.pp_cost_of(super_def)
        if pp_used + need > pp_budget:
            return {"ok": False, "reason": "pp_insufficient", "message": "PP 不足",
                    "need": need, "available": max(0, pp_budget - pp_used)}

        # ⑥ 特性位余量（INH-06：普通位默认≤3 可配 1-6 + 超特性第 4 位独占；T-1/T-5）
        budget = self.inherit_slots(player, tier)
        if slot_cap is not None:
            try:
                budget = min(budget, max(0, int(slot_cap)))
            except (TypeError, ValueError):
                pass
        gold_exclusive = self._gold_slot_exclusive()
        super_uses_normal = super_def is not None and not gold_exclusive  # TSC-12 关闭独占
        prev_traits = snap.get("traits")
        if not isinstance(prev_traits, (list, tuple)):
            prev_traits = []
        prev_neg = snap.get("negatives")
        if not isinstance(prev_neg, (list, tuple)):
            prev_neg = []
        prev_count = len([t for t in prev_traits if isinstance(t, str) and t]) + \
            len([n for n in prev_neg if isinstance(n, str) and n])  # T-4 负面占普通位（累计）
        negatives = self._resolve_negatives(neg_cfg, ctx)  # T-4 负面占普通位
        normal_used = prev_count + len(chosen) + len(negatives)
        if super_uses_normal:
            normal_used += 1
        if normal_used > budget:
            return {"ok": False, "reason": "slot_overflow",
                    "message": f"继承超 {budget} 项", "limit": budget}
        if gold_exclusive and super_def is not None and snap.get("gold_slot"):
            return {"ok": False, "reason": "gold_slot_occupied",
                    "message": "第 4 位金色已占用"}

        # ⑦ group 互斥（INH-10：组内最多 1 项，与已选/批内/已占金色位同组拒绝并提示组名）
        group_holder: Dict[str, str] = {}
        for t in prev_traits:
            if not isinstance(t, str):
                continue
            td = self._find_trait_def(t, ctx, normal_pool) or {"id": t}
            g = td.get("group")
            if isinstance(g, str) and g:
                group_holder[g] = str(td.get("id", t))
        prev_gs = snap.get("gold_slot")
        if isinstance(prev_gs, str) and prev_gs:
            # INH-10 成品共存层面：已占第 4 位金色与普通位同组互斥
            gd = self._find_trait_def(prev_gs, ctx, gold_pool) or {"id": prev_gs}
            g = gd.get("group")
            if isinstance(g, str) and g:
                group_holder[g] = str(gd.get("id", prev_gs))
        all_chosen = list(chosen) + ([super_def] if super_def is not None else [])
        for tdef in all_chosen:
            g = tdef.get("group")
            if isinstance(g, str) and g:
                tid_here = str(tdef.get("id", ""))
                holder = group_holder.get(g)
                if holder is not None and holder != tid_here:
                    # INH-10 组内不同特性互斥；同 id 重复归 repeatable（INH-11）
                    return {"ok": False, "reason": "group_conflict",
                            "message": f"互斥组内最多 1 项：{g}",
                            "group": g, "conflict_with": holder}
                group_holder[g] = tid_here

        # ⑧ repeatable（INH-11：false 不可重复；true 允许重复受叠加规则约束）
        counter: Dict[str, int] = {}
        for t in prev_traits:
            if isinstance(t, str):
                counter[t] = counter.get(t, 0) + 1
        for tdef in all_chosen:
            tid = str(tdef.get("id", ""))
            counter[tid] = counter.get(tid, 0) + 1
        for tdef in all_chosen:
            tid = str(tdef.get("id", ""))
            if not tdef.get("repeatable") and counter.get(tid, 0) > 1:
                return {"ok": False, "reason": "not_repeatable",
                        "message": "该特性不可重复继承"}

        # ⑨ 结果（T-5：独占时超特性进 gold_slot；关闭独占时并入普通 traits）
        selected_ids = [str(t.get("id", "")) for t in chosen]
        if super_uses_normal and super_tid is not None:
            selected_ids.append(super_tid)
        return {
            "ok": True,
            "traits": selected_ids,
            "gold_slot": super_tid if (super_def is not None and gold_exclusive) else None,
            "negatives": negatives,
            "pp_used": pp_used + need,
            "message": "继承成功",
        }

    # ------------------------------------------------------------------
    # 写入快照（INH-08/STO-03：/确认 时随结算写入成品；本方法落快照）
    # ------------------------------------------------------------------
    def apply_to_snapshot(
        self,
        snap: Optional[Mapping[str, Any]],
        traits: Optional[Sequence[Any]],
        *,
        super_trait: Optional[Any] = None,
        negatives: Optional[Sequence[Any]] = None,
        pp_used: Optional[int] = None,
    ) -> dict:
        """所选特性写入会话快照（INH-08/STO-03，version 递增 §7.1 行4）。

        入参：snap（会话快照，只读）；traits=普通特性 id 列表；super_trait=超特性 id
        （独占时落 gold_slot 字段，T-5）；negatives=负面特性 id 列表（T-4）；pp_used=
        select_traits 返回的会话累计 PP used（直接写入避免重复计价）。
        出参：新快照 dict——traits/gold_slot/negatives/pp.used/step/version 更新。
        """
        snap2 = dict(snap) if isinstance(snap, Mapping) else {}
        raw: Mapping[str, Any] = snap if isinstance(snap, Mapping) else snap2
        snap2["traits"] = [str(t) for t in (traits or [])]
        if super_trait is not None and str(super_trait):
            if self._gold_slot_exclusive():
                snap2["gold_slot"] = str(super_trait)
            else:
                # TSC-12 关闭独占：超特性与普通共用位池 → 并入普通 traits 列表
                if str(super_trait) not in snap2["traits"]:
                    snap2["traits"].append(str(super_trait))
                snap2["gold_slot"] = raw.get("gold_slot")
        else:
            snap2["gold_slot"] = raw.get("gold_slot")
        if negatives is not None:
            snap2["negatives"] = [str(n) for n in negatives]
        else:
            snap2["negatives"] = list(raw.get("negatives") or [])
        pp = dict(snap2.get("pp") or {})
        if pp_used is not None:
            try:
                pp["used"] = max(0, int(pp_used))
            except (TypeError, ValueError):
                pass
        snap2["pp"] = pp
        snap2["step"] = STEP_INHERIT
        snap2["version"] = self.snapshot_version(raw) + 1  # §7.1 行4：version 递增
        return snap2

    @staticmethod
    def snapshot_version(snap: Optional[Mapping[str, Any]]) -> int:
        """读快照 version（§7.2 version 幂等锚点；None/非法 → 1；对齐
        AlchemyCore.snapshot_version 口径）。"""
        if not isinstance(snap, Mapping):
            return 1
        v = snap.get("version")
        if isinstance(v, bool) or not isinstance(v, int):
            try:
                v = int(v)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return 1
        return max(1, int(v))

    # ------------------------------------------------------------------
    # 结算复核（INH-10/11，TC-18/19：防会话内绕校验；供批6A 结算引擎调用）
    # ------------------------------------------------------------------
    def check_placement_conflict(
        self,
        snap: Optional[Mapping[str, Any]],
        trait_ids: Optional[Sequence[Any]],
        ctx: Optional[Mapping[str, Any]] = None,
    ) -> dict:
        """结算时 group/repeatable 复核（INH-10/11，TC-18/19）。

        入参：snap（会话快照，含已选 traits/gold_slot/negatives）；trait_ids=待落成品特性
        id 列表（含普通+金色+负面，批6A 结算写入前调用）；ctx（traits def 解析）。
        出参：{ok, conflicts}——conflicts=[{kind:"group", group, traits} |
        {kind:"repeatable", trait_id, count}]；无冲突 {ok:True, conflicts:[]}。
        核心逻辑：聚合快照已选 + 待落全部 id → 同 group >1 个 → 互斥冲突；repeatable=false
          且出现 >1 次 → 重复冲突。
        """
        # 聚合快照已选 + 待落全部 id（不除重——repeatable 计数需保留重复，INH-11）
        ids: List[str] = []
        for t in trait_ids or []:
            if isinstance(t, str) and t:
                ids.append(t)
        raw: Mapping[str, Any] = snap if isinstance(snap, Mapping) else {}
        for t in list(raw.get("traits") or []) + list(raw.get("negatives") or []):
            if isinstance(t, str) and t:
                ids.append(t)
        gs = raw.get("gold_slot")
        if isinstance(gs, str) and gs:
            ids.append(gs)

        counter: Dict[str, int] = {}
        defs: Dict[str, dict] = {}
        for tid in ids:
            counter[tid] = counter.get(tid, 0) + 1
            d = self._find_trait_def(tid, ctx)
            if d is not None:
                defs[tid] = d
        conflicts: List[dict] = []
        groups: Dict[str, List[str]] = {}
        for tid, d in defs.items():
            g = d.get("group")
            if isinstance(g, str) and g:
                groups.setdefault(g, []).append(tid)
        for g, members in groups.items():
            if len(members) > 1:
                conflicts.append({"kind": "group", "group": g, "traits": members})
        for tid, d in defs.items():
            if not d.get("repeatable") and counter.get(tid, 0) > 1:
                conflicts.append({"kind": "repeatable", "trait_id": tid,
                                  "count": counter[tid]})
        if conflicts:
            return {"ok": False, "conflicts": conflicts,
                    "message": "结算校验：互斥组/repeatable 冲突"}
        return {"ok": True, "conflicts": []}
