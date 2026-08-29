"""职业熟练度引擎（M8 批1·路A · 实装版）——等级/熟练经验/SP 解锁/称号/存档校验。

文件名：qbot_rpg/core/proficiency.py
创建时间：2026-08-29
作者：Hermes 子agent-1A
功能描述：ProficiencyEngine 承载职业等级体系全部核心规则（LVL/EXP/SP/TTL 族），
操作对象 = 玩家状态 dict（ctx 玩家表示，就地改写），返回 dict 结果、拒绝场景返回
{ok: False, reason: ...} 不抛异常；纯函数零 IO 零 NoneBot。

依据：
  - docs/细化/细化_2c5a_职业等级与SP.md：LVL-01~09（七阶链/双尺独立/job_rank_levels 成长曲线/
    job_tier_map 区间/每级解锁明细/能量条）、EXP-01~07（三来源经验/倍率/判定顺序 入账→升级→SP）、
    SP-01~08（每级 SP/面板自选解锁/sp_earned+sp_used 双计/作用域限定）、TTL-01~09（王称号图鉴全亮/
    三来源共用 1 佩戴槽/title_state 存档）、§5.1 JSON 样例、§5.3 玩家存档 schema、§七 TC-01~26。
  - docs/m8_contract_核心机制.md §二（职业等级体系 JOB-01~06，proficiency dict 形态）、
    §十 10.3 默认值速查。
  - docs/m8_contract_数据与校验.md §三（proficiency.json 字段表 + 玩家存档保持 dict 形态）。
  - content/test_demo/proficiency.json（alchemy 真实样例：7 级 tier_names、job_rank_levels
    [0,100,300,700,1500,3000,6000]、exp_sources、sp_panel、energy enabled=false、job_tier_map、
    titles）——引擎构造应兼容此形态。
  - 模式参考 core/levelup.py LevelUpEngine（构造器配置注入+缺省默认值兜底；操作玩家状态 dict 就地
    改写；{ok:False, reason:...} 不抛异常；纯函数零 IO 零 NoneBot）、core/inventory.py 同类引擎。

【工程补白 · 显式标注】（定稿/细化未显式定义处，全部按本清单落地）
  1) 操作对象 = 玩家状态 dict（可变，就地改写）；proficiency.<job_id>.{level,exp,sp_earned,sp_used,
     unlocks} 形态对齐细化 §5.3 与 levelup.py _grant_sp（M8 决策 4：保持 dict、Player dataclass
     不加字段）。
  2) 配置注入 = 构造器参数 entries（proficiency.json 条目列表）+ settings dict；缺省默认值兜底：
     tier_names 默认 7 级（见习→王）、job_rank_levels 默认 [0,100,300,700,1500,3000,6000]、
     exp_sources 默认 {craft:1.0, gather:1.0, combat:1.0}、sp_per_level 默认 1、sp_panel 默认 []。
  3) 等级口径 = job_rank_levels 为「累计阈值」（LVL-05），存档 exp 存「当前级内余量」（对齐细化
     §5.3 例：level 4 / exp 850，850 ≥ 800=1500-700 且 < 1500=3000-1500）；升级判定 = 当前级余量 ≥
     相邻阈值差 job_rank_levels[level+1] - job_rank_levels[level]，可连跳多级（LVL-05/EXP-06）。
     该口径精确复现 TC-09：level 1 / 余量 250，入账 350 → 余量 600 跨阈值 300（需 200）→ 精通、
     余量 400 跨阈值 700（需 400）→ 专家，连跳 2 级、SP +2（跨「300→700」两阈值）。
  4) 经验倍率 = 入账 amount × exp_sources[source]（EXP-02），结果向下取整为整数（存档 int 口径）；
     source 未配置/未知 → 默认倍率 1.0（EXP-02 兜底）；amount ≤ 0 → 拒绝 {ok:False,
     reason:"exp_amount_invalid"}。合成经验 = 配方等级×1（EXP-03/CASC-01）由调用方传入 amount，
     引擎只承载「入账+倍率+升级+SP 发放」判定链，不推导具体来源数值。
  5) sp_panel 子字段缺省兜底（§5.2 补白子字段）：cost 默认 1（SP-05）、repeatable 默认 False、
     max_repeat 默认 1（repeatable=false 单次；repeatable=true 未配 → 保守 1，内容包显式配大值放开，
     防无限扣点滥用；TC-15 以 max_repeat=3 显式放 3 次）。name 默认 = id、desc 默认 ""。
  6) job_tier_map 主落点 settings.alchemy.job_tier_map（LVL-06），proficiency 条目可选覆盖（字段
     缺省=settings）；两者都缺 → 默认 见习1-5/正式6-10/精通11-20/专家21-30/大师31-40/宗师41-50/
     王51-99。当前档位称号在 map 中缺失或配方 level 非正整数 → 保守拒绝（不可调合）。
  7) recipe_level_eligible 需要 player 参数（按玩家当前职业等级取档位）；任务清单写
     recipe_level_eligible(job, recipe_level)，语义要求当前档位，签名带 player【工程补白】。
  8) 能量条（LVL-08/09）不落本引擎：m8 契约 ENG-09 规定能量当前值 + energy_last_regen_ts 统一存
     persistent_state 桶（不落 proficiency dict），由装配层/指令层按 settings.alchemy.energy_enabled
     消费；本引擎不实现能量消耗/恢复（不新增定稿外机制行为）。
  9) 王称号授予只做 title_state.owned 落账（TTL-08）；专属配方 / 称号加成等奖励由装配层在
     granted=True 时下发（TTL-07 佩戴不参与授予；本引擎不越权发配方/加成）。
 10) equip_title 支持 title_id=None/"" 取消佩戴（TC-22 取消佩戴 → 前缀渲染为空），替换式 1 槽
     （TTL-05）。
 11) validate_load 返回问题列表（空 = 通过），不变量 sp_used ≤ sp_earned（SP-06）。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；工程补白显式标注；不新增定稿外机制行为。
"""
from __future__ import annotations

from typing import Any, List, Mapping, MutableMapping, Optional, Sequence, Tuple

__all__ = ["ProficiencyEngine"]

# ---------------------------------------------------------------------------
# 缺省默认值（LVL-01/05、EXP-02、SP-01/05，对齐细化 §5.2 字段表默认）
# ---------------------------------------------------------------------------
_DEFAULT_TIER_NAMES: Tuple[str, ...] = ("见习", "正式", "精通", "专家", "大师", "宗师", "王")
_DEFAULT_RANK_LEVELS: Tuple[int, ...] = (0, 100, 300, 700, 1500, 3000, 6000)
_DEFAULT_EXP_SOURCES: Mapping[str, float] = {"craft": 1.0, "gather": 1.0, "combat": 1.0}
_DEFAULT_SP_PER_LEVEL: int = 1
_DEFAULT_JOB_TIER_MAP: Mapping[str, Tuple[int, int]] = {
    "见习": (1, 5), "正式": (6, 10), "精通": (11, 20), "专家": (21, 30),
    "大师": (31, 40), "宗师": (41, 50), "王": (51, 99),
}


class ProficiencyEngine:
    """职业等级 / 熟练经验 / SP 面板 / 称号引擎（细化_2c5a：LVL/EXP/SP/TTL 族）。

    操作对象为玩家状态 dict（ctx 玩家表示），所有改写就地发生；返回 dict 结果，
    拒绝场景返回 {ok: False, reason: ...} 不抛异常；纯函数零 IO 零 NoneBot。
    """

    def __init__(
        self,
        entries: Optional[Sequence[Mapping[str, Any]]] = None,
        settings: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """构造职业熟练度引擎（配置注入，缺省默认值兜底，对齐 levelup.py B-1 模式）。

        入参：
          - entries：proficiency.json 条目列表（细化 §5.1 形态）；None/[] → 全默认值兜底。
          - settings：settings dict；job_tier_map 主落点 settings.alchemy.job_tier_map（LVL-06）。
        """
        self._entries: List[Mapping[str, Any]] = list(entries) if entries else []
        self._settings: Mapping[str, Any] = settings if isinstance(settings, Mapping) else {}

    # ------------------------------------------------------------------
    # 工具：条目查找 / 配置取值（缺省兜底）
    # ------------------------------------------------------------------
    def _entry(self, job_id: str) -> Optional[Mapping[str, Any]]:
        """按职业 ID 查 proficiency 条目（无 → None，调用方走默认值兜底）。"""
        for e in self._entries:
            if e.get("id") == job_id:
                return e
        return None

    def _tier_names(self, job_id: str) -> Tuple[str, ...]:
        """7 级称号名（LVL-01，内容包可改名；长度 ≥2 才采纳，否则默认 7 级）。"""
        e = self._entry(job_id)
        raw = e.get("tier_names") if e else None
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            return tuple(str(x) for x in raw)
        return _DEFAULT_TIER_NAMES

    def _rank_levels(self, job_id: str) -> Tuple[int, ...]:
        """成长曲线累计阈值（LVL-05；长度 ≥2 才采纳，否则默认 [0,100,300,700,1500,3000,6000]）。"""
        e = self._entry(job_id)
        raw = e.get("job_rank_levels") if e else None
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            return tuple(int(x) for x in raw)
        return _DEFAULT_RANK_LEVELS

    def _exp_source_mult(self, job_id: str, source: str) -> float:
        """来源经验倍率（EXP-02，exp_sources 可配；未知来源/未配置 → 默认 1.0）。"""
        e = self._entry(job_id)
        raw = e.get("exp_sources") if e else None
        if isinstance(raw, Mapping):
            try:
                return float(raw.get(source, 1.0))
            except (TypeError, ValueError):
                return 1.0
        return float(_DEFAULT_EXP_SOURCES.get(source, 1.0))

    def _sp_per_level(self, job_id: str) -> int:
        """每级 SP 发放量（SP-01，范围 ≥0，默认 1）。"""
        e = self._entry(job_id)
        raw = e.get("sp_per_level") if e else None
        if raw is not None:
            try:
                return max(0, int(raw))
            except (TypeError, ValueError):
                pass
        return _DEFAULT_SP_PER_LEVEL

    @staticmethod
    def _norm_tier_map(raw: Any) -> Optional[Mapping[str, Tuple[int, int]]]:
        """job_tier_map 归一（LVL-06）：{称号: [lo, hi]} → {(str): (int, int)}；非法项跳过。"""
        if not isinstance(raw, Mapping) or not raw:
            return None
        out: dict = {}
        for k, v in raw.items():
            try:
                lo, hi = int(v[0]), int(v[1])
            except (TypeError, ValueError, IndexError):
                continue
            out[str(k)] = (lo, hi)
        return out or None

    def job_tier_map(self, job_id: str) -> Mapping[str, Tuple[int, int]]:
        """称号→配方等级区间（LVL-06）：主落点 settings.alchemy.job_tier_map，proficiency 条目可选
        覆盖（字段缺省=settings）；两者都缺 → 默认 见习1-5…王51+。"""
        e = self._entry(job_id)
        entry_map = self._norm_tier_map(e.get("job_tier_map")) if e else None
        if entry_map is not None:
            return entry_map
        alchemy = self._settings.get("alchemy") if isinstance(self._settings, Mapping) else None
        if isinstance(alchemy, Mapping):
            settings_map = self._norm_tier_map(alchemy.get("job_tier_map"))
            if settings_map is not None:
                return settings_map
        return dict(_DEFAULT_JOB_TIER_MAP)

    # ------------------------------------------------------------------
    # 工具：玩家状态读写（proficiency / title_state）
    # ------------------------------------------------------------------
    @staticmethod
    def _prof_node(
        player: MutableMapping[str, Any], job_id: str, *, create: bool = False
    ) -> Optional[MutableMapping[str, Any]]:
        """proficiency.<job_id> 节点（§5.3；不存在时 create=True 建默认节点并挂回 player）。"""
        prof = player.get("proficiency")
        if not isinstance(prof, MutableMapping):
            if not create:
                return None
            prof = {}
            player["proficiency"] = prof
        node = prof.get(job_id)
        if not isinstance(node, MutableMapping):
            if not create:
                return None
            node = {"level": 0, "exp": 0, "sp_earned": 0, "sp_used": 0, "unlocks": {}}
            prof[job_id] = node
        return node

    @staticmethod
    def _title_state(
        player: MutableMapping[str, Any], *, create: bool = False
    ) -> Optional[MutableMapping[str, Any]]:
        """title_state 节点（TTL-08；不存在时 create=True 建 {owned, equipped} 并挂回 player）。"""
        ts = player.get("title_state")
        if not isinstance(ts, MutableMapping):
            if not create:
                return None
            ts = {"owned": [], "equipped": None}
            player["title_state"] = ts
        return ts

    @staticmethod
    def _owned_list(ts: MutableMapping[str, Any]) -> List[str]:
        """title_state.owned 归一为可变 list（就地初始化）。"""
        owned = ts.get("owned")
        if not isinstance(owned, list):
            owned = []
            ts["owned"] = owned
        return owned

    @staticmethod
    def _ensure_unlocks(node: MutableMapping[str, Any]) -> MutableMapping[str, int]:
        """unlocks 计数桶归一为可变 dict（就地初始化；写路径用）。"""
        u = node.get("unlocks")
        if not isinstance(u, MutableMapping):
            u = {}
            node["unlocks"] = u
        return u

    # ------------------------------------------------------------------
    # 等级 / 档位（LVL-01/05、EXP-06）
    # ------------------------------------------------------------------
    def tier_index_for_level(self, job_id: str, level: int) -> int:
        """职业档位索引（0~6，与 tier_names 一一对应，LVL-01/05）。level=0 即见习；越界钳制到末档。

        入参：job_id、level（职业等级，0=见习起点）。
        出参：档位索引 int。
        """
        names = self._tier_names(job_id)
        level = max(0, int(level))
        return min(level, len(names) - 1)

    def tier_name(self, job_id: str, level: int) -> str:
        """当前档位称号名（LVL-01：见习→正式→精通→专家→大师→宗师→王，内容包可改名）。

        入参：job_id、level（职业等级）。
        出参：档位称号 str。
        """
        names = self._tier_names(job_id)
        return names[self.tier_index_for_level(job_id, level)]

    def gain_prof_exp(self, player: Any, job_id: str, amount: int, source: str = "craft") -> Any:
        """熟练经验入账 → 升级判定 → SP 发放（EXP-01~07/LVL-05/SP-01，TC-05/08/09/10/11）。

        入参：
          - player：玩家状态 dict（就地改写 proficiency.<job_id> 的 level/exp/sp_earned）。
          - job_id：生活职业 ID（对应 proficiency.json id / jobs.json）。
          - amount：本次熟练值（制作=配方等级×1 等来源口径由调用方传入，EXP-03/CASC-01）。
          - source：来源键 craft/gather/combat（EXP-01/02）；未知来源按默认倍率 1.0。
        核心逻辑（EXP-06 判定链：先入账 → 后升级 → 再发 SP，一次结算内完成）：
          1) 入账：exp += amount × exp_sources[source]（倍率可配，EXP-02；向下取整为整数）。
          2) 升级：while 当前级余量 ≥ 相邻阈值差（job_rank_levels[level+1]-job_rank_levels[level]）
             逐级提升，可连跳多级（LVL-05/EXP-06）。
          3) SP 发放：每升 1 级 + sp_per_level 点入 sp_earned（SP-01，未跨阈值不发放、可累积）。
        出参：{ok, exp_gained, level, tier_from, tier_to, sp_gained, level_ups}；
          拒绝：{ok:False, reason:"invalid_player"|"exp_amount_invalid"}。
        """
        if not isinstance(player, MutableMapping):
            return {"ok": False, "reason": "invalid_player"}
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            return {"ok": False, "reason": "exp_amount_invalid"}

        node = self._prof_node(player, job_id, create=True)
        assert node is not None  # create=True 必建
        mult = self._exp_source_mult(job_id, source)
        raw_gain = int(amount * mult)  # 【工程补白 4】倍率结果向下取整（存档 int 口径）
        old_level = max(0, int(node.get("level", 0)))
        exp = max(0, int(node.get("exp", 0))) + raw_gain  # EXP-06 ① 先入账
        ranks = self._rank_levels(job_id)
        level = old_level
        max_level = len(ranks) - 1
        level_ups = 0
        sp_gained = 0
        sp_per = self._sp_per_level(job_id)
        while level < max_level:  # EXP-06 ② 升级判定（可连跳）③ 逐级发 SP
            cost = ranks[level + 1] - ranks[level]
            if cost <= 0:
                break
            if exp < cost:
                break
            exp -= cost
            level += 1
            level_ups += 1
            sp_gained += sp_per  # SP-01：每级 1 点 × 级数（sp_per_level 可配）

        node["level"] = level
        node["exp"] = exp
        node["sp_earned"] = max(0, int(node.get("sp_earned", 0))) + sp_gained
        return {
            "ok": True,
            "exp_gained": raw_gain,
            "level": level,
            "tier_from": self.tier_name(job_id, old_level),
            "tier_to": self.tier_name(job_id, level),
            "sp_gained": sp_gained,
            "level_ups": level_ups,
        }

    def recipe_level_eligible(self, player: Any, job_id: str, recipe_level: Any) -> bool:
        """配方等级区间准入（LVL-06/TC-03）：配方 level 落在当前档位区间才可调合/合成。

        入参：player（读当前职业等级取档位）、job_id、recipe_level（配方等级）。
        出参：bool。档位称号在 map 中缺失 / recipe_level 非正整数 → 保守拒绝 False。
        """
        if not isinstance(player, MutableMapping):
            return False
        if isinstance(recipe_level, bool) or not isinstance(recipe_level, int) or recipe_level <= 0:
            return False
        node = self._prof_node(player, job_id, create=False)
        level = 0 if node is None else max(0, int(node.get("level", 0)))
        tier = self.tier_name(job_id, level)
        bounds = self.job_tier_map(job_id).get(tier)
        if bounds is None:
            return False  # 【工程补白 6】当前档位未配置区间 → 保守拒绝
        lo, hi = bounds
        return lo <= recipe_level <= hi

    # ------------------------------------------------------------------
    # SP 面板（SP-01~08）
    # ------------------------------------------------------------------
    def sp_available(self, player: Any, job_id: str) -> int:
        """可用 SP = sp_earned - sp_used（SP-06 双计，防重复扣点）。

        入参：player、job_id。出参：可用 SP int（≥0）。
        """
        if not isinstance(player, MutableMapping):
            return 0
        node = self._prof_node(player, job_id, create=False)
        if node is None:
            return 0
        earned = max(0, int(node.get("sp_earned", 0)))
        used = max(0, int(node.get("sp_used", 0)))
        return max(0, earned - used)

    def sp_panel_defs(self, job_id: str) -> List[dict]:
        """SP 面板解锁项定义列表（SP-03/05，§5.2 补白子字段）。

        入参：job_id。出参：归一化 [{id, name, cost, repeatable, max_repeat, desc}]；
          cost 默认 1（SP-05）、repeatable 默认 False、max_repeat 默认 1、name 默认 id、
          desc 默认 ""（【工程补白 5】）；未配置职业/空面板 → []。
        """
        e = self._entry(job_id)
        raw = e.get("sp_panel") if e else None
        out: List[dict] = []
        if not isinstance(raw, (list, tuple)):
            return out
        for item in raw:
            if not isinstance(item, Mapping) or not item.get("id"):
                continue
            pid = str(item["id"])
            try:
                cost = max(1, int(item.get("cost", 1)))
            except (TypeError, ValueError):
                cost = 1
            repeatable = bool(item.get("repeatable", False))
            try:
                max_repeat = max(1, int(item.get("max_repeat", 1)))
            except (TypeError, ValueError):
                max_repeat = 1
            out.append({
                "id": pid,
                "name": str(item.get("name") or pid),
                "cost": cost,
                "repeatable": repeatable,
                "max_repeat": max_repeat,
                "desc": str(item.get("desc") or ""),
            })
        return out

    def unlock_item(self, player: Any, job_id: str, panel_id: str) -> Any:
        """SP 面板自选解锁（SP-02/04/05，TC-13/14/15/16/18）。

        入参：player、job_id、panel_id（sp_panel 项 id）。
        校验链（SP-05）：
          - 面板项不存在 → {ok:False, reason:"panel_not_found"}
          - 可用 SP < cost → {ok:False, reason:"sp_insufficient"}（TC-16）
          - repeatable=false 已购 → {ok:False, reason:"not_repeatable"}
          - repeatable=true 达 max_repeat 上限 → {ok:False, reason:"max_repeat_reached"}（TC-15）
        通过：sp_used += cost、unlocks[panel_id] += 1（SP-06 双计），即时生效（SP-04）。
        出参：{ok, sp_used_delta, unlock_count, panel_id, panel_name}；拒绝 reason 见上。
        """
        if not isinstance(player, MutableMapping):
            return {"ok": False, "reason": "invalid_player"}
        if not isinstance(panel_id, str) or not panel_id:
            return {"ok": False, "reason": "panel_not_found"}
        defs = {d["id"]: d for d in self.sp_panel_defs(job_id)}
        panel = defs.get(panel_id)
        if panel is None:
            return {"ok": False, "reason": "panel_not_found"}
        node = self._prof_node(player, job_id, create=True)
        assert node is not None  # create=True 必建
        count = self.unlock_count(player, job_id, panel_id)
        if not panel["repeatable"] and count > 0:
            return {"ok": False, "reason": "not_repeatable"}
        if panel["repeatable"] and count >= panel["max_repeat"]:
            return {"ok": False, "reason": "max_repeat_reached"}
        earned = max(0, int(node.get("sp_earned", 0)))
        used = max(0, int(node.get("sp_used", 0)))
        if earned - used < panel["cost"]:
            return {"ok": False, "reason": "sp_insufficient"}
        node["sp_used"] = used + panel["cost"]
        unlocks = self._ensure_unlocks(node)
        unlocks[panel_id] = count + 1
        return {
            "ok": True,
            "sp_used_delta": panel["cost"],
            "unlock_count": count + 1,
            "panel_id": panel_id,
            "panel_name": panel["name"],
        }

    def unlock_count(self, player: Any, job_id: str, panel_id: str) -> int:
        """已解锁次数（SP-03，供其它系统消费：品质上限/投入次数/特性位/采集量/连锁上限/复制·进化·挑战）。

        入参：player、job_id、panel_id。出参：解锁次数 int（未购 = 0，纯读不改写）。
        """
        if not isinstance(player, MutableMapping):
            return 0
        node = self._prof_node(player, job_id, create=False)
        if node is None:
            return 0
        u = node.get("unlocks")
        if not isinstance(u, MutableMapping):
            return 0
        try:
            return max(0, int(u.get(panel_id, 0)))
        except (TypeError, ValueError):
            return 0

    # ------------------------------------------------------------------
    # 王称号 / 佩戴（TTL-01~08）
    # ------------------------------------------------------------------
    def grant_king_title(self, player: Any, job_id: str, *, codex_all_lit: bool = False) -> Any:
        """王称号授予（TTL-01/03，TC-19/20/21）。

        入参：player、job_id、codex_all_lit（该职业图鉴是否全点亮，与等级区间解耦，TTL-01）。
        条件：codex_all_lit=True 且 title_state.owned 尚无该 job。
        通过：title 条目自动生成 id=职业 ID（TTL-03），加入 title_state.owned 可佩戴列表（TTL-08）。
        出参：{ok, granted, title_id}；图鉴未全亮 → {ok:False, reason:"codex_incomplete"}；
          已拥有 → 幂等 {ok:True, granted:False, title_id}。
        """
        if not isinstance(player, MutableMapping):
            return {"ok": False, "reason": "invalid_player"}
        if not codex_all_lit:
            return {"ok": False, "reason": "codex_incomplete"}
        ts = self._title_state(player, create=True)
        assert ts is not None  # create=True 必建
        owned = self._owned_list(ts)
        if job_id in owned:
            return {"ok": True, "granted": False, "title_id": job_id}
        owned.append(job_id)
        return {"ok": True, "granted": True, "title_id": job_id}

    def owned_titles(self, player: Any) -> List[str]:
        """已拥有称号列表（TTL-08，title_state.owned；纯读不改写）。

        入参：player。出参：称号 id 列表（未建档 → []）。
        """
        if not isinstance(player, MutableMapping):
            return []
        ts = self._title_state(player, create=False)
        if ts is None:
            return []
        owned = ts.get("owned")
        if not isinstance(owned, list):
            return []
        return [str(t) for t in owned]

    def equip_title(self, player: Any, title_id: Any) -> Any:
        """称号佩戴（TTL-05/TC-22）：1 槽替换式；title_id=None/"" 取消佩戴。

        入参：player、title_id（已拥有称号 id；None/"" 取消佩戴）。
        校验：title_id 非空时必须在 owned 列表 → 否则 {ok:False, reason:"title_not_owned"}。
        通过：title_state.equipped = title_id（替换旧值）。
        出参：{ok, equipped, replaced}。
        """
        if not isinstance(player, MutableMapping):
            return {"ok": False, "reason": "invalid_player"}
        ts = self._title_state(player, create=True)
        assert ts is not None  # create=True 必建
        if title_id is not None and str(title_id):
            tid = str(title_id)
            if tid not in self._owned_list(ts):
                return {"ok": False, "reason": "title_not_owned"}
        else:
            tid = None
        old = ts.get("equipped")
        ts["equipped"] = tid
        return {"ok": True, "equipped": tid, "replaced": old}

    # ------------------------------------------------------------------
    # 存档校验（SP-06/TC-26）
    # ------------------------------------------------------------------
    def validate_load(self, player: Any) -> List[dict]:
        """存档校验（SP-06/TC-26）：不变量 sp_used ≤ sp_earned，返回问题列表（空 = 通过）。

        入参：player。出参：[{job_id, sp_earned, sp_used}, ...] 仅含超支项。
        """
        if not isinstance(player, MutableMapping):
            return []
        prof = player.get("proficiency")
        if not isinstance(prof, MutableMapping):
            return []
        problems: List[dict] = []
        for job_id, node in prof.items():
            if not isinstance(node, MutableMapping):
                continue
            earned = max(0, int(node.get("sp_earned", 0)))
            used = max(0, int(node.get("sp_used", 0)))
            if used > earned:
                problems.append({"job_id": str(job_id), "sp_earned": earned, "sp_used": used})
        return problems
