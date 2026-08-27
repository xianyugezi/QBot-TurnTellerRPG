"""ReloadResult 人话翻译（WIR-09/10）：ReloadResult → TPL-15~18 渲染串。

依据：
  - 细化_M6_热重载接线（D3）§1.4（TPL-15~18 四模板文案，逐字抄录，禁止缩写）
  - 细化_3e2_热重载契约 SNAP-3 / BLK-3（人话 = 原因 + 正确用法 + 下一步）
  - 细化_3e_loader校验接线 D-06（commands 层翻译；content 零 NoneBot、不拼用户文案）
  - 细化_3d_消息模板规范 §1.2（TPL 注册表；本模块新增 TPL-15~18 回填）
  - 【规则】L170（文案禁词：必须/强制/上限/封顶/拒绝——四模板禁词扫描通过）

本模块只做「ReloadResult → TPL 渲染串」纯函数翻译，零 NoneBot import；
/重载 结果与自动重载提示共用本翻译出口（WIR-10 统一发送出口）。
"""

from __future__ import annotations

from typing import Tuple

from qbot_rpg.content.hot_reload import ReloadResult
from qbot_rpg.content.models import PackError

# -------------------------------------------------------------------------------------
# TPL-15~18 模板（D3 §1.4 逐字抄录；变量渲染期代入；四模板禁词扫描通过）
# -------------------------------------------------------------------------------------
# TPL-15 成功：result.ok（N = len(changed_modules)）
TPL_15_SUCCESS = "✅ 已重载【{pack}】：{N} 个模块变更生效"
# TPL-15 头部（cmd_gm_reload 拼接后端 summary 尾部用；尾部 = reload_success_summary）
TPL_15_HEAD = "✅ 已重载【{pack}】："
# TPL-16 失败回退：result.restored（原因 = 首个红拦人话，detail 拼接）
TPL_16_ROLLBACK = "❌ 重载失败，已回退旧配置：{原因}。请修正配置后保存，或手动 /重载 重试"
# TPL-17 连续失败暂停：result.paused（N = consecutive_failures）
TPL_17_PAUSED = "❌ 连续 {N} 次重载失败，已暂停自动检测；请修正配置后手动 /重载"
# TPL-18 无变更：轮询检测无新事件（no change）
TPL_18_NO_CHANGE = "✅ 内容包无变更，无需重载"

# 全部 TPL-15~18 模板文本（禁词扫描用；【规则】L170：必须/强制/上限/封顶/拒绝）
ALL_RELOAD_TPL_TEXT: Tuple[str, ...] = (
    TPL_15_SUCCESS,
    TPL_16_ROLLBACK,
    TPL_17_PAUSED,
    TPL_18_NO_CHANGE,
)

# 【规则】L170 红线词（文案禁词扫描）
FORBIDDEN_WORDS: Tuple[str, ...] = ("必须", "强制", "上限", "封顶", "拒绝")


def reload_success_summary(result: ReloadResult) -> str:
    """TPL-15 尾部（GmBackend.reload_content 的 summary 字段：`{N} 个模块变更生效`）。

    cmd_gm_reload 用 TPL_15_HEAD 拼接成完整 TPL-15：
        TPL_15_HEAD.format(pack=...) + reload_success_summary(result)
            == TPL_15_SUCCESS.format(pack=..., N=len(result.changed_modules))
    """
    return f"{len(result.changed_modules)} 个模块变更生效"


def first_error_reason(errors: Tuple[PackError, ...]) -> str:
    """首个红拦人话（D3 §1.4 TPL-16「原因 = 首个红拦人话，detail 拼接」）。

    结构化：`{module}.json {field} {kind}（{detail 前 3 项}）`；无红拦 → 通用兜底。
    该人话为动态拼接（非模板本体），不参与四模板禁词扫描（TC-WIR-07 只扫四模板）。
    """
    if not errors:
        return "配置校验未通过"
    e = errors[0]
    where = f"{e.module}.json"
    if e.field and e.field != f"{e.module}.json":
        where += f" {e.field}"
    detail = dict(e.detail or {})
    detail_str = "；".join(f"{k}={v}" for k, v in list(detail.items())[:3])
    if detail_str:
        return f"{where} {e.kind}（{detail_str}）"
    return f"{where} {e.kind}"


def render_reload_result(
    result: ReloadResult,
    *,
    consecutive_failures: int | None = None,
) -> str:
    """ReloadResult → TPL-15~18 人话渲染串（WIR-09/10，四路径判定）。

    判定优先级（对齐 D3 §1.4 触发条件）：
      1. result.paused      → TPL-17（连续失败暂停，N = consecutive_failures）
      2. result.restored    → TPL-16（失败回退，原因 = 首个红拦人话）
      3. result.no_change   → TPL-18（轮询无新事件，不重载）
      4. result.ok          → TPL-15（成功，N = len(changed_modules)）
      5. 其余（ok=False 且未回退的异常兜底）→ TPL-16 兜底

    :param consecutive_failures: 连续失败次数（result.paused 时模板 N 需要；
        缺省回退 1——ReloadResult 自身不携带该计数，调用方可从
        watcher.consecutive_failures 取，见 WIR-09 备注）。
    """
    if result.paused:
        n = consecutive_failures if consecutive_failures is not None else 1
        return TPL_17_PAUSED.format(N=n)
    if not result.ok and result.restored:
        return TPL_16_ROLLBACK.format(原因=first_error_reason(result.errors))
    if result.no_change:
        return TPL_18_NO_CHANGE.format()
    if result.ok:
        return TPL_15_SUCCESS.format(pack=result.pack_id, N=len(result.changed_modules))
    # 兜底：ok=False 且未标记回退（如轮询异常路径）→ 仍走失败回退文案
    return TPL_16_ROLLBACK.format(原因=first_error_reason(result.errors))


__all__ = [
    "TPL_15_SUCCESS",
    "TPL_15_HEAD",
    "TPL_16_ROLLBACK",
    "TPL_17_PAUSED",
    "TPL_18_NO_CHANGE",
    "ALL_RELOAD_TPL_TEXT",
    "FORBIDDEN_WORDS",
    "first_error_reason",
    "reload_success_summary",
    "render_reload_result",
]
