# -*- coding: utf-8 -*-
"""
风险评估主入口（重构版）
使用重构后的类结构：RiskAssessor（评估编排）、ExcelExporter（Excel输出）、
RiskRuleEngine（规则引擎）、DataFetcher（数据查询）
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime
import logging

from minio import Minio
from minio.error import S3Error

import config_loader
from elink_client import ElinkClient
from risk_assessor import RiskAssessor
from excel_exporter import ExcelExporter

# ==================== 日志配置 ====================

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LOG_DIR = os.path.join(BASE_DIR, "log")
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, f"risk_calculation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.__stdout__),
    ],
)

logger = logging.getLogger(__name__)

from data_cache import DataCache
DataCache.clean_old_logs(keep_days=30)

class LogWriter:
    """将 stdout 输出重定向到 logger，使所有模块的 print() 都写入日志"""
    def __init__(self, logger, level=logging.INFO):
        self.logger = logger
        self.level = level

    def write(self, message):
        message = message.strip()
        if message:
            self.logger.log(self.level, message)

    def flush(self):
        pass


# 重定向 stdout 和 stderr，使全局 print() 和异常堆栈都写入日志
sys.stdout = LogWriter(logger)
sys.stderr = LogWriter(logger, level=logging.ERROR)


# ==================== MinIO 上传 ====================

def upload_to_minio(local_file_path, object_name=None):
    """上传文件到 MinIO"""
    cfg = config_loader.get_minio_config()
    try:
        client = Minio(
            cfg['endpoint'],
            access_key=cfg['access_key'],
            secret_key=cfg['secret_key'],
            secure=cfg.get('secure', False),
            region=cfg.get('region', None),
        )
        bucket = cfg['bucket_name']
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

        if object_name is None:
            object_name = os.path.basename(local_file_path)

        prefix = cfg.get('object_prefix', '').strip()
        full_name = f"{prefix.rstrip('/')}/{object_name}" if prefix else object_name

        client.fput_object(bucket, full_name, local_file_path)
        print(f"文件已上传到 MinIO: {bucket}/{full_name}")
        return full_name
    except S3Error as e:
        print(f"MinIO 上传失败: {e}")
        return None


# ==================== Elink 发送 ====================

# ==================== 违规待处理记录 API ====================

def _build_violation_description(detailed_results):
    """从详细评估结果构建违规描述文本"""
    differences = [d for d in detailed_results if d.get('风险值得分', 0) != d.get('客户填入分值', 0)]
    if not differences:
        return '模型评估结果与客户填写结果一致'

    parts = []
    for diff in differences:
        factor = diff.get('评估因子', '')
        rule_score = diff.get('风险值得分', 0)
        customer_score = diff.get('客户填入分值', 0)
        parts.append(f"{factor}: 模型评估{rule_score}分，人工评估{customer_score}分")
    return '；'.join(parts)


def send_violation_records(results):
    """批量新增违章待处理记录（在导出Excel前调用）"""
    violation_config = config_loader.get_violation_api_config()
    if not violation_config.get('enabled', False):
        print("违规待处理记录API未启用，跳过")
        return

    base_url = violation_config.get('base_url', '').rstrip('/')
    path = violation_config.get('batch_create_path', '/api/violation-pending/batch-create')
    timeout = violation_config.get('timeout_seconds', 30)
    url = f"{base_url}{path}"

    if not results:
        print("无评估结果，跳过违规待处理记录创建")
        return

    payload = []
    for result in results:
        dept_code = result.get('局编码', '')
        if not dept_code:
            continue

        detailed = result.get('详细评估结果', [])

        # 只发送模型分值 > 人工分值的记录（无差异或模型分值更低的不发送）
        has_model_gt_manual = any(
            d.get('风险值得分', 0) > d.get('客户填入分值', 0)
            for d in detailed
        )
        if not has_model_gt_manual:
            continue

        description = _build_violation_description(detailed)

        payload.append({
            "deptCode": dept_code,
            "workSite": None,
            "violationCode": "D10",
            "description": description,
            "wticketNo": result.get('工作票票号', ''),
            "workPlanNo": result.get('作业计划编号', ''),
            "oticketNo": None,
            "taskStage": None,
            "sourceAgent": 3,
            "imageUrl": None,
        })

    if not payload:
        print("没有有效的局编码数据，跳过违规待处理记录创建")
        return

    import urllib.request
    import json

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )

    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        status = resp.status
        resp_body = resp.read().decode('utf-8')
        print(f"违规待处理记录API响应: status={status}, body={resp_body[:500]}")
        print(f"成功发送 {len(payload)} 条违规待处理记录")
    except Exception as e:
        print(f"违规待处理记录API调用失败: {e}")


def send_file_via_elink(file_path, touser_id=None, message_type=None):
    """通过 elink 发送文件"""
    elink_config = config_loader.get_elink_config()
    if not elink_config.get('enabled', False):
        print("elink未启用，跳过文件发送")
        return None

    if touser_id is None:
        touser_id = elink_config.get('touser_id', '')
    if message_type is None:
        message_type = elink_config.get('type', 1)

    client = ElinkClient(
        base_url=elink_config.get('base_url', "http://10.120.182.54:9090"),
        send_message_path=elink_config.get('send_message_path', "/api/report/sendMessage"),
        send_file_path=elink_config.get('send_file_path', "/api/report/sendFile"),
        timeout_seconds=elink_config.get('timeout_seconds', 30),
    )
    result = client.send_file(file_path, touser_id, message_type)
    print(f"elink文件发送成功: {file_path}")
    return result


# ==================== 主流程 ====================

def get_query_params():
    """获取查询参数（limit、query_start_date、query_end_date），供 run_risk_calculation 和 run_daily_precalculation 共用
    :return: (limit, query_start_date, query_end_date)
        - query_start_date/query_end_date: 查询时间区间，用于区间重叠判断 NOT(plan_end_time <= start OR plan_start_time >= end)
    """
    limit = config_loader.get_query_limit()

    # 查询时间区间：优先 query_year 配置，其次 query_time_range
    query_start_date, query_end_date = None, None
    if config_loader.get_query_year_enabled():
        query_start_date = config_loader.get_query_year_start_date()
        query_end_date = config_loader.get_query_year_end_date()
    elif config_loader.get_query_time_range_enabled():
        query_start_date = config_loader.get_start_date()
        query_end_date = config_loader.get_end_date()

    return limit, query_start_date, query_end_date


def run_risk_calculation():
    """执行风险评估的主函数"""
    try:
        print("开始执行风险评估...")

        # 加载配置
        config = config_loader.get_config()
        db_config = config_loader.get_db_new_config()

        # 查询参数
        limit, query_start_date, query_end_date = get_query_params()

        print(f"测试模式: {config.get('test_mode', False)}, 限制记录数: {limit}")
        print(f"时间过滤: 查询时间区间 {query_start_date} ~ {query_end_date}（区间重叠判断）")

        # 特定计划编号测试模式
        work_codes = None
        if config.get('specific_plan_num_test_mode', False):
            work_codes = config.get('work_code', [])
            if work_codes:
                print(f"特定计划编号测试模式: {work_codes}")

        # 执行风险评估
        assessor = RiskAssessor(db_config)
        results = assessor.assess(limit=limit, query_start_date=query_start_date, query_end_date=query_end_date,
                                  incremental_output=True, work_codes=work_codes)

        if not results:
            print("没有增量数据，输出空Excel")

        print(f"共评估 {len(results)} 条工作计划编号")

        # 调用违规待处理记录API（在写入Excel之前）
        try:
            send_violation_records(results)
        except Exception as e:
            print(f"发送违规待处理记录时出错: {e}")

        # 导出 Excel
        output_dir = os.path.join(BASE_DIR, "output")
        exporter = ExcelExporter(output_dir)
        filepath = exporter.export(results)

        if not filepath:
            return

        # 上传 MinIO
        try:
            minio_name = upload_to_minio(filepath)
            if minio_name:
                print(f"MinIO上传成功: {minio_name}")
        except Exception as e:
            print(f"上传MinIO时出错: {e}")

        # 发送 elink
        if config_loader.get_elink_enabled():
            try:
                send_file_via_elink(filepath)
            except Exception as e:
                print(f"发送elink文件时出错: {e}")

    except Exception as e:
        print(f"程序执行出错: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("风险评估完成。")


if __name__ == "__main__":
    run_risk_calculation()