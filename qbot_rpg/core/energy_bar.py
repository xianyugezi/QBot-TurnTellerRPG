"""调合能量条引擎（M8 批4·路2）——懒计算补格/上限随等级/消耗/安全区 2 倍速/默认关直通/存档同步。

文件：qbot_rpg/core/energy_bar.py
创建：2026-08-29
作者：Hermes 子agent-2（路2）
功能：M8 炼金调合能量条（ENG-01~10）纯函数引擎——可选默认关（ENG-01）、见习解锁/上限随职业
      等级 7 档（ENG-02/03）、每炼金消耗 1 格（ENG-04）、30 分钟回 1 格懒计算（ENG-05）、
      安全区 2 倍速（ENG-06）、合成豁免（ENG-07：引擎不扣即豁免，n=0 无操作）、软节奏保底
      （ENG-08：能量不足提示 /合成 保底）、存档同步（ENG-09：energy_current +
      energy_last_regen_ts 统一 persistent_state 桶，不落 proficiency）、门槛挂载消费点
      （ENG-10：/炼金 /深度炼金 /即时调合 由指令壳调 consume，关闭时守卫直通）。

依据：
  - docs/细化/细化_2c4f_投料触媒与能量条.md 三（ENG-01~10）/ 五（TC-21~30）
  - docs/m8_contract_核心机制.md 三（ENG-01~10 全文；ENG-09 存档统一 persistent_state 桶）
  - 批0 落地数据 content/test_demo/settings.json alchemy 段（energy_enabled=false /
    energy_max 7 档 / energy_regen_sec=1800 / energy_regen_sec_safe=900）
  - 模式参考 qbot_rpg/core/quality.py（构造器配置注入 + 缺省默认值兜底；纯函数零 IO 零
    NoneBot）；qbot_rpg/core/levelup.py（玩家状态 dict 就地改写风格）；
    qbot_rpg/core/adventure_log.py _persistent_state_of（persistent_state 容器定位口径）

【工程补白 · 显式标注】（定稿未给口径处，本引擎最小必要推导，不得新增定稿外机制行为）：
  E-1  存档落点：player["persistent_state"]["energy_current"] / ["energy_last_regen_ts"]
       （ENG-09 统一 persistent_state 桶；上下文容器定位对齐 adventure_log：ctx["persistent_state"]
       或 player.persistent_state，本引擎操作对象为 player dict 自身）。
  E-2  懒计算补格公式：regen_gained = floor((now - last_ts) / interval)（向下取整）；补格后
       锚点 energy_last_regen_ts 覆写为 now（剩余秒数丢弃，碎片化友好，对齐三周期懒计算口径，
       见 TC-27：3600s→+2 格 1800s→+1 格）。
  E-3  首锚点缺失（新玩家/旧存档无 energy_last_regen_ts）：锚点=now（不凭空补格，防一次大量
       回格）；energy_current 缺失 → 默认满格 = max（新玩家满能量，TC-21 见习 5/5 口径）。
  E-4  时钟回拨防御（now < last_ts）：不补格、不覆写锚点（防锚点倒退）。
  E-5  安全区判定口径：ctx["scene"]（str 场景 id）命中 safe_scenes 集合
       （settings.alchemy.safe_scenes > 构造注入 safe_scenes > 默认空集）为安全；Mapping 场景
       取 scene["safe"]==True 为安全；无任何场景标记 → False（缺省 False，安全失败保守）。
  E-6  职业档位索引提取启发式：player["tier_index"]（装配层预计算）> proficiency 节点 level
       （player["job_id"] 指定或首个带 level 的条目，钳制到 [0, len-1]）> 0（防御兜底）。
  E-7  默认关直通（ENG-01）：关闭时 consume 只读计算 current/max（不写存档、不扣、无能量不足
       模板）——「不干预炼金节奏」。
  E-8  energy_max 配置 = 7 档有序映射：档位序固定 见习→王（默认七档序，ENG-02/03 语义）；
       配置键按默认序归位、未知键按配置序追加尾部；缺键回落默认模板；档位索引越界钳制
       到末档；非法值（非 int/负值）跳过。
  E-9  能量不足模板「能量 0/10，等 30 分钟回 1 格，或 /合成 保底」（L344）：分钟数按配置
       energy_regen_sec/60 取整动态渲染（默认 1800s → 30 分钟，文本与定稿逐字一致）。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；now/safe 注入确定性；工程补白显式标注；
      不抛异常（配置缺省兜底、方法防御降级）。
"""

from __future__ import annotations

import time
from typing import Any, List, Mapping, MutableMapping, Optional

__all__ = [
    "DEFAULT_ENERGY_MAX",
    "DEFAULT_REGEN_SEC",
    "DEFAULT_REGEN_SEC_SAFE",
    "DEFAULT_TIER_NAMES",
    "EnergyBar",
]

# 档位称号序（ENG-02/03：见习→正式→精通→专家→大师→宗师→王，内容包可改名，键序=档位序）
DEFAULT_TIER_NAMES: tuple = ("见习", "正式", "精通", "专家", "大师", "宗师", "王")

# 上限 7 档默认模板（ENG-03 / 定稿 L416，可配）
DEFAULT_ENERGY_MAX: dict = {
    "见习": 5,
    "正式": 8,
    "精通": 10,
    "专家": 12,
    "大师": 15,
    "宗师": 18,
    "王": 20,
}

# 恢复间隔默认（ENG-05：30 分钟回 1 格，L417）
DEFAULT_REGEN_SEC: int = 1800
# 安全区恢复间隔默认（ENG-06：2 倍速，实现层细化默认 900）
DEFAULT_REGEN_SEC_SAFE: int = 900


class EnergyBar:
    """调合能量条引擎（细化_2c4f 三：ENG-01~10）。

    构造器配置注入（settings）+ 缺省默认值兜底；操作对象为玩家状态 dict（就地改写
    persistent_state 桶），纯函数零 IO 零 NoneBot，不抛异常。供批4B 指令壳
    /炼金 /深度炼金 /即时调合 前置守卫与批量能量扣减复用。
    """

    def __init__(
        self,
        settings: Optional[Mapping[str, Any]] = None,
        *,
        safe_scenes: Optional[Any] = None,
    ) -> None:
        """构造能量条引擎（配置注入 + 缺省默认值兜底）。

        - settings：settings dict（取 alchemy 段）；None/缺省 → 默认关（ENG-01 默认关）。
        - safe_scenes：安全区场景 id 集合（可覆盖 settings.alchemy.safe_scenes，工程补白 E-5）。
        """
        self._settings: Mapping[str, Any] = settings if isinstance(settings, Mapping) else {}
        alchemy = self._settings.get("alchemy")
        self._alchemy: Mapping[str, Any] = alchemy if isinstance(alchemy, Mapping) else {}

        # ENG-01：默认关（缺省 false）
        self._enabled = bool(self._alchemy.get("energy_enabled", False))

        # ENG-03：energy_max 7 档有序映射（E-8：档位序固定 见习→王；配置键按默认序归位，
        # 未知键按配置序追加尾部；缺键回落默认模板）
        raw_max = self._alchemy.get("energy_max")
        self._energy_max_raw: Mapping[str, Any] = (
            raw_max if isinstance(raw_max, Mapping) else {}
        )
        merged = dict(DEFAULT_ENERGY_MAX)
        for k, v in self._energy_max_raw.items():
            try:
                iv = int(v)
            except (TypeError, ValueError):
                continue
            if iv >= 0:
                merged[str(k)] = iv
        self._energy_max: dict = merged
        std_index = {name: i for i, name in enumerate(DEFAULT_TIER_NAMES)}
        order: List[Optional[str]] = [None] * len(DEFAULT_TIER_NAMES)
        extra: List[str] = []
        for k in self._energy_max:
            if k in std_index and order[std_index[k]] is None:
                order[std_index[k]] = k
            else:
                extra.append(k)
        self._tier_order: List[str] = [k for k in order if k is not None]
        for k in extra:
            if k not in self._tier_order:
                self._tier_order.append(k)

        # ENG-05/06：恢复间隔（可配；缺省 1800 / 安全区 900）
        self._regen_sec = self._as_positive_int(
            self._alchemy.get("energy_regen_sec"), DEFAULT_REGEN_SEC
        )
        self._regen_sec_safe = self._as_positive_int(
            self._alchemy.get("energy_regen_sec_safe"), DEFAULT_REGEN_SEC_SAFE
        )

        # E-5：安全区场景集合（settings.alchemy.safe_scenes > 构造注入 > 默认空集）
        sc = self._alchemy.get("safe_scenes")
        if safe_scenes is not None:
            base_scenes = set(safe_scenes)
        elif isinstance(sc, (list, tuple, set, frozenset)):
            base_scenes = {str(s) for s in sc}
        else:
            base_scenes = set()
        self._safe_scenes = frozenset(base_scenes)

    @staticmethod
    def _as_positive_int(value: Any, default: int) -> int:
        """正整数归一（bool/非 int/≤0 → 缺省），防御非法配置。"""
        if isinstance(value, bool):
            return default
        try:
            iv = int(value)
        except (TypeError, ValueError):
            return default
        return iv if iv > 0 else default

    # ------------------------------------------------------------------
    # 开关 / 上限 / 间隔（ENG-01/02/03/05/06）
    # ------------------------------------------------------------------
    def enabled(self) -> bool:
        """能量条是否启用（ENG-01）：settings.alchemy.energy_enabled，缺省 false。"""
        return self._enabled

    def max_for_tier(self, job_tier_index: int) -> int:
        """上限随职业等级（ENG-02/03）：energy_max 7 档，tier 索引 0~6。

        入参：job_tier_index 职业档位索引（0=见习 … 6=王）。
        出参：该档上限 int。越界钳制到末档（E-8）；缺键回落默认模板值。
        """
        i = int(job_tier_index)
        if i < 0:
            i = 0
        if i >= len(self._tier_order):
            i = len(self._tier_order) - 1
        return int(self._energy_max.get(self._tier_order[i], 1))

    def regen_sec(self, *, safe: Optional[bool] = None) -> int:
        """恢复间隔秒数（ENG-05/06）：safe=True → energy_regen_sec_safe（2 倍速）；否则基准。

        入参：safe 显式指定安全区口径（None=基准，缺省调用等价 regen_sec()）。
        出参：间隔秒数 int（默认 1800 / 安全区 900）。
        """
        if safe:
            return self._regen_sec_safe
        return self._regen_sec

    # ------------------------------------------------------------------
    # 安全区判定（ENG-06，工程补白 E-5）
    # ------------------------------------------------------------------
    @staticmethod
    def _scene_from_ctx(ctx: Optional[Mapping[str, Any]]) -> Any:
        """ctx → 当前场景标记：ctx["scene"] → ctx["player"]["scene"] → None。"""
        if not isinstance(ctx, Mapping):
            return None
        scene = ctx.get("scene")
        if scene is None:
            player = ctx.get("player")
            if isinstance(player, Mapping):
                scene = player.get("scene")
        return scene

    def _scene_is_safe(self, scene: Any) -> bool:
        """场景标记是否安全（E-5）：str 命中 safe_scenes；Mapping 取 scene["safe"]；无 → False。"""
        if scene is None:
            return False
        if isinstance(scene, str):
            return scene in self._safe_scenes
        if isinstance(scene, Mapping):
            return bool(scene.get("safe"))
        return False

    def is_safe_zone(self, ctx: Mapping[str, Any]) -> bool:
        """安全区判定（ENG-06）：玩家当前场景标记命中安全区 → True；缺省 False（工程补白 E-5）。

        入参：ctx 事件/玩家上下文（ctx["scene"] 或 ctx["player"]["scene"] 取场景标记）。
        出参：bool。无任何场景信息 → False（安全失败保守，不误加速）。
        """
        return self._scene_is_safe(self._scene_from_ctx(ctx))

    # ------------------------------------------------------------------
    # 玩家状态容器 / 档位索引（E-1 / E-6）
    # ------------------------------------------------------------------
    @staticmethod
    def _ps_read(player: Mapping[str, Any]) -> Mapping[str, Any]:
        """persistent_state 只读容器（E-1）；缺失 → 空 dict（不新建）。"""
        ps = player.get("persistent_state")
        return ps if isinstance(ps, Mapping) else {}

    @staticmethod
    def _ps_rw(player: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        """persistent_state 读写容器（E-1）；缺失 → 新建并挂回 player。"""
        ps = player.get("persistent_state")
        if not isinstance(ps, MutableMapping):
            ps = {}
            player["persistent_state"] = ps
        return ps

    def _tier_index(self, player: Mapping[str, Any]) -> int:
        """职业档位索引提取启发式（E-6）：tier_index > proficiency level > 0。"""
        top = len(self._tier_order) - 1
        ti = player.get("tier_index")
        if isinstance(ti, int) and not isinstance(ti, bool):
            return max(0, min(ti, top))
        prof = player.get("proficiency")
        node: Any = None
        if isinstance(prof, Mapping):
            job_id = player.get("job_id")
            if isinstance(job_id, str) and job_id in prof:
                cand = prof[job_id]
                if isinstance(cand, Mapping):
                    node = cand
            if node is None:
                for _k, v in prof.items():
                    if isinstance(v, Mapping) and isinstance(v.get("level"), int):
                        node = v
                        break
        if isinstance(node, Mapping):
            level = node.get("level")
            if isinstance(level, int) and not isinstance(level, bool):
                return max(0, min(level, top))
        return 0

    # ------------------------------------------------------------------
    # 懒计算核心（ENG-05，工程补白 E-2/E-3/E-4）
    # ------------------------------------------------------------------
    @staticmethod
    def _now_ts(now: Any) -> int:
        """秒级时间戳：now 注入优先（确定性可测），缺省 = UTC 现刻。"""
        if now is not None:
            return int(now)
        return int(time.time())

    def _compute(
        self,
        player: Mapping[str, Any],
        now: Any,
        write: bool,
        safe: Optional[bool] = None,
    ) -> dict:
        """懒计算补格（ENG-05）——读存档 + 补格 + 上限封顶 +（write=True 时）回写存档。

        入参：
          - player：玩家状态 dict（persistent_state 桶读能量字段）。
          - now：注入当前时刻（秒；None=UTC 现刻）。
          - write：True=回写 current+last_regen_ts 存档；False=只读计算（关闭直通用，E-7）。
          - safe：安全区口径覆盖（None=按玩家场景标记自动判定，E-5）。
        出参：{current, max, regen_gained, capped, safe, interval}。
        核心：gained = floor(max(0, now-last_ts) / interval)，new = min(current+gained, max)；
              capped = current+gained > max（有补格被上限吃掉）；补格后锚点=now（E-2）；
              首锚点缺失 → 锚点=now、current 缺省=max（E-3）；时钟回拨 → 不补格不覆写锚点（E-4）。
        """
        mx = self.max_for_tier(self._tier_index(player))
        ps = self._ps_read(player)
        current_raw = ps.get("energy_current")
        last_raw = ps.get("energy_last_regen_ts")

        if safe is None:
            safe = self._scene_is_safe(self._scene_from_ctx({"player": player}))
        interval = self._regen_sec_safe if safe else self._regen_sec

        now_i = self._now_ts(now)
        if current_raw is None:
            current = mx  # E-3：新玩家默认满格（TC-21 5/5 口径）
        else:
            try:
                current = int(current_raw)
            except (TypeError, ValueError):
                current = 0
            if current < 0:
                current = 0
        if last_raw is None:
            last = now_i  # E-3：首锚点缺失 → 锚点=now（不凭空补格）
        else:
            try:
                last = int(last_raw)
            except (TypeError, ValueError):
                last = now_i

        gained = 0
        capped = False
        elapsed = now_i - last
        if elapsed > 0:
            gained = elapsed // interval
            raw = current + gained
            capped = raw > mx
            current = min(raw, mx)
        elif current > mx:
            # 配置下调上限后的钳制（不新增回格）
            current = mx

        if write and isinstance(player, MutableMapping):
            ps_w = self._ps_rw(player)
            ps_w["energy_current"] = current
            if now_i >= last:
                ps_w["energy_last_regen_ts"] = now_i

        return {
            "current": current,
            "max": mx,
            "regen_gained": int(gained),
            "capped": bool(capped),
            "safe": bool(safe),
            "interval": interval,
        }

    # ------------------------------------------------------------------
    # 对外接口（ENG-04/05/07/09/10）
    # ------------------------------------------------------------------
    def lazy_regen(
        self,
        player: Any,
        *,
        now: Any = None,
        safe: Optional[bool] = None,
    ) -> dict:
        """懒计算补格（ENG-05）：按 (now - last_regen_ts)/interval 补格、上限封顶、回写存档。

        入参：player 玩家状态 dict（就地改写 persistent_state）；now 注入确定性（缺省 UTC 现刻）；
              safe 安全区口径覆盖（None=按场景标记自动判定）。
        出参：{current, max, regen_gained, capped, safe, interval}；
              拒绝：{ok:False, reason:"invalid_player"}。
        核心：查询/消耗时调用补格（ENG-05 查询即补格）；补格后锚点=now（E-2）。
        """
        if not isinstance(player, Mapping):
            return {"ok": False, "reason": "invalid_player"}
        return self._compute(player, now, True, safe)

    def current_of(
        self,
        player: Any,
        *,
        now: Any = None,
        safe: Optional[bool] = None,
    ) -> int:
        """当前能量格数（ENG-05 查询即补格）：懒计算后返回 current（回写存档）。

        入参：player 玩家状态 dict；now 注入确定性；safe 安全区口径覆盖。
        出参：补格后当前能量 int；非法 player → 0。
        """
        if not isinstance(player, Mapping):
            return 0
        return int(self._compute(player, now, True, safe)["current"])

    def consume(
        self,
        player: Any,
        n: int = 1,
        *,
        now: Any = None,
        safe: Optional[bool] = None,
    ) -> dict:
        """每炼金消耗 n 格（ENG-04 / BATCH-03：批量 N 次扣 N 格，由调用方传 n=N）。

        入参：player 玩家状态 dict；n 消耗格数（n=0 表示不消耗——合成豁免 ENG-07 直通不扣）；
              now 注入确定性；safe 安全区口径覆盖。
        出参：
          - 关闭（ENG-01）：{ok:True, current, max, bypassed:True}——只读计算、不写存档、不扣
            （E-7 不干预炼金节奏，ENG-10 守卫直通）。
          - 开启且充足：{ok:True, current, max, consumed:n, regen_gained, capped, bypassed:False}。
          - 开启但不足（ENG-04/08）：{ok:False, reason:"energy_insufficient", current, max,
            message:"能量 0/10，等 30 分钟回 1 格，或 /合成 保底"}（不扣，保底通道 /合成 仍可用）。
        核心：先懒计算补格（ENG-05）再扣；n=0 → 只补格不扣（ENG-07 合成豁免由引擎「不扣」承载）。
        """
        if not isinstance(player, MutableMapping):
            return {"ok": False, "reason": "invalid_player"}
        try:
            need = int(n)
        except (TypeError, ValueError):
            need = 1
        if need < 0:
            need = 0  # 防御：负消耗按 0（无操作）

        # ENG-01/ENG-10：关闭 → 直通（只读计算，不干预）
        if not self._enabled:
            peek = self._compute(player, now, False, safe)
            return {
                "ok": True,
                "current": peek["current"],
                "max": peek["max"],
                "bypassed": True,
            }

        # 先懒计算补格再扣（ENG-05）
        result = self._compute(player, now, True, safe)

        if need == 0:
            # ENG-07：合成豁免——引擎不扣（n=0 只补格不扣，energy 状态不变）
            return {
                "ok": True,
                "current": result["current"],
                "max": result["max"],
                "consumed": 0,
                "regen_gained": result["regen_gained"],
                "capped": result["capped"],
                "bypassed": False,
            }

        if result["current"] < need:
            # ENG-04/08：能量不足 → 拒绝并提示保底（E-9 分钟数按配置动态渲染）
            mins = int(round(self._regen_sec / 60))
            return {
                "ok": False,
                "reason": "energy_insufficient",
                "current": result["current"],
                "max": result["max"],
                "message": (
                    f"能量 {result['current']}/{result['max']}，"
                    f"等 {mins} 分钟回 1 格，或 /合成 保底"
                ),
            }

        ps = self._ps_rw(player)
        new_current = result["current"] - need
        ps["energy_current"] = new_current
        return {
            "ok": True,
            "current": new_current,
            "max": result["max"],
            "consumed": need,
            "regen_gained": result["regen_gained"],
            "capped": result["capped"],
            "bypassed": False,
        }

    def sync_after(self, player: Any, now: Any = None) -> dict:
        """结算后同步懒计算锚点（ENG-09 / TC-30）：覆写 energy_last_regen_ts = now。

        入参：player 玩家状态 dict；now 注入确定性（缺省 UTC 现刻）。
        出参：{ok, energy_last_regen_ts, current}；非法 player →
              {ok:False, reason:"invalid_player"}。
        核心：调合/消耗结算后把锚点拨到当前时刻，后续懒计算不重复计已结算的补格（对齐 L509
              旧快照结算口径，热重载不丢）。
        """
        if not isinstance(player, MutableMapping):
            return {"ok": False, "reason": "invalid_player"}
        ps = self._ps_rw(player)
        ts = self._now_ts(now)
        ps["energy_last_regen_ts"] = ts
        return {"ok": True, "energy_last_regen_ts": ts, "current": ps.get("energy_current")}
