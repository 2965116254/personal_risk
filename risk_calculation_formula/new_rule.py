# -*- coding: utf-8 -*-
# @Project ：personal_risk_prevention_algo 
# @FileName: new_rule.py
# @Author  : 
# @Time    : 2026/4/21

import mysql.connector
from mysql.connector import Error
import config_loader
import os
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from datetime import datetime


def calculate_risk_score(db_config, limit=None, start_date=None, end_date=None):
    """
    根据评估因子的评估结果计算风险值得分
    
    参数:
    db_config: 数据库配置字典
    limit: 限制返回记录数
    start_date: 开始日期，默认为None
    end_date: 结束日期，默认为None
    
    返回:
    列表，包含每个评估对象的详细信息和风险得分
    """
    all_results = []
    
    try:
        # 创建数据库连接
        connection = mysql.connector.connect(
            host=db_config['host'],
            port=db_config['port'],
            user=db_config['user'],
            password=db_config['password'],
            database=db_config['database']
        )
        print("数据库连接成功")
        
        cursor = connection.cursor(dictionary=True)
        
        # 查询操作票表数据，关联作业计划表以过滤时间范围，并获取作业计划信息
        query = """
        SELECT 
            wb.id,                  -- 主键ID
            wb.ticket_no,           -- 工作票票号
            wb.ticket_source_id,    -- 作业计划表关联ID
            wb.work_principal_uid,  -- 工作负责人ID
            wb.work_member_uid,     -- 工作班人员ID
            wb.guardian_uid,        -- 专责监护人ID
            wb.work_member_count,   -- 工作班人员总数
            wp.task_main,           -- 作业主体
            wp.work_code,           -- 作业计划编号
            wp.task_type            -- 作业类型
        FROM sp_pd_wticket_base wb
        JOIN sp_ss_rc_work_plan wp ON wb.ticket_source_id = wp.id
        """
        
        # 添加时间范围过滤
        where_clause = []
        params = []
        
        if start_date:
            where_clause.append("wp.create_time >= %s")
            params.append(start_date)
        if end_date:
            where_clause.append("wp.create_time <= %s")
            params.append(end_date)
        
        if where_clause:
            query += " WHERE " + " AND ".join(where_clause)
        
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        
        print("执行查询操作票表...")
        cursor.execute(query, params)
        work_tickets = cursor.fetchall()
        # 确保结果被完全获取
        cursor.fetchall()
        
        if not work_tickets:
            print("没有找到任何操作票")
            return None
        
        print(f"找到 {len(work_tickets)} 张操作票")
        
        # 收集所有需要查询违章的人员ID和需要查询同类型作业次数的人员ID
        all_user_ids = set()
        all_same_type_ids = set()
        task_types = {}
        
        for ticket in work_tickets:
            # 收集违章查询人员ID
            if ticket.get('work_principal_uid'):
                all_user_ids.add(ticket.get('work_principal_uid'))
                all_same_type_ids.add(ticket.get('work_principal_uid'))
            if ticket.get('work_member_uid'):
                # 工作班人员ID可能是逗号分隔的多个ID
                member_ids = ticket.get('work_member_uid').split(',')
                for mid in member_ids:
                    if mid.strip():
                        all_user_ids.add(mid.strip())
                        all_same_type_ids.add(mid.strip())
            if ticket.get('guardian_uid'):
                all_user_ids.add(ticket.get('guardian_uid'))
                all_same_type_ids.add(ticket.get('guardian_uid'))
            
            # 保存任务类型
            task_types[ticket.get('ticket_source_id')] = ticket.get('task_type')
        
        print(f"共收集 {len(all_user_ids)} 个人员ID")
        print(f"共收集 {len(all_same_type_ids)} 个需要查询同类型作业次数的人员ID")
        
        # 查询违章记录
        peccancy_dict = {}
        if all_user_ids:
            placeholders = ','.join(['%s'] * len(all_user_ids))
            peccancy_query = f"""
            SELECT 
                peccancy_uid,
                peccancy_code,
                COUNT(*) as count
            FROM sp_ss_uq_peccancy_list_log 
            WHERE peccancy_uid IN ({placeholders})
            AND record_date BETWEEN DATE_SUB(CURDATE(), INTERVAL 1 YEAR) AND CURDATE()
            GROUP BY peccancy_uid, peccancy_code
            """
            peccancy_params = list(all_user_ids)
            print("执行查询违章记录...")
            cursor.execute(peccancy_query, peccancy_params)
            peccancy_records = cursor.fetchall()
            # 确保结果被完全获取
            cursor.fetchall()
            
            print(f"找到 {len(peccancy_records)} 条违章记录")
            
            # 构建违章记录字典
            for record in peccancy_records:
                peccancy_uid = record['peccancy_uid']
                if peccancy_uid not in peccancy_dict:
                    peccancy_dict[peccancy_uid] = {}
                peccancy_code = record['peccancy_code']
                if peccancy_code:
                    violation_type = peccancy_code[0].upper()  # 获取违章类型（第一个字母）
                    if violation_type not in peccancy_dict[peccancy_uid]:
                        peccancy_dict[peccancy_uid][violation_type] = 0
                    peccancy_dict[peccancy_uid][violation_type] += record['count']
        
        # 批量查询同类型作业次数
        same_type_dict = {}
        if all_same_type_ids:
            placeholders = ','.join(['%s'] * len(all_same_type_ids))
            same_type_query = f"""
            WITH task_stats AS (
                SELECT
                    work_master_uid AS leader_uid,
                    task_type,
                    COUNT(1) AS total_count,
                    SUM(CASE WHEN create_time >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR) THEN 1 ELSE 0 END) AS cnt_last_1year,
                    SUM(CASE WHEN create_time >= DATE_SUB(CURDATE(), INTERVAL 2 YEAR) THEN 1 ELSE 0 END) AS cnt_last_2year
                FROM sp_ss_rc_work_plan
                WHERE work_master_uid IN ({placeholders})
                  AND work_master_uid IS NOT NULL
                  AND task_type IS NOT NULL
                GROUP BY work_master_uid, task_type
            )
            SELECT
                leader_uid,
                task_type,
                total_count AS same_type_work_count,
                CASE
                    WHEN cnt_last_1year >= 2 OR cnt_last_2year >= 5 THEN 0
                    WHEN total_count = 1 THEN 6
                    WHEN total_count < 3 THEN 5
                    WHEN total_count BETWEEN 3 AND 4 THEN 3
                    WHEN total_count >= 5 THEN 2
                    ELSE 0
                END AS risk_score
            FROM task_stats
            """
            same_type_params = list(all_same_type_ids)
            print("执行批量查询同类型作业次数...")
            cursor.execute(same_type_query, same_type_params)
            same_type_records = cursor.fetchall()
            # 确保结果被完全获取
            cursor.fetchall()
            
            print(f"找到 {len(same_type_records)} 条同类型作业记录")
            
            # 构建同类型作业次数字典
            for record in same_type_records:
                leader_uid = record['leader_uid']
                task_type = record['task_type']
                if leader_uid not in same_type_dict:
                    same_type_dict[leader_uid] = {}
                same_type_dict[leader_uid][task_type] = {
                    'count': record.get('same_type_work_count', 0),
                    'score': record.get('risk_score', 0) or 0
                }
        
        # 处理每张操作票
        print("开始计算风险值...")
        for ticket in work_tickets:
            # 初始化分数
            B = 0  # 作业人员能力风险值
            C = 0  # 作业环境和时间影响风险值
            D = 0  # 电网、设备风险联动值
            F = 0  # 总风险值
            
            # 1. 计算作业人员能力风险值 (B)
            
            # 1.1 工作负责人安全意识
            work_principal_uid = ticket.get('work_principal_uid')
            principal_score = calculate_person_safety_awareness_score(peccancy_dict.get(work_principal_uid, {}))
            B += principal_score
            
            # 1.2 主要工作班成员安全意识
            work_member_uid = ticket.get('work_member_uid')
            member_score = 0
            if work_member_uid:
                member_ids = work_member_uid.split(',')
                for mid in member_ids:
                    if mid.strip():
                        member_score += calculate_person_safety_awareness_score(peccancy_dict.get(mid.strip(), {}))
            B += member_score
            
            # 1.3 监护人安全意识
            guardian_uid = ticket.get('guardian_uid')
            guardian_score = calculate_person_safety_awareness_score(peccancy_dict.get(guardian_uid, {}))
            B += guardian_score
            
            # 1.4 作业总人数
            work_member_count = ticket.get('work_member_count')
            work_count_score = calculate_work_total_count_score(work_member_count)
            B += work_count_score
            
            # 1.5 负责人的人员性质
            principal_nature = "未知"
            principal_nature_score = 0
            work_code = ticket.get('work_code', "")
            task_main = ticket.get('task_main')
            
            try:
                if task_main:
                    # 直接根据作业主体的值确定人员性质和风险值
                    try:
                        task_main_float = float(task_main)
                        if task_main_float == 1.0:
                            principal_nature = "本单位-系统内人员"
                            principal_nature_score = 0  # 本单位人员
                        else:
                            principal_nature = "外单位-系统外人员"
                            principal_nature_score = 5  # 外施工单位人员
                    except (ValueError, TypeError):
                        principal_nature = "未知人员性质"
                        principal_nature_score = 5  # 默认外施工单位人员
            except Exception as e:
                print(f"处理负责人人员性质时出错: {e}")
            
            # 1.6 工作负责人组织同类型作业次数
            principal_same_type_count = 0
            principal_same_type_score = 0
            task_type = ticket.get('task_type')
            
            try:
                if work_principal_uid and task_type:
                    # 从批量查询结果中获取
                    if work_principal_uid in same_type_dict and task_type in same_type_dict[work_principal_uid]:
                        principal_same_type_count = same_type_dict[work_principal_uid][task_type]['count']
                        principal_same_type_score = same_type_dict[work_principal_uid][task_type]['score']
            except Exception as e:
                print(f"处理工作负责人同类型作业次数时出错: {e}")
            
            # 1.7 主要工作班成员参与同类型作业次数
            member_same_type_count = 0
            member_same_type_score = 0
            
            try:
                if work_member_uid and task_type:
                    # 处理工作班成员ID
                    member_ids = work_member_uid.split(',')
                    for mid in member_ids:
                        if mid.strip():
                            member_id = mid.strip()
                            # 从批量查询结果中获取
                            if member_id in same_type_dict and task_type in same_type_dict[member_id]:
                                member_same_type_count += same_type_dict[member_id][task_type]['count']
                                if same_type_dict[member_id][task_type]['score'] > member_same_type_score:
                                    member_same_type_score = same_type_dict[member_id][task_type]['score']
                    
                    print(f"[DEBUG] 主要工作班成员同类型作业次数: {member_same_type_count}, 风险值: {member_same_type_score}")
            except Exception as e:
                print(f"处理主要工作班成员同类型作业次数时出错: {e}")
            
            # 1.8 监护人参与同类型作业次数
            guardian_same_type_count = 0
            guardian_same_type_score = 0
            
            try:
                if guardian_uid and task_type:
                    # 从批量查询结果中获取
                    if guardian_uid in same_type_dict and task_type in same_type_dict[guardian_uid]:
                        guardian_same_type_count = same_type_dict[guardian_uid][task_type]['count']
                        guardian_same_type_score = same_type_dict[guardian_uid][task_type]['score']
                    
                    print(f"[DEBUG] 监护人同类型作业次数: {guardian_same_type_count}, 风险值: {guardian_same_type_score}")
            except Exception as e:
                print(f"处理监护人同类型作业次数时出错: {e}")
            
            # 1.9 作业地段、类型
            work_location = "未知"
            work_type = "未知"
            work_location_score = 0
            try:
                # 查询作业计划表获取工作地点、专业二级分类、工作内容
                work_plan_query = """
                SELECT work_place, major_sub_type, work_content FROM sp_ss_rc_work_plan WHERE id = %s
                """
                cursor.execute(work_plan_query, [ticket.get('ticket_source_id')])
                work_plan = cursor.fetchone()
                # 确保结果被完全获取
                cursor.fetchall()
                
                if work_plan:
                    work_place = work_plan.get('work_place', '')
                    major_sub_type = work_plan.get('major_sub_type', '')
                    work_content = work_plan.get('work_content', '')
                    
                    # 根据工作内容判断地段
                    if '城区' in work_content or '市中心' in work_content:
                        work_location = '城区'
                    elif '郊区' in work_content or '农村' in work_content:
                        work_location = '郊区'
                    elif '山区' in work_content:
                        work_location = '山区'
                    else:
                        work_location = work_place if work_place else "其他地段"
                    
                    # 根据工作内容判断作业类型
                    if '抢修' in work_content or '故障' in work_content:
                        work_type = '抢修作业'
                    elif '检修' in work_content or '维护' in work_content:
                        work_type = '检修作业'
                    elif '巡视' in work_content:
                        work_type = '巡视作业'
                    elif '带电作业' in work_content:
                        work_type = '带电作业'
                    else:
                        work_type = major_sub_type if major_sub_type else "常规作业"
                    
                    # 计算作业地段风险值
                    if '有限空间' in work_content:
                        if '完备' in work_content or '良好' in work_content:
                            work_location_score += 3  # 有限空间内作业:风、水、电和空气监测设施完备、信号传输良好
                        else:
                            work_location_score += 10  # 有限空间内作业:风、水、电和空气监测设施不完备、信号传输不良
                    elif '氧气不足' in work_content or '有毒有害' in work_content:
                        work_location_score += 999  # 有限空间环境当氧气不足或有毒有害气体含量超标时，禁止作业
                    elif '多回共塔' in work_content or '带电线路' in work_content:
                        work_location_score += 10  # 作业区段内包含(双)多回共塔带电线路
                    elif '林区' in work_content:
                        work_location_score += 15  # 林区内作业
                    elif '地质隐患' in work_content:
                        work_location_score += 15  # 地质隐患区内作业
                    elif '导地线' in work_content or '光缆脱落' in work_content or '重要交叉' in work_content:
                        work_location_score += 30  # 可能造成导、地线、光缆脱落的作业，区段内包含重要交叉跨越
                    else:
                        work_location_score += 0  # 无特殊地段
                    
                    # 计算作业类型风险值
                    if '地面' in work_content or '1.5米以下' in work_content:
                        work_location_score += 0  # 地面以上1.5米以下
                    elif '1.5米以上' in work_content and '5米以下' in work_content:
                        work_location_score += 2  # 1.5米以上5米以下
                    elif '5米以上' in work_content and '15米以下' in work_content:
                        work_location_score += 5  # 5米以上15米以下
                    elif '15米以上' in work_content and '30米以下' in work_content:
                        work_location_score += 7  # 15米以上30米以下
                    elif '30米以上' in work_content:
                        work_location_score += 10  # 30米以上
                    elif '动火' in work_content:
                        work_location_score += 5  # 动火作业
                    elif '吊装' in work_content:
                        work_location_score += 5  # 大型吊装作业
            except Exception as e:
                print(f"查询作业地段、类型时出错: {e}")
            
            # 1.10 计划性质
            plan_nature = "未知"
            plan_nature_score = 0
            try:
                # 查询作业计划表获取计划类型、创建时间和计划开始时间
                ticket_source_id = ticket.get('ticket_source_id')
                work_plan_query = """
                SELECT
                    id,
                    plan_type,
                    release_time,
                    plan_start_time,
                    CASE CAST(plan_type AS SIGNED)
                        WHEN 1 THEN '计划性工作'
                        WHEN 2 THEN '临时性工作'
                        ELSE '未知'
                    END AS work_nature
                FROM sp_ss_rc_work_plan
                WHERE id = %s
                """
                cursor.execute(work_plan_query, [ticket_source_id])
                work_plan = cursor.fetchone()
                # 确保结果被完全获取
                cursor.fetchall()
                
                if work_plan:
                    work_nature = work_plan.get('work_nature')
                    create_time = work_plan.get('release_time')
                    plan_begin_time = work_plan.get('plan_start_time')
                    
                    # 判断计划性质
                    if work_nature == "计划性工作":
                        plan_nature = "计划性工作"
                        plan_nature_score = 0
                    elif work_nature == "临时性工作":
                        # 判断是提前一日制定还是当日制定
                        if create_time and plan_begin_time:
                            # 计算创建时间和计划开始时间的天数差
                            create_date = create_time.date() if hasattr(create_time, 'date') else create_time
                            plan_begin_date = plan_begin_time.date() if hasattr(plan_begin_time, 'date') else plan_begin_time
                            
                            # 计算天数差
                            days_diff = (plan_begin_date - create_date).days
                            
                            if days_diff >= 1:
                                # 提前一日制定的临时性作业任务
                                plan_nature = "提前一日制定的临时性作业任务"
                                plan_nature_score = 10
                            else:
                                # 当日制定的临时性作业任务
                                plan_nature = "当日制定的临时性作业任务"
                                plan_nature_score = 20
                        else:
                            # 无法判断，默认按当日制定处理
                            plan_nature = "当日制定的临时性作业任务"
                            plan_nature_score = 20
                    else:
                        plan_nature = "未知"
                        plan_nature_score = 0
                else:
                    print(f"[DEBUG] 未找到对应的作业计划: ticket_source_id={ticket_source_id}")
            except Exception as e:
                print(f"查询计划性质时出错: {e}")
            
            # 计算风险值总和
            # 1.5-1.8, 1.10 属于B值（作业人员能力风险值）
            B += principal_nature_score
            B += principal_same_type_score
            B += member_same_type_score
            B += guardian_same_type_score
            B += plan_nature_score
            
            # 1.9 属于C值（作业环境和时间影响风险值）
            C = work_location_score
            
            # 3. 电网、设备风险联动值 (D) - 暂时不需要
            D = 0
            
            # 4. 计算总风险值 (F = B + C + D)
            F = B + C + D
            
            # 生成详细的评估记录
            detailed_results = []
            
            # 工作负责人安全意识
            principal_violations = peccancy_dict.get(work_principal_uid, {})
            principal_result = "无违章" if not principal_violations else ",".join([f"{k}类{principal_violations[k]}次" for k in principal_violations])
            detailed_results.append({
                '工作票票号': ticket.get('ticket_no'),
                '作业计划编号': work_code,
                '评估因子': '工作负责人(含小组工作负责人)安全意识',
                '评估结果名称': '安全意识',
                '评估结果': principal_result,
                '风险值得分': principal_score
            })
            
            # 主要工作班成员安全意识
            member_violations = {}
            if work_member_uid:
                member_ids = work_member_uid.split(',')
                for mid in member_ids:
                    if mid.strip():
                        member_viol_id = mid.strip()
                        if member_viol_id in peccancy_dict:
                            for k, v in peccancy_dict[member_viol_id].items():
                                if k not in member_violations:
                                    member_violations[k] = 0
                                member_violations[k] += v
            member_result = "无违章" if not member_violations else ",".join([f"{k}类{member_violations[k]}次" for k in member_violations])
            detailed_results.append({
                '工作票票号': ticket.get('ticket_no'),
                '作业计划编号': work_code,
                '评估因子': '主要工作班成员(辅助工除外)安全意识',
                '评估结果名称': '安全意识',
                '评估结果': member_result,
                '风险值得分': member_score
            })
            
            # 监护人安全意识
            guardian_violations = peccancy_dict.get(guardian_uid, {})
            guardian_result = "无违章" if not guardian_violations else ",".join([f"{k}类{guardian_violations[k]}次" for k in guardian_violations])
            detailed_results.append({
                '工作票票号': ticket.get('ticket_no'),
                '作业计划编号': work_code,
                '评估因子': '监护人(含专职监护人)安全意识',
                '评估结果名称': '安全意识',
                '评估结果': guardian_result,
                '风险值得分': guardian_score
            })
            
            # 作业总人数
            count_result = str(work_member_count) if work_member_count else "未知"
            detailed_results.append({
                '工作票票号': ticket.get('ticket_no'),
                '作业计划编号': work_code,
                '评估因子': '作业总人数',
                '评估结果名称': '作业总人数',
                '评估结果': count_result,
                '风险值得分': work_count_score
            })
            
            # 负责人的人员性质
            detailed_results.append({
                '工作票票号': ticket.get('ticket_no'),
                '作业计划编号': work_code,
                '评估因子': '负责人的人员性质',
                '评估结果名称': '人员性质',
                '评估结果': principal_nature,
                '风险值得分': principal_nature_score
            })
            
            # 工作负责人组织同类型作业次数
            detailed_results.append({
                '工作票票号': ticket.get('ticket_no'),
                '作业计划编号': work_code,
                '评估因子': '工作负责人(含小组工作负责人)组织同类型作业次数',
                '评估结果名称': '同类型作业次数',
                '评估结果': str(principal_same_type_count),
                '风险值得分': principal_same_type_score
            })
            
            # 主要工作班成员参与同类型作业次数
            detailed_results.append({
                '工作票票号': ticket.get('ticket_no'),
                '作业计划编号': work_code,
                '评估因子': '主要工作班成员(辅助工除外)参与同类型作业次数',
                '评估结果名称': '同类型作业次数',
                '评估结果': str(member_same_type_count),
                '风险值得分': member_same_type_score
            })
            
            # 监护人参与同类型作业次数
            detailed_results.append({
                '工作票票号': ticket.get('ticket_no'),
                '作业计划编号': work_code,
                '评估因子': '监护人(含专职监护人)参与同类型作业次数',
                '评估结果名称': '同类型作业次数',
                '评估结果': str(guardian_same_type_count),
                '风险值得分': guardian_same_type_score
            })
            
            # 作业地段、类型
            detailed_results.append({
                '工作票票号': ticket.get('ticket_no'),
                '作业计划编号': work_code,
                '评估因子': '作业地段、类型',
                '评估结果名称': '作业地段、类型',
                '评估结果': f"地段: {work_location}, 类型: {work_type}",
                '风险值得分': work_location_score
            })
            
            # 计划性质
            detailed_results.append({
                '工作票票号': ticket.get('ticket_no'),
                '作业计划编号': work_code,
                '评估因子': '计划性质',
                '评估结果名称': '计划性质',
                '评估结果': plan_nature,
                '风险值得分': plan_nature_score
            })
            
            # 添加记录
            result = {
                '工作票票号': ticket.get('ticket_no'),
                '作业计划编号': work_code,
                'B（作业人员能力风险值）': B,
                'C（作业环境和时间影响风险值）': C,
                'D（电网、设备风险联动值）': D,
                'F（总风险值）': F,
                '详细评估结果': detailed_results
            }
            all_results.append(result)
            
            print(f"工作票 {ticket.get('ticket_no')} 风险评估完成，总风险值: {F}")
    
    except Exception as e:
        print(f"数据库错误: {e}")
        return None
    
    finally:
        # 关闭连接
        if 'cursor' in locals():
            cursor.close()
            print("数据库游标已关闭")
        if 'connection' in locals():
            connection.close()
            print("数据库连接已关闭")
    
    return all_results


def calculate_safety_awareness_score(awareness_level):
    """计算安全意识评分"""
    if not awareness_level:
        return 0
    
    # 根据Excel规则映射分数
    awareness_map = {
        '1年内累计1次及以上A类违章': 6,
        '1年内累计1次及以上B类违章': 5,
        '1年内累计1次及以上C类违章': 3,
        '1年内累计3次及以上D类违章': 2,
        '1年内0-2次D类违章': 0
    }
    
    return awareness_map.get(awareness_level, 0)


def calculate_person_safety_awareness_score(peccancy_records):
    """根据人员违章记录计算安全意识评分"""
    if not peccancy_records:
        return 0
    
    score = 0
    
    # 检查是否有A类违章
    if 'A' in peccancy_records:
        score += 6
    # 检查是否有B类违章
    elif 'B' in peccancy_records:
        score += 5
    # 检查是否有C类违章
    elif 'C' in peccancy_records:
        score += 3
    # 检查是否有D类违章
    elif 'D' in peccancy_records:
        d_count = peccancy_records['D']
        if d_count >= 3:
            score += 2
        else:
            score += 0
    
    return score


def calculate_work_total_count_score(count):
    """计算作业总人数评分"""
    if not count:
        return 0
    
    # 尝试将count转换为整数
    try:
        count = int(count)
    except (ValueError, TypeError):
        return 0
    
    # 根据Excel规则映射分数
    if count >= 50:
        return 15
    elif 24 <= count < 50:
        return 8
    elif 16 <= count < 24:
        return 5
    elif 8 <= count < 16:
        return 3
    elif 5 <= count < 8:
        return 1
    else:
        return 0


def calculate_temporary_change_score(change_status):
    """计算作业人员临时变更评分"""
    if not change_status:
        return 0
    
    # 根据Excel规则映射分数
    change_map = {
        '不超过5人': 0,
        '作业当日临时变更工作负责人': 5,
        '工作负责人在作业前(含工作间断后)1日确认': 0
    }
    
    return change_map.get(change_status, 0)


def calculate_personnel_nature_score(nature):
    """计算人员性质评分"""
    if not nature:
        return 0
    
    # 根据Excel规则映射分数
    nature_map = {
        '外施工单位劳务分包人员': 8,
        '外施工单位人员': 5,
        '本单位人员': 0
    }
    
    return nature_map.get(nature, 0)


def calculate_experience_score(experience):
    """计算作业经验评分"""
    if not experience:
        return 0
    
    # 根据Excel规则映射分数
    experience_map = {
        '第一次承担该类作业': 6,
        '累计不足3次但不是第一次': 5,
        '累计不足5次但不小于3次': 3,
        '不满足上述要求，但累计5次及以上': 2,
        '1年内2次及以上或2年内5次及以上': 0
    }
    
    return experience_map.get(experience, 0)


def calculate_mental_state_score(state):
    """计算精神状态评分"""
    if not state:
        return 0
    
    # 根据Excel规则映射分数
    state_map = {
        '很差': 999,
        '较差': 10,
        '一般': 2,
        '良好': 0
    }
    
    return state_map.get(state, 0)


def calculate_weather_score(weather):
    """计算天气评分"""
    if not weather:
        return 0
    
    # 根据Excel规则映射分数
    weather_map = {
        '天气舒适': 0,
        '户外作业小雨天气': 10,
        '气象部门发布天气预报信号后，户外作业受天气影响时': 10,
        '雷雨、雷电、风力大于五级时(台风、大风预警信号)不具备': 0
    }
    
    return weather_map.get(weather, 0)


def calculate_work_location_score(location):
    """计算作业地段评分"""
    if not location:
        return 0
    
    # 根据Excel规则映射分数
    location_map = {
        '无特殊地段': 0,
        '有限空间内作业:风、水、电和空气监测设施完备、信号传': 3,
        '有限空间内作业:风、水、电和空气监测设施不完备、信号传': 10,
        '有限空间环境当氧气不足或有毒有害气体含量超标时，禁止': 999,
        '作业区段内包含(双)多回共塔带电线路': 10,
        '林区内作业': 15,
        '地质隐患区内作业': 15,
        '可能造成导、地线、光缆脱落的作业，区段内包含重要交叉': 30
    }
    
    return location_map.get(location, 0)


def calculate_work_type_score(work_type):
    """计算作业类型评分"""
    if not work_type:
        return 0
    
    # 根据Excel规则映射分数
    type_map = {
        '地面以上1.5米以下': 0,
        '1.5米以上5米以下': 2,
        '5米以上15米以下': 5,
        '15米以上30米以下': 7,
        '30米以上': 10,
        '动火作业': 5,
        '大型吊装作业': 5
    }
    
    return type_map.get(work_type, 0)


def calculate_work_time_period_score(time_period):
    """计算作业时段评分"""
    if not time_period:
        return 0
    
    # 根据Excel规则映射分数
    period_map = {
        '正常时段作业': 0,
        '二级保供电期间涉及保供电设备的作业': 5,
        '站内或室内夜间作业(0点-次日6:00)': 20,
        '特级、一级保供电涉及保供电设备的作业、或春节等法定假': 30,
        '站外线路夜间作业(20:00-次日6:00)': 20
    }
    
    return period_map.get(time_period, 0)


def calculate_single_day_work_hours_score(hours):
    """计算单日持续作业时长评分"""
    if not hours:
        return 0
    
    # 根据Excel规则映射分数
    if hours <= 4:
        return 0
    elif 4 < hours <= 8:
        return 2
    elif 8 < hours <= 12:
        return 10
    else:
        return 20


def calculate_plan_nature_score(plan_nature):
    """计算计划性质评分"""
    if not plan_nature:
        return 0
    
    # 根据Excel规则映射分数
    plan_map = {
        '计划性作业': 0,
        '提前一日制定的临时性作业任务': 10,
        '当日制定的临时性作业任务': 20
    }
    
    return plan_map.get(plan_nature, 0)


def calculate_key_station_line_score(key_status):
    """计算关键重要站点(线路)评分"""
    if not key_status:
        return 0
    
    # 根据Excel规则映射分数
    key_map = {
        '非关键重要站点(线路)': 0,
        '关键重要站点(线路)': 5
    }
    
    return key_map.get(key_status, 0)


def calculate_accident_consequence_score(consequence):
    """计算事故后果评分"""
    if not consequence:
        return 0
    
    # 根据Excel规则映射分数
    consequence_map = {
        '无事故事件': 0,
        '造成电力安全四级及以下事件(相关风险': 0,
        '造成电力安全三级事件': 10,
        '造成电力安全二级事件': 40,
        '造成电力安全一级事件': 160,
        '造成一般电力安全事故': 180,
        '造成较大及以上电力安全事故或县域及以上大面积停电': 200
    }
    
    return consequence_map.get(consequence, 0)


def get_person_same_type_work_count(cursor, person_ids, task_type, filter_words=None):
    """
    查询人员的同类型作业次数
    
    参数:
    cursor: 数据库游标
    person_ids: 人员ID列表或逗号分隔的字符串
    task_type: 作业类型
    filter_words: 过滤词列表，默认为None
    
    返回:
    dict: 包含每个人员的作业次数和风险值
    """
    # 处理人员ID
    if isinstance(person_ids, str):
        # 如果是字符串，按逗号和分号分割
        person_ids = person_ids.replace(';', ',').split(',')
        # 过滤空字符串并去除首尾空格
        person_ids = [pid.strip() for pid in person_ids if pid.strip()]
    elif not isinstance(person_ids, list):
        # 如果不是列表，转换为单元素列表
        person_ids = [person_ids]
    
    # 构建查询参数
    results = {}
    
    # 过滤词列表，默认为空
    if filter_words is None:
        filter_words = []
    
    # 预定义的过滤词
    default_filter_words = ['吊车', '厂家', '公司', '单位','司机','指挥']
    # 合并过滤词
    all_filter_words = default_filter_words + filter_words
    
    for person_id in person_ids:
        if not person_id:
            continue
        
        # 检查是否包含过滤词
        skip = False
        for word in all_filter_words:
            if word in person_id:
                skip = True
                break
        if skip:
            continue
        
        # 检查是否为有效的ID或中文名
        # 这里简单处理：如果只包含标点符号或特殊字符，跳过
        if not any(c.isalnum() or '\u4e00' <= c <= '\u9fff' for c in person_id):
            continue
        
        # 查询同类型作业次数
        same_type_query = """
        SELECT
            COUNT(*) AS total_count,
            SUM(CASE WHEN create_time >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR) THEN 1 ELSE 0 END) AS cnt_last_1year,
            SUM(CASE WHEN create_time >= DATE_SUB(CURDATE(), INTERVAL 2 YEAR) THEN 1 ELSE 0 END) AS cnt_last_2year
        FROM sp_ss_rc_work_plan
        WHERE work_master_uid = %s AND task_type = %s
        """
        
        try:
            cursor.execute(same_type_query, [person_id, task_type])
            same_type_result = cursor.fetchone()
            # 确保结果被完全获取
            cursor.fetchall()
            
            if same_type_result:
                total_count = same_type_result.get('total_count', 0) or 0
                cnt_last_1year = same_type_result.get('cnt_last_1year', 0) or 0
                cnt_last_2year = same_type_result.get('cnt_last_2year', 0) or 0
                
                # 计算风险值
                if cnt_last_1year >= 2 or cnt_last_2year >= 5:
                    risk_score = 0
                elif total_count == 1:
                    risk_score = 6
                elif total_count < 3:
                    risk_score = 5
                elif total_count >= 3 and total_count <= 4:
                    risk_score = 3
                elif total_count >= 5:
                    risk_score = 2
                else:
                    risk_score = 0
                
                results[person_id] = {
                    'count': total_count,
                    'score': risk_score
                }
        except Exception as e:
            print(f"查询人员 {person_id} 同类型作业次数时出错: {e}")
            results[person_id] = {
                'count': 0,
                'score': 0
            }
    
    return results


def calculate_equipment_risk_score(equipment_risk):
    """计算设备风险评分"""
    if not equipment_risk:
        return 0
    
    # 根据Excel规则映射分数
    equipment_map = {
        '无设备风险影响作业典型场景': 0,
        '对《设备风险预警通知单》揭示的隐患设备开展作业，相关': 0,
        '在运行回路上使用万用表、螺丝刀等工器具开展作业，工器': 0,
        '开展保护装置、安自装置、操作箱及智能终端定检/维护/消': 45,
        '开展带电水冲洗作业': 140,
        '开展保护装置、安自装置、测控装置、操作箱及智能终端兑': 0,
        '开展双母线热倒母操作，操作涉及的母线侧刀闸存在超期未': 90,
        '手动操作隔离开关，操作涉及的隔离开关为单轴、单电机三': 70,
        '开展电气操作，操作涉及的设备在监控后台无法正确显示设': 70,
        '开展电气操作，操作涉及的设备存在微机五防、机械防误、': 70
    }
    
    return equipment_map.get(equipment_risk, 0)


def save_to_excel(results, output_dir=None):
    """
    将评估结果保存到Excel文件
    
    参数:
    results: 评估结果列表
    output_dir: 输出目录，默认为当前目录
    
    返回:
    保存的文件路径
    """
    if not results:
        print("没有数据可保存")
        return None
    
    # 设置输出目录
    if output_dir is None:
        output_dir = os.path.join(os.getcwd(), "output")
    
    # 创建输出目录
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"创建目录: {output_dir}")
    
    # 生成文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f'风险评估结果_{timestamp}.xlsx'
    filepath = os.path.join(output_dir, filename)
    
    # 创建Excel工作簿
    wb = Workbook()
    
    # 创建详细评估结果工作表
    ws_detail = wb.active
    ws_detail.title = "详细评估结果"
    
    # 定义详细评估结果表头
    detail_headers = [
        '工作票票号',
        '作业计划编号',
        '评估因子',
        '评估结果名称',
        '评估结果',
        '风险值得分'
    ]
    
    # 写入详细评估结果表头
    for col_num, header in enumerate(detail_headers, 1):
        ws_detail.cell(row=1, column=col_num, value=header)
    
    # 写入详细评估结果数据
    row_num = 2
    for result in results:
        detailed_results = result.get('详细评估结果', [])
        for detail in detailed_results:
            ws_detail.cell(row=row_num, column=1, value=detail.get('工作票票号', ''))
            ws_detail.cell(row=row_num, column=2, value=detail.get('作业计划编号', ''))
            ws_detail.cell(row=row_num, column=3, value=detail.get('评估因子', ''))
            ws_detail.cell(row=row_num, column=4, value=detail.get('评估结果名称', ''))
            ws_detail.cell(row=row_num, column=5, value=detail.get('评估结果', ''))
            ws_detail.cell(row=row_num, column=6, value=detail.get('风险值得分', 0))
            row_num += 1
    
    # 调整详细评估结果列宽
    detail_column_widths = {
        1: 30,
        2: 20,
        3: 40,
        4: 15,
        5: 40,
        6: 15
    }
    for col, width in detail_column_widths.items():
        ws_detail.column_dimensions[get_column_letter(col)].width = width
    
    # 创建总风险值工作表
    ws_summary = wb.create_sheet(title="总风险值")
    
    # 定义总风险值表头
    summary_headers = [
        '工作票票号',
        '作业计划编号',
        'B（作业人员能力风险值）',
        'C（作业环境和时间影响风险值）',
        'D（电网、设备风险联动值）',
        'F（总风险值）'
    ]
    
    # 写入总风险值表头
    for col_num, header in enumerate(summary_headers, 1):
        ws_summary.cell(row=1, column=col_num, value=header)
    
    # 写入总风险值数据
    for row_num, result in enumerate(results, 2):
        ws_summary.cell(row=row_num, column=1, value=result.get('工作票票号', ''))
        ws_summary.cell(row=row_num, column=2, value=result.get('作业计划编号', ''))
        ws_summary.cell(row=row_num, column=3, value=result.get('B（作业人员能力风险值）', 0))
        ws_summary.cell(row=row_num, column=4, value=result.get('C（作业环境和时间影响风险值）', 0))
        ws_summary.cell(row=row_num, column=5, value=result.get('D（电网、设备风险联动值）', 0))
        ws_summary.cell(row=row_num, column=6, value=result.get('F（总风险值）', 0))
    
    # 调整总风险值列宽
    summary_column_widths = {
        1: 30,
        2: 20,
        3: 25,
        4: 30,
        5: 25,
        6: 15
    }
    for col, width in summary_column_widths.items():
        ws_summary.column_dimensions[get_column_letter(col)].width = width
    
    # 保存文件
    wb.save(filepath)
    print(f"数据已保存到: {filepath}")
    print(f"共保存了 {len(results)} 张操作票的评估结果")
    
    # 计算详细记录数
    total_detail_records = sum(len(result.get('详细评估结果', [])) for result in results)
    print(f"共保存了 {total_detail_records} 条详细评估记录")
    
    return filepath


if __name__ == "__main__":
    print("开始执行风险评估...")
    # 获取新数据库配置
    print("获取数据库配置...")
    db_config = config_loader.get_db_new_config()
    print(f"数据库配置: {db_config}")
    
    # 测试模式限制10条，正式运行改为None
    TEST_MODE = None
    limit = 100 if TEST_MODE else None
    print(f"测试模式: {TEST_MODE}, 限制记录数: {limit}")

    # limit = None
    
    # 时间范围设置，可根据需要修改
    # 例如：查询半年的作业计划
    start_date = "2026-03-27"  # 开始日期
    end_date = "2026-04-27"    # 结束日期
    print(f"查询时间范围: {start_date} 至 {end_date}")
    
    # 执行风险评估
    print("执行风险评估...")
    results = calculate_risk_score(db_config, limit=limit, start_date=start_date, end_date=end_date)
    
    if results:
        print(f"共评估 {len(results)} 张工作票")
        for result in results:
            print(f"工作票 {result['工作票票号']}: 总风险值={result['F（总风险值）']}")
        
        # 保存结果到Excel文件
        print("保存结果到Excel文件...")
        try:
            filepath = save_to_excel(results)
            print(f"Excel文件保存成功: {filepath}")
        except Exception as e:
            print(f"保存Excel文件时出错: {e}")
    else:
        print("没有获取到数据")
    print("风险评估完成。")
