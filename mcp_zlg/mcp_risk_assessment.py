# -*- coding: utf-8 -*-
# @Project ：personal_risk_prevention_algo
# @FileName: mcp_risk_assessment.py
# @Author  :
# @Time    : 2026/5/11
# @Description: 风险评估MCP模块 - 按作业计划编号查询单票风险评分，规则与主项目 v3.2 保持一致

import os
import sys
import json
import yaml

# 添加项目根目录到 sys.path，以便导入主项目的 code/ 模块
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from mcp.server.fastmcp import FastMCP
from config_loader import get_db_new_config, get_bracket_filter_words
from code.risk_rule_engine import RiskRuleEngine
from code.data_fetcher import DataFetcher

# ==================== MCP 配置加载 ====================

CONFIG_FILE_NAME = "config.yaml"

def get_config_path():
    """获取 MCP 配置文件路径"""
    local_config_path = os.path.join(os.path.dirname(__file__), CONFIG_FILE_NAME)
    if os.path.exists(local_config_path):
        return local_config_path
    raise FileNotFoundError(f"配置文件不存在: {local_config_path}")

def load_mcp_config():
    """加载 MCP 的 YAML 配置文件"""
    config_path = get_config_path()
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

_MCP_CONFIG = load_mcp_config()
_MCP_SERVER_CONFIG = _MCP_CONFIG.get('mcp', {})

# ==================== MCP 服务初始化 ====================

mcp = FastMCP(
    "risk-assessment-mcp",
    host=_MCP_SERVER_CONFIG.get('host', '0.0.0.0'),
    port=_MCP_SERVER_CONFIG.get('port', 8766)
)

TIMEOUT_SECONDS = _MCP_SERVER_CONFIG.get('timeout_seconds', 120)

# ==================== 规则引擎（复用主项目） ====================

engine = RiskRuleEngine()

# ==================== 数据库查询 ====================

# 操作票查询（与主项目 data_fetcher.py 保持一致）
WORK_TICKET_QUERY = """
SELECT 
    wp.work_code,
    wb.ticket_no,
    wb.ticket_source_id,
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
    wb.work_task,
    wp.release_time
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
WHERE (wp.task_state != '1.0' OR wp.task_state IS NULL)
"""

# 违章查询（与主项目保持一致）
PECCANCY_QUERY = """
SELECT 
    peccancy_uid,
    peccancy_code,
    COUNT(*) as count
FROM sp_ss_uq_peccancy_list_log 
WHERE peccancy_uid = %s
AND record_date BETWEEN DATE_SUB(CURDATE(), INTERVAL 1 YEAR) AND CURDATE()
GROUP BY peccancy_uid, peccancy_code
"""

# ==================== 工具函数：获取数据库连接 ====================


def _get_db_connection():
    """创建数据库连接"""
    db_config = get_db_new_config()
    import mysql.connector
    return mysql.connector.connect(
        host=db_config['host'],
        port=db_config['port'],
        user=db_config['user'],
        password=db_config['password'],
        database=db_config['database'],
    )


def _query_peccancy(cursor, uid: str) -> dict:
    """查询单个人员的违章记录"""
    cursor.execute(PECCANCY_QUERY, (uid,))
    records = cursor.fetchall()
    cursor.fetchall()  # 清空未读取结果
    peccancy = {}
    for record in records:
        peccancy_code = record.get('peccancy_code', '')
        if peccancy_code:
            vt = peccancy_code[0].upper()
            peccancy[vt] = peccancy.get(vt, 0) + record.get('count', 0)
    return peccancy


# ==================== 单票风险计算 ====================


def _calculate_single_ticket_risk(ticket: dict, cursor) -> dict:
    """
    计算单张操作票的风险评分（与主项目 risk_assessor._calc_single_ticket 规则一致）
    不使用大模型，使用规则引擎的规则化方法。
    """
    B = 0  # 作业人员能力风险值
    C = 0  # 作业环境和时间影响风险值
    D = 0  # 电网、设备风险联动值

    work_code = ticket.get('work_code', '')
    work_task = ticket.get('work_task', '') or ''
    detailed_results = []

    # ==================== B: 作业人员能力风险值 ====================

    # B1: 现场作业负责人 + 监护人安全意识（取最高分，与主项目一致）
    max_awareness_score = 0
    awareness_details = []

    for ptype, puid, puname in [
        ('工作负责人', ticket.get('work_principal_uid'), ticket.get('work_principal_uname', '')),
        ('监护人', ticket.get('guardian_uid'), ticket.get('guardian_uname', '')),
    ]:
        if not puid:
            continue
        peccancy = _query_peccancy(cursor, str(puid))
        score = engine.calc_safety_awareness(peccancy)
        if score > max_awareness_score:
            max_awareness_score = score
        viol_desc = '无违章' if not peccancy else ','.join([f'{k}类{v}次' for k, v in peccancy.items()])
        awareness_details.append(f"{ptype}【{puname}】{'存在' if peccancy else ''}{viol_desc}(得分:{score})")

    B += max_awareness_score
    detailed_results.append({
        "评估因子": "现场作业负责人及监护人安全意识",
        "评估对象": '; '.join(awareness_details) if awareness_details else '无人员',
        "评分": max_awareness_score,
        "违章记录": awareness_details,
    })

    # B2: 主要工作班成员安全意识（取最高分，与主项目一致）
    member_max_score = 0
    member_details = []
    work_member_uid = ticket.get('work_member_uid')
    if work_member_uid:
        for mid in work_member_uid.split(','):
            mid = mid.strip()
            if not mid:
                continue
            parts = engine.split_member_ids(mid)
            if not parts:
                parts = [mid]
            for part in parts:
                peccancy = _query_peccancy(cursor, part)
                score = engine.calc_safety_awareness(peccancy)
                if score > member_max_score:
                    member_max_score = score
                if peccancy:
                    viol_desc = ','.join([f'{k}类{v}次' for k, v in peccancy.items()])
                    member_details.append(f"{part}({viol_desc},得分:{score})")

    B += member_max_score
    detailed_results.append({
        "评估因子": "主要工作班成员安全意识",
        "评估对象": '; '.join(member_details) if member_details else ticket.get('work_member_uname', '无'),
        "评分": member_max_score,
    })

    # B3: 作业总人数（与主项目规则一致）
    work_count = ticket.get('work_member_count')
    work_count_score = engine.calc_work_count(work_count)
    B += work_count_score
    detailed_results.append({
        "评估因子": "作业总人数",
        "评估对象": f"{work_count}人" if work_count else "未知",
        "评分": work_count_score,
    })

    # B4: 负责人的人员性质（与主项目规则一致）
    task_main = ticket.get('task_main', '')
    principal_nature, principal_nature_score = engine.calc_personnel_nature(task_main)
    B += principal_nature_score
    detailed_results.append({
        "评估因子": "负责人的人员性质",
        "评估对象": principal_nature,
        "评分": principal_nature_score,
    })

    # B5: 计划性质（与主项目规则一致）
    plan_start = ticket.get('plan_start_time')
    release_time = ticket.get('release_time')
    plan_nature = engine.determine_plan_nature(plan_start, release_time)
    plan_nature_score = engine.calc_plan_nature_score(plan_nature)
    B += plan_nature_score
    detailed_results.append({
        "评估因子": "计划性质",
        "评估对象": plan_nature,
        "评分": plan_nature_score,
    })

    # ==================== C: 作业环境和时间影响风险值 ====================

    # C1: 作业地段 - 规则化判断（MCP 不含大模型，使用关键词匹配）
    work_location_score = _calc_work_location(work_task)
    C += work_location_score
    detailed_results.append({
        "评估因子": "作业地段",
        "评估对象": work_task[:80] if work_task else "无",
        "评分": work_location_score,
    })

    # C2: 作业类型（高度）- 规则化判断（MCP 不含大模型，使用关键词匹配）
    work_type_score = _calc_work_type(work_task)
    C += work_type_score
    detailed_results.append({
        "评估因子": "作业类型（高度）",
        "评估对象": work_task[:80] if work_task else "无",
        "评分": work_type_score,
    })

    # C3: 作业时段（与主项目规则一致）
    plan_end = ticket.get('plan_end_time')
    actual_start = ticket.get('actual_start_time')
    actual_end = ticket.get('actual_end_time')
    # MCP 不含大模型，location_type 通过关键词判断
    location_type = None
    if work_task:
        for kw in engine.OUTDOOR_KEYWORDS:
            if kw in work_task:
                location_type = '站外线路作业'
                break
    work_time_period = engine.determine_work_time_period(
        plan_start, plan_end, actual_start, actual_end,
        work_task, location_type,
    )
    work_time_score = engine.calc_work_time_period_score(work_time_period)
    C += work_time_score
    detailed_results.append({
        "评估因子": "作业时段",
        "评估对象": work_time_period,
        "评分": work_time_score,
    })

    # ==================== D: 电网、设备风险联动值 ====================

    # D 值暂不计算（与主项目一致）
    D = 0

    # ==================== 总分与风险等级 ====================

    F = B + C + D
    risk_level = engine.get_risk_level(F)

    return {
        '工作票票号': ticket.get('ticket_no', ''),
        '作业计划编号': work_code,
        '工作任务': work_task,
        'B（作业人员能力风险值）': B,
        'C（作业环境和时间影响风险值）': C,
        'D（电网、设备风险联动值）': D,
        'F（总风险值）': F,
        '风险等级': risk_level,
        '详细评估结果': detailed_results,
    }


# ==================== 作业地段/类型的规则化判断（替代大模型） ====================

def _calc_work_location(work_task: str) -> int:
    """规则化判断作业地段评分（替代大模型）"""
    if not work_task:
        return 0
    text = work_task
    # 有限空间
    if any(kw in text for kw in ['有限空间', '密闭空间', '电缆沟', '电缆井', '隧道', '管沟', '基坑']):
        return 3
    # 多回共塔
    if any(kw in text for kw in ['共塔', '同塔', '多回']):
        return 10
    # 林区
    if any(kw in text for kw in ['林区', '山林', '森林']):
        return 15
    # 地质隐患
    if any(kw in text for kw in ['地质隐患', '塌方', '泥石流', '滑坡', '边坡']):
        return 15
    return 0


def _calc_work_type(work_task: str) -> int:
    """规则化判断作业类型（高度）评分（替代大模型）"""
    if not work_task:
        return 0
    text = work_task
    # 30米以上
    if any(kw in text for kw in ['30米', '30m', '30M', '铁塔', '高塔', '跨江', '大跨越']):
        return 10
    # 15-30米
    if any(kw in text for kw in ['15米', '15m', '15M', '20米', '25米', '钢管塔']):
        return 7
    # 5-15米
    if any(kw in text for kw in ['5米', '5m', '5M', '10米', '电杆', '水泥杆', '门架']):
        return 5
    # 1.5-5米
    if any(kw in text for kw in ['1.5米', '2米', '3米', '4米', '登高', '高处', '高空', '脚手架', '爬梯']):
        return 3
    if any(kw in text for kw in ['杆上', '杆塔', '构架', '屋顶', '房顶']):
        return 3
    # 吊装/大型吊装
    if any(kw in text for kw in ['吊装', '吊车', '起重', '吊机']):
        return 5
    return 0


# ==================== 按作业计划编号查询 ====================

def _query_single_by_work_plan_code(work_plan_code: str):
    """根据作业计划编号查询单条记录并计算风险"""
    conn = None
    cursor = None
    try:
        conn = _get_db_connection()
        cursor = conn.cursor(dictionary=True)

        query = WORK_TICKET_QUERY + " AND wp.work_code = %s"
        cursor.execute(query, (work_plan_code,))
        ticket = cursor.fetchone()
        cursor.fetchall()

        if not ticket:
            return None

        return _calculate_single_ticket_risk(ticket, cursor)

    except Exception as e:
        print(f"查询失败: {e}")
        return None
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


# ==================== MCP 工具函数 ====================

@mcp.tool()
def query_risk_all_by_code(work_plan_code: str) -> str:
    """
    查询全类风险评分（F = B + C + D）
    :param work_plan_code: 作业计划编号
    """
    result = _query_single_by_work_plan_code(work_plan_code)
    if not result:
        return json.dumps({"error": f"未找到作业计划编号: {work_plan_code}"}, ensure_ascii=False, indent=2)

    return json.dumps({
        "作业计划编号": result['作业计划编号'],
        "工作任务": result['工作任务'],
        "B（作业人员能力风险值）": result['B（作业人员能力风险值）'],
        "C（作业环境和时间影响风险值）": result['C（作业环境和时间影响风险值）'],
        "D（电网、设备风险联动值）": result['D（电网、设备风险联动值）'],
        "F（总风险值）": result['F（总风险值）'],
        "风险等级": result['风险等级'],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def query_risk_b_by_code(work_plan_code: str) -> str:
    """
    查询B类风险评分（作业人员能力风险值）
    :param work_plan_code: 作业计划编号
    """
    result = _query_single_by_work_plan_code(work_plan_code)
    if not result:
        return json.dumps({"error": f"未找到作业计划编号: {work_plan_code}"}, ensure_ascii=False, indent=2)

    b_details = [
        d for d in result['详细评估结果']
        if d['评估因子'] in (
            '现场作业负责人及监护人安全意识',
            '主要工作班成员安全意识',
            '作业总人数',
            '负责人的人员性质',
            '计划性质',
        )
    ]

    return json.dumps({
        "作业计划编号": result['作业计划编号'],
        "B（作业人员能力风险值）": result['B（作业人员能力风险值）'],
        "详细评估": b_details,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def query_risk_c_by_code(work_plan_code: str) -> str:
    """
    查询C类风险评分（作业环境和时间影响风险值）
    :param work_plan_code: 作业计划编号
    """
    result = _query_single_by_work_plan_code(work_plan_code)
    if not result:
        return json.dumps({"error": f"未找到作业计划编号: {work_plan_code}"}, ensure_ascii=False, indent=2)

    c_details = [
        d for d in result['详细评估结果']
        if d['评估因子'] in ('作业地段', '作业类型（高度）', '作业时段')
    ]

    return json.dumps({
        "作业计划编号": result['作业计划编号'],
        "C（作业环境和时间影响风险值）": result['C（作业环境和时间影响风险值）'],
        "详细评估": c_details,
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def query_risk_d_by_code(work_plan_code: str) -> str:
    """
    查询D类风险评分（电网、设备风险联动值）
    :param work_plan_code: 作业计划编号
    """
    result = _query_single_by_work_plan_code(work_plan_code)
    if not result:
        return json.dumps({"error": f"未找到作业计划编号: {work_plan_code}"}, ensure_ascii=False, indent=2)

    return json.dumps({
        "作业计划编号": result['作业计划编号'],
        "D（电网、设备风险联动值）": result['D（电网、设备风险联动值）'],
        "备注": "D 值暂未实现，当前为 0",
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def health_check() -> str:
    """健康检查"""
    return json.dumps({"status": "ok", "service": "risk-assessment-mcp"}, ensure_ascii=False)


# ==================== 启动入口 ====================

if __name__ == "__main__":
    print(f"风险评估 MCP 服务启动中...")
    print(f"  监听地址: {_MCP_SERVER_CONFIG.get('host', '0.0.0.0')}:{_MCP_SERVER_CONFIG.get('port', 8766)}")
    print(f"  超时时间: {TIMEOUT_SECONDS}s")
    mcp.run("streamable-http")