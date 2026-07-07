# -*- coding: utf-8 -*-
"""
NightShiftDetector 单元测试
使用 mock 数据验证夜间作业判断逻辑，不依赖数据库。
"""
import sys
import os
from datetime import datetime, timedelta
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'code'))
from night_shift_detector import NightShiftDetector


class MockDataFetcher:
    """模拟 DataFetcher，返回预设的测试数据"""

    def __init__(self, mock_data):
        self.mock_data = mock_data

    def fetchall(self, query, params=None):
        return self.mock_data


# ==================== 测试数据构建 ====================

def make_ticket(ticket_type, work_state='6', last_gap_time=None,
                last_gap_start_time=None, work_code='WC-001',
                ticket_no='T-001', work_task='测试任务'):
    """构建测试工作票数据"""
    return {
        'work_code': work_code,
        'ticket_no': ticket_no,
        'ticket_type': ticket_type,
        'work_state': work_state,
        'last_gap_time': last_gap_time,
        'last_gap_start_time': last_gap_start_time,
        'work_task': work_task,
        'plan_start_time': datetime(2026, 7, 7, 8, 0, 0),
        'plan_end_time': datetime(2026, 7, 7, 18, 0, 0),
    }


def make_detector(mock_tickets):
    """创建使用 mock 数据的 NightShiftDetector"""
    return NightShiftDetector(MockDataFetcher(mock_tickets))


# ==================== 厂站工作票测试 ====================

class TestStationNightShift:
    """厂站工作票夜间作业判断"""

    def test_work_state_not_executing__should_not_be_night(self):
        """厂站票非执行中状态 → 不判定为夜间作业"""
        for ws in ['7', '8', '']:
            ticket = make_ticket('11', work_state=ws, last_gap_time=None)
            detector = make_detector([ticket])
            results = detector.detect_force(ticket_type_filter='station')
            assert len(results) == 0, f"work_state={ws} 不应检测到夜间作业"

    def test_no_last_gap_time__should_be_night(self):
        """没有最后一次间断时间 → 判定为夜间作业"""
        ticket = make_ticket('11', work_state='6', last_gap_time=None, last_gap_start_time=datetime(2026, 7, 6, 22, 0, 0))
        detector = make_detector([ticket])
        results = detector.detect_force(ticket_type_filter='station')
        assert len(results) == 1
        assert results[0]['night_shift'] is True
        assert '无最后一次间断时间' in results[0]['reason']

    def test_last_gap_start_gt_last_gap_time__should_be_night(self):
        """最后一次开工时间 > 最后一次间断时间 → 判定为夜间作业"""
        ticket = make_ticket('12',
            last_gap_time=datetime(2026, 7, 6, 20, 0, 0),
            last_gap_start_time=datetime(2026, 7, 6, 22, 0, 0))
        detector = make_detector([ticket])
        results = detector.detect_force(ticket_type_filter='station')
        assert len(results) == 1
        assert results[0]['night_shift'] is True
        assert '最后一次开工时间大于最后一次间断时间' in results[0]['reason']

    def test_has_gap_and_start_not_greater__should_not_be_night(self):
        """有间断时间且开工时间不大于间断时间 → 不判定为夜间作业"""
        ticket = make_ticket('13',
            last_gap_time=datetime(2026, 7, 6, 22, 0, 0),
            last_gap_start_time=datetime(2026, 7, 6, 20, 0, 0))
        detector = make_detector([ticket])
        results = detector.detect_force(ticket_type_filter='station')
        assert len(results) == 0

    def test_has_gap_and_start_equal__should_not_be_night(self):
        """有间断时间且开工时间等于间断时间 → 不判定为夜间作业"""
        now = datetime(2026, 7, 6, 22, 0, 0)
        ticket = make_ticket('11', last_gap_time=now, last_gap_start_time=now)
        detector = make_detector([ticket])
        results = detector.detect_force(ticket_type_filter='station')
        assert len(results) == 0

    def test_has_gap_but_no_start__should_not_be_night(self):
        """有间断时间但没有开工时间 → 不判定为夜间作业"""
        ticket = make_ticket('12',
            last_gap_time=datetime(2026, 7, 6, 20, 0, 0),
            last_gap_start_time=None)
        detector = make_detector([ticket])
        results = detector.detect_force(ticket_type_filter='station')
        assert len(results) == 0

    def test_both_gap_and_start_none__should_be_night(self):
        """间断时间和开工时间都为空 → 判定为夜间作业（命中条件1）"""
        ticket = make_ticket('13', last_gap_time=None, last_gap_start_time=None)
        detector = make_detector([ticket])
        results = detector.detect_force(ticket_type_filter='station')
        assert len(results) == 1
        assert results[0]['night_shift'] is True

    def test_all_station_types(self):
        """三种厂站工作票类型都能正确判断"""
        for tt in ['11', '12', '13']:
            ticket = make_ticket(tt, last_gap_time=None)
            detector = make_detector([ticket])
            results = detector.detect_force(ticket_type_filter='station')
            assert len(results) == 1, f"ticket_type={tt} 应该被检测到"


# ==================== 线路工作票测试 ====================

class TestLineNightShift:
    """线路工作票夜间作业判断"""

    def test_work_state_executing__should_be_night(self):
        """工作状态为执行中(6) → 判定为夜间作业"""
        ticket = make_ticket('21', work_state='6')
        detector = make_detector([ticket])
        results = detector.detect_force(ticket_type_filter='line')
        assert len(results) == 1
        assert results[0]['night_shift'] is True
        assert '执行中' in results[0]['reason']

    def test_work_state_finished__should_not_be_night(self):
        """工作状态为工作终结(7) → 不判定为夜间作业"""
        ticket = make_ticket('22', work_state='7')
        detector = make_detector([ticket])
        results = detector.detect_force(ticket_type_filter='line')
        assert len(results) == 0

    def test_work_state_ticket_finished__should_not_be_night(self):
        """工作状态为工作票终结(8) → 不判定为夜间作业"""
        ticket = make_ticket('21', work_state='8')
        detector = make_detector([ticket])
        results = detector.detect_force(ticket_type_filter='line')
        assert len(results) == 0

    def test_work_state_empty__should_not_be_night(self):
        """工作状态为空 → 不判定为夜间作业"""
        ticket = make_ticket('22', work_state='')
        detector = make_detector([ticket])
        results = detector.detect_force(ticket_type_filter='line')
        assert len(results) == 0

    def test_all_line_types(self):
        """两种线路工作票类型都能正确判断"""
        for tt in ['21', '22']:
            ticket = make_ticket(tt, work_state='6')
            detector = make_detector([ticket])
            results = detector.detect_force(ticket_type_filter='line')
            assert len(results) == 1, f"ticket_type={tt} 应该被检测到"


# ==================== 混合票类型测试 ====================

class TestMixedTickets:
    """混合票类型测试"""

    def test_force_all__detects_both_types(self):
        """强制模式 all → 同时检测厂站和线路票"""
        tickets = [
            make_ticket('11', work_code='WC-1', ticket_no='T-1',
                        last_gap_time=None),                      # 厂站票，夜间
            make_ticket('21', work_code='WC-2', ticket_no='T-2',
                        work_state='6'),                          # 线路票，夜间
            make_ticket('12', work_code='WC-3', ticket_no='T-3',
                        last_gap_time=datetime(2026, 7, 6, 20, 0),
                        last_gap_start_time=datetime(2026, 7, 6, 18, 0)),  # 厂站票，非夜间
            make_ticket('22', work_code='WC-4', ticket_no='T-4',
                        work_state='7'),                          # 线路票，非夜间
        ]
        detector = make_detector(tickets)
        results = detector.detect_force(ticket_type_filter='all')
        assert len(results) == 2
        work_codes = {r['work_code'] for r in results}
        assert work_codes == {'WC-1', 'WC-2'}

    def test_force_station__only_detects_station(self):
        """强制模式 station → 仅检测厂站票"""
        tickets = [
            make_ticket('11', last_gap_time=None),
            make_ticket('21', work_state='6'),
        ]
        detector = make_detector(tickets)
        results = detector.detect_force(ticket_type_filter='station')
        assert len(results) == 1
        assert results[0]['ticket_type'] == '11'

    def test_force_line__only_detects_line(self):
        """强制模式 line → 仅检测线路票"""
        tickets = [
            make_ticket('11', last_gap_time=None),
            make_ticket('21', work_state='6'),
        ]
        detector = make_detector(tickets)
        results = detector.detect_force(ticket_type_filter='line')
        assert len(results) == 1
        assert results[0]['ticket_type'] == '21'

    def test_other_ticket_types_ignored(self):
        """其他票类型（非11/12/13/21/22）被忽略"""
        tickets = [
            make_ticket('99', work_state='6'),  # 其他类型，应忽略
            make_ticket('11', last_gap_time=None),
        ]
        detector = make_detector(tickets)
        results = detector.detect_force(ticket_type_filter='all')
        assert len(results) == 1
        assert results[0]['ticket_type'] == '11'


# ==================== 时间驱动的 detect() 方法测试 ====================

class TestDetectWithTime:
    """detect() 方法的时间驱动逻辑测试"""

    def test_hour_0__detects_station(self):
        """当前时间为0点 → 检测厂站票"""
        ticket = make_ticket('11', last_gap_time=None)
        detector = make_detector([ticket])
        sim_time = datetime(2026, 7, 7, 0, 0, 0)
        results = detector.detect(current_time=sim_time)
        assert len(results) == 1
        assert '厂站' in results[0]['reason']

    def test_hour_20__detects_line(self):
        """当前时间为20点 → 检测线路票"""
        ticket = make_ticket('21', work_state='6')
        detector = make_detector([ticket])
        sim_time = datetime(2026, 7, 7, 20, 0, 0)
        results = detector.detect(current_time=sim_time)
        assert len(results) == 1
        assert '线路' in results[0]['reason']

    def test_hour_0__ignores_line_tickets(self):
        """0点检测时忽略线路票"""
        tickets = [
            make_ticket('11', last_gap_time=None),
            make_ticket('21', work_state='6'),
        ]
        detector = make_detector(tickets)
        sim_time = datetime(2026, 7, 7, 0, 0, 0)
        results = detector.detect(current_time=sim_time)
        assert len(results) == 1
        assert results[0]['ticket_type'] == '11'

    def test_hour_20__ignores_station_tickets(self):
        """20点检测时忽略厂站票"""
        tickets = [
            make_ticket('11', last_gap_time=None),
            make_ticket('21', work_state='6'),
        ]
        detector = make_detector(tickets)
        sim_time = datetime(2026, 7, 7, 20, 0, 0)
        results = detector.detect(current_time=sim_time)
        assert len(results) == 1
        assert results[0]['ticket_type'] == '21'

    def test_other_hours__returns_empty(self):
        """非0点非20点 → 返回空列表"""
        ticket = make_ticket('11', last_gap_time=None)
        detector = make_detector([ticket])
        for h in [6, 9, 12, 15, 18]:
            sim_time = datetime(2026, 7, 7, h, 0, 0)
            results = detector.detect(current_time=sim_time)
            assert len(results) == 0, f"hour={h} 不应检测到夜间作业"


# ==================== 边界情况测试 ====================

class TestEdgeCases:
    """边界情况测试"""

    def test_empty_tickets(self):
        """空数据列表 → 返回空"""
        detector = make_detector([])
        results = detector.detect_force()
        assert results == []

    def test_none_fields(self):
        """所有关键字段为 None 的票"""
        ticket = {
            'work_code': 'WC-001',
            'ticket_no': 'T-001',
            'ticket_type': '11',
            'work_state': '6',          # 必须为执行中
            'last_gap_time': None,
            'last_gap_start_time': None,
            'work_task': None,
            'plan_start_time': None,
            'plan_end_time': None,
        }
        detector = make_detector([ticket])
        results = detector.detect_force(ticket_type_filter='station')
        # 厂站票 + last_gap_time 为 None → 应判定为夜间
        assert len(results) == 1

    def test_result_has_required_fields(self):
        """返回结果包含必要的字段"""
        ticket = make_ticket('11', last_gap_time=None)
        detector = make_detector([ticket])
        results = detector.detect_force()
        assert len(results) == 1
        r = results[0]
        assert 'night_shift' in r
        assert r['night_shift'] is True
        assert 'reason' in r
        assert 'ticket_no' in r
        assert 'work_code' in r
        assert 'ticket_type' in r