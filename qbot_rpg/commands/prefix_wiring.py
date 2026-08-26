"""message_prefix 前缀消费接线 prefix_wiring.py（M5 批0 公共接线 · D1 渲染器最后一块拼图）。

依据：
  - docs/m5_shared_contract.md §一（IF02 settings 读取 / IF01b truncated 消费 / 铁律 1/8）
  - docs/m5_batch_plan.md M5-01（批0 公共接线：enabled/show_on_system/per_channel + 前缀挂首行 +
    截断黄提示发射，验收①~⑥）
  - docs/细化/细化_3d_消息模板规范.md（§1.5 显示规则 / §3.1 首行 / §3.3 超长截断 /
    TC-13 / TC-23 / TC-24 / TC-25 / TC-26）
  - docs/审查参考/消息前缀功能设计定稿.md（【前缀】§三 字段默认值 / §五 显示规则 / §七 长度）
  - docs/细化/细化_3h_settings通用设置.md §6.1（message_prefix 段归属 settings.json，7 字段登记）

职责（装配层统一入口，非各指令自行拼装——M5-01 核心）：
  ① settings 读取 helper：read_message_prefix_settings 消费 message_prefix 段 7 字段
     （enabled/format/show_on_system/per_channel/hide_when_empty/empty_title_text/prefix_max_len，
     缺省合并框架默认值，IF02）；
  ② 前缀挂玩家回复首行：apply_message_prefix 在发送前统一注入，多行回复仅首行带前缀（铁律 1）；
  ③ 系统消息豁免：show_on_system=false 不加、true 加（TC-24）；
  ④ 渠道限定：per_channel all/group/private（TC-25）；
  ⑤ enabled 总开关：false 完全无前缀（【前缀】L42）；
  ⑥ 截断黄提示：消费 render_prefix_result(...).truncated → PREFIX_TRUNCATED_HINT
     「前缀过长已截断」（归属发起指令所在群，不阻断正文，TC-13 / 【前缀】L100）；
  ⑦ 前缀不影响指令解析：纯渲染层产物，不进解析器/条件键/存档（铁律 1，TC-26）。

纯函数约定：零 NoneBot import（3a R1）；纯逻辑无 IO，pytest 可脱离平台单测。
本模块不触碰 Sender（sender 是传输层：CQ 转义/长度分条/重试；前缀是显示层产物），
由装配层（on_command）在调用 sender.send 前调用 apply_message_prefix 统一注入。

--------------------------------------------------------------------------------
消费接口（core/message_format/prefix_render.py · M4 已实装，真实签名）：
  render_prefix_result(level, name, title, *, format_template, hide_when_empty,
                       empty_title_text, prefix_max_len, extra) -> PrefixResult
    [群名]/[职业] 经 extra={"群名": ..., "职业": ...} 传入（shared_contract IF01/IF01b）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from qbot_rpg.core.message_format.prefix_render import (
    DEFAULT_PREFIX_FORMAT,
    DEFAULT_PREFIX_MAX_LEN,
    render_prefix_result,
)

__all__ = [
    # 渠道枚举（per_channel 配置 与 消息来源 channel 共用取值）
    "CHANNEL_GROUP",
    "CHANNEL_PRIVATE",
    "PER_CHANNEL_ALL",
    "PER_CHANNEL_GROUP",
    "PER_CHANNEL_PRIVATE",
    # 默认配置 / 黄提示文案
    "DEFAULT_MESSAGE_PREFIX_SETTINGS",
    "PREFIX_TRUNCATED_HINT",
    # 结果类型 / 装配入口 / settings 读取
    "PrefixWiringResult",
    "apply_message_prefix",
    "read_message_prefix_settings",
]

# ---------------------------------------------------------------------------
# 常量：渠道枚举 / 黄提示文案 / 7 字段默认值
# ---------------------------------------------------------------------------

# per_channel 枚举（【前缀】L45：all 群聊+私聊 / group 仅群聊 / private 仅私聊）
PER_CHANNEL_ALL = "all"
PER_CHANNEL_GROUP = "group"
PER_CHANNEL_PRIVATE = "private"

# 消息来源渠道（装配层注入；与 per_channel 取值对齐）
CHANNEL_GROUP = "group"
CHANNEL_PRIVATE = "private"

# 截断黄提示文案（3d §3.3 / TC-13 / 【前缀】L100：归属发起指令所在群，不阻断正文）
PREFIX_TRUNCATED_HINT = "前缀过长已截断"

# message_prefix settings 段 7 字段默认值（shared_contract §1.1 / 【前缀】§三）
DEFAULT_MESSAGE_PREFIX_SETTINGS: dict = {
    "enabled": True,                                   # 总开关，内容包可关
    "format": DEFAULT_PREFIX_FORMAT,                   # "Lv[等级].[玩家名] -[称号]-"
    "show_on_system": False,                           # 系统公告/群广播默认不加前缀
    "per_channel": PER_CHANNEL_ALL,                    # all/group/private
    "hide_when_empty": False,                          # 无称号整段省略
    "empty_title_text": "-",                           # 无称号时 [称号] 输出
    "prefix_max_len": DEFAULT_PREFIX_MAX_LEN,          # 40，0=不限
}


@dataclass(frozen=True)
class PrefixWiringResult:
    """前缀装配结果（发送前统一入口输出，供装配层消费）。

    text:      最终待发送文本（前缀 + 正文；enabled=false / 渠道不符 / 系统豁免 → 原样正文）
    truncated: 本次前缀渲染是否触发 prefix_max_len 截断（TC-13 黄提示依据）
    hint:      截断时 = PREFIX_TRUNCATED_HINT「前缀过长已截断」（归属发起指令所在群）；否则 ""
    """

    text: str
    truncated: bool = False
    hint: str = ""

    @property
    def has_hint(self) -> bool:
        """是否有截断黄提示需要发送（不阻断正文，正文已含于 text）。"""
        return bool(self.hint)


def read_message_prefix_settings(
    settings: Optional[Mapping[str, object]] = None,
) -> dict:
    """读取 message_prefix settings 段 7 字段（IF02），缺省合并框架默认值。

    settings 接受两种形态（防御式，适配内容包装配两种传法）：
      - 完整 settings.json 映射（含 "message_prefix" 键）→ 解包该段；
      - message_prefix 段映射本体（含 format/per_channel 等字段键）→ 直接消费。
    None / 空 → 全默认。未知字段忽略（字段级校验属 M5-02 校验器职责，本层只读消费）。
    per_channel 非法枚举 → 按 "all" 兜底（对齐校验器「非法按 all 补全」口径，只建议不限制）。
    """
    seg: Mapping[str, object] = {}
    if settings is not None:
        if not isinstance(settings, Mapping):
            raise TypeError(f"settings 必须是映射，收到 {type(settings).__name__}")
        nested = settings.get("message_prefix")
        seg = nested if isinstance(nested, Mapping) else settings

    cfg = dict(DEFAULT_MESSAGE_PREFIX_SETTINGS)
    # enabled 总开关（默认 true；false = 完全无前缀，【前缀】L42）
    if "enabled" in seg and seg["enabled"] is not None:
        cfg["enabled"] = bool(seg["enabled"])
    # format 格式模板（默认 TPL-01；占位符自由组合；空串按默认补全——对齐校验器
    # 「format 空按默认补全」黄提示口径，避免提示与实际渲染不一致，P2-4）
    if "format" in seg and seg["format"] is not None:
        fmt = str(seg["format"])
        cfg["format"] = fmt if fmt else str(DEFAULT_MESSAGE_PREFIX_SETTINGS["format"])
    # show_on_system 系统消息豁免（默认 false）
    if "show_on_system" in seg and seg["show_on_system"] is not None:
        cfg["show_on_system"] = bool(seg["show_on_system"])
    # per_channel 渠道限定（默认 all；非法按 all 兜底）
    if "per_channel" in seg and seg["per_channel"] is not None:
        pc = str(seg["per_channel"])
        if pc in (PER_CHANNEL_ALL, PER_CHANNEL_GROUP, PER_CHANNEL_PRIVATE):
            cfg["per_channel"] = pc
    # hide_when_empty 空称号整段省略（默认 false）
    if "hide_when_empty" in seg and seg["hide_when_empty"] is not None:
        cfg["hide_when_empty"] = bool(seg["hide_when_empty"])
    # empty_title_text 空称号文本（默认 "-"）
    if "empty_title_text" in seg and seg["empty_title_text"] is not None:
        cfg["empty_title_text"] = str(seg["empty_title_text"])
    # prefix_max_len 前缀最大长度（默认 40，0=不限）
    if "prefix_max_len" in seg and seg["prefix_max_len"] is not None:
        raw_len = seg["prefix_max_len"]
        if isinstance(raw_len, (int, float, str)):
            cfg["prefix_max_len"] = int(raw_len)
    return cfg


def apply_message_prefix(
    text: str,
    *,
    level: int,
    name: str,
    title: Optional[str] = None,
    channel: str = CHANNEL_GROUP,
    is_system: bool = False,
    settings: Optional[Mapping[str, object]] = None,
    extra: Optional[Mapping[str, object]] = None,
) -> PrefixWiringResult:
    """玩家指令回复发送前统一注入前缀（装配层唯一入口，铁律 1：前缀只加首行）。

    门控顺序（全部命中才注入；任一不满足 → 原样正文）：
      ① enabled=false → 完全无前缀（【前缀】L42）；
      ② 渠道限定 per_channel（group 仅群聊 / private 仅私聊 / all 群聊+私聊；TC-25）；
      ③ 系统消息豁免 show_on_system（false 不加前缀，true 加；TC-24）；
    渲染：render_prefix_result(level, name, title, format_template=cfg["format"],
      hide_when_empty=..., empty_title_text=..., prefix_max_len=..., extra=extra)
      —— [群名]/[职业] 经 extra 传入（shared_contract IF01b）；消费 .truncated（TC-13）。
    注入：prefix + "\\n" + 正文，多行回复仅首行带前缀（TC-23）；前缀为空串时不注入。
    截断黄提示：hint = PREFIX_TRUNCATED_HINT（归属发起指令所在群，不阻断正文，TC-13）。

    :param level:      玩家当前等级（[等级]）
    :param name:       玩家名（角色名，无则 QQ 昵称兜底）
    :param title:      当前佩戴称号（无 → empty_title_text 三态渲染）
    :param channel:    消息来源渠道（group/private）
    :param is_system:  True = 系统公告/群广播（默认 false：玩家指令回复）
    :param settings:   message_prefix 段 / 完整 settings 映射（None → 全默认）
    :param extra:      额外占位符映射，如 {"群名": ..., "职业": ...}
    """
    body = str(text or "")
    cfg = read_message_prefix_settings(settings)

    # ① enabled 总开关：false = 完全无前缀
    if not cfg["enabled"]:
        return PrefixWiringResult(text=body)

    # ② 渠道限定 per_channel（TC-25）
    if cfg["per_channel"] == PER_CHANNEL_GROUP and channel != CHANNEL_GROUP:
        return PrefixWiringResult(text=body)
    if cfg["per_channel"] == PER_CHANNEL_PRIVATE and channel != CHANNEL_PRIVATE:
        return PrefixWiringResult(text=body)

    # ③ 系统消息豁免 show_on_system（TC-24：默认 false 不加，true 加）
    if is_system and not cfg["show_on_system"]:
        return PrefixWiringResult(text=body)

    # 私聊 [群名]="私聊" 兜底（定稿 §五.5 / shared_contract §1.2）：私聊渠道且调用方
    # 未提供「群名」extra 且 format 含 [群名] → 注入「私聊」，避免原样输出占位符，P2-2
    extra_eff: Mapping[str, object] = dict(extra) if extra else {}
    if (
        channel == CHANNEL_PRIVATE
        and "群名" not in extra_eff
        and "[群名]" in str(cfg["format"])
    ):
        extra_eff["群名"] = "私聊"

    res = render_prefix_result(
        level, name, title,
        format_template=cfg["format"],
        hide_when_empty=cfg["hide_when_empty"],
        empty_title_text=cfg["empty_title_text"],
        prefix_max_len=cfg["prefix_max_len"],
        extra=extra_eff,
    )
    if not res.prefix:
        return PrefixWiringResult(text=body)
    if not body:
        # 无正文 → 无可发消息（前缀是正文装饰，不单发裸前缀行，不增加消息条数）
        return PrefixWiringResult(text="")
    return PrefixWiringResult(
        text=f"{res.prefix}\n{body}",
        truncated=res.truncated,
        hint=PREFIX_TRUNCATED_HINT if res.truncated else "",
    )
