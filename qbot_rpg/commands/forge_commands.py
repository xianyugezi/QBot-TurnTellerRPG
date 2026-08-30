"""M9 锻造·批4·路4A+路4B+路4C：/锻造 原子流程 + 直锻/预览双流 + /确认 一次性窗口
      + 参数解析完整词法（P-01~06 + 批量 *N 消费）。
      （批4 路4D 扩展：装备实例快照入档 forge_instances + 图鉴 item 分册点亮）

文件名：qbot_rpg/commands/forge_commands.py
创建时间：2026-08-30
作者：Hermes 子agent-4B（M9 锻造实现组批4·路4B：直锻/预览双流 + /确认 一次性窗口）
      —— 批4 路4D 扩展作者：Hermes 子agent-4D（实例快照入档 + 图鉴 item 分册点亮，追加不改写）
      —— 批4 路4C 扩展作者：Hermes 子agent-4C（参数解析完整词法 P-01~06 + 批量 *N 消费，追加不改写）
      —— 批5 路5B 扩展作者：Hermes 子agent-5B（/图纸 标注段：✓/✅/失效标注 + 持有进度段接线，
         追加不改写批4 内容；与路5A 主链段共存，主链/分支渲染归路5A）
      —— 批5 路5C 扩展作者：Hermes 子agent-5C（/锻造树 分页视图 + 四指令路由收口：
         /锻造 /确认 /图纸 /锻造树 全部注册 + 白名单登记，追加不改写批4/路5B/路5A 内容）
         —— 依据：细化_2c2b §5.3（/锻造树（无参）查看当前可锻装备树（分页））+ 列表模板统一
            （core/message_format/list_render：5 条/页 + CakeGame 尾段，2026-08-27 用户拍板）
      —— 批5 路5A 扩展作者：Hermes 子agent-5A（/图纸 主链+分支+持有进度渲染 cmd_blueprint +
         /图纸 CommandSpec 注册；消费 5B forge_node_suffix/forge_progress_segment，
         标注文案不重复实现——红名/失效文案由 5B 统一提供）

【批内协作状态】路4A（原子流程引擎：守卫 GU-01~06 + 成功/失败模板）与路4B 同批并行。
本工作区收口时 forge_commands.py 尚未落盘（批4 拆 4A+4B 子批并行，4A 未先提交），
为保证交付可运行且自测可过，本文件一次性承载路4A 原子流程（_forge_atomic）+ 路4B
双流/确认窗——文件名/入口签名（register_forge_commands + cmd_forge + cmd_confirm）
对齐任务派工单，主 agent 收口时若路4A 另行落盘可按契约合并。

功能描述（路4B 主体）：
  ① 双流路由：cmd_forge 入口先判 settings.forge.straight_forge（缺省 true）——
     - true（直锻）：无「预览」参数 → 原子流程直接成功（小白 1 步，TC-09）；
     - 显式「预览」参数 → 预览流 2 步（TC-10）；
     - false（深度模式）：全部 /锻造 强制预览（前台无直锻入口，TC-13）；
     - 双流并存：直锻开时仍可显式带「预览」切深度流（预览参数不依赖开关，2c2b §3.1）。
  ② 预览卡片（2c2b §3.2 / TC-10）：`<节点名>（<属性摘要>）` 标题 + 素材行
     （前置节点名 + 各行素材 + 需求档位级）+ 孔位/后续行（slots + 主线 child → ■终结）；
     **预览不扣任何资源**（0 副作用）。
  ③ 确认窗（2c2b §3.3 / TC-11~14）：
     - 预览发出后登记一次性待确认上下文（单键：qid → {node_id, ts} 字段快照），
       ctx 内存窗（ctx["forge_preview"] = {qid: {node_id, ts}}）；
     - /确认 cmd_confirm：重跑 GU-03~06 守卫再扣素材发经验（复用 _forge_atomic 原子执行）
       → `✅ <节点> 锻造完成！`（TC-12）；未确认/超时（carry_sec 缺省 90，0=不限）
       → 上下文作废，无锻造无扣款无经验（TC-11）；
     - 同一玩家同时仅 1 个待确认窗；新 /锻造 或 /图纸 不覆盖既有窗（保持可感知）；
     - **边界**：超短期一次性引导，非框架 3.18 会话（不持久化、不可跨指令续接）；
     - 无进行中预览时 /确认 → 拒绝「当前无可确认的锻造预览」（TC-14）。
  ④ register_forge_commands 追加 /确认 CommandSpec（白名单标记）。
  ⑤ 路4A 原子流程（_forge_atomic）：守卫 GU-01~06 顺序链（系统注册/参数/节点存在可锻/
     前置已锻/素材足够/等级足够）+ 成功路径（扣素材/扣金币/实例化入包/发经验原子写）+
     失败零副作用（2c2b §1.1~1.3）。
  ⑥ 实例快照入档 + 图鉴 item 分册点亮（批4 路4D 扩展，追加不改写批4-1 内容）：
     - 成功路径除 player["forge_last"]（最近一次快照）外，追加 player["forge_instances"]
       全量实例快照列表——每件 {node_id, item_id, name, ts(回合/事件计数，ctx 时钟),
       stats(合并后快照), slots, quality, rarity}，含 node_id/item_id 双向溯源
       （forge 节点 → items 装备条目互查），供后续 /装备 /背包 读取
       （2c2b §1.2 步骤 4「实例化并快照：属性快照入玩家存档」/ AR-5 / 接口摸底缺口2）；
     - forge_last 与 forge_instances 一致性：forge_last = 最新快照的独立拷贝
       （只读安全：外部读写互不污染）；
     - 首次锻造同刻点亮图鉴 weapon + item 分册（mark_seen ref = items 装备条目 id
       node.item，非 forge 节点 id node_*；素材类也进物品册，装备类经 weapon 册）。

依据（文件头标注）：
  - docs/细化/细化_2c2b_锻造流程契约.md §三（3.1 双流开关语义 / 3.2 预览卡片 / 3.3 确认窗
    与会话边界 / 3.4 双流差异对照）+ §1.1（守卫 GU-01~06）/ §1.2（成功路径）/ §1.3（失败模板）
    + §六 C（验收 TC-09~14）。—— §1.2 步骤 4「实例化并快照：属性快照入玩家存档」/
      步骤 5「图鉴点亮」为批4 路4D 扩展点。
  - docs/细化/细化_2c2b_锻造流程契约.md §五 5.1（P-01~06 词法）/ §5.2（匹配算法：精确→
    唯一前缀→歧义列表）——批4 路4C 参数词法扩展点（parse_forge_target 独立词法函数 +
    批量 *N 消费进 forge_atomic；歧义/未知仍走引擎 resolve_node，词法层只喂 key）。
  - 定稿（锻造系统设计定稿 v1.0.1）§3.1 L74-79（直锻）/ §3.3 L89-97（预览+/确认）/
    §2.1 #7 L57（双流）/ settings straight_forge L355 / 零会话 L239（不使用框架 3.18）。
  - docs/m9_shared_contract.md §三（S-03 straight_forge 缺省 true）/ §二（ForgeNode 字段）。
  - docs/m9_接口摸底.md §二（缺口2：装备实例快照管线——/锻造 完成时「items 基础 + 节点
    改造」合并实例化 → 属性快照入玩家存档；批4 路4D 落档结构）。
  - AR-5 快照缺省键（2c2a §1.3 / forge_tree.F-5）：stats/slots/rarity/final/augmentable/
    monster_source 齐备——批4 路4D 快照取自合并产物 inst（forge_tree.merge_forge_instance）。
  - 批5 路5B（/图纸 标注段）：docs/细化/细化_2c2b_锻造流程契约.md §2.2（当前持有段 +
    输出结构）/ §2.3（✓ 标注规则：已锻＝✓态、素材满额＝✓态、满链推进度）/ §2.4（失效
    标注：红名「已失效：物品已删除」）+ 定稿 §4（装备派生树）。——主链/分支渲染归路5A，
    本段只提供行尾标注（forge_node_suffix）+ 持有进度段接线（forge_progress_segment）。
  - 批5 路5A（/图纸 主链+分支+持有进度）：docs/细化/细化_2c2b_锻造流程契约.md §二 2.2
    （主链全链：根 → … → 目标节点 → … → ■最终强化，终结点 ■ + 属性标注）/ §2.1（无门槛）、
    §2.4（红名失效标注——行尾标注文案由 5B forge_node_suffix 统一，本路消费不重复实现）+
    定稿 §4（装备派生树）/ §2.1 #8（素材即进度 L58）。——分支折叠：forge_sp.sp_locked
    （SP-F1 unlock_branch_tree 未解锁 → 分支段折叠只显主干）。

【工程补白 · 显式标注】（契约/细化未显式定义处的实现口径，标 F-x）：
  F-1  预览卡片渲染：2c2b §3.2 卡片示意含 📖 图标（定稿 L92），本仓 emoji 纪律
       （用户拍板「不用 emoji」，tests/unit/test_emoji_discipline.py 全仓扫描）只允许
       ✅/❌ + 排版符号 → 卡片标题降级纯文本 `<节点名>（<属性摘要>）`（对齐 M5 裁决
       「数据型功能图标一律降级纯文本」；alchemy_commands 同口径弃用 📖）。
  F-2  ctx 契约（对齐 synthesis.py / alchemy_commands）：ctx 为 MutableMapping，含
       ctx["forge"]（forge.json 顶层 raw，含 trees/settings）/ ctx["items"]（items 表，
       Mapping 或 list）/ ctx["player"]（玩家状态 MutableMapping，就地改写
       proficiency/currencies/inventory）/ ctx["inventory"]（背包计数 in-memory 兜底）/
       ctx["count_item"]/ctx["remove_item"]/ctx["add_item"] hooks / ctx["settings"]
       （完整 settings dict 含 forge 段）/ ctx["qid"]（玩家 id，确认窗单键）。
       ctx["now"]：确认窗超时判定时钟（装配层注入；缺省 time.time 兜底，对齐
       alchemy_commands 种植/收获 now 兜底口径；零定时器/零睡眠，仅读时钟）。
  F-3  确认窗内存窗形态：ctx["forge_preview"] = {qid: {"node_id": str, "ts": float}}，
       装配层/测试注入共享 ctx 即共享窗；不持久化（非 3.18 会话，定稿 L239）。
       carry_sec 读 settings.forge.carry_sec（缺省 90，0=不限；非 FORGE_SETTINGS_KEYS
       标准键，本壳层读段兜底）。
  F-4  需求档位名：素材行「需求：铸造 <档位> 级」——<档位> = ProficiencyEngine
       tier_name(FORGE_JOB_ID, node.level)（与 forge_job.rank_name 同源；level 越界钳末档）。
  F-5  品质中文映射：normal→普通 / fine→精良 / epic→史诗 / legendary→传说（对齐
       formula_engine 品质类字符串映射 + 定稿 L78「品质：X（固定）」）。
  F-6  属性摘要：stats.element 存在 → `<元素中文>属性+<element_value>`（元素中文用
       alchemy_core.ELEMENT_NAMES_CN 同表）；无 element → 用 stats 首项 `atk`/`def`
       摘要（`攻击+<atk>`）；均无 → 空摘要。
  F-7  孔位渲染：slots 非空 → `孔位：<Lv> 级槽 ×<n> | ...`（同 level 合并计数）；
       空 → 略去孔位段。后续段：主线 child（非 branch 的 children 首项）→
       line_endpoint（■终结名）；无主线 child → 略去。
  F-8  确认窗超时边界：carry_sec=0 表示不限（永不因超时作废，仅 /确认 时重跑守卫）。
       超时判定在 cmd_confirm 内用 ctx now 比较（now - ts > carry_sec），不 sleep。
  F-9  实例快照落档（批4 路4D）：player["forge_instances"] 为 list（锻造序，可回溯），
       每件 = _forge_snapshot 输出（node_id/item_id/name/ts/stats/slots/quality/rarity，
       stats/slots 为深拷贝）；player["forge_last"] = 最新快照独立拷贝（只读安全）。
       quality 缺省映射 inst.rarity（AR-3 品质仲裁产物；items 基础无 quality 键时）。
       后续 /装备 /背包 读取本结构即保证数据落档可查（本路不写读指令）。
  F-10 图鉴 item 分册点亮（批4 路4D）：首次锻造同刻 mark_seen(ctx,"weapon",item_ref,name)
       与 mark_seen(ctx,"item",item_ref,name)——weapon 册 total 来自 registry equipment
       表（codex._total_of），ref 必须与 items 装备条目 id（node.item）对齐，非 forge
       节点 id（node_*）；item 分册同 ref 进物品册（素材类经其素材产生处点亮，装备类
       经 weapon 册+item 册双登记）。图鉴回写失败不阻断锻造结算（辅助钩子）。
  F-11 罗马数字等价（批4 路4C）：任务派工单明令 P-03 采用「罗马数字统一映射
       （Ⅰ=1…Ⅹ=10）」，保证「炎剑Ⅱ」与「炎剑2」等价命中——与细化 2c2b §5.1 P-03 原文
       （「Ⅱ≠2 除非配置别名」）口径不同；本实现按派工单裁决执行（歧义/未知判定不变），
       在 parse_forge_target 层做 Ⅰ-Ⅹ↔1-10 双向归一后喂 resolve_node（引擎不改动），
       节点名按 2c2a N-02 原样登记（不写回改写）。文件头依据标注含此裁决。
  F-12 /图纸 标注段（批5 路5B）：契约 ✓ 符号在本仓 emoji 纪律下渲染为 ✅（批2 F-1 同口径
       ——用户拍板「不用 emoji」，仅 ✅/❌ + 排版符号），已锻节点/素材满额 行尾统一 `✅`；
      失效标注文案 `（已失效：物品已删除）`（2c2b §2.4 / 定稿 L296）为 /图纸 侧行尾标注，
      与 /锻造 拒绝文案 `❌ 已失效：物品已删除`（批4-1 已落地）同源、不改写批4 内容。
      红名节点标注优先（2.4 红名不参与 ✓ 判定），已锻判定 = player["forged"] 含节点 id
      （父链已锻集，与 forge_tree._forged_set / already_forged 同口径，list/set/tuple 兼容）。

铁律：零 NoneBot import（3a R1）；纯函数确定性（同刻同参必同值）；不写定时器/睡眠调用
      （确认窗超时用 ctx now 比较，不 sleep）；渲染输出无 emoji（仅 ✅/❌ + 排版符号
      | → × / 【】 ■）；确认窗不持久化（非 3.18 会话）；每功能可追溯（文件头标注依据）。
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Tuple

from qbot_rpg.core.alchemy_core import ELEMENT_NAMES_CN
from qbot_rpg.core.codex import mark_seen
from qbot_rpg.core.forge_cascade import is_redflagged
from qbot_rpg.core.forge_job import (
    _tier_name,
    exp_to_next,
    gain_forge_exp,
    level_gate_met,
)
from qbot_rpg.core.forge_progress import material_holdings, progress_line, shortfall
from qbot_rpg.core.forge_sp import sp_locked
from qbot_rpg.core.forge_tree import ForgeTreeEngine
from qbot_rpg.core.message_format.list_render import (
    DEFAULT_PAGE_SIZE,
    render_cake_tail,
    render_item_line,
)

# 同包兄弟模块：相对导入（G0 架构门禁，与 alchemy_commands/shop_commands 同口径）
from .parsers import parse_int
from .router import CommandSpec
from .sender import format_tpl12

__all__ = [
    # 指令名常量
    "FORGE_CMD",
    "CONFIRM_CMD",
    "PREVIEW_SUBWORD",
    # 窗口常量
    "DEFAULT_CARRY_SEC",
    "PREVIEW_WINDOW_KEY",
    # 参数词法（批4 路4C：P-01~06 + 解析错误分类模板）
    "parse_forge_target",
    "ERR_P_EMPTY",
    "ERR_P_SPACE",
    "ERR_P_CHARSET",
    "ERR_P_UNKNOWN",
    "ERR_P_AMBIGUOUS",
    "ERR_P_QTY",
    # 指令处理器（纯函数：parsed + ctx → 回复正文）
    "cmd_forge",
    "cmd_confirm",
    # 原子流程（路4A 承载；确认窗复用）
    "forge_atomic",
    # /图纸 标注段（批5 路5B：✓/✅/失效标注；供路5A 主链/分支/持有进度段调用）
    "FORGE_REDFLAG_SUFFIX",
    "FORGE_DONE_MARK",
    "forge_node_suffix",
    "forge_forged_prefix_names",
    "forge_progress_segment",
    # /图纸（批5 路5A：主链+分支+持有进度渲染 cmd_blueprint）
    "BLUEPRINT_CMD",
    "cmd_blueprint",
    # /锻造树（批5 路5C：全树可锻装备分页视图 cmd_forge_tree）
    "TREE_CMD",
    "cmd_forge_tree",
    "TREE_PAGE_SIZE",
    "TREE_EMPTY_PAGE",
    "TREE_TAIL_TIP",
    # 装配
    "register_forge_commands",
]

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 指令名（白名单已含：DEFAULT_WHITELIST「锻造」「确认」；「预览」为 FIXED_SUBWORDS）
FORGE_CMD: str = "锻造"
CONFIRM_CMD: str = "确认"
# /图纸（批5 路5A：主链+分支+持有进度渲染；CommandSpec whitelisted=True 注册，无门槛）
BLUEPRINT_CMD: str = "图纸"
# /锻造树（批5 路5C：全树可锻装备分页视图；CommandSpec whitelisted=True 注册，无门槛，
#   细化 2c2b §5.3 登记指令 / 定稿 L234「查看当前可锻装备树（分页）」）
TREE_CMD: str = "锻造树"
# 预览子词（2c2b §3.1：`/锻造 <节点> 预览`；parsers FIXED_SUBWORDS 已含「预览」）
PREVIEW_SUBWORD: str = "预览"

# 确认窗超时缺省（2c2b §3.3：carry_sec 缺省 90s，0=不限）
DEFAULT_CARRY_SEC: int = 90
# 确认窗内存窗键（ctx["forge_preview"] = {qid: {"node_id", "ts"}}；F-3）
PREVIEW_WINDOW_KEY: str = "forge_preview"

# /锻造树 分页每页条数（批5 路5C：列表类模板统一 5 条/页上限——全仓口径，
#   对齐 list_render.DEFAULT_PAGE_SIZE，用户 2026-08-27 拍板列表模板统一）
TREE_PAGE_SIZE: int = DEFAULT_PAGE_SIZE
# 越界页空态提示（细化 2c2b §5.3：/锻造树（无参）分页；越界页 → 空态提示，
#   输出「该页暂无锻造装备」+ 总页数引导，对齐 /背包 空态口径）
TREE_EMPTY_PAGE: str = "该页暂无锻造装备（/锻造树 共 {total_pages} 页）"
# /锻造树 Tip 尾行（列表模板统一 CakeGame 式「当前页 + Tip」，2026-08-27 用户拍板；
#   引导锻造入口，对齐 /背包 _BAG_TAIL_TIP 口径）
TREE_TAIL_TIP: str = "发送'/锻造 装备名'即可锻造"

# 品质四档中文（F-5：normal→普通 / fine→精良 / epic→史诗 / legendary→传说）
_RARITY_CN: Mapping[str, str] = {
    "normal": "普通",
    "fine": "精良",
    "epic": "史诗",
    "legendary": "传说",
}
# 部位中文（对齐 basic_commands._SLOT_NAME 口径：weapon→武器）
_SLOT_CN: Mapping[str, str] = {"weapon": "武器"}

# ---------------------------------------------------------------------------
# 参数词法常量（批4 路4C：P-01~06，细化 2c2b §五 5.1）
# ---------------------------------------------------------------------------

# 解析错误分类模板（P_EMPTY/P_SPACE/P_CHARSET/P_UNKNOWN/P_AMBIGUOUS/P_QTY）
ERR_P_EMPTY: str = "P_EMPTY"        # 空参数（无目标）
ERR_P_SPACE: str = "P_SPACE"        # 节点名含空格（P-01）
ERR_P_CHARSET: str = "P_CHARSET"    # 非法字符（P-02 允许字符集外）
ERR_P_UNKNOWN: str = "P_UNKNOWN"    # 未找到节点（GU-03 not_found）
ERR_P_AMBIGUOUS: str = "P_AMBIGUOUS"  # 歧义（候选多个，§5.2 ③）
ERR_P_QTY: str = "P_QTY"            # 数量非正整数（P-05 `*` 后须 ≥1）

# P-02 允许字符集（节点名/材料名）：中文 / 大小写英文 / 数字 / 间隔号· / 罗马数字Ⅰ-Ⅹ /
# 方头括号【】 / 短横-（细化 2c2b §5.1 P-02 允许集）；另加 ■（P-04 最终强化标记，输入可省可带）。
# 罗马数字 Ⅰ-Ⅹ = U+2160~U+2169（\w 族 Nl，解析器 token 亦放行）。
_ALLOWED_NAME_RE = re.compile(r"^[\u4e00-\u9fffA-Za-z0-9·\u2160-\u2169【】\-■]+$")

# P-03 罗马数字统一映射（Ⅰ=1…Ⅹ=10，任务派工单裁决；F-11）：罗马字符 → 阿拉伯数字串
_ROMAN_TO_DIGIT: Mapping[str, str] = {
    "Ⅰ": "1", "Ⅱ": "2", "Ⅲ": "3", "Ⅳ": "4", "Ⅴ": "5",
    "Ⅵ": "6", "Ⅶ": "7", "Ⅷ": "8", "Ⅸ": "9", "Ⅹ": "10",
}
# 数字串 → 罗马字符（单值逆映射；仅用于 1-10 内的数字段，超范围保留原文）
_DIGIT_TO_ROMAN: Mapping[int, str] = {
    1: "Ⅰ", 2: "Ⅱ", 3: "Ⅲ", 4: "Ⅳ", 5: "Ⅴ",
    6: "Ⅵ", 7: "Ⅶ", 8: "Ⅷ", 9: "Ⅸ", 10: "Ⅹ",
}
# 引号剥离（P-06 多词节点名可带引号整体作单参）：半角双引号 / 单引号 / 「」 / 『』
_QUOTE_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("\"", "\""), ("'", "'"), ("「", "」"), ("『", "』"),
)


# ---------------------------------------------------------------------------
# 工具（纯函数）
# ---------------------------------------------------------------------------

def _fragment(parsed: Any) -> str:
    """TPL-12 原文片段（parsed.raw 优先；缺省重构，对齐 shop_commands._fragment）。"""
    if getattr(parsed, "raw", None):
        return str(parsed.raw)
    cmd = getattr(parsed, "command", None) or ""
    args = getattr(parsed, "args", None) or []
    tail = (" " + " ".join(str(a) for a in args)) if args else ""
    return f"/{cmd}{tail}"


def _player_of(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """玩家状态 dict（ctx["player"] 优先；缺省 ctx 自身——测试可把 ctx 直接当 player）。"""
    player = ctx.get("player")
    if isinstance(player, MutableMapping):
        return player
    return ctx


def _qid_of(ctx: Mapping[str, Any]) -> Optional[str]:
    """玩家 id（确认窗单键；ctx["qid"] → ctx["player"] 内 qid/qq/player_qid）。"""
    qid = ctx.get("qid")
    if qid:
        return str(qid)
    player = ctx.get("player")
    if isinstance(player, Mapping):
        for k in ("qid", "qq", "player_qid"):
            v = player.get(k)
            if v:
                return str(v)
    return None


def _forge_raw(ctx: Mapping[str, Any]) -> Mapping[str, object]:
    """forge.json 顶层 raw dict（ctx["forge"]；非 Mapping → {}，GU-01 系统未启用兜底）。"""
    forge = ctx.get("forge")
    return forge if isinstance(forge, Mapping) else {}


def _settings_of(ctx: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    """完整 settings dict（ctx["settings"]；非 Mapping → None，引擎缺省兜底）。"""
    s = ctx.get("settings")
    return s if isinstance(s, Mapping) else None


def _engine(ctx: Mapping[str, Any]) -> ForgeTreeEngine:
    """ForgeTreeEngine（构造器注入 forge raw + items + settings；缺省兜底）。"""
    return ForgeTreeEngine(
        forge=_forge_raw(ctx),
        items=ctx.get("items"),
        settings=_settings_of(ctx),
    )


def _straight_forge(ctx: Mapping[str, Any]) -> bool:
    """straight_forge 开关（S-03 缺省 true；归一取 settings.forge 段）。"""
    seg = _forge_settings(ctx)
    v = seg.get("straight_forge")
    return v if isinstance(v, bool) else True


def _forge_settings(ctx: Mapping[str, Any]) -> Mapping[str, object]:
    """settings.forge 段（完整 settings dict 取段；forge 段本身直接消费；无 → {}）。"""
    settings = _settings_of(ctx)
    if settings is None:
        return {}
    seg = settings.get("forge")
    return seg if isinstance(seg, Mapping) else {}


def _carry_sec(ctx: Mapping[str, Any]) -> int:
    """确认窗超时秒数（settings.forge.carry_sec 缺省 90，0=不限；F-3）。"""
    v = _forge_settings(ctx).get("carry_sec")
    if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
        return v
    return DEFAULT_CARRY_SEC


def _now(ctx: Mapping[str, Any]) -> float:
    """当前时钟（ctx["now"] 注入优先；缺省 time.time 兜底，仅读时钟零睡眠，F-2）。"""
    v = ctx.get("now")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return time.time()


def _count_item(ctx: Mapping[str, Any], item_id: str) -> int:
    """持有计数（对齐 synthesis._count_item：hook 优先；inventory 兜底）。"""
    hook = ctx.get("count_item")
    if callable(hook):
        try:
            v: Any = hook(item_id)
            return int(v)
        except Exception:
            return 0
    inv = ctx.get("inventory")
    if isinstance(inv, Mapping):
        return int(inv.get(item_id, 0))
    return 0


def _remove_item(ctx: MutableMapping[str, Any], item_id: str, count: int) -> bool:
    """扣减（不部分扣减，对齐 synthesis._remove_item：hook 优先；inventory 兜底）。"""
    hook = ctx.get("remove_item")
    if callable(hook):
        try:
            return bool(hook(item_id, count))
        except Exception:
            return False
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        have = int(inv.get(item_id, 0))
        if have < count:
            return False
        inv[item_id] = have - count
        return True
    return False


def _add_item(ctx: MutableMapping[str, Any], item_id: str, count: int, bound: bool) -> bool:
    """入包（对齐 synthesis._add_item：hook 优先；inventory 兜底）。"""
    hook = ctx.get("add_item")
    if callable(hook):
        try:
            return bool(hook(item_id, count, bound))
        except Exception:
            return False
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        inv[item_id] = int(inv.get(item_id, 0)) + count
        return True
    return False


def _item_name(ctx: Mapping[str, Any], item_id: str) -> str:
    """物品 id → 显示名（items 表 name；缺省回退原 id，对齐 forge_progress._item_name）。"""
    items = ctx.get("items")
    if isinstance(items, Mapping):
        hit = items.get(item_id)
        if isinstance(hit, Mapping):
            name = hit.get("name")
            if isinstance(name, str) and name:
                return name
    elif isinstance(items, (list, tuple)):
        for e in items:
            if isinstance(e, Mapping) and e.get("id") == item_id:
                name = e.get("name")
                if isinstance(name, str) and name:
                    return name
    return item_id


def _material_text(ctx: Mapping[str, Any], node: Any) -> str:
    """素材段文本：`<前置节点名> + <素材名>×<count> + ...`（2c2b §3.2 素材行）。"""
    raw = node.raw if hasattr(node, "raw") else node
    parent_id = raw.get("parent") if isinstance(raw, Mapping) else None
    parts: List[str] = []
    if isinstance(parent_id, str) and parent_id:
        eng = _engine(ctx)
        pnode = eng.node(parent_id)
        if pnode is not None:
            parts.append(pnode.name or parent_id)
    holdings = material_holdings(ctx, node)
    for _iid, h in holdings.items():
        parts.append(f"{h.get('name', _iid)}×{h.get('need', 0)}")
    return " + ".join(parts)


def _req_text(ctx: Mapping[str, Any], node_level: object) -> str:
    """需求档位文本：`需求：铸造 <档位> 级`（F-4：档位名 = forge_job._tier_name(node.level)，
    与 rank_name 同源；level 越界钳末档）。"""
    lv = node_level if isinstance(node_level, int) and not isinstance(node_level, bool) else 1
    return f"需求：铸造 {_tier_name(lv)} 级"


def _element_summary(stats: Mapping[str, object]) -> str:
    """属性摘要（F-6）：element → `<元素中文>属性+<element_value>`；无 element → `攻击+N`。"""
    elem = stats.get("element")
    if isinstance(elem, str) and elem:
        ev = stats.get("element_value")
        val = f"+{ev}" if isinstance(ev, (int, float)) and not isinstance(ev, bool) else ""
        cn = ELEMENT_NAMES_CN.get(elem, elem)
        return f"{cn}属性{val}"
    atk = stats.get("atk")
    if isinstance(atk, (int, float)) and not isinstance(atk, bool):
        return f"攻击+{atk}"
    return ""


def _slots_text(slots: object) -> Optional[str]:
    """孔位段（F-7）：`孔位：<Lv> 级槽 ×<n> | ...`；空 slots → None。"""
    if not isinstance(slots, (list, tuple)):
        return None
    counts: Dict[int, int] = {}
    for s in slots:
        if isinstance(s, Mapping):
            lv = s.get("level")
            if isinstance(lv, int) and not isinstance(lv, bool) and lv >= 1:
                counts[lv] = counts.get(lv, 0) + 1
    if not counts:
        return None
    seg = " | ".join(f"{lv} 级槽 ×{counts[lv]}" for lv in sorted(counts))
    return f"孔位：{seg}"


def _continue_text(ctx: Mapping[str, Any], node_id: str) -> Optional[str]:
    """后续段（F-7）：主线 child → ■终结名；无主线 child → None。"""
    eng = _engine(ctx)
    node = eng.node(node_id)
    if node is None:
        return None
    children = eng.children_of(node_id)
    branch = set(eng.branch_of(node_id))
    main = [c for c in children if c not in branch]
    if not main:
        return None
    child = eng.node(main[0])
    child_name = child.name if child is not None else main[0]
    endpoint = eng.line_endpoint(node_id)
    ep_name = ""
    if endpoint:
        ep = eng.node(endpoint)
        ep_name = ep.name if ep is not None else endpoint
    return f"可继续锻造：{child_name} → {ep_name}" if ep_name else f"可继续锻造：{child_name}"


# ---------------------------------------------------------------------------
# 批4 路4C：参数解析完整词法（P-01~06，细化 2c2b §五 5.1）
# ---------------------------------------------------------------------------

def _strip_quotes(fragment: str) -> str:
    """P-06 引号剥离：多词节点名可整体带引号作单参数（`"炎王剑"` = `炎王剑`）。

    成对半角双引号 / 单引号 / 「」 / 『』 包裹 → 剥壳取内；非成对 → 原样返回
    （非法字符由 P-02 字符集校验拒绝）。纯函数确定性。
    """
    for left, right in _QUOTE_PAIRS:
        if fragment.startswith(left) and fragment.endswith(right) and len(fragment) >= 2:
            return fragment[1:-1]
    return fragment


def _roman_normalize(value: str) -> str:
    """P-03 罗马数字 → 阿拉伯数字（Ⅰ=1…Ⅹ=10，F-11）：`炎剑Ⅱ` → `炎剑2`。

    逐字符映射（Ⅹ→"10"）；非罗马字符原样保留。纯函数确定性。
    """
    return "".join(_ROMAN_TO_DIGIT.get(ch, ch) for ch in value)


def _digit_to_roman(value: str) -> str:
    """P-03 阿拉伯数字 → 罗马数字（1-10 段内）：`炎剑2` → `炎剑Ⅱ`（F-11 逆映射）。

    连续数字段整体换算（1-10 → Ⅰ-Ⅹ；超范围段保留原文），非数字字符原样保留。
    """
    def _rep(m: "re.Match[str]") -> str:
        n = int(m.group(0))
        return _DIGIT_TO_ROMAN.get(n, m.group(0))
    return re.sub(r"\d+", _rep, value)


def _resolve_with_roman(eng: ForgeTreeEngine, key: str) -> Tuple[str, dict]:
    """resolve_node + P-03 罗马等价兜底：依次喂 原key → 罗马归一 → 数字转罗马。

    返回 (命中用 key, resolve 结果)：命中时 key 为实际喂入且成功的变体（forge_atomic
    复用该 key 二次 resolve 恒一致）；全部未命中时合并歧义候选（文件序去重）或返回
    首个结果（not_found）。resolve_node 引擎不改动（只喂 key 过去，任务要求）。
    """
    variants: List[str] = [key]
    nk = _roman_normalize(key)
    if nk != key and nk not in variants:
        variants.append(nk)
    dk = _digit_to_roman(key)
    if dk != key and dk not in variants:
        variants.append(dk)

    results: List[dict] = []
    for k in variants:
        res = eng.resolve_node(k)
        if res.get("ok"):
            return k, res
        results.append(res)

    # 全部未命中：合并歧义候选（去重保序）或返回首个 not_found
    merged: List[str] = []
    for r in results:
        if r.get("match") == "ambiguous":
            for nid in (r.get("candidates") or []):
                if nid not in merged:
                    merged.append(nid)
    if merged:
        return key, {"ok": False, "match": "ambiguous", "node_id": None, "node": None,
                     "candidates": merged}
    return key, results[0]


def _ambiguous_message(eng: ForgeTreeEngine, candidates: List[str]) -> str:
    """歧义候选渲染（§5.2 ③：候选名（LvN）+ /锻造树 指引）。"""
    lines = []
    for nid in candidates:
        nd = eng.node(nid)
        nm = nd.name if nd is not None else nid
        lv = nd.level if nd is not None else 0
        lines.append(f"{nm}（Lv{lv}）")
    return "候选多个节点：" + " | ".join(lines) + " → /锻造树 查看可锻装备"


def parse_forge_target(fragment: str, eng: Optional[ForgeTreeEngine] = None) -> dict:
    """/锻造 目标参数词法（批4 路4C：P-01~06 全流程，细化 2c2b §五 5.1）。

    入参：
      - fragment：单参原文（节点名 + 可选 `*N` 数量；可带引号/前导 + /前导 ■）。
      - eng：ForgeTreeEngine（可选）。提供时做 P_UNKNOWN/P_AMBIGUOUS 判定（喂 key 给
        resolve_node，引擎独立不改动）；None 时只做纯词法（P_EMPTY/P_SPACE/P_CHARSET/
        P_QTY），ok 即返回，供无引擎场景复用。

    出参（解析错误分类模板，任务要求）：
      - ok：True 解析通过 / False 词法或匹配失败。
      - key：归一后的节点名（P-04 ■ 保留给 resolve_node 剥、P-03 罗马等价命中变体）。
      - qty：批量数量（P-05 `*N`；缺省 1）。
      - error_code：失败分类 P_EMPTY/P_SPACE/P_CHARSET/P_QTY/P_UNKNOWN/P_AMBIGUOUS。
      - message：可渲染错误文案（ok=False 时）。
      - candidates：歧义候选节点 id 列表（P_AMBIGUOUS 时）。

    词法顺序（P-01~06）：空参 → 空格 → 数量 `*N` → 字符集 → 匹配。纯函数确定性。
    """
    frag = _strip_quotes((fragment or "").strip())
    if frag.startswith("+"):  # 紧凑 `+` 连接符收敛（对齐 _target_of）
        frag = frag[1:].strip()

    # P_EMPTY：空参数（无目标）→ TPL-12 兜底由调用方处理，此处给分类
    if not frag:
        return {"ok": False, "key": "", "qty": 1, "error_code": ERR_P_EMPTY,
                "message": "参数错误：缺少锻造目标（示例：/锻造 铁剑 或 /锻造 炎剑Ⅱ*3）",
                "candidates": []}

    # P-01 节点名禁空格（含 tab/全角空格等空白字符）
    if any(ch.isspace() for ch in frag):
        return {"ok": False, "key": frag, "qty": 1, "error_code": ERR_P_SPACE,
                "message": "参数错误：节点名不含空格", "candidates": []}

    # P-05 数量 `*N`：`*` 后须正整数（≥1）；`预览 *N` 顺序兼容由 cmd_forge 剥离预览后进入
    qty: int = 1
    name = frag
    if "*" in frag:
        name, _, right = frag.partition("*")
        if not right.isdigit() or int(right) < 1:
            return {"ok": False, "key": name, "qty": 1, "error_code": ERR_P_QTY,
                    "message": "参数错误：数量须为正整数（示例：/锻造 炎剑Ⅱ*3）",
                    "candidates": []}
        qty = int(right)

    # P-02 允许字符集（中文/字母/数字/·/Ⅰ-Ⅹ/【】/-/■；非法字符 → 明确拒绝）
    if not name or not _ALLOWED_NAME_RE.match(name):
        return {"ok": False, "key": name, "qty": 1, "error_code": ERR_P_CHARSET,
                "message": "参数错误：节点名含非法字符"
                           "（仅允许 中文/字母/数字/·/Ⅰ-Ⅹ/【】/-/■）",
                "candidates": []}

    # P-06 多词节点名（连续无空格）整体作为单参数：name 已为整串；词法到此通过
    if eng is None:
        return {"ok": True, "key": name, "qty": qty, "error_code": None,
                "message": None, "candidates": []}

    # 匹配（喂 key 给 resolve_node；P-03 罗马等价 + P-04 ■ 省略由引擎 match_name 剥）
    hit_key, res = _resolve_with_roman(eng, name)
    if res.get("ok"):
        return {"ok": True, "key": hit_key, "qty": qty, "error_code": None,
                "message": None, "candidates": []}
    if res.get("match") == "ambiguous":
        cands = list(res.get("candidates") or [])
        return {"ok": False, "key": hit_key, "qty": qty, "error_code": ERR_P_AMBIGUOUS,
                "message": _ambiguous_message(eng, cands), "candidates": cands}
    return {"ok": False, "key": hit_key, "qty": qty, "error_code": ERR_P_UNKNOWN,
            "message": f"未找到「{name}」→ /锻造树 查看可锻装备", "candidates": []}


# ---------------------------------------------------------------------------
# 路4A 原子流程（守卫 GU-01~06 + 成功/失败模板；确认窗复用）
# ---------------------------------------------------------------------------

def forge_atomic(ctx: MutableMapping[str, Any], key: object, *, preview: bool = False,
                 qty: int = 1) -> str:
    """/锻造 原子流程（路4A 承载；路4B 直锻/预览/确认 复用同一执行路径；
    批4 路4C 扩展批量 *N：qty>1 循环重跑守卫+原子，N 次成功 N 次结算）。

    入参：
      - ctx：玩家表示（MutableMapping；forge/items/settings/inventory/player + hooks）。
      - key：节点名/id（2c2b §5.2 匹配：精确→唯一前缀→歧义列表）。
      - preview：True = 预览流（渲染卡片 + 登记确认窗，不扣任何资源，TC-10/11）；
                 False = 执行流（守卫全过即原子扣素材/扣金币/产装/发经验，TC-09/12）。
                 qty 与预览组合时预览仍单次（预览 0 副作用，qty 不生效）。
      - qty：批量数量（P-05 `*N`；缺省 1）。qty>1 → 执行流按 N 次循环，每次重跑
             守卫 GU-03~06 + 原子结算（素材按件扣、实例按件入包、经验按件计，§1.2
             多件语义）；中途失败 → 中断并报「第 N 次失败，已成功 M 次」（已成功
             结算不回滚；§1.2 多件逐件原子）。qty 非正整数钳 1。
    出参：回复正文 str。

    守卫链（2c2b §1.1 GU-01~06，顺序固定）：
      GU-01 指令存在（forge.json 有效注册）；GU-02 参数可解析（名禁空格）；
      GU-03 节点存在 & 可锻（红名失效拒绝）；GU-04 前置已锻；GU-05 素材足够；
      GU-06 等级足够。
    失败零副作用（§1.3：不扣素材/不扣金币/不加经验/不建确认窗）。预览登记确认窗后
    仍不扣资源（3.3：预览 0 副作用）。
    """
    # GU-01 指令存在（forge.json trees 有效注册，2c2b §1.1）
    eng = _engine(ctx)
    if not eng.load_trees():
        return "❌ 锻造系统未启用（内容包 forge.json 未注册）"

    # GU-02 参数可解析（P-01：节点名禁空格；含空格 → 参数错误，不匹配任何节点）
    #   由 _forge_once 承载（批量逐件与单件同口径重跑）；此处先做一次快筛兜底
    if not isinstance(key, str) or not key.strip():
        return format_tpl12(_fragment_fallback(key))
    if any(ch.isspace() for ch in key):
        return "参数错误：节点名不含空格"

    if preview:
        # 预览流：单次卡片 + 登记一次性待确认窗（qty 不生效，预览 0 副作用）
        return _forge_once(ctx, key, preview=True)

    n = qty if isinstance(qty, int) and not isinstance(qty, bool) and qty >= 1 else 1
    if n == 1:
        return _forge_once(ctx, key, preview=False)

    # 批量 *N（P-05 / §1.2 多件）：逐件重跑守卫 + 原子结算，N 次成功 N 次结算
    successes = 0
    last_success = ""
    for i in range(1, n + 1):
        out = _forge_once(ctx, key, preview=False)
        if not out.startswith("✅"):
            return f"第 {i} 次失败，已成功 {successes} 次\n{out}"
        successes += 1
        last_success = out
    # 全部成功：汇总行（`✅ <名> 锻造完成！×N` + 属性行，属性取自末次成功）
    head, _, tail = last_success.partition("\n")
    return f"{head} ×{n}\n{tail}"


def _forge_once(ctx: MutableMapping[str, Any], key: object, *, preview: bool) -> str:
    """单次锻造（路4A 守卫 GU-02~06 + 成功/失败模板；供批量 *N 逐件重跑）。

    每次调用独立执行守卫链（素材逐件耗尽后重跑 GU-05 拦截）与 §1.2 原子结算；
    失败零副作用。预览路径渲染卡片 + 登记确认窗（0 资源副作用）。
    """
    eng = _engine(ctx)

    # GU-02 参数可解析（P-01：节点名禁空格；含空格 → 参数错误，不匹配任何节点）
    if not isinstance(key, str) or not key.strip():
        return format_tpl12(_fragment_fallback(key))
    if any(ch.isspace() for ch in key):
        return "参数错误：节点名不含空格"

    # GU-03 节点存在 & 可锻（resolve：精确→唯一前缀→歧义列表，2c2b §5.2）
    res = eng.resolve_node(key)
    if not res.get("ok"):
        match = res.get("match")
        if match == "ambiguous":
            cands = res.get("candidates") or []
            return _ambiguous_message(eng, list(cands))
        return f"未找到「{key}」→ /锻造树 查看可锻装备"
    node = res.get("node")
    node_id = res.get("node_id")
    if node is None or not isinstance(node_id, str):
        return f"未找到「{key}」→ /锻造树 查看可锻装备"
    player = _player_of(ctx)

    # GU-03b 红名失效节点拒绝（级联删除①，2c2a §五 V15 / 定稿 L296「已失效：物品已删除」）
    if is_redflagged(node):
        return "❌ 已失效：物品已删除"

    # GU-04 前置已锻（沿 parent 链；缺 → 报缺前置 + /图纸 指引，§1.3）
    if not eng.parent_forged(player, node_id):
        chain = eng.path_to_root(node_id)
        first_unforged = ""
        for nid in chain:
            if nid == node_id:
                break
            if not eng.already_forged(player, nid):
                nd = eng.node(nid)
                first_unforged = nd.name if nd is not None else nid
                break
        hint = f"需先锻造：{first_unforged}" if first_unforged else "需先锻造：前置节点"
        return f"❌ {hint} → /图纸 查看全链"

    # GU-05 素材足够（material_holdings + shortfall，§1.3 缺件模板 + 来源提示）
    holdings = material_holdings(ctx, node)
    short = shortfall(holdings)
    if short.get("items"):
        need = _material_text(ctx, node)
        deficits = []
        for (name, deficit, src) in short["items"]:
            base = f"{name}×{deficit}"
            deficits.append(base if not src else f"{base}（来源：{src}）")
        return (
            f"❌ 素材不足：需要 {need}；缺：{'、'.join(deficits)}"
            f" → /图纸 查看全链"
        )

    # GU-06 等级足够（可锻节点上限=职业等级，§1.3 L240 模板：熟练缺口 = exp_to_next）
    node_level = node.level
    gate = level_gate_met(player, node_level)
    if not gate.get("ok"):
        need_rank = _tier_name(int(gate.get("need", 0)))
        cur_rank = _tier_name(int(gate.get("current", 0)))
        # 还差 N 熟练：熟练缺口来自 §4.1 计价（exp_to_next 缺口，非等级差）
        missing = int(exp_to_next(player).get("missing", 0))
        return f"需要 {need_rank} 级，当前 {cur_rank}（还差 {missing} 熟练）"

    # ---- 守卫全过 ----
    if preview:
        # 预览流：渲染卡片 + 登记一次性待确认窗（不覆盖既有窗，3.3）；0 资源副作用
        window = _register_preview(ctx, node_id)
        card = _render_preview(ctx, node)
        if not window:
            return "已有待确认的锻造预览，请先 /确认 或等待超时\n" + card
        return card

    # 执行流（直锻 / 确认 / 批量 复用）：成功路径 §1.2 原子写（扣素材/扣金币/产装/发经验）
    return _execute(ctx, player, node, node_id)


def _fragment_fallback(key: object) -> str:
    """无参数时 TPL-12 片段兜底（/锻造 空参）。"""
    return f"/{FORGE_CMD} {key}" if key not in (None, "") else f"/{FORGE_CMD}"


def _render_preview(ctx: Mapping[str, Any], node: Any) -> str:
    """预览卡片（2c2b §3.2 / TC-10；F-1 无 emoji 纯文本）。

    三行：`<节点名>（<属性摘要>）` / `素材：<前置 + 素材行> | <需求档位级>` /
    `孔位：<slots> | 可继续锻造：<主线 child → ■终结>`（孔位/后续为空段略去）。
    """
    name = node.name if hasattr(node, "name") and node.name else (node.get("name") or "")
    stats = node.stats if hasattr(node, "stats") else (node.get("stats") or {})
    title = f"{name}（{_element_summary(stats)}）" if _element_summary(stats) else name
    lines: List[str] = [title]

    mats = _material_text(ctx, node)
    req = _req_text(ctx, node.level if hasattr(node, "level") else node.get("level"))
    lines.append(f"素材：{mats} | {req}")

    tail: List[str] = []
    slots = node.slots if hasattr(node, "slots") else (node.get("slots") or [])
    slots_seg = _slots_text(slots)
    if slots_seg:
        tail.append(slots_seg)
    node_id = node.id if hasattr(node, "id") else node.get("id")
    cont = _continue_text(ctx, node_id) if node_id else None
    if cont:
        tail.append(cont)
    if tail:
        lines.append(" | ".join(tail))
    return "\n".join(lines)


def _register_preview(ctx: MutableMapping[str, Any], node_id: str) -> bool:
    """登记一次性待确认窗（3.3：同一玩家仅 1 窗；新预览不覆盖既有窗）。

    入参：ctx（MutableMapping；窗落 ctx[PREVIEW_WINDOW_KEY][qid]）、node_id。
    出参：True=登记成功；False=已有待确认窗（不覆盖，保持可感知）。
    qid 缺失（无 ctx qid / player qid）→ 不登记（返回 True：预览仍可出卡片，
    但 /确认 无窗可确认——装配层应恒注入 qid）。
    """
    qid = _qid_of(ctx)
    if qid is None:
        return True
    window = ctx.get(PREVIEW_WINDOW_KEY)
    if not isinstance(window, MutableMapping):
        window = {}
        ctx[PREVIEW_WINDOW_KEY] = window
    existing = window.get(qid)
    if isinstance(existing, Mapping) and not _window_expired(ctx, existing):
        return False  # 不覆盖既有窗
    window[qid] = {"node_id": node_id, "ts": _now(ctx)}
    return True


def _window_expired(ctx: Mapping[str, Any], window: Mapping[str, object]) -> bool:
    """确认窗是否超时（carry_sec=0 不限；now - ts > carry_sec 判定，零 sleep，F-8）。"""
    carry = _carry_sec(ctx)
    if carry == 0:
        return False
    ts = window.get("ts")
    if not isinstance(ts, (int, float)):
        return True  # 无时间戳 → 视为过期（保守作废）
    return (_now(ctx) - float(ts)) > carry


def _execute(
    ctx: MutableMapping[str, Any],
    player: MutableMapping[str, Any],
    node: Any,
    node_id: str,
) -> str:
    """成功路径（2c2b §1.2 原子写：扣素材/扣金币/实例化入包/发经验 + 成功行渲染）。

    扣减顺序：先扣素材（remove_item 全量，任一失败回滚已扣项）→ 扣金币（node.cost
    coins 或 settings forge_fee=节点等级×10）→ 实例化合并（merge_forge_instance）→
    add_item 入包 → 熟练经验入账（gain_forge_exp，节点等级×2）。全链零中间态
    （失败即回滚已扣项，失败零副作用 §1.3）。
    """
    eng = _engine(ctx)

    # 扣素材（先校验可扣，再全量扣；失败零副作用）
    holdings = material_holdings(ctx, node)
    for item_id, h in holdings.items():
        if int(h.get("have", 0)) < int(h.get("need", 0)):
            # 素材不足（确认窗期间素材变化导致 → 拒绝，失败零副作用）
            name = str(h.get("name", item_id))
            deficit = int(h.get("need", 0)) - int(h.get("have", 0))
            src = str(h.get("source", ""))
            base = f"❌ 素材不足：需要 {_material_text(ctx, node)}；缺：{name}×{deficit}"
            base = base if not src else f"{base}（来源：{src}）"
            return f"{base} → /图纸 查看全链"
    deducted: List[str] = []
    for item_id, h in holdings.items():
        if not _remove_item(ctx, item_id, int(h.get("need", 0))):
            # 扣减失败 → 回滚已扣项（原子性，失败零副作用）
            for done in deducted:
                _add_item(ctx, done, int(holdings[done]["need"]), bound=False)
            return "❌ 素材扣减失败，本次锻造未执行（零副作用）"
        deducted.append(item_id)

    # 扣金币（node.cost.coins 显式覆盖 > settings forge_fee=节点等级×10，2c2a N-11）
    cost = _resolve_cost(ctx, node)
    currencies = player.get("currencies") if isinstance(player, MutableMapping) else None
    coins_have = 0
    if isinstance(currencies, MutableMapping):
        coins_have = int(currencies.get("coins", 0))
    if cost > 0 and coins_have < cost:
        # 金币不足 → 回滚素材，失败零副作用
        for done in deducted:
            _add_item(ctx, done, int(holdings[done]["need"]), bound=False)
        return f"❌ 金币不足：需要 {cost}，当前 {coins_have}"
    if cost > 0 and isinstance(currencies, MutableMapping):
        currencies["coins"] = coins_have - cost

    # 实例化并入包（AR-1~5 合并：items 基础 + 节点改造 → 属性快照入存档）
    item_ref = node.item if hasattr(node, "item") else (node.get("item") or node.get("output_item"))
    if isinstance(item_ref, str) and item_ref:
        items_def = _resolve_items_def(ctx, item_ref)
        inst = eng.merge_forge_instance(items_def, node)
        if not _add_item(ctx, item_ref, 1, bound=False):
            # 入包失败 → 回滚素材+金币（原子性）
            for done in deducted:
                _add_item(ctx, done, int(holdings[done]["need"]), bound=False)
            if cost > 0 and isinstance(currencies, MutableMapping):
                currencies["coins"] = coins_have
            return "❌ 装备入包失败，本次锻造未执行（零副作用）"
        # 实例快照入档（批4 路4D：AR-5 + 接口摸底缺口2——forge_instances 全量快照
        #   （node_id/item_id 双向溯源 + ts 回合/事件计数）+ forge_last 指向最新）
        snap = _forge_snapshot(ctx, node, node_id, item_ref, inst)
        _append_instance(player, snap)

    # 标记已锻造（forge_guard F-1：player["forged"] 追加节点 id；set/frozenset → 转 list）
    forged = player.get("forged")
    if not isinstance(forged, list):
        forged = list(forged) if isinstance(forged, (set, frozenset, tuple)) else []
        player["forged"] = forged
    if node_id not in forged:
        forged.append(node_id)

    # 熟练经验入账（EXP-01 craft 来源；节点等级×2 可配）
    node_lv = node.level if hasattr(node, "level") else 1
    gain_forge_exp(player, node_lv if isinstance(node_lv, int) else 1,
                   settings=_settings_of(ctx))

    # 首次锻造图鉴点亮（2c2b §1.2 步骤 5：mark_seen weapon 分册，ref=装备 item id，名=节点名）
    #   图鉴 weapon 册 total 来自 registry equipment 表（codex._total_of），ref 必须与
    #   items 装备条目 id 对齐（node.item），不能用 forge 节点 id（node_* 非装备条目 id）。
    #   （批4 路4D 追加）同刻点亮 items 分册（mark_seen "item" 同 ref）——素材类也进
    #   物品册，装备类经 weapon 册 + item 册双登记（2c2b §1.2 步骤 5 / F-10）。
    try:
        item_ref = getattr(node, "item", None) or node_id
        node_name = getattr(node, "name", None) or node_id
        mark_seen(ctx, "weapon", item_ref, node_name)
        mark_seen(ctx, "item", item_ref, node_name)
    except Exception:
        pass  # 图鉴回写失败不阻断锻造结算（图鉴为辅助钩子）

    return _success_line(ctx, node)


def _resolve_cost(ctx: Mapping[str, Any], node: Any) -> int:
    """锻造金币开销（2c2a N-11 cost 显式 > settings forge_fee；forge_fee 缺省 节点等级×10）。"""
    raw = node.raw if hasattr(node, "raw") else node
    cost = raw.get("cost") if isinstance(raw, Mapping) else None
    if isinstance(cost, Mapping):
        coins = cost.get("coins")
        if isinstance(coins, int) and not isinstance(coins, bool) and coins >= 0:
            return coins
    seg = _forge_settings(ctx)
    fee = seg.get("forge_fee")
    lv = node.level if hasattr(node, "level") else node.get("level")
    lv = lv if isinstance(lv, int) and not isinstance(lv, bool) and lv > 0 else 1
    if isinstance(fee, int) and not isinstance(fee, bool) and fee >= 0:
        return fee
    if isinstance(fee, str):
        for token in fee.split("×"):
            t = token.strip()
            if t.isdigit():
                return lv * int(t)
    return lv * 10  # 缺省 节点等级×10（S-01）


def _resolve_items_def(ctx: Mapping[str, Any], item_id: str) -> Mapping[str, object]:
    """items 条目解析（id→条目 Mapping 或条目 list/tuple；缺 → {}，merge 兜底）。"""
    items = ctx.get("items")
    if isinstance(items, Mapping):
        hit = items.get(item_id)
        return hit if isinstance(hit, Mapping) else {}
    if isinstance(items, (list, tuple)):
        for e in items:
            if isinstance(e, Mapping) and e.get("id") == item_id:
                return e
    return {}


# ---------------------------------------------------------------------------
# 批4 路4D：实例快照入档（AR-5 / 接口摸底缺口2）+ 图鉴 item 分册点亮
# ---------------------------------------------------------------------------

def _forge_snapshot(
    ctx: Mapping[str, Any],
    node: Any,
    node_id: str,
    item_id: str,
    inst: Mapping[str, object],
) -> Dict[str, object]:
    """锻造实例快照（批4 路4D / AR-5 / 接口摸底缺口2：属性快照入玩家存档）。

    入参：ctx（时钟 ts 取 _now）、node（ForgeNode，取显示名）、node_id（forge 节点 id）、
      item_id（items 装备条目 id）、inst（merge_forge_instance 合并产物，AR-1~5 齐备）。
    出参：快照 dict——{node_id, item_id, name, ts, stats, slots, quality, rarity}：
      - node_id / item_id：双向溯源（forge 节点 ↔ items 装备条目互查，铁律9）；
      - name：装备显示名（node.name → inst.name → node_id 兜底）；
      - ts：回合/事件计数（ctx 时钟，_now 注入优先，零定时器）；
      - stats / slots：合并后快照（深拷贝，不引用 inst 内部可变对象）；
      - quality：inst.quality 优先，缺省映射 inst.rarity（AR-3 品质仲裁产物）；
      - rarity：inst.rarity（档位，可为 None）。
    纯函数（确定性）；不改写入参。
    """
    stats = inst.get("stats")
    slots = inst.get("slots")
    rarity = inst.get("rarity")
    quality = inst.get("quality")
    if quality is None:
        quality = rarity
    node_name = getattr(node, "name", None) or node_id
    if not isinstance(node_name, str) or not node_name:
        inst_name = inst.get("name")
        node_name = str(inst_name) if isinstance(inst_name, str) and inst_name else node_id
    return {
        "node_id": node_id,
        "item_id": item_id,
        "name": node_name,
        "ts": _now(ctx),
        "stats": dict(stats) if isinstance(stats, Mapping) else {},
        "slots": list(slots) if isinstance(slots, (list, tuple)) else [],
        "quality": quality,
        "rarity": rarity,
    }


def _append_instance(
    player: MutableMapping[str, Any],
    snap: Mapping[str, object],
) -> None:
    """实例快照入档（批4 路4D：player["forge_instances"] 全量 + forge_last 指向最新）。

    forge_instances：list（锻造序，可回溯全量）；每件为 _forge_snapshot 输出
      （含 node_id/item_id 双向溯源），供后续 /装备 /背包 读取。
    forge_last：最新快照的独立拷贝（只读安全——外部读侧改动 forge_last 引用
      不污染实例列表条目，反之亦然；stats/slots 亦独立拷贝）。
    """
    instances = player.get("forge_instances")
    if not isinstance(instances, list):
        instances = []
        player["forge_instances"] = instances
    instances.append(dict(snap))
    stats = snap.get("stats")
    slots = snap.get("slots")
    player["forge_last"] = {
        "node_id": snap.get("node_id"),
        "item_id": snap.get("item_id"),
        "name": snap.get("name"),
        "ts": snap.get("ts"),
        "stats": dict(stats) if isinstance(stats, Mapping) else {},
        "slots": list(slots) if isinstance(slots, (list, tuple)) else [],
        "quality": snap.get("quality"),
        "rarity": snap.get("rarity"),
    }


def _success_line(ctx: Mapping[str, Any], node: Any) -> str:
    """成功行（2c2b §1.2 / 定稿 L78：`✅ <节点名> 锻造完成！` + 属性行）。

    属性行：`攻击 N | 部位：武器 | 槽位：无 | 品质：<四档>（固定）`；
    带孔装备 槽位 显示 `1 级槽 ×1`（2c2a N-09 / 定稿 L190）。
    """
    name = node.name if hasattr(node, "name") and node.name else (node.get("name") or "")
    stats = node.stats if hasattr(node, "stats") else (node.get("stats") or {})
    node_type = node.node_type if hasattr(node, "node_type") else node.get("type")
    atk = stats.get("atk")
    atk_text = f"攻击 {atk}" if isinstance(atk, (int, float)) and not isinstance(atk, bool) else ""
    slot_cn = _SLOT_CN.get(str(node_type or ""), str(node_type or ""))
    slots = node.slots if hasattr(node, "slots") else (node.get("slots") or [])
    slots_seg = _slots_text(slots)
    slot_text = slots_seg.replace("孔位：", "") if slots_seg else "无"
    rarity_raw = node.rarity if hasattr(node, "rarity") else node.get("rarity")
    rarity_cn = _RARITY_CN.get(str(rarity_raw or "normal"), "普通")
    fields = []
    if atk_text:
        fields.append(atk_text)
    fields.append(f"部位：{slot_cn}")
    fields.append(f"槽位：{slot_text}")
    fields.append(f"品质：{rarity_cn}（固定）")
    return f"✅ {name} 锻造完成！\n" + " | ".join(fields)


# ---------------------------------------------------------------------------
# 路4B 双流路由 + /确认 窗口
# ---------------------------------------------------------------------------

def cmd_forge(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/锻造 主入口（路4A 原子流程 + 路4B 双流路由 + 批4 路4C 参数词法 P-01~06）。

    参数提取（批4 路4C）：用 parsed.tokens[1:]（跳过指令名）而非 args——解析器对含
    ■/非法字符的 token 设 error 并丢出 args，但保留在 tokens（探针实证）→ 词法层
    （parse_forge_target）能拿到完整原文做 P-02 字符集 / P-04 ■ 判定；多词（含空格）
    → P-01 参数错误；剥离「预览」子词后单参 → parse_forge_target 全流程（P-01~06）。

    双流路由（2c2b §3.1 / TC-09~13）：
      - 显式「预览」参数（parsed.fixed_subword=预览 或 token 含 预览）→ 预览流 2 步；
      - 无「预览」参数 且 straight_forge=true（缺省）→ 直锻 1 步（原子成功）；
      - 无「预览」参数 且 straight_forge=false（深度模式）→ 强制预览流（前台无直锻入口）。
      批量 *N（P-05）：qty>1 随双流路由进 forge_atomic（直锻批量 N 次；预览批量单次）。

    GU-01 系统注册 / GU-02 参数解析（名禁空格）由 forge_atomic 承载；无节点参数 →
    TPL-12（对齐 shop cmd_buy 缺参模板）。
    """
    args = list(getattr(parsed, "args", None) or [])
    raw_tokens = list(getattr(parsed, "tokens", None) or [])
    # 目标词法输入：tokens 跳过指令名（含解析器 error 仍保留的 ■/非法字符 token）；
    # 无 tokens 兜底用 args（直测 parse_command 均带 tokens；防御形态）
    body = raw_tokens[1:] if raw_tokens else args
    if not body and not args:
        return format_tpl12(_fragment(parsed))
    # 显式「预览」子词：fixed_subword 或 token/args 中的「预览」标记（P-05 顺序兼容 `预览 *N`）
    fixed = getattr(parsed, "fixed_subword", None)
    has_preview = fixed == PREVIEW_SUBWORD or PREVIEW_SUBWORD in body or PREVIEW_SUBWORD in args
    node_args = [t for t in body if t != PREVIEW_SUBWORD]
    # P-01 节点名禁空格：多参数拆分（`/锻造 炎剑 Ⅱ` → 两 token）→ 参数错误
    # （定稿 L232 语法约束，不匹配任何节点、不产生锻造）
    if len(node_args) > 1:
        return "参数错误：节点名不含空格"
    if not node_args:
        return format_tpl12(_fragment(parsed))
    fragment = node_args[0]

    # 参数词法 P-01~06（parse_forge_target 独立词法函数；P_UNKNOWN/P_AMBIGUOUS 含歧义候选）
    res = parse_forge_target(fragment, eng=_engine(ctx))
    if not res.get("ok"):
        return res.get("message") or format_tpl12(_fragment(parsed))
    key = res.get("key") or ""
    qty = int(res.get("qty") or 1)
    if not key:
        return format_tpl12(_fragment(parsed))

    # 双流路由：预览参数不依赖开关（3.1 双流并存）；straight_forge=false → 强制预览
    if not has_preview and _straight_forge(ctx):
        return forge_atomic(ctx, key, preview=False, qty=qty)  # 直锻 1 步 / 批量 N 次（TC-09）
    return forge_atomic(ctx, key, preview=True, qty=qty)  # 预览流（TC-10/13）


def cmd_confirm(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/确认（2c2b §3.3 / TC-12~14）：预览 → /确认 一次性窗口终态。

    流程：
      ① 无进行中预览（qid 无窗 / 窗已超时作废）→ 拒绝「当前无可确认的锻造预览」
         （TC-14；无锻造、无扣款、无经验）；
      ② 有未过期窗 → 取 node_id，作废窗口（一次性），重跑 GU-03~06 守卫再扣素材发经验
         （复用 forge_atomic 执行路径）→ `✅ <节点> 锻造完成！`（TC-12）；
      ③ 失败（确认窗期间素材/前置/等级变化）→ 失败模板（失败零副作用，§1.3）。

    边界：本确认窗为超短期一次性引导，非框架 3.18 会话（不持久化、不可跨指令续接，
    L239）；窗口仅存在于单条指令→下一条指令之间。
    """
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    qid = _qid_of(ctx)
    if qid is None:
        return "当前无可确认的锻造预览"
    window = ctx.get(PREVIEW_WINDOW_KEY)
    if not isinstance(window, MutableMapping):
        return "当前无可确认的锻造预览"
    entry = window.get(qid)
    if not isinstance(entry, Mapping):
        return "当前无可确认的锻造预览"
    if _window_expired(ctx, entry):
        window.pop(qid, None)  # 超时 → 上下文作废（无锻造无扣款无经验，TC-11）
        return "预览已过期，请重新 /锻造 <节点> 预览"
    node_id = entry.get("node_id")
    window.pop(qid, None)  # 一次性：取走即作废（成功或失败均不再可确认）

    if not isinstance(node_id, str) or not node_id:
        return "当前无可确认的锻造预览"
    return forge_atomic(ctx, node_id, preview=False)  # 复用原子执行（重跑守卫再扣素材发经验）


def _join_node_args(args: List[str]) -> str:
    """节点名多参数拼接（P-01：`/锻造 炎剑 Ⅱ` → args=[炎剑, Ⅱ] → 拼接 `炎剑Ⅱ`）。

    非「预览」子词的多参数按紧凑拼接（节点名无空格，args 拆分来自空格输入）；
    拼接后仍含空格 → 由调用方 P-01 校验拒绝（参数错误）。"""
    return "".join(str(a) for a in args)


def _target_of(parsed: Any) -> str:
    """节点名剥离（兼容保留：批4 路4C 后 cmd_forge 改走 parse_forge_target，本函数不再被调用）。

    语义（对齐 alchemy _target_of）：解析器契约 + 紧凑 `+` 连接符收敛 + `*N` 剥离——
    `/锻造 炎剑Ⅱ*2` → args=["炎剑Ⅱ*2"] → 目标 "炎剑Ⅱ"（P-05 数量）。保留供外部兼容，
    不消费 qty（qty 消费归 parse_forge_target → forge_atomic 批量）。
    """
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return ""
    t = str(args[0])
    if t.startswith("+"):
        t = t[1:]
    if "*" in t:
        t = t.split("*", 1)[0]
    return t.strip()


# ---------------------------------------------------------------------------
# 批5 路5B：/图纸 标注段（✓/✅/失效标注 + 持有进度段接线；供路5A 主链/分支/持有进度段调用）
#   依据：docs/细化/细化_2c2b_锻造流程契约.md §2.2（当前持有段）/ §2.3（✓ 标注规则：
#   已锻＝✓态、素材满额＝✓态）/ §2.4（失效标注：红名「已失效：物品已删除」）+ 定稿 §4
#   （装备派生树）。——分工：主链/分支渲染归路5A；本段只提供 行尾标注
#   （forge_node_suffix）+ 持有进度段（forge_progress_segment，progress_line 接线
#   forged_prefix_names 父链已锻名，✅ 后缀来源，批2 F-3）。
# ---------------------------------------------------------------------------

# 失效标注文案（2c2b §2.4 / 定稿 L296）：红名节点 /图纸 行尾追加「（已失效：物品已删除）」；
# 与 /锻造 拒绝文案「❌ 已失效：物品已删除」（批4-1 已落地）同源——本段只做 /图纸 侧行尾
# 追加，不改写批4 拒绝文案（F-12）。
FORGE_REDFLAG_SUFFIX: str = "（已失效：物品已删除）"
# ✓ 态标注（批2 F-1 / M5-10 emoji 纪律：✅ 渲染契约 ✓ 态，U+2713 非白名单不可用）
FORGE_DONE_MARK: str = "✅"


def forge_node_suffix(player: object, node_id: str, node: object) -> str:
    """节点行尾标注（2c2b §2.3/§2.4；图纸行行尾统一标注，供路5A 主链/分支节点名后追加）。

    判定顺序（固定）：
      ① 红名/已删节点（is_redflagged，级联删除①）→ `（已失效：物品已删除）`
         ——失效标注优先，红名节点不参与 ✓/可锻造 判定（2c2b §2.4）；
      ② 已锻节点（player["forged"] 含 node_id，父链已锻集判定）→ `✅`（✓ 态渲染）；
      ③ 其它 → 空串（无标注）。
    player：玩家状态（Mapping，含 forged list/set/tuple；缺省空集兜底）。
    node：ForgeNode 或 raw dict（is_redflagged 双形态兼容）。纯函数确定性。
    """
    if is_redflagged(node):
        return FORGE_REDFLAG_SUFFIX
    forged = player.get("forged") if isinstance(player, Mapping) else None
    if isinstance(forged, (list, tuple, set, frozenset)) and node_id in forged:
        return FORGE_DONE_MARK
    return ""


def forge_forged_prefix_names(
    player: object, node_id: str, eng: ForgeTreeEngine
) -> List[str]:
    """父链已锻节点名列表（2c2b §2.3：前置/父链节点已锻 → 名后 ✓；✅ 后缀来源）。

    沿 eng.path_to_root(node_id)（根在前、含自身）取前置段（剔除目标自身），
    逐节点已锻判定（eng.already_forged，player["forged"] 含节点 id）→ 收集节点显示名
    （node.name，缺省回退节点 id）。返回序 = 根→近 父链序。
    供 forge_progress_segment → progress_line 的 forged_prefix_names 入参（批2 F-3）。
    """
    names: List[str] = []
    for nid in eng.path_to_root(node_id) or []:
        if nid == node_id:
            continue
        if eng.already_forged(player, nid):
            nd = eng.node(nid)
            names.append(nd.name if nd is not None else nid)
    return names


def forge_progress_segment(
    ctx: Mapping[str, object],
    player: object,
    node: object,
    eng: Optional[ForgeTreeEngine] = None,
) -> str:
    """持有进度段（2c2b §2.2 当前持有行 / PROG-05）：progress_line 接线。

    progress_line(material_holdings(ctx, node), forged_prefix_names=父链已锻名)——
    素材满额 ✅ / 已锻前置名 ✅ 均由 progress_line 渲染（批2 F-1/F-3）；本函数只做
    数据接线（目标节点 id 提取 → 父链已锻名列表 → 传入）。
    node：ForgeNode 或 raw dict（material_holdings 双形态，批2 F-6）；node id 缺失 →
    父链名列表空（只渲染素材段）。eng 缺省 → _engine(ctx)。纯函数确定性。
    """
    if eng is None:
        eng = _engine(ctx)
    node_id = getattr(node, "id", None)
    if not isinstance(node_id, str) or not node_id:
        node_id = node.get("id") if isinstance(node, Mapping) else None
        node_id = node_id if isinstance(node_id, str) and node_id else None
    prefixes = forge_forged_prefix_names(player, node_id, eng) if node_id else []
    return progress_line(material_holdings(ctx, node), forged_prefix_names=prefixes)


# ---------------------------------------------------------------------------
# 批5 路5A：/图纸 主链+分支+持有进度渲染（cmd_blueprint）
#   依据：细化_2c2b §二 2.2（主链全链/分支行/持有进度段）+ §2.1（无门槛：0 级玩家可用）/
#         §2.3（✓ 标注规则：已锻/素材满额 → 持有段 progress_line 渲染）+ §2.4（红名失效标注）
#         + 定稿 §4（装备派生树拓扑）。——主链/分支渲染归本路；行尾失效标注消费 5B
#         FORGE_REDFLAG_SUFFIX/forge_node_suffix（统一文案，不重复实现）；持有进度段消费
#         5B forge_progress_segment（progress_line 接线）；分支折叠复用 forge_sp.sp_locked
#         （SP-F1 unlock_branch_tree 未解锁 → 分支段折叠只显主干）。
# ---------------------------------------------------------------------------

def _blueprint_main_chain(eng: ForgeTreeEngine, node_id: str) -> List[str]:
    """主链全链节点 id（2c2b §2.2 主链段）：根 → … → 目标节点 → … → ■最终强化。

    沿 line_endpoint(node_id)（所在线终点，■最终强化）取 path_to_root 全链——目标在主线
    上（如 炎剑）时链延伸至 ■炎王剑（TC-15 全长）；目标是分支线终点（如 冰剑，final=true）
    时链止于其自身。line_endpoint 无 → 回落 path_to_root(node_id)。纯函数确定性。
    """
    endpoint = eng.line_endpoint(node_id)
    chain = eng.path_to_root(endpoint) if endpoint else eng.path_to_root(node_id)
    return list(chain) if chain else [node_id]


def _node_display_name(
    ctx: Mapping[str, Any], eng: ForgeTreeEngine, nid: str, *, is_terminal: bool
) -> str:
    """主链节点显示名（2c2b §2.2）：普通节点原名；终结点（■最终强化）■ 前缀 + 元素标注
    （（火））；红名节点行尾追加失效标注（§2.4，文案消费 5B FORGE_REDFLAG_SUFFIX）。

    终结点判定：链末节点（line_endpoint，final=true）；元素标注取 stats.element 中文
    （ELEMENT_NAMES_CN，与 4B _element_summary 同源）。纯函数确定性，不改写入参。
    """
    node = eng.node(nid)
    name = node.name if node is not None else nid
    if is_terminal:
        if not str(name).startswith("■"):
            name = "■" + str(name)
        stats = node.stats if node is not None else {}
        elem = stats.get("element") if isinstance(stats, Mapping) else None
        if isinstance(elem, str) and elem:
            cn = ELEMENT_NAMES_CN.get(elem, elem)
            name = f"{name}（{cn}）"
    if node is not None and is_redflagged(node):
        name = f"{name}{FORGE_REDFLAG_SUFFIX}"
    return name


def _branch_key_material(ctx: Mapping[str, Any], node: object) -> str:
    """分支关键素材名（2c2b §2.2 分支行：`<名> ← <关键素材>` = 该分支首段素材行 item 名）。

    node 为 ForgeNode 或 raw dict（materials 行文件序首行 item id → _item_name）；无素材
    → 空串。纯函数确定性。
    """
    raw = getattr(node, "raw", None)
    if not isinstance(raw, Mapping):
        raw = node if isinstance(node, Mapping) else {}
    mats = raw.get("materials")
    if isinstance(mats, list):
        for m in mats:
            if isinstance(m, Mapping):
                iid = m.get("item")
                if isinstance(iid, str) and iid:
                    return _item_name(ctx, iid)
    return ""


def _blueprint_branch_lines(
    ctx: Mapping[str, Any],
    eng: ForgeTreeEngine,
    player: object,
    chain: List[str],
) -> List[str]:
    """分支行（2c2b §2.2 分支段 + §2.1「从该节点向两端展开全链」）：主链上各节点可转出的
    其他线（children_of 中非主线子 = branch 标注子，2c2a N-07），格式
    `├─ 分支：<分支名> ← <关键素材>`（首 N-1 行 ├─、末行 └─）。

    branch 标注子按主链序聚合（目标节点及主链沿途各节点的非主线子，去重——同一分支子节点
    只有一个父节点故天然不重）：查询 炎剑Ⅱ 直接命中其 冰剑/雷剑 分支；查询 炎王剑（主线
    途经 炎剑Ⅱ）同样聚合出 冰剑/雷剑（对齐 §2.2 模板「从该节点向两端展开全链」）。
    SP-F1（unlock_branch_tree）未解锁（sp_locked=True，forge_sp）→ 分支段折叠只显主干
    （返回空列表，2c2b §4.3）；分支节点红名 → 行尾追加失效标注（§2.4）。纯函数确定性。
    """
    if sp_locked(player, "unlock_branch_tree"):
        return []
    branch_ids: List[str] = []
    seen: set = set()
    for nid in chain:
        for c in eng.children_of(nid):
            if c in set(eng.branch_of(nid)) and c not in seen:
                seen.add(c)
                branch_ids.append(c)
    lines: List[str] = []
    for i, cid in enumerate(branch_ids):
        cnode = eng.node(cid)
        cname = cnode.name if cnode is not None else cid
        mat = _branch_key_material(ctx, cnode) if cnode is not None else ""
        seg = f"{cname} ← {mat}"
        if cnode is not None and is_redflagged(cnode):
            seg += FORGE_REDFLAG_SUFFIX
        prefix = "└─" if i == len(branch_ids) - 1 else "├─"
        lines.append(f"{prefix} 分支：{seg}")
    return lines


def cmd_blueprint(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/图纸 主入口（批5 路5A：主链+分支+持有进度渲染，2c2b §二 + 定稿 §4）。

    流程：
      ① 参数提取（对齐 cmd_forge：tokens[1:] 优先，args 兜底）；空参 → TPL-12；
         多参（节点名含空格，P-01）→ 参数错误；
      ② 词法+匹配（复用 parse_forge_target：P-01~06；未知节点 → TC-19 空态
         `未找到「<名>」相关锻造链`；歧义/词法错误 → 复用解析 message）；
      ③ 主链渲染（_blueprint_main_chain + _node_display_name：根 → … → ■最终强化，
         终结点 ■ + 元素标注 + 红名失效标注）；
      ④ 分支行（SP-F1 未解锁 → 折叠只显主干）；
      ⑤ 持有进度段（消费 5B forge_progress_segment → progress_line，`当前持有：…`）。

    无铸造等级门槛（§2.1「无」，0 级玩家即可看全链）；不覆盖既有确认窗（纯读渲染，3.3）。
    """
    args = list(getattr(parsed, "args", None) or [])
    raw_tokens = list(getattr(parsed, "tokens", None) or [])
    body = raw_tokens[1:] if raw_tokens else args
    if not body:
        return format_tpl12(_fragment(parsed))
    if len(body) > 1:
        return "参数错误：节点名不含空格"
    fragment = body[0]

    eng = _engine(ctx)
    if not eng.load_trees():
        return "❌ 锻造系统未启用（内容包 forge.json 未注册）"

    res = parse_forge_target(fragment, eng=eng)
    if not res.get("ok"):
        # 未知节点 → /图纸 空态（TC-19：未找到「<名>」相关锻造链）；歧义/词法 → 解析 message
        if res.get("error_code") == ERR_P_UNKNOWN:
            return f"未找到「{fragment}」相关锻造链"
        return res.get("message") or format_tpl12(_fragment(parsed))
    key = res.get("key") or ""
    if not key:
        return format_tpl12(_fragment(parsed))
    return _render_blueprint(ctx, key)


def _render_blueprint(ctx: MutableMapping[str, Any], key: str) -> str:
    """主链+分支+持有进度 全链渲染（2c2b §2.2 输出结构 + §2.1 匹配）。

    输出形态（无 📖 降级纯文本，对齐 F-1/emoji 纪律）：
      `<目标节点名>派生链：`
      `<主链> → … → ■<终结点>（<元素>）`     ← 根在前、终结点 ■ + 属性标注
      `├─ 分支：<分支名> ← <关键素材>`         ← SP-F1 解锁才显示（未解锁折叠）
      `当前持有：…`                            ← 5B forge_progress_segment（progress_line）
    """
    eng = _engine(ctx)
    res = eng.resolve_node(key)
    if not res.get("ok"):
        return f"未找到「{key}」相关锻造链"
    node = res.get("node")
    node_id = res.get("node_id")
    if node is None or not isinstance(node_id, str):
        return f"未找到「{key}」相关锻造链"
    player = _player_of(ctx)

    chain = _blueprint_main_chain(eng, node_id)
    segs: List[str] = []
    for i, nid in enumerate(chain):
        segs.append(_node_display_name(ctx, eng, nid, is_terminal=(i == len(chain) - 1)))
    main_line = " → ".join(segs)

    target_name = node.name if hasattr(node, "name") and node.name else node_id
    title = f"{str(target_name).lstrip('■')}派生链："

    lines: List[str] = [title, main_line]
    lines.extend(_blueprint_branch_lines(ctx, eng, player, chain))
    lines.append(forge_progress_segment(ctx, player, node, eng))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 批5 路5C：/锻造树 全树可锻装备分页视图（cmd_forge_tree）
#   依据：细化_2c2b §5.3（/锻造树（无参）查看当前可锻装备树（分页），L234）+ 列表模板统一
#         （core/message_format/list_render：5 条/页 + CakeGame 尾段，2026-08-27 用户拍板；
#          /背包 同款 render_cake_tail 当前页 + Tip 尾行）
#   —— 行格式：`N. 装备名（等级/档位） 可锻状态`；终结点 ■（final_of，2c2a §2.2）；已锻 ✅。
#   —— 可锻状态（对齐 GU-04/06 判定，forge_tree）：已锻 → ✅；前置未锻 → 需前置；
#      等级不足 → 需等级；其余 → 可锻。未锻造节点按派生树文件序展示（eng.nodes() 文件序）。
#   —— 分页：`/锻造树`（第 1 页）`/锻造树 2`（第 2 页）；越界页 → 空态提示 TREE_EMPTY_PAGE。
# ---------------------------------------------------------------------------

def _tree_row_line(
    ctx: Mapping[str, Any],
    eng: ForgeTreeEngine,
    player: object,
    nid: str,
    index: int,
    finals: set,
) -> str:
    """锻造树单行（批5 路5C）：`{N}. {装备名}（{等级}级/{档位}） {可锻状态}`。

    装备名：node.name（缺省回退节点 id）；终结点（final_of 集合）→ ■ 前缀（2c2a §2.2
    ■最终强化显示标记，P-04）；档位名 = forge_job._tier_name(node.level)（对齐 _req_text
    口径，等级越界钳末档）。可锻状态（对齐 GU-04/06）：已锻 → ✅（FORGE_DONE_MARK）；
    前置未锻（parent_forged=False）→ 需前置；等级不足（node_level_met=False）→ 需等级；
    其余 → 可锻。纯函数确定性，不改写入参。
    """
    node = eng.node(nid)
    name = node.name if node is not None else nid
    if not isinstance(name, str) or not name:
        name = nid
    if nid in finals and not name.startswith("■"):
        name = "■" + name
    level = node.level if node is not None else 1
    if not isinstance(level, int) or isinstance(level, bool) or level <= 0:
        level = 1
    seg = f"{name}（{level}级/{_tier_name(level)}）"
    if eng.already_forged(player, nid):
        status = FORGE_DONE_MARK
    elif not eng.parent_forged(player, nid):
        status = "需前置"
    elif not eng.node_level_met(player, nid):
        status = "需等级"
    else:
        status = "可锻"
    return render_item_line(index, seg, status)


def cmd_forge_tree(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/锻造树 主入口（批5 路5C：全树可锻装备分页视图，细化 2c2b §5.3 / L234）。

    参数：`/锻造树`（第 1 页）`/锻造树 2`（第 2 页）；越界页 → 空态提示
    TREE_EMPTY_PAGE（`该页暂无锻造装备（/锻造树 共 N 页）`）；非法页码
    （0/负数/非数字）→ TPL-12（对齐列表模板页码报错口径，3d §2.2）。

    流程：
      ① 页码解析（body = tokens[1:] 或 args；无参 → 第 1 页）；
      ② 引擎加载（load_trees 空 → `❌ 锻造系统未启用（内容包 forge.json 未注册）`）；
      ③ 全部节点按派生树文件序（eng.nodes()）→ 终结点集合（final_of 跨树并集）；
      ④ TREE_PAGE_SIZE（5）条/页切片 + 单行渲染（等级/档位 + 可锻状态）；
      ⑤ 尾段 render_cake_tail（当前页：X/Y + Tip 尾行，列表模板统一）。

    无铸造等级门槛（§5.3：无，0 级玩家即可查看可锻装备树）；纯读渲染不覆盖既有确认窗。
    """
    args = list(getattr(parsed, "args", None) or [])
    raw_tokens = list(getattr(parsed, "tokens", None) or [])
    body = raw_tokens[1:] if raw_tokens else args
    page = 1
    if body:
        p = parse_int(str(body[0]))
        if p is None or p < 1:
            return format_tpl12(_fragment(parsed))
        page = p

    eng = _engine(ctx)
    if not eng.load_trees():
        return "❌ 锻造系统未启用（内容包 forge.json 未注册）"

    nids = [n.id for n in eng.nodes() if n.id]
    total = len(nids)
    total_pages = (total + TREE_PAGE_SIZE - 1) // TREE_PAGE_SIZE if total else 1
    if page > total_pages:
        return TREE_EMPTY_PAGE.format(total_pages=total_pages)

    finals: set = set()
    for t in eng.load_trees():
        finals.update(eng.final_of(t))
    player = _player_of(ctx)

    start = (page - 1) * TREE_PAGE_SIZE
    page_nids = nids[start:start + TREE_PAGE_SIZE]
    lines = [
        _tree_row_line(ctx, eng, player, nid, start + i + 1, finals)
        for i, nid in enumerate(page_nids)
    ]
    tail = render_cake_tail(page, total_pages, tip=TREE_TAIL_TIP)
    return "\n".join(lines + [tail])


# ---------------------------------------------------------------------------
# 装配（Router 注册；make_context 由装配层注入，对齐 shop/alchemy 壳模式）
# ---------------------------------------------------------------------------

def register_forge_commands(
    router: Any,
    *,
    make_context: Optional[Callable[[Any], dict]] = None,
) -> Any:
    """把 /锻造 /确认 /图纸 /锻造树 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    :param make_context: ParsedCommand → 玩家 ctx dict（含 forge/items/settings/player/
        inventory/qid/now 等，见 _forge_atomic ctx 契约）。None 时 handler 调用抛
        RuntimeError（【待接线】装配层注入，对齐 shop_commands 口径）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "forge_commands.register_forge_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _forge(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_forge(parsed, injected)
        return cmd_forge(parsed, _ctx(parsed))

    def _confirm(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_confirm(parsed, injected)
        return cmd_confirm(parsed, _ctx(parsed))

    def _blueprint(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_blueprint(parsed, injected)
        return cmd_blueprint(parsed, _ctx(parsed))

    def _tree(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_forge_tree(parsed, injected)
        return cmd_forge_tree(parsed, _ctx(parsed))

    # /锻造（白名单已含「锻造」）；/确认（白名单已含「确认」，2c2b §5.3 登记指令）
    # /图纸（批5 路5A：CommandSpec whitelisted=True 白名单标记；2c2b §5.3 登记指令）
    # /锻造树（批5 路5C：CommandSpec whitelisted=True 白名单标记；2c2b §5.3 登记指令，
    #   L234「查看当前可锻装备树（分页）」）——四指令全部注册（路由收口）
    router.register(CommandSpec(FORGE_CMD, handler=_forge))
    router.register(CommandSpec(CONFIRM_CMD, handler=_confirm))
    router.register(CommandSpec(BLUEPRINT_CMD, handler=_blueprint))
    router.register(CommandSpec(TREE_CMD, handler=_tree))
    return router
