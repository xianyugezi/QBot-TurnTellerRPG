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

# 职业详情显示层翻译（2026-09-05：难度/武器类型枚举 → 中文；内容包可覆盖模板）
_JOB_DIFFICULTY_CN = {"simple": "上手简单", "advanced": "进阶", "complex": "复杂"}
_WEAPON_TYPE_CN = {"ridgeblade": "脊刃", "veinbow": "脉弓", "sword": "剑", "axe": "斧",
                   "bow": "弓", "longbow": "长弓", "lance": "枪", "dagger": "匕首", "hammer": "锤",
                   "staff": "法杖", "tome": "法术书"}
# 2026-09-05 用户需求：职业列表/详情独立指令
JOB_LIST_CMD = "职业"
JOB_LIST_CMD2 = "职业列表"  # 2026-09-05 别名（原 stub 词转正）
JOB_DETAIL_CMD = "职业详情"


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
    # 2026-09-07 zerc 实机反馈：职业列表换行显示（原「，」单行挤在一起）
    return "\n".join(parts)


def _job_list_render(ctx: Mapping[str, Any], page: int) -> str:
    """职业列表分页渲染（2026-09-07 zerc 拍板格式）：标题独立行 + `N. 职业（推荐）`
    行 + render_cake_tail（当前页：X/Y + Tip）。每页 DEFAULT_PAGE_SIZE 条。"""
    from qbot_rpg.core.templates import tpl_of  # noqa: PLC0415
    from qbot_rpg.core.message_format.list_render import (
        DEFAULT_PAGE_SIZE,
        render_cake_tail,
        resolve_page,
    )  # noqa: PLC0415

    jobs = _jobs_table(ctx)
    if not jobs:
        return "当前无可转职业（系统未配置 jobs 表）"
    items = [(jid, d) for jid, d in jobs.items() if isinstance(d, Mapping)]
    res = resolve_page(page, len(items), DEFAULT_PAGE_SIZE)
    if res.invalid:
        from qbot_rpg.commands.sender import format_tpl12  # noqa: PLC0415
        return format_tpl12(f"/转职 {page}")
    assert res.page is not None
    start = (res.page - 1) * DEFAULT_PAGE_SIZE
    slice_items = items[start:start + DEFAULT_PAGE_SIZE]
    lines = [tpl_of(ctx, "job_list", {"list": ""}).rstrip("\n") or "当前可转职业："]
    for i, (jid, d) in enumerate(slice_items, start + 1):
        name = str(d.get("name") or jid)
        rec = "（推荐）" if d.get("recommended_newbie") else ""
        lines.append(f"{i}. {name}{rec}")
    lines.append(render_cake_tail(
        res.page, res.total_pages,
        tip=tpl_of(ctx, "job_list_tip", {}),
        templates=ctx.get("templates")))
    return "\n".join(lines)


def _job_detail_text(ctx: Mapping[str, Any], job: Mapping[str, Any]) -> str:
    """职业详情面板（2026-09-05 新功能：职业详情 <序号|名称>；模板 job_tpl 可覆盖）。"""
    from qbot_rpg.core.templates import tpl_of  # noqa: PLC0415
    name = str(job.get("name") or job.get("id") or "")
    lines = [tpl_of(ctx, "job_detail_header", {"name": name})]
    if job.get("recommended_newbie"):
        lines.append(tpl_of(ctx, "job_detail_rec", {}))
    dif = str(job.get("difficulty") or "")
    if dif:
        lines.append(tpl_of(ctx, "job_detail_line",
                            {"k": "难度", "v": _JOB_DIFFICULTY_CN.get(dif, dif)}))
    ps = str(job.get("playstyle") or "")
    if ps:
        lines.append(tpl_of(ctx, "job_detail_line", {"k": "玩法", "v": ps}))
    tags = job.get("mechanic_tags")
    if isinstance(tags, list) and tags:
        lines.append(tpl_of(ctx, "job_detail_line",
                            {"k": "标签", "v": "、".join(str(t) for t in tags)}))
    # 武器类型（显示层翻译，未知类型原文兜底）
    wts = job.get("weapon_types")
    if isinstance(wts, list) and wts:
        lines.append(tpl_of(ctx, "job_detail_line",
                            {"k": "武器", "v": "、".join(_WEAPON_TYPE_CN.get(str(w), str(w)) for w in wts)}))
    # 资源轴：stats 表中文翻译（name 字段），无 → 原文
    ra = job.get("resource_axes")
    if isinstance(ra, list) and ra:
        stats_tbl = ctx.get("stats") if isinstance(ctx.get("stats"), Mapping) else {}
        ra_cn = []
        for r in ra:
            rs = str(r)
            sd2 = stats_tbl.get(rs) if isinstance(stats_tbl, Mapping) else None
            if isinstance(sd2, Mapping) and sd2.get("name"):
                ra_cn.append(str(sd2["name"]))
            else:
                ra_cn.append(rs)
        lines.append(tpl_of(ctx, "job_detail_line", {"k": "资源", "v": "、".join(ra_cn)}))
    growth = job.get("growth")
    if isinstance(growth, Mapping) and growth:
        stats_tbl = ctx.get("stats") if isinstance(ctx.get("stats"), Mapping) else {}
        g_parts = []
        for k, v in growth.items():
            if v is None:
                continue
            sd3 = stats_tbl.get(str(k)) if isinstance(stats_tbl, Mapping) else None
            kn = str(sd3.get("name") or k) if isinstance(sd3, Mapping) else str(k)
            g_parts.append(f"{kn}+{v}")
        if g_parts:
            lines.append(tpl_of(ctx, "job_detail_line", {"k": "成长", "v": " ".join(g_parts)}))
    tr = job.get("transform")
    if isinstance(tr, Mapping):
        tt = str(tr.get("transform_to") or tr.get("transform_skill") or "")
        dur = str(tr.get("duration") or "")
        tv = tt + (f"（时长 {dur}）" if dur and tt else "")
        if tv:
            lines.append(tpl_of(ctx, "job_detail_line", {"k": "形态", "v": tv}))
    desc = str(job.get("description") or "")
    if desc:
        lines.append(desc)
    return "\n".join(lines)


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
        # 2026-09-07 zerc 实机修复：Player 是 frozen dataclass——直接赋值抛
        # FrozenInstanceError 被 except 吞 → job_id 未改 → 落档旧职业（转职
        # 成功提示但档案不变）。frozen 形态用 dataclasses.replace 重建写回。
        try:
            import dataclasses  # noqa: PLC0415
            _nb = dataclasses.replace(player, job_id=job_id)
            ctx["player"] = _nb
            player = _nb
        except Exception:  # noqa: BLE001 - 重建失败回退直接赋值（非 frozen 可写）
            try:
                player.job_id = job_id
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
        # 无参 → 职业列表（2026-09-07：分页渲染——标题/行/当前页/Tip）
        return _job_list_render(ctx, 1)
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

    # 2026-09-05 独立指令：职业（列表）/ 职业详情 <序号|名称>
    def _job_list_cmd(parsed: Any, *a: Any, **k: Any) -> str:
        from qbot_rpg.core.templates import tpl_of  # noqa: PLC0415
        injected = k.get("ctx") if isinstance(k, dict) else None
        ctx2 = injected if isinstance(injected, MutableMapping) else _ctx(parsed)
        page = 1
        _args2 = list(getattr(parsed, "args", None) or [])
        if _args2 and str(_args2[0]).isdigit():
            page = int(str(_args2[0]))
            if page < 1:
                from qbot_rpg.commands.sender import format_tpl12  # noqa: PLC0415
                raw = getattr(parsed, "raw", None) or ""
                return format_tpl12(str(raw))
        return _job_list_render(ctx2, page)

    def _job_detail_cmd(parsed: Any, *a: Any, **k: Any) -> str:
        from qbot_rpg.core.templates import tpl_of  # noqa: PLC0415
        injected = k.get("ctx") if isinstance(k, dict) else None
        ctx2 = injected if isinstance(injected, MutableMapping) else _ctx(parsed)
        args2 = list(getattr(parsed, "args", None) or [])
        if not args2:
            return tpl_of(ctx2, "job_detail_usage")
        arg2 = str(args2[0]).strip()
        job = resolve_job(ctx2, arg2) or _find_job_by_index(ctx2, arg2)
        if job is None:
            return tpl_of(ctx2, "job_not_found", {"job": arg2, "list": _job_list_text(ctx2)})
        return _job_detail_text(ctx2, job)

    router.register(CommandSpec(JOB_LIST_CMD, handler=_job_list_cmd))
    router.register(CommandSpec(JOB_LIST_CMD2, handler=_job_list_cmd))
    router.register(CommandSpec(JOB_DETAIL_CMD, handler=_job_detail_cmd))
    return router
