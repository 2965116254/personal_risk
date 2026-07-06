# -*- coding: utf-8 -*-
"""
数据库查询层
封装所有数据库查询操作，包括操作票、违章记录、动态风险、基准关系等。
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import mysql.connector
from mysql.connector.cursor import MySQLCursorDict
from typing import List, Dict, Optional, Set, Tuple
import sql_queries


class DataFetcher:
    """数据库查询封装类"""

    def __init__(self, db_config: Dict):
        self.db_config = db_config
        self.connection = None
        self.cursor = None

    def connect(self):
        """建立数据库连接（使用无缓冲游标，避免大数据量时客户端内存溢出）"""
        self.connection = mysql.connector.connect(
            host=self.db_config['host'],
            port=self.db_config['port'],
            user=self.db_config['user'],
            password=self.db_config['password'],
            database=self.db_config['database'],
            connection_timeout=30,
        )
        # 使用 SSCursor（无缓冲游标）：结果集在服务端按需获取，避免客户端 C 层一次性缓存全部数据
        self.cursor = self.connection.cursor(dictionary=True, buffered=False)

    def close(self):
        """关闭数据库连接（兼容 SSCursor 未读结果）"""
        try:
            if self.cursor:
                self.cursor.close()
        except Exception:
            pass
        try:
            if self.connection:
                self.connection.close()
        except Exception:
            pass

    def _consume_pending(self):
        """消费 SSCursor 中可能残留的未读取结果（兜底保护）"""
        try:
            while True:
                row = self.cursor.fetchone()
                if row is None:
                    break
        except Exception:
            pass

    def fetchone(self, query: str, params=None) -> Optional[Dict]:
        """执行查询并返回单条记录"""
        self._consume_pending()
        self.cursor.execute(query, params or ())
        result = self.cursor.fetchone()
        # SSCursor 必须消费完所有结果才能执行下一条查询
        self._consume_pending()
        return result

    def fetchall(self, query: str, params=None) -> List[Dict]:
        """执行查询并返回所有记录"""
        self._consume_pending()
        self.cursor.execute(query, params or ())
        results = self.cursor.fetchall()
        # SSCursor 下 fetchall() 已取完所有数据，无需再次清空
        return results

    # ==================== 分批查询辅助 ====================

    def _batch_query(self, query_template: str, ids: List[str], batch_size: int = 5000) -> List[Dict]:
        """
        将 ID 列表分批执行 IN 查询，避免单次 IN 子句过长导致 SQL 报错
        使用 buffered cursor：每批最多 5000 行，内存占用可忽略，网络往返只需 1 次
        """
        all_results = []
        buf = self.connection.cursor(dictionary=True, buffered=True)
        try:
            for i in range(0, len(ids), batch_size):
                batch = ids[i:i + batch_size]
                placeholders = ','.join(['%s'] * len(batch))
                query = query_template.format(placeholders=placeholders)
                buf.execute(query, batch)
                all_results.extend(buf.fetchall())
        finally:
            buf.close()
        return all_results

    # ==================== 操作票查询 ====================

    def fetch_work_tickets(self, limit: int = None, query_start_date: str = None,
                          query_end_date: str = None) -> List[Dict]:
        """
        查询操作票数据（以 sp_ss_rc_work_plan 为主表）
        :param query_start_date: 查询时间区间开始，用于区间重叠判断 NOT(plan_end_time <= query_start_date)
        :param query_end_date:   查询时间区间结束，用于区间重叠判断 NOT(plan_start_time >= query_end_date)
        """
        query = """
        SELECT 
            wp.work_code,
            wb.ticket_no,
            wb.ticket_source_id,
            wp.bureau_code,
            wp.plan_start_time,
            wp.plan_end_time,
            wp.actual_start_time,
            wp.actual_end_time,
            wb.work_principal_uid,
            wb.work_principal_uname,
            wb.work_member_uid,
            wb.work_member_uname,
            wb.guardian_uid,
            wb.guardian_uname,
            wb.work_member_count,
            CASE wp.task_main
                WHEN '1.0' THEN '本单位'
                WHEN '2.0' THEN '总包单位作业'
                ELSE ''
            END AS task_main,
            wp.task_type,
            wp.work_content,
            wb.work_task
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
        """
        params = []
        if query_start_date and query_end_date:
            query += " AND ( NOT(wp.plan_end_time <= %s OR wp.plan_start_time >= %s) )"
            params.append(query_start_date + " 00:00:00")
            params.append(query_end_date + " 23:59:59")
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        return self.fetchall(query, params)

    def fetch_work_codes(self, query_start_date: str = None, query_end_date: str = None) -> List[str]:
        """
        轻量查询：只返回满足时间条件的 work_code 列表（不关联工作票表，速度快）
        :param query_start_date: 查询时间区间开始
        :param query_end_date: 查询时间区间结束
        :return: work_code 字符串列表
        """
        query = """
        SELECT wp.work_code
        FROM sp_ss_rc_work_plan wp
        WHERE wp.task_state IN ('2.0', '3.0', '6.0')
        """
        params = []
        if query_start_date and query_end_date:
            query += " AND ( NOT(wp.plan_end_time <= %s OR wp.plan_start_time >= %s) )"
            params.append(query_start_date + " 00:00:00")
            params.append(query_end_date + " 23:59:59")
        rows = self.fetchall(query, params)
        return [row['work_code'] for row in rows]

    def fetch_work_tickets_by_codes(self, work_codes: List[str]) -> List[Dict]:
        """
        根据指定的作业计划编号列表查询操作票数据
        """
        if not work_codes:
            return []
        query = """
        SELECT
            wp.work_code,
            wb.ticket_no,
            wb.ticket_source_id,
            wp.bureau_code,
            wp.plan_start_time,
            wp.plan_end_time,
            wp.actual_start_time,
            wp.actual_end_time,
            wb.work_principal_uid,
            wb.work_principal_uname,
            wb.work_member_uid,
            wb.work_member_uname,
            wb.guardian_uid,
            wb.guardian_uname,
            wb.work_member_count,
            CASE wp.task_main
                WHEN '1.0' THEN '本单位'
                WHEN '2.0' THEN '总包单位作业'
                ELSE ''
            END AS task_main,
            wp.task_type,
            wp.work_content,
            wb.work_task
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
        WHERE wp.work_code IN ({placeholders})
        """
        return self._batch_query(query, work_codes)

    # ==================== 违章记录查询 ====================

    def fetch_peccancy_records(self, user_ids: List[str]) -> Dict[str, Dict[str, int]]:
        """
        批量查询违章记录（分批查询，避免 IN 子句过长）
        :return: {user_key: {'A': count, 'B': count, ...}, ...}
        """
        if not user_ids:
            return {}
        query = """
        SELECT peccancy_uid, peccancy_code, peccancy_uname, COUNT(*) AS count, record_date
        FROM sp_ss_uq_peccancy_list_log 
        WHERE peccancy_uid IN ({placeholders})
        AND record_date >= DATE_FORMAT(CURDATE(), '%Y-01-01')
        AND record_date < DATE_FORMAT(CURDATE() + INTERVAL 1 YEAR, '%Y-01-01')
        GROUP BY peccancy_uid, peccancy_code, peccancy_uname, record_date;
        """
        records = self._batch_query(query, user_ids)

        peccancy_dict = {}
        for r in records:
            user_key = r['peccancy_uid']
            code = r['peccancy_code']
            if user_key not in peccancy_dict:
                peccancy_dict[user_key] = {}
            if code:
                vtype = code[0].upper()
                peccancy_dict[user_key][vtype] = peccancy_dict[user_key].get(vtype, 0) + r['count']
        return peccancy_dict

    # ==================== 用户姓名映射查询 ====================

    def fetch_user_name_map(self, user_ids: List[str]) -> Dict[str, str]:
        """
        批量查询用户ID对应的姓名（从违章记录表获取）
        :param user_ids: 用户ID列表
        :return: {peccancy_uid: peccancy_uname}
        """
        if not user_ids:
            return {}
        query = """
        SELECT peccancy_uid, peccancy_uname
        FROM sp_ss_uq_peccancy_list_log
        WHERE peccancy_uid IN ({placeholders})
        AND peccancy_uname IS NOT NULL AND peccancy_uname != ''
        GROUP BY peccancy_uid, peccancy_uname
        """
        records = self._batch_query(query, user_ids)
        # 如果一个uid有多条记录取第一条的uname
        result = {}
        for r in records:
            uid = r['peccancy_uid']
            if uid not in result:
                result[uid] = r['peccancy_uname']
        return result

    # ==================== 动火作业票查询 ====================

    def fetch_hot_work_tickets(self, work_codes: List[str]) -> Dict[str, str]:
        """
        批量查询动火作业票
        :return: {work_code: 动火票票号}
        """
        if not work_codes:
            return {}
        query = """
        SELECT wp.work_code, wf.ticket_no AS '动火票票号'
        FROM sp_ss_rc_work_plan wp 
        LEFT JOIN sp_pd_wticket_business_re wbr ON wp.work_code = wbr.business_name 
        LEFT JOIN sp_pd_wticket_fire wf ON wbr.wticket_id = wf.wticket_id 
        WHERE wp.work_code IN ({placeholders}) AND wf.ticket_no IS NOT NULL
        """
        records = self._batch_query(query, work_codes)
        return {r['work_code']: r.get('动火票票号') for r in records}

    # ==================== 作业计划详情查询 ====================

    def fetch_work_plan_details(self, work_codes: List[str]) -> Dict[str, Dict]:
        """
        批量查询作业计划详情
        :return: {work_code: {work_place, major_sub_type, work_content, ...}}
        """
        if not work_codes:
            return {}
        query = """
        SELECT id, work_code, work_place, major_sub_type, work_content,
               release_time, plan_start_time, plan_end_time,
               actual_start_time, actual_end_time
        FROM sp_ss_rc_work_plan
        WHERE work_code IN ({placeholders})
        """
        records = self._batch_query(query, work_codes)
        return {r['work_code']: r for r in records}

    # ==================== 动态风险分值查询 ====================

    def fetch_dynamic_risk_scores(self, work_codes: List[str]) -> Dict[str, Dict[str, float]]:
        """
        批量查询客户填入的动态风险评估分值
        :return: {work_code: {评估因子: 分值}, ...}
        """
        if not work_codes:
            return {}
        query = """
        SELECT A.WORK_CODE, B.ITEM_NAME AS ASSESS_FACTOR, B.ASSESS_VALUE AS CUSTOMER_SCORE
        FROM sp_ss_rc_work_plan A
        LEFT JOIN sp_ss_rc_dynamic_risk_assess B ON A.ID = B.WORK_PLAN_ID
        WHERE A.WORK_CODE IN ({placeholders})
        """
        records = self._batch_query(query, work_codes)
        result = {}
        for r in records:
            wc = r['WORK_CODE']
            if wc not in result:
                result[wc] = {}
            result[wc][r['ASSESS_FACTOR']] = float(r['CUSTOMER_SCORE']) if r['CUSTOMER_SCORE'] else 0.0
        return result

    # ==================== 电网、设备风险维度查询（DIMENSION_TYPE = '3.00'） ====================

    def fetch_dynamic_risk_scores_d(self, work_codes: List[str]) -> Dict[str, List[Dict]]:
        """
        批量查询电网、设备风险维度（DIMENSION_TYPE = '3.00'）的人工评估分值
        :return: {work_code: [{评估因子, 评估结果项, 风险值得分}, ...]}
        """
        if not work_codes:
            return {}
        query = """
        SELECT A.WORK_CODE, B.ITEM_NAME AS ASSESS_FACTOR, 
               B.ASSESS_RESULT AS ASSESS_RESULT, B.ASSESS_VALUE AS CUSTOMER_SCORE
        FROM sp_ss_rc_work_plan A
        LEFT JOIN sp_ss_rc_dynamic_risk_assess B ON A.ID = B.WORK_PLAN_ID
        WHERE A.WORK_CODE IN ({placeholders}) AND B.DIMENSION_TYPE = '3.00'
        """
        records = self._batch_query(query, work_codes)
        result = {}
        for r in records:
            wc = r['WORK_CODE']
            if wc not in result:
                result[wc] = []
            result[wc].append({
                '评估因子': r['ASSESS_FACTOR'] or '',
                '评估结果项': r['ASSESS_RESULT'] or '',
                '风险值得分': float(r['CUSTOMER_SCORE']) if r['CUSTOMER_SCORE'] else 0.0,
            })
        return result

    # ==================== 基准关系查询 ====================

    def fetch_benchmark_relations(self, work_codes: List[str],
                                   work_plan_details: Dict[str, Dict] = None) -> Dict[str, List[Dict]]:
        """
        批量查询基准关系（典型基准风险值）
        :param work_plan_details: 已查询的作业计划详情，用于 id->work_code 映射
        :return: {work_code: [{benchmark_name, risk_value}, ...]}
        """
        if not work_codes:
            return {}
        query = sql_queries.BENCHMARK_RELATION_QUERY
        records = self._batch_query(query, work_codes)
        return self._group_benchmark_records(records, work_plan_details or {})

    @staticmethod
    def _group_benchmark_records(records: List[Dict], work_plan_details: Dict[str, Dict]) -> Dict[str, List[Dict]]:
        """将基准关系记录按 work_code 分组（使用已有的 work_plan_details 做映射）"""
        # 建立 id -> work_code 的映射（从已有 work_plan_details 中获取）
        id_to_work_code = {}
        for wc, details in work_plan_details.items():
            if details.get('id'):
                id_to_work_code[details['id']] = wc

        result = {}
        for r in records:
            wc = r.get('work_code', '')
            if not wc and r.get('id') in id_to_work_code:
                wc = id_to_work_code[r['id']]
            if wc:
                if wc not in result:
                    result[wc] = []
                rv = r.get('RISK_VALUE')
                if rv is None:
                    rv = 0
                result[wc].append({
                    'benchmark_name': r.get('BENCHMARK_NAME', ''),
                    'risk_value': rv,
                })
        return result

    # ==================== 预计算相关查询 ====================

    def fetch_precalc_work_tickets(self, target_date: str) -> List[Dict]:
        """查询预计算用工作票数据"""
        start_dt = f"{target_date} 00:00:00"
        end_dt = f"{target_date} 23:59:59"
        query = """
        SELECT DISTINCT
            wb.id AS ticket_id, wb.ticket_no, wb.ticket_source_id,
            wb.work_principal_uid, wb.work_member_uid, wb.guardian_uid,
            wb.work_member_count, wp.task_main, wp.work_code, wp.task_type,
            wp.plan_start_time, wp.release_time, wp.work_place,
            wp.major_sub_type, wp.work_content, wb.work_task
        FROM sp_pd_wticket_base wb
        JOIN sp_ss_rc_work_plan wp ON wb.ticket_source_id = wp.id
        WHERE wp.create_time >= %s AND wp.create_time <= %s
        """
        return self.fetchall(query, (start_dt, end_dt))

    def fetch_batch_same_type_scores(self, user_ids: List[str]) -> Dict[str, Dict[str, Dict]]:
        """
        批量查询同类型作业次数
        :return: {leader_uid: {task_type: {count, score}}}
        """
        if not user_ids:
            return {}
        query = sql_queries.BATCH_SAME_TYPE_QUERY
        records = self._batch_query(query, user_ids)
        result = {}
        for r in records:
            uid = r['leader_uid']
            tt = r['task_type']
            if uid not in result:
                result[uid] = {}
            result[uid][tt] = {
                'count': r.get('same_type_work_count', 0),
                'score': r.get('risk_score', 0) or 0,
            }
        return result

    def create_daily_result_table(self):
        """创建预计算结果表"""
        query = sql_queries.CREATE_MACHINE_DAILY_RESULT_TABLE
        self.cursor.execute(query)
        self.cursor.fetchall()  # SSCursor 必须消费结果
        self.connection.commit()

    def insert_daily_result(self, record: Dict):
        """插入预计算结果"""
        query = """
        INSERT INTO sp_ss_rc_machine_daily_result (
            ticket_no, work_code, work_task, risk_score, b_score, c_score, d_score,
            work_member_count, principal_nature, work_location, work_type, plan_nature, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON DUPLICATE KEY UPDATE
            risk_score = VALUES(risk_score), b_score = VALUES(b_score),
            c_score = VALUES(c_score), d_score = VALUES(d_score),
            work_member_count = VALUES(work_member_count),
            principal_nature = VALUES(principal_nature),
            work_location = VALUES(work_location),
            work_type = VALUES(work_type), plan_nature = VALUES(plan_nature),
            updated_at = NOW()
        """
        self.cursor.execute(query, (
            record['ticket_no'], record['work_code'], record['work_task'],
            record['risk_score'], record['b_score'], record['c_score'], record['d_score'],
            record['work_member_count'], record['principal_nature'],
            record['work_location'], record['work_type'], record['plan_nature'],
        ))
        self.cursor.fetchall()  # SSCursor 必须消费结果