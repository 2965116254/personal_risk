# -*- coding: utf-8 -*-
"""
pytest fixtures
"""
import sys
import os
from datetime import datetime, date
import pytest

# 将 code 目录加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'code'))

from risk_rule_engine import RiskRuleEngine


@pytest.fixture
def engine():
    """返回 RiskRuleEngine 实例"""
    return RiskRuleEngine()


@pytest.fixture
def sample_ticket():
    """返回一个模拟的工作票数据"""
    return {
        'work_code': 'TEST-2026-0001',
        'ticket_no': 'TICKET-001',
        'work_task': '更换10kV线路绝缘子',
        'work_content': '站外线路更换绝缘子',
        'work_plan_start_time': datetime(2026, 6, 29, 8, 0, 0),
        'work_plan_end_time': datetime(2026, 6, 29, 18, 0, 0),
        'actual_start_time': datetime(2026, 6, 29, 8, 30, 0),
        'actual_end_time': datetime(2026, 6, 29, 17, 30, 0),
        'release_time': datetime(2026, 6, 27, 10, 0, 0),
        'task_main': '本单位',
        'member_ids': '张三,李四,王五',
        'member_count': 3,
        'peccancy_records': {'A': 1, 'B': 2},
    }


@pytest.fixture
def normal_date():
    """普通工作日"""
    return date(2026, 6, 29)  # 周一