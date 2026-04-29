# -*- coding: utf-8 -*-
# @Project ：personal_risk_prevention_algo 
# @FileName: main.py
# @Author  : 
# @Time    : 2026/4/25

import mysql.connector
from mysql.connector import Error
import config_loader
import os
import sys
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from openpyxl.styles import Border, Side, Alignment, PatternFill, Font
from datetime import datetime
import calculators
from elink_client import ElinkClient
from minio import Minio
from minio.error import S3Error

# 配置日志
import logging

# 日志文件路径
LOG_DIR = os.path.join(os.path.dirname(__file__), "log")

# 确保日志目录存在
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

# 创建日志文件
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(LOG_DIR, f"risk_calculation_{timestamp}.log")

# 配置logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# 创建logger对象
logger = logging.getLogger(__name__)

# 重定向print函数到logger
def print(*args, **kwargs):
    logger.info(' '.join(map(str, args)))


def upload_to_minio(local_file_path, object_name=None):
    """上传文件到 MinIO，返回对象名称或 None"""
    cfg = config_loader.get_minio_config()
    try:
        client = Minio(
            cfg['endpoint'],
            access_key=cfg['access_key'],
            secret_key=cfg['secret_key'],
            secure=cfg.get('secure', False),
            region=cfg.get('region', None)
        )
        bucket = cfg['bucket_name']
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            print(f"创建 bucket: {bucket}")

        if object_name is None:
            object_name = os.path.basename(local_file_path)
        
        prefix = cfg.get('object_prefix', '').strip()
        if prefix:
            full_object_name = f"{prefix.rstrip('/')}/{object_name}"
        else:
            full_object_name = object_name

        client.fput_object(bucket, full_object_name, local_file_path)
        print(f"文件已上传到 MinIO: {bucket}/{full_object_name}")
        return full_object_name
    except S3Error as e:
        print(f"MinIO 上传失败: {e}")
        return None


def get_risk_level(score):
    """
    根据总分判断风险等级
    
    风险等级判定规则:
    - 可接受: 0 <= score <= 20
    - 低: 20 < score <= 70
    - 中: 70 < score <= 200
    - 高: 200 < score <= 400
    - 特高: score > 400
    
    参数:
    score: 总风险值
    
    返回:
    风险等级名称
    """
    score = int(score) if isinstance(score, (int, float)) else 0
    
    if score <= 20:
        return "可接受"
    elif score <= 70:
        return "低"
    elif score <= 200:
        return "中"
    elif score <= 400:
        return "高"
    else:
        return "特高"


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
    filename = f'数智问安-风险评估审核-{timestamp}.xlsx'
    filepath = os.path.join(output_dir, filename)
    
    # 创建Excel工作簿
    wb = Workbook()
    
    # 创建总风险值工作表（主工作表）
    ws_summary = wb.active
    ws_summary.title = "风险评估结果"
    
    # 定义表头（添加风险等级判定列）
    headers = [
        '作业计划编号',
        '工作任务',
        '作业人员能力风险值',
        '作业环境和时间影响风险值',
        '电网、设备风险联动值',
        '总分',
        '风险等级判定'
    ]
    
    # 写入表头
    for col_num, header in enumerate(headers, 1):
        ws_summary.cell(row=1, column=col_num, value=header)
    
    # 写入数据
    for row_num, result in enumerate(results, 2):
        # 基本信息
        ws_summary.cell(row=row_num, column=1, value=result.get('作业计划编号', ''))
        ws_summary.cell(row=row_num, column=2, value=result.get('工作任务', ''))
        
        # 作业人员能力风险值（包含详细信息）
        b_score = result.get('B（作业人员能力风险值）', 0)
        detailed_results = result.get('详细评估结果', [])
        b_details = []
        for detail in detailed_results:
            if '安全意识' in detail.get('评估结果名称', '') or '同类型作业次数' in detail.get('评估结果名称', '') or '人员性质' in detail.get('评估结果名称', '') or '作业总人数' in detail.get('评估结果名称', '') or '临时变更' in detail.get('评估结果名称', '') or '精神状态' in detail.get('评估结果名称', ''):
                b_details.append(f"{detail.get('评估因子', '')}: {detail.get('风险值得分', 0)}分")
        b_info = f"总分: {b_score}分\n" + "\n".join(b_details)
        ws_summary.cell(row=row_num, column=3, value=b_info)
        
        # 作业环境和时间影响风险值
        c_score = result.get('C（作业环境和时间影响风险值）', 0)
        c_details = []
        
        # 作业地段
        score = 0
        for detail in detailed_results:
            if detail.get('评估因子', '') == '作业地段、类型':
                score = detail.get('风险值得分', 0)
                break
        c_details.append(f"作业地段: {score}分")
        
        # 作业类型
        score = 0
        for detail in detailed_results:
            if detail.get('评估因子', '') == '作业地段、类型':
                score = detail.get('风险值得分', 0)
                break
        c_details.append(f"作业类型: {score}分")
        
        # 天气
        score = 0
        for detail in detailed_results:
            if detail.get('评估因子', '') == '天气':
                score = detail.get('风险值得分', 0)
                break
        c_details.append(f"天气: {score}分")
        
        # 作业时段
        score = 0
        for detail in detailed_results:
            if detail.get('评估因子', '') == '作业时段':
                score = detail.get('风险值得分', 0)
                break
        c_details.append(f"作业时段: {score}分")
        
        # 单日持续作业时长(疲劳度)
        score = 0
        for detail in detailed_results:
            if detail.get('评估因子', '') == '单日持续作业时长(疲劳度)':
                score = detail.get('风险值得分', 0)
                break
        c_details.append(f"单日持续作业时长(疲劳度): {score}分")
        
        # 计划性质
        score = 0
        for detail in detailed_results:
            if detail.get('评估因子', '') == '计划性质':
                score = detail.get('风险值得分', 0)
                break
        c_details.append(f"计划性质: {score}分")
        
        # 关键重要站点(线路)
        score = 0
        for detail in detailed_results:
            if detail.get('评估因子', '') == '关键重要站点(线路)':
                score = detail.get('风险值得分', 0)
                break
        c_details.append(f"关键重要站点(线路): {score}分")
        
        c_info = f"总分: {c_score}分\n" + "\n".join(c_details)
        ws_summary.cell(row=row_num, column=4, value=c_info)
        
        # 电网、设备风险联动值
        d_score = result.get('D（电网、设备风险联动值）', 0)
        d_details = []
        for detail in detailed_results:
            if '事故后果' in detail.get('评估结果名称', '') or '设备风险' in detail.get('评估结果名称', ''):
                d_details.append(f"{detail.get('评估因子', '')}: {detail.get('风险值得分', 0)}分")
        d_info = f"总分: {d_score}分\n" + "\n".join(d_details)
        ws_summary.cell(row=row_num, column=5, value=d_info)
        
        # 总分
        f_score = result.get('F（总风险值）', 0)
        ws_summary.cell(row=row_num, column=6, value=f"{f_score}分")
        
        # 风险等级判定
        risk_level = get_risk_level(f_score)
        ws_summary.cell(row=row_num, column=7, value=risk_level)
    
    # 保存文件
    wb.save(filepath)
    
    # 美化Excel文件
    print("美化Excel文件...")
    beautify_excel(filepath)
    
    print(f"数据已保存到: {filepath}")
    print(f"共保存了 {len(results)} 张操作票的评估结果")
    
    return filepath


def beautify_excel(filename):
    from openpyxl import load_workbook
    wb = load_workbook(filename)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, name='微软雅黑')
    content_font = Font(name='微软雅黑', size=10)
    thin_border = Border(left=Side(style='thin'), right=Side(style='thin'), top=Side(style='thin'), bottom=Side(style='thin'))
    alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        for col in ws.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if cell.value:
                        length = len(str(cell.value).encode('gbk'))
                        if length > max_length: max_length = length
                except: pass
            ws.column_dimensions[column].width = min(max(max_length + 2, 12), 50)
        for row_idx, row in enumerate(ws.iter_rows()):
            for cell in row:
                cell.border = thin_border
                cell.alignment = alignment
                if row_idx == 0:
                    cell.fill = header_fill; cell.font = header_font
                else:
                    cell.font = content_font
        ws.freeze_panes = "A2"
    wb.save(filename)


def send_file_via_elink(file_path, touser_id=None, message_type=None):
    """
    通过elink发送文件
    
    参数:
    file_path: 要发送的文件路径
    touser_id: 接收方用户ID（可选，默认从配置获取）
    message_type: 消息类型（可选，默认从配置获取）
    
    返回:
    发送结果字典
    """
    try:
        # 从配置获取参数
        elink_config = config_loader.get_elink_config()
        if not elink_config.get('enabled', False):
            print("elink未启用，跳过文件发送")
            return None
        
        # 使用传入的参数或从配置获取
        if touser_id is None:
            touser_id = elink_config.get('touser_id', '')
        if message_type is None:
            message_type = elink_config.get('type', 1)
        
        # 使用配置创建ElinkClient
        client = ElinkClient(
            base_url=elink_config.get('base_url', "http://10.120.182.54:9090"),
            send_message_path=elink_config.get('send_message_path', "/api/report/sendMessage"),
            send_file_path=elink_config.get('send_file_path', "/api/report/sendFile"),
            timeout_seconds=elink_config.get('timeout_seconds', 30)
        )
        
        result = client.send_file(file_path, touser_id, message_type)
        print(f"elink文件发送成功: {file_path}")
        return result
    except Exception as e:
        print(f"elink文件发送失败: {e}")
        raise


def run_risk_calculation():
    """执行风险评估的主函数"""
    try:
        print("开始执行风险评估...")
        # 获取配置
        print("加载配置文件...")
        config = config_loader.get_config()
        print("配置文件加载成功")
        
        # 获取新数据库配置
        print("获取数据库配置...")
        db_config = config_loader.get_db_new_config()
        print(f"数据库配置: {db_config}")
        
        # 从配置获取测试模式
        TEST_MODE = config.get('test_mode', False)
        limit = config_loader.get_query_limit()
        print(f"测试模式: {TEST_MODE}, 限制记录数: {limit}")
        
        # 从配置获取年度（动态计算）
        record_year = config_loader.get_current_year()
        print(f"当前年份: {record_year}")
        
        # 从配置获取查询时间范围
        query_mode = config_loader.get_query_time_mode()
        start_date = config_loader.get_start_date()
        end_date = config_loader.get_end_date()
        print(f"查询时间范围模式: {query_mode}")
        print(f"查询开始日期: {start_date}")
        print(f"查询结束日期: {end_date}")
        
        # 从配置获取过滤词
        filter_words = config_loader.get_default_filter_words()
        print(f"默认过滤词: {filter_words}")
        
        # 从配置获取elink状态
        elink_enabled = config_loader.get_elink_enabled()
        print(f"Elink启用状态: {elink_enabled}")
        if elink_enabled:
            elink_config = config_loader.get_elink_config()
            print(f"Elink接收方ID: {elink_config.get('touser_id', '')}")
            print(f"Elink消息类型: {elink_config.get('type', 1)}")
        
        # 执行风险评估
        print("执行风险评估...")
        results = calculators.calculate_risk_score(db_config, limit=limit, record_year=record_year, start_date=start_date, end_date=end_date)
        
        if results:
            print(f"共评估 {len(results)} 张工作票")
            for result in results:
                print(f"工作票 {result['工作票票号']}: 总风险值={result['F（总风险值）']}")
            
            # 保存结果到Excel文件
            print("保存结果到Excel文件...")
            try:
                # 设置输出目录为当前文件所在目录下的output文件夹
                output_dir = os.path.join(os.path.dirname(__file__), "output")
                print(f"输出目录: {output_dir}")
            
                filepath = save_to_excel(results, output_dir=output_dir)
                print(f"Excel文件保存成功: {filepath}")
            
                # 上传到MinIO
                print("上传Excel文件到MinIO...")
                try:
                    minio_object_name = upload_to_minio(filepath)
                    if minio_object_name:
                        print(f"MinIO上传成功: {minio_object_name}")
                    else:
                        print("MinIO上传失败")
                except Exception as e:
                    print(f"上传MinIO时出错: {e}")
            
                # 通过elink发送文件
                if elink_enabled:
                    print("通过elink发送文件...")
                    try:
                        send_file_via_elink(filepath)
                    except Exception as e:
                        print(f"发送elink文件时出错: {e}")
                else:
                    print("elink未启用，跳过文件发送")
            except Exception as e:
                print(f"保存Excel文件时出错: {e}")
        else:
            print("没有获取到数据")
    except Exception as e:
        print(f"程序执行出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("风险评估完成。")


if __name__ == "__main__":
    run_risk_calculation()
