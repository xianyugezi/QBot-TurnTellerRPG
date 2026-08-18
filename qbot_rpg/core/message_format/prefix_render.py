"""message_prefix 前缀模板渲染（细化_3d_消息模板规范 §一 / 细化_3a §5.2 S6）。

- 默认模板 TPL-01：``Lv[等级].[玩家名] -[称号]-``（【前缀】L22/L43/L57）。
- 空称号三态（细化_3d §1.4，TP-02/TP-03/TP-04）：
  - 默认（empty_title_text="-"）        → ``Lv35.阿伟 - -``（TPL-02）
  - hide_when_empty=True                 → ``Lv35.阿伟``（整段省略 [称号] 及相邻装饰，尾随空格清理，TPL-03）
  - empty_title_text=""（不带隐藏）      → ``Lv35.阿伟 - -``（仅隐占位符本体，装饰符保留，TPL-04）
- enabled 总开关/渠道限定/系统豁免等由**调用方**（壳层/内容包 settings 消费处）控制；
  本函数只做纯格式渲染（3a §5.2 S6：「enabled=false = 完全无前缀」→ 调用方不给前缀时直接不调用）。
- 平台无关（3a §5 D-04）：返回纯 str，不含 [CQ:、不含 at/图片占位符（S2/S3）。
- 未知占位符原样透传（3d TC-06：校验器黄提示，渲染层不拦截）。

依据：细化_3d_消息模板规范 §1.2 TPL-01~06 / §1.4 空称号三态 / §3.3 前缀超长截断；
     【消息前缀功能设计定稿】L22/L35/L43/L46-47/L57/L74/L90-92/L100/L130-133。
"""
from __future__ import annotations

import re
from typing import Dict, Mapping, Optional

__all__ = [
    "DEFAULT_PREFIX_FORMAT",
    "render_prefix",
]

# 默认格式模板（TPL-01，【前缀】L22）：占位符自由组合，作者可配 format 字段。
DEFAULT_PREFIX_FORMAT: str = "Lv[等级].[玩家名] -[称号]-"

# 前缀截断默认上限（前缀设计 L48：prefix_max_len 默认 40，0 = 不限）
DEFAULT_PREFIX_MAX_LEN: int = 40

# 紧邻 [称号] 的纯符号装饰 token（整段省略/空称号时按文档口径处理；3d §1.4 相邻装饰符定义）
_TITLE_DECOR = r"[-=/~]+"


def _worn(title: object) -> str:
    """把称号值归一化为非空字符串；空/None → 走空分支。"""
    if title is None:
        return ""
    s = str(title).strip()
    return s


def render_prefix(
    level: int,
    name: str,
    title: Optional[str] = None,
    *,
    format_template: Optional[str] = None,
    hide_when_empty: bool = False,
    empty_title_text: str = "-",
    prefix_max_len: int = DEFAULT_PREFIX_MAX_LEN,
    extra: Optional[Mapping[str, object]] = None,
) -> str:
    """按 message_prefix 模板渲染前缀（细化_3d §1.2/§1.3/§1.4）。

    :param level: 玩家当前等级（[等级]，角色存档 level）
    :param name:  玩家名（[玩家名]）
    :param title: 当前佩戴称号（[称号]）；None/空 = 无称号 → 走三态
    :param format_template: 作者可配格式（TPL-01~06 范例）；缺省 DEFAULT_PREFIX_FORMAT
    :param hide_when_empty: hide_when_empty（【前缀】L46）：空称号整段省略 [称号] 及相邻装饰
    :param empty_title_text: 空称号文本（【前缀】L61，默认 "-"；"" = 仅隐占位符本体）
    :param prefix_max_len: 前缀截断上限（3d §3.3），0 = 不限
    :param extra: 额外占位符映射（[群名]/[职业] 等，供 TPL-05/TPL-06 扩展，templates 驱动）
    :return: 纯 str 前缀（无 CQ 码、无平台占位符；3a §5.2 S1/S2/S3）
    """
    fmt: str = DEFAULT_PREFIX_FORMAT if format_template is None else format_template
    title_str = _worn(title)

    # 1) [称号] 三态（细化_3d §1.4）
    if title_str:
        fmt = fmt.replace("[称号]", title_str)
    elif hide_when_empty:
        # TPL-03：整段省略 [称号] 及其紧邻纯符号装饰，尾随空格清理（3d L91）
        fmt = re.sub(
            r"\s*" + _TITLE_DECOR + r"\[称号\]" + r"\s*" + _TITLE_DECOR + r"\s*",
            "", fmt,
        ).rstrip(" ")
    else:
        if empty_title_text in ("-", ""):
            # TPL-02/TPL-04：文档口径 —— 默认装饰「 -[称号]-」空称号时渲染为「 - -」
            # （empty_title_text="-": 显示空称号文本；"" : 仅隐本体，装饰符保留 → 文档示例均为此形）
            fmt = re.sub(
                r"\s*(" + _TITLE_DECOR + r")\s*\[称号\]\s*(" + _TITLE_DECOR + r")\s*",
                r" \1 \2 ",
                fmt,
            ).rstrip(" ")
        else:
            # 自定义空称号文本：占位符本体替换，装饰符保留（合理泛化）
            fmt = fmt.replace("[称号]", empty_title_text)

    # 2) 等级 / 玩家名 / 额外占位符（未知占位符原样透传，3d TC-06）
    fmt = fmt.replace("[等级]", str(level)).replace("[玩家名]", name)
    if extra:
        for key, value in extra.items():
            fmt = fmt.replace("[" + key + "]", str(value))

    # 3) 前缀超长截断（3d §3.3；截断 + 提示归属壳层 sender，正文不受影响）
    if prefix_max_len and prefix_max_len > 0 and len(fmt) > prefix_max_len:
        fmt = fmt[:prefix_max_len]
    return fmt
