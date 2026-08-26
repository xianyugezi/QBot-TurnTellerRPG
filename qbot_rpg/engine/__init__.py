"""engine 层 —— M3 地图里程碑新增：时间/天气引擎（细化_2a4a / 细化_2a4c / m3_shared_contract §5）。

分层（细化_3a_架构分层契约 §2.1 同口径）：平台无关纯逻辑层，零 NoneBot import。
本批次（M31 路C 骨架）交付 qbot_rpg/engine/worldtime.py：时间引擎三周期懒计算纯函数
（IF01~IF07 骨架）+ time_cycle 段校验；后续批次在 worldtime.py 内扩展 IF08~IF12 与天气引擎。
"""