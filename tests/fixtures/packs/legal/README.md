# 合法包 legal

依据：细化_5d_测试体系总纲 §5.1（TC-5d-13，四件套之一）/ 细化_3e §5.2 / 细化_3e TC-30 / 细化_1e（M2 A3 路）。

- 目的：`load_pack` 全绿基线 —— validator 全绿（0 errors，0 warnings）+ registry 全量注册且 ID 唯一。
- 破坏点：**无**（故意构造为完全合法的对照基线）。
- 内容（manifest 声明 9 模块，与磁盘文件一一对应，无缺失无未声明）：
  - `effects.json`：heal_small / power_slash / rage_up（rage_up.apply_status 引用 statuses.berserk）
  - `statuses.json`：regen（effects→heal_small / on_tick→heal_small）、berserk
  - `marks.json`：fire_mark / curse_mark（type=mark）
  - `items.json`：potion / hi_potion（effects 引用 effects 家族）
  - `equipment.json`：iron_sword / iron_shield（slot=weapon/shield；excludes 单向互斥无环）
  - `action.json`：怪物行动库 7 招（claw_swipe/tail_sweep/rock_roll/hard_body/roar/fireball/doomsday_breath），
    含 ActionCore 字段 + AI 字段（weight/intent/cooldown/hungry/condition/tags/armor/interrupt/charge_*/preview）。
    注：入池行动的 `probability` 用等价正值 0.5（细化_1e S1「写其他正值等价 1」）——0/1 会触发 Y-2
    概率极值黄提示（F_PROBABILITY 旗标误伤 0/1 开关，已登记契约偏差）；锚点行动缺省（默认 0）。
    池入池语义的规范表达在 enemies.actions[].probability。
  - `enemies.json`：八段合法怪 4 只（细化_1e §① 18 顶层字段）——
    rock_weasel 岩皮鼬（normal，TC-01 形状）/ stone_skink 石甲蜥（elite）/ ember_drake 烬火龙（boss，
    含 chains 顶层连招 + chain_ref）/ training_dummy 练兵木桩（tier:training + type:dummy，木桩特例，
    未配置 drops/lore/pv/actions → 零黄提示）。全部过 A2 校验器（R1-R15）无红拦无黄提示。
  - `stats.json`：九预置键空间（resource: hp/mp；combat: str/int/con/spr/foc/agi/lck）
  - `formula.json`：damage_base / heal_rate（无黑名单词，合法公式）+ F-FIX-01~27 段级参数
    （damage/hit/crit/block/defense/weakness/type_affinity/derived/monster_def_rate/elements，
    细化_1a §2.1 默认值；M6 批6·路A FIX-1 —— 读取器 tests/conftest.py formula_params，
    详细化_M6 测试体系强化 D6 §三 F-FIX-01~27）
  - `npc.json`（M4 批次6 · 校验器接线，依据：m4_shared_contract §3.1 + 细化_2b1 validate_npcs）：
    4 只 NPC（merchant/quest_giver/dealer/narrator），map 挂点引用既有 maps（rubble_field 等）、
    shop_refs 引用 shop.village_shop、quests 引用 quest.q_potion_supply、dealer.pool 非空（无孤寂卡）、
    对话树 ≤ max_dialog_depth 默认 2 → 零红拦零黄
  - `shop.json`（m4_shared_contract §3.2 + 细化_2b3 validate_shops）：2 家 normal 店（无 Y-8 未使用），
    items 引用既有 items（potion/hi_potion），价格与 items 基准价一致（无 Y-7 同物不同价）、
    stock≥5（无 Y-2）、currency=coins 注册（DEFAULT_CURRENCY_IDS）→ 零红拦零黄
  - `quest.json`（m4_shared_contract §3.3 + 细化_2b4 validate_quests）：q_potion_supply，
    conditions 三原语合法（item_count/ge）、reward 引用 items.potion、zone 引用 maps.rubble_field、
    npc.id 引用 npc.quest_giver_ling → 零红拦零黄
  - `checkin.json`（m4_shared_contract §3.4 + 细化_2b5 validate_checkins）：三表 loop/monthly/activity，
    loop 配 cycle_days=7（无默认补全黄）、streak.days≤cycle（无 TC-06 黄）、activity period.start/end
    必填齐全、无 [签到:*] 条件键（无跨模块引用黄）→ 零红拦零黄
  - `settings.json`（M8 批0C 新增）：currencies 三币（coins/diamond/gem）+ death_penalty +
    alchemy 段（照 m8_contract_数据与校验 §五 全字段默认值：mode=full / quality_tiers / quality_coef /
    chain_map / pp_cost / pp_refresh / energy_enabled=false / energy_max 7 档 / energy_regen_sec /
    energy_regen_sec_safe / decompose_rate 6 档 / catalyst_unlock_tier=expert / catalyst_consume /
    gem{分解,复制,成品合成,配方合成,特性合成,珠升阶,复制额外,decompose_formula} / gem_diminish /
    synth_exp / sp_per_level / sp_panel 4 项 / 战斗道具 / 战斗即时调合 / max_qty=2147483647 /
    job_tier_map）→ 引用全部指向本包真实 ID，ALC-01~24 全绿
  - `traits.json`（M8 批0C 新增）：6 条特性（斩击强化/回复强化/狂暴强化/铁壁庇护等），rarity 覆盖
    normal/super，group 互斥组 slash_boost（3 成员）、rage_boost，repeatable 有 true 有 false，
    source 覆盖 素材/成品/金色素材，effects 引用本包 effects 家族（heal_small/power_slash/rage_up）→ TRT-01~09 全绿
  - `recipe.json`（M8 批0C 新增）：9 条配方 —— craft 3（含 master_only 深度配方 rcp_deep_blade，
    synth_allowed=false；rcp_slash_bomb 带 element_req/evolve_to/catalyst）、combine 1（3:1 素材合成）、
    upgrade 5（珠升阶×2 gem10 / 成品合成 gem10 / 配方合成 combine_from gem5 / 特性合成 gem20）→
    REC-01~16 全绿（进化线无环）
  - `proficiency.json`（M8 批0C 新增）：id=alchemy，tier_names 7 级、job_rank_levels 7 阈值、exp_sources、
    sp_per_level=1、sp_panel 4 项、energy{enabled:false}、job_tier_map、titles（contest/achievement，无手写 king）→
    PRF-01~10 全绿
  - `slots.json`（M8 批0C 新增）：iron_sword（槽级 1/2/3）+ iron_shield（槽级 1/2），equip_id 引用本包
    equipment.json 真实 ID
- M8 扩展后 items.json 追加：装饰珠 4（quality common/uncommon/rare）、触媒 1、炼金材料 2、炼金成品 4
  （quality common→legendary），全部引用本包 traits.json 真实 ID；原 potion/hi_potion 未改动。
- 断言见 tests/unit/test_content.py::test_legal_pack_full_green（细化_3e#TC-30 / 3a#TC-09/22）
  与 tests/unit/test_enemies_schema.py（细化_1e §⑥ TC-01~14）
  与 tests/unit/test_content.py::test_legal_pack_m4_interaction_modules（M4 批次6 集成断言）。
