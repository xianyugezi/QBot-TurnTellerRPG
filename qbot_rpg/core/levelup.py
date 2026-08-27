"""升级引擎（M6 批次1·路A · 实装版）——经验入账/跨级判定/升级回满/白值重算/SP 发放联动/自由加点。

依据：
  - 细化_M6_三引擎与基础指令（D1）§一 levelup 引擎实装契约：规则 LVL-01~LVL-12、
    字段 F-01~F-07、边界异常 LVL-E1~LVL-E4、验收用例 TC-LVL-01~TC-LVL-06。
  - 【框架】L125-127（成长引擎：经验曲线/职业成长率内容包配置）、L294-297（等级上限与
    战后恢复：满级经验不再增长/升级 HP MP 回满）、L1101（升级推送，事件默认关防刷屏）。
  - 【3b】§1.1（白值 = base + growth×(lv-1) + 自由加点，L142/L173；换职业不重算 L174）、
    §2.1 管线（calc_all_final_attributes）；data/player.py PlayerAttributes.base 白值层。
  - 【2c5a】EXP-06（入账→升级→SP 判定链）、SP-01（每级 SP）；proficiency.<job_id>.sp_earned
    为 SP 发放落点（§5.3）。
  - 现有代码 core/levelup.py（M1 空壳骨架，方法体原为 raise NotImplementedError）。

【工程补白 · 显式标注】
  1) 操作对象 = 玩家状态 dict（ctx 玩家表示，可变，就地改写），非 frozen Player 快照
     （与 checkin/quest/shop/reward 既有引擎一致；frozen Player 仅作存储/渲染快照）。
     dict 内字段：level/exp/hp/mp=int；attributes=PlayerAttributes；proficiency 可选
     {job_id: {"sp_earned": int}}。
  2) 配置注入 = 构造器参数，缺省默认值兜底（对齐 D1 B-1【工程补白】）：
     exp_curve：可调用 lv->int 或 dict 表；默认 lambda lv: 100*lv（B-1：1 级升 2 级需 100）。
     level_cap：默认 45（对齐定稿 L296 示例）；sp_per_level：默认 1（SP-01）。
     growth：职业成长率 map（jobs.json 可配）；默认 {}（无成长 → 白值重算按 0 处理）。
     attr_registry：自由加点属性注册表（3b ADR-05）；默认九预置键（hp/mp/str/int/con/spr/foc/agi/lck）。
  3) 多级连升只在最后一级结算后回满一次（LVL-05）：升级循环内只累加 growth 进白值层
     base 与发放 SP，循环结束统一 calc_all_final_attributes 重算并回满 HP/MP（上限=重算后最终属性）。
  4) exp_curve 为 dict 表时，查无对应等级 → 按默认曲线 100×lv 兜底（防表越界崩溃）。
  5) 引擎零 IO、零 NoneBot import、纯函数（3a R1）；存储事务由装配层 save_player 包裹（LVL-10）。
  6) 战斗结算接缝（LVL-12）：引擎不持有战斗状态，由装配层在结算点调用 gain_exp 入账。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；now/rng 确定性注入；工程补白显式标注。
"""
from __future__ import annotations

from typing import Any, Callable, Collection, Dict, Mapping, MutableMapping, Optional

from qbot_rpg.core.player_attributes import calc_all_final_attributes
from qbot_rpg.data.player import PlayerAttributes

__all__ = ["LevelUpEngine"]

# 缺省属性注册表（对齐 player_attributes 九预置键：hp/mp=resource，其余 combat，3b §4.2）
_DEFAULT_ATTR_REGISTRY: frozenset = frozenset(
    {"hp", "mp", "str", "int", "con", "spr", "foc", "agi", "lck"}
)


class LevelUpEngine:
    """等级/经验/自由加点引擎（D1 §一：LVL-01~LVL-12）。

    操作对象为玩家状态 dict（ctx 玩家表示），所有改写就地发生；返回 dict 结果，
    拒绝场景返回 {ok: False, reason: ...} 不抛异常。
    """

    def __init__(
        self,
        exp_curve: Optional[Any] = None,
        level_cap: int = 45,
        sp_per_level: int = 1,
        growth: Optional[Mapping[str, float]] = None,
        attr_registry: Optional[Collection[str]] = None,
    ) -> None:
        """构造升级引擎（配置注入，缺省默认值兜底，D1 B-1）。

        - exp_curve：可调用 lv->int（升级阈值），或 {lv: 阈值} dict 表；None → 默认 100×lv。
        - level_cap：等级上限（满级判定 LVL-03/F-03），默认 45。
        - sp_per_level：每级 SP 发放量（LVL-07/SP-01），默认 1。
        - growth：职业成长率 map（F-05），升级时白值重算加成（LVL-06）；默认 {}。
        - attr_registry：自由加点属性注册表（LVL-08，3b ADR-05）；默认九预置键。
        """
        self.level_cap = int(level_cap)
        self.sp_per_level = int(sp_per_level)
        self._growth: Dict[str, float] = {
            str(k): float(v) for k, v in (growth or {}).items()
        }
        self._registry: Collection[str] = (
            _DEFAULT_ATTR_REGISTRY if attr_registry is None else tuple(attr_registry)
        )
        self._exp_to_next = self._normalize_curve(exp_curve)

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_curve(exp_curve: Any) -> Callable[[int], int]:
        """经验曲线归一（D1 B-1 / LVL-01）：callable 直用；dict 表查缺兜底 100×lv。"""
        if exp_curve is None:
            return lambda lv: 100 * int(lv)
        if callable(exp_curve):
            curve: Callable[[int], int] = exp_curve

            def _callable_curve(lv: int) -> int:
                return int(curve(lv))

            return _callable_curve
        if isinstance(exp_curve, Mapping):
            table = {int(k): int(v) for k, v in exp_curve.items()}

            def _from_table(lv: int) -> int:
                lv = int(lv)
                if lv in table:
                    return table[lv]
                return 100 * lv  # 【工程补白 4】表越界兜底默认曲线

            return _from_table
        raise TypeError(
            "exp_curve 必须是可调用或 lv->阈值 dict 表，收到 "
            f"{type(exp_curve).__name__}"
        )

    def exp_next(self, level: int) -> int:
        """当前级升下一级所需经验（LVL-11 口径）；满级返回 0。"""
        level = int(level)
        if level >= self.level_cap:
            return 0
        return int(self._exp_to_next(level))

    def _grant_sp(self, player: MutableMapping[str, Any], job_id: str) -> int:
        """SP 发放落点（LVL-07/F-06）：proficiency.<job_id>.sp_earned += sp_per_level。"""
        prof = player.get("proficiency")
        if not isinstance(prof, MutableMapping):
            prof = {}
            player["proficiency"] = prof
        node = prof.get(job_id)
        if not isinstance(node, MutableMapping):
            node = {}
            prof[job_id] = node
        node["sp_earned"] = int(node.get("sp_earned", 0)) + self.sp_per_level
        return self.sp_per_level

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def gain_exp(self, player: Any, amount: int) -> Any:
        """经验入账 → 跨级判定 → 升级结算（D1 §一 LVL-01~LVL-12）。

        - LVL-02：amount ≤ 0（或非 int）→ 幂等拒绝 {ok: False, reason: "exp_amount_invalid"}。
        - LVL-03：满级（level ≥ level_cap）→ 静默丢弃入账（经验不再增长，LVL-E2）。
        - LVL-04：while exp ≥ exp_to_next(level) 逐级结算（每级一次结算，含白值重算/SP）。
        - LVL-05：多级连升只在最后一级结算后回满一次 HP/MP（上限=重算后最终属性）。
        - LVL-06：升级触发白值层重算（growth 累加进 attributes.base）+ 全链重算。
        - LVL-07：每升 1 级向 proficiency.<job_id>.sp_earned 累加 sp_per_level。
        - LVL-11：返回 exp_next = exp_to_next(当前 level)；满级返回 0。
        - LVL-09：返回 dict {ok, level, level_ups, sp_earned_delta, hp_restored,
          mp_restored, exp_next}，装配层据此渲染「升级推送」（公告折叠 + 事件默认关）。
        """
        if not isinstance(player, MutableMapping):
            return {"ok": False, "reason": "invalid_player"}
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            return {"ok": False, "reason": "exp_amount_invalid"}

        level = int(player.get("level", 1))
        cap = self.level_cap
        if level >= cap:
            # LVL-E2：满级后再次入账 → 经验不增长，不提示升级
            return {
                "ok": True, "level": level, "level_ups": 0,
                "sp_earned_delta": 0, "hp_restored": 0, "mp_restored": 0,
                "exp_next": 0,
            }

        exp = int(player.get("exp", 0)) + amount
        job_id = str(player.get("job_id", "novice"))
        attributes = player.get("attributes")
        if not isinstance(attributes, PlayerAttributes):
            return {"ok": False, "reason": "invalid_attributes"}

        level_ups = 0
        sp_delta = 0
        while level < cap and exp >= self._exp_to_next(level):
            exp -= self._exp_to_next(level)
            level += 1
            level_ups += 1
            # LVL-06：白值层逐级累加 growth（base 已是「工厂算好的白值」口径，3b §4.4）
            base = attributes.base
            for attr, g in self._growth.items():
                base[attr] = float(base.get(attr, 0.0)) + float(g)
            # LVL-07：SP 发放（每级一次）
            sp_delta += self._grant_sp(player, job_id)

        player["level"] = level
        player["exp"] = exp

        hp_restored = 0
        mp_restored = 0
        if level_ups > 0:
            # LVL-05/LVL-06：重算最终属性并按上限回满 HP/MP
            final = calc_all_final_attributes(attributes)
            if "hp" in player:
                max_hp = final.get("hp")
                if max_hp is not None:
                    old_hp = int(player["hp"])
                    player["hp"] = int(max_hp)
                    hp_restored = max(0, int(max_hp) - old_hp)
            if "mp" in player:
                max_mp = final.get("mp")
                if max_mp is not None:
                    old_mp = int(player["mp"])
                    player["mp"] = int(max_mp)
                    mp_restored = max(0, int(max_mp) - old_mp)

        return {
            "ok": True,
            "level": level,
            "level_ups": level_ups,
            "sp_earned_delta": sp_delta,
            "hp_restored": hp_restored,
            "mp_restored": mp_restored,
            "exp_next": self.exp_next(level),
        }

    def allocate_point(self, player: Any, attr_id: str, amount: int) -> Any:
        """自由加点（LVL-08 / LVL-E3）：向白值层 base[attr_id] 加自由加点。

        校验：attr_id ∈ 属性注册表（3b ADR-05，非法 → 提示「属性不存在」）、
        amount ≥ 1、加点后白值非负。换职业保留（不加点不重算）。
        返回 {ok: True, attr_id, amount, base} 或 {ok: False, reason, message}。
        """
        if not isinstance(player, MutableMapping):
            return {"ok": False, "reason": "invalid_player"}
        attributes = player.get("attributes")
        if not isinstance(attributes, PlayerAttributes):
            return {"ok": False, "reason": "invalid_attributes"}
        if not isinstance(attr_id, str) or attr_id not in self._registry:
            return {
                "ok": False, "reason": "attr_not_found",
                "message": f"属性不存在：{attr_id}",
            }
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 1:
            return {"ok": False, "reason": "invalid_amount", "message": "加点数量必须 ≥ 1"}
        base = attributes.base
        cur = float(base.get(attr_id, 0.0))
        if cur + float(amount) < 0:
            return {"ok": False, "reason": "negative_base", "message": "加点后白值不能为负"}
        new_value = cur + float(amount)
        base[attr_id] = new_value
        return {
            "ok": True,
            "attr_id": attr_id,
            "amount": int(amount),
            "base": new_value,
        }
