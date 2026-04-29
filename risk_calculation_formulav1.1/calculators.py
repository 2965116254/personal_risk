# -*- coding: utf-8 -*-
# @Project ：personal_risk_prevention_algo 
# @FileName: calculators.py
# @Author  : 
# @Time    : 2026/4/22

import mysql.connector
from mysql.connector import Error
import sql_queries
import risk_rules
from datetime import datetime


def calculate_risk_score(db_config, limit=None, record_year=2025, start_date=None, end_date=None):
    """
    根据评估因子的评估结果计算风险值得分
    
    参数:
    db_config: 数据库配置字典
    limit: 限制返回记录数
    record_year: 违章登记年份，默认为2025
    start_date: 开始日期，默认为None
    end_date: 结束日期，默认为None
    
    返回:
    列表，包含每个评估对象的详细信息和风险得分
    """
    print("开始计算风险得分...")
    print(f"数据库配置: {db_config}")
    print(f"限制记录数: {limit}")
    print(f"违章登记年份: {record_year}")
    print(f"开始日期: {start_date}")
    print(f"结束日期: {end_date}")
    
    all_results = []
    
    try:
        # 创建数据库连接
        print("正在连接数据库...")
        print(f"连接参数: host={db_config['host']}, port={db_config['port']}, user={db_config['user']}, database={db_config['database']}")
        connection = mysql.connector.connect(
            host=db_config['host'],
            port=db_config['port'],
            user=db_config['user'],
            password=db_config['password'],
            database=db_config['database']
        )
        print("数据库连接成功")
        print(f"连接ID: {connection.connection_id}")
        
        cursor = connection.cursor(dictionary=True)
        print("创建游标成功")
        
        # 查询操作票表数据，关联作业计划表以过滤时间范围，并获取作业计划信息
        query = sql_queries.WORK_TICKET_QUERY
        
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
        
        print(f"执行查询操作票表，SQL: {query}")
        print(f"查询参数: {params}")
        
        try:
            cursor.execute(query, params)
            print("执行查询成功")
            work_tickets = cursor.fetchall()
            # 确保结果被完全获取
            cursor.fetchall()
            print(f"获取查询结果成功，共 {len(work_tickets)} 条记录")
        except Exception as e:
            print(f"执行查询操作票表出错: {e}")
            import traceback
            traceback.print_exc()
            raise
        
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
            peccancy_query = sql_queries.PECCANCY_QUERY.format(placeholders=placeholders)
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
            same_type_query = sql_queries.BATCH_SAME_TYPE_QUERY.format(placeholders=placeholders)
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
            principal_score = risk_rules.calculate_person_safety_awareness_score(peccancy_dict.get(work_principal_uid, {}))
            B += principal_score
            
            # 1.2 主要工作班成员安全意识
            work_member_uid = ticket.get('work_member_uid')
            member_score = 0
            if work_member_uid:
                member_ids = work_member_uid.split(',')
                for mid in member_ids:
                    if mid.strip():
                        member_score += risk_rules.calculate_person_safety_awareness_score(peccancy_dict.get(mid.strip(), {}))
            B += member_score
            
            # 1.3 监护人安全意识
            guardian_uid = ticket.get('guardian_uid')
            guardian_score = risk_rules.calculate_person_safety_awareness_score(peccancy_dict.get(guardian_uid, {}))
            B += guardian_score
            
            # 1.4 作业总人数
            work_member_count = ticket.get('work_member_count')
            work_count_score = risk_rules.calculate_work_total_count_score(work_member_count)
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
                work_plan_query = sql_queries.WORK_DETAIL_QUERY
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
                '工作任务': ticket.get('work_task', ''),
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
