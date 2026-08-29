"""战斗即时调合引擎（M8 批9·路A · qbot_rpg/core/alchemy_battle.py）——BattleAlchemyEngine。

文件：qbot_rpg/core/alchemy_battle.py
创建：2026-08-29
作者：Hermes 子agent（批9 路A；并发同仓：仅新建本文件 + tests/unit/test_alchemy_battle.py；
      兄弟路 B 在改 commands/alchemy_commands.py（/即时调合 指令壳），本文件零 import 之，
      只读勿探查）

功能描述：BattleAlchemyEngine —— /即时调合 <配方>（第 3 层 · 战斗即时调合）核心引擎
  （纯逻辑零 IO 零 NoneBot，构造器配置注入 + 缺省默认值兜底）。承载：
  ① 守卫 instant_eligible（GU-50~52/54：战斗中/大师/能量/限次）→
  ② 携带素材 carry_ok（GU-53：配方所需素材在战斗携带素材内，不足全拒+差异，ATO-01）→
  ③ 一步出结果 resolve（BA-07/08/10：材料/宝石原子扣减 → 产出实例 ItemInstance 形态 →
     auto_use 默认当场自动使用走注入 use_fn（战斗道具行动入口 _resolve_item_action 鸭子，
     BA-07）或入包；限次幂等衔接 battle_alchemy_used）→
  ④ 强度公式 intensity（BA-10：技能×(1+0.4×冷却数)，settings 战斗道具.强度公式 可配）→
  ⑤ 冷却 cooldown_of（BA-06：吃冷却对齐 /道具 冷却配置，炸弹 3 回合冷却）→
  ⑥ 能量 consume_energy（GU-52/R-08：energy_enabled=true 时 EnergyBar.consume(1)，关则直通）。

依据：
  - docs/m8_contract_战斗资源.md §三（BA-01~11；BA-02 battle_alchemy_used 落点战斗快照顶层键
    中断不清零战斗结束清零 / BA-06 吃冷却+消耗携带素材+能量 / BA-07 auto_use 可配默认当场
    自动使用走 _resolve_item_action / BA-08 一步出结果 材料宝石原子扣减→ItemInstance→
    auto_use 结算或入包 / BA-10 道具强度公式可配；IF-B01~05 战斗接口签名）
  - docs/m8_contract_指令契约.md §16（/即时调合 GU-50~54 / F-17 / M-17 限次拒绝模板）、§三
    （MUT-03 战斗即时调合豁免互斥——本引擎不申请会话槽、不进状态机）、§九（ATO-01 全量
    原子校验：全量满足才执行否则全拒+逐项差异）
  - 已落地：core/energy_bar.py（EnergyBar.consume，批4·路2）、core/proficiency.py
    （ProficiencyEngine.tier_index_for_level/tier_name，批1）、core/alchemy_core.py
    （ALCHEMY_JOB_ID，批4A）、core/inventory.py（POTION_USE_COUNTS_KEY 计数落点模式
    L56/L168，BA-03 对齐）
  - 模式参考：core/synthesis.py（ctx hook：count_item/remove_item/add_item/currencies +
    快照-回滚原子性，批2）、core/alchemy_settle.py（SettleEngine 构造注入+纯逻辑，批5·路2）

【工程补白 · 显式标注】（定稿/契约未给口径处，本引擎最小必要推导，不得新增定稿外行为）：
  E-A1  battle_alchemy_used 落点：BA-02 要求挂战斗快照 to_snapshot() 返回 dict 顶层键
       （与 ai_state/combo_state 同层）。本引擎提供 read_used(battle_snapshot) /
       write_used(battle_snapshot, count) 两个落点读写 helper（键名
       BATTLE_ALCHEMY_USED_KEY="battle_alchemy_used"）；resolve 接收当前计数 kwarg
       （None → 回落 ctx["battle_snapshot"] 经 read_used 读取），成功时返回新计数，且当
       ctx["battle_snapshot"] 为可变 dict 时直接 write_used 回写。中断恢复不清零、战斗结束
       清零由战斗层负责（BA-02/BA-03 对齐 potion_use_counts 口径：引擎只提供落点，生命周期
       清零归战斗入口）。
  E-A2  携带素材范围：GU-53「配方所需素材在战斗携带素材内」。本引擎只认 ctx["count_item"] /
       remove_item hook——「战斗携带素材」与「背包」的区分由壳层注入的 hook 承载（战斗层把
       count_item/remove_item 绑到战斗携带素材容器而非背包）；引擎不区分二者、不读背包。
  E-A3  产出品质/特性形态（BA-08 ItemInstance）：即时调合无投料链（BA-01 无投料/继承/确认
       链），产出 quality/traits 取产出物品 def 自身（items.json quality/traits 字段；
       缺省 quality=None、traits=[]），不聚合材料品质（无材料品质输入）。
  E-A4  宝石扣减（BA-08「材料/宝石原子扣减」）：配方 cost.gem > 0 时校验并扣减
       ctx["currencies"]["gem"]（全量校验、全拒+差异，ATO-01）；金币 cost.coins 不扣
       （F-17 仅「素材+能量 1 格」+ 宝石口径，即时调合不消耗金币——定稿未言，保守不扣）。
  E-A5  冷却读取顺序（BA-06）：recipe_def.cooldown > recipe_def.output.cooldown >
       默认 3（炸弹 3 回合冷却）。物品级冷却配置（/道具 冷却配置）由壳层解析 items def 后
       并入配方 cooldown 字段，或经 resolve(cooldown=...) 显式传入——本签名 cooldown_of
       (recipe_def) 无 ctx，不从 items 注册表解析。
  E-A6  强度公式基准（BA-10「技能×(1+0.4×冷却数)」）：「技能」基准值取 recipe_def.skill
       （缺省 1.0）；系数 settings 战斗道具.强度公式（数字直取 / Mapping 取 coef/系数 键）
       缺省 0.4。强度为 float，参与伤害链结算由战斗层消费。
  E-A7  auto_use=true 但未注入 use_fn / use_fn 失败（BA-07）：产出已入包不丢（add_item 已
       成功），auto_used=False、outcome=None，按入包口径返回——防御战斗层未接线时不吞产出。
  E-A8  原子性（ATO-01/BA-08）：快照-回滚覆盖 ctx["currencies"]/ctx["inventory"]/玩家
       persistent_state（能量字段）就地容器（对齐 synthesis 工程补白 7）；hook 背靠外部
       存储时事务由壳层保证。
  E-A9  大师判定（GU-51）：职业档位索引 ≥ 大师档位索引。档位序取自 prof.tier_name 逐级探测
       （0..6），大师档位名 settings 战斗即时调合.master_tier 可配（缺省「大师」）；未命中
       → 默认索引 4（见习0 正式1 精通2 专家3 大师4 宗师5 王6，对齐 energy_bar 档位序）。

铁律：零 NoneBot import；纯函数（同刻同参必同值，ctx 只读注册表 + 经 hook 就地改写）；不抛
      异常（防御降级返回 dict）；每条规则注释标注出处（BA/GU/F/ATO 编号 + 定稿/契约行号）；
      不得新增定稿外机制行为；装饰性 emoji 禁用（消息模板纯文本，BA-09 一行渲染归批9B）。
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Tuple, cast

from qbot_rpg.core.alchemy_core import ALCHEMY_JOB_ID
from qbot_rpg.core.energy_bar import EnergyBar
from qbot_rpg.core.proficiency import ProficiencyEngine

__all__ = [
    "BATTLE_ALCHEMY_USED_KEY",
    "DEFAULT_AUTO_USE",
    "DEFAULT_BOMB_COOLDOWN",
    "DEFAULT_INTENSITY_COEF",
    "DEFAULT_MASTER_TIER",
    "DEFAULT_MASTER_TIER_INDEX",
    "DEFAULT_PER_BATTLE_LIMIT",
    "DEFAULT_TIER_NAMES",
    "GEM_KEY",
    "BattleAlchemyEngine",
]

# ---------------------------------------------------------------------------
# 常量（BA-02/06/07/10、GU-51/54）
# ---------------------------------------------------------------------------
# BA-02/BA-03：battle_alchemy_used 落战斗快照顶层键（对齐 potion_use_counts 计数落点模式）
BATTLE_ALCHEMY_USED_KEY: str = "battle_alchemy_used"
# BA-02/BA-06/GU-54：per_battle_limit 默认 1（settings 战斗即时调合.per_battle_limit 可配）
DEFAULT_PER_BATTLE_LIMIT: int = 1
# BA-07：auto_use 默认 true（当场自动使用；settings 战斗即时调合.auto_use 可配）
DEFAULT_AUTO_USE: bool = True
# BA-06：炸弹 3 回合冷却（对齐 /道具 冷却配置）
DEFAULT_BOMB_COOLDOWN: int = 3
# BA-10：道具强度公式 技能×(1+0.4×冷却数)（settings 战斗道具.强度公式 可配）
DEFAULT_INTENSITY_COEF: float = 0.4
# GU-51：大师档位名（settings 战斗即时调合.master_tier 可配）
DEFAULT_MASTER_TIER: str = "大师"
# GU-51/E-A9：默认档位序（对齐 energy_bar DEFAULT_TIER_NAMES 七档序）
DEFAULT_TIER_NAMES: Tuple[str, ...] = ("见习", "正式", "精通", "专家", "大师", "宗师", "王")
# GU-51/E-A9：大师默认档位索引（0 基：见习0 正式1 精通2 专家3 大师4 宗师5 王6）
DEFAULT_MASTER_TIER_INDEX: int = 4
# BA-08/E-A4：宝石货币键（ctx["currencies"] 就地扣减）
GEM_KEY: str = "gem"
# E-A8：快照-回滚覆盖的可变 ctx 子结构（对齐 synthesis 工程补白 7 原子防双扣口径）
_SNAP_KEYS: tuple = ("currencies", "inventory")


class BattleAlchemyEngine:
    """战斗即时调合引擎（/即时调合 F-17，纯逻辑零 IO 零 NoneBot）。

    构造器配置注入（settings + prof 熟练引擎）+ 缺省默认值兜底（对齐 quality.py /
    alchemy_settle.py 模式）。操作对象 = ctx（items/recipe 注册表 + count_item/remove_item/
    add_item hook + currencies + player + battle_snapshot），背包/货币/能量经 hook 就地改写，
    存储与事务由壳层完成。每条规则注释标注出处（BA/GU/F/ATO 编号）。
    """

    def __init__(
        self,
        settings: Optional[Mapping[str, Any]] = None,
        prof: Optional[ProficiencyEngine] = None,
    ) -> None:
        """构造战斗即时调合引擎（配置注入 + 缺省默认值兜底）。

        入参：
          - settings：settings dict（读 alchemy.战斗即时调合 / alchemy.战斗道具 /
            alchemy.energy_enabled 等）；None/缺省 → 默认值兜底。
          - prof：ProficiencyEngine 实例（可选注入，用于大师档位判定；缺省兜底默认引擎）。
        """
        self._settings: Mapping[str, Any] = settings if isinstance(settings, Mapping) else {}
        alchemy = self._settings.get("alchemy")
        self._alchemy: Mapping[str, Any] = alchemy if isinstance(alchemy, Mapping) else {}
        ba = self._alchemy.get("战斗即时调合")
        self._ba_cfg: Mapping[str, Any] = ba if isinstance(ba, Mapping) else {}
        it = self._alchemy.get("战斗道具")
        self._item_cfg: Mapping[str, Any] = it if isinstance(it, Mapping) else {}
        self._prof: ProficiencyEngine = (
            prof if prof is not None else ProficiencyEngine()
        )
        # GU-52/R-08：能量引擎（energy_enabled 默认关，关时 consume 直通，ENG-01/ENG-10）
        self._energy = EnergyBar(settings=settings)

    # ------------------------------------------------------------------
    # 配置读取（缺省默认值兜底，防御非法配置）
    # ------------------------------------------------------------------
    def _per_battle_limit(self) -> int:
        """限次（BA-02/GU-54）：settings 战斗即时调合.per_battle_limit，默认 1。"""
        v = self._ba_cfg.get("per_battle_limit", DEFAULT_PER_BATTLE_LIMIT)
        if isinstance(v, bool) or v is None:
            return DEFAULT_PER_BATTLE_LIMIT
        try:
            n = int(v)
        except (TypeError, ValueError):
            return DEFAULT_PER_BATTLE_LIMIT
        return n if n > 0 else DEFAULT_PER_BATTLE_LIMIT

    def _auto_use_default(self) -> bool:
        """auto_use 默认（BA-07）：settings 战斗即时调合.auto_use，默认 true。"""
        v = self._ba_cfg.get("auto_use", DEFAULT_AUTO_USE)
        return bool(v)

    def _master_tier_name(self) -> str:
        """大师档位名（GU-51/E-A9）：settings 战斗即时调合.master_tier，默认「大师」。"""
        v = self._ba_cfg.get("master_tier", DEFAULT_MASTER_TIER)
        return str(v) if v else DEFAULT_MASTER_TIER

    def _intensity_coef(self) -> float:
        """强度公式系数（BA-10/E-A6）：settings 战斗道具.强度公式，默认 0.4。"""
        v = self._item_cfg.get("强度公式")
        if isinstance(v, Mapping):
            v = v.get("coef", v.get("系数"))
        if isinstance(v, bool) or v is None:
            return DEFAULT_INTENSITY_COEF
        try:
            f = float(v)
        except (TypeError, ValueError):
            return DEFAULT_INTENSITY_COEF
        return f if f >= 0 else DEFAULT_INTENSITY_COEF

    def energy_enabled(self) -> bool:
        """能量条是否启用（GU-52/R-08）：settings.alchemy.energy_enabled，默认关。"""
        return self._energy.enabled()

    # ------------------------------------------------------------------
    # 冷却 / 强度（BA-06 / BA-10）
    # ------------------------------------------------------------------
    @staticmethod
    def cooldown_of(recipe_def: Any) -> int:
        """冷却回合数（BA-06/E-A5）：配方 cooldown > 配方 output.cooldown > 默认 3。

        入参：recipe_def（配方 def，可带 cooldown 字段或 output.cooldown）。
        出参：冷却回合数 int（非负；非法/缺失 → 默认 3 炸弹冷却）。
        核心：对齐 /道具 冷却配置——物品级冷却由壳层解析 items def 后并入配方 cooldown 或
              经 resolve(cooldown=...) 显式传入（本签名无 ctx，不从 items 注册表解析）。
        """
        if not isinstance(recipe_def, Mapping):
            return DEFAULT_BOMB_COOLDOWN
        raw = recipe_def.get("cooldown")
        if raw is None:
            out = recipe_def.get("output")
            if isinstance(out, Mapping):
                raw = out.get("cooldown")
        if isinstance(raw, bool) or raw is None:
            return DEFAULT_BOMB_COOLDOWN
        try:
            n = int(raw)
        except (TypeError, ValueError):
            return DEFAULT_BOMB_COOLDOWN
        return n if n >= 0 else DEFAULT_BOMB_COOLDOWN

    def intensity(self, recipe_def: Any, *, cooldown: Any) -> float:
        """道具强度公式（BA-10/E-A6）：强度 = 技能 × (1 + 系数 × 冷却数)。

        入参：recipe_def（配方 def，skill 字段为「技能」基准值）；cooldown 冷却回合数。
        出参：强度 float（技能缺省 1.0；系数 settings 战斗道具.强度公式，缺省 0.4）。
        核心：技能基准缺省 1.0，强度参与伤害链结算由战斗层消费。
        """
        if not isinstance(recipe_def, Mapping):
            return 0.0
        base = 1.0
        for key in ("skill", "power"):
            v = recipe_def.get(key)
            if v is None or isinstance(v, bool):
                continue
            try:
                base = float(v)
                break
            except (TypeError, ValueError):
                continue
        try:
            cd = max(0, int(cooldown))
        except (TypeError, ValueError):
            cd = 0
        return base * (1.0 + self._intensity_coef() * float(cd))

    # ------------------------------------------------------------------
    # 落点 helper（BA-02/BA-03：battle_alchemy_used 顶层键读写，E-A1）
    # ------------------------------------------------------------------
    @staticmethod
    def read_used(battle_snapshot: Any) -> int:
        """读取 battle_alchemy_used（BA-02）：战斗快照 dict 顶层键，缺失 → 0。"""
        if not isinstance(battle_snapshot, Mapping):
            return 0
        return BattleAlchemyEngine._norm_used(battle_snapshot.get(BATTLE_ALCHEMY_USED_KEY))

    @staticmethod
    def write_used(battle_snapshot: Any, count: Any) -> None:
        """写入 battle_alchemy_used（BA-02）：挂战斗快照 dict 顶层键（非可变 dict 忽略）。

        中断恢复不清零、战斗结束清零由战斗层负责（BA-02/BA-03 对齐 potion_use_counts 口径）。
        """
        if not isinstance(battle_snapshot, MutableMapping):
            return
        battle_snapshot[BATTLE_ALCHEMY_USED_KEY] = BattleAlchemyEngine._norm_used(count)

    # ------------------------------------------------------------------
    # 守卫（GU-50~52/54）
    # ------------------------------------------------------------------
    def instant_eligible(
        self,
        player: Any,
        job_id: Optional[str] = None,
        *,
        in_battle: bool,
        battle_alchemy_used: Any,
    ) -> dict:
        """前置守卫（GU-50~52/54，按 GU 顺序判定）：{ok} 或 {ok:False, reason}。

        入参：player 玩家状态 dict；job_id 职业 id（缺省炼金 ALCHEMY_JOB_ID）；in_battle
              是否战斗中（GU-50）；battle_alchemy_used 本场已用次数（GU-54）。
        出参：{ok:True, battle_alchemy_used, per_battle_limit}；
              拒绝：{ok:False, reason:'not_in_battle'|'tier_too_low'|'energy'|'already_used',
              message}。
        核心逻辑（GU 顺序）：GU-50 战斗中 → GU-51 炼金职业 ≥ 大师 → GU-52 能量 ≥1 格
              （R-08 可配，关闭直通）→ GU-54 battle_alchemy_used < per_battle_limit。
        """
        job_id = job_id or ALCHEMY_JOB_ID
        # GU-50 战斗中（战斗会话上下文内）
        if not in_battle:
            return {"ok": False, "reason": "not_in_battle",
                    "message": "仅战斗中可使用 /即时调合 <配方>"}
        # GU-51 炼金职业 ≥ 大师（E-A9：档位索引 ≥ 大师档位索引）
        if not self._master_ok(player, job_id):
            return {"ok": False, "reason": "tier_too_low",
                    "message": "炼金职业需达到大师方可即时调合"}
        # GU-52 能量 ≥1 格（R-08 默认关；开启时才校验）
        if self.energy_enabled():
            if not isinstance(player, Mapping) or self._energy.current_of(player) < 1:
                return {"ok": False, "reason": "energy", "message": "能量不足，无法即时调合"}
        # GU-54 battle_alchemy_used < per_battle_limit（限 1 次/场；第 2 次拒绝）
        used = self._norm_used(battle_alchemy_used)
        if used >= self._per_battle_limit():
            return {"ok": False, "reason": "already_used",
                    "message": "本场战斗已使用过即时调合（限 1 次/场）"}
        return {"ok": True, "battle_alchemy_used": used,
                "per_battle_limit": self._per_battle_limit()}

    def _master_ok(self, player: Any, job_id: str) -> bool:
        """大师判定（GU-51/E-A9）：职业档位索引 ≥ 大师档位索引。"""
        if not isinstance(player, Mapping):
            return False
        level = self._player_level(player, job_id)
        try:
            idx = int(self._prof.tier_index_for_level(job_id, level))
        except Exception:
            idx = 0
        return idx >= self._master_index(job_id)

    def _master_index(self, job_id: str) -> int:
        """大师档位索引（E-A9）：档位名列表命中可配大师名；未命中 → 默认 4。"""
        names = self._tier_names_of(job_id)
        master = self._master_tier_name()
        if master in names:
            return names.index(master)
        return DEFAULT_MASTER_TIER_INDEX

    def _tier_names_of(self, job_id: str) -> List[str]:
        """档位名列表（E-A9）：prof.tier_name 逐级探测 0..6（重名去重）；缺省七档序。"""
        names: List[str] = []
        seen: set = set()
        for lv in range(0, 8):
            try:
                n = str(self._prof.tier_name(job_id, lv))
            except Exception:
                continue
            if n not in seen:
                seen.add(n)
                names.append(n)
        return names if names else list(DEFAULT_TIER_NAMES)

    @staticmethod
    def _player_level(player: Any, job_id: str) -> int:
        """玩家职业等级（proficiency.<job_id>.level；缺失/非法 → 0）。"""
        if not isinstance(player, Mapping):
            return 0
        prof = player.get("proficiency")
        if not isinstance(prof, Mapping):
            return 0
        node = prof.get(job_id)
        if not isinstance(node, Mapping):
            return 0
        lv = node.get("level")
        if isinstance(lv, bool) or lv is None:
            return 0
        try:
            return max(0, int(lv))
        except (TypeError, ValueError):
            return 0

    # ------------------------------------------------------------------
    # 携带素材（GU-53）
    # ------------------------------------------------------------------
    def carry_ok(self, ctx: Any, recipe_def: Any) -> dict:
        """携带素材校验（GU-53/ATO-01）：配方所需素材在战斗携带素材内，不足全拒+差异。

        入参：ctx（count_item hook 承载「战斗携带素材」范围，E-A2）；recipe_def 配方 def。
        出参：{ok:True, materials:[{item_id,count}]} 或 {ok:False, reason:
              'materials_insufficient'|'invalid_ctx'|'recipe_invalid', message, shortfall:
              [{item_id,name,need,have,diff}]}。
        核心：逐材料 need vs have；任一不足 → 全拒（严禁部分执行，ATO-01）+ 差异清单。
        """
        if not isinstance(ctx, Mapping):
            return {"ok": False, "reason": "invalid_ctx", "message": "上下文非法"}
        if not isinstance(recipe_def, Mapping):
            return {"ok": False, "reason": "recipe_invalid", "message": "配方非法"}
        needs = self._materials(recipe_def)
        shortfall: List[dict] = []
        for rec in needs:
            have = self._count_item(ctx, rec["item_id"])
            if have < rec["count"]:
                shortfall.append({
                    "item_id": rec["item_id"],
                    "name": self._name_of(ctx, rec["item_id"]),
                    "need": rec["count"],
                    "have": have,
                    "diff": rec["count"] - have,
                })
        if shortfall:
            return {"ok": False, "reason": "materials_insufficient",
                    "message": "携带素材不足，无法即时调合",
                    "shortfall": shortfall}
        return {"ok": True, "materials": needs}

    # ------------------------------------------------------------------
    # 一步出结果（BA-07/08/10）
    # ------------------------------------------------------------------
    def resolve(
        self,
        ctx: Any,
        recipe_def: Any,
        *,
        battle_alchemy_used: Any,
        auto_use: Optional[bool] = None,
        cooldown: Any = 0,
        use_fn: Any = None,
    ) -> dict:
        """一步出结果（BA-08/F-17）：原子扣减 → 产出实例 → auto_use 结算或入包。

        入参：
          - ctx：上下文（items/recipe 注册表 + count_item/remove_item/add_item hook +
            currencies + player + battle_snapshot，就地改写）。
          - recipe_def：配方 def。
          - battle_alchemy_used：本场已用次数（GU-54 幂等衔接；None → 回落
            ctx["battle_snapshot"] 经 read_used 读取，E-A1）。
          - auto_use：当场自动使用开关（None → settings 战斗即时调合.auto_use，默认 true，
            BA-07）。
          - cooldown：本次产出冷却回合数（0/None → cooldown_of(recipe_def) 兜底，BA-06）。
          - use_fn：道具行动入口回调 use_fn(item_id, count, produced)（战斗层注入
            _resolve_item_action 鸭子，BA-07；返回 outcome 或 None）。
        出参：
          - 成功：{ok:True, message, produced:{item_id,name,count,quality,tier,traits,
            effects}, auto_use, auto_used, outcome, battle_alchemy_used:新计数, cooldown,
            intensity}。
          - 拒绝：{ok:False, reason, message}；已用/素材不足/能量不足/扣减失败/入包失败。
        核心逻辑（管线顺序）：GU-54 限次防御拦截 → auto_use/冷却/强度解析 → 全量原子校验
          （材料+宝石，ATO-01）→ 快照 → 能量消耗（GU-52）→ 材料/宝石原子扣减（BA-08）→
          产出实例构造（ItemInstance 形态，E-A3）→ auto_use 结算或入包（BA-07，E-A7）→
          计数自增并回写（E-A1）。
        """
        if not isinstance(ctx, Mapping):
            return {"ok": False, "reason": "invalid_ctx", "message": "上下文非法"}
        if not isinstance(recipe_def, Mapping):
            return {"ok": False, "reason": "recipe_invalid", "message": "配方非法"}
        # ctx 为可变容器（回滚/扣减就地改写），经 isinstance 收窄后显式 cast（对齐 mypy 收窄）
        ctx_mut = cast(MutableMapping[str, Any], ctx)

        # E-A1：battle_alchemy_used 来源 = kwarg 优先 → ctx["battle_snapshot"] 兜底
        used = self._norm_used(battle_alchemy_used)
        snap_dict: Any = ctx.get("battle_snapshot")
        if battle_alchemy_used is None and isinstance(snap_dict, Mapping):
            used = self.read_used(snap_dict)

        # GU-54 限次防御拦截（ATO-01 幂等衔接：resolve 也拦一次，防壳层漏守卫）
        if used >= self._per_battle_limit():
            return {"ok": False, "reason": "already_used",
                    "message": "本场战斗已使用过即时调合（限 1 次/场）"}

        # BA-07 auto_use 解析；BA-06 冷却；BA-10 强度
        use = self._auto_use_default() if auto_use is None else bool(auto_use)
        cd = self.cooldown_of(recipe_def)
        if cooldown not in (None, 0):
            try:
                raw_cd = int(cooldown)
                if raw_cd > 0:
                    cd = raw_cd
            except (TypeError, ValueError):
                pass
        strength = self.intensity(recipe_def, cooldown=cd)

        # 全量原子校验（ATO-01/BA-08：材料+宝石全量满足才执行，否则全拒+差异，严禁部分扣除）
        needs = self._materials(recipe_def)
        shortfall: List[dict] = []
        for rec in needs:
            have = self._count_item(ctx, rec["item_id"])
            if have < rec["count"]:
                shortfall.append({
                    "item_id": rec["item_id"],
                    "name": self._name_of(ctx, rec["item_id"]),
                    "need": rec["count"],
                    "have": have,
                    "diff": rec["count"] - have,
                })
        gem_cost = self._gem_cost(recipe_def)
        currencies: Any = ctx.get("currencies")
        if gem_cost > 0:
            if not isinstance(currencies, MutableMapping):
                return {"ok": False, "reason": "currencies_missing",
                        "message": "无法结算宝石"}
            have_gem = self._gem_of(currencies)
            if have_gem < gem_cost:
                shortfall.append({
                    "item_id": GEM_KEY, "name": "宝石",
                    "need": gem_cost, "have": have_gem,
                    "diff": gem_cost - have_gem,
                })
        if shortfall:
            return {"ok": False, "reason": "materials_insufficient",
                    "message": "携带素材或宝石不足，无法即时调合",
                    "shortfall": shortfall}

        # 快照（E-A8：currencies/inventory/玩家 persistent_state 原子防双扣）
        snap = self._snapshot(ctx)

        # GU-52 能量消耗（enabled 时扣 1 格；关则直通，ENG-01/ENG-10）
        en = self.consume_energy(ctx.get("player"), ctx)
        if not en.get("ok"):
            self._restore(ctx_mut, snap)
            return {"ok": False, "reason": "energy",
                    "message": en.get("message", "能量不足，无法即时调合"),
                    "energy": en}

        # 材料原子扣减（BA-08：走 ctx remove_item，战斗携带素材，E-A2）
        for rec in needs:
            if not self._remove_item(ctx_mut, rec["item_id"], rec["count"]):
                self._restore(ctx_mut, snap)
                return {"ok": False, "reason": "materials_remove_failed",
                        "message": "材料扣除失败，已回滚"}

        # 宝石原子扣减（BA-08/E-A4：cost.gem > 0 时扣减）
        if gem_cost > 0:
            currencies[GEM_KEY] = self._gem_of(currencies) - gem_cost

        # 产出实例构造（BA-08：ItemInstance quality/traits 形态，E-A3）
        produced = self._produce_record(ctx, recipe_def)
        if produced is None:
            self._restore(ctx_mut, snap)
            return {"ok": False, "reason": "produce_failed", "message": "产出实例构造失败"}

        # auto_use 结算或入包（BA-07：二选一——当场自动使用走 use_fn；否则产出入包）
        auto_used = False
        outcome: Any = None
        if use:
            outcome = self._try_use(use_fn, produced)
            if outcome is not None:
                auto_used = True
        if not auto_used:
            # 入包（BA-07 auto_use=false 或 E-A7：未注入/失败 use_fn → 不丢产出按入包）
            if not self._into_pack(ctx_mut, produced):
                self._restore(ctx_mut, snap)
                return {"ok": False, "reason": "add_item_failed", "message": "产出入包失败"}

        # 计数自增（GU-54）并回写注入的战斗快照 dict（E-A1）
        new_used = used + 1
        if isinstance(snap_dict, MutableMapping):
            self.write_used(snap_dict, new_used)

        return {
            "ok": True,
            "message": self._success_message(produced, auto_used, use),
            "produced": produced,
            "auto_use": use,
            "auto_used": auto_used,
            "outcome": outcome,
            "battle_alchemy_used": new_used,
            "cooldown": cd,
            "intensity": strength,
        }

    # ------------------------------------------------------------------
    # 能量（GU-52/R-08）
    # ------------------------------------------------------------------
    def consume_energy(self, player: Any, ctx: Any = None) -> dict:
        """能量消耗（GU-52/R-08）：energy_enabled=true 时 EnergyBar.consume(1)，关则直通。

        入参：player 玩家状态 dict（None → 回落 ctx["player"]）；ctx 上下文（兜底取 player）。
        出参：EnergyBar.consume 结果——关闭：{ok:True, bypassed:True}（ENG-01 直通不扣）；
              开启且充足：{ok:True, consumed:1, current, max}；不足：{ok:False, reason:
              'energy_insufficient', message}；非法 player：{ok:False, reason:'invalid_player'}。
        """
        if player is None and isinstance(ctx, Mapping):
            player = ctx.get("player")
        if not isinstance(player, MutableMapping):
            return {"ok": False, "reason": "invalid_player", "message": "玩家状态非法"}
        return self._energy.consume(player, 1)

    # ------------------------------------------------------------------
    # 内部工具（纯函数，对齐 synthesis 同款实现）
    # ------------------------------------------------------------------
    @staticmethod
    def _norm_used(v: Any) -> int:
        """battle_alchemy_used 归一（bool/None/非法 → 0；负 → 0）。"""
        if isinstance(v, bool) or v is None:
            return 0
        try:
            n = int(v)
        except (TypeError, ValueError):
            return 0
        return max(0, n)

    @staticmethod
    def _materials(recipe_def: Mapping[str, Any]) -> List[dict]:
        """配方材料清单（[{item_id, count}]；兼容 {id|item, count} 两种形态）。"""
        raw = recipe_def.get("materials")
        out: List[dict] = []
        if not isinstance(raw, (list, tuple)):
            return out
        for rec in raw:
            if not isinstance(rec, Mapping):
                continue
            item_id = rec.get("id") or rec.get("item")
            if not isinstance(item_id, str) or not item_id:
                continue
            cnt = rec.get("count", 1)
            try:
                n = int(cnt)
            except (TypeError, ValueError):
                n = 1
            out.append({"item_id": item_id, "count": max(1, n)})
        return out

    @staticmethod
    def _gem_cost(recipe_def: Mapping[str, Any]) -> int:
        """配方宝石成本（BA-08/E-A4）：recipe.cost.gem，缺省/非法 → 0。"""
        cost = recipe_def.get("cost")
        if not isinstance(cost, Mapping):
            return 0
        v = cost.get(GEM_KEY, 0)
        if isinstance(v, bool) or v is None:
            return 0
        try:
            n = int(v)
        except (TypeError, ValueError):
            return 0
        return max(0, n)

    @staticmethod
    def _gem_of(currencies: Mapping[str, Any]) -> int:
        """货币表宝石持有数（缺省 0）。"""
        try:
            return max(0, int(currencies.get(GEM_KEY, 0)))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _count_item(ctx: Mapping[str, Any], item_id: str) -> int:
        """持有计数（GU-53/E-A2）：ctx["count_item"] hook 优先；ctx["inventory"] 兜底。"""
        hook = ctx.get("count_item")
        if callable(hook):
            try:
                return max(0, int(hook(item_id)))
            except Exception:
                return 0
        inv = ctx.get("inventory")
        if isinstance(inv, Mapping):
            try:
                return max(0, int(inv.get(item_id, 0)))
            except (TypeError, ValueError):
                return 0
        return 0

    @staticmethod
    def _remove_item(ctx: MutableMapping[str, Any], item_id: str, count: int) -> bool:
        """扣减（BA-08，不部分扣减）：ctx["remove_item"] hook 优先；ctx["inventory"] 兜底。"""
        hook = ctx.get("remove_item")
        if callable(hook):
            try:
                return BattleAlchemyEngine._hook_ok(hook(item_id, count))
            except Exception:
                return False
        inv = ctx.get("inventory")
        if isinstance(inv, MutableMapping):
            cur = BattleAlchemyEngine._count_item(ctx, item_id)
            if cur < count:
                return False
            left = cur - count
            if left <= 0:
                inv.pop(item_id, None)
            else:
                inv[item_id] = left
            return True
        return False

    @staticmethod
    def _hook_ok(result: Any) -> bool:
        """hook 返回值布尔归一（True / {ok} / 带 .ok 对象；None/False → False）。"""
        if result is True:
            return True
        if result is None:
            return False
        if isinstance(result, Mapping):
            return bool(result.get("ok"))
        return bool(getattr(result, "ok", False))

    def _find_item(self, ctx: Mapping[str, Any], key: Any) -> Optional[Mapping[str, Any]]:
        """按 id 查 items def（ctx["items"] 注册表 / ctx["resolve_item"] 解析器）。"""
        if isinstance(key, str) and key:
            items = ctx.get("items")
            if isinstance(items, Mapping):
                hit = items.get(key)
                if isinstance(hit, Mapping):
                    return hit
        resolver = ctx.get("resolve_item")
        if callable(resolver):
            try:
                hit = resolver(key)
                if isinstance(hit, Mapping):
                    return hit
            except Exception:
                pass
        return None

    def _name_of(self, ctx: Mapping[str, Any], item_id: str) -> str:
        """物品 id → 显示名（items def name；缺失 → 原 id）。"""
        idef = self._find_item(ctx, item_id)
        if isinstance(idef, Mapping):
            name = idef.get("name")
            if isinstance(name, str) and name:
                return name
        return str(item_id)

    @staticmethod
    def _def_traits(idef: Any) -> List[str]:
        """物品 def traits 归一（str/list/tuple → str 列表；缺失/非法 → []）。"""
        if not isinstance(idef, Mapping):
            return []
        raw = idef.get("traits")
        if isinstance(raw, str) and raw:
            return [raw]
        if isinstance(raw, (list, tuple)):
            return [str(t) for t in raw if str(t)]
        return []

    def _produce_record(self, ctx: Mapping[str, Any],
                        recipe_def: Mapping[str, Any]) -> Optional[dict]:
        """产出实例构造（BA-08：ItemInstance quality/traits 形态，E-A3；不入包）。

        出参：{item_id, name, count, quality, tier, traits, effects} 或 None（输出非法）。
        """
        out = recipe_def.get("output")
        if isinstance(out, Mapping):
            item_id = out.get("item") or recipe_def.get("id")
            cnt_raw = out.get("count", 1)
        else:
            item_id = recipe_def.get("id")
            cnt_raw = 1
        if not isinstance(item_id, str) or not item_id:
            return None
        try:
            count = max(1, int(cnt_raw))
        except (TypeError, ValueError):
            count = 1
        idef = self._find_item(ctx, item_id)
        quality: Any = idef.get("quality") if isinstance(idef, Mapping) else None
        traits = self._def_traits(idef)
        effects = idef.get("base_effects") if isinstance(idef, Mapping) else None
        name = str(idef.get("name") or item_id) if isinstance(idef, Mapping) else item_id
        return {
            "item_id": item_id,
            "name": name,
            "count": count,
            "quality": quality,
            "tier": quality,
            "traits": traits,
            "effects": effects,
        }

    def _into_pack(self, ctx: MutableMapping[str, Any],
                   produced: Mapping[str, Any]) -> bool:
        """产出入包（BA-07 入包口径/BA-08）：add_item(item_id, count, bound=True, quality,
        traits=tuple)；hook 缺失/失败 → False。"""
        add_item = ctx.get("add_item")
        if not callable(add_item):
            return False
        try:
            result = add_item(
                produced.get("item_id"), produced.get("count", 1), True,
                quality=produced.get("quality"), traits=tuple(produced.get("traits") or ()),
            )
        except Exception:
            return False
        return self._hook_ok(result)

    @staticmethod
    def _try_use(use_fn: Any, produced: Mapping[str, Any]) -> Any:
        """auto_use 结算（BA-07/E-A7）：调 use_fn(item_id, count, produced)；异常 → None。"""
        if use_fn is None or not callable(use_fn):
            return None
        try:
            return use_fn(produced.get("item_id"), produced.get("count", 1), produced)
        except Exception:
            return None

    @staticmethod
    def _success_message(produced: Mapping[str, Any], auto_used: bool, use: bool) -> str:
        """成功消息（M-17 纯文本模板，无 emoji；BA-09 一行渲染归批9B）。"""
        name = produced.get("name") or produced.get("item_id")
        count = produced.get("count", 1)
        if use and auto_used:
            return f"{name} ×{count} 已即时调合并自动使用"
        return f"{name} ×{count} 已即时调合入包（auto_use 关闭或未自动使用）"

    @staticmethod
    def _snapshot(ctx: Mapping[str, Any]) -> dict:
        """快照（E-A8：currencies/inventory/玩家 persistent_state 就地容器）。"""
        snap: Dict[str, Any] = {k: copy.deepcopy(ctx.get(k)) for k in _SNAP_KEYS}
        player = ctx.get("player")
        if isinstance(player, Mapping):
            ps = player.get("persistent_state")
            if isinstance(ps, Mapping):
                snap["_player_ps"] = copy.deepcopy(ps)
        return snap

    @staticmethod
    def _restore(ctx: MutableMapping[str, Any], snap: dict) -> None:
        """回滚（E-A8：对齐 synthesis._restore + 玩家 persistent_state）。"""
        for k in _SNAP_KEYS:
            v = snap.get(k)
            if v is None:
                ctx.pop(k, None)
            else:
                ctx[k] = v
        player = ctx.get("player")
        ps = snap.get("_player_ps")
        if isinstance(player, MutableMapping):
            if ps is None:
                player.pop("persistent_state", None)
            else:
                player["persistent_state"] = ps
