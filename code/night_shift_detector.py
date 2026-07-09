# -*- coding: utf-8 -*-
"""
夜间作业检测模块
根据厂站工作票和线路工作票的实时数据判断是否为夜间作业。

判断规则：
  - 厂站工作票（ticket_type: 11/12/13）：程序在配置时间（默认24点）运行检测
      前提：工作票状态为执行中（work_state = '6'）
      条件1：没有最后一次间断时间（last_gap_time 为空）
      条件2：最后一次开工时间 > 最后一次间断时间
      满足任一条件即判定为夜间作业
  - 线路工作票（ticket_type: 21/22）：程序在配置时间（默认20点）运行检测
      条件：工作状态为"执行中"（work_state = '6'）
      满足条件即判定为夜间作业

注意：不能使用增量数据，每次检测均基于全量当前数据。
运行时间和开关等配置项在 config.yaml 的 night_shift 段中。
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Set, Tuple

from openpyxl import Workbook
from openpyxl.styles import Border, Side, Alignment, PatternFill, Font

import config_loader
from data_fetcher import DataFetcher

logger = logging.getLogger(__name__)

# ==================== 日志配置 ====================

def setup_logging():
    """配置夜间作业检测的日志输出

    日志文件存放在 {项目根目录}/log/ 下，文件名格式：night_shift_YYYYMMDD_HHMMSS.log
    同时输出到控制台。
    """
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(BASE_DIR, 'log')
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(log_dir, f"night_shift_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

    # 避免重复添加 handler
    if logger.handlers:
        return log_file

    logger.setLevel(logging.DEBUG)

    # 文件 handler（记录所有日志）
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(file_handler)

    # 控制台 handler（只输出 INFO 及以上级别）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    ))
    logger.addHandler(console_handler)

    logger.info(f"日志文件: {log_file}")
    return log_file


# ==================== SQL 查询 ====================

# 夜间作业检测 SQL 查询
# 查询厂站和线路工作票的关键字段，用于夜间作业判断
NIGHT_SHIFT_QUERY = """
SELECT 
    wp.work_code,             -- 作业计划编号
    wb.ticket_no,             -- 工作票票号
    wb.ticket_type,           -- 工作票类型（11/12/13=厂站, 21/22=线路）
    wb.work_state,            -- 工作票状态（6=执行中, 7=工作终结, 8=工作票终结）
    wb.last_gap_time,         -- 最后一次间断时间
    wb.last_gap_start_time,   -- 最后一次开工时间
    wb.work_task,             -- 工作任务
    wp.plan_start_time,       -- 计划开始时间
    wp.plan_end_time          -- 计划结束时间
FROM sp_ss_rc_work_plan wp
LEFT JOIN (
    SELECT business_name, wticket_id
    FROM (
        SELECT business_name, wticket_id,
            ROW_NUMBER() OVER (PARTITION BY business_name ORDER BY update_time DESC) AS rn
        FROM sp_pd_wticket_business_re
    ) t
    WHERE rn = 1
) re ON wp.work_code = re.business_name
LEFT JOIN sp_pd_wticket_base wb ON re.wticket_id = wb.id
WHERE wp.task_state IN ('2.0', '3.0', '6.0')
  AND wb.ticket_type IN ('11', '12', '13', '21', '22')
"""


# ==================== Excel 列定义 ====================

NIGHT_SHIFT_EXCEL_HEADERS = [
    '序号',
    '工作票类型',
    '工作票票号',
    '作业计划编号',
    '工作任务',
    '工作票状态',
    '最后一次间断时间',
    '最后一次开工时间',
    '判定依据',
]


class NightShiftDetector:
    """夜间作业检测器

    用于判断厂站工作票和线路工作票是否属于夜间作业。
    每次检测均查询全量当前数据，不使用增量数据。

    运行时间和开关从 config.yaml 读取，支持通过 detect_force 手动触发。
    """

    # 厂站工作票类型（ticket_type 值）
    STATION_TICKET_TYPES = {'11', '12', '13'}

    # 线路工作票类型（ticket_type 值）
    LINE_TICKET_TYPES = {'21', '22'}

    # 工作内容排除关键词：包含这些关键词的工作票不算夜间作业
    EXCLUDE_WORK_TASK_KEYWORDS = ['机巡', '智能巡检', '智能巡视']

    TICKET_TYPE_NAMES = {
        '11': '厂站第一种工作票',
        '12': '厂站第二种工作票',
        '13': '厂站第三种工作票',
        '21': '线路第一种工作票',
        '22': '线路第二种工作票',
    }

    WORK_STATE_NAMES = {
        '6': '执行中',
        '7': '工作终结',
        '8': '工作票终结',
    }

    def __init__(self, data_fetcher):
        """
        :param data_fetcher: DataFetcher 实例，提供数据库查询能力
        """
        self.data_fetcher = data_fetcher

    @staticmethod
    def is_excluded_by_work_task(work_task: str) -> bool:
        """检查工作内容是否包含排除关键词

        如果工作内容包含【机巡】、【智能巡检】、【智能巡视】等关键词，
        则不算夜间作业。

        :param work_task: 工作内容/工作任务
        :return: True 表示应排除（不算夜间作业），False 表示正常判定
        """
        if not work_task:
            return False
        for keyword in NightShiftDetector.EXCLUDE_WORK_TASK_KEYWORDS:
            if keyword in work_task:
                logger.info(
                    f"工作内容包含排除关键词'{keyword}'，不判定为夜间作业（工作内容: {work_task[:60]}）"
                )
                return True
        return False

    # ==================== 配置读取 ====================

    @staticmethod
    def get_station_hour() -> int:
        """获取厂站工作票检测时间（小时）"""
        cfg = config_loader.get_night_shift_config()
        return int(cfg.get('station', {}).get('hour', 0))

    @staticmethod
    def get_station_minute() -> int:
        """获取厂站工作票检测时间（分钟）"""
        cfg = config_loader.get_night_shift_config()
        return int(cfg.get('station', {}).get('minute', 0))

    @staticmethod
    def get_line_hour() -> int:
        """获取线路工作票检测时间（小时）"""
        cfg = config_loader.get_night_shift_config()
        return int(cfg.get('line', {}).get('hour', 20))

    @staticmethod
    def get_line_minute() -> int:
        """获取线路工作票检测时间（分钟）"""
        cfg = config_loader.get_night_shift_config()
        return int(cfg.get('line', {}).get('minute', 0))

    @staticmethod
    def is_station_enabled() -> bool:
        """厂站工作票检测是否启用"""
        cfg = config_loader.get_night_shift_config()
        return cfg.get('enabled', True) and cfg.get('station', {}).get('enabled', True)

    @staticmethod
    def is_line_enabled() -> bool:
        """线路工作票检测是否启用"""
        cfg = config_loader.get_night_shift_config()
        return cfg.get('enabled', True) and cfg.get('line', {}).get('enabled', True)

    @staticmethod
    def is_global_enabled() -> bool:
        """夜间作业检测总开关"""
        return config_loader.get_night_shift_config().get('enabled', True)

    @staticmethod
    def get_output_dir() -> str:
        """获取输出目录"""
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cfg_dir = config_loader.get_night_shift_config().get('output_dir', '')
        if cfg_dir:
            return cfg_dir
        return os.path.join(BASE_DIR, 'output', 'night_shift')

    @staticmethod
    def get_output_prefix() -> str:
        """获取输出文件名前缀"""
        return config_loader.get_night_shift_config().get('output_prefix', '夜间作业检测')

    @staticmethod
    def is_output_excel_enabled() -> bool:
        """是否在定时检测时导出Excel并推送（MinIO/elink）

        默认 true（向后兼容），设置为 false 时定时任务仅保存 JSON。
        """
        return config_loader.get_night_shift_config().get('output_excel', True)

    @staticmethod
    def get_json_output_dir() -> str:
        """获取夜间作业 work_codes JSON 文件的保存目录（risk_calculation_formulav3.2/cache/）"""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, 'cache')

    @staticmethod
    def save_night_shift_work_codes(results: List[Dict], detection_hour: int):
        """将夜间作业每条 work_code 的详细检测信息保存到 JSON 文件

        文件名格式：
          - 20点检测（线路票）: line_YYYYMMDD_HHMMSS.json
          - 0点检测（厂站票）: station_YYYYMMDD_HHMMSS.json

        :param results: 夜间作业检测结果列表，每条包含 work_code、ticket_type、work_state、last_gap_time 等
        :param detection_hour: 检测的小时（20=线路, 0=厂站）
        """
        output_dir = NightShiftDetector.get_json_output_dir()
        os.makedirs(output_dir, exist_ok=True)

        # 根据检测小时确定类型前缀
        if detection_hour == 20:
            prefix = 'line'
        else:
            prefix = 'station'  # 0点（24点）检测的是厂站票

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'{prefix}_{timestamp}.json'
        filepath = os.path.join(output_dir, filename)

        work_codes = sorted([r['work_code'] for r in results if r.get('work_code')])

        # 构建每条 work_code 的详细检测信息
        def _fmt_dt(val):
            """格式化 datetime 对象为字符串，None 返回 None"""
            if val is None:
                return None
            if isinstance(val, str):
                return val
            return val.strftime('%Y-%m-%d %H:%M:%S')

        details = {}
        for r in results:
            wc = r.get('work_code', '')
            if not wc:
                continue
            details[wc] = {
                'ticket_type': r.get('ticket_type', ''),
                'ticket_no': r.get('ticket_no', ''),
                'work_task': r.get('work_task', ''),
                'work_state': r.get('work_state', ''),
                'last_gap_time': _fmt_dt(r.get('last_gap_time')),
                'last_gap_start_time': _fmt_dt(r.get('last_gap_start_time')),
                'reason': r.get('reason', ''),
            }

        detected_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # 为每条详情记录注入检测时间
        for wc in details:
            details[wc]['detected_at'] = detected_at

        data = {
            'type': prefix,
            'detected_at': detected_at,
            'work_codes': work_codes,
            'details': details,
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"夜间作业检测详情已保存: {filepath}（{prefix}，共 {len(work_codes)} 条）")

    @staticmethod
    def load_yesterday_night_shift_work_codes() -> Tuple[Set[str], str, Dict]:
        """加载前一天所有夜间作业检测的 work_code 集合、检测时间描述和详细检测信息

        扫描 cache/ 目录下所有 line_ 和 station_ 前缀的 JSON 文件，
        取日期为前一天的，合并所有 work_code 和 details。

        :return: (work_codes集合, 检测时间描述, 详细检测信息字典)
            检测时间描述如 "线路检测: 2026-07-08 20:05:00, 厂站检测: 2026-07-09 00:02:00"
            详细检测信息字典 {work_code: {ticket_type, ticket_no, work_state, last_gap_time, last_gap_start_time, ...}}
        """
        output_dir = NightShiftDetector.get_json_output_dir()
        if not os.path.isdir(output_dir):
            return set(), '', {}

        import re
        yesterday = (date.today() - timedelta(days=1)).strftime('%Y%m%d')
        pattern = re.compile(r'^(line|station)_(\d{8})_\d{6}\.json$')

        work_codes = set()
        detection_times = {}  # {'line': '2026-07-08 20:05:00', 'station': '2026-07-09 00:02:00'}
        all_details = {}
        for filename in os.listdir(output_dir):
            match = pattern.match(filename)
            if not match:
                continue
            file_date_str = match.group(2)
            if file_date_str != yesterday:
                continue
            filepath = os.path.join(output_dir, filename)
            ns_type = match.group(1)  # 'line' or 'station'
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                codes = data.get('work_codes', [])
                work_codes.update(codes)
                detected_at = data.get('detected_at', '')
                if detected_at:
                    detection_times[ns_type] = detected_at
                # 加载详细检测信息
                details = data.get('details', {})
                if details:
                    all_details.update(details)
                logger.info(f"读取夜间作业检测结果: {filename}（{len(codes)} 条）")
            except Exception as e:
                logger.warning(f"读取夜间作业检测结果文件失败: {filename}，错误: {e}")

        # 构建检测时间描述
        desc_parts = []
        type_names = {'line': '线路检测', 'station': '厂站检测'}
        for ns_type in ['line', 'station']:
            if ns_type in detection_times:
                desc_parts.append(f"{type_names[ns_type]}: {detection_times[ns_type]}")
        detection_desc = ', '.join(desc_parts) if desc_parts else ''

        return work_codes, detection_desc, all_details

    @staticmethod
    def clean_old_json_files(keep_days: int = 7):
        """清理超过 keep_days 天的夜间作业 JSON 文件

        文件名格式: line_YYYYMMDD_*.json 或 station_YYYYMMDD_*.json
        :param keep_days: 保留天数，默认7天
        """
        output_dir = NightShiftDetector.get_json_output_dir()
        if not os.path.isdir(output_dir):
            return

        import re
        cutoff = date.today() - timedelta(days=keep_days)
        pattern = re.compile(r'^(line|station)_(\d{8})_\d{6}\.json$')

        count = 0
        for filename in os.listdir(output_dir):
            match = pattern.match(filename)
            if not match:
                continue
            try:
                file_date = datetime.strptime(match.group(2), '%Y%m%d').date()
                if file_date < cutoff:
                    filepath = os.path.join(output_dir, filename)
                    os.remove(filepath)
                    count += 1
                    logger.debug(f"已删除过期夜间作业JSON文件: {filename}")
            except (ValueError, OSError) as e:
                logger.warning(f"清理夜间作业JSON文件失败: {filename}，错误: {e}")

        if count > 0:
            logger.info(f"夜间作业JSON文件清理完成: 共删除 {count} 个过期文件（保留 {keep_days} 天）")

    # ==================== 数据查询 ====================

    def fetch_tickets(self, query_start_date: str = None,
                      query_end_date: str = None) -> List[Dict]:
        """查询夜间作业判断所需的工作票数据（全量查询，非增量）

        :param query_start_date: 查询时间区间开始（日期字符串，如 '2026-01-01'）
        :param query_end_date: 查询时间区间结束（日期字符串，如 '2026-02-01'）
        :return: 工作票数据列表
        """
        query = NIGHT_SHIFT_QUERY
        params = []

        if query_start_date and query_end_date:
            query += " AND ( NOT(wp.plan_end_time <= %s OR wp.plan_start_time >= %s) )"
            params.append(query_start_date + " 00:00:00")
            params.append(query_end_date + " 23:59:59")

        return self.data_fetcher.fetchall(query, params)

    # ==================== 检测主逻辑 ====================

    def detect(self, current_time: datetime = None,
               query_start_date: str = None,
               query_end_date: str = None) -> List[Dict]:
        """执行夜间作业检测（主入口）

        根据配置的检测时间自动判断应该检测厂站工作票还是线路工作票。
        如果总开关禁用，跳过检测。

        :param current_time: 当前检测时间，默认为当前系统时间
        :param query_start_date: 查询时间区间开始
        :param query_end_date: 查询时间区间结束
        :return: 被判定为夜间作业的工作票列表，每项附加 night_shift=True 和 reason 字段
        """
        if not self.is_global_enabled():
            logger.debug("夜间作业检测总开关禁用，跳过")
            return []

        if current_time is None:
            current_time = datetime.now()

        current_hour = current_time.hour
        current_min = current_time.minute

        # 判断是否为厂站工作票检测时间
        if self.is_station_enabled():
            sh = self.get_station_hour()
            sm = self.get_station_minute()
            if current_hour == sh and current_min >= sm:
                return self._detect_station_night_shift(current_time, query_start_date, query_end_date)

        # 判断是否为线路工作票检测时间
        if self.is_line_enabled():
            lh = self.get_line_hour()
            lm = self.get_line_minute()
            if current_hour == lh and current_min >= lm:
                return self._detect_line_night_shift(current_time, query_start_date, query_end_date)

        logger.debug(
            f"当前时间 {current_hour:02d}:{current_min:02d} 不在检测时段内"
            f"（厂站票: {self.get_station_hour():02d}:{self.get_station_minute():02d}, "
            f"线路票: {self.get_line_hour():02d}:{self.get_line_minute():02d}），跳过夜间作业检测"
        )
        return []

    def _detect_station_night_shift(self, current_time: datetime,
                                     query_start_date: str = None,
                                     query_end_date: str = None) -> List[Dict]:
        """检测厂站工作票夜间作业

        判断条件：
          1. 没有最后一次间断时间（last_gap_time 为空）
          2. 最后一次开工时间 > 最后一次间断时间
        """
        tickets = self.fetch_tickets(query_start_date, query_end_date)
        night_shift_list = []

        for ticket in tickets:
            ticket_type = str(ticket.get('ticket_type', ''))

            # 只处理厂站工作票
            if ticket_type not in self.STATION_TICKET_TYPES:
                continue

            # 前提：工作状态必须为"执行中"
            work_state = str(ticket.get('work_state', ''))
            if work_state != '6':
                continue

            # 排除：工作内容包含【机巡】、【智能巡检】、【智能巡视】等关键词
            work_task = ticket.get('work_task', '') or ''
            if self.is_excluded_by_work_task(work_task):
                continue

            last_gap_time = ticket.get('last_gap_time')
            last_gap_start_time = ticket.get('last_gap_start_time')

            # 条件1：没有最后一次间断时间
            if last_gap_time is None:
                night_shift_list.append({
                    **ticket,
                    'night_shift': True,
                    'reason': '厂站工作票：无最后一次间断时间，判定为夜间作业',
                })
                continue

            # 条件2：最后一次开工时间 > 最后一次间断时间
            if last_gap_start_time is not None and last_gap_start_time > last_gap_time:
                night_shift_list.append({
                    **ticket,
                    'night_shift': True,
                    'reason': '厂站工作票：最后一次开工时间大于最后一次间断时间，判定为夜间作业',
                })

        if night_shift_list:
            logger.info(
                f"[夜间作业检测-厂站票] 检测时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}, "
                f"共检测 {len(tickets)} 张厂站工作票，判定夜间作业 {len(night_shift_list)} 张"
            )

        return night_shift_list

    def _detect_line_night_shift(self, current_time: datetime,
                                  query_start_date: str = None,
                                  query_end_date: str = None) -> List[Dict]:
        """检测线路工作票夜间作业

        判断条件：工作状态为"执行中"（work_state = '6'）
        """
        tickets = self.fetch_tickets(query_start_date, query_end_date)
        night_shift_list = []

        for ticket in tickets:
            ticket_type = str(ticket.get('ticket_type', ''))

            # 只处理线路工作票
            if ticket_type not in self.LINE_TICKET_TYPES:
                continue

            work_state = str(ticket.get('work_state', ''))

            # 条件：工作状态为执行中
            if work_state != '6':
                continue

            # 排除：工作内容包含【机巡】、【智能巡检】、【智能巡视】等关键词
            work_task = ticket.get('work_task', '') or ''
            if self.is_excluded_by_work_task(work_task):
                continue

            night_shift_list.append({
                **ticket,
                'night_shift': True,
                'reason': '线路工作票：工作状态为执行中，20点检测判定为夜间作业',
            })

        if night_shift_list:
            logger.info(
                f"[夜间作业检测-线路票] 检测时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}, "
                f"共检测 {len(tickets)} 张线路工作票，判定夜间作业 {len(night_shift_list)} 张"
            )

        return night_shift_list

    def detect_force(self, ticket_type_filter: str = 'all',
                     query_start_date: str = None,
                     query_end_date: str = None) -> List[Dict]:
        """强制执行夜间作业检测（不依赖当前时间，用于手动触发或测试）

        :param ticket_type_filter: 票类型过滤
            - 'station': 仅检测厂站工作票
            - 'line': 仅检测线路工作票
            - 'all': 检测全部（默认）
        """
        tickets = self.fetch_tickets(query_start_date, query_end_date)
        night_shift_list = []

        for ticket in tickets:
            ticket_type = str(ticket.get('ticket_type', ''))

            # 根据过滤器跳过不需要检测的票类型
            if ticket_type_filter == 'station' and ticket_type not in self.STATION_TICKET_TYPES:
                continue
            if ticket_type_filter == 'line' and ticket_type not in self.LINE_TICKET_TYPES:
                continue

            # 排除：工作内容包含【机巡】、【智能巡检】、【智能巡视】等关键词
            work_task = ticket.get('work_task', '') or ''
            if self.is_excluded_by_work_task(work_task):
                continue

            is_night = False
            reason = ''

            # 厂站工作票判断（前提：工作状态必须为"执行中"）
            if ticket_type in self.STATION_TICKET_TYPES:
                work_state = str(ticket.get('work_state', ''))
                if work_state != '6':
                    continue

                last_gap_time = ticket.get('last_gap_time')
                last_gap_start_time = ticket.get('last_gap_start_time')

                if last_gap_time is None:
                    is_night = True
                    reason = '厂站工作票：无最后一次间断时间，判定为夜间作业'
                elif last_gap_start_time is not None and last_gap_start_time > last_gap_time:
                    is_night = True
                    reason = '厂站工作票：最后一次开工时间大于最后一次间断时间，判定为夜间作业'

            # 线路工作票判断
            elif ticket_type in self.LINE_TICKET_TYPES:
                work_state = str(ticket.get('work_state', ''))
                if work_state == '6':
                    is_night = True
                    reason = '线路工作票：工作状态为执行中，判定为夜间作业'

            if is_night:
                night_shift_list.append({
                    **ticket,
                    'night_shift': True,
                    'reason': reason,
                })

        logger.info(
            f"[夜间作业检测-强制模式] filter={ticket_type_filter}, "
            f"共检测 {len(tickets)} 张票，判定夜间作业 {len(night_shift_list)} 张"
        )

        return night_shift_list

    # ==================== Excel 导出 ====================

    def export_to_excel(self, results: List[Dict]) -> Optional[str]:
        """将夜间作业检测结果导出到 Excel

        :param results: detect() 或 detect_force() 的返回结果
        :return: Excel 文件路径，无数据时返回 None
        """
        if not results:
            logger.info("无夜间作业检测结果，跳过Excel导出")
            return None

        output_dir = self.get_output_dir()
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        prefix = self.get_output_prefix()
        filename = f'{prefix}_{timestamp}.xlsx'
        filepath = os.path.join(output_dir, filename)

        wb = Workbook()
        ws = wb.active
        ws.title = '夜间作业检测'

        # 写标题行
        for col, header in enumerate(NIGHT_SHIFT_EXCEL_HEADERS, 1):
            ws.cell(row=1, column=col, value=header)

        # 写数据
        for i, r in enumerate(results, 1):
            ticket_type = str(r.get('ticket_type', ''))
            work_state = str(r.get('work_state', ''))

            lag_gap = r.get('last_gap_time')
            lag_start = r.get('last_gap_start_time')

            row_data = [
                i,
                self.TICKET_TYPE_NAMES.get(ticket_type, f'未知({ticket_type})'),
                r.get('ticket_no', ''),
                r.get('work_code', ''),
                r.get('work_task', ''),
                self.WORK_STATE_NAMES.get(work_state, work_state),
                lag_gap.strftime('%Y-%m-%d %H:%M:%S') if lag_gap else '',
                lag_start.strftime('%Y-%m-%d %H:%M:%S') if lag_start else '',
                r.get('reason', ''),
            ]
            for col, value in enumerate(row_data, 1):
                ws.cell(row=i + 1, column=col, value=value)

        # 美化
        self._beautify_excel(ws, len(results))

        wb.save(filepath)
        logger.info(f"夜间作业检测结果已导出: {filepath}，共 {len(results)} 条记录")
        return filepath

    @staticmethod
    def _beautify_excel(ws, row_count: int):
        """美化 Excel 工作表"""
        header_fill = PatternFill(start_color='4472C4', end_color='4472C4', fill_type='solid')
        header_font = Font(color='FFFFFF', bold=True, name='微软雅黑', size=11)
        content_font = Font(name='微软雅黑', size=10)
        thin_border = Border(
            left=Side(style='thin'), right=Side(style='thin'),
            top=Side(style='thin'), bottom=Side(style='thin'),
        )
        center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
        left_align = Alignment(horizontal='left', vertical='center', wrap_text=True)

        # 文本列索引（1-based）：工作任务、判定依据
        text_cols = {5, 9}

        for row in ws.iter_rows():
            for cell in row:
                cell.border = thin_border
                if cell.row == 1:
                    cell.fill = header_fill
                    cell.font = header_font
                    cell.alignment = center_align
                else:
                    cell.font = content_font
                    cell.alignment = left_align if cell.column in text_cols else center_align

        # 列宽
        col_widths = [6, 20, 22, 24, 40, 12, 22, 22, 50]
        for col_idx, width in enumerate(col_widths, 1):
            col_letter = ws.cell(row=1, column=col_idx).column_letter
            ws.column_dimensions[col_letter].width = width

        ws.freeze_panes = 'A2'


# ==================== 独立运行入口 ====================

def run_night_shift_detection():
    """执行夜间作业检测的独立函数（供 new_rule.py 定时调度器调用）

    流程：
      1. 连接数据库 → 2. 执行检测 → 3. 导出Excel → 4. 上传MinIO → 5. 发送elink
    """
    # 初始化日志
    setup_logging()

    if not NightShiftDetector.is_global_enabled():
        logger.info("夜间作业检测总开关禁用，跳过检测")
        return

    db_config = config_loader.get_db_new_config()
    fetcher = DataFetcher(db_config)
    fetcher.connect()

    try:
        # 清理过期的夜间作业 JSON 文件（执行检测前清理，保留7天）
        NightShiftDetector.clean_old_json_files(keep_days=7)

        # 获取查询参数
        from main import get_query_params
        _, query_start_date, query_end_date = get_query_params()

        detector = NightShiftDetector(fetcher)
        current_time = datetime.now()
        logger.info("=" * 60)
        logger.info(f"夜间作业检测（自动模式，当前时间: {current_time.strftime('%Y-%m-%d %H:%M:%S')}）")
        logger.info("=" * 60)

        results = detector.detect(
            current_time=current_time,
            query_start_date=query_start_date,
            query_end_date=query_end_date,
        )

        if not results:
            logger.info("未检测到夜间作业。")
            return

        logger.info(f"检测到 {len(results)} 张夜间作业工作票：")
        work_codes = set()
        for i, r in enumerate(results, 1):
            ticket_type = str(r.get('ticket_type', ''))
            type_name = detector.TICKET_TYPE_NAMES.get(ticket_type, '未知')
            wc = r.get('work_code', '')
            if wc:
                work_codes.add(wc)
            logger.info(f"  [{i}] {type_name}")
            logger.info(f"      票号: {r.get('ticket_no', '')}")
            logger.info(f"      作业计划编号: {wc}")
            logger.info(f"      工作任务: {r.get('work_task', '')}")
            logger.info(f"      判定依据: {r.get('reason', '')}")

        # 保存检测结果详情到 JSON 文件（供第二天9点的主流程读取）
        current_hour = current_time.hour
        if results:
            NightShiftDetector.save_night_shift_work_codes(results, current_hour)

        # 根据配置决定是否导出Excel并推送（MinIO/elink）
        if not NightShiftDetector.is_output_excel_enabled():
            logger.info("output_excel 已关闭，跳过Excel导出及后续推送")
            return

        # 导出 Excel
        filepath = detector.export_to_excel(results)
        if not filepath:
            logger.warning("导出 Excel 失败，终止后续操作")
            return

        # 上传 MinIO
        try:
            from main import upload_to_minio
            minio_name = upload_to_minio(filepath)
            if minio_name:
                logger.info(f"夜间作业检测结果已上传到 MinIO: {minio_name}")
        except Exception as e:
            logger.error(f"上传 MinIO 时出错: {e}")

        # 发送 elink
        try:
            if config_loader.get_elink_enabled():
                from main import send_file_via_elink
                send_file_via_elink(filepath)
                logger.info(f"夜间作业检测结果已通过 elink 发送")
        except Exception as e:
            logger.error(f"发送 elink 时出错: {e}")

    finally:
        fetcher.close()


# ==================== 直接执行入口 ====================

if __name__ == "__main__":
    """
    直接执行方式：
      cd risk_calculation_formulav3.2/code
      python night_shift_detector.py                    # 自动模式（根据当前时间）
      python night_shift_detector.py --force            # 强制检测所有票
      python night_shift_detector.py --force station    # 仅强制检测厂站票
      python night_shift_detector.py --force line       # 仅强制检测线路票
      python night_shift_detector.py --hour 0           # 模拟24点检测
      python night_shift_detector.py --hour 20          # 模拟20点检测
    """
    import argparse

    parser = argparse.ArgumentParser(description='夜间作业检测')
    parser.add_argument('--force', nargs='?', const='all',
                        choices=['all', 'station', 'line'],
                        help='强制模式（不依赖当前时间），可选值: all/station/line')
    parser.add_argument('--hour', type=int, default=None,
                        help='模拟指定小时执行检测（0=24点, 20=20点）')
    parser.add_argument('--start-date', type=str, default=None,
                        help='查询开始日期，如 2026-01-01')
    parser.add_argument('--end-date', type=str, default=None,
                        help='查询结束日期，如 2026-02-01')
    args = parser.parse_args()

    # 初始化日志
    setup_logging()

    db_config = config_loader.get_db_new_config()
    fetcher = DataFetcher(db_config)
    fetcher.connect()

    try:
        detector = NightShiftDetector(fetcher)
        current_time = datetime.now()

        if args.force:
            logger.info(f"=== 夜间作业检测（强制模式，filter={args.force}）===")
            results = detector.detect_force(
                ticket_type_filter=args.force,
                query_start_date=args.start_date,
                query_end_date=args.end_date,
            )
            # 强制模式下根据 filter 确定保存类型（all 时按当前小时判断）
            if args.force == 'station':
                save_hour = 0
            elif args.force == 'line':
                save_hour = 20
            else:
                save_hour = current_time.hour
        elif args.hour is not None:
            now = datetime.now()
            sim_time = now.replace(hour=args.hour, minute=0, second=0, microsecond=0)
            logger.info(f"=== 夜间作业检测（模拟时间: {sim_time.strftime('%Y-%m-%d %H:%M:%S')}）===")
            results = detector.detect(
                current_time=sim_time,
                query_start_date=args.start_date,
                query_end_date=args.end_date,
            )
            save_hour = args.hour
        else:
            logger.info(f"=== 夜间作业检测（自动模式，当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}）===")
            results = detector.detect(
                query_start_date=args.start_date,
                query_end_date=args.end_date,
            )
            save_hour = current_time.hour

        if not results:
            logger.info("未检测到夜间作业。")
        else:
            logger.info(f"检测到 {len(results)} 张夜间作业工作票：")
            work_codes = set()
            for i, r in enumerate(results, 1):
                ticket_type = str(r.get('ticket_type', ''))
                type_name = detector.TICKET_TYPE_NAMES.get(ticket_type, '未知')
                wc = r.get('work_code', '')
                if wc:
                    work_codes.add(wc)
                logger.info(f"  [{i}] {type_name}")
                logger.info(f"      票号: {r.get('ticket_no', '')}")
                logger.info(f"      作业计划编号: {wc}")
                logger.info(f"      工作任务: {r.get('work_task', '')}")
                logger.info(f"      判定依据: {r.get('reason', '')}")

            # 保存检测结果详情到 JSON 文件（供第二天主流程读取）
            if results:
                NightShiftDetector.save_night_shift_work_codes(results, save_hour)

            # 导出 Excel
            filepath = detector.export_to_excel(results)
            if filepath:
                logger.info(f"Excel 已导出: {filepath}")
    finally:
        fetcher.close()