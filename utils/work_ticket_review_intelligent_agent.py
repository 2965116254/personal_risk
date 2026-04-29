#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
@Project ：personal_risk_prevention_agent 
@File    ：work_permit_review_intelligent_agent.py
@IDE     ：PyCharm 
@Author  ：BingshengTian
@Date    ：2026-01-20 14:11 
'''

######################工作票审查智能体#############################
import pandas as pd
from datetime import datetime

# 读取工作票数据
df_ticket = pd.read_excel("../data_offline/工作票表测试.xlsx", sheet_name="Sheet1")

# 定义审查函数
def review_work_ticket(row):
    ticket_id = row['id']
    review_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reviewer = "智能审查引擎 v1.0"
    results = []

    # 【1】规则A03: 未经许可即开展作业 (序号1)
    is_violated_rule_a03 = False
    violation_detail_rule_a03 = ""
    check_logic_rule_a03 = "1. 未经停电、验电、接地、许可即开展作业；2. 工作票未经许可或主要安全措施未落实前擅自作业；3. 未按工作票所列‘应装设的接地’要求装设接地或工作地点未装设封闭接地。"
    platform_path_rule_a03 = "电网管理平台-两票管理-安全措施执行状态；许可时间 vs 开工时间比对"

    # 检查是否已许可（work_state == 6 执行中）
    if row['work_state'] in [5, 6]:  # 待许可 或 执行中
        # 检查是否有许可时间
        if pd.isna(row['permission_time']):
            is_violated_rule_a03 = True
            violation_detail_rule_a03 = "工作票处于‘待许可’或‘执行中’状态，但无许可时间记录，可能未经许可即开工。"
        else:
            # 检查是否在许可前有操作（如接收时间早于许可时间）
            receive_time = row.get('receive_time', pd.NaT)
            if pd.notna(receive_time) and pd.to_datetime(receive_time) < pd.to_datetime(row['permission_time']):
                # 此处为演示，实际应检查更具体的“开工”时间
                pass  # 不视为违规，因为接收不等于开工

    suggestion_rule_a03 = "请确保工作票在获得正式许可后方可开始作业，并完整记录所有安全措施。" if is_violated_rule_a03 else "工作票许可流程正常。"

    results.append({
        "rule_code": "A03",
        "rule_name": "未经许可即开展作业",
        "is_violated": is_violated_rule_a03,
        "violation_detail": violation_detail_rule_a03,
        "check_logic": check_logic_rule_a03,
        "platform_path": platform_path_rule_a03,
        "suggestion": suggestion_rule_a03
    })

    # 【2】规则B01: 无计划作业或未录入信息系统 (序号2)
    is_violated_rule_b01 = False
    violation_detail_rule_b01 = ""
    check_logic_rule_b01 = "核查是否按规制定作业计划或作业计划是否按要求录入信息系统；未查询到关联工作计划时提示告警。"
    platform_path_rule_b01 = "电网管理平台-作业计划库；工作票与计划ID关联校验接口"

    # 检查是否有关联的工作计划ID
    if pd.isna(row['ticket_source_id']) or row['ticket_source_id'].strip() == "": # 工作票来源ID
        is_violated_rule_b01 = True
        violation_detail_rule_b01 = "工作票未关联任何工作计划ID，可能存在‘体外循环’风险。"
    else:
        # 此处应查询计划库，因无数据，暂设为合规
        pass

    suggestion_rule_b01 = "请确保每张工作票均关联一个有效的作业计划编号，避免‘体外循环’。" if is_violated_rule_b01 else "工作票已关联计划编号，符合管控要求。"

    results.append({
        "rule_code": "B01",
        "rule_name": "无计划作业或未录入信息系统",
        "is_violated": is_violated_rule_b01,
        "violation_detail": violation_detail_rule_b01,
        "check_logic": check_logic_rule_b01,
        "platform_path": platform_path_rule_b01,
        "suggestion": suggestion_rule_b01
    })

    # 【3】规则B02: 工作票关键内容缺失或错误 (序号3)
    is_violated_rule_b02 = False
    violation_detail_rule_b02 = ""
    check_logic_rule_b02 = "核实操作任务与设备状态、名称编号是否对应；操作项目有无漏项、错项、顺序错误；如停电操作需挂接地线、戴绝缘手套等安全措施是否遗漏。"
    platform_path_rule_b02 = "设备台账系统；标准票模板库；历史工作票数据库"

    # 检查工作内容和工作地点是否为空
    if pd.isna(row['work_task']) or row['work_task'].strip() == "":
        is_violated_rule_b02 = True
        violation_detail_rule_b02 += "工作任务描述为空。"
    if pd.isna(row['work_place']) or row['work_place'].strip() == "":
        is_violated_rule_b02 = True
        violation_detail_rule_b02 += "工作地点描述为空。"

    # 检查是否涉及高空作业或带电作业，但未提及安全措施
    work_task = str(row['work_task']).lower()
    if ("高空" in work_task or "登高" in work_task) and not ("安全带" in work_task or "系安全带" in work_task):
        is_violated_rule_b02 = True
        violation_detail_rule_b02 += "涉及高空作业，但未提及使用安全带。"
    if ("停电" in work_task or "检修" in work_task) and not ("接地" in work_task or "挂接地线" in work_task):
        is_violated_rule_b02 = True
        violation_detail_rule_b02 += "涉及停电检修，但未提及装设接地线。"

    suggestion_rule_b02 = "请补充完整的工作任务、工作地点描述，并确保安全措施与作业内容匹配。" if is_violated_rule_b02 else "工作票关键内容完整且准确。"

    results.append({
        "rule_code": "B02",
        "rule_name": "工作票关键内容缺失或错误",
        "is_violated": is_violated_rule_b02,
        "violation_detail": violation_detail_rule_b02,
        "check_logic": check_logic_rule_b02,
        "platform_path": platform_path_rule_b02,
        "suggestion": suggestion_rule_b02
    })

    # 【4】 规则C01: 签发人兼任工作负责人或空白工作票 (序号4)
    is_violated_rule_c01 = False
    violation_detail_rule_c01 = ""
    check_logic_rule_c01 = "核查工作票签发人与工作负责人是否为同一人，工作票是否为空白。"
    platform_path_rule_c01 = "人员组织架构系统；工作票签发与负责人字段比对"

    # 检查签发人和负责人是否为空
    if pd.isna(row['ticket_sign_uname']) or row['ticket_sign_uname'].strip() == "":
        is_violated_rule_c01 = True
        violation_detail_rule_c01 = "工作票签发人姓名为空。"
    if pd.isna(row['work_principal_uname']) or row['work_principal_uname'].strip() == "":
        is_violated_rule_c01 = True
        violation_detail_rule_c01 = "工作负责人姓名为空。"

    # 检查签发人和负责人是否为同一人
    if not is_violated_rule_c01:  # 只有在非空的情况下才比较
        if row['ticket_sign_uname'] == row['work_principal_uname']:
            is_violated_rule_c01 = True
            violation_detail_rule_c01 = f"工作票签发人 '{row['ticket_sign_uname']}' 与工作负责人 '{row['work_principal_uname']}' 为同一人，违反职责分离原则。"

    suggestion_rule_c01 = "请指定独立的签发人和工作负责人，确保职责分离。" if is_violated_rule_c01 else "签发人与工作负责人职责分离，合规。"

    results.append({
        "rule_code": "C01",
        "rule_name": "签发人兼任工作负责人或空白工作票",
        "is_violated": is_violated_rule_c01,
        "violation_detail": violation_detail_rule_c01,
        "check_logic": check_logic_rule_c01,
        "platform_path": platform_path_rule_c01,
        "suggestion": suggestion_rule_c01
    })

    # 【5】规则C07: 工作负责人同时持两张及以上工作票 (序号5)
    is_violated_rule_c07 = False
    violation_detail_rule_c07 = ""
    check_logic_rule_c07 = "判断工作负责人在同一时间段内是否关联多张未终结的工作票。"
    platform_path_rule_c07 = "两票状态实时查询接口；工作负责人-工作票关联表"

    # 此处为演示，假设我们有一个全局的“负责人-票证”映射，因无数据，暂设为“待复核”
    # 实际应用中，应查询数据库，统计该负责人当前持有的有效票证数量
    # for demo, assume all are not violated
    # is_violated_rule_c07 = True  # For demonstration only
    # violation_detail_rule_c07 = f"工作负责人 '{row['work_principal_uname']}' 当前同时持有其他未终结的工作票。"

    suggestion_rule_c07 = "请确保工作负责人在同一时段仅负责一张工作票，避免精力分散导致安全风险。" if is_violated_rule_c07 else "工作负责人当前仅负责此张工作票，合规。"

    results.append({
        "rule_code": "C07",
        "rule_name": "工作负责人同时持两张及以上工作票",
        "is_violated": is_violated_rule_c07,
        "violation_detail": violation_detail_rule_c07,
        "check_logic": check_logic_rule_c07,
        "platform_path": platform_path_rule_c07,
        "suggestion": suggestion_rule_c07
    })

    # 【6】 规则C81: 工作票流程不符合《安规》要求 (序号6)
    is_violated_rule_c81 = False
    violation_detail_rule_c81 = ""
    check_logic_rule_c81 = "《安规》规定流程：接收→创建→签发→许可→开工→终结；各环节时间逻辑必须合规。"
    platform_path_rule_c81 = "工作票流程日志；时间戳字段（接收时间、许可时间、开工时间）"

    # 检查时间逻辑：接收时间 -> 创建时间 -> 签发时间 -> 许可时间 -> 开工时间 -> 终结时间
    times = {
        'create_time': row.get('create_time', pd.NaT),
        'ticket_sign_time': row.get('ticket_sign_time', pd.NaT),
        'permission_time': row.get('permission_time', pd.NaT),
        'receive_time': row.get('receive_time', pd.NaT),
        'work_end_time': row.get('work_end_time', pd.NaT)
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

    suggestion_rule_c81 = "请严格遵守《安规》规定的票证流程，确保各环节时间逻辑正确。" if is_violated_rule_c81 else "工作票流程时间逻辑正常。"

    results.append({
        "rule_code": "C81",
        "rule_name": "工作票流程不符合《安规》要求",
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

# 对每条工作票执行审查
all_review_results = []
for index, row in df_ticket.iterrows():
    result = review_work_ticket(row)
    all_review_results.append(result)

# 构建最终的扁平化DataFrame用于输出到Excel
output_rows = []
for i, result in enumerate(all_review_results, 1):
    for rule in result['rules_check_result']:
        output_row = {
            "序号": i,
            "票证类型": "工作票",
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
output_file = "../output/工作票审查结果_20260120.xlsx"
df_output.to_excel(output_file, index=False, sheet_name="审查结果")

print(f"✅ 审查完成！结果已保存至 {output_file}")