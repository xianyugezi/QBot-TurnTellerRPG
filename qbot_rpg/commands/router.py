"""指令路由壳 Router（M4 批次1·路B3 · 实装）。

依据：
  - m4_shared_contract.md §2.1（解析管线顺序：快捷表→别名→白名单→忽略；会话路由：对话激活时
    纯数字/继续/退出/选择N 送状态机、带指令词照常解析；**战斗中裸数字 = 快捷表（2026-08-27 裁决①）**）
  - docs/细化/细化_3c_指令解析契约.md §5（会话路由 R1-R5 / 5.3 路由优先级总表）+ §4（快捷冲突检测
    C01-C05 / GM 禁绑 C02 / E03 上限 / 4.5 指令别名 A01-A08）+ §3.0 状态机 S0-S5
  - docs/细化/细化_2b2_对话会话状态机.md（会话激活区间 = 建会话→会话收尾；结束词三同义 离开·再见·退出；
    R1-R5 判定表）
  - 2026-08-27 裁决①（战斗中裸数字 = 快捷绑定，无会话上下文，快捷表生效；选技能用带指令词「/攻击 2」）
  - M4 实现审查批次1 P1-2（审查_M4实现_批次1_jspace.md）：双管线口径漂移修复 ①②——
    ① require_at 下裸 / 不再豁免 @（无 @ 一律忽略）；② 剥离顺序统一「先 @ 后 /」
    （@机器人 /攻击 2 组合可命中，对齐 parsers S0）；并补 at_gate_passed 让快捷展开串
    不再重复要求 @（对齐 parsers 展开重入 require_at=False），配套
    tests/unit/test_dual_pipeline_parity.py 同输入两管线一致性测试。

职责（细化_3a §1.3 壳层职责清单 · 唯一 NoneBot 适配器接触点）——本模块实装：
  ① 指令注册表（CommandSpec：名称/解析函数/白名单标记/GM 权限标记/别名/权限等级/冷却）
  ② 路由管线 快捷表→别名→白名单→忽略（纯判定；快捷/别名表由调用方注入或 ctx 读取，本模块不持有存储）
  ③ 会话路由（对话激活时子词送状态机 mode=session_digit；带指令词照常解析）
  ④ 战斗中裸数字 = 快捷表（裁决①，不送会话）
  ⑤ GM 禁绑（快捷绑定拒绝 GM 指令，防权限绕过 C02；执行层二次检查位 E02 → spec.is_gm）
  ⑥ 指令别名显示层替换（keep_original 可选，A04/A05）

纯函数约定：本模块**零 NoneBot import**（3a R1：pytest 可脱离平台跑核心层）、纯逻辑无 IO。
ParsedCommand 细粒度 token 化（分隔符全集 / 紧凑双认 / command_mode 剥离细节）由 commands/parsers.py
负责（M4 批次1 并行路）；本模块在解析前完成「送状态机 / 正常指令解析」二选一 + 快捷/别名/白名单
路由判定，输出 RouteResult 供调用方（状态机 or 指令管线）消费。

【工程补白 · 显式标注】
  1) 别名紧凑形态（如「炼丹3」）3c 未显式定义：按最长前缀匹配，与白名单紧凑双认（S6 L109-112）同构。
  2) route_message 带 allow_shortcut 参数；快捷展开深度 = 1（S7 裁决：命中快捷后替换为指令串，从
     指令名层续走，不再回查快捷表，防 A→B→A 无限循环）。
  3) require_at 开启时：@机器人 是唯一放行入口——输入无 @（含裸 / 前缀）一律忽略
     （非指令触发；L102-104/L178）；@ 剥离后紧随的 / 一并剥离（@机器人 /攻击 2 组合）。
     快捷展开串经 at_gate_passed 传递 @ 门（对齐 parsers 展开重入 require_at=False）。
  4) keep_original=false 时发原指令 → 独立路由结果 kind="hidden_original"，供调用方渲染
     「没有这个指令，试试『XX』？」（A04 / TC-33）。
  5) 权限/频率/防抖等执行层职责仍由下游（on_command 装配 / 5b GM 层）承担；本模块仅暴露
     spec.is_gm / spec.permission / result.is_gm 供其检查（E02 执行层权限二次检查位）。
  6) 白名单命中后显示层别名替换（A05：帮助/提示/错误模板全用别名 display_name），原指令名仍为
     执行目标 command。
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

__all__ = [
    # 权限常量
    "PERM_OWNER", "PERM_GM", "PERM_USER",
    # mode 常量（ParsedCommand.mode 对齐 3c §3.2 P03 + 会话 mode=session_digit）
    "MODE_NORMAL", "MODE_SHORTCUT", "MODE_ALIAS", "MODE_SESSION_DIGIT",
    # 路由结果 kind
    "ROUTE_SESSION", "ROUTE_SHORTCUT", "ROUTE_ALIAS", "ROUTE_COMMAND",
    "ROUTE_HIDDEN", "ROUTE_IGNORED",
    # 会话子词
    "SESSION_SUBWORD_DIGIT", "SESSION_SUBWORD_CONTINUE", "SESSION_SUBWORD_EXIT",
    "SESSION_SUBWORD_SELECT", "SESSION_EXIT_WORDS", "is_session_subword",
    # 指令注册表
    "CommandSpec", "Router", "register_command",
    # 路由结果 / 上下文
    "RouteResult", "RoutingContext",
    # 路由管线
    "route_message", "route_and_expand", "dispatch_message",
    # 指令别名（A01-A08）
    "AliasEntry", "AliasTable", "normalize_aliases",
    # 快捷绑定校验（C01-C05 / E03 / GM 禁绑）
    "resolve_command_word", "is_gm_command", "check_shortcut_binding", "check_shortcut_limit",
]

# ---------------------------------------------------------------------------
# 权限三级（细化_3a §1.3；【规则】L455-462）
# ---------------------------------------------------------------------------
PERM_OWNER = "owner"     # 机主
PERM_GM = "gm"           # GM
PERM_USER = "user"       # 普通

# ---------------------------------------------------------------------------
# mode 常量（对齐 3c §3.2 P03；会话路由专用 mode=session_digit 见任务要求）
# ---------------------------------------------------------------------------
MODE_NORMAL = "normal"             # 正常指令
MODE_SHORTCUT = "shortcut"         # 快捷表触发（L149①）
MODE_ALIAS = "alias"               # 指令别名触发（L150②）
MODE_SESSION_DIGIT = "session_digit"  # 会话子词 → 送状态机（2b2 R1 / 3c §5）

# 路由结果 kind（RouteResult.kind）
ROUTE_SESSION = "session"               # 送激活会话状态机
ROUTE_SHORTCUT = "shortcut"             # 命中快捷表（等待展开）
ROUTE_ALIAS = "alias"                   # 命中指令别名（command=原指令名）
ROUTE_COMMAND = "command"               # 命中指令白名单 → 正常解析
ROUTE_HIDDEN = "hidden_original"        # keep_original=false 发原指令（A04）
ROUTE_IGNORED = "ignored"               # 非指令消息（L152④ / L126-127）

# ---------------------------------------------------------------------------
# 会话子词（2b2 R1 / 3c §5.1 R1）
# ---------------------------------------------------------------------------
SESSION_SUBWORD_DIGIT = "digit"         # 纯数字 1/2/3
SESSION_SUBWORD_CONTINUE = "continue"   # 继续
SESSION_SUBWORD_EXIT = "exit"           # 退出/离开/再见（三词同义，L62）
SESSION_SUBWORD_SELECT = "select"       # 选择 N（与纯数字 N 等价映射【工程补白】）

# 结束词三同义（2b2 L62 / R1）
SESSION_EXIT_WORDS: tuple = ("退出", "离开", "再见")

# 选择 N 形态：`选择 N` / `选择N`（2b2 R1）
_SELECT_RE = re.compile(r"^选择\s*(\d+)$")


def is_session_subword(text: str) -> Optional[tuple]:
    """会话子词判定（2b2 R1 + 3c §5.1 R1，纯函数）。

    输入 ∈ {纯数字, 继续, 退出/离开/再见, 选择 N} → 返回 (category, value)；
    否则返回 None。
      - 纯数字 → ("digit", int(N))
      - 继续   → ("continue", None)
      - 结束词 → ("exit", None)
      - 选择 N → ("select", int(N))
    """
    t = str(text or "").strip()
    if not t:
        return None
    if t.isdigit():
        return (SESSION_SUBWORD_DIGIT, int(t))
    if t == "继续":
        return (SESSION_SUBWORD_CONTINUE, None)
    if t in SESSION_EXIT_WORDS:
        return (SESSION_SUBWORD_EXIT, None)
    m = _SELECT_RE.match(t)
    if m:
        return (SESSION_SUBWORD_SELECT, int(m.group(1)))
    return None


# ---------------------------------------------------------------------------
# 指令注册表（CommandSpec：名称/解析函数/白名单标记/GM 权限标记/别名/权限等级/冷却）
# ---------------------------------------------------------------------------

class CommandSpec:
    """指令静态描述（注册表条目，供路由/帮助/权限对照；M4 由 on_command 消费）。

    name: 指令名（不含前导 /）；aliases: 别名；permission: 权限等级；cooldown_seconds: 冷却；
    handler: 解析函数（参数串 → 结构化结果 / 执行回调）；
    whitelisted: 白名单标记（False = 不参与 S5 白名单开头匹配，普通消息不触发）；
    is_gm: GM 权限标记（GM 指令强制 / 前缀 W07/L128、快捷禁绑 C02、执行层二次检查 E02）。
    """

    def __init__(
        self,
        name: str,
        *,
        aliases: Optional[List[str]] = None,
        permission: str = PERM_USER,
        cooldown_seconds: float = 0.0,
        handler: Optional[Callable[..., Any]] = None,
        whitelisted: bool = True,
        is_gm: bool = False,
    ) -> None:
        if not name or not isinstance(name, str):
            raise ValueError(f"指令名必须为非空 str，收到 {name!r}")
        self.name = name
        self.aliases: List[str] = list(aliases or [])
        self.permission = permission
        self.cooldown_seconds = cooldown_seconds
        self.handler = handler
        self.whitelisted = bool(whitelisted)
        self.is_gm = bool(is_gm)

    def matches(self, raw: str) -> bool:
        """指令名/别名匹配（触发模式 @/前缀/直接/敏感词，【框架】L1604）。"""
        t = str(raw or "").strip()
        if t.startswith("/"):
            t = t[1:].strip()
        return t == self.name or t in self.aliases

    def __repr__(self) -> str:
        flags = []
        if self.is_gm:
            flags.append("gm")
        if not self.whitelisted:
            flags.append("no-whitelist")
        suffix = f" [{','.join(flags)}]" if flags else ""
        return f"<CommandSpec {self.name}{suffix}>"


class Router:
    """指令路由注册表（M4 接线 on_command；零 nonebot，纯注册表 + 路由入口）。

    维护：指令表 _specs；白名单名集合（whitelisted=True 的参与 S5 匹配）；
    GM 指令名集合（供禁绑/执行层二次检查）。dispatch 为完整消息路由入口（含一级快捷展开）。
    """

    def __init__(self, *, command_mode: str = "global_shortcut", require_at: bool = False) -> None:
        self._specs: Dict[str, CommandSpec] = {}
        self.command_mode = command_mode
        self.require_at = bool(require_at)

    # -- 注册表 CRUD ----------------------------------------------------------

    def register(self, spec: CommandSpec, *, replace: bool = False) -> CommandSpec:
        """注册指令。重名冲突 → ValueError（默认）；replace=True 允许覆盖（热重载/内容包升级）。"""
        if not isinstance(spec, CommandSpec):
            raise TypeError(f"register 需要 CommandSpec，收到 {type(spec).__name__}")
        if spec.name in self._specs and not replace:
            raise ValueError(f"指令『{spec.name}』重复注册（动态注册表冲突，S6 裁决）")
        self._specs[spec.name] = spec
        return spec

    def unregister(self, name: str) -> bool:
        """注销指令。返回是否真的移除。"""
        return self._specs.pop(name, None) is not None

    def get(self, name: str) -> Optional[CommandSpec]:
        return self._specs.get(name)

    def has(self, name: str) -> bool:
        return name in self._specs

    def names(self) -> List[str]:
        return list(self._specs)

    def whitelist_names(self) -> List[str]:
        """白名单名集合（S5 ③：whitelisted=True 的才参与开头匹配）。"""
        return [n for n, s in self._specs.items() if s.whitelisted]

    def gm_commands(self) -> List[str]:
        """GM 指令名集合（C02 禁绑 / E02 二次检查 / W07 强制前缀）。"""
        return [n for n, s in self._specs.items() if s.is_gm]

    # -- 路由入口 --------------------------------------------------------------

    def dispatch(self, raw: str, ctx: Optional[Mapping] = None) -> "RouteResult":
        """完整消息路由（含一级快捷展开）。ctx 可注入；缺省用自身注册表与默认 command_mode。"""
        data = dict(ctx) if ctx else {}
        data.setdefault("registry", self)
        data.setdefault("command_mode", self.command_mode)
        data.setdefault("require_at", self.require_at)
        return route_and_expand(raw, data)


# ---------------------------------------------------------------------------
# 路由结果 / 路由上下文
# ---------------------------------------------------------------------------

class RouteResult:
    """路由管线输出（供调用方消费：送状态机 / 交给解析器 / 忽略）。

    kind: 路由类别（session/shortcut/alias/command/hidden_original/ignored）；
    mode: 触发来源（normal/shortcut/alias/session_digit，对齐 3c P03）；
    command: 规范化指令名（别名时=原指令名 P07；shortcut 展开时=指令串）；
    display_name: 显示层名称（别名优先 P08）；
    session_route: True=已移交激活会话状态机（P02，本解析链中止）；
    subword: 会话子词 (category, value)；
    args_text: 指令名之后的参数剩余串（供 parsers.py 继续 token 化）；
    compact: 指令名与首参数紧贴（粘合写法 P06）；
    shortcut_name/shortcut_command/expand_count: 快捷来源信息（P04）；
    prefix_stripped: 是否已剥离 / 前缀（S0）。
    """

    def __init__(
        self,
        kind: str,
        *,
        raw: str = "",
        text: str = "",
        mode: str = MODE_NORMAL,
        session_route: bool = False,
        subword: Optional[tuple] = None,
        command: Optional[str] = None,
        display_name: Optional[str] = None,
        args_text: str = "",
        compact: bool = False,
        shortcut_name: Optional[str] = None,
        shortcut_command: Optional[str] = None,
        expand_count: int = 0,
        prefix_stripped: bool = False,
        alias: Optional["AliasEntry"] = None,
        spec: Optional[CommandSpec] = None,
        reason: Optional[str] = None,
    ) -> None:
        self.kind = kind
        self.raw = raw
        self.text = text
        self.mode = mode
        self.session_route = session_route
        self.subword = subword
        self.command = command
        self._display_name = display_name
        self.args_text = args_text
        self.compact = compact
        self.shortcut_name = shortcut_name
        self.shortcut_command = shortcut_command
        self.expand_count = expand_count
        self.prefix_stripped = prefix_stripped
        self.alias = alias
        self.spec = spec
        self.reason = reason

    @property
    def display_name(self) -> str:
        """显示层名称（P08：别名优先；无别名 → 指令名 / 快捷串 / 原文）。"""
        if self._display_name:
            return self._display_name
        if self.command:
            return self.command
        if self.shortcut_command:
            return self.shortcut_command
        return self.text or self.raw

    @property
    def is_gm(self) -> bool:
        """执行层权限二次检查位（E02 / W07）：命中指令是否为 GM 指令。"""
        return bool(self.spec and self.spec.is_gm)

    @property
    def ignored(self) -> bool:
        return self.kind == ROUTE_IGNORED

    def __repr__(self) -> str:
        return (
            f"<RouteResult kind={self.kind} mode={self.mode}"
            + (f" command={self.command!r}" if self.command else "")
            + (f" display={self._display_name!r}" if self._display_name else "")
            + (f" session_route={self.session_route}" if self.session_route else "")
            + ">"
        )


class RoutingContext:
    """路由上下文（调用方注入；等价接受 dict 形态）。

    字段（dict 键同名字段）：
      registry:      Router 或 {指令名: CommandSpec} 映射（白名单匹配/冲突检测用）
      shortcuts:     快捷表 {快捷名: 完整指令串}（L145，每玩家独立，由调用方注入）
      aliases:       指令别名配置（3c A02 形态，见 normalize_aliases）
      dialog_active: 对话会话是否激活（激活区间=建会话→收尾，2b2 L135）
      battle_active: 战斗会话是否激活（仅用于 combat_shortcut 免前缀判定；**不触发会话路由，裁决①**）
      command_mode:  global_shortcut（默认）/ prefix_only / combat_shortcut（L92-97）
      require_at:    @机器人 触发开关（默认关，L102-104）
      at_text:       @机器人 匹配文本（默认 "@机器人"）
    """

    def __init__(self, data: Optional[Mapping] = None) -> None:
        d = dict(data) if data else {}
        self.registry = d.get("registry")
        self.shortcuts: Dict[str, str] = dict(d.get("shortcuts") or {})
        aliases_raw = d.get("aliases")
        self.aliases = (
            aliases_raw if isinstance(aliases_raw, AliasTable) else AliasTable.from_config(aliases_raw)
        )
        self.dialog_active = bool(d.get("dialog_active"))
        self.battle_active = bool(d.get("battle_active"))
        self.command_mode = d.get("command_mode") or "global_shortcut"
        self.require_at = bool(d.get("require_at"))
        self.at_text = str(d.get("at_text") or "@机器人")


def _as_ctx(ctx: Any) -> RoutingContext:
    return ctx if isinstance(ctx, RoutingContext) else RoutingContext(ctx)


# ---------------------------------------------------------------------------
# 路由管线 快捷表→别名→白名单→忽略（3c §5.3 / S5 裁决；含会话路由）
# ---------------------------------------------------------------------------

def _split_first(text: str) -> tuple:
    """首词（空格分隔）+ 剩余串。"""
    parts = text.split(None, 1)
    return parts[0], (parts[1] if len(parts) > 1 else "")


def _strip_trigger_prefix(text: str, ctx: RoutingContext, *,
                          at_gate_passed: bool = False) -> tuple:
    """S0 预处理：剥离触发前缀（记录 prefix_stripped / at_stripped）。

    剥离顺序统一为「先 @ 后 /」（与 parsers S0 同序，P1-2b 对拍）：
      - require_at 开启：@机器人 是唯一放行入口——先剥 @，再剥紧随的 /（@机器人 /攻击 2）；
        输入无 @ 且非快捷展开（at_gate_passed=False）→ 一律不剥（裸 / 也不豁免 @，P1-2a，
        与 parsers 一致）；at_gate_passed=True（快捷展开串，触发消息已过 @ 门）时展开串的
        / 正常剥离（对齐 parsers 展开重入 require_at=False）。
      - require_at 关闭：只剥前导 /。

    返回 (text, prefix_stripped, at_stripped)。
    """
    prefix_stripped = False
    at_stripped = False
    if ctx.require_at:
        if text.startswith(ctx.at_text):
            text = text[len(ctx.at_text):].lstrip()
            at_stripped = True
            if text.startswith("/"):
                text = text[1:].strip()
                prefix_stripped = True
        elif at_gate_passed and text.startswith("/"):
            text = text[1:].strip()
            prefix_stripped = True
    elif text.startswith("/"):
        text = text[1:].strip()
        prefix_stripped = True
    return text, prefix_stripped, at_stripped


def _spec_of(registry: Any, name: str) -> Optional[CommandSpec]:
    if registry is None:
        return None
    if isinstance(registry, Router):
        return registry.get(name)
    if isinstance(registry, Mapping):
        spec = registry.get(name)
        return spec if isinstance(spec, CommandSpec) else None
    getter = getattr(registry, "get", None)
    if callable(getter):
        spec = getter(name)
        return spec if isinstance(spec, CommandSpec) else None
    return None


def _registry_names(registry: Any) -> set:
    if registry is None:
        return set()
    if isinstance(registry, Router):
        return set(registry.names())
    if isinstance(registry, Mapping):
        return {n for n, s in registry.items() if isinstance(s, CommandSpec)}
    return set()


def _whitelist_names(registry: Any) -> set:
    """白名单名集合（S5 ③：仅 whitelisted=True 参与开头匹配）。"""
    if registry is None:
        return set()
    if isinstance(registry, Router):
        return set(registry.whitelist_names())
    if isinstance(registry, Mapping):
        return {n for n, s in registry.items() if isinstance(s, CommandSpec) and s.whitelisted}
    return set()


def _match_whitelist(first: str, registry: Any) -> Optional[tuple]:
    """白名单开头匹配（S5 ③ L151）：指令名是首词的前缀（含精确）。

    返回 (CommandSpec, compact_args)；无命中 → None。最长指令名前缀优先。
    """
    names = _whitelist_names(registry)
    if not first or not names:
        return None
    # 精确匹配（无紧凑参数）优先
    if first in names:
        return _spec_of(registry, first), ""
    best: Optional[tuple] = None
    for name in names:
        if first.startswith(name):
            if best is None or len(name) > len(best[0].name):
                best = (_spec_of(registry, name), first[len(name):])
    return best


def _bare_allowed(ctx: RoutingContext) -> bool:
    """免前缀触发是否允许（E05 / L92-97 联动）：

    - prefix_only → 全部需 /（快捷/别名/白名单均须带前缀）；
    - combat_shortcut → 战斗内免前缀、战斗外需 /；
    - global_shortcut（默认）→ 免前缀。
    """
    mode = ctx.command_mode
    if mode == "prefix_only":
        return False
    if mode == "combat_shortcut":
        return ctx.battle_active
    return True


def _trigger_allowed(spec: CommandSpec, prefix_stripped: bool, ctx: RoutingContext,
                     authorized_prefix: bool = False) -> bool:
    """白名单触发条件（S0 ③ / W07 / L92-97）：

    - 已带 / 前缀 → 允许；
    - GM 指令 → 强制 / 前缀（W07/L128），裸发与快捷授权（authorized_prefix）均不豁免；
    - 其余按 command_mode（_bare_allowed）；authorized_prefix（快捷以 / 触发后展开）放行。
    """
    if prefix_stripped:
        return True
    if spec.is_gm:
        return False
    return authorized_prefix or _bare_allowed(ctx)


def route_message(raw: str, ctx: Any = None, *, allow_shortcut: bool = True,
                  authorized_prefix: bool = False,
                  at_gate_passed: bool = False) -> RouteResult:
    """路由管线单级判定（3c §5.3 优先级总表 + 2b2 R1-R5 + 裁决①）：

      ① 对话会话激活 且 输入 ∈ {纯数字, 继续, 退出/离开/再见, 选择 N} → 送状态机
         （mode=session_digit，会话优先于快捷 R3）【裁决①：战斗中裸数字不送会话，落 ②】
      ② 快捷表精确匹配（完整消息匹配快捷名，L149①）→ mode=shortcut（allow_shortcut=False 跳过）
      ③ 指令别名（全局配置，L150②）→ mode=alias，command=原指令名
      ④ 指令白名单开头匹配（L151③）→ mode=normal（GM 强制 / 前缀；显示层别名替换 A05）
      ⑤ 忽略（非指令消息，L152④ / L126-127）

    allow_shortcut=False 时跳过 ① 会话与 ② 快捷（S7 裁决：快捷展开后从指令名层 S4 续走，不再回查）。
    authorized_prefix=True 时按已授权前缀放行（E01/E05：快捷以 / 触发后，展开串不再受前缀模式门控，
    由 route_and_expand 注入）。
    at_gate_passed=True 时跳过 require_at @ 门（P1-2 对拍：触发消息已过 @ 门，快捷展开串不再
    重复要求 @，对齐 parsers 展开重入 require_at=False；由 route_and_expand 注入）。
    返回 RouteResult。
    """
    c = _as_ctx(ctx)
    text = str(raw or "").strip()
    if not text:
        return RouteResult(ROUTE_IGNORED, raw=raw, text="", reason="empty")

    text, prefix_stripped, at_stripped = _strip_trigger_prefix(text, c, at_gate_passed=at_gate_passed)
    if not text:
        return RouteResult(ROUTE_IGNORED, raw=raw, text=text, prefix_stripped=prefix_stripped,
                           reason="empty_after_prefix")
    # 【工程补白】require_at 开启但输入既无 @ 也无 / → 非指令触发，忽略
    # （P1-2a：裸 / 也不豁免 @；at_gate_passed=True 时触发消息已过 @ 门，不重复判定）
    if c.require_at and not prefix_stripped and not at_stripped and not at_gate_passed:
        return RouteResult(ROUTE_IGNORED, raw=raw, text=text, prefix_stripped=prefix_stripped,
                           reason="require_at_miss")

    # ① 会话路由（仅对话会话激活；战斗侧裁决①不送会话）
    if c.dialog_active:
        sub = is_session_subword(text)
        if sub is not None:
            return RouteResult(
                ROUTE_SESSION, raw=raw, text=text, mode=MODE_SESSION_DIGIT,
                session_route=True, subword=sub, prefix_stripped=prefix_stripped,
            )

    # 前缀模式门控（E05：prefix_only / 战外 combat_shortcut 下，快捷/别名/白名单均须带 /；
    # authorized_prefix：快捷以 / 触发后展开串放行）
    bare_ok = prefix_stripped or authorized_prefix or _bare_allowed(c)

    # ② 快捷表精确匹配（完整消息匹配快捷名，L149①；E05 前缀联动）
    if allow_shortcut and bare_ok and text in c.shortcuts:
        return RouteResult(
            ROUTE_SHORTCUT, raw=raw, text=text, mode=MODE_SHORTCUT,
            shortcut_name=text, shortcut_command=c.shortcuts[text],
            prefix_stripped=prefix_stripped,
        )

    first, rest = _split_first(text)

    # ③ 指令别名（全局配置，L150②；同样受前缀模式门控）
    entry = c.aliases.alias_for(first) if bare_ok else None
    if entry is not None:
        compact = len(first) > len(entry.alias)
        args_text = (first[len(entry.alias):] + (" " + rest if rest else "")) if compact else rest
        return RouteResult(
            ROUTE_ALIAS, raw=raw, text=text, mode=MODE_ALIAS,
            command=entry.command, display_name=entry.alias,
            args_text=args_text, compact=compact, alias=entry,
            prefix_stripped=prefix_stripped,
        )

    # ④ 指令白名单开头匹配
    matched = _match_whitelist(first, c.registry)
    if matched is not None:
        spec, compact_args = matched
        if not _trigger_allowed(spec, prefix_stripped, c, authorized_prefix):
            reason = "gm_requires_prefix" if spec.is_gm else "prefix_required"
            return RouteResult(ROUTE_IGNORED, raw=raw, text=text,
                               prefix_stripped=prefix_stripped, reason=reason)
        compact = bool(compact_args)
        args_text = (compact_args + (" " + rest if rest else "")) if compact else rest
        # 显示层别名替换（A05）；keep_original=false → 原指令隐藏（A04 → hidden_original）
        own_alias = c.aliases.for_command(spec.name)
        if own_alias is not None and not own_alias.keep_original:
            return RouteResult(
                ROUTE_HIDDEN, raw=raw, text=text, mode=MODE_ALIAS,
                command=spec.name, display_name=own_alias.alias,
                args_text=args_text, compact=compact, alias=own_alias, spec=spec,
                prefix_stripped=prefix_stripped,
            )
        return RouteResult(
            ROUTE_COMMAND, raw=raw, text=text, mode=MODE_NORMAL,
            command=spec.name,
            display_name=own_alias.alias if own_alias else None,
            args_text=args_text, compact=compact, spec=spec,
            prefix_stripped=prefix_stripped,
        )

    # ⑤ 忽略（非指令消息）
    return RouteResult(ROUTE_IGNORED, raw=raw, text=text, prefix_stripped=prefix_stripped,
                       reason="no_match")


def route_and_expand(raw: str, ctx: Any = None) -> RouteResult:
    """完整消息路由（含一级快捷展开，S7 裁决：展开深度=1）。

    命中快捷 → 替换为完整指令串，从指令名层（S4 别名）续走，不再回查快捷表；
    最终结果保留快捷来源信息（mode=shortcut / expand_count=1 / shortcut_name / shortcut_command）。
    其余情况与 route_message 一致。
    """
    first = route_message(raw, ctx)
    if first.kind != ROUTE_SHORTCUT:
        return first
    if not first.shortcut_command:
        # 工程补白：快捷命中断言其展开串存在（kind=shortcut 时必置）
        return first
    second = route_message(first.shortcut_command, ctx, allow_shortcut=False,
                           authorized_prefix=first.prefix_stripped,
                           at_gate_passed=True)
    # 保留快捷来源信息（P03 mode=shortcut / P04 expand_count=1）
    second.raw = raw
    second.mode = MODE_SHORTCUT
    second.expand_count = 1
    second.shortcut_name = first.shortcut_name
    second.shortcut_command = first.shortcut_command
    return second


# 消息入口别名（完整管线 = route_and_expand）
dispatch_message = route_and_expand


# ---------------------------------------------------------------------------
# 指令别名（3c 4.5 A01-A08：显示层替换 / keep_original）
# ---------------------------------------------------------------------------

class AliasEntry:
    """指令别名条目（3c 4.5 A01-A08）。

    command: 原指令名；alias: 别名；keep_original: True（默认）=原指令保留可用，
    False=原指令隐藏禁用（A04 → 发原指令「没有这个指令，试试『XX』？」）。
    """

    def __init__(self, command: str, alias: str, keep_original: bool = True) -> None:
        self.command = command
        self.alias = alias
        self.keep_original = bool(keep_original)

    def __eq__(self, other: Any) -> bool:
        return (
            isinstance(other, AliasEntry)
            and self.command == other.command
            and self.alias == other.alias
            and self.keep_original == other.keep_original
        )

    def __repr__(self) -> str:
        ko = "keep_original" if self.keep_original else "hidden"
        return f"<AliasEntry {self.alias}→{self.command} ({ko})>"


class AliasTable:
    """指令别名查询表（{alias: AliasEntry} 查询 + {command: AliasEntry} 显示层反查）。

    alias_for(token):  输入首词 → 别名条目（精确优先，其次最长前缀【工程补白】紧凑别名）；
    for_command(name): 原指令名 → 别名条目（显示层替换 A05 / keep_original 判定 A04）；
    display_name(name): 原指令名 → 显示层名称（无别名=原指令名）。
    """

    def __init__(self, entries: Optional[Iterable[AliasEntry]] = None) -> None:
        self._by_alias: Dict[str, AliasEntry] = {}
        self._by_command: Dict[str, AliasEntry] = {}
        for e in entries or []:
            self._by_alias[e.alias] = e
            self._by_command.setdefault(e.command, e)

    @classmethod
    def from_config(cls, config: Any) -> "AliasTable":
        """从 3c A02 配置形态归一化：

          - {"炼金": {"alias":"炼丹","keep_original":false}}  键=原指令名，值=别名配置
          - {"锻造": "炼器"}                                 键=原指令名，值=别名串（keep_original=True）
          - {"炼丹": {"command":"炼金", ...}}                 键=别名，值=含 command 的配置（备选形态）
        """
        if config is None:
            return cls()
        if isinstance(config, AliasTable):
            return config
        if not isinstance(config, Mapping):
            raise TypeError(f"指令别名配置必须是映射，收到 {type(config).__name__}")
        entries: List[AliasEntry] = []
        for key, value in config.items():
            if isinstance(value, str):
                # 键=原指令名，值=别名（默认 keep_original=True）
                entries.append(AliasEntry(command=str(key), alias=value, keep_original=True))
            elif isinstance(value, Mapping):
                if "alias" in value:
                    # 键=原指令名
                    entries.append(AliasEntry(
                        command=str(key),
                        alias=str(value["alias"]),
                        keep_original=bool(value.get("keep_original", True)),
                    ))
                elif "command" in value:
                    # 键=别名
                    entries.append(AliasEntry(
                        command=str(value["command"]),
                        alias=str(key),
                        keep_original=bool(value.get("keep_original", True)),
                    ))
                else:
                    raise ValueError(f"别名配置缺 alias/command 键: {key!r}")
            else:
                raise ValueError(f"别名配置值形态非法: {key!r} → {value!r}")
        return cls(entries)

    def alias_for(self, token: str) -> Optional[AliasEntry]:
        """首词 → 别名条目。精确匹配优先；未命中按最长前缀（紧凑别名【工程补白】）。"""
        if not token:
            return None
        if token in self._by_alias:
            return self._by_alias[token]
        best: Optional[AliasEntry] = None
        for alias, entry in self._by_alias.items():
            if token.startswith(alias) and len(alias) < len(token):
                if best is None or len(alias) > len(best.alias):
                    best = entry
        return best

    def for_command(self, command: str) -> Optional[AliasEntry]:
        return self._by_command.get(command)

    def display_name(self, command: str) -> str:
        """显示层名称（A05：别名优先；无别名=原指令名）。"""
        entry = self._by_command.get(command)
        return entry.alias if entry else command

    def alias_names(self) -> set:
        return set(self._by_alias)

    def commands(self) -> set:
        return set(self._by_command)

    def __bool__(self) -> bool:
        return bool(self._by_alias)


def normalize_aliases(config: Any) -> AliasTable:
    """别名配置归一化（等价 AliasTable.from_config，供快捷绑定冲突检测复用）。"""
    return AliasTable.from_config(config)


# ---------------------------------------------------------------------------
# 快捷绑定校验（3c §4.3 C01-C05 / E03 上限 / GM 禁绑 C02）
# ---------------------------------------------------------------------------

def resolve_command_word(text: str, *, registry: Any = None,
                         aliases: Any = None) -> Optional[str]:
    """消息首词 → 规范化指令名（经别名展开；无白名单命中 → None）。

    供 is_gm_command / 快捷绑定目标解析使用；剥离前导 / 与首词。
    """
    t = str(text or "").strip()
    if t.startswith("/"):
        t = t[1:].strip()
    if not t:
        return None
    first, _ = _split_first(t)
    at = aliases if isinstance(aliases, AliasTable) else AliasTable.from_config(aliases)
    entry = at.alias_for(first)
    if entry is not None:
        return entry.command
    matched = _match_whitelist(first, registry)
    if matched is not None:
        return matched[0].name
    return None


def is_gm_command(target_text: str, *, registry: Any = None,
                  gm_commands: Optional[Iterable[str]] = None,
                  aliases: Any = None) -> bool:
    """目标指令串首词是否为 GM 指令（C02 禁绑判定 / E02 执行层二次检查）。

    gm_commands 显式给出 → 直接查集合（无需 registry 白名单即可判定）；
    否则查 registry 内 spec.is_gm。首词先剥离 / 并经别名展开。
    """
    t = str(target_text or "").strip()
    if t.startswith("/"):
        t = t[1:].strip()
    first, _ = _split_first(t) if t else ("", "")
    if not first:
        return False
    at = aliases if isinstance(aliases, AliasTable) else AliasTable.from_config(aliases)
    entry = at.alias_for(first)
    word = entry.command if entry is not None else first
    if gm_commands is not None:
        return word in set(gm_commands)
    spec = _spec_of(registry, word)
    return bool(spec and spec.is_gm)


def _first_word(text: str) -> str:
    t = str(text or "").strip()
    if t.startswith("/"):
        t = t[1:].strip()
    return _split_first(t)[0] if t else ""


_RESERVED_CHAR_RE = re.compile(r"[\s*,=+/]")


def _has_reserved_char(name: str) -> bool:
    """C03：快捷名含空格/保留字符（`* , = + /` 保留字符，L58/L162）。"""
    return bool(_RESERVED_CHAR_RE.search(name))


def check_shortcut_binding(
    shortcut_name: str,
    target_text: str,
    *,
    registry: Any = None,
    gm_commands: Optional[Iterable[str]] = None,
    aliases: Any = None,
    reserved_words: Optional[Iterable[str]] = None,
) -> dict:
    """快捷绑定校验（3c §4.3 C01-C05，GM 禁绑为核心）。返回 verdict dict：

      {ok, code, message?, hint?}
      - ok=False code="gm_forbidden"  → C02 GM 禁绑（防权限绕过，L160-161）
      - ok=False code="name_conflict" → C01 绑定名 ∈ 动态注册表（框架指令+内容包+固定子词，L158-159）
      - ok=False code="empty_name"    → 快捷名为空
      - ok=True  code="name_format_hint" → C03 名称含空格/保留字符（提示不拦截，L162/L60）
      - ok=True  code="ok"            → 通过（可绑定/覆盖）
    覆盖（C05）由调用方按既有绑定存在性自行提示，本校验不感知玩家存储。
    """
    s = str(shortcut_name or "").strip()
    if not s:
        return {"ok": False, "code": "empty_name", "message": "快捷名不能为空"}

    # C02 GM 禁绑（优先，防权限绕过）
    if is_gm_command(target_text, registry=registry, gm_commands=gm_commands, aliases=aliases):
        gm_word = _first_word(target_text)
        return {
            "ok": False,
            "code": "gm_forbidden",
            "message": f"『{gm_word}』是 GM 指令，不可绑定为快捷",
        }

    # C01 名称冲突：动态注册表 = 框架指令 ∪ 内容包注册指令 ∪ 固定子词（S6 裁决）
    occupied = _registry_names(registry)
    at = aliases if isinstance(aliases, AliasTable) else AliasTable.from_config(aliases)
    occupied |= at.alias_names()
    occupied |= set(reserved_words or [])
    if s in occupied:
        return {
            "ok": False,
            "code": "name_conflict",
            "message": f"『{s}』已经是现有指令，换个快捷名吧（如 a/1/火球）",
        }

    # C03 名称格式建议（提示不拦截，只建议不限制 L246）
    if _has_reserved_char(s):
        return {
            "ok": True,
            "code": "name_format_hint",
            "hint": f"快捷名『{s}』含空格或保留字符，建议 1-4 字符（数字/字母/汉字）",
        }

    return {"ok": True, "code": "ok"}


def check_shortcut_limit(count: int, limit: int = 20) -> dict:
    """快捷表上限校验（E03：每玩家默认 20 条，0=不限；L172）。"""
    if limit and limit > 0 and int(count) >= int(limit):
        return {
            "ok": False,
            "code": "shortcut_full",
            "message": f"快捷已满 {limit} 条，先解绑再绑",
        }
    return {"ok": True, "code": "ok"}


def register_command(
    name: str,
    *,
    aliases: Optional[List[str]] = None,
    permission: str = PERM_USER,
    handler: Optional[Callable[..., Any]] = None,
    whitelisted: bool = True,
    is_gm: bool = False,
) -> CommandSpec:
    """指令注册便捷构造（M4：NoneBot on_command 注册包壳；零 nonebot 本文件内）。"""
    return CommandSpec(
        name,
        aliases=aliases,
        permission=permission,
        handler=handler,
        whitelisted=whitelisted,
        is_gm=is_gm,
    )
