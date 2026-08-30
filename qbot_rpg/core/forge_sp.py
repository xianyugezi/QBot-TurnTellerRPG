"""M9 锻造·批3·路3B：铸造 SP 面板解锁（qbot_rpg/core/forge_sp.py）——SP-F1~F5 纯函数层。

文件名：qbot_rpg/core/forge_sp.py
创建时间：2026-08-30
作者：Hermes 子agent-3B（M9 锻造实现组批3·路3B：并发同仓，仅新建本文件 +
  tests/unit/test_forge_sp.py + 扩展 content/test_demo/proficiency.json 的 forge 实例
  sp_panel；不改动 qbot_rpg/core/proficiency.py（只读消费））

功能描述：铸造职业 SP 面板解锁项的纯函数集合（细化_2c2d §3.2 SP-F1~F5 五类自选）：
  1) FORGE_SP_PANEL  SP-F1~F5 解锁项定义（id/名称/作用域/描述）——
      SP-F1 unlock_branch_tree 分支树视野（/图纸 /锻造树：未解锁→分支段折叠、只显主干）
      SP-F2 unlock_combine_3to1 3:1 合成（无 combine 升档入口）
      SP-F3 unlock_slot_tool 开孔（开孔道具不可用）
      SP-F4 unlock_sets 套装（/套装 拒绝、技能不生效）
      SP-F5 unlock_augment 客制（/客制 拒绝）
  2) sp_available(player)    可用 SP 点数（委托 ProficiencyEngine.sp_available(player, "forge")）
  3) sp_unlock(player, panel_id)   SP 自选解锁（委托 ProficiencyEngine.unlock_item(
     player, "forge", panel_id)：已解锁幂等（repeatable=false 拒绝不重复扣点）/
     SP 不足拒 / 未识别面板拒）
  4) sp_locked(player, panel_id)   未解锁判定（消费方：3:1 合成入口隐藏 / /套装、/客制
     指令拒绝 / /图纸 分支折叠）
  5) sp_panel_view(player)   SP 面板数据源（每项 id/name/scope/desc/unlocked，供
     /技能面板 渲染）

依据：
  - docs/细化/细化_2c2d_锻造套装与客制.md §3.2（SP-F1~F5 五类解锁项：分支树/3:1合成/
    开孔/套装/客制 + 默认 1 SP/次 不可重复单次解锁）——消费方侧语义逐项对齐
    （SP-F1 /图纸 分支折叠、/锻造树 主干；SP-F2 无 combine 升档入口；SP-F3 开孔道具
    不可用；SP-F4 /套装 拒绝、技能不生效；SP-F5 /客制 拒绝）。
  - docs/细化/细化_2c5a_职业等级与SP.md SP-01~08（每级 1 SP 可累积 / 面板自选解锁 /
    sp_earned+sp_used 双计持久化 / 1 SP/次可配 cost / 作用域限定）。
  - docs/m9_shared_contract.md §三（forge settings 段：synth_ratio_3to1/sets_enabled/
    augments_enabled 等消费方开关）。
  - 复用 M8：qbot_rpg/core/proficiency.py（ProficiencyEngine.sp_available /
    sp_panel_defs / unlock_item / unlock_count——SP 引擎已实装，本模块只委托不重写）。
  - 复用批1：qbot_rpg/core/forge_tree.py（FORGE_JOB_ID 铸造职业 id）。
  - content/test_demo/proficiency.json（forge 实例 sp_panel：SP-F1~F5 五项，
    cost=1/repeatable=false/max_repeat=1/desc，与 FORGE_SP_PANEL 保持同构）。

【工程补白 · 显式标注】（契约/细化未显式定义处的实现口径，标 F-x）：
  F-1  FORGE_SP_PANEL 为 SP-F1~F5 的静态定义（id/name/scope/desc），是面板渲染与
       sp_unlock/sp_locked 判定 id 集合的权威；sp_panel 内容配置（proficiency.json）
       与它保持同构。本地兜底：_engine() 将 FORGE_SP_PANEL 转成引擎 sp_panel 定义
       （cost=1/repeatable=false/max_repeat=1，对齐 2c5a SP-05 默认与 2c2d §3.2
       「默认 1 SP/次 不可重复单次解锁」）注入 ProficiencyEngine——即便内容配置未落盘，
       unlock_item 也能按 SP-F1~F5 正常解锁（确定性兜底，零 IO）。
  F-2  sp_locked 对未识别 panel_id（不在 FORGE_SP_PANEL id 集合）保守返回 True（锁定）
       ——消费方（入口隐藏/指令拒绝/分支折叠）对未知项一律不放开，避免越权。
  F-3  sp_locked 判定 = ProficiencyEngine.unlock_count(player, "forge", panel_id) <= 0；
       player 非 Mapping / 无 proficiency.forge 节点 → 0 → 锁定（确定性兜底）。
  F-4  sp_unlock 直接委托 ProficiencyEngine.unlock_item：其已覆盖 未识别面板拒
       （panel_not_found）/ SP 不足拒（sp_insufficient）/ 已解锁幂等（repeatable=false
       二次解锁拒 not_repeatable，不重复扣点）/ 上限达拒（max_repeat_reached）——
       本模块不重写判定链，仅收敛 job_id 为铸造职业。
  F-5  sp_panel_view 遍历 FORGE_SP_PANEL（文件序 SP-F1→F5），逐项计算 unlocked 状态；
       desc/scope 取 FORGE_SP_PANEL 静态定义（渲染不依赖内容配置 desc，确定性）。

铁律：零 NoneBot import；纯函数确定性（同刻同参必同值）；平台无关；不引入随机；
      每功能可追溯（文件头标注依据）。
"""
from __future__ import annotations

from typing import Any, Dict, List

from qbot_rpg.core.forge_tree import FORGE_JOB_ID
from qbot_rpg.core.proficiency import ProficiencyEngine

__all__ = [
    "FORGE_SP_PANEL",
    "sp_available",
    "sp_locked",
    "sp_panel_view",
    "sp_unlock",
]


# =====================================================================================
# FORGE_SP_PANEL：SP-F1~F5 解锁项定义（细化_2c2d §3.2；id/名称/作用域/描述）
# =====================================================================================
# 五项均为不可重复单次解锁（2c2d §3.2 定价行：默认 1 SP/次、repeatable=false）
FORGE_SP_PANEL: List[Dict[str, str]] = [
    {
        "id": "unlock_branch_tree",
        "name": "分支树视野",
        "scope": "/图纸 /锻造树",
        "desc": "解锁分支树视野：未解锁时 /图纸 分支段折叠（只显已解锁分支）、/锻造树 只显示主干",
    },
    {
        "id": "unlock_combine_3to1",
        "name": "3:1 合成",
        "scope": "合成引擎",
        "desc": "解锁 3:1 合成：未解锁时无 combine 升档入口（3 普通素材→1 稀有素材）",
    },
    {
        "id": "unlock_slot_tool",
        "name": "开孔",
        "scope": "开孔渠道",
        "desc": "解锁开孔：未解锁时开孔道具不可用、锻造不产出开孔道具",
    },
    {
        "id": "unlock_sets",
        "name": "套装",
        "scope": "/套装 + 套装技能",
        "desc": "解锁套装：未解锁时 /套装 拒绝、套装技能不生效（即使穿齐 5 件）",
    },
    {
        "id": "unlock_augment",
        "name": "客制",
        "scope": "/客制",
        "desc": "解锁客制：未解锁时 /客制 拒绝（GU-A1）；解锁后仍需宗师+最终强化武器",
    },
]

# SP-F1~F5 面板项 id 集合（【工程补白 F-2】未识别判定基准；确定性）
_PANEL_IDS: frozenset = frozenset(item["id"] for item in FORGE_SP_PANEL)


# =====================================================================================
# SP 引擎构造（本地兜底：FORGE_SP_PANEL 转引擎 sp_panel 定义，零 IO 确定性）
# =====================================================================================
def _forge_entry() -> Dict[str, Any]:
    """forge 实例条目（仅 sp_panel 段）：FORGE_SP_PANEL 转引擎 sp_panel 形态。

    【工程补白 F-1】cost=1 / repeatable=False / max_repeat=1（2c5a SP-05 默认 +
    2c2d §3.2「默认 1 SP/次 不可重复单次解锁」）；desc 复用 FORGE_SP_PANEL 静态描述。
    """
    return {
        "id": FORGE_JOB_ID,
        "sp_panel": [
            {
                "id": item["id"],
                "name": item["name"],
                "cost": 1,
                "repeatable": False,
                "max_repeat": 1,
                "desc": item["desc"],
            }
            for item in FORGE_SP_PANEL
        ],
    }


def _engine() -> ProficiencyEngine:
    """SP 引擎构造：注入 forge sp_panel 本地兜底定义（纯函数，每次新建无共享状态）。

    ProficiencyEngine 构造为纯函数（entries 注入 + 缺省兜底），同刻同参必同值；
    sp_available/unlock_count 不依赖 sp_panel，sp_unlock 依赖其查到 SP-F1~F5 定义。
    """
    return ProficiencyEngine(entries=[_forge_entry()])


# =====================================================================================
# 1) sp_available：可用 SP 点数（SP-06 双计：sp_earned - sp_used）
# =====================================================================================
def sp_available(player: Any) -> int:
    """可用 SP 点数（委托 ProficiencyEngine.sp_available(player, "forge")）。

    入参：player（玩家状态 dict，读 proficiency.forge.{sp_earned, sp_used}）。
    出参：可用 SP int（≥0）；player 非 Mapping / 无 proficiency.forge 节点 → 0。
    语义：SP-06 双计防重复扣点；每升 1 级 +sp_per_level（SP-01，默认 1）。
    """
    return _engine().sp_available(player, FORGE_JOB_ID)


# =====================================================================================
# 2) sp_unlock：SP 自选解锁（委托 ProficiencyEngine.unlock_item）
# =====================================================================================
def sp_unlock(player: Any, panel_id: Any) -> Dict[str, Any]:
    """SP 面板自选解锁（委托 ProficiencyEngine.unlock_item(player, "forge", panel_id)）。

    校验链（SP-05，由引擎承载，本模块只收敛 job_id）：
      - 未识别面板项 → {ok:False, reason:"panel_not_found"}
      - 可用 SP < cost → {ok:False, reason:"sp_insufficient"}
      - repeatable=false 已解锁 → {ok:False, reason:"not_repeatable"}（【工程补白 F-4】
        幂等：不重复扣点、不重复生效）
      - repeatable=true 达 max_repeat → {ok:False, reason:"max_repeat_reached"}
    通过：sp_used += cost、unlocks[panel_id] += 1（SP-06 双计），即时生效（SP-04）。
    出参：{ok, sp_used_delta, unlock_count, panel_id, panel_name}；拒绝 reason 见上。
    """
    return _engine().unlock_item(player, FORGE_JOB_ID, panel_id)


# =====================================================================================
# 3) sp_locked：未解锁判定（消费方：3:1 入口隐藏 / /套装、/客制 拒绝 / /图纸 分支折叠）
# =====================================================================================
def sp_locked(player: Any, panel_id: Any) -> bool:
    """SP 解锁项未解锁判定（消费方守卫；【工程补白 F-2/F-3】）。

    判定：panel_id 非空字符串且 ∈ FORGE_SP_PANEL id 集合 且
      ProficiencyEngine.unlock_count(player, "forge", panel_id) > 0 → False（已解锁）；
      否则 True（未解锁）。player 非 Mapping / 无 proficiency.forge → 0 → 锁定。
    未识别 panel_id → True（保守锁定，避免越权放开未知项）。

    入参：player（玩家状态 dict）、panel_id（SP-F1~F5 面板项 id）。
    出参：bool；True = 未解锁（消费方据此隐藏入口/拒绝指令/折叠分支）。
    """
    if not isinstance(panel_id, str) or not panel_id:
        return True
    if panel_id not in _PANEL_IDS:
        return True  # 【工程补白 F-2】未识别面板项保守锁定
    return _engine().unlock_count(player, FORGE_JOB_ID, panel_id) <= 0


# =====================================================================================
# 4) sp_panel_view：SP 面板数据源（供 /技能面板 渲染）
# =====================================================================================
def sp_panel_view(player: Any) -> List[Dict[str, Any]]:
    """SP 面板数据源（供 /技能面板 渲染；【工程补白 F-5】）。

    遍历 FORGE_SP_PANEL（文件序 SP-F1→F5），逐项输出：
      {id, name, scope, desc, unlocked}——unlocked = 该面板项已解锁（unlock_count > 0）。

    入参：player（玩家状态 dict）。
    出参：确定性 list（5 项，恒与 FORGE_SP_PANEL 同长同序）；纯读不改写。
    """
    prof = _engine()
    out: List[Dict[str, Any]] = []
    for item in FORGE_SP_PANEL:
        out.append({
            "id": item["id"],
            "name": item["name"],
            "scope": item["scope"],
            "desc": item["desc"],
            "unlocked": prof.unlock_count(player, FORGE_JOB_ID, item["id"]) > 0,
        })
    return out
