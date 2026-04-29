# -*- coding: utf-8 -*-
# @Project ：personal_risk_prevention_algo 
# @FileName: mcp_risk_server.py
# @Author  : 
# @Time    : 2026/4/29

import json

from mcp.server.fastmcp import FastMCP

import config_loader
import calculators
import risk_rules

# 从配置文件获取MCP服务配置
mcp_config = config_loader.get_mcp_config()
mcp = FastMCP("risk-assessment-server", host=mcp_config['host'], port=mcp_config['port'])

# 数据库配置缓存
_db_config = None


def _get_db_config():
    """获取数据库配置（带缓存）"""
    global _db_config
    if _db_config is None:
        _db_config = config_loader.get_db_new_config()
    return _db_config


# ===================== MCP Tools =====================

@mcp.tool()
def query_risk_all(limit: int = None, start_date: str = None, end_date: str = None) -> str:
    """查询全类作业风险评分（F=A+B+C+D）。综合A类、B类作业人员能力、C类作业环境时间、D类设备故障四类风险，计算总风险值F。当用户询问工作票的总体风险等级或全部风险时调用此工具。

    Args:
        limit: 限制返回数量（可选）
        start_date: 开始日期(YYYY-MM-DD)（可选）
        end_date: 结束日期(YYYY-MM-DD)（可选）
    """
    try:
        db_config = _get_db_config()
        results = calculators.calculate_risk_score(
            db_config,
            limit=limit,
            start_date=start_date,
            end_date=end_date
        )

        if not results:
            return json.dumps({"success": False, "message": "未查询到数据"}, ensure_ascii=False)

        response = []
        for result in results:
            response.append({
                "work_ticket_no": result.get('工作票票号', ''),
                "work_plan_code": result.get('作业计划编号', ''),
                "work_task": result.get('工作任务', ''),
                "B": result.get('B（作业人员能力风险值）', 0),
                "C": result.get('C（作业环境和时间影响风险值）', 0),
                "D": result.get('D（电网、设备风险联动值）', 0),
                "F": result.get('F（总风险值）', 0),
                "detailed_results": result.get('详细评估结果', []),
            })

        return json.dumps({
            "success": True,
            "message": "全类风险评分查询成功",
            "data": response
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "message": f"查询失败: {str(e)}"}, ensure_ascii=False)


@mcp.tool()
def query_risk_b(limit: int = None, start_date: str = None, end_date: str = None) -> str:
    """查询B类作业风险评分（作业人员能力风险）。包含安全意识、作业人数、人员性质、同类型作业次数、计划性质等评估因子。当用户询问工作票的B类风险或作业人员能力风险时调用此工具。

    Args:
        limit: 限制返回数量（可选）
        start_date: 开始日期(YYYY-MM-DD)（可选）
        end_date: 结束日期(YYYY-MM-DD)（可选）
    """
    try:
        db_config = _get_db_config()
        results = calculators.calculate_risk_score(
            db_config,
            limit=limit,
            start_date=start_date,
            end_date=end_date
        )

        if not results:
            return json.dumps({"success": False, "message": "未查询到数据"}, ensure_ascii=False)

        response = []
        for result in results:
            # 筛选B类相关的详细结果
            b_details = [r for r in result.get('详细评估结果', [])
                         if any(keyword in r.get('评估因子', '') for keyword in
                                ['安全意识', '作业总人数', '人员性质', '同类型作业次数', '计划性质', '精神状态'])]

            response.append({
                "work_ticket_no": result.get('工作票票号', ''),
                "work_plan_code": result.get('作业计划编号', ''),
                "work_task": result.get('工作任务', ''),
                "B": result.get('B（作业人员能力风险值）', 0),
                "detailed_results": b_details,
            })

        return json.dumps({
            "success": True,
            "message": "B类风险评分查询成功",
            "data": response
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "message": f"查询失败: {str(e)}"}, ensure_ascii=False)


@mcp.tool()
def query_risk_c(limit: int = None, start_date: str = None, end_date: str = None) -> str:
    """查询C类作业风险评分（作业环境和时间影响风险）。包含作业地段、作业类型、天气、作业时段、单日持续作业时长、计划性质、关键重要站点(线路)等评估因子。当用户询问工作票的C类风险或作业环境风险时调用此工具。

    Args:
        limit: 限制返回数量（可选）
        start_date: 开始日期(YYYY-MM-DD)（可选）
        end_date: 结束日期(YYYY-MM-DD)（可选）
    """
    try:
        db_config = _get_db_config()
        results = calculators.calculate_risk_score(
            db_config,
            limit=limit,
            start_date=start_date,
            end_date=end_date
        )

        if not results:
            return json.dumps({"success": False, "message": "未查询到数据"}, ensure_ascii=False)

        response = []
        for result in results:
            # 筛选C类相关的详细结果
            c_details = [r for r in result.get('详细评估结果', [])
                         if any(keyword in r.get('评估因子', '') for keyword in
                                ['作业地段', '作业类型', '天气', '作业时段', '单日持续作业时长', '关键重要站点'])]

            response.append({
                "work_ticket_no": result.get('工作票票号', ''),
                "work_plan_code": result.get('作业计划编号', ''),
                "work_task": result.get('工作任务', ''),
                "C": result.get('C（作业环境和时间影响风险值）', 0),
                "detailed_results": c_details,
            })

        return json.dumps({
            "success": True,
            "message": "C类风险评分查询成功",
            "data": response
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "message": f"查询失败: {str(e)}"}, ensure_ascii=False)


@mcp.tool()
def query_risk_d(limit: int = None, start_date: str = None, end_date: str = None) -> str:
    """查询D类作业风险评分（电网、设备风险联动值）。包含事故后果、设备风险等评估因子。当用户询问工作票的D类风险或设备风险时调用此工具。

    Args:
        limit: 限制返回数量（可选）
        start_date: 开始日期(YYYY-MM-DD)（可选）
        end_date: 结束日期(YYYY-MM-DD)（可选）
    """
    try:
        db_config = _get_db_config()
        results = calculators.calculate_risk_score(
            db_config,
            limit=limit,
            start_date=start_date,
            end_date=end_date
        )

        if not results:
            return json.dumps({"success": False, "message": "未查询到数据"}, ensure_ascii=False)

        response = []
        for result in results:
            # 筛选D类相关的详细结果
            d_details = [r for r in result.get('详细评估结果', [])
                         if any(keyword in r.get('评估因子', '') for keyword in
                                ['事故后果', '设备风险'])]

            response.append({
                "work_ticket_no": result.get('工作票票号', ''),
                "work_plan_code": result.get('作业计划编号', ''),
                "work_task": result.get('工作任务', ''),
                "D": result.get('D（电网、设备风险联动值）', 0),
                "detailed_results": d_details,
            })

        return json.dumps({
            "success": True,
            "message": "D类风险评分查询成功",
            "data": response
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "message": f"查询失败: {str(e)}"}, ensure_ascii=False)


@mcp.tool()
def calculate_safety_awareness(peccancy_records: str = None, awareness_level: str = None) -> str:
    """计算安全意识评分。当用户询问安全意识评分规则或具体人员的安全意识评分时调用此工具。

    Args:
        peccancy_records: 违章记录JSON字符串，如: {"A":1,"B":2}（优先）
        awareness_level: 安全意识等级（可选）

    评分规则:
    - A类违章: 6分
    - B类违章: 5分
    - C类违章: 3分
    - D类违章(≥3次): 2分
    - D类违章(<3次): 0分
    """
    try:
        score = 0

        if peccancy_records:
            try:
                records = json.loads(peccancy_records)
                score = risk_rules.calculate_person_safety_awareness_score(records)
            except json.JSONDecodeError:
                return json.dumps({"success": False, "message": "peccancy_records格式错误"}, ensure_ascii=False)
        elif awareness_level:
            score = risk_rules.calculate_safety_awareness_score(awareness_level)

        return json.dumps({
            "success": True,
            "message": "安全意识评分计算成功",
            "factor_type": "安全意识",
            "score": score,
            "input": {"peccancy_records": peccancy_records, "awareness_level": awareness_level}
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "message": f"计算失败: {str(e)}"}, ensure_ascii=False)


@mcp.tool()
def calculate_work_count(count: int) -> str:
    """计算作业总人数评分。当用户询问作业总人数评分规则时调用此工具。

    Args:
        count: 作业总人数

    评分规则:
    - ≥50人: 15分
    - 24-49人: 8分
    - 16-23人: 5分
    - 8-15人: 3分
    - 5-7人: 1分
    - <5人: 0分
    """
    try:
        score = risk_rules.calculate_work_total_count_score(count)
        return json.dumps({
            "success": True,
            "message": "作业总人数评分计算成功",
            "factor_type": "作业总人数",
            "input_value": count,
            "score": score
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "message": f"计算失败: {str(e)}"}, ensure_ascii=False)


@mcp.tool()
def calculate_personnel_nature(nature: str) -> str:
    """计算人员性质评分。当用户询问人员性质评分规则时调用此工具。

    Args:
        nature: 人员性质

    评分规则:
    - 外施工单位劳务分包人员: 8分
    - 外施工单位人员: 5分
    - 本单位人员: 0分
    """
    try:
        score = risk_rules.calculate_personnel_nature_score(nature)
        return json.dumps({
            "success": True,
            "message": "人员性质评分计算成功",
            "factor_type": "人员性质",
            "input_value": nature,
            "score": score
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "message": f"计算失败: {str(e)}"}, ensure_ascii=False)


@mcp.tool()
def calculate_experience(count: int) -> str:
    """计算作业经验评分（同类型作业次数）。当用户询问作业经验评分规则时调用此工具。

    Args:
        count: 同类型作业次数

    评分规则:
    - 第一次承担该类作业: 6分
    - 累计不足3次但不是第一次: 5分
    - 累计不足5次但不小于3次: 3分
    - 1年内2次及以上或2年内5次及以上: 0分
    - 其他累计5次及以上: 2分
    """
    try:
        score = risk_rules.get_same_type_score(count)
        return json.dumps({
            "success": True,
            "message": "作业经验评分计算成功",
            "factor_type": "作业经验",
            "input_value": count,
            "score": score
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "message": f"计算失败: {str(e)}"}, ensure_ascii=False)


@mcp.tool()
def calculate_work_hours(hours: float) -> str:
    """计算单日持续作业时长评分（疲劳度）。当用户询问作业时长评分规则时调用此工具。

    Args:
        hours: 单日持续作业时长(小时)

    评分规则:
    - ≤4小时: 0分
    - 4-8小时: 2分
    - 8-12小时: 10分
    - >12小时: 20分
    """
    try:
        score = risk_rules.calculate_single_day_work_hours_score(hours)
        return json.dumps({
            "success": True,
            "message": "单日持续作业时长评分计算成功",
            "factor_type": "单日持续作业时长",
            "input_value": hours,
            "score": score
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "message": f"计算失败: {str(e)}"}, ensure_ascii=False)


@mcp.tool()
def calculate_plan_nature(plan_nature: str) -> str:
    """计算计划性质评分。当用户询问计划性质评分规则时调用此工具。

    Args:
        plan_nature: 计划性质

    评分规则:
    - 计划性作业: 0分
    - 提前一日制定的临时性作业任务: 10分
    - 当日制定的临时性作业任务: 20分
    """
    try:
        score = risk_rules.calculate_plan_nature_score(plan_nature)
        return json.dumps({
            "success": True,
            "message": "计划性质评分计算成功",
            "factor_type": "计划性质",
            "input_value": plan_nature,
            "score": score
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "message": f"计算失败: {str(e)}"}, ensure_ascii=False)


@mcp.tool()
def calculate_time_period(time_period: str) -> str:
    """计算作业时段评分。当用户询问作业时段评分规则时调用此工具。

    Args:
        time_period: 作业时段

    评分规则:
    - 正常时段作业: 0分
    - 二级保供电期间涉及保供电设备的作业: 5分
    - 站内或室内夜间作业(0点-次日6:00): 20分
    - 特级、一级保供电涉及保供电设备的作业或春节等法定节假日: 30分
    - 站外线路夜间作业(20:00-次日6:00): 20分
    """
    try:
        score = risk_rules.calculate_work_time_period_score(time_period)
        return json.dumps({
            "success": True,
            "message": "作业时段评分计算成功",
            "factor_type": "作业时段",
            "input_value": time_period,
            "score": score
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "message": f"计算失败: {str(e)}"}, ensure_ascii=False)


@mcp.tool()
def calculate_weather(weather: str) -> str:
    """计算天气评分。当用户询问天气评分规则时调用此工具。

    Args:
        weather: 天气状况

    评分规则:
    - 天气舒适: 0分
    - 户外作业小雨天气: 10分
    - 气象部门发布天气预报信号后，户外作业受天气影响时: 10分
    - 雷雨、雷电、风力大于五级时(台风、大风预警信号)不具备作业条件: 0分(禁止作业)
    """
    try:
        score = risk_rules.calculate_weather_score(weather)
        return json.dumps({
            "success": True,
            "message": "天气评分计算成功",
            "factor_type": "天气",
            "input_value": weather,
            "score": score
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "message": f"计算失败: {str(e)}"}, ensure_ascii=False)


@mcp.tool()
def calculate_mental_state(state: str) -> str:
    """计算精神状态评分。当用户询问精神状态评分规则时调用此工具。

    Args:
        state: 精神状态

    评分规则:
    - 很差: 999分(禁止作业)
    - 较差: 10分
    - 一般: 2分
    - 良好: 0分
    """
    try:
        score = risk_rules.calculate_mental_state_score(state)
        return json.dumps({
            "success": True,
            "message": "精神状态评分计算成功",
            "factor_type": "精神状态",
            "input_value": state,
            "score": score
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "message": f"计算失败: {str(e)}"}, ensure_ascii=False)


@mcp.tool()
def calculate_key_station(key_status: str) -> str:
    """计算关键重要站点(线路)评分。当用户询问关键重要站点评分规则时调用此工具。

    Args:
        key_status: 关键重要站点(线路)状态

    评分规则:
    - 非关键重要站点(线路): 0分
    - 关键重要站点(线路): 5分
    """
    try:
        score = risk_rules.calculate_key_station_line_score(key_status)
        return json.dumps({
            "success": True,
            "message": "关键重要站点(线路)评分计算成功",
            "factor_type": "关键重要站点(线路)",
            "input_value": key_status,
            "score": score
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "message": f"计算失败: {str(e)}"}, ensure_ascii=False)


@mcp.tool()
def calculate_accident_consequence(consequence: str) -> str:
    """计算事故后果评分。当用户询问事故后果评分规则时调用此工具。

    Args:
        consequence: 事故后果描述

    评分规则:
    - 无事故事件: 0分
    - 造成电力安全四级及以下事件: 0分
    - 造成电力安全三级事件: 10分
    - 造成电力安全二级事件: 40分
    - 造成电力安全一级事件: 160分
    - 造成一般电力安全事故: 180分
    - 造成较大及以上电力安全事故或县域及以上大面积停电: 200分
    """
    try:
        score = risk_rules.calculate_accident_consequence_score(consequence)
        return json.dumps({
            "success": True,
            "message": "事故后果评分计算成功",
            "factor_type": "事故后果",
            "input_value": consequence,
            "score": score
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "message": f"计算失败: {str(e)}"}, ensure_ascii=False)


@mcp.tool()
def calculate_equipment_risk(equipment_risk: str) -> str:
    """计算设备风险评分。当用户询问设备风险评分规则时调用此工具。

    Args:
        equipment_risk: 设备风险描述

    评分规则:
    - 无设备风险影响作业典型场景: 0分
    - 对《设备风险预警通知单》揭示的隐患设备开展作业: 0分
    - 在运行回路上使用万用表、螺丝刀等工器具开展作业: 0分
    - 开展保护装置、安自装置、操作箱及智能终端定检/维护/消缺: 45分
    - 开展带电水冲洗作业: 140分
    - 开展双母线热倒母操作，操作涉及的母线侧刀闸存在超期未检: 90分
    - 手动操作隔离开关，操作涉及的隔离开关为单轴、单电机三连杆机构: 70分
    - 开展电气操作，操作涉及的设备在监控后台无法正确显示设备状态: 70分
    - 开展电气操作，操作涉及的设备存在微机五防、机械防误、电气闭锁异常: 70分
    """
    try:
        score = risk_rules.calculate_equipment_risk_score(equipment_risk)
        return json.dumps({
            "success": True,
            "message": "设备风险评分计算成功",
            "factor_type": "设备风险",
            "input_value": equipment_risk,
            "score": score
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "message": f"计算失败: {str(e)}"}, ensure_ascii=False)


@mcp.tool()
def health_check() -> str:
    """健康检查。用于检查MCP服务是否正常运行。"""
    return json.dumps({
        "success": True,
        "status": "healthy",
        "service": "risk-assessment-mcp-server"
    }, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run("streamable-http")
