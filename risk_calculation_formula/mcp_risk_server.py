# -*- coding: utf-8 -*-
# @Project ：risk_v1.0
# @FileName: mcp_risk_server.py
# @Author  : greenaut
# @Time    : 2026/4/16

import json
import mysql.connector
from mysql.connector import Error

from mcp.server.fastmcp import FastMCP

import config_loader
from operator_capability_B import (
    calculate_b3_score,
    calculate_b4_score,
    calculate_person_score,
)
from operator_capability_C import (
    calculate_c2_score,
    calculate_c3_score,
    calculate_c4_score,
    calculate_c5_score,
)
from operator_capability_D import (
    calculate_D_value,
    get_major_name,
    extract_voltage_level,
)
from name_cleaner import init_name_extractor, get_name_extractor

import pandas as pd

# 从配置文件获取MCP服务配置
mcp_config = config_loader.get_mcp_config()
mcp = FastMCP("risk-assessment-server", host=mcp_config['host'], port=mcp_config['port'])

_name_extractor_initialized = False
_d_score_df = None
_fault_scene_df = None


def _get_db_config():
    return config_loader.get_db_config()


def _ensure_name_extractor():
    global _name_extractor_initialized
    if not _name_extractor_initialized:
        try:
            init_name_extractor(_get_db_config())
            _name_extractor_initialized = True
        except Exception as e:
            raise RuntimeError(f"姓名提取器初始化失败: {e}")


def _ensure_csv_data():
    global _d_score_df, _fault_scene_df
    if _d_score_df is None:
        _d_score_df = pd.read_csv(config_loader.get_d_score_path(), encoding="utf-8")
    if _fault_scene_df is None:
        _fault_scene_df = pd.read_csv(config_loader.get_fault_scene_path(), encoding="utf-8")


def _query_ticket_basic(ticket_id: str):
    db_config = _get_db_config()
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM sp_pd_wticket_base WHERE id = %s",
            (ticket_id,),
        )
        row = cursor.fetchone()
        return row
    except Error as e:
        raise RuntimeError(f"数据库查询失败: {e}")
    finally:
        cursor and cursor.close()
        conn and conn.close()


def _query_peccancy_by_names(names: list, current_year: int):
    if not names:
        return {}
    db_config = _get_db_config()
    start_date = f"{current_year}-01-01 00:00:00"
    end_date = f"{current_year}-12-31 23:59:59"
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        placeholders = ",".join(["%s"] * len(names))
        query = f"""
            SELECT peccancy_uname, peccancy_code, COUNT(*) as count
            FROM sp_ss_uq_peccancy_list_log
            WHERE peccancy_time >= %s AND peccancy_time <= %s
              AND peccancy_uname IN ({placeholders})
            GROUP BY peccancy_uname, peccancy_code
        """
        cursor.execute(query, [start_date, end_date] + names)
        rows = cursor.fetchall()
        peccancy_dict = {}
        for r in rows:
            uname = r["peccancy_uname"]
            if uname not in peccancy_dict:
                peccancy_dict[uname] = []
            peccancy_dict[uname].append(r)
        return peccancy_dict
    except Error as e:
        raise RuntimeError(f"违章记录查询失败: {e}")
    finally:
        cursor and cursor.close()
        conn and conn.close()


# ===================== MCP Tools =====================

@mcp.tool()
def query_risk_a(ticket_id: str) -> str:
    """查询A类作业风险评分。A类风险默认为0分（暂未配置评分规则）。当用户询问某工作票的A类风险时调用此工具。

    Args:
        ticket_id: 工作票id
    """
    ticket = _query_ticket_basic(ticket_id)
    if not ticket:
        return json.dumps({"success": False, "message": f"工作票 {ticket_id} 不存在"}, ensure_ascii=False)

    result = {
        "ticket_id": ticket_id,
        "success": True,
        "message": "A类风险评分查询成功",
        "A": 0,
        "detail": "A类风险默认为0（暂未配置评分规则）",
    }
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def query_risk_b(ticket_id: str) -> str:
    """查询B类作业风险评分（作业人员能力风险）。包含B1工作负责人违章评分、B2班组成员违章评分、B3作业总人数评分、B4人员性质评分。当用户询问某工作票的B类风险或作业人员能力风险时调用此工具。

    Args:
        ticket_id: 工作票id
    """
    ticket = _query_ticket_basic(ticket_id)
    if not ticket:
        return json.dumps({"success": False, "message": f"工作票 {ticket_id} 不存在"}, ensure_ascii=False)

    _ensure_name_extractor()
    name_extractor = get_name_extractor()
    current_year = config_loader.get_current_year()

    principal_name = ticket.get("work_principal_uname") or ""
    member_text = ticket.get("work_member_uname") or ""
    raw_count = ticket.get("work_member_count")
    member_count = int(raw_count) if raw_count is not None else 0
    outer_dept = ticket.get("whether_outer_dept")

    B3 = calculate_b3_score(member_count)
    B4 = calculate_b4_score(outer_dept)

    all_names = [principal_name] if principal_name else []
    member_names = []
    if member_text:
        try:
            member_names = name_extractor.extract_names(member_text)
        except Exception:
            member_names = []
        all_names.extend(member_names)

    peccancy_dict = _query_peccancy_by_names(all_names, current_year)

    if principal_name:
        leader_records = peccancy_dict.get(principal_name, [])
        if leader_records:
            B1, criteria_str = calculate_person_score(leader_records, "工作负责人")
            B1_criteria = f"{principal_name}：{criteria_str}"
        else:
            B1 = 0
            B1_criteria = f"{principal_name}：无违章记录"
    else:
        B1 = 0
        B1_criteria = "无工作负责人信息"

    B2 = 0
    if member_names:
        member_criteria_list = []
        for mname in member_names:
            m_records = peccancy_dict.get(mname, [])
            if m_records:
                m_score, m_criteria = calculate_person_score(m_records, mname)
                B2 += m_score
                member_criteria_list.append(f"{mname}：{m_criteria}")
            else:
                member_criteria_list.append(f"{mname}：无违章记录")
        B2_criteria = "；".join(member_criteria_list)
    else:
        B2_criteria = "无工作班成员信息"

    B = B1 + B2 + B3 + B4

    result = {
        "ticket_id": ticket_id,
        "success": True,
        "message": "B类风险评分查询成功",
        "B": B,
        "sub_scores": {
            "B1": B1,
            "B1_criteria": B1_criteria,
            "B2": B2,
            "B2_criteria": B2_criteria,
            "B3": B3,
            "B3_member_count": member_count,
            "B4": B4,
            "B4_outer_dept": str(outer_dept) if outer_dept is not None else "",
        },
    }
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def query_risk_c(ticket_id: str) -> str:
    """查询C类作业风险评分（作业环境和时间影响风险）。包含C1气象评分、C2作业地段评分、C3作业方式评分、C4作业时段评分、C5特殊场景作业评分。当用户询问某工作票的C类风险或作业环境风险时调用此工具。

    Args:
        ticket_id: 工作票id
    """
    ticket = _query_ticket_basic(ticket_id)
    if not ticket:
        return json.dumps({"success": False, "message": f"工作票 {ticket_id} 不存在"}, ensure_ascii=False)

    work_place = ticket.get("work_place") or ""
    is_key_station = ticket.get("is_key_station")
    is_re_fire = ticket.get("is_re_fire")
    work_task = ticket.get("work_task") or ""
    permission_time = ticket.get("permission_time")
    whether_es_risk = ticket.get("whether_es_risk")

    C1 = 0
    C1_criteria = "缺气象数据"

    C2, C2_criteria = calculate_c2_score(work_place, work_task, is_key_station)
    C3, C3_criteria = calculate_c3_score(is_re_fire, work_task)
    C4, C4_criteria = calculate_c4_score(permission_time)
    C5, C5_criteria = calculate_c5_score(whether_es_risk)

    C = C1 + C2 + C3 + C4 + C5

    result = {
        "ticket_id": ticket_id,
        "success": True,
        "message": "C类风险评分查询成功",
        "C": C,
        "sub_scores": {
            "C1": C1,
            "C1_criteria": C1_criteria,
            "C2": C2,
            "C2_criteria": C2_criteria,
            "C3": C3,
            "C3_criteria": C3_criteria,
            "C4": C4,
            "C4_criteria": C4_criteria,
            "C5": C5,
            "C5_criteria": C5_criteria,
        },
    }
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def query_risk_d(ticket_id: str) -> str:
    """查询D类作业风险评分（设备故障风险）。基于典型故障场景匹配和事故后果判定D值。当用户询问某工作票的D类风险或设备故障风险时调用此工具。

    Args:
        ticket_id: 工作票id
    """
    ticket = _query_ticket_basic(ticket_id)
    if not ticket:
        return json.dumps({"success": False, "message": f"工作票 {ticket_id} 不存在"}, ensure_ascii=False)

    _ensure_csv_data()

    work_place = ticket.get("work_place") or ""
    work_task = ticket.get("work_task") or ""
    major = str(ticket.get("major") or "")

    major_name = get_major_name(major)
    voltage_level = extract_voltage_level(work_task)

    row_dict = {
        "major_name": major_name,
        "work_task": work_task,
        "work_place": work_place,
        "voltage_level": voltage_level,
    }

    d_value, is_match, consequence, detail = calculate_D_value(
        row_dict, _d_score_df, _fault_scene_df
    )

    result = {
        "ticket_id": ticket_id,
        "success": True,
        "message": "D类风险评分查询成功",
        "D": d_value,
        "is_matched_scene": "是" if is_match else "否",
        "accident_consequence": consequence if is_match else "",
        "detail": detail,
    }
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def query_risk_all(ticket_id: str) -> str:
    """查询全类作业风险评分（F=A+B+C+D）。综合A类、B类作业人员能力、C类作业环境时间、D类设备故障四类风险，计算总风险值F。当用户询问某工作票的总体风险等级或全部风险时调用此工具。

    Args:
        ticket_id: 工作票id
    """
    ticket = _query_ticket_basic(ticket_id)
    if not ticket:
        return json.dumps({"success": False, "message": f"工作票 {ticket_id} 不存在"}, ensure_ascii=False)

    a_result = json.loads(query_risk_a(ticket_id))
    b_result = json.loads(query_risk_b(ticket_id))
    c_result = json.loads(query_risk_c(ticket_id))
    d_result = json.loads(query_risk_d(ticket_id))

    A = a_result.get("A", 0)
    B = b_result.get("B", 0)
    C = c_result.get("C", 0)
    D = d_result.get("D", 0)
    F = A + B + C + D

    result = {
        "ticket_id": ticket_id,
        "success": True,
        "message": "全类风险评分查询成功",
        "A": A,
        "B": B,
        "C": C,
        "D": D,
        "F": F,
        "b_sub": b_result.get("sub_scores"),
        "c_sub": c_result.get("sub_scores"),
        "d_sub": {
            "D": D,
            "is_matched_scene": d_result.get("is_matched_scene"),
            "accident_consequence": d_result.get("accident_consequence"),
            "detail": d_result.get("detail"),
        },
    }
    return json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run("streamable-http")
