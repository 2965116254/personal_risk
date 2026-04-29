# -*- coding: utf-8 -*-
# @Project ：safety 
# @FileName: operator_capability_D.py
# @Author  : greenaut
# @Time    : 2026/2/12 15:23


import re
import os
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import pandas as pd
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

# ==================== 全局CSV数据（在main中加载） ====================
D_SCORE_DF = None
FAULT_SCENE_DF = None

# ==================== 专业映射（与D.py一致） ====================
MAJOR_MAP = {"1": "变电", "2": "输电", "3": "配电"}


# ==================== 工具函数：从工作任务中提取电压等级 ====================
def extract_voltage_level(work_task):
    """提取电压等级，如 '500kV'，返回字符串"""
    if not work_task or not isinstance(work_task, str):
        return ""
    pattern = re.compile(r"(\d+kV)")
    matches = pattern.findall(work_task)
    return matches[0] if matches else ""


# ==================== D值核心评分函数（直接移植自D.py，适配字典输入） ====================
def match_fault_scene(row_dict, fault_scene_df):
    """
    判断作业是否属于典型故障场景
    row_dict: 包含 'major_name', 'work_task' 的字典
    """
    major_name = row_dict.get('major_name', '')
    work_task = str(row_dict.get('work_task', '')).lower()

    # 按专业筛选
    scene_filter = fault_scene_df[fault_scene_df["所属专业"] == major_name]
    if scene_filter.empty:
        return False

    for _, scene in scene_filter.iterrows():
        scene_task = str(scene["作业任务"]).lower()
        scene_type = str(scene["作业类别"]).lower()
        if (scene_task in work_task) or (scene_type in work_task):
            return True
    return False

# ==================== 辅助函数：从专业名称中提取专业代码 ====================
MAJOR_MAP = {
    "1": "变电", "2": "输电", "3": "配电",
    "变电": "变电", "输电": "输电", "配电": "配电"
}
def get_major_name(major_val):
    if not major_val:
        return ""
    major_str = str(major_val).strip()
    return MAJOR_MAP.get(major_str, major_str)

def judge_accident_consequence(row_dict):
    """
    判定作业可能引发的事故事件后果
    row_dict: 包含 'voltage_level', 'work_place', 'work_task' 的字典
    """
    voltage = str(row_dict.get('voltage_level', '')).lower()
    work_place = str(row_dict.get('work_place', '')).lower()
    work_task = str(row_dict.get('work_task', '')).lower()

    if "500kv" in voltage or "220kv" in voltage:
        if "双母" in work_place or "双母线" in work_task or "n-1" in work_task:
            return "换流站、变电站500kV、220kV双母失压"
        elif "主变" in work_place or "线路" in work_place and "n-2" in work_task:
            return "年运行方式明确的关键设备和重要设备N-2故障"
        else:
            return "造成电力安全二级事件"  # 增加“造成”前缀
    elif "110kv" in voltage or "35kv" in voltage:
        if "关键设备" in work_place or "重要设备" in work_place:
            return "造成电力安全三级事件"
        else:
            return "造成电力安全四级及以下事件"
    else:
        return "造成电力安全四级及以下事件"


def calculate_D_value(row_dict, d_score_df, fault_scene_df):
    """
    计算单张工作票的D值
    返回: (D值, 是否匹配, 事故后果, 详细判断依据)
    """
    # 1. 匹配典型场景
    is_match = match_fault_scene(row_dict, fault_scene_df)
    if not is_match:
        return 0, False, "", "未匹配典型故障场景"

    # 2. 判定后果
    consequence = judge_accident_consequence(row_dict)

    # 3. 查分值
    d_score_row = d_score_df[d_score_df["作业可能导致的电力安全事故事件后果"] == consequence]
    if d_score_row.empty:
        return 0, True, consequence, f"匹配场景，但后果「{consequence}」未在D_score.csv中找到对应分值"
    else:
        d_value = int(d_score_row.iloc[0]["分值"])
        detail = f"匹配典型场景；事故后果：{consequence}；D值={d_value}"
        return d_value, True, consequence, detail


# ==================== 主计算函数（复用C.py数据库连接框架） ====================
def calculate_device_risk_score(db_config, d_score_path, fault_scene_path, limit=None):
    """
    从数据库读取工作票，计算每张票的D值
    参数:
        db_config: 数据库连接配置字典
        d_score_path: D_score.csv 文件路径
        fault_scene_path: fault_scene.csv 文件路径
    返回:
        包含每张工作票D值信息的列表，每个元素为字典
    """
    global D_SCORE_DF, FAULT_SCENE_DF

    # 加载CSV（若未加载）
    if D_SCORE_DF is None:
        D_SCORE_DF = pd.read_csv(d_score_path, encoding="utf-8")
    if FAULT_SCENE_DF is None:
        FAULT_SCENE_DF = pd.read_csv(fault_scene_path, encoding="utf-8")

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

        # 查询工作票所需字段（与D.py所需字段对齐）
        query = """
        SELECT 
            id,
            work_place,
            work_task,
            major
        FROM sp_pd_wticket_base 
        """
        params = []
        if limit is not None:
            query += " LIMIT %s"
            params.append(limit)
        cursor.execute(query, params)
        work_tickets = cursor.fetchall()

        if not work_tickets:
            print("没有找到工作票数据")
            return None

        print(f"找到 {len(work_tickets)} 张工作票，开始计算D值...")

        for ticket in work_tickets:
            ticket_id = ticket['id']
            work_place = ticket['work_place'] or ""
            work_task = ticket['work_task'] or ""
            major = str(ticket['major'] or "")  # 数据库可能为数字或字符串

            # 预处理：专业名称、电压等级
            major_name = MAJOR_MAP.get(major, "")
            voltage_level = extract_voltage_level(work_task)

            # 构建用于评分的数据字典
            row_dict = {
                'major_name': major_name,
                'work_task': work_task,
                'work_place': work_place,
                'voltage_level': voltage_level
            }

            # 计算D值
            d_value, is_match, consequence, detail = calculate_D_value(
                row_dict, D_SCORE_DF, FAULT_SCENE_DF
            )

            # 打印简要日志
            print(f"\n工作票ID: {ticket_id}")
            print(f"  专业: {major_name} ({major})")
            print(f"  电压等级: {voltage_level}")
            print(f"  匹配场景: {is_match}")
            if is_match:
                print(f"  事故后果: {consequence}")
            print(f"  D值: {d_value}")
            print(f"  依据: {detail}")

            # 组装结果记录
            result = {
                '工作票id': ticket_id,
                'D值': d_value,
                '是否匹配典型场景': '是' if is_match else '否',
                '事故后果描述': consequence if is_match else '',
                '判断依据': detail
            }
            all_results.append(result)

    except Error as err:
        print(f"数据库错误: {err}")
        return None
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

    return all_results


# ==================== 保存结果到Excel（复用C.py风格） ====================
def save_d_to_excel(d_data, output_dir, filename):
    """将D值计算结果保存为Excel文件"""
    if not d_data:
        print("没有数据可保存")
        return

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"创建目录: {output_dir}")

    filepath = os.path.join(output_dir, filename)
    wb = Workbook()
    ws = wb.active
    ws.title = "设备风险D值评分"

    # 表头定义
    headers = [
        '工作票id',
        'D值',
        '是否匹配典型场景',
        '事故后果描述',
        '判断依据'
    ]

    for col_num, header in enumerate(headers, 1):
        ws.cell(row=1, column=col_num, value=header)

    # 写入数据
    for row_num, row_data in enumerate(d_data, 2):
        ws.cell(row=row_num, column=1, value=row_data.get('工作票id', ''))
        ws.cell(row=row_num, column=2, value=row_data.get('D值', 0))
        ws.cell(row=row_num, column=3, value=row_data.get('是否匹配典型场景', ''))
        ws.cell(row=row_num, column=4, value=row_data.get('事故后果描述', ''))
        ws.cell(row=row_num, column=5, value=row_data.get('判断依据', ''))

    # 调整列宽
    column_widths = {1: 15, 2: 8, 3: 12, 4: 50, 5: 70}
    for col, width in column_widths.items():
        ws.column_dimensions[get_column_letter(col)].width = width

    wb.save(filepath)
    print(f"\n数据已保存到 {filepath}")
    print(f"共保存 {len(d_data)} 条记录")


# ==================== 主程序入口 ====================
if __name__ == "__main__":
    # 数据库配置
    db_config = {
        'host': '192.168.176.229',
        'port': 23306,
        'user': 'root',
        'password': 'hyetec@2025_personal_risk',
        'database': 'personal_risk_db'
    }

    base_dir = os.path.dirname(os.path.abspath(__file__))
    d_score_path = os.path.join(base_dir, "D_score.csv")
    fault_scene_path = os.path.join(base_dir, "fault_scene.csv")
    output_dir = r'D:\hyetec\safety\execl_output'
    TEST_MODE = True   # 测试模式限制10条，正式运行改为False
    limit = 10 if TEST_MODE else None

    print("=" * 60)
    print("开始计算设备故障风险D值（基于数据库）")
    print("=" * 60)

    if not os.path.exists(d_score_path):
        print(f"错误：未找到D_score.csv，请检查路径：{d_score_path}")
        exit(1)
    if not os.path.exists(fault_scene_path):
        print(f"错误：未找到fault_scene.csv，请检查路径：{fault_scene_path}")
        exit(1)

    d_results = calculate_device_risk_score(db_config, d_score_path, fault_scene_path, limit=limit)

    if d_results:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f'设备风险D值_{timestamp}.xlsx'
        save_d_to_excel(d_results, output_dir, filename)
    else:
        print("未获取到D值计算结果")