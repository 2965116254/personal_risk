# -*- coding: utf-8 -*-
# @Project ：risk_v1.0
# @FileName: api.py
# @Author  : greenaut
# @Time    : 2026/4/16

import os
import mysql.connector
from mysql.connector import Error
from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

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
    D_SCORE_DF as D_SCORE_GLOBAL,
    FAULT_SCENE_DF as FAULT_SCENE_GLOBAL,
)
from name_cleaner import init_name_extractor, get_name_extractor

import pandas as pd

app = FastAPI(
    title="作业风险评估 API",
    description="通过工作票id查询 A/B/C/D 各类风险评分",
    version="1.0.0",
)

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


# ===================== Response Models =====================

class RiskBaseResponse(BaseModel):
    ticket_id: str
    success: bool
    message: str


class ARiskResponse(RiskBaseResponse):
    A: int = 0
    detail: str = "A类风险默认为0"


class BSubScore(BaseModel):
    B1: int
    B1_criteria: str
    B2: int
    B2_criteria: str
    B3: int
    B3_member_count: int
    B4: int
    B4_outer_dept: Optional[str] = ""


class BRiskResponse(RiskBaseResponse):
    B: int
    sub_scores: BSubScore


class CSubScore(BaseModel):
    C1: int
    C1_criteria: str
    C2: int
    C2_criteria: str
    C3: int
    C3_criteria: str
    C4: int
    C4_criteria: str
    C5: int
    C5_criteria: str


class CRiskResponse(RiskBaseResponse):
    C: int
    sub_scores: CSubScore


class DRiskResponse(RiskBaseResponse):
    D: int
    is_matched_scene: str
    accident_consequence: str
    detail: str


class AllRiskResponse(RiskBaseResponse):
    A: int
    B: int
    C: int
    D: int
    F: int
    b_sub: Optional[BSubScore] = None
    c_sub: Optional[CSubScore] = None
    d_sub: Optional[DRiskResponse] = None


# ===================== API Endpoints =====================

@app.get("/api/risk/a/{ticket_id}", response_model=ARiskResponse, summary="A类风险评分")
def get_risk_a(ticket_id: str = Path(..., description="工作票id")):
    ticket = _query_ticket_basic(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"工作票 {ticket_id} 不存在")
    return ARiskResponse(
        ticket_id=ticket_id,
        success=True,
        message="A类风险评分查询成功",
        A=0,
        detail="A类风险默认为0（暂未配置评分规则）",
    )


@app.get("/api/risk/b/{ticket_id}", response_model=BRiskResponse, summary="B类风险评分（作业人员能力）")
def get_risk_b(ticket_id: str = Path(..., description="工作票id")):
    ticket = _query_ticket_basic(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"工作票 {ticket_id} 不存在")

    _ensure_name_extractor()
    name_extractor = get_name_extractor()
    current_year = config_loader.get_current_year()

    principal_name = ticket.get("work_principal_uname") or ""
    member_text = ticket.get("work_member_uname") or ""
    raw_count = ticket.get("work_member_count")
    member_count = int(raw_count) if raw_count is not None else 0
    outer_dept = ticket.get("whether_outer_dept")

    # B3
    B3 = calculate_b3_score(member_count)

    # B4
    B4 = calculate_b4_score(outer_dept)

    # B1 - 工作负责人
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

    # B2 - 工作班成员
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

    return BRiskResponse(
        ticket_id=ticket_id,
        success=True,
        message="B类风险评分查询成功",
        B=B,
        sub_scores=BSubScore(
            B1=B1,
            B1_criteria=B1_criteria,
            B2=B2,
            B2_criteria=B2_criteria,
            B3=B3,
            B3_member_count=member_count,
            B4=B4,
            B4_outer_dept=str(outer_dept) if outer_dept is not None else "",
        ),
    )


@app.get("/api/risk/c/{ticket_id}", response_model=CRiskResponse, summary="C类风险评分（作业环境和时间影响）")
def get_risk_c(ticket_id: str = Path(..., description="工作票id")):
    ticket = _query_ticket_basic(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"工作票 {ticket_id} 不存在")

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

    return CRiskResponse(
        ticket_id=ticket_id,
        success=True,
        message="C类风险评分查询成功",
        C=C,
        sub_scores=CSubScore(
            C1=C1,
            C1_criteria=C1_criteria,
            C2=C2,
            C2_criteria=C2_criteria,
            C3=C3,
            C3_criteria=C3_criteria,
            C4=C4,
            C4_criteria=C4_criteria,
            C5=C5,
            C5_criteria=C5_criteria,
        ),
    )


@app.get("/api/risk/d/{ticket_id}", response_model=DRiskResponse, summary="D类风险评分（设备故障风险）")
def get_risk_d(ticket_id: str = Path(..., description="工作票id")):
    ticket = _query_ticket_basic(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"工作票 {ticket_id} 不存在")

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

    return DRiskResponse(
        ticket_id=ticket_id,
        success=True,
        message="D类风险评分查询成功",
        D=d_value,
        is_matched_scene="是" if is_match else "否",
        accident_consequence=consequence if is_match else "",
        detail=detail,
    )


@app.get("/api/risk/all/{ticket_id}", response_model=AllRiskResponse, summary="全类风险评分（F=A+B+C+D）")
def get_risk_all(ticket_id: str = Path(..., description="工作票id")):
    ticket = _query_ticket_basic(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"工作票 {ticket_id} 不存在")

    a_resp = get_risk_a(ticket_id)
    b_resp = get_risk_b(ticket_id)
    c_resp = get_risk_c(ticket_id)
    d_resp = get_risk_d(ticket_id)

    F = a_resp.A + b_resp.B + c_resp.C + d_resp.D

    return AllRiskResponse(
        ticket_id=ticket_id,
        success=True,
        message="全类风险评分查询成功",
        A=a_resp.A,
        B=b_resp.B,
        C=c_resp.C,
        D=d_resp.D,
        F=F,
        b_sub=b_resp.sub_scores,
        c_sub=c_resp.sub_scores,
        d_sub=d_resp,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8030, reload=True)
