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
from night_shift_detector import NightShiftDetector

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

def _simplify_factor(factor: str) -> str:
    """简化评估因子名称"""
    if '现场作业负责人' in factor:
        return '现场作业负责人及监护人安全意识'
    if '主要工作班成员' in factor:
        return '主要工作班成员安全意识'
    if '负责人的人员性质' in factor:
        return '人员性质'
    return factor


def _build_violation_description(detailed_results):
    """从详细评估结果构建违规描述文本（仅包含模型评估>人工评估的数据，附带规则判断依据）"""
    differences = [d for d in detailed_results if d.get('风险值得分', 0) > d.get('客户填入分值', 0)]
    if not differences:
        return '模型评估结果与客户填写结果一致'

    parts = []
    for diff in differences:
        factor = diff.get('评估因子', '')
        rule_score = diff.get('风险值得分', 0)
        customer_score = diff.get('客户填入分值', 0)
        evaluation_result = diff.get('评估结果', '')
        llm_rule = diff.get('大模型命中规则', '')
        llm_keywords = diff.get('大模型命中关键词', '')
        llm_inferred = diff.get('大模型推断依据', '')

        simplified = _simplify_factor(factor)

        # 分数行
        parts.append(f"{simplified}: 模型评估{rule_score}分，人工评估{customer_score}分")

        # 规则判断依据
        if factor in ('作业地段', '作业类型'):
            reason = f"规则判断依据：模型判断{simplified}为{rule_score}分"
            if llm_rule:
                reason += f"，{llm_rule}"
            if llm_keywords:
                reason += f"，工作内容中命中关键词：{llm_keywords}"
            if llm_inferred:
                reason += f"（{llm_inferred}）"
            parts.append(reason)
        elif factor in (
            '现场作业负责人（含小组工作负责人）及监护人（含专职监护人）安全意识',
            '主要工作班成员(辅助工除外)安全意识',
        ):
            if evaluation_result and evaluation_result != '无人员':
                parts.append(f"规则判断依据：{evaluation_result}")
                parts.append(
                    "评分说明：根据安全意识评分规则——有A类违章得6分、有B类违章得5分、"
                    "有C类违章得3分、有D类违章3次及以上得2分、D类违章不足3次或无违章得0分，取最高分作为该项得分"
                )
            else:
                parts.append(f"规则判断依据：无相关作业人员信息，根据规则默认得{rule_score}分")
        elif factor == '作业总人数':
            count_str = evaluation_result if evaluation_result and evaluation_result != '未知' else '0'
            result_line = f"规则判断依据：作业总人数为{count_str}人"
            try:
                count = int(count_str)
                thresholds = [
                    (50, 15, '≥50人'),
                    (24, 8, '24-49人'),
                    (16, 5, '16-23人'),
                    (8, 3, '8-15人'),
                    (5, 1, '5-7人'),
                ]
                rule_desc = '，根据人数评分规则：'
                for threshold, score, desc in thresholds:
                    if count >= threshold:
                        rule_desc += f'{desc}得{score}分'
                        break
                else:
                    rule_desc += '不足5人得0分'
                result_line += rule_desc
            except (ValueError, TypeError):
                result_line += '，无法根据人数确定分值，默认得0分'
            parts.append(result_line)
        elif factor == '负责人的人员性质':
            nature_explanation = {
                '本单位-系统内人员': '得0分',
                '总包单位作业': '得3分',
                '分包作业': '得5分',
                '未知人员性质': '默认得0分',
            }
            explanation = nature_explanation.get(evaluation_result, f'对应规则得{rule_score}分')
            parts.append(f'规则判断依据：作业主体的人员性质为"{evaluation_result}"，根据人员性质评分规则——{explanation}')
        elif factor == '作业时段':
            parts.append(f'规则判断依据：作业时段被判定为"{evaluation_result}"，根据作业时段评分规则得{rule_score}分')
        elif evaluation_result:
            parts.append(f"规则判断依据：{evaluation_result}")
        else:
            parts.append(f"规则判断依据：根据{simplified}评估规则，计算得分为{rule_score}分")

    return '\n'.join(parts)


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

        # 判断模型评估与人工评估的关系
        has_model_gt_manual = any(
            d.get('风险值得分', 0) > d.get('客户填入分值', 0)
            for d in detailed
        )
        has_model_lt_manual = any(
            d.get('风险值得分', 0) < d.get('客户填入分值', 0)
            for d in detailed
        )

        if has_model_gt_manual:
            # 有模型>人工的记录 → D10，附带详细差异说明
            violation_code = "D10"
            description = _build_violation_description(detailed)
        else:
            # 模型<=人工 → 跳过不发送
            continue

        payload.append({
            "deptCode": dept_code,
            "workSite": None,
            "violationCode": violation_code,
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

        # 清理过期的夜间作业 JSON 文件（保留7天）
        NightShiftDetector.clean_old_json_files(keep_days=7)

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

        # 加载前一天的夜间作业详情（work_codes + 检测时间 + 详细检测信息）
        night_shift_work_codes, night_shift_detection_desc, night_shift_details = \
            NightShiftDetector.load_yesterday_night_shift_work_codes()
        if night_shift_work_codes:
            print(f"加载前一天夜间作业检测结果: {len(night_shift_work_codes)} 条")
            if night_shift_detection_desc:
                print(f"  检测时间: {night_shift_detection_desc}")

        # 执行风险评估
        assessor = RiskAssessor(db_config)
        results = assessor.assess(limit=limit, query_start_date=query_start_date, query_end_date=query_end_date,
                                  incremental_output=True, work_codes=work_codes,
                                  night_shift_work_codes=night_shift_work_codes,
                                  night_shift_detection_desc=night_shift_detection_desc,
                                  night_shift_details=night_shift_details)

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