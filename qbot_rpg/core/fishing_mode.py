"""M10 批5·路5B：钓鱼模式三态路由（qbot_rpg/core/fishing_mode.py）——mode 行为矩阵 + 门控。

文件名：qbot_rpg/core/fishing_mode.py
创建时间：2026-08-31
作者：Hermes 子agent-5B（M10 钓鱼实现组批5·路5B：mode 三态路由）

功能描述（T17 · 细化_2c1b §2.4 模式前缀 + §六 TC-09/14）：
  - mode_of(ctx) -> str：settings.fishing.mode 归一（full/simple/off；非法/缺失
    回落 full，对齐运行期容错口径，V4 枚举硬错归校验器）。
  - mode_matrix() -> dict：三态行为矩阵（full 完整 FSM / simple 单消息直出无等待
    鱼讯鱼王 / off 全拒绝）——本模块为唯一权威矩阵，供测试与文档断言。
  - feature_available(mode, feature) -> bool：full 专属功能门控——等待/鱼讯/收杆/
    鱼王是否在当前 mode 可达；simple 下 king_event 不可达 → 金闪永不出现（TC-13
    金闪隔离）；off 下 /钓鱼 /收杆 /鱼讯 全拒（GU-01）。
  - command_allowed(mode, command) -> bool：指令可达性（fish/bite/reel 三指令）。
  - king_available / direct_catch / rejects_all：矩阵行便捷门控。

依据：
  - docs/细化/细化_2c1b_钓鱼流程状态机.md §2.4（模式前缀 full/simple/off：full
    S0→S1→S2→S3→{ST,SL,BOSS} 完整状态机 / simple S0→S1→ST 短接——/钓鱼 单消息
    直出，无等待/鱼讯/鱼王，保留鱼种/图鉴/冠级/饵/熟练 / off 所有钓鱼指令拒绝）
    + §六 TC-09（mode 路由）/ TC-14（simple 出鱼无鱼讯消息实例）
  - 定稿 v1.0.1 L4（simple 直出）/ L67（off 拒绝）/ L73（mode 三态）
  - docs/m10_shared_contract.md §三（mode 路由）/ §四（R-04 mode 约束）
  - docs/m10_接口摸底.md §九（坑位：rng 注入、零定时器、M43 探针措辞）
模式参考：
  - qbot_rpg/core/fishing_settings.py（MODE_VALUES 三态枚举单一事实源，本模块复用）
  - qbot_rpg/core/fishing.py FishingEngine._mode（运行期 mode 归一同口径）

铁律：零 NoneBot import；纯函数确定性零 IO 零定时器/零睡眠；docstring 勿写字面
      定时器调用字样（M43 探针，措辞统一「零定时器/零睡眠」）；零 emoji；本路独占
      本文件 + tests/unit/test_fishing_mode.py。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

from qbot_rpg.core.fishing_settings import MODE_VALUES, fishing_cfg

# =====================================================================================
# mode 常量（三态枚举单一事实源 = fishing_settings.MODE_VALUES，本模块复用不重列）
# =====================================================================================
MODE_FULL: str = "full"      # 完整流程：S0→S1→S2→S3→{ST,SL,BOSS}
MODE_SIMPLE: str = "simple"  # 单消息直出：S0→S1→ST（无等待/鱼讯/鱼王）
MODE_OFF: str = "off"        # 关闭：所有钓鱼指令拒绝

# mode 中文名（文档/测试断言用；渲染端批6 模板化，本模块零文案职责）
MODE_LABELS: Dict[str, str] = {
    MODE_FULL: "完整流程",
    MODE_SIMPLE: "单消息直出",
    MODE_OFF: "关闭",
}

# 功能特征键（mode_matrix 行键 + feature_available 入参）
FEATURE_WAIT: str = "wait"   # 等待期（S2 实例）
FEATURE_BITE: str = "bite"   # 鱼讯（S3 实例）
FEATURE_REEL: str = "reel"   # 收杆三选一
FEATURE_KING: str = "king"   # 鱼王可达（金闪只可能出现在猛烈鱼讯，TC-13 隔离）

# 指令键（command_allowed 入参）
CMD_FISH: str = "fish"       # /钓鱼
CMD_BITE: str = "bite"       # /鱼讯
CMD_REEL: str = "reel"       # /收杆

# 矩阵行键全集（mode_matrix 每行键序，供测试断言与文档引用）
MATRIX_KEYS: tuple = ("path", "wait", "bite", "reel", "king", "direct", "reject_all")


# =====================================================================================
# mode 归一（纯函数确定性：非法/缺失回落 full，对齐运行期容错口径）
# =====================================================================================
def mode_of(ctx: Mapping[str, Any]) -> str:
    """settings.fishing.mode 归一（契约 §三 mode 路由 + 定稿 L73 三态）。

    入参：ctx —— settings 全量 dict / settings.fishing 段 / ctx 形态均可
          （fishing_cfg 三态容错，A-1）。
    出参：full/simple/off 三态之一；非法值/缺失/非 str → full 兜底（V4 枚举硬错
    归校验器，读段不拦——对齐 fishing_cfg A-4 口径）。
    纯函数确定性零 IO 零定时器/零睡眠。
    """
    cfg = fishing_cfg(ctx)
    mode = cfg.get("mode")
    if isinstance(mode, str) and mode in MODE_VALUES:
        return mode
    return MODE_FULL


def _normalize_mode(mode: object) -> str:
    """mode 值归一（对象入参容错）：非 (full,simple,off) → full 兜底。"""
    if isinstance(mode, str) and mode in MODE_VALUES:
        return mode
    return MODE_FULL


# =====================================================================================
# 三态行为矩阵（细化 §2.4 + TC-09/14 唯一权威矩阵）
# =====================================================================================
def mode_matrix() -> Dict[str, Dict[str, object]]:
    """三态行为矩阵（细化 §2.4 + TC-09/14，供测试与文档断言）。

    full:   path=S0→S1→S2→S3→{ST,SL,BOSS} 完整状态机——等待+鱼讯+收杆三选一+鱼王；
    simple: path=S0→S1→ST 短接——/钓鱼 单消息直出（无等待/鱼讯/鱼王），保留鱼种/
            图鉴/冠级/饵/熟练（direct=True，settle 链路走结算）；
    off:    path=全拒绝——/钓鱼 /收杆 /鱼讯 全拒，不进入任何状态（reject_all）。

    每行键（MATRIX_KEYS 序）：path（状态路径）/ wait（等待期）/ bite（鱼讯）/
    reel（收杆三选一）/ king（鱼王可达）/ direct（单消息直出）/ reject_all（全拒）。
    纯函数确定性零 IO。
    """
    return {
        MODE_FULL: {
            "path": "S0->S1->S2->S3->{ST,SL,BOSS}",
            "wait": True,    # S2 等待期实例
            "bite": True,    # S3 鱼讯实例（三类 + 金闪覆写位）
            "reel": True,    # 收杆三选一（满力/自动/止损）
            "king": True,    # 鱼王可达（TR-10 BOSS 战 + 金闪）
            "direct": False,
            "reject_all": False,
        },
        MODE_SIMPLE: {
            "path": "S0->S1->ST",
            "wait": False,   # 无 S2 实例（TR-03 不可达，TC-14）
            "bite": False,   # 无 S3 实例（无鱼讯消息实例，TC-09/14）
            "reel": False,   # 无收杆三选一（直接出鱼）
            "king": False,   # 鱼王不可达 → 金闪永不出现（TC-13 隔离）
            "direct": True,  # /钓鱼 单消息直出
            "reject_all": False,
        },
        MODE_OFF: {
            "path": "全拒绝（不进入任何状态）",
            "wait": False,
            "bite": False,
            "reel": False,
            "king": False,
            "direct": False,
            "reject_all": True,  # /钓鱼 /收杆 /鱼讯 全拒（GU-01）
        },
    }


# =====================================================================================
# 门控（full 专属功能可达性 / 指令可达性）
# =====================================================================================
def feature_available(mode: object, feature: str) -> bool:
    """功能门控：feature ∈ {wait, bite, reel, king} 是否在当前 mode 可达。

    - full：等待/鱼讯/收杆/鱼王 全可达；
    - simple：等待/鱼讯/收杆/鱼王 全不可达（king_event 不可达 → 金闪永不出现，
      TC-13 金闪隔离；无 S2/S3 实例，TC-14）；
    - off：全不可达（不进入任何状态）。
    未知 feature → False（保守拒绝）；mode 非法回落 full（运行期容错口径）。
    纯函数确定性零 IO 零定时器/零睡眠。
    """
    row = mode_matrix().get(_normalize_mode(mode))
    if row is None or feature not in row:
        return False
    return bool(row.get(feature))


def king_available(mode: object) -> bool:
    """鱼王/金闪可达门控：仅 full 可达（simple 下 king_event 不可达 → 金闪永不
    出现；off 下全拒）。调用方（指令壳/鱼王触发接线）据此决定是否走
    fishing_king.king_event_available 判定链。"""
    return feature_available(mode, FEATURE_KING)


def direct_catch(mode: object) -> bool:
    """单消息直出门控：仅 simple（/钓鱼 直接出鱼，无等待/鱼讯/鱼王）。"""
    return feature_available(mode, "direct")


def rejects_all(mode: object) -> bool:
    """全拒绝门控：仅 off（所有钓鱼指令拒绝，GU-01）。"""
    return feature_available(mode, "reject_all")


def command_allowed(mode: object, command: str) -> bool:
    """指令可达性（GU-01 模式路由 + TC-09）：

    - off：/钓鱼 /收杆 /鱼讯 全拒（reject_all）；
    - simple：仅 /钓鱼 可达（单消息直出）；/收杆 /鱼讯 拒绝（无 S2/S3 实例）；
    - full：三指令全可达（完整流程）。
    未知 command → False（保守拒绝）。mode 非法回落 full。
    纯函数确定性零 IO。
    """
    m = _normalize_mode(mode)
    if m == MODE_OFF:
        return False
    if m == MODE_SIMPLE:
        return command == CMD_FISH
    return command in (CMD_FISH, CMD_BITE, CMD_REEL)


__all__ = [
    # mode 常量
    "MODE_FULL", "MODE_SIMPLE", "MODE_OFF", "MODE_LABELS",
    # 特征/指令键
    "FEATURE_WAIT", "FEATURE_BITE", "FEATURE_REEL", "FEATURE_KING",
    "CMD_FISH", "CMD_BITE", "CMD_REEL", "MATRIX_KEYS",
    # mode 归一
    "mode_of",
    # 行为矩阵
    "mode_matrix",
    # 门控
    "feature_available", "king_available", "direct_catch", "rejects_all",
    "command_allowed",
]
