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
- 断言见 tests/unit/test_content.py::test_legal_pack_full_green（细化_3e#TC-30 / 3a#TC-09/22）
  与 tests/unit/test_enemies_schema.py（细化_1e §⑥ TC-01~14）
  与 tests/unit/test_content.py::test_legal_pack_m4_interaction_modules（M4 批次6 集成断言）。
