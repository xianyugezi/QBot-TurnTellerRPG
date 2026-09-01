"""M13 /转职 指令（qbot_rpg/commands/job_commands.py · M13 批14 路14A）。

依据 docs/细化/细化_4f_基础指令组契约.md（转职语法/职业列表/继承覆盖）与
批13 装配（ctx["jobs"] 注入）+ 批14C（core/job_slots.py 转职快照/重排）。

功能：
  - /转职：无参 → 职业列表（含推荐角标）；有参 → 职业名/序号解析 → 校验
    ∈ ctx["jobs"] → 转职执行（player.job_id 更新 + 技能位重排落档）→ 成功消息。
  - 复用 register_commands.resolve_job（显示名/job_id 双形态）+ default_job。
  - 转职后技能位重排：core.job_slots.rearrange_job_slots + save_rearranged_slots
    （新职业视角装配 + job_restrict 过滤 + 存档迁移）。

工程补白（契约未显式处收敛，显式标注供审查）：
  P-1  转职不设冷却/费用（细化_4f 无冷却字段——覆盖审计_H P1-9：routes/继承
       覆盖字段全仓 0 落点，契约文档实际未含；以工程补白记录待契约补全）。
  P-2  转职写 ctx["player"] 可变字典的 job_id + persistent_state 挂 job_slots
       段（14C 接口）；装配层落档由 make_context 完成（零 IO 本层）。
  P-3  /转职 列表复用 jobs 表 recommended_newbie 标记（「（推荐）」角标）。

铁律：平台无关（零 NoneBot import）；文件头零定时器/零睡眠；不 git commit。
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, MutableMapping, Optional

from qbot_rpg.commands.register_commands import resolve_job
from qbot_rpg.commands.router import CommandSpec

JOB_CMD = "转职"


def _jobs_table(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    jobs = ctx.get("jobs")
    return jobs if isinstance(jobs, Mapping) else {}


def _job_list_text(ctx: Mapping[str, Any]) -> str:
    """职业列表文案（含推荐角标）。"""
    jobs = _jobs_table(ctx)
    if not jobs:
        return "当前无可转职业（系统未配置 jobs 表）"
    parts: list[str] = []
    for i, (jid, d) in enumerate(jobs.items(), 1):
        if not isinstance(d, Mapping):
            continue
        name = str(d.get("name") or jid)
        rec = "（推荐）" if d.get("recommended_newbie") else ""
        parts.append(f"{i}. {name}{rec}")
    return "，".join(parts)


def _find_job_by_index(ctx: Mapping[str, Any], arg: str) -> Optional[dict]:
    """序号形态（/转职 2）→ 第 N 个职业。"""
    jobs = _jobs_table(ctx)
    if not arg.isdigit():
        return None
    idx = int(arg)
    if idx < 1:
        return None
    for i, (jid, d) in enumerate(jobs.items(), 1):
        if i == idx and isinstance(d, Mapping):
            return {"id": str(jid), **d}
    return None


def _persistent_state_of(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """persistent_state 定位（对齐 investigate_commands 先例三级链）。"""
    ps = ctx.get("persistent_state")
    if isinstance(ps, MutableMapping):
        return ps
    player = ctx.get("player")
    ps2 = getattr(player, "persistent_state", None) if not isinstance(player, Mapping) else \
        player.get("persistent_state")
    if isinstance(ps2, MutableMapping):
        return ps2
    return ctx  # 兜底：ctx 自身（装配层无 ps 时降级）


def _apply_job_switch(
    ctx: MutableMapping[str, Any], job: Mapping[str, Any]
) -> Mapping[str, Any]:
    """转职执行：更新 player job_id + 技能位重排落档（14C 接口）。"""
    job_id = str(job.get("id") or "")
    player = ctx.get("player")
    if isinstance(player, MutableMapping):
        player["job_id"] = job_id
        player["job_name"] = str(job.get("name") or "")
    elif player is not None and not isinstance(player, Mapping):
        try:
            player.job_id = job_id  # dataclass 形态
        except Exception:  # noqa: BLE001 - 只读对象防御
            pass
    ctx["job_id"] = job_id
    ctx["job_name"] = str(job.get("name") or "")
    # 技能位重排（14C：新职业视角装配 + job_restrict 过滤）
    try:
        from qbot_rpg.core.job_slots import rearrange_job_slots, save_rearranged_slots  # noqa: PLC0415

        ps = _persistent_state_of(ctx)
        player_map: MutableMapping[str, Any] = {"persistent_state": ps}
        snap = rearrange_job_slots(ctx, job_id)
        save_rearranged_slots(player_map, snap, job_id=job_id,
                              at=str(ctx.get("now") or ""))
        ctx["skill_slots"] = snap
    except Exception:  # noqa: BLE001 - 装配失败不阻断转职（落档由装配层兜底）
        pass
    return job


def cmd_job(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/转职 [职业名|序号]：无参 → 职业列表；有参 → 转职执行。"""
    from qbot_rpg.core.templates import tpl_of  # noqa: PLC0415

    if parsed.error:
        from qbot_rpg.commands.sender import format_tpl12  # noqa: PLC0415

        raw = getattr(parsed, "raw", None)
        if raw:
            frag = str(raw)
        else:
            cmd = getattr(parsed, "command", None) or ""
            args = list(getattr(parsed, "args", None) or [])
            tail = (" " + " ".join(str(a) for a in args)) if args else ""
            frag = f"/{cmd}{tail}"
        return format_tpl12(frag)
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        # 无参 → 职业列表
        return tpl_of(ctx, "job_list", {"list": _job_list_text(ctx)})
    arg = str(args[0]).strip()
    # 解析（名称/job_id/序号三形态）
    job = resolve_job(ctx, arg) or _find_job_by_index(ctx, arg)
    if job is None:
        return tpl_of(ctx, "job_not_found", {"job": arg, "list": _job_list_text(ctx)})
    _apply_job_switch(ctx, job)
    rec = "（推荐）" if job.get("recommended_newbie") else ""
    return tpl_of(ctx, "job_switch_success", {
        "job": str(job.get("name") or job.get("id") or ""), "rec": rec,
    })


def register_job_commands(
    router: Any, *, make_context: Optional[Callable[[Any], dict]] = None
) -> Any:
    """把 /转职 注册进 Router（对齐 register_commands 先例）。"""
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】job_commands.register_job_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _job(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_job(parsed, injected)
        return cmd_job(parsed, _ctx(parsed))

    router.register(CommandSpec(JOB_CMD, handler=_job))
    return router
