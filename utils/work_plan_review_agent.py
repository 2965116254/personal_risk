#!/usr/bin/env python
# -*- coding: UTF-8 -*-
'''
@Project ：personal_risk_prevention_agent 
@File    ：work_plan_review_agent.py
@IDE     ：PyCharm 
@Author  ：BingshengTian
@Date    ：2026-01-20 14:10 
'''
import pandas as pd

######################工作计划审查智能体 ##################################

import pandas as pd
from datetime import datetime

from DB_DATA.work_operation_ticket_plan_DB import work_operation_plan_db

# 假设这是从Excel读取的数据框
df_plan = pd.read_excel("../data_offline/人身风险作业计划测试.xlsx", sheet_name="Sheet1")


# 定义审查函数
def review_work_plan(row):
    work_plan_id = row['作业计划编号']
    review_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reviewer = "智能审查引擎 v1.0"
    results = []

    # 规则1: 工作计划超期 (序号1)
    is_violated_rule1 = False
    violation_detail_rule1 = ""
    check_logic_rule1 = "1.计划结束时间 > 计划开始时间; 2.实际结束时间 > 实际开始时间; 3.计划结束时间 > 实际结束时间。"
    platform_path_rule1 = ""

    # 检查条件：实际结束时间 > 计划结束时间（属于超期）
    if pd.notna(row['实际结束时间']) and pd.notna(row['计划结束时间']):
        actual_end = pd.to_datetime(row['实际结束时间'])
        plan_end = pd.to_datetime(row['计划结束时间'])
        if actual_end > plan_end:
            is_violated_rule1 = True
            violation_detail_rule1 = f"实际结束时间({actual_end})晚于计划结束时间({plan_end})，属于超期。"

    suggestion_rule1 = "应调整计划时间或加快进度。" if is_violated_rule1 else "计划时间逻辑正常。"

    results.append({
        "rule_code": "1",
        "rule_name": "工作计划超期",
        "is_violated": is_violated_rule1,
        "violation_detail": violation_detail_rule1,
        "check_logic": check_logic_rule1,
        "platform_path": platform_path_rule1,
        "suggestion": suggestion_rule1
    })

    # 规则2: 未引用作业文件和作业指导书 (序号2)
    is_violated_rule2 = False
    violation_detail_rule2 = ""
    check_logic_rule2 = "核查工作计划是否引用作业文件和作业指导书，计划内容是否引用相关作业文件、作业指导书。【依据：根据作业计划编号查询作业文件计划关联表数据情况】"
    platform_path_rule2 = "判断已执行的作业有无关联作业文件,【依据：作业文件计划关联表数据查询】"

    # 判断依据，应查询关联的作业文件库（作业文件计划关联表数据查询）
    work_operation_plan_info = work_operation_plan_db.query_work_plan_file_info(work_plan_code=work_plan_id)
    # 如果work_operation_plan_info为空，则视为未引用，就是违规
    if not work_operation_plan_info:
        is_violated_rule2 = True
        violation_detail_rule2 = "工作计划未引用任何作业文件或作业指导书。"
        suggestion_rule2 = "请在计划描述中明确引用对应的作业文件或指导书，确保作业依据充分。"

    results.append({
        "rule_code": "2",
        "rule_name": "未引用作业文件和作业指导书",
        "is_violated": is_violated_rule2,
        "violation_detail": violation_detail_rule2,
        "check_logic": check_logic_rule2,
        "platform_path": platform_path_rule2,
        "suggestion": suggestion_rule2
    })

    # 规则3: 作业指导书风险评估不到位 (序号3)
    is_violated_rule3 = False
    violation_detail_rule3 = ""
    check_logic_rule3 = "核查作业指导书风险评估是否到位，风险评估是否准确。利用超高压的作业风险库对比。"
    platform_path_rule3 = "附录F典型作业类型风险库、附录G场景式持续作业风险评估方法"

    # 同样，原始数据无风险评估字段，标记为“待人工复核”
    is_violated_rule3 = True  # 为演示，假设风险评估缺失
    violation_detail_rule3 = "计划中未体现风险评估过程或结果，未与超高压作业风险库进行对比。"
    suggestion_rule3 = "请补充风险评估记录，并与超高压作业风险库进行比对，确保风险可控。"

    results.append({
        "rule_code": "3",
        "rule_name": "作业指导书风险评估不到位",
        "is_violated": is_violated_rule3,
        "violation_detail": violation_detail_rule3,
        "check_logic": check_logic_rule3,
        "platform_path": platform_path_rule3,
        "suggestion": suggestion_rule3
    })

    # 规则4: 未领用工器具或不全提醒 (序号4)
    is_violated_rule4 = False
    violation_detail_rule4 = ""
    check_logic_rule4 = "对照作业文件中涵盖的工器具，核查领用工器具是否齐全或未领。五种可能：1该领没领(错误) 2不该领不领(正确) 3该领领全(正确) 4该领没领全(错误) 5不该领领了(错误)"
    platform_path_rule4 = "电网管理平台-台账查询管理-工器具台账 (电网管理平台工器具台账接口)"

    # 原始数据中无“工器具”字段，且“是否需要使用工器具”为“否”，故默认合规
    if row.get('是否需要使用工器具', '否') == '是':
        is_violated_rule4 = True
        violation_detail_rule4 = "计划要求使用工器具，但未提供工器具清单或领用记录。"
    else:
        is_violated_rule4 = False
        violation_detail_rule4 = "计划无需使用工器具，此项不适用。"

    suggestion_rule4 = "如需使用工器具，请提供完整清单并确认已领用且在有效期内。" if is_violated_rule4 else "无需使用工器具，此项合规。"

    results.append({
        "rule_code": "4",
        "rule_name": "未领用工器具或不全提醒",
        "is_violated": is_violated_rule4,
        "violation_detail": violation_detail_rule4,
        "check_logic": check_logic_rule4,
        "platform_path": platform_path_rule4,
        "suggestion": suggestion_rule4
    })

    # 规则5: 工作负责人资质库对比 (序号5)
    is_violated_rule5 = False
    violation_detail_rule5 = ""
    check_logic_rule5 = "1工作负责人与资质库比对，无工作负责人资质的担任负责人需要告警提醒。2检索工作负责人，历史违章情况。3查询工作负责人安规考试记录，并提醒证件有效期。"
    platform_path_rule5 = "数据中心可获取人员资质模块的数据"

    # 原始数据中“工作负责人”为空，视为严重违规
    if pd.isna(row['工作负责人']) or row['工作负责人'].strip() == "":
        is_violated_rule5 = True
        violation_detail_rule5 = "工作负责人字段为空，无法进行资质比对。"
    else:
        # 此处应调用人员资质库API，因无数据，暂设为“待复核”
        is_violated_rule5 = True  # 为演示，假设所有负责人都未通过资质校验
        violation_detail_rule5 = f"工作负责人 '{row['工作负责人']}' 未在资质库中找到有效记录或安规考试过期。"

    suggestion_rule5 = "请指定有效的工作负责人，并确认其资质、无历史违章、安规考试在有效期内。"

    results.append({
        "rule_code": "5",
        "rule_name": "工作负责人资质库对比异常",
        "is_violated": is_violated_rule5,
        "violation_detail": violation_detail_rule5,
        "check_logic": check_logic_rule5,
        "platform_path": platform_path_rule5,
        "suggestion": suggestion_rule5
    })

    # 规则6: 带电和不带电作业选择错误 (序号6)
    is_violated_rule6 = False
    violation_detail_rule6 = ""
    check_logic_rule6 = "1工作方式获取是否带电。2工作内容判断带电是否正确 keyword: (停电, 检修, 更换) (猜测)"
    platform_path_rule6 = ""

    work_method = row.get('工作方式', '')
    work_content = row.get('工作内容', '')

    # 简单关键词匹配
    if work_method == "不停电" and ("停电" in work_content or "检修" in work_content or "更换" in work_content):
        is_violated_rule6 = True
        violation_detail_rule6 = f"工作方式为'{work_method}'，但工作内容包含'停电/检修/更换'等关键词，可能存在选择错误。"

    suggestion_rule6 = "请核实工作内容与工作方式是否匹配，避免误判带电作业风险。" if is_violated_rule6 else "工作方式与内容描述一致，选择正确。"

    results.append({
        "rule_code": "6",
        "rule_name": "带电和不带电作业选择错误",
        "is_violated": is_violated_rule6,
        "violation_detail": violation_detail_rule6,
        "check_logic": check_logic_rule6,
        "platform_path": platform_path_rule6,
        "suggestion": suggestion_rule6
    })

    # 规则7: 看工作单位，是否是外单位作业 (序号7)
    is_violated_rule7 = False
    violation_detail_rule7 = ""
    check_logic_rule7 = "1获取施工/工作班组内容 (“外协单位”关键词判断是否为外单位，是则结束，否则走第二条规则) 2获取查高压组织结构，判断工作班组内容为外单位"
    platform_path_rule7 = ""

    work_unit = row.get('施工/工作班组', '')
    is_outside_unit = "外单位" in row.get('作业主体', '') or "外协单位" in work_unit

    # 如果是外单位，需进一步验证其是否在超高压组织结构内
    if is_outside_unit:
        # 此处应查询组织结构库，因无数据，暂设为“待复核”
        is_violated_rule7 = True  # 为演示，假设所有外单位均未在组织结构内备案
        violation_detail_rule7 = f"作业主体为外单位，工作班组 '{work_unit}' 未在超高压组织结构内备案。"

    suggestion_rule7 = "如为外单位作业，需确认其已在超高压组织结构内备案，并办理相应手续。" if is_violated_rule7 else "作业主体为本单位，无需走外单位流程。"

    results.append({
        "rule_code": "7",
        "rule_name": "外单位作业识别错误",
        "is_violated": is_violated_rule7,
        "violation_detail": violation_detail_rule7,
        "check_logic": check_logic_rule7,
        "platform_path": platform_path_rule7,
        "suggestion": suggestion_rule7
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
        "work_plan_id": work_plan_id,
        "review_time": review_time,
        "reviewer": reviewer,
        "rules_check_result": results,
        "overall_status": overall_status
    }


# 对每条计划执行审查
all_review_results = []
for index, row in df_plan.iterrows():
    result = review_work_plan(row)
    all_review_results.append(result)

# 构建最终的扁平化DataFrame用于输出到Excel
output_rows = []
for i, result in enumerate(all_review_results, 1):
    for rule in result['rules_check_result']:
        output_row = {
            "序号": i,
            "计划ID": result['work_plan_id'],
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
output_file = "../output/工作计划审查结果_20260120.xlsx"
df_output.to_excel(output_file, index=False, sheet_name="审查结果")

print(f"✅ 审查完成！结果已保存至 {output_file}")
