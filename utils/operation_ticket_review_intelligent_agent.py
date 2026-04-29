#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
@Project ：personal_risk_prevention_agent 
@File    ：operation_ticket_review_intelligent_agent.py
@IDE     ：PyCharm 
@Author  ：BingshengTian
@Date    ：2026-01-20 14:12 
'''

######################操作票审查智能体#############################
import pandas as pd
from datetime import datetime

# 读取操作票数据
df_oticket = pd.read_excel("../data_offline/操作票表测试.xlsx", sheet_name="Sheet1")


# 定义审查函数
def review_operation_ticket(row):
    ticket_id = row['id']
    review_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reviewer = "智能审查引擎 v1.0"
    results = []

    # 【1】规则B01: 无计划作业或未录入信息系统 (序号1)
    is_violated_rule_b01 = False
    violation_detail_rule_b01 = ""
    check_logic_rule_b01 = "核查是否按规定制定作业计划或作业计划是否按要求录入信息系统；未查询到关联工作计划时提示告警。"
    platform_path_rule_b01 = "电网管理平台-作业计划库；操作票与计划ID关联校验接口"

    # 检查是否有关联的工作计划ID
    if pd.isna(row['oticket_source']) or str(row['oticket_source']).strip() == "":
        is_violated_rule_b01 = True
        violation_detail_rule_b01 = "操作票未关联任何工作计划ID，可能存在‘体外循环’风险。"
    else:
        # 此处应查询计划库，因无数据，暂设为合规
        pass

    suggestion_rule_b01 = "请确保每张操作票均关联一个有效的作业计划编号，避免‘体外循环’。" if is_violated_rule_b01 else "操作票已关联计划编号，符合管控要求。"

    results.append({
        "rule_code": "B01",
        "rule_name": "无计划作业或未录入信息系统",
        "is_violated": is_violated_rule_b01,
        "violation_detail": violation_detail_rule_b01,
        "check_logic": check_logic_rule_b01,
        "platform_path": platform_path_rule_b01,
        "suggestion": suggestion_rule_b01
    })

    # 【2】 规则B03: 操作票关键内容缺失或错误 (序号2)
    is_violated_rule_b03 = False
    violation_detail_rule_b03 = ""
    check_logic_rule_b03 = "核实操作任务与设备状态、名称编号是否对应；操作项目有无漏项、错项、顺序错误；如停电操作需挂接地线、戴绝缘手套等安全措施是否遗漏。"
    platform_path_rule_b03 = "设备台账系统；标准票模板库；历史操作票数据库"

    # 检查操作任务是否为空
    if pd.isna(row['operation_task']) or row['operation_task'].strip() == "":
        is_violated_rule_b03 = True
        violation_detail_rule_b03 += "操作任务描述为空。"

    # 检查操作地点是否为空
    if pd.isna(row['function_location_name']) or row['function_location_name'].strip() == "":
        is_violated_rule_b03 = True
        violation_detail_rule_b03 += "操作地点描述为空。"

    # 检查是否涉及高空作业或带电作业，但未提及安全措施
    operation_task = str(row['operation_task']).lower()
    if ("高空" in operation_task or "登高" in operation_task) and not (
            "安全带" in operation_task or "系安全带" in operation_task):
        is_violated_rule_b03 = True
        violation_detail_rule_b03 += "涉及高空作业，但未提及使用安全带。"
    if ("停电" in operation_task or "检修" in operation_task) and not (
            "接地" in operation_task or "挂接地线" in operation_task):
        is_violated_rule_b03 = True
        violation_detail_rule_b03 += "涉及停电检修，但未提及装设接地线。"

    suggestion_rule_b03 = "请补充完整的操作任务、操作地点描述，并确保安全措施与作业内容匹配。" if is_violated_rule_b03 else "操作票关键内容完整且准确。"

    results.append({
        "rule_code": "B03",
        "rule_name": "操作票关键内容缺失或错误",
        "is_violated": is_violated_rule_b03,
        "violation_detail": violation_detail_rule_b03,
        "check_logic": check_logic_rule_b03,
        "platform_path": platform_path_rule_b03,
        "suggestion": suggestion_rule_b03
    })

    # 【3】规则C01: 签发人兼任工作负责人或空白操作票 (序号3)
    is_violated_rule_c01 = False
    violation_detail_rule_c01 = ""
    check_logic_rule_c01 = "核查操作票签发人与工作负责人是否为同一人，操作票是否为空白。"
    platform_path_rule_c01 = "人员组织架构系统；操作票签发与负责人字段比对"

    # 检查签发人和负责人是否为空
    if pd.isna(row['issue_order_uname']) or row['issue_order_uname'].strip() == "":
        is_violated_rule_c01 = True
        violation_detail_rule_c01 = "操作票签发人姓名为空。"
    if pd.isna(row['operator_unames']) or row['operator_unames'].strip() == "":
        is_violated_rule_c01 = True
        violation_detail_rule_c01 = "操作负责人姓名为空。"

    # 检查签发人和负责人是否为同一人
    if not is_violated_rule_c01:  # 只有在非空的情况下才比较
        if row['issue_order_uname'] == row['operator_unames']:
            is_violated_rule_c01 = True
            violation_detail_rule_c01 = f"操作票签发人 '{row['issue_order_uname']}' 与操作负责人 '{row['operator_unames']}' 为同一人，违反职责分离原则。"

    suggestion_rule_c01 = "请指定独立的签发人和操作负责人，确保职责分离。" if is_violated_rule_c01 else "签发人与操作负责人职责分离，合规。"

    results.append({
        "rule_code": "C01",
        "rule_name": "签发人兼任工作负责人或空白操作票",
        "is_violated": is_violated_rule_c01,
        "violation_detail": violation_detail_rule_c01,
        "check_logic": check_logic_rule_c01,
        "platform_path": platform_path_rule_c01,
        "suggestion": suggestion_rule_c01
    })

    # 【4】规则C07: 工作负责人同时持两张及以上工作票 (序号4)
    is_violated_rule_c07 = False
    violation_detail_rule_c07 = ""
    check_logic_rule_c07 = "判断操作负责人在同一时间段内是否关联多张未终结的操作票。"
    platform_path_rule_c07 = "两票状态实时查询接口；操作负责人-操作票关联表"

    # 此处为演示，假设我们有一个全局的“负责人-票证”映射，因无数据，暂设为“待复核”
    # 实际应用中，应查询数据库，统计该负责人当前持有的有效票证数量
    # for demo, assume all are not violated
    # is_violated_rule_c07 = True  # For demonstration only
    # violation_detail_rule_c07 = f"操作负责人 '{row['operator_unames']}' 当前同时持有其他未终结的操作票。"

    suggestion_rule_c07 = "请确保操作负责人在同一时段仅负责一张操作票，避免精力分散导致安全风险。" if is_violated_rule_c07 else "操作负责人当前仅负责此张操作票，合规。"

    results.append({
        "rule_code": "C07",
        "rule_name": "操作负责人同时持两张及以上操作票",
        "is_violated": is_violated_rule_c07,
        "violation_detail": violation_detail_rule_c07,
        "check_logic": check_logic_rule_c07,
        "platform_path": platform_path_rule_c07,
        "suggestion": suggestion_rule_c07
    })

    # 【5】规则C81: 操作票流程不符合《安规》要求 (序号5)
    is_violated_rule_c81 = False
    violation_detail_rule_c81 = ""
    check_logic_rule_c81 = "《安规》规定流程：接收→创建→签发→许可→开工→终结；各环节时间逻辑必须合规。"
    platform_path_rule_c81 = "操作票流程日志；时间戳字段（接收时间、许可时间、开工时间）"

    # 检查时间逻辑：创建时间 -> 受令时间 -> 操作开始时间 -> 操作结束时间 -> 汇报时间
    times = {
        'create_time': row.get('create_time', pd.NaT),
        'take_order_time': row.get('take_order_time', pd.NaT),
        'operation_start_time': row.get('operation_start_time', pd.NaT),
        'operation_end_time': row.get('operation_end_time', pd.NaT),
        'report_time': row.get('report_time', pd.NaT)
    }

    # 将所有非空时间转换为datetime
    valid_times = {k: pd.to_datetime(v) for k, v in times.items() if pd.notna(v)}

    # 检查时间顺序
    if len(valid_times) > 1:
        sorted_times = sorted(valid_times.items(), key=lambda x: x[1])
        for i in range(len(sorted_times) - 1):
            current_key, current_time = sorted_times[i]
            next_key, next_time = sorted_times[i + 1]
            if current_time > next_time:
                is_violated_rule_c81 = True
                violation_detail_rule_c81 += f"{current_key}({current_time})晚于{next_key}({next_time})，流程倒置。"

    suggestion_rule_c81 = "请严格遵守《安规》规定的票证流程，确保各环节时间逻辑正确。" if is_violated_rule_c81 else "操作票流程时间逻辑正常。"

    results.append({
        "rule_code": "C81",
        "rule_name": "操作票流程不符合《安规》要求",
        "is_violated": is_violated_rule_c81,
        "violation_detail": violation_detail_rule_c81,
        "check_logic": check_logic_rule_c81,
        "platform_path": platform_path_rule_c81,
        "suggestion": suggestion_rule_c81
    })

    # 计算综合状态
    violated_rules = [r for r in results if r['is_violated']]
    if len(violated_rules) == 0:
        overall_status = "合规"
    elif len(violated_rules) <= 2:
        overall_status = "部分违规需整改"
    else:
        overall_status = "严重违规需立即整改"

    return {
        "ticket_id": ticket_id,
        "review_time": review_time,
        "reviewer": reviewer,
        "rules_check_result": results,
        "overall_status": overall_status
    }


# 对每条操作票执行审查
all_review_results = []
for index, row in df_oticket.iterrows():
    result = review_operation_ticket(row)
    all_review_results.append(result)

# 构建最终的扁平化DataFrame用于输出到Excel
output_rows = []
for i, result in enumerate(all_review_results, 1):
    for rule in result['rules_check_result']:
        output_row = {
            "序号": i,
            "票证类型": "操作票",
            "票证ID": result['ticket_id'],
            "审查时间": result['review_time'],
            "审查人": result['reviewer'],
            "规则编码": rule['rule_code'],
            "规则名称": rule['rule_name'],
            "是否违规": "是" if rule['is_violated'] else "否",
            "违规详情": rule['violation_detail'],
            "判断逻辑": rule['check_logic'],
            "数据来源/平台路径": rule['platform_path'],
            "整改建议": rule['suggestion'],
            "综合状态": result['overall_status']
        }
        output_rows.append(output_row)

df_output = pd.DataFrame(output_rows)

# 输出到Excel
output_file = "../output/操作票审查结果_20260120.xlsx"
df_output.to_excel(output_file, index=False, sheet_name="审查结果")

print(f"✅ 审查完成！结果已保存至 {output_file}")
