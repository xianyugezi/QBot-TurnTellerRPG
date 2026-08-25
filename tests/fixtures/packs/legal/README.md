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
  - `formula.json`：damage_base / heal_rate（无黑名单词，合法公式）
- 断言见 tests/unit/test_content.py::test_legal_pack_full_green（细化_3e#TC-30 / 3a#TC-09/22）
  与 tests/unit/test_enemies_schema.py（细化_1e §⑥ TC-01~14）。
