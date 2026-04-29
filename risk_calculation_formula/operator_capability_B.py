# -*- coding: utf-8 -*-
# @Project ：safety 
# @FileName: operator_capability_B.py
# @Author  : greenaut
# @Time    : 2026/2/9 10:47
import re
import os
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import pandas as pd
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from name_cleaner import get_name_extractor


def calculate_worker_capacity_score(db_config, current_year, name_extractor=None, limit=None):
    """
    计算作业人员能力评分（B类）

    参数:
    db_config: 数据库配置字典
    current_year: 当前年份

    返回:
    列表，包含每个工作票的详细信息
    """
    all_results = []
    if name_extractor is None:
        name_extractor = get_name_extractor()

    try:
        # 创建数据库连接
        connection = mysql.connector.connect(
            host=db_config['host'],
            port=db_config['port'],
            user=db_config['user'],
            password=db_config['password'],
            database=db_config['database']
        )

        cursor = connection.cursor(dictionary=True)

        # 获取当前年份用于查询近一年违章
        start_date_str = f"{current_year}-01-01 00:00:00"
        end_date_str = f"{current_year}-12-31 23:59:59"
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d %H:%M:%S')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d %H:%M:%S')

        # 查询所有违章记录（按人员+违章代码分组）
        query_leader_peccancy = """
        SELECT 
            peccancy_uname,
            peccancy_code,
            COUNT(*) as count
        FROM sp_ss_uq_peccancy_list_log 
        WHERE peccancy_time >= %s
        AND peccancy_time <= %s
        GROUP BY peccancy_uname, peccancy_code
        """

        cursor.execute(query_leader_peccancy, (start_date, end_date))
        leader_peccancies = cursor.fetchall()

        # 初始化违章字典和人员列表
        peccancy_dict = {}
        people_with_peccancies = []

        if leader_peccancies:
            print(f"查询到 {len(leader_peccancies)} 条违章记录")
            print(f"时间范围: {start_date} 到 {end_date}")

            # 将违章记录按姓名分组
            for record in leader_peccancies:
                name = record['peccancy_uname']
                if name not in peccancy_dict:
                    peccancy_dict[name] = []
                peccancy_dict[name].append(record)

            people_with_peccancies = list(peccancy_dict.keys())
            print(f"有违章记录的人员: {people_with_peccancies}")

            # 查询与违章人员相关的工作票
            placeholders = ', '.join(['%s'] * len(people_with_peccancies))
            query_work_tickets = f"""
            SELECT 
                id,
                work_member_count,
                work_principal_uname,
                whether_outer_dept,
                work_member_uname 
            FROM sp_pd_wticket_base 
            WHERE work_principal_uname IN ({placeholders})
               OR work_member_uname LIKE %s
            """
            params = people_with_peccancies.copy()
            like_params = '|'.join(people_with_peccancies)
            params.append(f'%{like_params}%')
            # --- 添加 limit ---
            if limit is not None:
                query_work_tickets += " LIMIT %s"
                params.append(limit)
            cursor.execute(query_work_tickets, params)

        else:
            print(f"警告：{current_year}年无违章记录，将生成所有工作票的B类评分（全0）")
            # 直接查询所有工作票（无违章时不需要人员过滤）
            query_all_tickets = """
            SELECT 
                id,
                work_member_count,
                work_principal_uname,
                whether_outer_dept,
                work_member_uname 
            FROM sp_pd_wticket_base
            """
            params = []
            if limit is not None:
                query_all_tickets += " LIMIT %s"
                params.append(limit)
            cursor.execute(query_all_tickets, params)

        work_plan_datas = cursor.fetchall()

        if not work_plan_datas:
            print("没有找到任何工作票")
            return None

        print(f"找到 {len(work_plan_datas)} 张待评分工作票")

        # 处理每张工作票
        for work_plan_data in work_plan_datas:
            # 初始化分数
            B1 = 0  # 工作负责人评分
            B2 = 0  # 主要工作班成员评分
            B3 = 0  # 作业总人数评分
            B4 = 0  # 人员性质评分

            # 初始化判断依据
            B1_criteria = ""
            B2_criteria = ""

            # 处理可能为 None 的工作成员数
            raw_count = work_plan_data['work_member_count']
            work_member_count = int(raw_count) if raw_count is not None else 0

            work_principal_uname = work_plan_data['work_principal_uname'] or ""
            whether_outer_dept = work_plan_data['whether_outer_dept']
            work_ticket_id = work_plan_data['id']

            print(f"\n{'=' * 50}")
            print(f"工作票id: {work_ticket_id}")
            print(f"工作负责人名称: {work_principal_uname}")
            print(f"工作班人员总数: {work_member_count}")
            print(f"人员性质标识: {whether_outer_dept}")

            # 计算B3: 作业总人数评分
            B3 = calculate_b3_score(work_member_count)
            print(f"B3(作业总人数评分): {B3}分")

            # 计算B4: 人员性质评分
            B4 = calculate_b4_score(whether_outer_dept)
            print(f"B4(人员性质评分): {B4}分")

            # 计算B1: 工作负责人评分
            work_leader_records = peccancy_dict.get(work_principal_uname, [])
            if work_leader_records:
                print(f"工作负责人 {work_principal_uname} 有违章记录")
                B1, criteria_str = calculate_person_score(work_leader_records, "工作负责人")
                B1_criteria = f"{work_principal_uname}：{criteria_str}"
            else:
                print(f"工作负责人 {work_principal_uname} 没有违章记录")
                B1 = 0
                B1_criteria = f"{work_principal_uname}：无违章记录"
            print(f"B1(工作负责人评分): {B1}分")
            print(f"B1判断依据: {B1_criteria}")

            # 计算B2: 主要工作班成员评分
            member_names = []
            try:
                work_members = work_plan_data['work_member_uname']
                if work_members:
                    member_names = name_extractor.extract_names(work_members)
                    print(f"工作班成员: {member_names}")

                    member_peccancies = []
                    member_criteria_list = []

                    for member_name in member_names:
                        if member_name in peccancy_dict:
                            member_records = peccancy_dict[member_name]
                            member_peccancies.extend(member_records)
                            print(f"成员 {member_name} 有违章记录")

                            member_score, member_criteria = calculate_person_score(member_records, member_name)
                            member_criteria_list.append(f"{member_name}：{member_criteria}")
                            B2 += member_score
                        else:
                            print(f"成员 {member_name} 没有违章记录")
                            member_criteria_list.append(f"{member_name}：无违章记录")

                    B2_criteria = "；".join(member_criteria_list)

                else:
                    print("未找到工作班成员信息，B2默认为0分")
                    B2_criteria = "无工作班成员信息"

            except Exception as e:
                print(f"获取工作班成员信息失败: {e}")
                B2_criteria = f"获取失败: {str(e)}"

            print(f"B2(主要工作班成员评分): {B2}分")
            print(f"B2判断依据: {B2_criteria}")

            # 计算总评分B
            B = B1 + B2 + B3 + B4

            print(f"\n最终评分结果:")
            print(f"工作负责人评分(B1): {B1}分")
            print(f"主要工作班成员评分(B2): {B2}分")
            print(f"作业总人数评分(B3): {B3}分")
            print(f"人员性质评分(B4): {B4}分")
            print(f"作业人员总评分(B): {B}分")

            # 添加记录
            result = {
                '工作票id': work_ticket_id,
                'B': B,
                'B1': B1,
                'B1判断依据（工作负责人名称）': B1_criteria,
                'B2': B2,
                'B2判断依据（工作班组人员）': B2_criteria,
                'B3': B3,
                'B3作业总人数': work_member_count,
                'B4': B4,
                'B4人员性质（外来单位(1=是，2=否)）': whether_outer_dept
            }
            all_results.append(result)

    except Error as err:
        print(f"数据库错误: {err}")
        return None
    finally:
        # 简化关闭逻辑
        cursor and cursor.close()
        connection and connection.close()

    return all_results


def calculate_b3_score(work_member_count):
    """计算作业总人数评分(B3)"""
    if work_member_count < 5:
        return 0
    elif 5 <= work_member_count < 8:
        return 1
    elif 8 <= work_member_count < 16:
        return 3
    elif 16 <= work_member_count < 24:
        return 5
    elif 24 <= work_member_count < 50:
        return 8
    elif work_member_count >= 50:
        return 10
    else:
        return 0


def calculate_b4_score(whether_outer_dept):
    """计算人员性质评分(B4)"""
    try:
        val = int(whether_outer_dept) if whether_outer_dept is not None else 0
        if val == 2:  # 2表示非外来单位（本单位）
            return 0
        elif val == 1:  # 1表示外来单位
            return 3
        else:
            return 0
    except:
        return 0


def calculate_person_score(peccancies, person_type):
    """计算个人违章评分"""
    score = 0

    d_count = 0
    c_count = 0
    b_count = 0
    a_count = 0

    for record in peccancies:
        peccancy_code = record['peccancy_code']
        count = record['count']

        if peccancy_code and peccancy_code.startswith('D'):
            d_count += count
        elif peccancy_code and peccancy_code.startswith('C'):
            c_count += count
        elif peccancy_code and peccancy_code.startswith('B'):
            b_count += count
        elif peccancy_code and peccancy_code.startswith('A'):
            a_count += count

    criteria_str = f"D类{d_count}次, C类{c_count}次, B类{b_count}次, A类{a_count}次"

    if d_count > 0:
        score += 2 if d_count < 3 else 3
    if c_count >= 1:
        score += 3
    if b_count >= 1:
        score += 5
    if a_count >= 1:
        score += 6

    return score, criteria_str


def extract_names_from_text(text):
    """
    从各种格式的文本中提取姓名列表，过滤公司名、小组名等非人名数据
    """
    names = []

    if not text or pd.isna(text):
        return names

    text = str(text).replace('\n', '').replace('\r', '')

    # 1. 处理带括号的姓名格式，如"熊xx（厂家技术人员）"
    pattern1 = r'([\u4e00-\u9fa5]{2,4}[\u00b7·]?[\u4e00-\u9fa5]{0,2})[\（\(][^）\)]*?[\）\)]'
    matches1 = re.findall(pattern1, text)
    for name in matches1:
        if is_valid_name(name):
            names.append(name.strip())

    # 2. 处理公司名:姓名格式，如"许继电气股份有限公司：张xx"
    pattern2 = r'[^:：]*[:：]([\u4e00-\u9fa5]{2,4}[\u00b7·]?[\u4e00-\u9fa5]{0,2})'
    matches2 = re.findall(pattern2, text)
    for name in matches2:
        if is_valid_name(name):
            names.append(name.strip())

    # 3. 处理小组:姓名格式，如"第01小组：吕xx（共2人）"
    pattern3 = r'(?:第[0-9零一二三四五六七八九十百千万]+小组|小组)[:：]([\u4e00-\u9fa5]{2,4}[\u00b7·]?[\u4e00-\u9fa5]{0,2})'
    matches3 = re.findall(pattern3, text)
    for name in matches3:
        if is_valid_name(name):
            names.append(name.strip())

    # 4. 处理简单的括号姓名，如"(罗xx)"
    pattern4 = r'[\（\(]([\u4e00-\u9fa5]{2,4}[\u00b7·]?[\u4e00-\u9fa5]{0,2})[\）\)]'
    matches4 = re.findall(pattern4, text)
    for name in matches4:
        if is_valid_name(name):
            names.append(name.strip())

    # 5. 处理纯姓名（无括号、冒号等特殊格式）
    text_no_special = text
    text_no_special = re.sub(r'[\（\(][^）\)]*?[\）\)]', ';', text_no_special)
    text_no_special = re.sub(r'[^:：]*[:：]', ';', text_no_special)
    text_no_special = re.sub(r'第[0-9零一二三四五六七八九十百千万]+小组[:：]?', ';', text_no_special)
    text_no_special = re.sub(r'小组[:：]?', ';', text_no_special)

    separators = [';', '；', '、', '，', ',', ' ', '(', ')', '（', '）', '\n', '\r', '\t']
    for sep in separators:
        text_no_special = text_no_special.replace(sep, ';')

    parts = text_no_special.split(';')
    for part in parts:
        part = part.strip()
        if not part:
            continue

        name_pattern = r'^([\u4e00-\u9fa5]{2,4})(?:[\u00b7·]([\u4e00-\u9fa5]{1,3}))?$'
        if re.match(name_pattern, part):
            if is_valid_name(part):
                names.append(part)
        else:
            mixed_names = re.findall(r'[\u4e00-\u9fa5]{2,4}', part)
            for name in mixed_names:
                if is_valid_name(name):
                    names.append(name)

    seen = set()
    unique_names = []
    for name in names:
        name = name.strip()
        if name and name not in seen and is_valid_name(name):
            seen.add(name)
            unique_names.append(name)

    return unique_names


def is_valid_name(name):
    """
    判断是否为有效的人名
    """
    if not name or len(name.strip()) < 2:
        return False

    invalid_keywords = [
        '公司', '有限', '建设', '工程', '保护', '控制', '班', '局',
        '队', '所', '厂', '站', '院', '小组', '第', '组', '人员',
        '技术', '操作', '管理', '维修', '安装', '调试', '试验',
        '电气', '机械', '设备', '系统', '网络', '软件', '硬件'
    ]
    for keyword in invalid_keywords:
        if keyword in name:
            return False

    if re.match(r'^\d+$', name):
        return False

    if re.search(r'[^\u4e00-\u9fa5\u00b7·]', name):
        return False

    if len(name) < 2 or len(name) > 4:
        if '·' in name or '·' in name:
            parts = re.split(r'[··]', name)
            total_len = sum(len(part) for part in parts)
            if total_len < 2 or total_len > 6:
                return False
        else:
            return False

    return True


def save_to_excel(data, output_dir, filename):
    """
    将数据保存到Excel文件
    """
    if not data:
        print("没有数据可保存")
        return

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"创建目录: {output_dir}")

    filepath = os.path.join(output_dir, filename)

    wb = Workbook()
    ws = wb.active
    ws.title = "作业票id"

    headers = [
        '工作票id',
        'B（作业人员能力风险值）',
        'B1',
        'B1判断依据（工作负责人名称）',
        'B2',
        'B2判断依据（工作班组人员）',
        'B3',
        'B3作业总人数',
        'B4',
        'B4人员性质（外来单位(1=是，2=否)）'
    ]

    for col_num, header in enumerate(headers, 1):
        ws.cell(row=1, column=col_num, value=header)

    for row_num, row_data in enumerate(data, 2):
        ws.cell(row=row_num, column=1, value=row_data.get('工作票id', ''))
        ws.cell(row=row_num, column=2, value=row_data.get('B', 0))
        ws.cell(row=row_num, column=3, value=row_data.get('B1', 0))
        ws.cell(row=row_num, column=4, value=row_data.get('B1判断依据（工作负责人名称）', ''))
        ws.cell(row=row_num, column=5, value=row_data.get('B2', 0))
        b2_criteria = row_data.get('B2判断依据（工作班组人员）', '')
        if not b2_criteria:
            b2_criteria = '无记录'
            print(f"警告：工作票 {row_data.get('工作票id', '未知')} B2判断依据为空，已填充默认值")
        ws.cell(row=row_num, column=6, value=b2_criteria)
        ws.cell(row=row_num, column=7, value=row_data.get('B3', 0))
        b3_count = row_data.get('B3作业总人数', 0)
        cell = ws.cell(row=row_num, column=8, value=str(b3_count))
        cell.number_format = '@'
        ws.cell(row=row_num, column=9, value=row_data.get('B4', 0))
        outer_dept = row_data.get('B4人员性质（外来单位(1=是，2=否)）', '')
        cell = ws.cell(row=row_num, column=10, value=str(outer_dept))
        cell.number_format = '@'

    column_widths = {
        1: 15, 2: 10, 3: 10, 4: 40, 5: 10, 6: 60, 7: 10, 8: 15, 9: 10, 10: 25
    }
    for col, width in column_widths.items():
        column_letter = get_column_letter(col)
        ws.column_dimensions[column_letter].width = width

    wb.save(filepath)
    print(f"数据已保存到 {filepath}")
    print(f"共保存了 {len(data)} 条记录")


if __name__ == "__main__":
    # 数据库配置
    db_config = {
        'host': '192.168.176.229',
        'port': 23306,
        'user': 'root',
        'password': 'hyetec@2025_personal_risk',
        'database': 'personal_risk_db'
    }
    current_year = 2025
    output_dir = r'D:\hyetec\safety\execl_output'
    TEST_MODE = True   # 测试模式限制10条，正式运行改为False
    limit = 10 if TEST_MODE else None

    # 👇 关键修改：传入 limit 参数
    results = calculate_worker_capacity_score(db_config, current_year, limit=limit)

    if results:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f'作业人员风险评分B_{current_year}.xlsx'
        save_to_excel(results, output_dir, filename)
    else:
        print("没有获取到数据")