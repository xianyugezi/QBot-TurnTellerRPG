"""指令解析器 Parsers（M4 批次1·路B1 实装）。

依据：
  - m4_shared_contract §2.1（解析管线：快捷表 → 别名 → 白名单 → 忽略；分隔符全集；
    快捷指令三模式 + require_at 默认关 + 紧凑/空格双认；会话路由判定；ParsedCommand 形态）
  - 细化_3c_指令解析契约 §1-§4（分隔符七种 / 紧凑+空格双认 / command_mode 三模式 /
    快捷绑定 / 指令别名 / 解析状态机 S0-S8 / 错误模板四类 / 验收 TC-01~45）
  - docs/审查参考/指令分隔符统一规范.md v1.1（权威 246 行）
  - 2026-08-27 裁决①（M4 设计审查 P0-1）：战斗中裸数字 = 快捷绑定（无会话上下文，
    快捷表生效），不送战斗状态机；选技能用带指令词「/攻击 2」（序号不带 *）。
  - M4 实现审查批次1 P1-2（审查_M4实现_批次1_jspace.md）：双管线口径漂移修复 ③——
    GM 判定从「prefix_required 集合」升级为「spec.is_gm 且前缀必须真正落在展开串上」
    （对齐 router._trigger_allowed W07/L128：快捷授权不豁免 GM，触发消息的 '/' 不算数）；
    新增 gm_commands 参数承载 GM 指令集合（与 router spec.is_gm 对拍），并补
    tests/unit/test_dual_pipeline_parity.py 同输入两管线一致性测试。

铁律（m4_shared_contract §0 / M3 沿用）：
  - 纯逻辑、零 NoneBot import（commands 层同为纯解析；唯一 NoneBot 接触点=装配入口）。
  - 确定性（无 IO / 无随机 / 无懒加载）；工程补白一律以【工程补白】标注。
  - 本模块只做「解析」与「会话路由判定」的**语义标记**（mode=session_digit /
    session_candidate），不接状态机；会话是否激活由调用方传入——
    对话=2b2 状态机生命周期；战斗按裁决①**永不置会话激活**（调用方对战斗传
    session_active=False，战斗裸数字即走快捷表，天然满足裁决①）。

ParsedCommand 形态（任务要求核心 6 字段 + 3c §3.2 P01-P18 对齐扩展）：
  {raw, tokens, command, args, mode, session_candidate,
   session_route, expand_count, prefix_stripped, compact, display_name,
   fixed_subword, kv, targets, qty, seq, level, path, error, hints, alias_hidden}

分隔符全集（7 种，规范 §一）：
  空格分参数、`*` 连数量、`,` 列列表、`=` 键值、`+` 等级、`-` 连招/区间、`>` 路径；
  物品名禁空格（N01 保留字符，解析层仅黄色提示不拦截）。
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

__all__ = [
    "ParsedCommand",
    "parse_command",
    "parse_int",
    # 触发来源 / 模式常量
    "MODE_NORMAL",
    "MODE_SHORTCUT",
    "MODE_ALIAS",
    "MODE_ALIAS_HIDDEN",
    "MODE_SESSION",
    "MODE_IGNORED",
    "MODE_PREFIX_ONLY",
    "MODE_COMBAT_SHORTCUT",
    "MODE_GLOBAL_SHORTCUT",
    # 错误模板四类（规范 L72；缺参需 command_specs 声明，其余纯结构可判）
    "ERR_MISSING",
    "ERR_TOO_MANY",
    "ERR_UNKNOWN_SEP",
    "ERR_RESERVED",
    # 常量
    "FIXED_SUBWORDS",
    "DEFAULT_WHITELIST",
    "DEFAULT_PREFIX_REQUIRED",
    "DEFAULT_GM_COMMANDS",
    "DEFAULT_QUANTITY_COMMANDS",
    "DEFAULT_NO_QUANTITY_COMMANDS",
    "DEFAULT_MAX_QTY",
    "is_session_subword",
    "reserved_char_hint",
]

# ---------------------------------------------------------------------------
# 常量：触发来源 / 模式 / 错误模板
# ---------------------------------------------------------------------------

# 触发来源（3c P03）
MODE_NORMAL = "normal"              # 正常指令解析
MODE_SHORTCUT = "shortcut"          # 快捷表触发（完整消息精确匹配快捷名）
MODE_ALIAS = "alias"                # 指令别名触发（发别名 = 执行原指令）
MODE_ALIAS_HIDDEN = "alias_hidden"  # 发被隐藏的原指令名（keep_original=false → 引导提示）
MODE_SESSION = "session_digit"      # 会话子词（对话激活时纯数字/继续/退出/选择 N → 送状态机）
MODE_IGNORED = "ignored"            # 非指令消息（无白名单匹配，规范 ④ L152）

# command_mode 三模式（规范 6.1 L88-98；settings.json 可配，默认全局免前缀）
MODE_PREFIX_ONLY = "prefix_only"        # 需要前缀：全部指令必须 /
MODE_COMBAT_SHORTCUT = "combat_shortcut"  # 战斗内免前缀；战斗外必须 /
MODE_GLOBAL_SHORTCUT = "global_shortcut"  # 全局免前缀（默认）

# 错误模板四类（规范 L72 / 3c §3.1）
ERR_MISSING = "缺参"
ERR_TOO_MANY = "超参"
ERR_UNKNOWN_SEP = "未知分隔符"
ERR_RESERVED = "保留字符违规"  # 命名铁律 N03：黄色提示不拦截（只建议不限制）

# ---------------------------------------------------------------------------
# 常量：固定子词 / 会话子词 / 默认白名单
# ---------------------------------------------------------------------------

# 固定子词表（规范 L71 / 3c P09）：内置常量，优先于物品匹配
FIXED_SUBWORDS = frozenset({"追加", "预览", "自动", "查看", "确认", "放弃", "续"})

# 会话子词（2b2 R1 泛化，3c §5）：纯数字 / 继续 / 退出 / 离开 / 再见 / 选择 N
_SESSION_EXIT_WORDS = frozenset({"继续", "退出", "离开", "再见"})
_RE_SESSION_DIGIT = re.compile(r"^\d+$")
_RE_SESSION_SELECT = re.compile(r"^选择\s*\d+$")

# 默认指令白名单（3c §2.3 W01-W04 + 基础指令组 + 快捷绑定指令；调用方可覆盖）
DEFAULT_WHITELIST = frozenset(
    {
        # W01 高频可快捷
        "攻击", "使用", "进入", "锁定怪物", "采集",
        # W02 制造可快捷（全局模式下）
        "合成", "炼金", "锻造", "强化", "调合", "镶嵌", "拆珠",
        # M9 锻造·批5 路5C：/锻造树 全树可锻装备分页视图（2c2b §5.3 登记指令 L234）——
        # 独立指令名注册须进白名单才能被 S5 前缀匹配触发（P-05 同款裁决；缺白名单静默不响应）
        "锻造树",
        # M9 锻造·批5 路5A：/图纸 主链+分支+持有进度（2c2b §5.3 登记指令 L235；批C 审查
        # P1-2 补登记 2026-08-30——独立指令名缺白名单 → S5 静默不响应 + check_consistency 硬不一致）
        "图纸",
        # M9 锻造·批7 路7C：/套装 /客制 查询指令（2c2d §5.3 登记指令 L236/L237）——
        # 独立指令名注册须进白名单才能被 S5 前缀匹配触发（P-05 同款裁决；缺白名单静默不响应）
        "套装", "客制",
        # W03 状态查询
        "状态", "背包", "背包筛选", "怪物", "地图",
        # 基础指令组（4f 常见）
        "注册", "注销", "角色", "角色详细", "装备", "技能", "帮助", "休息", "对话",
        "任务", "商店", "购买", "出售", "签到",
        # 3f 单机向体验（F-05/F-06/F-07）：/调查 目标可选（交互点别名/地图名/省略=当前地图）
        "调查",
        # 3f 单机向体验（F-11/F-12）：/图鉴 分册总览/分册分页（未收集条目 ???）
        "图鉴",
        # 快捷绑定指令（规范 6.6）
        "快捷绑定", "快捷解绑", "快捷列表",
        # 规范示例出现的制造/生活指令（L17 投料 / L49 代工 / L42 继承）
        "投料", "代工", "继承",
        # M8 炼金会话/终态/深度/合成/资源循环（m8_contract 指令契约 §3.1 批11 补齐：
        # 独立指令名注册须进白名单才能被 S5 前缀匹配触发，P-05；/秘钥 已砍不注册）
        # 批11-2 收口裁决补「珠升阶」（批7-2 已实现指令，缺白名单静默不响应）
        "继承超", "确认", "放弃", "调合续",
        "深度炼金", "进化", "镶核心", "加成",
        "成品合成", "分解", "登记", "复制",
        "配方合成", "特性合成", "挑战", "即时调合",
        "教学", "协力", "种植", "收获", "收取", "技能面板", "珠升阶",
        # GM 指令（5b；强制 / 前缀，永不快捷，规范 L128）
        "重载", "封禁", "日志", "编辑", "设置",
    }
)

# 需 / 前缀的指令（免前缀一律忽略）：GM 指令（L128）+ /对话（m4 §2.3 接缝裁决：
# 可快捷绑定、不可免前缀直发）+ /调查（3f R-07 同款接缝：可快捷绑定、不可免前缀直发）
DEFAULT_PREFIX_REQUIRED = frozenset(
    {"重载", "封禁", "日志", "编辑", "设置", "对话", "调查", "图鉴"}
)

# 自由参数指令（M5-09 筛选链）：位置参数数量不限（豁免 S7 铁律 3「第 3 参数起强制
# 列表/键值」+ ≤2 上限）。框架 §7.4 L1336 语法 `<功能>筛选 <物品类型> [类型 <子类目>]
# [品质 <品质>]` —— 空格分隔的多词筛选条件按位置参数直取（4f RUL-16 / TC-14）。
DEFAULT_FREE_ARG_COMMANDS = frozenset({"背包筛选"})

# GM 指令（5b L160 长清单：重载/封禁/日志/编辑/设置；L128 强制 / 前缀 + 永不快捷 +
# 快捷禁绑 C02）。与 router spec.is_gm 对齐（P1-2c 对拍）：GM 判定用本集合而非
# prefix_required（后者另含非 GM 的 /对话）；GM 要求 '/' 前缀**真正落在当前展开串上**，
# 快捷展开的触发 '/' 不豁免（对齐 router._trigger_allowed）。
DEFAULT_GM_COMMANDS = frozenset({"重载", "封禁", "日志", "编辑", "设置"})

# 旧空格数量格式兼容回退适用指令（规范 L238-239；调用方可覆盖）
# M8 批13 审查收口（P2-5）：加「复制」——契约 §3.3 要求 /复制 兼容 `空格 数量` 旧式
# （`/复制 魔力药水 5`），`*` 批量语法不依赖本集合（parsers L532-548 全指令生效）。
DEFAULT_QUANTITY_COMMANDS = frozenset(
    {"使用", "购买", "合成", "投料", "出售", "炼金", "调合", "复制"}
)

# 禁止 `*` 数量的指令（规范 L34：/强化 禁止 *，批量=连点爆装风险；+N 是等级标记）
DEFAULT_NO_QUANTITY_COMMANDS = frozenset({"强化"})

# 数量上限（规范 L33：默认 ≤99 可配，仅提示不拦截）
DEFAULT_MAX_QTY = 99

# token 合法字符集：CJK + 字母数字下划线 + 登记分隔符 `* , = + - >` + 允许名
# 字符 `· Ⅱ`（N02）+ 全角逗号 `，`（列表等价，L42）+ 半角 `%`（词条数值 回复量+5%，D03）
# 其余符号（！/％/#/@/$/&/?/~/|/\\ 等）一律按「未知分隔符」（S1 裁决，L72）
_ALLOWED_TOKEN_RE = re.compile(r"^[\w\u4e00-\u9fff·Ⅱ*+=>,，%\-]+$")

# 保留字符（命名铁律 N01：禁止空格、禁止 `* , = + /`；仅黄色提示不拦截）
_RESERVED_CHARS = re.compile(r"[*\s,=+/]")


# ---------------------------------------------------------------------------
# ParsedCommand
# ---------------------------------------------------------------------------


class ParsedCommand:
    """指令解析结果。

    核心 6 字段（任务要求）：raw / tokens / command / args / mode / session_candidate；
    扩展字段对齐 3c §3.2 P01-P18（session_route / expand_count / prefix_stripped /
    compact / display_name / fixed_subword / kv / targets / qty / seq / level /
    path / error / hints / alias_hidden）。

    - mode：触发来源（normal/shortcut/alias/alias_hidden/session_digit/ignored）
    - session_candidate：输入是否为会话子词候选（对话激活时纯数字/继续/退出/选择 N）
    - session_route：true=应移交激活会话状态机（本模块只标记语义，不接状态机）
    - command：None=非指令（ignored / session / alias_hidden）
    - args：位置参数（原始 token 形态，≤2；结构化视图见 qty/targets/kv/seq/level/path）
    - error：四类错误模板之一（缺参需 command_specs 声明；保留字符违规=黄色提示入 hints）
    - hints：非拦截提示（数量超限 / 紧凑回写 / 黄色建议 / 旧格式兼容回写）
    """

    __slots__ = (
        "raw", "tokens", "command", "args", "mode", "session_candidate",
        "session_route", "expand_count", "prefix_stripped", "compact",
        "display_name", "fixed_subword", "kv", "targets", "qty", "seq",
        "level", "path", "error", "hints", "alias_hidden",
    )

    def __init__(
        self,
        raw: str,
        *,
        tokens: Optional[Iterable[str]] = None,
        command: Optional[str] = None,
        args: Optional[Iterable[str]] = None,
        mode: str = MODE_NORMAL,
        session_candidate: bool = False,
        session_route: bool = False,
        expand_count: int = 0,
        prefix_stripped: bool = False,
        compact: bool = False,
        display_name: Optional[str] = None,
        fixed_subword: Optional[str] = None,
        kv: Optional[Iterable[Dict[str, Any]]] = None,
        targets: Optional[Iterable[str]] = None,
        qty: Optional[int] = None,
        seq: Optional[Iterable[int]] = None,
        level: Optional[int] = None,
        path: Optional[Iterable[str]] = None,
        error: Optional[str] = None,
        hints: Optional[Iterable[str]] = None,
        alias_hidden: Optional[str] = None,
    ) -> None:
        self.raw = raw
        self.tokens: List[str] = list(tokens or [])
        self.command: Optional[str] = command
        self.args: List[str] = list(args or [])
        self.mode: str = mode
        self.session_candidate: bool = bool(session_candidate)
        self.session_route: bool = bool(session_route)
        self.expand_count: int = int(expand_count)
        self.prefix_stripped: bool = bool(prefix_stripped)
        self.compact: bool = bool(compact)
        self.display_name: Optional[str] = display_name
        self.fixed_subword: Optional[str] = fixed_subword
        self.kv: List[Dict[str, Any]] = list(kv or [])
        self.targets: List[str] = list(targets or [])
        self.qty: Optional[int] = qty
        self.seq: List[int] = list(seq or [])
        self.level: Optional[int] = level
        self.path: List[str] = list(path or [])
        self.error: Optional[str] = error
        self.hints: List[str] = list(hints or [])
        self.alias_hidden: Optional[str] = alias_hidden

    # -- 便捷视图 ----------------------------------------------------------

    @property
    def positional(self) -> List[str]:
        """3c P10 位置参数（= args 别称，兼容旧字段名）。"""
        return self.args

    @property
    def name(self) -> Optional[str]:
        """旧壳层字段兼容：指令名（= command）。"""
        return self.command

    @property
    def is_command(self) -> bool:
        """是否解析为一条可执行指令（非 ignored/session/alias_hidden）。"""
        return self.command is not None

    def arg(self, index: int, default: Optional[str] = None) -> Optional[str]:
        """按位取位置参数（越界返回 default），兼容旧壳层签名。"""
        return self.args[index] if index < len(self.args) else default

    # -- 构造辅助（非指令结果） --------------------------------------------

    @classmethod
    def _ignored(cls, raw: str, text: str) -> "ParsedCommand":
        return cls(raw, tokens=[text], mode=MODE_IGNORED, command=None)

    @classmethod
    def _session(cls, raw: str, text: str) -> "ParsedCommand":
        """会话子词：只标记语义（mode=session_digit / session_candidate），不接状态机。"""
        return cls(
            raw,
            tokens=[text],
            mode=MODE_SESSION,
            command=None,
            session_candidate=True,
            session_route=True,
        )

    @classmethod
    def _alias_hidden(cls, raw: str, text: str, orig: str, alias_name: str) -> "ParsedCommand":
        return cls(
            raw,
            tokens=[text],
            mode=MODE_ALIAS_HIDDEN,
            command=None,
            display_name=alias_name,
            alias_hidden=orig,
            hints=[f"没有这个指令，试试『{alias_name}』？"],
        )

    # -- dunder ------------------------------------------------------------

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, ParsedCommand):
            return NotImplemented
        return all(getattr(self, f) == getattr(other, f) for f in self.__slots__)

    def __repr__(self) -> str:
        return (
            f"ParsedCommand(raw={self.raw!r}, command={self.command!r}, "
            f"args={self.args!r}, mode={self.mode!r}, "
            f"qty={self.qty}, error={self.error!r}, hints={self.hints!r})"
        )


# ---------------------------------------------------------------------------
# 公共工具
# ---------------------------------------------------------------------------


def is_session_subword(text: str) -> bool:
    """会话子词判定（2b2 R1 泛化，3c §5.1）：纯数字 / 继续 / 退出 / 离开 / 再见 / 选择 N。

    仅做语义判定；是否送状态机由 parse_command 的 session_active 上下文决定。
    """
    t = (text or "").strip()
    if _RE_SESSION_DIGIT.match(t):
        return True
    if t in _SESSION_EXIT_WORDS:
        return True
    if _RE_SESSION_SELECT.match(t):
        return True
    return False


def reserved_char_hint(name: str) -> Optional[str]:
    """命名铁律 N03 黄色提示（不拦截，只建议不限制，规范 L60/L246）。

    供快捷绑定/注册层调用：名字含保留字符（空格/`* , = + /`）时返回提示文案，
    否则返回 None。解析层对纯位置参数同样调用（TC-15）。
    """
    if not name:
        return None
    if " " in name or "\t" in name:
        return "名字含空格容易歧义（建议改名）"
    if _RESERVED_CHARS.search(name):
        return "名字含保留字符（* , = + /），解析时容易歧义（建议改名）"
    return None


def parse_int(text: Optional[str]) -> Optional[int]:
    """安全整数解析（3d §2.2：页码等；非法返回 None → 壳层 TPL-12 报错）。

    仅接受完整整数（可带 +- 号）；'12'→12、'-3'→-3、'1.5'/'abc'/'12a'/''→None。
    """
    if text is None:
        return None
    t = str(text).strip()
    if re.fullmatch(r"[+-]?\d+", t):
        return int(t)
    return None


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _normalize_aliases(
    aliases: Optional[Mapping[str, Any]],
) -> Tuple[Dict[str, Tuple[str, bool]], Dict[str, str]]:
    """归一化指令别名配置（规范 6.7 L196-204）。

    入参两种形态：{"锻造": "炼器"}（默认 keep_original:true）或
    {"炼金": {"alias": "炼丹", "keep_original": false}}。
    返回 (alias_to_orig, orig_to_alias)：
      - alias_to_orig: {别名: (原指令名, keep_original)}
      - orig_to_alias: {原指令名: 别名}（仅含 keep_original=false 被隐藏的原指令）
    """
    alias_to_orig: Dict[str, Tuple[str, bool]] = {}
    orig_to_alias: Dict[str, str] = {}
    for orig, entry in (aliases or {}).items():
        if isinstance(entry, str):
            alias_name, keep = entry, True
        elif isinstance(entry, dict):
            alias_name = entry.get("alias")  # type: ignore[assignment]
            keep = bool(entry.get("keep_original", True))
        else:
            continue
        if not alias_name:
            continue
        alias_to_orig[alias_name] = (orig, keep)
        if not keep:
            orig_to_alias[orig] = alias_name
    return alias_to_orig, orig_to_alias


def _split_command(
    text: str, candidates: Iterable[str]
) -> Tuple[Optional[str], str, bool]:
    """指令名解析（S4/S5/S6 开头匹配，规范 L151）：返回 (指令名, 剩余串, 是否紧凑)。

    - 首词精确匹配（空格形）："攻击 2" → ("攻击", "2", False)
    - 紧贴最长前缀（紧凑形，L109/L240 粘合永久兼容）："攻击2" → ("攻击", "2", True)
    - 未命中 → (None, "", False)
    """
    head, _, tail = text.partition(" ")
    if head in candidates:
        return head, tail.strip(), False
    for name in sorted(candidates, key=len, reverse=True):
        if text.startswith(name):
            return name, text[len(name):].strip(), True
    return None, "", False


def _tokenize(remainder: str) -> List[str]:
    """S6 TOKENIZE：空格切分 token 流（紧凑形剩余串已是单 token）。"""
    return [t for t in remainder.split() if t.strip()]


def _split_list(token: str) -> List[str]:
    """`,` 列表拆（全角/半角等价，规范 L42 / TC-09）。"""
    return [s.strip() for s in re.split(r"[,，]", token) if s.strip()]


def _contains_list_sep(token: str) -> bool:
    return "," in token or "，" in token


def _parse_seq(token: str) -> Optional[List[int]]:
    """`-` 连招/区间（D06/S2）：'1-2-3'→[1,2,3] 序列；'1-3'→[1,2,3] 区间展开。

    仅纯数字连链（`-` 亦为允许名字符 N02，字母链如 'A-B' 不作 seq）。
    """
    if not re.fullmatch(r"\d+(?:-\d+)+", token):
        return None
    parts = [int(p) for p in token.split("-")]
    if len(parts) == 2:
        lo, hi = parts
        return list(range(lo, hi + 1)) if lo <= hi else [lo, hi]
    return parts


def _parse_kv_item(item: str) -> Tuple[str, str, Optional[int]]:
    """`=` 键值（值可再含 `*` 数量，D04/L49）：'代采=矿石*5'→(代采,矿石,5)。"""
    q: Optional[int] = None
    if "*" in item:
        left, _, right = item.partition("*")
        if right.isdigit():
            q = int(right)
            item = left
    key, _, value = item.partition("=")
    return key, value, q


def _subparse(
    tokens: List[str],
    *,
    command: str,
    quantity_commands: frozenset,
    no_quantity_commands: frozenset,
    max_qty: int,
    free_arg_commands: frozenset,
) -> Dict[str, Any]:
    """S7 SUBPARSE：参数内子解析（顺序写死 , → * → =，S3 裁决背书 L69）+ 后置修饰
    （+ 等级 / - 连招 / > 路径）+ 固定子词抽离（L71）+ 错误判定（L72）+ 数量超限提示（L73）。

    返回 dict：args / kv / targets / qty / seq / level / path / fixed_subword /
    error / hints。
    """
    args: List[str] = []
    kv: List[Dict[str, Any]] = []
    targets: List[str] = []
    qty: Optional[int] = None
    seq: List[int] = []
    level: Optional[int] = None
    path: List[str] = []
    fixed_subword: Optional[str] = None
    error: Optional[str] = None
    hints: List[str] = []
    positional_count = 0

    for idx, tok in enumerate(tokens):
        # 未知分隔符：未登记符号一律错误模板（S1 裁决，L72）
        if not _ALLOWED_TOKEN_RE.match(tok):
            error = ERR_UNKNOWN_SEP
            hints.append(f"参数含未知分隔符：{tok}")
            continue

        # 固定子词（槽位 0/1，优先于物品匹配，L71 / TC-42）
        if fixed_subword is None and idx <= 1 and tok in FIXED_SUBWORDS:
            fixed_subword = tok
            continue

        is_list = _contains_list_sep(tok)
        is_kv = "=" in tok

        # 铁律 3：第 3 参数起强制列表/键值（L46-51 / TC-11）；自由参数指令（筛选链等，
        # M5-09 / 4f RUL-16）豁免——多词筛选条件按位置参数直取（框架 §7.4）
        if idx >= 2 and not is_list and not is_kv and command not in free_arg_commands:
            error = ERR_TOO_MANY
            continue

        if is_kv:
            # 键值列表：先 , 拆列表 → 再 * 拆数量 → 再 = 拆键值（L69 / TC-10）
            for item in _split_list(tok):
                k, v, q = _parse_kv_item(item)
                kv.append({"key": k, "value": v, "qty": q})
            continue

        if is_list:
            # 列表展开（L69a / TC-08/09）
            items = _split_list(tok)
            targets.extend(items)
            if positional_count < 2:
                args.append(tok)
                positional_count += 1
            continue

        # 普通位置参数（≤2；自由参数指令不限，M5-09 筛选链）
        if positional_count >= 2 and command not in free_arg_commands:
            error = ERR_TOO_MANY
            continue
        args.append(tok)
        positional_count += 1

        # 后置修饰（优先级：> 路径 → + 等级 → - 连招）
        if ">" in tok:
            path = [p for p in tok.split(">") if p]
        else:
            lm = re.search(r"\+(\d+)$", tok)
            if lm:
                if level is None:
                    level = int(lm.group(1))
            else:
                s = _parse_seq(tok)
                if s and not seq:
                    seq = s

        # 数量 `*`（铁律 1：* 后必须纯数字，L31-32 / TC-03/06/07）
        if "*" in tok:
            if command in no_quantity_commands:
                # /强化 禁止 *（L34 / TC-05）
                error = ERR_UNKNOWN_SEP
                hints.append(f"「{command}」不使用数量（成功率随机），+N 是等级标记")
            else:
                _, _, right = tok.partition("*")
                if right.isdigit():
                    q = int(right)
                    if qty is None:
                        qty = q
                    if q > max_qty:
                        hints.append(f"最多一次使用 {max_qty} 个")
                else:
                    error = ERR_UNKNOWN_SEP
                    hints.append("数量必须为纯数字，例如：使用 经验药水*10")
        else:
            # 名称保留字符黄色提示（N03：不拦截，只建议不限制，TC-15）
            rh = reserved_char_hint(tok)
            if rh:
                hints.append(rh)

    # 旧空格数量格式兼容回退（L238-239 / TC-02）：物品 + 纯数字 → 按 对象*数量 处理
    if (
        error is None
        and command in quantity_commands
        and len(args) == 2
        and args[1].isdigit()
    ):
        name, n = args
        args = [name]
        qty = int(n)
        hints.append(f"下次可以这样写：{command} {name}*{n}")

    return {
        "args": args,
        "kv": kv,
        "targets": targets,
        "qty": qty,
        "seq": seq,
        "level": level,
        "path": path,
        "fixed_subword": fixed_subword,
        "error": error,
        "hints": hints,
    }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def parse_command(
    raw: str,
    *,
    command_mode: str = MODE_GLOBAL_SHORTCUT,
    require_at: bool = False,
    shortcuts: Optional[Mapping[str, str]] = None,
    aliases: Optional[Mapping[str, Any]] = None,
    whitelist: Optional[Iterable[str]] = None,
    prefix_required: Optional[Iterable[str]] = None,
    gm_commands: Optional[Iterable[str]] = None,
    session_active: bool = False,
    in_battle: bool = False,
    max_qty: int = DEFAULT_MAX_QTY,
    quantity_commands: Optional[Iterable[str]] = None,
    no_quantity_commands: Optional[Iterable[str]] = None,
    free_arg_commands: Optional[Iterable[str]] = None,
    command_specs: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> ParsedCommand:
    """全系统唯一解析入口（3c §三 S0-S8）。

    解析管线写死：会话路由判定 → 快捷表（个人）→ 指令别名（全局）→ 指令白名单 → 忽略
    （规范 L230 / 3c §5.3）。

    参数：
      raw           原始消息原文
      command_mode  三模式之一（默认 global_shortcut 全局免前缀，规范 6.1）
      require_at    是否需 @机器人 触发（默认关，规范 6.2）
      shortcuts     玩家个人快捷表 {快捷名: 完整指令串}（规范 6.6；展开深度 ≤1，S7 裁决）
      aliases       全局指令别名配置（规范 6.7；两种形态，见 _normalize_aliases）
      whitelist     指令白名单（框架+内容包注册指令，动态注册表；默认 DEFAULT_WHITELIST）
      prefix_required  需 / 前缀的指令（GM + /对话 接缝裁决；默认 DEFAULT_PREFIX_REQUIRED）
      gm_commands   GM 指令集合（5b L160 长清单；默认 DEFAULT_GM_COMMANDS）。GM 判定用本
                    集合且要求 '/' 前缀真正落在当前展开串上（P1-2c 对拍 router spec.is_gm：
                    快捷展开的触发 '/' 不豁免 GM，防权限绕过）
      session_active 是否对话会话激活（2b2 生命周期；**战斗按裁决① 传 False**）
      in_battle     是否战斗内（combat_shortcut 模式判定用；战斗裸数字走快捷表，不送会话）
      max_qty       数量上限（默认 99，仅提示不拦截，L33/L73）
      quantity_commands 旧空格数量兼容指令集（默认 DEFAULT_QUANTITY_COMMANDS）
      no_quantity_commands 禁止 `*` 的指令（默认 {强化}，L34）
      free_arg_commands  自由参数指令（位置参数数量不限；默认 DEFAULT_FREE_ARG_COMMANDS，
                          含「背包筛选」——筛选链多词条件豁免 S7 铁律 3，M5-09 / 4f RUL-16）
      command_specs 指令参数声明 {指令名: {"min_args": N}}（缺参判定，可选）

    返回：ParsedCommand（mode=session_digit 表示应送激活会话状态机——本模块只标记
    语义不接状态机；mode=ignored 表示非指令消息，调用方不响应）。
    """
    return _parse_text(
        raw,
        raw=raw,
        mode=MODE_NORMAL,
        expand_count=0,
        allow_shortcut=True,
        command_mode=command_mode,
        require_at=require_at,
        shortcuts=dict(shortcuts or {}),
        aliases=dict(aliases or {}),
        whitelist=frozenset(whitelist if whitelist is not None else DEFAULT_WHITELIST),
        prefix_required=frozenset(
            prefix_required if prefix_required is not None else DEFAULT_PREFIX_REQUIRED
        ),
        gm_commands=frozenset(
            gm_commands if gm_commands is not None else DEFAULT_GM_COMMANDS
        ),
        session_active=session_active,
        in_battle=in_battle,
        max_qty=max_qty,
        quantity_commands=frozenset(
            quantity_commands
            if quantity_commands is not None
            else DEFAULT_QUANTITY_COMMANDS
        ),
        no_quantity_commands=frozenset(
            no_quantity_commands
            if no_quantity_commands is not None
            else DEFAULT_NO_QUANTITY_COMMANDS
        ),
        free_arg_commands=frozenset(
            free_arg_commands if free_arg_commands is not None else DEFAULT_FREE_ARG_COMMANDS
        ),
        command_specs=dict(command_specs or {}),
    )


def _parse_text(
    text: str,
    *,
    raw: str,
    mode: str,
    expand_count: int,
    allow_shortcut: bool,
    command_mode: str,
    require_at: bool,
    shortcuts: Dict[str, str],
    aliases: Dict[str, Any],
    whitelist: frozenset,
    prefix_required: frozenset,
    gm_commands: frozenset,
    session_active: bool,
    in_battle: bool,
    max_qty: int,
    quantity_commands: frozenset,
    no_quantity_commands: frozenset,
    free_arg_commands: frozenset,
    command_specs: Dict[str, Mapping[str, Any]],
    prefix_gate_passed: bool = False,
    prefix_stripped_in: bool = False,
) -> ParsedCommand:
    """解析管线内层（S0-S8）；快捷展开经递归重入（expand_count ≤1 防连环，S7 裁决）。

    prefix_gate_passed：免前缀门槛是否已通过。前缀模式（prefix_only / combat_shortcut
    战斗外）只约束**触发消息**（L177：prefix_only 发 '/1'）；快捷展开串不再重复判定
    （触发消息已带 '/' 即通过）。
    prefix_stripped_in：上级剥离的 '/' / @提及标记（P05：原始消息是否剥离前缀）；
    快捷展开后保留触发消息的标记。
    """

    # ---- S0 预处理：trim / require_at 剥离 @提及 / 按 command_mode 剥离 '/' ----
    text = (text or "").strip()
    if not text:
        return ParsedCommand._ignored(raw, text)

    if require_at:
        stripped = re.sub(r"^@\S*\s*", "", text, count=1)
        if stripped == text:
            # 未带 @ 提及 → 非指令；会话子词仍可送状态机（【工程补白】会话交互不要求 @）
            if session_active and not in_battle and is_session_subword(text):
                return ParsedCommand._session(raw, text)
            return ParsedCommand._ignored(raw, text)
        text = stripped
        if not text:
            return ParsedCommand._ignored(raw, text)

    if text.startswith("/"):
        text = text[1:].strip()
        slash_on_text = True
    else:
        slash_on_text = False
        # 免前缀是否被模式允许（规范 6.1 L88-98；快捷名跟随前缀模式 L177）。
        # 仅约束触发消息：prefix_gate_passed=True（快捷展开重入）时不再判定。
        if not prefix_gate_passed and (
            command_mode == MODE_PREFIX_ONLY
            or (command_mode == MODE_COMBAT_SHORTCUT and not in_battle)
        ):
            if session_active and not in_battle and is_session_subword(text):
                return ParsedCommand._session(raw, text)
            return ParsedCommand._ignored(raw, text)

    # 合并上级剥离标记（P05：原始消息是否剥离 '/' / @提及；快捷展开后保留触发消息标记）。
    # slash_on_text = 当前这层文本是否真实以 '/' 开头（P1-2c：GM 判定用当前层标记，
    # 不沿用触发消息的 '/'——快捷授权不豁免 GM，对齐 router._trigger_allowed）。
    prefix_stripped = slash_on_text or prefix_stripped_in

    # ---- S1/S2 会话路由判定（裁决①：战斗永不置会话激活，裸数字走快捷表） ----
    if session_active and not in_battle and is_session_subword(text):
        # 会话优先于快捷（R3）：即使绑了 "1=攻击"，对话激活中发 "1" 仍选选项
        return ParsedCommand._session(raw, text)

    # ---- S3 快捷表：完整消息精确匹配（规范① L149）；展开深度 ≤1（S7 裁决） ----
    if allow_shortcut and text in shortcuts:
        return _parse_text(
            shortcuts[text],
            raw=raw,
            mode=MODE_SHORTCUT,
            expand_count=expand_count + 1,
            allow_shortcut=False,  # 不回查快捷表，防 A→B→A 无限循环
            command_mode=command_mode,
            require_at=False,  # @提及仅 S0 剥离一次（L104）；展开串不再要求 @
            shortcuts=shortcuts,
            aliases=aliases,
            whitelist=whitelist,
            prefix_required=prefix_required,
            gm_commands=gm_commands,
            session_active=session_active,
            in_battle=in_battle,
            max_qty=max_qty,
            quantity_commands=quantity_commands,
            no_quantity_commands=no_quantity_commands,
            free_arg_commands=free_arg_commands,
            command_specs=command_specs,
            prefix_gate_passed=True,  # 触发消息已通过前缀门槛（含 '/' 或模式允许）
            prefix_stripped_in=prefix_stripped or prefix_stripped_in,
        )

    # ---- S4/S5 指令名解析：候选名（白名单 ∪ 别名名 ∪ 被隐藏原指令名） ----
    alias_to_orig, orig_to_alias = _normalize_aliases(aliases)
    candidates = set(whitelist) | set(alias_to_orig) | set(orig_to_alias)
    command, remainder, compact = _split_command(text, candidates)
    if command is None:
        # 无白名单/别名命中 → 忽略（规范④ L152 / L126-127 防误触）。
        # 快捷展开后目标非指令时保留 mode=shortcut（触发来源=快捷，command=None 不可执行）
        final_mode = MODE_SHORTCUT if mode == MODE_SHORTCUT else MODE_IGNORED
        return ParsedCommand(
            raw,
            tokens=[text],
            mode=final_mode,
            command=None,
            expand_count=expand_count,
        )

    # S4 指令别名层（规范② L150 / 6.7）
    display_name: Optional[str] = command
    if command in alias_to_orig:
        orig, _keep = alias_to_orig[command]
        display_name = command  # 显示层=别名（A05）
        command = orig
        mode = MODE_ALIAS
    elif command in orig_to_alias:
        # keep_original:false 原指令隐藏禁用 → 引导提示（A04 / L212）
        return ParsedCommand._alias_hidden(raw, text, command, orig_to_alias[command])

    # S5 GM/需前缀指令：GM 指令要求 '/' 前缀**真正落在当前展开串上**（P1-2c 修复：
    # GM 判定 = spec.is_gm（gm_commands 集合）且 slash_on_text=True——快捷展开的触发
    # '/' 不豁免 GM，对齐 router._trigger_allowed W07/L128）；非 GM 需前缀指令
    # （/对话 接缝裁决：可快捷绑定、不可免前缀直发）沿用触发消息剥离标记 prefix_stripped。
    if command in gm_commands:
        if not slash_on_text:
            return ParsedCommand._ignored(raw, text)
    elif command in prefix_required and not prefix_stripped:
        return ParsedCommand._ignored(raw, text)

    # ---- S6 TOKENIZE：紧凑/空格双认 → token 流 ----
    tokens = _tokenize(remainder)

    # ---- S7 SUBPARSE + S8 BUILD ----
    sub = _subparse(
        tokens,
        command=command,
        quantity_commands=quantity_commands,
        no_quantity_commands=no_quantity_commands,
        max_qty=max_qty,
        free_arg_commands=free_arg_commands,
    )
    args: List[str] = sub["args"]
    error: Optional[str] = sub["error"]
    hints: List[str] = sub["hints"]

    # 空格写法解析成功 → 紧凑回写提示（L111 / TC-19）
    if not compact and args:
        hints.append(f"下次可以这样写：{command}{args[0]}")

    # 缺参（command_specs 声明 min_args；L72 错误模板 / TC-44）
    if error is None and command in command_specs:
        spec = command_specs[command]
        if len(args) < int(spec.get("min_args", 0)):
            error = ERR_MISSING

    return ParsedCommand(
        raw=raw,
        tokens=[command] + tokens,
        command=command,
        args=args,
        mode=mode,
        session_candidate=False,
        session_route=False,
        expand_count=expand_count,
        prefix_stripped=prefix_stripped,
        compact=compact,
        display_name=display_name,
        fixed_subword=sub["fixed_subword"],
        kv=sub["kv"],
        targets=sub["targets"],
        qty=sub["qty"],
        seq=sub["seq"],
        level=sub["level"],
        path=sub["path"],
        error=error,
        hints=hints,
        alias_hidden=None,
    )
