# -*- coding: utf-8 -*-
"""
RiskRuleEngine 规则方法单元测试
"""
import pytest
from datetime import datetime, date


# ==================== calc_safety_awareness ====================

class TestSafetyAwareness:
    """安全意识评分测试"""

    def test_empty_records(self, engine):
        assert engine.calc_safety_awareness({}) == 0
        assert engine.calc_safety_awareness(None) == 0

    def test_A_level(self, engine):
        assert engine.calc_safety_awareness({'A': 1}) == 6
        assert engine.calc_safety_awareness({'A': 5, 'B': 10}) == 6

    def test_B_level(self, engine):
        assert engine.calc_safety_awareness({'B': 1}) == 5
        assert engine.calc_safety_awareness({'B': 3, 'C': 2}) == 5

    def test_C_level(self, engine):
        assert engine.calc_safety_awareness({'C': 1}) == 3
        assert engine.calc_safety_awareness({'C': 100}) == 3

    def test_D_level(self, engine):
        # D 类 >= 3 次才计分
        assert engine.calc_safety_awareness({'D': 2}) == 0
        assert engine.calc_safety_awareness({'D': 3}) == 2
        assert engine.calc_safety_awareness({'D': 10}) == 2

    def test_unknown_key(self, engine):
        assert engine.calc_safety_awareness({'X': 5}) == 0

    def test_person_awareness(self, engine):
        peccancy_dict = {'user_001': {'A': 1}, 'user_002': {'B': 3}}
        assert engine.calc_person_awareness(peccancy_dict, 'user_001') == 6
        assert engine.calc_person_awareness(peccancy_dict, 'user_002') == 5
        assert engine.calc_person_awareness(peccancy_dict, 'user_999') == 0


# ==================== calc_work_count ====================

class TestWorkCount:
    """作业总人数评分测试"""

    def test_zero_or_empty(self, engine):
        assert engine.calc_work_count(0) == 0
        assert engine.calc_work_count(None) == 0
        assert engine.calc_work_count('') == 0

    def test_string_input(self, engine):
        assert engine.calc_work_count('3') == 0  # < 5
        assert engine.calc_work_count('8') == 3
        assert engine.calc_work_count('50') == 15

    def test_invalid_input(self, engine):
        assert engine.calc_work_count('abc') == 0
        assert engine.calc_work_count('') == 0

    def test_boundaries(self, engine):
        """边界值测试"""
        assert engine.calc_work_count(4) == 0
        assert engine.calc_work_count(5) == 1
        assert engine.calc_work_count(7) == 1
        assert engine.calc_work_count(8) == 3
        assert engine.calc_work_count(15) == 3
        assert engine.calc_work_count(16) == 5
        assert engine.calc_work_count(23) == 5
        assert engine.calc_work_count(24) == 8
        assert engine.calc_work_count(49) == 8
        assert engine.calc_work_count(50) == 15
        assert engine.calc_work_count(100) == 15


# ==================== calc_personnel_nature ====================

class TestPersonnelNature:
    """人员性质评分测试"""

    def test_ziben_danwei(self, engine):
        desc, score = engine.calc_personnel_nature('本单位')
        assert desc == '本单位-系统内人员'
        assert score == 0

    def test_zongbao(self, engine):
        desc, score = engine.calc_personnel_nature('总包单位作业')
        assert desc == '总包单位作业'
        assert score == 3

    def test_float_one(self, engine):
        desc, score = engine.calc_personnel_nature('1.0')
        assert desc == '本单位-系统内人员'
        assert score == 0

    def test_other_float(self, engine):
        desc, score = engine.calc_personnel_nature('2.0')
        assert desc == '外单位-系统外人员'
        assert score == 5

    def test_unknown(self, engine):
        desc, score = engine.calc_personnel_nature('未知类型')
        assert desc == '未知人员性质'
        assert score == 0

    def test_numeric_string(self, engine):
        desc, score = engine.calc_personnel_nature('0.5')
        assert desc == '外单位-系统外人员'
        assert score == 5


# ==================== calc_same_type_score ====================

class TestSameTypeScore:
    """同类型作业经验评分测试"""

    def test_zero(self, engine):
        assert engine.calc_same_type_score(0) == 0

    def test_one(self, engine):
        assert engine.calc_same_type_score(1) == 6

    def test_two(self, engine):
        assert engine.calc_same_type_score(2) == 5

    def test_three_and_four(self, engine):
        assert engine.calc_same_type_score(3) == 3
        assert engine.calc_same_type_score(4) == 3

    def test_five_plus(self, engine):
        assert engine.calc_same_type_score(5) == 2
        assert engine.calc_same_type_score(100) == 2


# ==================== calc_work_time_period_score ====================

class TestWorkTimePeriodScore:
    """作业时段评分测试"""

    def test_normal(self, engine):
        assert engine.calc_work_time_period_score('正常时段作业') == 0

    def test_indoor_night(self, engine):
        assert engine.calc_work_time_period_score('室内夜间作业(0点-次日6:00)') == 20

    def test_outdoor_night(self, engine):
        assert engine.calc_work_time_period_score('站外线路夜间作业(19:00-次日6:00)') == 20

    def test_holiday(self, engine):
        assert engine.calc_work_time_period_score('元旦、春节、清明、五一、端午、中秋、国庆法定节日期间作业') == 30

    def test_unknown(self, engine):
        assert engine.calc_work_time_period_score('未知时段') == 0
        assert engine.calc_work_time_period_score('') == 0


# ==================== calc_plan_nature_score ====================

class TestPlanNatureScore:
    """计划性质评分测试"""

    def test_planned(self, engine):
        assert engine.calc_plan_nature_score('计划性作业') == 0

    def test_one_day_advance(self, engine):
        assert engine.calc_plan_nature_score('提前一日制定的临时性作业任务') == 10

    def test_same_day(self, engine):
        assert engine.calc_plan_nature_score('当日制定的临时性作业任务') == 20

    def test_unknown(self, engine):
        assert engine.calc_plan_nature_score('未知') == 0
        assert engine.calc_plan_nature_score('') == 0


# ==================== get_risk_level ====================

class TestRiskLevel:
    """风险等级判定测试"""

    def test_acceptable(self, engine):
        assert engine.get_risk_level(0) == '可接受'
        assert engine.get_risk_level(10) == '可接受'
        assert engine.get_risk_level(20) == '可接受'

    def test_low(self, engine):
        assert engine.get_risk_level(21) == '低'
        assert engine.get_risk_level(50) == '低'
        assert engine.get_risk_level(70) == '低'

    def test_medium(self, engine):
        assert engine.get_risk_level(71) == '中'
        assert engine.get_risk_level(150) == '中'
        assert engine.get_risk_level(200) == '中'

    def test_high(self, engine):
        assert engine.get_risk_level(201) == '高'
        assert engine.get_risk_level(300) == '高'
        assert engine.get_risk_level(400) == '高'

    def test_critical(self, engine):
        assert engine.get_risk_level(401) == '特高'
        assert engine.get_risk_level(999) == '特高'

    def test_negative(self, engine):
        assert engine.get_risk_level(-1) == '可接受'

    def test_float(self, engine):
        assert engine.get_risk_level(20.5) == '可接受'
        assert engine.get_risk_level(70.9) == '低'


# ==================== determine_plan_nature ====================

class TestDeterminePlanNature:
    """计划性质判定测试"""

    def test_planned(self, engine):
        start = datetime(2026, 6, 29, 8, 0, 0)
        release = datetime(2026, 6, 26, 10, 0, 0)  # 提前3天（>=2天即为计划性）
        assert engine.determine_plan_nature(start, release) == '计划性作业'

    def test_one_day_advance(self, engine):
        start = datetime(2026, 6, 29, 8, 0, 0)
        release = datetime(2026, 6, 27, 10, 0, 0)  # 提前1天多（>=1天但<2天）
        assert engine.determine_plan_nature(start, release) == '提前一日制定的临时性作业任务'

    def test_same_day(self, engine):
        start = datetime(2026, 6, 29, 8, 0, 0)
        release = datetime(2026, 6, 29, 6, 0, 0)  # 当天
        assert engine.determine_plan_nature(start, release) == '当日制定的临时性作业任务'

    def test_missing_data(self, engine):
        assert engine.determine_plan_nature(None, datetime(2026, 6, 27, 10, 0)) == '计划性作业'
        assert engine.determine_plan_nature(datetime(2026, 6, 29, 8, 0), None) == '计划性作业'
        assert engine.determine_plan_nature(None, None) == '计划性作业'


# ==================== determine_work_time_period ====================

class TestDetermineWorkTimePeriod:
    """作业时段判定测试"""

    def test_normal(self, engine):
        start = datetime(2026, 6, 29, 8, 0, 0)
        end = datetime(2026, 6, 29, 18, 0, 0)
        result = engine.determine_work_time_period(start, end, start, end)
        assert result == '正常时段作业'

    def test_cross_day(self, engine):
        """跨天作业"""
        start = datetime(2026, 6, 29, 8, 0, 0)
        end = datetime(2026, 6, 30, 18, 0, 0)
        result = engine.determine_work_time_period(start, end, start, end)
        assert result == '时间段超过一天'

    def test_indoor_night(self, engine):
        """室内夜间作业（0点-6点）"""
        plan_start = datetime(2026, 6, 29, 8, 0, 0)
        plan_end = datetime(2026, 6, 29, 18, 0, 0)
        actual_start = datetime(2026, 6, 29, 2, 0, 0)  # 凌晨2点
        actual_end = datetime(2026, 6, 29, 6, 0, 0)
        result = engine.determine_work_time_period(plan_start, plan_end, actual_start, actual_end)
        assert result == '室内夜间作业(0点-次日6:00)'

    def test_outdoor_night(self, engine):
        """站外线路夜间作业"""
        plan_start = datetime(2026, 6, 29, 8, 0, 0)
        plan_end = datetime(2026, 6, 29, 18, 0, 0)
        actual_start = datetime(2026, 6, 29, 20, 0, 0)  # 晚上8点
        actual_end = datetime(2026, 6, 29, 23, 0, 0)
        result = engine.determine_work_time_period(
            plan_start, plan_end, actual_start, actual_end,
            location_type='站外线路作业'
        )
        assert result == '站外线路夜间作业(19:00-次日6:00)'

    def test_missing_actual_times(self, engine):
        """缺少实际时间"""
        plan_start = datetime(2026, 6, 29, 8, 0, 0)
        plan_end = datetime(2026, 6, 29, 18, 0, 0)
        result = engine.determine_work_time_period(plan_start, plan_end, None, None)
        assert result == '正常时段作业'

    def test_outdoor_keyword_detection(self, engine):
        """通过关键词检测站外"""
        plan_start = datetime(2026, 6, 29, 8, 0, 0)
        plan_end = datetime(2026, 6, 29, 18, 0, 0)
        actual_start = datetime(2026, 6, 29, 20, 0, 0)
        actual_end = datetime(2026, 6, 29, 23, 0, 0)
        result = engine.determine_work_time_period(
            plan_start, plan_end, actual_start, actual_end,
            work_task='输电线路检修'
        )
        assert result == '站外线路夜间作业(19:00-次日6:00)'


# ==================== split_member_ids ====================

class TestSplitMemberIds:
    """成员ID分割测试"""

    def test_comma(self, engine):
        assert engine.split_member_ids('张三,李四,王五') == ['张三', '李四', '王五']

    def test_semicolon(self, engine):
        assert engine.split_member_ids('张三;李四;王五') == ['张三', '李四', '王五']

    def test_mixed_delimiters(self, engine):
        assert engine.split_member_ids('张三,李四;王五') == ['张三', '李四', '王五']

    def test_single(self, engine):
        assert engine.split_member_ids('张三') == ['张三']

    def test_empty(self, engine):
        assert engine.split_member_ids('') == []
        assert engine.split_member_ids(None) == []