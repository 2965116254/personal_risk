# -*- coding: utf-8 -*-
# @Project ：safety 
# @FileName: operator_capability_C.py
# @Author  : greenaut
# @Time    : 2026/2/11 15:27


import re
import os
import mysql.connector
from mysql.connector import Error
from datetime import datetime, time
import pandas as pd
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

try:
    import chinese_calendar as cn_calendar

    CHINESE_CALENDAR_AVAILABLE = True
    print("chinese-calendar 库已安装")
except ImportError:
    CHINESE_CALENDAR_AVAILABLE = False
    print("警告: chinese-calendar 库未安装，将使用固定节假日列表")
    # 2024年节假日作为备选
    DEFAULT_HOLIDAYS_2024 = [
        '2024-01-01',  # 元旦
        '2024-02-10', '2024-02-11', '2024-02-12', '2024-02-13', '2024-02-14', '2024-02-15', '2024-02-16',
        '2024-02-17',  # 春节
        '2024-04-04', '2024-04-05', '2024-04-06',  # 清明节
        '2024-05-01', '2024-05-02', '2024-05-03', '2024-05-04', '2024-05-05',  # 劳动节
        '2024-06-08', '2024-06-09', '2024-06-10',  # 端午节
        '2024-09-15', '2024-09-16', '2024-09-17',  # 中秋节
        '2024-10-01', '2024-10-02', '2024-10-03', '2024-10-04', '2024-10-05', '2024-10-06', '2024-10-07'  # 国庆节
    ]


def calculate_work_risk_score(db_config, limit=None):
    """
    计算作业风险评分（C类）

    参数:
    db_config: 数据库配置字典
    返回:
    列表，包含每个工作票的C类评分详细信息
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

        cursor = connection.cursor(dictionary=True)

        # 查询所有工作票的C类相关字段
        query_work_tickets = """
        SELECT 
            id,
            work_place,
            is_key_station,
            is_re_fire,
            work_task,
            permission_time,
            whether_es_risk
        FROM sp_pd_wticket_base 
        """
        params = []
        if limit is not None:
            query_work_tickets += " LIMIT %s"
            params.append(limit)
        cursor.execute(query_work_tickets, params)
        work_tickets = cursor.fetchall()

        if not work_tickets:
            print("没有找到工作票数据")
            return None

        print(f"找到 {len(work_tickets)} 张工作票")

        # 处理每张工作票
        for ticket in work_tickets:
            ticket_id = ticket['id']
            work_place = ticket['work_place'] or ""
            is_key_station = ticket['is_key_station']
            is_re_fire = ticket['is_re_fire']
            work_task = ticket['work_task'] or ""
            permission_time = ticket['permission_time']
            whether_es_risk = ticket['whether_es_risk']

            print(f"\n{'=' * 50}")
            print(f"工作票id: {ticket_id}")
            print(f"作业地点: {work_place}")
            print(f"是否关键站: {is_key_station}")
            print(f"是否关联动火票: {is_re_fire}")
            print(f"工作任务: {work_task}")
            print(f"许可时间: {permission_time}")
            print(f"是否密闭空间: {whether_es_risk}")

            # 初始化分数
            C1 = 0  # 默认为0
            C2 = 0  # 作业地段评分
            C3 = 0  # 作业方式评分
            C4 = 0  # 作业时段评分
            C5 = 0  # 特殊场景作业评分

            # 初始化判断依据
            C2_criteria = ""
            C3_criteria = ""
            C4_criteria = ""
            C5_criteria = ""

            # 计算C2: 作业地段评分
            C2, C2_criteria = calculate_c2_score(work_place, work_task, is_key_station)
            print(f"C2(作业地段评分): {C2}分，判断依据: {C2_criteria}")

            # 计算C3: 作业方式评分
            C3, C3_criteria = calculate_c3_score(is_re_fire, work_task)
            print(f"C3(作业方式评分): {C3}分，判断依据: {C3_criteria}")

            # 计算C4: 作业时段评分
            C4, C4_criteria = calculate_c4_score(permission_time)
            print(f"C4(作业时段评分): {C4}分，判断依据: {C4_criteria}")

            # 计算C5: 特殊场景作业评分
            C5, C5_criteria = calculate_c5_score(whether_es_risk)
            print(f"C5(特殊场景作业评分): {C5}分，判断依据: {C5_criteria}")

            # 计算总评分C
            C = C1 + C2 + C3 + C4 + C5

            print(f"\n最终评分结果:")
            print(f"作业风险总评分(C): {C}分")
            print(f"作业地段评分(C2): {C2}分")
            print(f"作业方式评分(C3): {C3}分")
            print(f"作业时段评分(C4): {C4}分")
            print(f"特殊场景作业评分(C5): {C5}分")

            # 添加一条记录
            result = {
                '工作票id': ticket_id,
                'C': C,
                'C1': C1,
                'C1判断依据': "缺气象数据",
                'C2': C2,
                'C2判断依据': C2_criteria,
                'C3': C3,
                'C3判断依据': C3_criteria,
                'C4': C4,
                'C4判断依据': C4_criteria,
                'C5': C5,
                'C5判断依据': C5_criteria
            }
            all_results.append(result)

    except Error as err:
        print(f"数据库错误: {err}")
        return None
    finally:
        # 简化数据库连接关闭代码
        cursor and cursor.close()
        connection and connection.close()

    return all_results


def calculate_c2_score(work_place, work_task, is_key_station):
    """计算作业地段评分(C2)"""
    score = 0
    criteria_parts = []

    # 检查是否含"500kV/±500kV" - 在work_place中检查
    place_text = f"{work_place} {work_task}"
    if "500kV" in place_text or "±500kV" in place_text:
        score += 10
        criteria_parts.append("含500kV/±500kV+10分")

    # 检查是否含"交叉跨越" - 在work_task中检查
    if work_task and "交叉跨越" in work_task:
        score += 30
        criteria_parts.append("含交叉跨越+30分")

    # 检查是否关键站
    if is_key_station is not None and is_key_station != '':
        try:
            is_key_station_int = int(is_key_station)
            if is_key_station_int == 1:
                score += 15
                criteria_parts.append("关键站+15分")
            elif is_key_station_int == 2:
                criteria_parts.append("非关键站")
            else:
                criteria_parts.append("关键站信息无效")
        except ValueError:
            criteria_parts.append("关键站信息格式错误")
    else:
        criteria_parts.append("关键站信息为空")

    criteria = "; ".join(criteria_parts)
    return score, criteria


def calculate_c3_score(is_re_fire, work_task):
    """计算作业方式评分(C3)"""
    score = 0
    criteria_parts = []

    # 检查是否关联动火票
    if is_re_fire is not None and is_re_fire != '':
        try:
            is_re_fire_int = int(is_re_fire)
            if is_re_fire_int == 1:
                score += 5
                criteria_parts.append("动火作业+5分")
            elif is_re_fire_int == 2:
                criteria_parts.append("非动火作业")
            else:
                criteria_parts.append("动火作业信息无效")
        except ValueError:
            criteria_parts.append("动火作业信息格式错误")
    else:
        criteria_parts.append("动火作业信息为空")

    # 检查是否含"吊装"
    if work_task and "吊装" in work_task:
        score += 5
        criteria_parts.append("含吊装+5分")

    # 检查高空作业高度
    height_score, height_criteria = calculate_height_score(work_task)
    if height_score > 0:
        score += height_score
        criteria_parts.append(height_criteria)

    criteria = "; ".join(criteria_parts)
    return score, criteria


def calculate_height_score(work_task):
    """从工作任务中提取高度信息并评分"""
    if not work_task:
        return 0, ""

    # 定义高度匹配模式
    patterns = [
        r'(\d+(?:\.\d+)?)\s*(?:米|m)',  # 数字+米/m
        r'(\d+(?:\.\d+)?)米',  # 数字+米
        r'(\d+(?:\.\d+)?)m',  # 数字+m
        r'([一二三四五六七八九十百千万]+)\s*(?:米|m)'  # 中文数字+米/m
    ]

    for pattern in patterns:
        matches = re.findall(pattern, work_task, re.IGNORECASE)
        if matches:
            for match in matches:
                try:
                    # 处理中文数字
                    if re.match(r'^[一二三四五六七八九十百千万]+$', match):
                        height = chinese_to_arabic(match)
                    else:
                        height = float(match)

                    # 根据高度范围评分
                    if 1.5 <= height < 5:
                        return 2, f"高度{height}米(1.5~5m)+2分"
                    elif 5 <= height < 30:
                        return 7, f"高度{height}米(5~30m)+7分"
                    elif height >= 30:
                        return 10, f"高度{height}米(>30m)+10分"
                except ValueError:
                    continue

    return 0, "无高度信息或高度不满足评分条件"


def chinese_to_arabic(chinese_num):
    """将中文数字转换为阿拉伯数字"""
    chinese_num_dict = {
        '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
        '百': 100, '千': 1000, '万': 10000
    }

    result = 0
    temp = 0

    for char in chinese_num:
        if char in chinese_num_dict:
            value = chinese_num_dict[char]
            if value >= 10:
                if temp == 0:
                    temp = 1
                result += temp * value
                temp = 0
            else:
                temp = value
        else:
            continue

    result += temp
    return result


def calculate_c4_score(permission_time):
    """计算作业时段评分(C4)"""
    score = 0
    criteria_parts = []

    if not permission_time:
        return 0, "许可时间为空"

    try:
        # 转换时间为datetime对象
        if isinstance(permission_time, str):
            # 尝试多种时间格式
            formats = ['%Y/%m/%d %H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y/%m/%d %H:%M:%S']
            dt = None
            for fmt in formats:
                try:
                    dt = datetime.strptime(permission_time, fmt)
                    break
                except ValueError:
                    continue

            if not dt:
                return 0, f"时间格式无法解析: {permission_time}"
        else:
            dt = permission_time

        # 检查是否为夜间作业 (0:00-6:00)
        night_start = time(0, 0, 0)
        night_end = time(6, 0, 0)
        if night_start <= dt.time() <= night_end:
            score += 20
            criteria_parts.append(f"夜间作业({dt.time()})+20分")
        else:
            criteria_parts.append(f"非夜间作业({dt.time()})")

        # ---------- 国家法定节假日判断----------
        date_obj = dt.date()

        if CHINESE_CALENDAR_AVAILABLE:
            try:
                # 获取详细的假期信息
                is_holiday, holiday_name = cn_calendar.get_holiday_detail(date_obj)

                # 法定节假日关键词
                LEGAL_HOLIDAY_KEYWORDS = ['元旦', '春节', '清明', '劳动节', '端午', '中秋', '国庆']

                # 判断是否为真正的法定节假日：is_holiday=True 且 假期名称包含关键词
                is_legal_holiday = is_holiday and holiday_name and any(
                    kw in holiday_name for kw in LEGAL_HOLIDAY_KEYWORDS)

                if is_legal_holiday:
                    score += 30
                    criteria_parts.append(f"国家法定节假日({date_obj})+30分")
                else:
                    if is_holiday:
                        criteria_parts.append(f"非国家法定节假日({date_obj})")
                    else:
                        criteria_parts.append(f"非国家法定节假日({date_obj})")
            except Exception as e:
                criteria_parts.append(f"节假日检查错误: {str(e)}")
        else:
            # 备选方案：使用2026年固定法定节假日列表（已提前整理）
            date_str_formatted = dt.strftime('%Y-%m-%d')
            if date_str_formatted in DEFAULT_HOLIDAYS_2024:
                score += 30
                criteria_parts.append(f"国家法定节假日({date_obj})+30分")
            else:
                criteria_parts.append(f"非国家法定节假日({date_obj})")
        # -------------------------------------------------

    except Exception as e:
        return 0, f"时间解析错误: {str(e)}"

    criteria = "; ".join(criteria_parts)
    return score, criteria


def calculate_c5_score(whether_es_risk):
    """计算特殊场景作业评分(C5)"""
    if whether_es_risk is not None and whether_es_risk != '':
        try:
            whether_es_risk_int = int(whether_es_risk)
            if whether_es_risk_int == 1:
                return 15, "密闭空间作业+15分"
            elif whether_es_risk_int == 2:
                return 0, "非密闭空间作业"
            else:
                return 0, "密闭空间信息无效"
        except ValueError:
            return 0, "密闭空间信息格式错误"
    else:
        return 0, "无特殊场景作业信息"


def save_combined_to_excel(c_data, output_dir, filename):
    """
    参数:
    c_data: C类评分数据列表
    output_dir: 输出目录
    filename: 输出的Excel文件名
    """
    if not c_data:
        print("没有数据可保存")
        return

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"创建目录: {output_dir}")

    filepath = os.path.join(output_dir, filename)

    # 创建新的工作簿
    wb = Workbook()
    ws = wb.active
    ws.title = "作业票评分"

    combined_data = []

    if c_data:
        for c_item in c_data:
            ticket_id = c_item['工作票id']
            combined_data.append(c_item)

    # 写入表头
    headers = [
        '工作票id',
        # C类评分
        'C（作业环境和时间影响风险值）',
        'C1',
        'C1判断依据',
        'C2',
        'C2判断依据',
        'C3',
        'C3判断依据',
        'C4',
        'C4判断依据',
        'C5',
        'C5判断依据'
    ]

    for col_num, header in enumerate(headers, 1):
        ws.cell(row=1, column=col_num, value=header)

    # 写入数据
    for row_num, row_data in enumerate(combined_data, 2):
        col_num = 1

        # 工作票id
        ws.cell(row=row_num, column=col_num, value=row_data.get('工作票id', ''))
        col_num += 1
        # C类数据
        ws.cell(row=row_num, column=col_num, value=row_data.get('C', 0))
        col_num += 1
        ws.cell(row=row_num, column=col_num, value=row_data.get('C1', 0))
        col_num += 1
        ws.cell(row=row_num, column=col_num, value=row_data.get('C1判断依据', ''))
        col_num += 1
        ws.cell(row=row_num, column=col_num, value=row_data.get('C2', 0))
        col_num += 1
        ws.cell(row=row_num, column=col_num, value=row_data.get('C2判断依据', ''))
        col_num += 1
        ws.cell(row=row_num, column=col_num, value=row_data.get('C3', 0))
        col_num += 1
        ws.cell(row=row_num, column=col_num, value=row_data.get('C3判断依据', ''))
        col_num += 1
        ws.cell(row=row_num, column=col_num, value=row_data.get('C4', 0))
        col_num += 1
        ws.cell(row=row_num, column=col_num, value=row_data.get('C4判断依据', ''))
        col_num += 1
        ws.cell(row=row_num, column=col_num, value=row_data.get('C5', 0))
        col_num += 1
        ws.cell(row=row_num, column=col_num, value=row_data.get('C5判断依据', ''))

    # 调整列宽
    column_widths = {
        1: 15,  # 工作票id
        2: 5,  # C（作业风险评分）
        3: 5,  # C1
        4: 5,  # C1判断依据
        5: 5,  # C2
        6: 40,  # C2判断依据
        7: 5,  # C3
        8: 40,  # C3判断依据
        9: 5,  # C4
        10: 40,  # C4判断依据
        11: 5,  # C5
        12: 25  # C5判断依据
    }

    for col, width in column_widths.items():
        column_letter = get_column_letter(col)
        ws.column_dimensions[column_letter].width = width

    wb.save(filepath)
    print(f"数据已保存到 {filepath}")
    print(f"共保存了 {len(combined_data)} 条记录")


if __name__ == "__main__":
    # 数据库配置
    db_config = {
        'host': '192.168.176.229',
        'port': 23306,
        'user': 'root',
        'password': 'hyetec@2025_personal_risk',
        'database': 'personal_risk_db'
    }
    output_dir = r'D:\hyetec\safety\execl_output'
    TEST_MODE = True   # 测试模式限制10条，正式运行改为False
    limit = 20 if TEST_MODE else None

    print("\n开始计算C类评分...")

    c_results = calculate_work_risk_score(db_config, limit=limit)

    if c_results:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f'作业人员风险评分C_{timestamp}.xlsx'
        save_combined_to_excel(c_results, output_dir, filename)
    else:
        print("没有获取到数据")