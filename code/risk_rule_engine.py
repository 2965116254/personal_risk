# -*- coding: utf-8 -*-
"""
风险评估规则引擎
将所有评分规则（安全意识、作业人数、人员性质、作业地段、作业类型、作业时段等）
封装在一个类中，便于维护和扩展。
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import re
import datetime
import logging
from typing import Optional, Dict, Any, Tuple, List
from config_loader import get_holiday_check_enabled, get_bracket_filter_words
from ai_client import (
    evaluate_work_task_with_llm,
    evaluate_work_location_with_llm,
    is_chinese_name_with_llm,
    evaluate_location_type_with_llm,
)


# 括号内容过滤关键词（从配置读取，模块级缓存）
_bracket_filter_keywords = None


def _get_bracket_filter_keywords():
    global _bracket_filter_keywords
    if _bracket_filter_keywords is None:
        _bracket_filter_keywords = get_bracket_filter_words()
    return _bracket_filter_keywords


class RiskRuleEngine:
    """风险评估规则引擎，包含所有评分规则和工具方法"""

    # ==================== 评分映射表 ====================

    # 安全意识评分映射表
    AWARENESS_MAP = {
        '1年内累计1次及以上A类违章': 6,
        '1年内累计1次及以上B类违章': 5,
        '1年内累计1次及以上C类违章': 3,
        '1年内累计3次及以上D类违章': 2,
        '1年内0-2次D类违章': 0,
    }

    # 人员性质评分映射表
    PERSONNEL_NATURE_MAP = {
        '分包作业': 5,
        '总包单位作业': 3,
        '本单位': 0,
    }

    # 同类型作业次数评分规则
    EXPERIENCE_MAP = {
        '第一次承担该类作业': 6,
        '累计不足3次但不是第一次': 5,
        '累计不足5次但不小于3次': 3,
        '不满足上述要求，但累计5次及以上': 2,
        '1年内2次及以上或2年内5次及以上': 0,
    }

    # 法定节假日名称映射
    TARGET_HOLIDAYS = {
        "New Year's Day": "元旦",
        "Spring Festival": "春节",
        "Tomb-sweeping Day": "清明",
        "Labour Day": "五一",
        "Dragon Boat Festival": "端午",
        "Mid-autumn Festival": "中秋",
        "National Day": "国庆",
    }

    # 作业时段评分映射表
    WORK_TIME_PERIOD_MAP = {
        '正常时段作业': 0,
        '室内夜间作业(0点-次日6:00)': 20,
        '站外线路夜间作业(19:00-次日6:00)': 20,
        '元旦、春节、清明、五一、端午、中秋、国庆法定节日期间作业': 30,
    }

    # 计划性质评分映射表
    PLAN_NATURE_MAP = {
        '计划性作业': 0,
        '提前一日制定的临时性作业任务': 10,
        '当日制定的临时性作业任务': 20,
    }

    # 站外线路关键词
    OUTDOOR_KEYWORDS = ['站外', '线路', '输电', '配电架空', '电缆线路', '杆塔', '导地线', '绝缘子', '金具']

    def __init__(self):
        self._init_chinese_calendar()
        self._holiday_logged = False

    def _init_chinese_calendar(self):
        """初始化 chinese_calendar 库"""
        try:
            from chinese_calendar import is_holiday, get_holiday_detail
            self._calendar_available = True
            self._is_holiday_func = is_holiday
            self._get_holiday_detail_func = get_holiday_detail
        except ImportError:
            self._calendar_available = False
            self._is_holiday_func = None
            self._get_holiday_detail_func = None

    # ==================== 安全意识评分 ====================

    def calc_safety_awareness(self, peccancy_records: Dict[str, int]) -> int:
        """
        根据人员违章记录计算安全意识评分
        :param peccancy_records: {'A': count, 'B': count, ...}
        :return: 风险分值
        """
        if not peccancy_records:
            return 0
        if 'A' in peccancy_records:
            return 6
        if 'B' in peccancy_records:
            return 5
        if 'C' in peccancy_records:
            return 3
        if 'D' in peccancy_records:
            return 2 if peccancy_records['D'] >= 3 else 0
        return 0

    def calc_person_awareness(self, peccancy_dict: Dict[str, Dict], person_uid: str) -> int:
        """计算单个人员的安全意识得分"""
        return self.calc_safety_awareness(peccancy_dict.get(person_uid, {}))

    # ==================== 作业总人数评分 ====================

    def calc_work_count(self, count) -> int:
        """计算作业总人数评分"""
        if not count:
            return 0
        try:
            count = int(count)
        except (ValueError, TypeError):
            return 0
        if count >= 50:
            return 15
        if count >= 24:
            return 8
        if count >= 16:
            return 5
        if count >= 8:
            return 3
        if count >= 5:
            return 1
        return 0

    # ==================== 人员性质评分 ====================

    def calc_personnel_nature(self, task_main: str) -> Tuple[str, int]:
        """
        计算负责人的人员性质评分
        :param task_main: 作业主体（本单位/总包单位作业）
        :return: (人员性质描述, 风险分值)
        """
        if task_main == '本单位':
            return '本单位-系统内人员', 0
        if task_main == '总包单位作业':
            return '总包单位作业', 3
        try:
            task_main_float = float(task_main)
            if task_main_float == 1.0:
                return '本单位-系统内人员', 0
            return '外单位-系统外人员', 5
        except (ValueError, TypeError):
            pass
        return '未知人员性质', 0

    # ==================== 同类型作业经验评分 ====================

    def calc_same_type_score(self, count: int) -> int:
        """根据同类型作业次数计算评分"""
        if count == 0:
            return 0
        if count == 1:
            return 6
        if count < 3:
            return 5
        if count <= 4:
            return 3
        return 2

    # ==================== 作业时段评分 ====================

    def is_legal_holiday(self, input_date) -> Optional[str]:
        """
        判断是否为法定节假日（元旦、春节、清明、五一、端午、中秋、国庆）
        :return: 节日名称或 None
        """
        if not self._calendar_available:
            return None
        if isinstance(input_date, datetime.datetime):
            input_date = input_date.date()
        elif not isinstance(input_date, datetime.date):
            return None
        is_hol, holiday_name = self._get_holiday_detail_func(input_date)
        if is_hol and holiday_name in self.TARGET_HOLIDAYS:
            return self.TARGET_HOLIDAYS[holiday_name]
        return None

    def calc_work_time_period_score(self, time_period: str) -> int:
        """计算作业时段评分"""
        return self.WORK_TIME_PERIOD_MAP.get(time_period, 0)

    def determine_work_time_period(
        self,
        plan_start_time, plan_end_time,
        actual_start_time, actual_end_time,
        work_task: str = None,
        location_type: str = None,
    ) -> str:
        """
        根据作业计划信息判断作业时段类型
        :param location_type: 大模型判断的站内/站外结果
        :return: 作业时段类型名称
        """
        # 1. 判断是否为法定节假日（可通过配置开关控制）
        holiday_enabled = get_holiday_check_enabled()
        if not self._holiday_logged:
            logging.info(f"[法定节假日判断] 配置开关 holiday_check_enabled = {holiday_enabled}")
            self._holiday_logged = True
        if holiday_enabled and plan_start_time:
            holiday_name = self.is_legal_holiday(plan_start_time)
            if holiday_name:
                return '元旦、春节、清明、五一、端午、中秋、国庆法定节日期间作业'

        # 2. 判断是否跨天
        if plan_start_time and plan_end_time:
            if plan_start_time.date() != plan_end_time.date():
                return '时间段超过一天'
        else:
            return '时间段超过一天'

        # 3. 检查实际时间
        if not actual_start_time or not actual_end_time:
            return '正常时段作业'

        # 4. 判断站内/站外
        is_outdoor = False
        if location_type == '站外线路作业':
            is_outdoor = True
        elif work_task:
            for keyword in self.OUTDOOR_KEYWORDS:
                if keyword in work_task:
                    is_outdoor = True
                    break

        # 5. 判断夜间
        start_hour = actual_start_time.hour if hasattr(actual_start_time, 'hour') else 0
        end_hour = actual_end_time.hour if hasattr(actual_end_time, 'hour') else 0

        if is_outdoor:
            if (start_hour >= 19 or start_hour < 6) or (end_hour >= 19 or end_hour < 6):
                return '站外线路夜间作业(19:00-次日6:00)'
        else:
            if (0 <= start_hour < 6) or (0 <= end_hour < 6):
                return '室内夜间作业(0点-次日6:00)'

        return '正常时段作业'

    # ==================== 计划性质评分 ====================

    def calc_plan_nature_score(self, plan_nature: str) -> int:
        return self.PLAN_NATURE_MAP.get(plan_nature, 0)

    def determine_plan_nature(self, plan_start_time, release_time) -> str:
        """根据发布时间和计划开始时间判定计划性质"""
        if not plan_start_time or not release_time:
            return '计划性作业'
        time_diff = (plan_start_time - release_time).days
        if time_diff >= 2:
            return '计划性作业'
        if time_diff >= 1:
            return '提前一日制定的临时性作业任务'
        return '当日制定的临时性作业任务'

    # ==================== 风险等级判定 ====================

    def get_risk_level(self, score) -> str:
        """
        根据总分判断风险等级
        - 可接受: 0 <= score <= 20
        - 低: 20 < score <= 70
        - 中: 70 < score <= 200
        - 高: 200 < score <= 400
        - 特高: score > 400
        """
        score = int(score) if isinstance(score, (int, float)) else 0
        if score <= 20:
            return "可接受"
        if score <= 70:
            return "低"
        if score <= 200:
            return "中"
        if score <= 400:
            return "高"
        return "特高"

    # ==================== 人员ID处理工具方法 ====================

    @staticmethod
    def split_member_ids(member_str: str) -> List[str]:
        """按分隔符分割班组成员字符串"""
        if not member_str or not isinstance(member_str, str):
            return []
        parts = re.split(r'[,;，；、\s/\\|。]', member_str)
        return [p.strip() for p in parts if p.strip()]

    @staticmethod
    def contains_chinese(s: str) -> bool:
        """判断字符串是否包含中文"""
        if not s or not isinstance(s, str):
            return False
        return bool(re.search(r'[\u4e00-\u9fa5]', s))

    @staticmethod
    def clean_bracket_content(s: str) -> str:
        """清理字符串中的括号内容（移除非人名信息）"""
        if not s or not isinstance(s, str):
            return s
        pattern = re.compile(r'([（\(](.*?)[）\)])')
        matches = pattern.findall(s)
        result = s
        for full_match, inner_content in matches:
            inner_content = inner_content.strip()
            if re.match(r'^\d+人?$', inner_content):
                result = result.replace(full_match, '')
            elif any(kw in inner_content for kw in _get_bracket_filter_keywords()):
                result = result.replace(full_match, '')
        return result.strip()

    # ==================== 大模型评估相关方法（委托给 ai_client） ====================

    async def evaluate_work_task(self, work_task: str, semaphore, session=None) -> Dict:
        """大模型评估工作任务"""
        return await evaluate_work_task_with_llm(work_task, semaphore, session)

    async def evaluate_work_location(self, work_content: str, semaphore, session=None) -> Dict:
        """大模型评估作业地段"""
        return await evaluate_work_location_with_llm(work_content, semaphore, session)

    async def evaluate_location_type(self, work_task: str, semaphore, session=None) -> Dict:
        """大模型判断站内/站外"""
        return await evaluate_location_type_with_llm(work_task, semaphore, session)

    async def is_chinese_name(self, text: str, semaphore, session=None) -> bool:
        """大模型判断是否为中文姓名"""
        return await is_chinese_name_with_llm(text, semaphore, session)