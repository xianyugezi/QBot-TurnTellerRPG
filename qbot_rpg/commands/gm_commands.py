"""GM 指令接线 gm_commands.py（M4 批次6·路G2 · qbot_rpg/commands/gm_commands.py）。

依据：
  - m4_shared_contract.md §2.3（GM 指令：/gm 权限三级 + 静默 + 留痕 + 禁绑；**GM 指令清单以
    分隔符规范 L160 长清单为准（+设置）**）+ §2.2（列表 5 条/页上限、页脚固定 TPL-08、
    页码越界夹取 +「已到最后一页」2026-08-27 用户裁决②、0/负数/非数字 → TPL-12、
    错误模板统一、emoji 纪律：M5 裁决不用 emoji——GM 结果前缀（日志/编辑/设置等
    数据型功能图标）一律降级纯文本，仅 ✅/❌ 功能性标记 + 排版符号）
  - docs/细化/细化_5b_GM指令契约.md（§1 权限模型：三级权限 机主/GM/普通玩家、判定优先级、
    静默语义（无权限→直接无视不报错不提示不写审计）、权限存储不进玩家存档、绑定层+执行层
    双检查；§2 GM 指令集 G1-G14 逐条契约；§3.1 /日志 双分支（权限 ≥ GM → 系统日志）；
    §3.2 快捷禁绑（C02，防权限绕过）；§4 审计：E1-E6 事件类、字段、成败皆痕、无权限不写）
  - docs/审查参考/指令分隔符统一规范.md L160（**GM 指令清单：重载/封禁/日志/编辑/设置**，
    绑定目标为 GM 指令 → 拒绝）+ L120-121/L128（GM 永不快捷、强制 / 前缀）+ L169-171
    （执行层权限二次检查，GM 指令即使被意外绑定也不执行）
  - 2026-08-27 用户裁决②（页码超总页数 → 夹取最后一页 +「已到最后一页」；0/负数/非数字 →
    TPL-12）
  - docs/细化/细化_3d_消息模板规范.md（TPL-08 页脚 / TPL-12 指令出错；§四 emoji 禁令——
    M5 裁决：GM 结果前缀数据型功能图标一律降级纯文本；§5.4 错误文案唯一源 errors.py D-04）
  - qbot_rpg/commands/router.py（PERM_OWNER/PERM_GM/PERM_USER 权限常量、CommandSpec.is_gm
    强制前缀位、check_shortcut_binding GM 禁绑 C02、is_gm_command 判定）

职责（细化_3a §1.3 壳层职责 · 唯一 GM 指令执行壳）：把 /gm 指令集（L160 长清单 =
重载/封禁/日志/编辑/设置）从 Router 接到 GM 后端引擎——权限三级检查（admin/manager/player，
一一对应 机主/GM/普通玩家，5b §1.1）、静默执行（成功不回显群聊，成功摘要进审计留痕）、
留痕（操作日志 audit_log 追加写，成败皆写；无权限不写）、GM 禁绑（禁止快捷绑定 GM 指令
防权限绕过）、GM 强制 / 前缀（is_gm=True → 路由层 W07/L128 拦截裸发）、/日志 列表
（5 条/页 + TPL-08 页脚 + 裁决② 夹取）、错误统一 TPL-12（sender.format_tpl12，
文案唯一源 errors.py D-04）。

铁律（m4_shared_contract §0 / 3a R1）：**零 NoneBot import**（GM 后端/权限存储/审计存储
全部经 ctx 注入，可脱离平台单测）、纯函数、确定性（now 由 ctx 注入）；工程补白一律
【工程补白】标注；装饰性 emoji 全局禁用（M5 裁决不用 emoji：仅 ✅/❌ 功能性标记 +
排版符号 | → × / 「」【】；GM 结果前缀等数据型功能图标一律降级纯文本）。
本模块只做「装配接线 + 权限 + 渲染 + 留痕」，
业务执行（重载内容包/封禁玩家/读系统日志/编辑器链接/改设置）全部委托 GM 后端引擎。

--------------------------------------------------------------------------------
消费接口（GM 后端引擎，批次6/7 装配注入 ctx["gm_backend"]；本层按以下契约签名消费，
不做二次判断；未注入 → 处理器抛 RuntimeError「【待接线】…」防御路径，不阻塞本层导入）：
  reload_content(pack_name, ctx) -> dict
      {ok: True, summary: str, failures: [str...]}   热重载结果摘要 + 失败项清单（5b G1）
      {ok: False, message: str}                      重载失败（坏配置拒绝，5b G1）
  ban_player(qq_id, duration, reason, ctx) -> dict
      {ok: True, expires: str|None, message: str}    封禁确认 + 到期时间（5b G10）
      {ok: False, message: str}                      封禁失败
  recent_audit(count, ctx) -> list[dict]             最近系统日志事件（5b G8；count ≤ 50）
  editor_link(role_level, ctx) -> dict
      {url: str, hint: str}                          编辑器链接 + 权限级提示（5b G13）
  apply_setting(key, value, ctx) -> dict
      {ok: True, current: str, message: str}         设置切换结果（5b G14）
      {ok: False, message: str}                      设置失败
权限存储 ctx["permission_store"]（批次7 注入，5b §1.2 admin_users 表）：
  store.user_of(qq_id) -> GmUser   权限唯一事实来源（角色 + per-command 授权）；
                                   None/缺省时按 ctx["role"]/ctx["granted_commands"] 兜底
审计存储 ctx["audit_store"]（批次7 注入，5b §4.2 audit_log 表，追加写不可删）：
  store.append(record) -> None    留痕落库；无权限调用不写（静默，防探测）
本层同时把留痕记录追加进 ctx["audit_log"] 列表（纯逻辑收集，测试与批次7 消费同一数据源）。

--------------------------------------------------------------------------------
【工程补白 · 显式标注】
  1) **GM 指令清单 = L160 长清单（5 条）**：重载/封禁/日志/编辑/设置。5b §2.1 另有 G2-G7/G9/G11/
     G12（备份/恢复/存档导出/调试/测试/广播/玩家查询/解封/封禁列表）等 9 条不在本批范围——
     m4 §2.3 明令「GM 指令清单以分隔符规范 L160 长清单为准（+设置）」，本模块只实现 L160
     清单内 5 条；其余留待批次6/7 其它路或后续批次（按 5b §2.1 总表登记）。
  2) **静默执行（父任务：成功不回显）**：有权限执行成功 → message=None（不回显群聊），
     成功摘要按 5b §2.2 逐条文案生成并写入审计 detail 字段（5b §4.2：detail =「成功摘要」），
     GM 经 /日志（GM 版 = 系统日志）自查。5b TC-02/TC-09「返回摘要」语义在批次7 装配层可选用
     audit.detail 私发/回显复现；本层纯逻辑侧不回显成功。
  3) **静默是安全边界，留痕是信任边界**（5b §0）：无权限调用 GM 指令 → 零出站、零审计
     （GmResult.silent=True），与「被封玩家发游玩指令 → 人话提示」严格区分（后者非本模块职责）。
  4) **/日志 双分支**：本层仅实现 GM 版（发令者权限 ≥ manager → 系统日志，5b G8/L2787）；
     普通玩家版（冒险日志）由其它指令路承接，不在本模块（GM 身份优先，L2787 口径）。
  5) **/日志 页码 + 条数=N 并存**：`/日志 [页码] [条数=N]`。条数=N 控制后端拉取窗口
     （默认 20 sys_log.default_show，上限 50 sys_log.max_entries，细化_0 R-02）；展示层按
     5 条/页横切 + TPL-08 页脚 + 裁决② 夹取。页码 0/负数/非数字 → TPL-12（裁决②）。
  6) **权限角色命名**：父任务三级命名 admin/manager/player = 5b 机主/GM/普通玩家 =
     router.PERM_OWNER/PERM_GM/PERM_USER，一一对应（_ROLE_ALIASES 双向归一，见 role_of）。
  7) **per-command 下授**：manager 执行「机主专属」指令（本批 = 设置，5b G14）需
     granted_commands 显式授权（5b §1.1.1 可另行下授）；未下授 → 静默（TC-04 口径）。
  8) **audit_ts_hmac**：5b §4.2 审计行校验值（防篡改可选开关，默认开）；HMAC-SHA256，
     密钥经 ctx["audit_hmac_key"] 注入（默认 None = 不落校验值，配置到位批次7 开启）。
  9) **GM 禁绑 / 强制前缀接线**：禁绑 = router.check_shortcut_binding(gm_commands=GM_COMMANDS)
     （绑定层 C02 + 执行层 E02 二次检查双保险，L160/L169-171）；强制前缀 = is_gm=True 注册
     （路由层 _trigger_allowed W07/L128 拦截裸发）+ parsers.DEFAULT_PREFIX_REQUIRED 已含 5 条。
  10) 本模块的玩家上下文工厂 make_context（NoneBot 事件 + 存储 → ctx dict）由装配层注入
      （register_gm_commands 的 make_context 参数），**批次6/7 装配待接线**；注入前本层可纯
      函数单测（直接构造 ctx + 注入替身 gm_backend/permission_store/audit_store）。
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, FrozenSet, List, Mapping, MutableMapping, Optional

from qbot_rpg.core.message_format.list_render import (
    DEFAULT_PAGE_SIZE,
    LAST_PAGE_HINT,
    render_list_page_text,
    resolve_page,
)

# 同包兄弟模块：相对导入（G0 架构门禁 test_commands_web_not_depended 不产生
# `qbot_rpg.commands` 前缀反向依赖边；同层兄弟引用架构合规，与 sender.py 同口径）。
from .parsers import parse_int
from .router import (
    PERM_GM,
    PERM_OWNER,
    PERM_USER,
    CommandSpec,
    check_shortcut_binding,
)
from .sender import format_tpl12

__all__ = [
    # L160 长清单指令名 / GM 清单
    "GM_CMD_RELOAD", "GM_CMD_BAN", "GM_CMD_LOG", "GM_CMD_EDIT", "GM_CMD_SETTINGS",
    "GM_COMMANDS", "GM_COMMAND_LEVEL", "GM_COMMAND_INDEX", "GM_DEFAULT_GRANT",
    "GM_PREFIX_REQUIRED",
    # 权限三级（admin/manager/player ↔ 机主/GM/普通玩家）
    "ROLE_ADMIN", "ROLE_MANAGER", "ROLE_PLAYER",
    "GmUser", "GmPermResult", "role_of", "check_gm_permission",
    # 结果模型（静默 / 错误）
    "GmResult", "silent_result", "success_result", "error_result",
    # 留痕（操作日志）
    "AUDIT_HMAC_FIELDS", "build_audit_record", "audit_hmac", "record_audit",
    # 指令处理器
    "cmd_gm_reload", "cmd_gm_ban", "cmd_gm_log", "cmd_gm_edit", "cmd_gm_settings",
    "handle_gm_command",
    # 渲染
    "LOG_PAGE_SIZE", "LOG_DEFAULT_SHOW", "LOG_MAX_ENTRIES", "BAN_DEFAULT_DURATION",
    "render_log_line", "render_log_page",
    # GM 禁绑 / 强制前缀
    "is_gm_command_name", "gm_requires_prefix", "gm_binding_guard",
    # 装配
    "register_gm_commands",
]

# ---------------------------------------------------------------------------
# L160 长清单（指令分隔符统一规范 L160：绑定目标为 GM 指令（重载/封禁/日志/编辑/设置）→ 拒绝）
# ---------------------------------------------------------------------------

GM_CMD_RELOAD = "重载"      # G1
GM_CMD_BAN = "封禁"         # G10
GM_CMD_LOG = "日志"         # G8
GM_CMD_EDIT = "编辑"        # G13
GM_CMD_SETTINGS = "设置"    # G14

# GM 指令清单（m4 §2.3：以分隔符规范 L160 长清单为准）
GM_COMMANDS: FrozenSet[str] = frozenset({
    GM_CMD_RELOAD, GM_CMD_BAN, GM_CMD_LOG, GM_CMD_EDIT, GM_CMD_SETTINGS,
})

# 5b §2.1 G 序号（本批 L160 清单内指令；审计展示 /日志 行前缀用）
GM_COMMAND_INDEX: Mapping[str, str] = {
    GM_CMD_RELOAD: "G1",
    GM_CMD_BAN: "G10",
    GM_CMD_LOG: "G8",
    GM_CMD_EDIT: "G13",
    GM_CMD_SETTINGS: "G14",
}

# GM 强制 / 前缀指令集（L128 / W07；parsers.DEFAULT_PREFIX_REQUIRED 已含 5 条，
# 本常量供装配/校验器对照，保证单一事实源）
GM_PREFIX_REQUIRED: FrozenSet[str] = GM_COMMANDS

# ---------------------------------------------------------------------------
# 权限三级（父任务命名 admin/manager/player = 5b 机主/GM/普通玩家 = router 常量，工程补白 6）
# ---------------------------------------------------------------------------

ROLE_ADMIN = "admin"        # 机主（owner / PERM_OWNER）：全部指令 + 授予/撤销
ROLE_MANAGER = "manager"    # GM（PERM_GM）：默认授予集 + per-command 下授
ROLE_PLAYER = "player"      # 普通玩家（PERM_USER）：仅游玩指令（GM 指令静默）

# 角色名归一表（owner/admin/机主 ↔ gm/manager ↔ user/player/普通玩家，双向兼容）
_ROLE_ALIASES: Mapping[str, str] = {
    "owner": ROLE_ADMIN, "admin": ROLE_ADMIN, "机主": ROLE_ADMIN,
    "gm": ROLE_MANAGER, "manager": ROLE_MANAGER,
    "user": ROLE_PLAYER, "player": ROLE_PLAYER, "普通玩家": ROLE_PLAYER,
}

# 每指令最低权限（5b §2.1 权限列；L160 清单内）：
#   重载 G1 = GM / 封禁 G10 = GM / 日志 G8 = GM / 编辑 G13 = 机主·GM / 设置 G14 = 机主
GM_COMMAND_LEVEL: Mapping[str, str] = {
    GM_CMD_RELOAD: ROLE_MANAGER,
    GM_CMD_BAN: ROLE_MANAGER,
    GM_CMD_LOG: ROLE_MANAGER,
    GM_CMD_EDIT: ROLE_MANAGER,
    GM_CMD_SETTINGS: ROLE_ADMIN,
}

# 默认授予集（5b §1.1.1 裁决：默认授予集 = 全部指令表标注 GM 的指令）；
# 「机主专属」指令（本批 = 设置）默认不授予，manager 需 per-command 下授。
GM_DEFAULT_GRANT: FrozenSet[str] = frozenset(
    cmd for cmd, level in GM_COMMAND_LEVEL.items() if level == ROLE_MANAGER
)

# CommandSpec.permission 值映射（装配注册用，与 router 权限常量对齐）
_SPEC_PERMISSION: Mapping[str, str] = {
    ROLE_ADMIN: PERM_OWNER,
    ROLE_MANAGER: PERM_GM,
    ROLE_PLAYER: PERM_USER,
}

# ---------------------------------------------------------------------------
# /日志 窗口与封禁默认（5b G8 / G10；细化_0 R-02）
# ---------------------------------------------------------------------------

# 系统日志每页条数（m4 §2.2 列表 5 条/页上限）
LOG_PAGE_SIZE: int = DEFAULT_PAGE_SIZE  # 5

# /日志 默认展示条数（sys_log.default_show=20，可配）
LOG_DEFAULT_SHOW: int = 20

# /日志 保留窗口上限（sys_log.max_entries=50，细化_0 R-02）
LOG_MAX_ENTRIES: int = 50

# 封禁默认时长（5b G10：时长默认永久）
BAN_DEFAULT_DURATION: str = "永久"

# 空日志文案（纯文本无装饰 emoji）
_EMPTY_LOG: str = "（暂无系统日志）"

# 审计 HMAC 参与字段（5b §4.2 audit_ts_hmac 校验值；不含 hmac 本身防自证）
AUDIT_HMAC_FIELDS: tuple = (
    "ts", "qq", "group_id", "command", "params", "target_qq", "result", "detail", "ref",
)


# ---------------------------------------------------------------------------
# 权限模型（5b §1.1：三级权限 + 判定优先级 机主 > GM > 普通玩家 + 静默语义）
# ---------------------------------------------------------------------------

class GmUser:
    """GM 指令发起者权限快照（5b §1.2：唯一事实来源 = admin_users 表，不在玩家存档内联）。

    qq_id: QQ 号；role: 角色（owner/gm/user 或 admin/manager/player，role_of 归一）；
    granted_commands: per-command 授权集合（机主下授，5b §1.1.1）。
    """

    __slots__ = ("qq_id", "role", "granted_commands")

    def __init__(self, qq_id: str, *, role: str = ROLE_PLAYER,
                 granted_commands: Optional[Any] = None) -> None:
        self.qq_id = str(qq_id or "")
        self.role = role_of(role)
        self.granted_commands: FrozenSet[str] = frozenset(
            str(c) for c in (granted_commands or ())
        )

    def __repr__(self) -> str:
        return (f"<GmUser qq={self.qq_id!r} role={self.role!r} "
                f"granted={sorted(self.granted_commands)!r}>")


class GmPermResult:
    """权限判定结果（静默是安全边界：无权限 → silent=True，调用方零出站零审计）。

    ok: 是否放行；silent: 无权限静默（5b §1.1 静默语义）；level: 放行级别 admin/manager；
    granted: 是否经 per-command 下授放行（5b §1.1.1）。
    """

    __slots__ = ("ok", "silent", "level", "granted")

    def __init__(self, ok: bool, *, silent: bool = False,
                 level: Optional[str] = None, granted: bool = False) -> None:
        self.ok = bool(ok)
        self.silent = bool(silent)
        self.level = level
        self.granted = bool(granted)

    def __repr__(self) -> str:
        return (f"<GmPermResult ok={self.ok} silent={self.silent} "
                f"level={self.level!r} granted={self.granted}>")


def role_of(role: Any) -> str:
    """权限角色归一（工程补白 6）：owner/admin/机主 → admin；gm/manager → manager；
    user/player/普通玩家 → player；未知 → player（安全失败，默认最低权限）。"""
    key = str(role or "").strip().lower()
    return _ROLE_ALIASES.get(key, ROLE_PLAYER)


def check_gm_permission(user: GmUser, command: str,
                        default_grant: Optional[Any] = None) -> GmPermResult:
    """GM 指令三级权限判定（5b §1.1 判定优先级：机主 > GM > 普通玩家；静默语义）。

    - 非 GM 指令 → 静默（本模块不处理）；
    - admin（机主）→ 全部放行（L258）；
    - manager（GM）→ 默认授予集内指令放行；机主专属指令需 granted_commands 下授
      （TC-04 口径：未下授 → 静默）；其余 → 静默（L255/L1310/L1355）；
    - player（普通玩家）→ 静默（TC-01：零出站零审计，防暴露指令存在）。
    """
    if command not in GM_COMMANDS:
        return GmPermResult(ok=False, silent=True)
    role = role_of(user.role)
    if role == ROLE_ADMIN:
        return GmPermResult(ok=True, level=ROLE_ADMIN)
    if role == ROLE_MANAGER:
        grant = frozenset(default_grant) if default_grant is not None else GM_DEFAULT_GRANT
        if command in grant:
            return GmPermResult(ok=True, level=ROLE_MANAGER)
        if command in user.granted_commands:
            return GmPermResult(ok=True, level=ROLE_MANAGER, granted=True)
        return GmPermResult(ok=False, silent=True)
    return GmPermResult(ok=False, silent=True)


# ---------------------------------------------------------------------------
# 结果模型（GmResult：静默执行成功不回显；错误 TPL-12；留痕随 audit 返回）
# ---------------------------------------------------------------------------

class GmResult:
    """GM 指令执行结果（供批次7 装配层消费）。

    ok:      业务是否成功（False + message=TPL-12 → 应报错出站）；
    silent:  无权限静默（True → 调用方**零出站零审计**，5b 静默语义 / TC-01/04/05/24）；
    message: 应回复正文——成功动作 → None（静默执行不回显成功，工程补白 2）；
             查询类（/日志 /编辑）→ 请求数据正文；失败 → TPL-12 统一报错；
    audit:   留痕记录（有权限执行时生成，成败皆写；无权限 → None，防探测）。
    """

    __slots__ = ("ok", "silent", "message", "audit")

    def __init__(self, ok: bool, *, silent: bool = False,
                 message: Optional[str] = None, audit: Optional[dict] = None) -> None:
        self.ok = bool(ok)
        self.silent = bool(silent)
        self.message = message
        self.audit = audit

    def __repr__(self) -> str:
        return (f"<GmResult ok={self.ok} silent={self.silent} "
                f"message={self.message!r} audit={self.audit!r}>")


def silent_result() -> GmResult:
    """无权限静默结果（零出站零审计；5b §1.1 / TC-01/04/05/24）。"""
    return GmResult(ok=False, silent=True, message=None, audit=None)


def success_result(record: dict, *, message: Optional[str] = None) -> GmResult:
    """有权限执行成功（静默执行：成功不回显群聊，摘要入 audit.detail；查询类传 message）。"""
    return GmResult(ok=True, silent=False, message=message, audit=record)


def error_result(record: dict, message: str) -> GmResult:
    """有权限但失败（参数错/执行失败）→ TPL-12 报错 + 审计 result=failed。"""
    return GmResult(ok=False, silent=False, message=message, audit=record)


# ---------------------------------------------------------------------------
# 留痕（5b §4 审计：追加写不可删；成败皆写；无权限不写——由调用方保证静默时不调本层）
# ---------------------------------------------------------------------------

def _now_iso(now: Optional[str]) -> str:
    """审计时间戳（now 注入优先保证确定性；缺省 UTC ISO-8601）。"""
    if now:
        return str(now)
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def audit_hmac(record: Mapping[str, Any], key: str) -> str:
    """审计行校验值（5b §4.2 audit_ts_hmac；HMAC-SHA256，防篡改可选开关默认开）。

    key 为空 → ""（校验值未启用）；否则对 AUDIT_HMAC_FIELDS 规范序列求 HMAC。
    确定性：同 record + 同 key → 同值；字段被改 → 值不同（防旁路篡改）。
    """
    if not key:
        return ""
    canonical = "|".join(
        f"{k}={str(record.get(k)).strip()}" for k in AUDIT_HMAC_FIELDS
    )
    digest = hmac.new(str(key).encode("utf-8"), canonical.encode("utf-8"),
                      hashlib.sha256)
    return digest.hexdigest()


def build_audit_record(*, qq: Any, group_id: Any = "0", command: str,
                       params: str = "", target_qq: Any = None, result: str,
                       detail: str = "", ref: Any = None,
                       now: Optional[str] = None,
                       hmac_key: Optional[str] = None) -> dict:
    """审计记录构造（5b §4.2 字段：id/ts/qq/group_id/command/params/target_qq/result/
    detail/ref/audit_ts_hmac）。params 截断 200 字（不含密文明文，GM 指令无密文参数）。"""
    p = str(params or "")
    if len(p) > 200:
        p = p[:200] + "…"
    record: dict = {
        "id": uuid.uuid4().hex,
        "ts": _now_iso(now),
        "qq": str(qq or ""),
        "group_id": str(group_id or "0"),  # 私聊=0（5b §4.2）
        "command": str(command),
        "params": p,
        "target_qq": str(target_qq) if target_qq is not None else None,
        "result": str(result),  # success | failed | rejected
        "detail": str(detail or ""),
        "ref": str(ref) if ref is not None else None,
        "audit_ts_hmac": "",
    }
    if hmac_key:
        record["audit_ts_hmac"] = audit_hmac(record, hmac_key)
    return record


def record_audit(ctx: MutableMapping[str, Any], record: dict) -> None:
    """留痕：追加写审计（操作日志）。

    - 纯逻辑收集：追加进 ctx["audit_log"]（测试/批次7 消费同一数据源）；
    - 落库：ctx["audit_store"].append(record)（批次7 注入，5b §4.2 audit_log 表）；
    - 无权限调用不写（静默防探测）——由 handle_gm_command 保证静默分支不调本函数。
    """
    log = ctx.setdefault("audit_log", [])
    log.append(record)
    store = ctx.get("audit_store")
    if store is not None:
        store.append(record)


# ---------------------------------------------------------------------------
# 工具（纯函数）
# ---------------------------------------------------------------------------

def _fragment(parsed: Any) -> str:
    """TPL-12 原文片段（parsed.raw 优先；缺省重构，对齐 checkin/quest 同口径）。"""
    if getattr(parsed, "raw", None):
        return str(parsed.raw)
    cmd = getattr(parsed, "command", None) or ""
    args = getattr(parsed, "args", None) or []
    tail = (" " + " ".join(str(a) for a in args)) if args else ""
    return f"/{cmd}{tail}"


def _params_summary(parsed: Any) -> str:
    """审计 params 参数摘要（args + 键值；截断在 build_audit_record 内做，5b §4.2）。"""
    parts: List[str] = [str(a) for a in (getattr(parsed, "args", None) or [])]
    for kv in getattr(parsed, "kv", None) or []:
        if not isinstance(kv, Mapping):
            continue
        key = kv.get("key")
        if key:
            parts.append(f"{key}={kv.get('value')}")
    return " ".join(parts)


def _ctx_qq(ctx: Mapping[str, Any]) -> str:
    return str(ctx.get("qq_id") or ctx.get("qq") or "")


def _ctx_group(ctx: Mapping[str, Any]) -> Any:
    return ctx.get("group_id") or ctx.get("group") or "0"


def _audit_args(ctx: Mapping[str, Any]) -> dict:
    """审计上下文透传（now / hmac_key 由 ctx 注入，确定性 + 防篡改）。"""
    return {"now": ctx.get("now"), "hmac_key": ctx.get("audit_hmac_key")}


def _user_of(ctx: Mapping[str, Any]) -> GmUser:
    """发起者权限快照（5b §1.2：permission_store 注入优先；否则 ctx role/granted 兜底）。

    ctx["permission_store"].user_of(qq_id) -> GmUser（权限唯一事实来源 = admin_users 表）；
    未注入 → 按 ctx["role"]/ctx["granted_commands"] 构造（测试/装配直给）。
    """
    qq = _ctx_qq(ctx)
    store = ctx.get("permission_store")
    if store is not None and hasattr(store, "user_of"):
        try:
            u = store.user_of(qq)
            if isinstance(u, GmUser):
                return u
            if u is not None:
                return GmUser(qq, role=u[0], granted_commands=(u[1] if len(u) > 1 else ()))
        except Exception:
            pass  # 【工程补白】权限存储异常 → 按 ctx 兜底，安全失败为 player
    return GmUser(qq, role=str(ctx.get("role") or ROLE_PLAYER),
                   granted_commands=ctx.get("granted_commands"))


def _backend(ctx: Mapping[str, Any]) -> Any:
    """GM 后端引擎解析（工程补白：注入优先；未注入 → 【待接线】RuntimeError 防御路径）。"""
    backend = ctx.get("gm_backend")
    if backend is None:
        raise RuntimeError(
            "【待接线】ctx['gm_backend'] 未注入（GM 后端引擎，批次6/7 装配；消费接口："
            "reload_content/ban_player/recent_audit/editor_link/apply_setting/audit_store）"
        )
    return backend


def _record_and_return(ctx: MutableMapping[str, Any], *, command: str,
                       result: str, detail: str, parsed: Any,
                       params: Optional[str] = None, target_qq: Any = None,
                       ref: Any = None, message: Optional[str] = None) -> GmResult:
    """构造审计记录 → 留痕 → 包装 GmResult（成败共用；ok 由 result 推导——单一来源）。

    result="success" → 静默成功（不回显成功，摘要入 audit.detail；查询类传 message）；
    result="failed"  → TPL-12 报错（error_result）。
    """
    record = build_audit_record(
        qq=_ctx_qq(ctx),
        group_id=_ctx_group(ctx),
        command=command,
        params=params if params is not None else _params_summary(parsed),
        target_qq=target_qq,
        result=result,
        detail=detail,
        ref=ref,
        **_audit_args(ctx),
    )
    record_audit(ctx, record)
    if result == "success":
        # 静默执行：成功不回显群聊，摘要入 audit.detail（工程补白 2）；查询类传 message
        return success_result(record, message=message)
    return error_result(record, format_tpl12(_fragment(parsed)))


# ---------------------------------------------------------------------------
# 指令处理器（纯函数：ParsedCommand + ctx + GmPermResult → GmResult）
# ---------------------------------------------------------------------------

def cmd_gm_reload(parsed: Any, ctx: MutableMapping[str, Any],
                  perm: GmPermResult) -> GmResult:
    """/重载 <内容包>（5b G1，权限 GM）：热重载结果摘要 + 失败项清单。
    缺参/超参/包不存在 → TPL-12 + 审计 failed；成功 → 静默（摘要入 audit.detail）。"""
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return _record_and_return(ctx, command=GM_CMD_RELOAD, result="failed",
                                  detail="缺参：/重载 <内容包>", parsed=parsed)
    if len(args) > 1:
        return _record_and_return(ctx, command=GM_CMD_RELOAD, result="failed",
                                  detail="超参：/重载 <内容包>", parsed=parsed)
    pack = str(args[0])
    res = _backend(ctx).reload_content(pack, ctx)
    if not res or not res.get("ok"):
        reason = str((res or {}).get("message") or "重载失败")
        return _record_and_return(ctx, command=GM_CMD_RELOAD, result="failed",
                                  detail=reason, parsed=parsed, params=pack, ref=pack)
    failures = res.get("failures") or []
    detail = f"✅ 已重载【{pack}】：{res.get('summary') or ''}"
    if failures:
        detail += f"；失败 {len(failures)} 项：{'、'.join(str(f) for f in failures[:3])}"
    return _record_and_return(ctx, command=GM_CMD_RELOAD, result="success",
                              detail=detail, parsed=parsed, params=pack, ref=pack)


def cmd_gm_ban(parsed: Any, ctx: MutableMapping[str, Any],
               perm: GmPermResult) -> GmResult:
    """/封禁 <QQ号> [时长] [原因=...]（5b G10，权限 GM）：封禁确认 + 到期时间。
    QQ 非纯数字/缺参 → TPL-12；成功 → 静默（摘要含 target/时长/到期/原因，入 audit E4）。"""
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return _record_and_return(ctx, command=GM_CMD_BAN, result="failed",
                                  detail="缺参：/封禁 <QQ号> [时长] [原因=...]", parsed=parsed)
    qq = str(args[0])
    if not qq.isdigit():
        return _record_and_return(ctx, command=GM_CMD_BAN, result="failed",
                                  detail="QQ 号必须为纯数字", parsed=parsed, params=qq,
                                  target_qq=qq)
    duration = str(args[1]) if len(args) > 1 else BAN_DEFAULT_DURATION
    reason: Optional[str] = None
    for kv in getattr(parsed, "kv", None) or []:
        if isinstance(kv, Mapping) and kv.get("key") == "原因" and kv.get("value"):
            reason = str(kv["value"])
    res = _backend(ctx).ban_player(qq, duration, reason, ctx)
    if not res or not res.get("ok"):
        msg = str((res or {}).get("message") or "封禁失败")
        return _record_and_return(ctx, command=GM_CMD_BAN, result="failed",
                                  detail=msg, parsed=parsed, params=f"{qq} {duration}",
                                  target_qq=qq)
    expires = res.get("expires")
    detail = f"❌ 已封禁 {qq}（{duration}）"
    if expires:
        detail += f" 到期 {expires}"
    if reason:
        detail += f" 原因：{reason}"
    return _record_and_return(ctx, command=GM_CMD_BAN, result="success", detail=detail,
                              parsed=parsed, params=f"{qq} {duration}",
                              target_qq=qq, ref=qq)


def cmd_gm_log(parsed: Any, ctx: MutableMapping[str, Any],
               perm: GmPermResult) -> GmResult:
    """/日志 [页码] [条数=N]（5b G8，权限 GM）：系统日志最近事件（GM 版 = 审计留痕表）。
    5 条/页 + TPL-08 页脚 + 裁决② 夹取；页码 0/负数/非数字 → TPL-12；条数上限 50。"""
    args = list(getattr(parsed, "args", None) or [])
    count = LOG_DEFAULT_SHOW
    for kv in getattr(parsed, "kv", None) or []:
        if isinstance(kv, Mapping) and kv.get("key") == "条数":
            n = parse_int(str(kv.get("value") or ""))
            if n is None or n < 1:
                return _record_and_return(ctx, command=GM_CMD_LOG, result="failed",
                                          detail="条数=N 必须为正整数（默认 20，上限 50）",
                                          parsed=parsed, params="条数=" + str(kv.get("value") or ""))
            count = min(int(n), LOG_MAX_ENTRIES)
    page = 1
    if args:
        p = parse_int(str(args[0]))
        if p is None or p < 1:
            return _record_and_return(ctx, command=GM_CMD_LOG, result="failed",
                                      detail="页码非法（0/负数/非数字）", parsed=parsed)
        page = int(p)
    events = _backend(ctx).recent_audit(count, ctx) or []
    total = len(events)
    res = resolve_page(page, total, LOG_PAGE_SIZE)
    if res.invalid:
        return _record_and_return(ctx, command=GM_CMD_LOG, result="failed",
                                  detail="页码非法（0/负数/非数字）", parsed=parsed)
    assert res.page is not None
    # 传原始页码 → render_list_page_text 内部裁决② 夹取最后一页 +「已到最后一页」提示
    body = render_log_page(events, page, command=GM_CMD_LOG)
    # 日志查询本身也写审计（5b §2：所有 GM 指令成败皆写）
    detail = f"系统日志 {count} 条窗口 第 {res.page}/{res.total_pages} 页" \
        if res.total_pages > 1 else f"系统日志 {count} 条窗口"
    if res.clamped:
        detail += f"（{LAST_PAGE_HINT}）"
    return _record_and_return(ctx, command=GM_CMD_LOG, result="success", detail=detail,
                              parsed=parsed, params=f"条数={count}", message=body)


def cmd_gm_edit(parsed: Any, ctx: MutableMapping[str, Any],
                perm: GmPermResult) -> GmResult:
    """/编辑（5b G13，机主/GM）：返回编辑器链接 + 权限级提示（机主=全功能，GM=只读预览）。
    返回链接为请求数据（非成功回显）；留痕 result=success。"""
    if getattr(parsed, "args", None):
        return _record_and_return(ctx, command=GM_CMD_EDIT, result="failed",
                                  detail="超参：/编辑 无参数", parsed=parsed)
    res = _backend(ctx).editor_link(perm.level, ctx)
    url = str(res.get("url") or "")
    hint = str(res.get("hint") or "")
    line = f"编辑器：{url}" if url else "编辑器：暂未配置链接"
    if hint:
        line += f"（{hint}）"
    return _record_and_return(ctx, command=GM_CMD_EDIT, result="success", detail=line,
                              parsed=parsed, message=line)


def cmd_gm_settings(parsed: Any, ctx: MutableMapping[str, Any],
                    perm: GmPermResult) -> GmResult:
    """/设置 <键=值>（5b G14，机主；可 per-command 下授）：指令模式/群级配置切换结果。
    缺参/超参 → TPL-12；成功 → 静默（新值摘要入 audit.detail）。"""
    kv = [k for k in getattr(parsed, "kv", None) or [] if isinstance(k, Mapping)]
    if not kv:
        return _record_and_return(ctx, command=GM_CMD_SETTINGS, result="failed",
                                  detail="缺参：/设置 <键=值>（如 command_mode=global_shortcut）",
                                  parsed=parsed)
    if len(kv) > 1:
        return _record_and_return(ctx, command=GM_CMD_SETTINGS, result="failed",
                                  detail="超参：/设置 一次一个键值", parsed=parsed)
    key = str(kv[0].get("key") or "")
    value = str(kv[0].get("value") or "")
    if not key or not value:
        return _record_and_return(ctx, command=GM_CMD_SETTINGS, result="failed",
                                  detail="缺参：/设置 <键=值>", parsed=parsed)
    res = _backend(ctx).apply_setting(key, value, ctx)
    if not res or not res.get("ok"):
        msg = str((res or {}).get("message") or "设置失败")
        return _record_and_return(ctx, command=GM_CMD_SETTINGS, result="failed",
                                  detail=msg, parsed=parsed, params=f"{key}={value}", ref=key)
    current = res.get("current")
    detail = f"{key}：{current}" if current is not None else f"已设置 {key}={value}"
    return _record_and_return(ctx, command=GM_CMD_SETTINGS, result="success",
                              detail=detail, parsed=parsed, params=f"{key}={value}", ref=key)


_HANDLERS: Mapping[str, Callable[..., GmResult]] = {
    GM_CMD_RELOAD: cmd_gm_reload,
    GM_CMD_BAN: cmd_gm_ban,
    GM_CMD_LOG: cmd_gm_log,
    GM_CMD_EDIT: cmd_gm_edit,
    GM_CMD_SETTINGS: cmd_gm_settings,
}


# ---------------------------------------------------------------------------
# 渲染（/日志 列表：5 条/页 + TPL-08 页脚 + 裁决② 夹取；纯文本零装饰 emoji）
# ---------------------------------------------------------------------------

def render_log_line(record: Mapping[str, Any]) -> str:
    """单条审计事件行（5b G8 分行格式）：`[ts] G1 /重载 内容包X 成功 by 123456`。"""
    ts = str(record.get("ts") or "?")
    # ts 仅取时刻（HH:MM:SS 或原样；ISO 串取 T 后 8 位）
    if "T" in ts:
        ts = ts.split("T", 1)[1][:8]
    cmd = str(record.get("command") or "?")
    idx = GM_COMMAND_INDEX.get(cmd, "GM")
    params = str(record.get("params") or "").strip()
    result = str(record.get("result") or "?")
    qq = str(record.get("qq") or "?")
    line = f"[{ts}] {idx} /{cmd}"
    if params:
        line += f" {params}"
    return f"{line} {result} by {qq}"


def render_log_page(events: List[Mapping[str, Any]], page: int, *,
                    command: str = GM_CMD_LOG,
                    per_page: int = LOG_PAGE_SIZE) -> str:
    """/日志 列表正文（5b G8 + m4 §2.2 + 裁决②）：

    - 事件行 5 条/页横切；页码超总页数 → 夹取最后一页 + LAST_PAGE_HINT（裁决②）；
    - TPL-08 页脚（render_footer，禁止自造页脚）；空日志 → 空文案；
    - 页码非法（0/负数/非数字）由调用方经 resolve_page 判定转 TPL-12（裁决②）。
    """
    items = [render_log_line(e) for e in events]
    if not items:
        return _EMPTY_LOG
    return render_list_page_text(items, page, command, per_page=per_page)


# ---------------------------------------------------------------------------
# GM 禁绑 / 强制前缀（5b §3.2 / 规范 L120-121、L128、L160-161、L169-171）
# ---------------------------------------------------------------------------

def is_gm_command_name(word: Any) -> bool:
    """首词是否为 GM 指令（L160 长清单成员判定；供绑定层/校验器复用）。
    剥离前导 /（与 router.is_gm_command 同口径），空 → False。"""
    w = str(word or "").strip()
    if w.startswith("/"):
        w = w[1:].strip()
    return w in GM_COMMANDS


def gm_requires_prefix() -> FrozenSet[str]:
    """GM 强制 / 前缀指令集（L128/W07；装配与 parsers.DEFAULT_PREFIX_REQUIRED 对照用）。"""
    return GM_PREFIX_REQUIRED


def gm_binding_guard(shortcut_name: str, target_text: str, *,
                     registry: Any = None, aliases: Any = None) -> dict:
    """快捷绑定 GM 禁绑（5b §3.2 / 规范 L160-161 C02，防权限绕过）。

    绑定目标首词为 GM 指令（L160 长清单）→ 拒绝，出站：
      『重载』是 GM 指令，不可绑定为快捷
    复用 router.check_shortcut_binding（gm_commands=GM_COMMANDS 注入），并显式覆盖
    C02 判定（L160 清单单一事实源）。返回 verdict dict（{ok, code, message?, hint?}）。
    """
    return check_shortcut_binding(
        shortcut_name, target_text,
        registry=registry, gm_commands=GM_COMMANDS, aliases=aliases,
    )


# ---------------------------------------------------------------------------
# 主入口（执行层权限二次检查 E02 → 解析错误 → 处理器；静默分支零出站零审计）
# ---------------------------------------------------------------------------

def handle_gm_command(parsed: Any, ctx: MutableMapping[str, Any]) -> GmResult:
    """GM 指令主入口（5b §1.4 执行层权限二次检查 + §0 决策链 ④⑤⑥⑦）。

    - 非 GM 指令 → 静默（不处理）；
    - 无权限（player / 未下授 manager）→ GmResult.silent=True（**零出站、零审计**，
      即使快捷表被写入脏数据绕过绑定层，执行层照样拦截，TC-24）；
    - 有权限 + 解析错误 → TPL-12 + 审计 failed；
    - 有权限 + 参数/执行错误 → TPL-12 + 审计 failed；
    - 有权限 + 成功 → 静默执行（message=None / 查询类数据），审计 success（留痕）。
    """
    command = getattr(parsed, "command", None)
    if command not in GM_COMMANDS:
        return silent_result()
    user = _user_of(ctx)
    perm = check_gm_permission(user, command)
    if not perm.ok:
        # 静默是安全边界：无权限 → 零出站零审计（TC-01/04/05/24）
        return silent_result()
    if getattr(parsed, "error", None):
        return _record_and_return(ctx, command=command, result="failed",
                                  detail=f"解析错误：{parsed.error}", parsed=parsed)
    handler = _HANDLERS[command]
    return handler(parsed, ctx, perm)


# ---------------------------------------------------------------------------
# 装配（Router 注册；make_context 由装配层注入，批次6/7 待接线）
# ---------------------------------------------------------------------------

def register_gm_commands(router: Any, *,
                         make_context: Optional[Callable[[Any], dict]] = None) -> Any:
    """把 /gm 指令集（L160 长清单 5 条）注册进 Router。

    - 每条 CommandSpec：is_gm=True（→ 路由层强制 / 前缀 W07/L128 + 快捷禁绑 C02 +
      执行层二次检查位 E02）；permission 按 GM_COMMAND_LEVEL 映射（PERM_OWNER/PERM_GM）；
    - handler 消费 ParsedCommand，返回 GmResult（批次7 装配据此处理静默/消息/审计）；
    - make_context 缺失 → handler 调用抛 RuntimeError（【待接线】批次6/7 装配注入）。

    :param make_context: ParsedCommand → 玩家 ctx dict（含 gm_backend/permission_store/
        audit_store/qq_id/group_id/now/audit_hmac_key 注入，见文件头消费接口）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】gm_commands.register_gm_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入：gm_backend/permission_store/audit_store）"
            )
        return make_context(parsed)

    def _gm(parsed: Any, *a: Any, **k: Any) -> GmResult:
        return handle_gm_command(parsed, _ctx(parsed))

    for cmd in sorted(GM_COMMANDS, key=lambda c: GM_COMMAND_INDEX.get(c, "")):
        level = GM_COMMAND_LEVEL[cmd]
        router.register(CommandSpec(
            cmd,
            permission=_SPEC_PERMISSION[level],
            is_gm=True,
            handler=_gm,
        ))
    return router
