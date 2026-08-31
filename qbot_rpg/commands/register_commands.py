"""注册指令接线 register_commands.py（M6 批次1·路B · qbot_rpg/commands/register_commands.py）。

依据：
  - docs/细化/细化_M6_三引擎与基础指令.md（M6 子细化 D1）§四 /注册 契约：REG-01~REG-06、
    TC-REG-01~05（承接 4f TC-01/02/03/04/06）；§七 P1-2/P1-3（DELAYED 收口 / 冒烟闭环依赖）
  - docs/细化/细化_4f_基础指令组契约.md（母契约）§一：CMD-01 / RUL-01~09 / TPL-4F-01；
    B5（角色名全服唯一）/ B6（/帮助 豁免注册门槛）/ B7（缺省职业兜底链）
  - docs/细化/细化_3d_消息模板规范.md（TPL-12 指令出错 / D-01 emoji 禁令 / D-04 文案唯一源）
  - docs/审查参考/指令分隔符统一规范.md（二 位置参数 ≤2 / 三 命名铁律 N01~N03）
  - docs/审查参考/RPG回合制框架设计文档.md【框架】L1156（角色名 ≤20 字 / 过滤控制字符与
    超长 emoji 安全补强）、L591（recommended_newbie 推荐角标）、L608-611（stats.json 属性模板）
  - M5 裁决「不用 emoji」（docs/全局图标登记表.md）：4f TPL-4F-01 / TC-02 示例中的 🟢 推荐角标
    按渲染零装饰 emoji 纪律降级为纯文本「（推荐新手）」——M5 用户拍板晚于 4f 定稿，本层取新裁决。

职责（细化_3a §1.3 壳层职责 · 唯一指令执行壳）：把 /注册 从 Router 接到玩家建档——
指令解析（parsers.parse_command 已 token 化 → 本模块取 角色名/职业）、角色名校验
（≤20 字 / 控制字符过滤 / 保留字符黄提示引导换名，REG-02）、已注册幂等拒绝（REG-03）、
职业解析（缺省兜底链 default_job_id → 首个 recommended_newbie → jobs 首职业，B7/REG-04）、
角色名唯一检查（ctx["name_exists"] 回调，REG-03）、构造初始 Player 状态写 ctx["player"] +
ctx["registered"]=True（REG-04/05）、渲染 TPL-4F-01 语义成功消息。
建号落档（角色名注册表检查 → Player 建档 → registered=True → save_player 单事务）由装配层
make_context 完成（REG-06 ③），本 handler 只生成数据（零 IO、零 NoneBot）。

铁律（m4_shared_contract §0 / 3a R1）：**零 NoneBot import**、纯函数、确定性；工程补白一律
【工程补白】标注；错误走 TPL-12 统一模板（格式错误）；装饰性 emoji 全局禁用（仅 ✅/❌）。

--------------------------------------------------------------------------------
ctx 消费契约（装配层 make_context 注入；未注入字段按缺省兜底）：
  registered: bool                    是否已注册（True → 幂等拒绝）
  player: dict|None                   玩家状态 dict（已注册时读当前角色渲染幂等文案）
  jobs: {job_id: {name, recommended_newbie, ...}}
                                      （缺省职业解析 + 职业名匹配 + 可用职业列表）
  job_name: str                       当前角色职业中文名（幂等文案用，可选）
  stats: {attr_id: {name, base, growth, type}}
                                      （初始属性模板，REG-04；base 缺失按 100/30/10 兜底）
  settings: {default_job_id, default_map, world_name, ...}
                                      （缺省职业/初始位置/世界名）
  name_exists: Callable[[str], bool]  角色名唯一检查回调（可选；缺省视为唯一）
--------------------------------------------------------------------------------

【工程补白 · 显式标注】
  1) 成功消息首行 = 前缀行 `Lv1.{名字} - -`（对齐 TPL-4F-01「前缀首行」与 TC-REG-01；与
     basic_commands /角色 的「LV 行固定头部」同模式——handler 直出可纯函数单测；装配层
     message_prefix 是否叠加由批次7 装配裁决，本层不重复注入）。
  2) 缺省职业兜底链 = settings.default_job_id → 首个 recommended_newbie 职业 → jobs 首职业
     （B7/REG-04）；default_job_id 无效（不在 jobs 表）时继续走推荐/首职业（防御）。
  3) 初始属性 = ctx["stats"] 各属性 base（hp/mp/战斗属性），缺省 hp=100/mp=30/其余=10
     （【框架】L608-611 stats 模板；4f RUL-05）。
  4) 初始位置 = settings.default_map（缺省「新手村」，REG-04 初始位置）；实际落位由装配层
     make_context 承接，本 handler 仅写入 ctx["location"] 供 /状态 等消费。
  5) 角色名校验细节：长度 >20 → 硬拦 `❌ 角色名最多 20 个字`；控制字符（ord<0x20/0x7f）
     → 硬拦过滤；超长 emoji 由解析器 token 合法集天然拦截（unknown separator → TPL-12），
     本层无需 emoji 正则；保留字符（空格/`* , = + /`）→ 黄提示不硬拦，成功消息附
     「（提示：名字含保留字符…建议改名）」（REG-02/RUL-02「只建议不限制」）。
  6) 已注册幂等文案 = RUL-09：`❌ 你已经注册过了！当前角色：{name}（Lv{level} {job}）。\n
     想重新开始请发送注销。`（意见一同步：注销指令已拍板存在，去「待确认」标注；B5 不覆盖原档）。
  7) 重名检查走 ctx["name_exists"] 回调（装配层查角色名注册表）；回调缺省 → 视为唯一
     （纯函数可测；注册表接线归装配层）。
"""

from __future__ import annotations

from typing import Any, Callable, List, Mapping, MutableMapping, Optional

from qbot_rpg.core.templates import tpl_of  # 消息模板配置化（2026-08-31 用户拍板）
from qbot_rpg.data.player import PlayerAttributes

# 同包兄弟模块：相对导入（G0 架构门禁 test_commands_web_not_depended 不产生
# `qbot_rpg.commands` 前缀反向依赖边；同层兄弟引用架构合规，与 sender.py 同口径）。
from .parsers import reserved_char_hint
from .router import CommandSpec
from .sender import format_tpl12

__all__ = [
    "REGISTER_CMD",
    # 文案常量
    "TPL_NAME_TOO_LONG",
    "TPL_NAME_BAD_CHARS",
    "TPL_ALREADY_REGISTERED",
    "TPL_DUP_NAME",
    "TPL_JOB_NOT_FOUND",
    # 指令处理器（纯函数：parsed + ctx → 回复正文）
    "cmd_register",
    # 渲染 / 工具
    "resolve_job",
    "default_job",
    "build_initial_player",
    "render_register_success",
    # 装配
    "register_register_commands",
]

# ---------------------------------------------------------------------------
# 常量：指令名 / 业务文案
# ---------------------------------------------------------------------------

REGISTER_CMD = "注册"

# 角色名校验（REG-02 / RUL-02；【框架】L1156 安全补强）
TPL_NAME_TOO_LONG = "❌ 角色名最多 20 个字"
TPL_NAME_BAD_CHARS = "❌ 角色名含非法字符，请重新输入（过滤控制字符/超长 emoji）"

# 已注册幂等拒绝（REG-03 / RUL-09；B5：禁止重复建号覆盖原档）
# 意见一同步：注销指令已拍板存在，文案改为引导「发送注销」（去掉旧「请联系管理员」）
# 2026-08-31 用户拍板：job 为空格时省略职业（内容包无 jobs 表不显示英文 id）
TPL_ALREADY_REGISTERED = (
    "❌ 你已经注册过了！当前角色：{name}（Lv{level}{job}）。\n想重新开始请发送注销。"
)

# 重名红拦换名（REG-03 / RUL-07 / B5）
TPL_DUP_NAME = "❌ 已经有一个叫『{name}』的角色了，换个名字吧"

# 职业不存在（RUL-03：精确匹配 jobs 显示名；推荐角标源 L591）
TPL_JOB_NOT_FOUND = "❌ 没有『{job}』这个职业，可用：{list}"

# 保留字符黄提示尾缀（RUL-02 ③「只建议不限制」；成功消息附引导换名）
_RESERVED_HINT = "（提示：{hint}）"

# 初始属性兜底（stats.json base 缺失时；【框架】L608-611：hp 100 / mp 30 / 战斗 10~15）
_BASE_FALLBACK: Mapping[str, float] = {"hp": 100.0, "mp": 30.0}

# 角色名最大长度（【框架】L1156 安全补强）
MAX_NAME_LEN = 20

# 初始位置兜底（REG-04 初始位置；缺省取「新手村」新手村默认精神）
_DEFAULT_LOCATION = "新手村"


# ---------------------------------------------------------------------------
# 工具（纯函数）
# ---------------------------------------------------------------------------

def _fragment(parsed: Any) -> str:
    """TPL-12 原文片段（parsed.raw 优先；缺省重构）。"""
    if getattr(parsed, "raw", None):
        return str(parsed.raw)
    cmd = getattr(parsed, "command", None) or ""
    args = getattr(parsed, "args", None) or []
    tail = (" " + " ".join(str(a) for a in args)) if args else ""
    return f"/{cmd}{tail}"


def _name_error(name: str) -> Optional[str]:
    """角色名硬性校验错误（REG-02 ①②）：长度超限 / 含控制字符 → 错误文案；合法 → None。

    保留字符（REG-02 ③）为黄提示不硬拦，不走本函数（见 cmd_register 尾缀逻辑）。
    """
    if len(name) > MAX_NAME_LEN:
        return TPL_NAME_TOO_LONG
    for ch in name:
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            return TPL_NAME_BAD_CHARS
    return None


def _job_entry(ctx: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    """jobs 表（ctx["jobs"] {job_id: {name, recommended_newbie, ...}}）；非映射 → None。"""
    jobs = ctx.get("jobs")
    if isinstance(jobs, Mapping):
        return jobs
    return None


def _job_of_id(ctx: Mapping[str, Any], job_id: str) -> Optional[dict]:
    """job_id → 职业定义 dict（含 id 冗余）；查无 → None。"""
    jobs = _job_entry(ctx)
    if jobs is None:
        return None
    d = jobs.get(job_id)
    if d is None:
        return None
    if isinstance(d, Mapping):
        return {"id": job_id, **d}
    return {"id": job_id, "name": str(d), "recommended_newbie": False}


def _job_name_of(d: Optional[Mapping[str, Any]]) -> str:
    """职业定义 → 中文名（name 缺失 → id 原样）。"""
    if not d:
        return "?"
    name = d.get("name")
    return str(name) if name else str(d.get("id") or "?")


def resolve_job(ctx: Mapping[str, Any], arg: object) -> Optional[dict]:
    """职业参数 → 职业定义 dict（RUL-03：jobs 显示名精确匹配；job_id 直配兜底）。

    匹配顺序：① 显示名精确匹配；② job_id 直配（防御兜底，工程补白）；查无 → None。
    """
    jobs = _job_entry(ctx)
    if jobs is None or arg is None:
        return None
    s = str(arg).strip()
    if not s:
        return None
    for jid, d in jobs.items():
        if not isinstance(d, Mapping):
            continue
        if str(d.get("name")) == s:
            return {"id": str(jid), **d}
    if s in jobs:
        return _job_of_id(ctx, s)
    return None


def default_job(ctx: Mapping[str, Any]) -> Optional[dict]:
    """缺省职业（B7 / REG-04 兜底链）：settings.default_job_id → 首个 recommended_newbie
    职业 → jobs 首职业；jobs 表缺失 → None（由调用方兜底「?"」）。"""
    jobs = _job_entry(ctx)
    if jobs is None or not jobs:
        return None
    settings = ctx.get("settings")
    if isinstance(settings, Mapping):
        dj = settings.get("default_job_id")
        if dj:
            d = _job_of_id(ctx, str(dj))
            if d is not None:
                return d
    for jid, d in jobs.items():
        if isinstance(d, Mapping) and d.get("recommended_newbie"):
            return {"id": str(jid), **d}
    first = next(iter(jobs))
    return _job_of_id(ctx, first)


def _available_jobs(ctx: Mapping[str, Any]) -> List[str]:
    """可用职业列表文案（RUL-03 黄提示）：`战士（推荐） 法师（推荐） 游侠`。"""
    jobs = _job_entry(ctx)
    if jobs is None:
        return []
    out: List[str] = []
    for jid, d in jobs.items():
        if not isinstance(d, Mapping):
            continue
        name = str(d.get("name") or jid)
        if d.get("recommended_newbie"):
            name += "（推荐）"
        out.append(name)
    return out


def _initial_base(ctx: Mapping[str, Any]) -> dict:
    """初始属性 base 层（REG-04 / RUL-05）：ctx["stats"] 各属性 base；缺失按 100/30/10 兜底。"""
    stats = ctx.get("stats")
    base: dict = {}
    if isinstance(stats, Mapping):
        for attr_id, d in stats.items():
            key = str(attr_id)
            if not isinstance(d, Mapping):
                base[key] = _BASE_FALLBACK.get(key, 10.0)
                continue
            raw = d.get("base")
            if raw is None:
                base[key] = _BASE_FALLBACK.get(key, 10.0)
                continue
            try:
                base[key] = float(raw)
            except (TypeError, ValueError):
                base[key] = _BASE_FALLBACK.get(key, 10.0)
    else:
        base = {"hp": 100.0, "mp": 30.0, "str": 10.0, "int": 10.0, "con": 10.0,
                "spr": 10.0, "foc": 10.0, "agi": 10.0, "lck": 10.0}
    return base


def _initial_location(ctx: Mapping[str, Any]) -> str:
    """初始位置（REG-04 / RUL-06）：settings.default_map → 兜底「新手村」。"""
    settings = ctx.get("settings")
    if isinstance(settings, Mapping):
        dm = settings.get("default_map")
        if dm:
            return str(dm)
    dm2 = ctx.get("default_map")
    if dm2:
        return str(dm2)
    return _DEFAULT_LOCATION


def build_initial_player(ctx: Mapping[str, Any], name: str, job_id: str) -> dict:
    """构造初始 Player 状态（REG-04/RUL-05/06：可变 dict，装配层落档用）。

    字段对齐 data/player.Player 语义（qid 由装配层补、inventory/equipment 初始为空、
    attributes 按 stats 模板 base、hp/mp 取 base 整数值）。
    """
    base = _initial_base(ctx)
    hp = int(base.get("hp", 100))
    mp = int(base.get("mp", 30))
    return {
        "name": name,
        "job_id": job_id,
        "level": 1,
        "exp": 0,
        "hp": hp,
        "mp": mp,
        "currencies": {},
        "inventory": [],
        "equipment": {},
        "attributes": PlayerAttributes(base=base),
        "schema_version": 4,
    }


def _world_name(ctx: Mapping[str, Any]) -> str:
    """世界名（TPL-4F-01「欢迎来到「世界名」世界」）：settings.world_name → 兜底「世界名」。"""
    settings = ctx.get("settings")
    if isinstance(settings, Mapping):
        wn = settings.get("world_name")
        if wn:
            return str(wn)
    return "世界名"


def render_register_success(
    ctx: Mapping[str, Any],
    name: str,
    job: Optional[Mapping[str, Any]],
    player: Mapping[str, Any],
    location: str,
    hint: Optional[str] = None,
) -> str:
    """注册成功消息（TPL-4F-01 语义；工程补白 1：首行 = 前缀行）。

    行序：前缀首行 `Lv1.{名字} - -` → ✅ 注册成功！欢迎来到「世界名」世界 → 职业行（含
    recommended_newbie 时附「（推荐新手）」）｜ 位置行 → 初始属性行（生命/魔力/攻击/防御，
    全中文，4f RUL-05）→ 引导行；保留字符黄提示（hint）附尾（RUL-02 ③，工程补白 5）。
    """
    attrs = player.get("attributes") if isinstance(player, Mapping) else getattr(player, "attributes", None)
    base = getattr(attrs, "base", None) if attrs is not None else None
    base = base if isinstance(base, Mapping) else {}
    hp = int(base.get("hp", 100))
    mp = int(base.get("mp", 30))
    atk = int(base.get("str", 10))
    dfn = int(base.get("con", 10))
    lines: List[str] = [
        f"Lv1.{name} - -",
        f"✅ 注册成功！欢迎来到「{_world_name(ctx)}」世界",
    ]
    job_name = _job_name_of(job)
    if job and job.get("recommended_newbie"):
        job_name += "（推荐新手）"
    lines.append(f"职业：{job_name} ｜ 位置：{location}")
    # 意见一同步：初始属性每项独立一行（生命/魔力/攻击/防御各一行）；引导行尾加句号
    lines.append("初始属性：")
    lines.append(f"生命 {hp}/{hp}")
    lines.append(f"魔力 {mp}/{mp}")
    lines.append(f"攻击 {atk}")
    lines.append(f"防御 {dfn}")
    lines.append(f"下一步：发 /帮助 查看指令，或 /锁定 {location}怪物开战。")
    if hint:
        lines.append(_RESERVED_HINT.format(hint=hint))
    return "\n".join(lines)


def _current_player_name(ctx: Mapping[str, Any]) -> str:
    """已注册玩家角色名（ctx["player"] dict/dataclass → ctx["name"] 兜底）。"""
    p = ctx.get("player")
    if isinstance(p, Mapping):
        n = p.get("name")
        if n:
            return str(n)
    if p is not None:
        n = getattr(p, "name", None)
        if n:
            return str(n)
    return str(ctx.get("name") or "?")


def _current_player_level(ctx: Mapping[str, Any]) -> int:
    """已注册玩家等级。"""
    p = ctx.get("player")
    if isinstance(p, Mapping):
        try:
            return int(p.get("level", 1))
        except (TypeError, ValueError):
            return 1
    if p is not None:
        try:
            return int(getattr(p, "level", 1))
        except (TypeError, ValueError):
            return 1
    try:
        return int(ctx.get("level", 1))
    except (TypeError, ValueError):
        return 1


def _current_job_name(ctx: Mapping[str, Any]) -> str:
    """已注册玩家职业中文名（ctx["job_name"] 优先 → player.job_id 查 jobs 表）。"""
    jn = ctx.get("job_name")
    if jn:
        return str(jn)
    p = ctx.get("player")
    job_id = ""
    if isinstance(p, Mapping):
        job_id = str(p.get("job_id") or "")
    elif p is not None:
        job_id = str(getattr(p, "job_id", "") or "")
    if not job_id:
        job_id = str(ctx.get("job_id") or "")
    if job_id:
        d = _job_of_id(ctx, job_id)
        if d is not None:
            return _job_name_of(d)
        # 2026-08-31 用户拍板：内容包无 jobs 表时职业名留空（不显示英文 id「novice」）
        return ""
    return "?"


# ---------------------------------------------------------------------------
# 指令处理器（纯函数：ParsedCommand + ctx → 回复正文）
# ---------------------------------------------------------------------------

def cmd_register(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/注册 <角色名> [职业]（REG-01~06 / RUL-01~09 / TPL-4F-01）：

      语法（REG-01）      位置参数 ≤2：`注册 <角色名> [职业]`；缺名/超参/解析错误 → TPL-12
      名字校验（REG-02）  ≤20 字 / 控制字符过滤（硬拦）；保留字符 → 黄提示引导换名（不硬拦）
      已注册（REG-03）    幂等拒绝，不覆盖原档（RUL-09）
      职业（REG-04/B7）   缺省 = default_job_id → 首个 recommended_newbie → jobs 首职业
      重名（REG-03）      ctx["name_exists"] 回调（可选）→ 撞名红拦换名
      建号（REG-04/05）   构造初始 Player 写 ctx["player"] + ctx["registered"]=True；
                         落档由装配层 make_context 完成（REG-06 ③，本层零 IO）
    """
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    # P1-1 修复（M6 批1B 审查）：fixed_subword（自动/继续/退出/选择N 等会话子词）非空
    # 即 TPL-12——解析器已把首参抽为 fixed_subword，若放行则 args[0] 变职业、角色名静默
    # 错位（/注册 自动 战士 → 注册名「战士」）。角色名含会话子词无法经解析器，明确拒绝。
    if getattr(parsed, "fixed_subword", None):
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    usage = "/注册 <角色名> [职业]"
    if len(args) > 2:
        # 超参 → 正确格式引导（3d §5.1「原因 + 正确用法 + 下一步」句式；TPL-12 同款错误头）
        return (f"❌ 指令不正确：/注册 最多 2 个参数。"
                f"正确格式：{usage}")
    if len(args) == 0:
        # 无参 → QQ 号兜底（用户拍板 2026-08-28：不带角色名直接用 QQ 号作玩家名，零输入开玩）
        auto_name = str(ctx.get("qq_id") or "").strip()
        if not auto_name:
            return (f"❌ 指令不正确：/注册 需要角色名。"
                    f"正确格式：{usage}（或直接发 /注册，将用你的 QQ 号作为名字）")
        name = auto_name
        used_auto_name = True
    else:
        name = str(args[0])
        used_auto_name = False

    # REG-03 已注册幂等拒绝（RUL-09；不覆盖原档）——先于名字校验（幂等提示优先于名字校验）
    if ctx.get("registered", True) is True:
        job_display = _current_job_name(ctx)
        return tpl_of(ctx, "already_registered", {
            "name": _current_player_name(ctx),
            "level": _current_player_level(ctx),
            "job": f" {job_display}" if job_display else "",  # 2026-08-31 无职业名（novice）不显示
        })

    # REG-02 名字硬性校验（长度/控制字符）
    err = _name_error(name)
    if err is not None:
        return err

    # REG-04 职业解析（显式参数 → 缺省兜底链 B7）
    if len(args) == 2:
        job = resolve_job(ctx, args[1])
        if job is None:
            avail = " ".join(_available_jobs(ctx)) or "?"
            return TPL_JOB_NOT_FOUND.format(job=str(args[1]), list=avail)
    else:
        job = default_job(ctx)
        if job is None:
            job = {"id": "novice", "name": "新手", "recommended_newbie": False}
    job_id = str(job.get("id") or "")

    # REG-03 重名检查（ctx["name_exists"] 回调可选）
    exists = ctx.get("name_exists")
    if callable(exists):
        try:
            if exists(name):
                return TPL_DUP_NAME.format(name=name)
        except Exception:
            pass  # 回调异常不阻断注册（唯一性判定缺省放行，工程补白 7）

    # REG-02 ③ 保留字符黄提示（不硬拦，成功消息附引导换名）
    hint = reserved_char_hint(name) if name else None
    # 无参注册 → 已用 QQ 号兜底（用户拍板 2026-08-28），成功消息附提示
    if used_auto_name:
        auto_hint = f"已自动用你的 QQ 号「{name}」作为名字"
        hint = f"{hint} {auto_hint}".strip() if hint else auto_hint

    # REG-04/05 建号：构造初始 Player 写 ctx + 置注册态（落档归装配层）
    player = build_initial_player(ctx, name, job_id)
    location = _initial_location(ctx)
    ctx["player"] = player
    ctx["registered"] = True
    ctx["location"] = location

    return render_register_success(ctx, name, job, player, location, hint=hint)


# ---------------------------------------------------------------------------
# 装配（Router 注册；make_context 由装配层注入，批次7 待接线）
# ---------------------------------------------------------------------------

def register_register_commands(
    router: Any, *, make_context: Optional[Callable[[Any], dict]] = None
) -> Any:
    """把 /注册 注册进 Router（CommandSpec.handler 消费 ParsedCommand；REG-06 ①）。

    :param make_context: ParsedCommand → 玩家 ctx dict（registered/player/jobs/stats/
        settings/name_exists 等，见本模块各函数消费契约；装配层同时实现建号事务 REG-06 ③）。
        None 时 handler 调用抛 RuntimeError（【待接线】批次7 装配注入）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】register_commands.register_register_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _register(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_register(parsed, injected)
        return cmd_register(parsed, _ctx(parsed))

    router.register(CommandSpec(REGISTER_CMD, handler=_register))
    return router
