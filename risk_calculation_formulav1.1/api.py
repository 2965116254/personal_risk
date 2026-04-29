# -*- coding: utf-8 -*-
# @Project ：personal_risk_prevention_algo 
# @FileName: api.py
# @Author  : 
# @Time    : 2026/4/28
# @Description: 规则B、C、D的API接口服务

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
import uvicorn
import config_loader
import calculators
import risk_rules
import json

app = FastAPI(title="风险评估API服务", description="规则B、C、D的风险评估接口")

# 数据库配置缓存
_db_config = None

def get_db_config():
    """获取数据库配置"""
    global _db_config
    if _db_config is None:
        _db_config = config_loader.get_db_new_config()
    return _db_config

class RiskResult(BaseModel):
    """风险评估结果模型"""
    work_ticket_no: Optional[str] = Field(None, description="工作票票号")
    work_plan_code: Optional[str] = Field(None, description="作业计划编号")
    work_task: Optional[str] = Field(None, description="工作任务")
    B_score: float = Field(description="作业人员能力风险值(B)")
    C_score: float = Field(description="作业环境和时间影响风险值(C)")
    D_score: float = Field(description="电网、设备风险联动值(D)")
    F_score: float = Field(description="总风险值(F)")
    detailed_results: List[Dict] = Field(description="详细评估结果")

class SingleFactorInput(BaseModel):
    """单个评估因子计算输入"""
    factor_type: str = Field(description="评估因子类型")
    input_value: str = Field(description="输入值")

class BatchQueryInput(BaseModel):
    """批量查询输入"""
    ticket_source_ids: Optional[List[int]] = Field(None, description="作业计划ID列表")
    limit: Optional[int] = Field(None, description="限制返回数量")
    start_date: Optional[str] = Field(None, description="开始日期(YYYY-MM-DD)")
    end_date: Optional[str] = Field(None, description="结束日期(YYYY-MM-DD)")

@app.get("/api/risk/calculate", response_model=List[RiskResult], summary="计算风险值")
async def calculate_risk(
    limit: Optional[int] = Query(None, description="限制返回数量"),
    start_date: Optional[str] = Query(None, description="开始日期(YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="结束日期(YYYY-MM-DD)")
):
    """
    计算风险值 - 获取所有符合条件的工作票风险评估结果
    
    参数:
    - limit: 限制返回数量
    - start_date: 开始日期
    - end_date: 结束日期
    """
    try:
        db_config = get_db_config()
        results = calculators.calculate_risk_score(
            db_config,
            limit=limit,
            start_date=start_date,
            end_date=end_date
        )
        
        if not results:
            return []
        
        # 转换为API响应格式
        response = []
        for result in results:
            response.append(RiskResult(
                work_ticket_no=result.get('工作票票号', ''),
                work_plan_code=result.get('作业计划编号', ''),
                work_task=result.get('工作任务', ''),
                B_score=result.get('B（作业人员能力风险值）', 0),
                C_score=result.get('C（作业环境和时间影响风险值）', 0),
                D_score=result.get('D（电网、设备风险联动值）', 0),
                F_score=result.get('F（总风险值）', 0),
                detailed_results=result.get('详细评估结果', [])
            ))
        
        return response
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算风险值失败: {str(e)}")

@app.get("/api/risk/B", response_model=List[RiskResult], summary="计算规则B - 作业人员能力风险值")
async def calculate_rule_B(
    limit: Optional[int] = Query(None, description="限制返回数量"),
    start_date: Optional[str] = Query(None, description="开始日期(YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="结束日期(YYYY-MM-DD)")
):
    """
    计算规则B - 作业人员能力风险值
    
    规则B包含以下评估因子:
    - 工作负责人(含小组工作负责人)安全意识
    - 主要工作班成员(辅助工除外)安全意识
    - 监护人(含专职监护人)安全意识
    - 作业总人数
    - 负责人的人员性质
    - 工作负责人组织同类型作业次数
    - 主要工作班成员参与同类型作业次数
    - 监护人参与同类型作业次数
    - 计划性质
    
    参数:
    - limit: 限制返回数量
    - start_date: 开始日期
    - end_date: 结束日期
    """
    try:
        db_config = get_db_config()
        results = calculators.calculate_risk_score(
            db_config,
            limit=limit,
            start_date=start_date,
            end_date=end_date
        )
        
        if not results:
            return []
        
        # 转换为API响应格式，只关注B值
        response = []
        for result in results:
            response.append(RiskResult(
                work_ticket_no=result.get('工作票票号', ''),
                work_plan_code=result.get('作业计划编号', ''),
                work_task=result.get('工作任务', ''),
                B_score=result.get('B（作业人员能力风险值）', 0),
                C_score=0,
                D_score=0,
                F_score=result.get('B（作业人员能力风险值）', 0),
                detailed_results=[r for r in result.get('详细评估结果', []) 
                                if any(keyword in r.get('评估因子', '') for keyword in 
                                        ['安全意识', '作业总人数', '人员性质', '同类型作业次数', '计划性质'])]
            ))
        
        return response
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算规则B失败: {str(e)}")

@app.get("/api/risk/C", response_model=List[RiskResult], summary="计算规则C - 作业环境和时间影响风险值")
async def calculate_rule_C(
    limit: Optional[int] = Query(None, description="限制返回数量"),
    start_date: Optional[str] = Query(None, description="开始日期(YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="结束日期(YYYY-MM-DD)")
):
    """
    计算规则C - 作业环境和时间影响风险值
    
    规则C包含以下评估因子:
    - 作业地段、类型
    - 天气
    - 作业时段
    - 单日持续作业时长(疲劳度)
    - 计划性质
    - 关键重要站点(线路)
    
    参数:
    - limit: 限制返回数量
    - start_date: 开始日期
    - end_date: 结束日期
    """
    try:
        db_config = get_db_config()
        results = calculators.calculate_risk_score(
            db_config,
            limit=limit,
            start_date=start_date,
            end_date=end_date
        )
        
        if not results:
            return []
        
        # 转换为API响应格式，只关注C值
        response = []
        for result in results:
            response.append(RiskResult(
                work_ticket_no=result.get('工作票票号', ''),
                work_plan_code=result.get('作业计划编号', ''),
                work_task=result.get('工作任务', ''),
                B_score=0,
                C_score=result.get('C（作业环境和时间影响风险值）', 0),
                D_score=0,
                F_score=result.get('C（作业环境和时间影响风险值）', 0),
                detailed_results=[r for r in result.get('详细评估结果', []) 
                                if any(keyword in r.get('评估因子', '') for keyword in 
                                        ['作业地段', '作业类型', '天气', '作业时段', '单日持续作业时长', '关键重要站点'])]
            ))
        
        return response
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算规则C失败: {str(e)}")

@app.get("/api/risk/D", response_model=List[RiskResult], summary="计算规则D - 电网、设备风险联动值")
async def calculate_rule_D(
    limit: Optional[int] = Query(None, description="限制返回数量"),
    start_date: Optional[str] = Query(None, description="开始日期(YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="结束日期(YYYY-MM-DD)")
):
    """
    计算规则D - 电网、设备风险联动值
    
    规则D包含以下评估因子:
    - 事故后果
    - 设备风险
    
    参数:
    - limit: 限制返回数量
    - start_date: 开始日期
    - end_date: 结束日期
    """
    try:
        db_config = get_db_config()
        results = calculators.calculate_risk_score(
            db_config,
            limit=limit,
            start_date=start_date,
            end_date=end_date
        )
        
        if not results:
            return []
        
        # 转换为API响应格式，只关注D值
        response = []
        for result in results:
            response.append(RiskResult(
                work_ticket_no=result.get('工作票票号', ''),
                work_plan_code=result.get('作业计划编号', ''),
                work_task=result.get('工作任务', ''),
                B_score=0,
                C_score=0,
                D_score=result.get('D（电网、设备风险联动值）', 0),
                F_score=result.get('D（电网、设备风险联动值）', 0),
                detailed_results=[r for r in result.get('详细评估结果', []) 
                                if any(keyword in r.get('评估因子', '') for keyword in 
                                        ['事故后果', '设备风险'])]
            ))
        
        return response
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算规则D失败: {str(e)}")

@app.get("/api/risk/factor/safety_awareness", summary="计算安全意识评分")
async def calculate_safety_awareness(
    peccancy_records: Optional[str] = Query(None, description="违章记录JSON字符串，如: {\"A\":1,\"B\":2}"),
    awareness_level: Optional[str] = Query(None, description="安全意识等级")
):
    """
    计算安全意识评分
    
    参数:
    - peccancy_records: 违章记录JSON字符串（优先）
    - awareness_level: 安全意识等级
    
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
                raise HTTPException(status_code=400, detail="peccancy_records格式错误")
        elif awareness_level:
            score = risk_rules.calculate_safety_awareness_score(awareness_level)
        
        return {"factor_type": "安全意识", "score": score}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算安全意识评分失败: {str(e)}")

@app.get("/api/risk/factor/work_count", summary="计算作业总人数评分")
async def calculate_work_count(count: int = Query(description="作业总人数")):
    """
    计算作业总人数评分
    
    参数:
    - count: 作业总人数
    
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
        return {"factor_type": "作业总人数", "input_value": count, "score": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算作业总人数评分失败: {str(e)}")

@app.get("/api/risk/factor/personnel_nature", summary="计算人员性质评分")
async def calculate_personnel_nature(nature: str = Query(description="人员性质")):
    """
    计算人员性质评分
    
    参数:
    - nature: 人员性质
    
    评分规则:
    - 外施工单位劳务分包人员: 8分
    - 外施工单位人员: 5分
    - 本单位人员: 0分
    """
    try:
        score = risk_rules.calculate_personnel_nature_score(nature)
        return {"factor_type": "人员性质", "input_value": nature, "score": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算人员性质评分失败: {str(e)}")

@app.get("/api/risk/factor/experience", summary="计算作业经验评分")
async def calculate_experience(count: int = Query(description="同类型作业次数")):
    """
    计算作业经验评分（同类型作业次数）
    
    参数:
    - count: 同类型作业次数
    
    评分规则:
    - 第一次承担该类作业: 6分
    - 累计不足3次但不是第一次: 5分
    - 累计不足5次但不小于3次: 3分
    - 1年内2次及以上或2年内5次及以上: 0分
    - 其他累计5次及以上: 2分
    """
    try:
        score = risk_rules.get_same_type_score(count)
        return {"factor_type": "作业经验", "input_value": count, "score": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算作业经验评分失败: {str(e)}")

@app.get("/api/risk/factor/work_hours", summary="计算单日持续作业时长评分")
async def calculate_work_hours(hours: float = Query(description="单日持续作业时长(小时)")):
    """
    计算单日持续作业时长评分（疲劳度）
    
    参数:
    - hours: 单日持续作业时长(小时)
    
    评分规则:
    - ≤4小时: 0分
    - 4-8小时: 2分
    - 8-12小时: 10分
    - >12小时: 20分
    """
    try:
        score = risk_rules.calculate_single_day_work_hours_score(hours)
        return {"factor_type": "单日持续作业时长", "input_value": hours, "score": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算单日持续作业时长评分失败: {str(e)}")

@app.get("/api/risk/factor/plan_nature", summary="计算计划性质评分")
async def calculate_plan_nature(plan_nature: str = Query(description="计划性质")):
    """
    计算计划性质评分
    
    参数:
    - plan_nature: 计划性质
    
    评分规则:
    - 计划性作业: 0分
    - 提前一日制定的临时性作业任务: 10分
    - 当日制定的临时性作业任务: 20分
    """
    try:
        score = risk_rules.calculate_plan_nature_score(plan_nature)
        return {"factor_type": "计划性质", "input_value": plan_nature, "score": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算计划性质评分失败: {str(e)}")

@app.get("/api/risk/factor/location", summary="计算作业地段评分")
async def calculate_work_location(work_content: str = Query(description="工作内容描述")):
    """
    根据工作内容描述计算作业地段评分
    
    参数:
    - work_content: 工作内容描述
    
    评分规则:
    - 有限空间内作业(设施完备): 3分
    - 有限空间内作业(设施不完备): 10分
    - 氧气不足或有毒有害气体超标: 999分(禁止作业)
    - 多回共塔带电线路: 10分
    - 林区内作业: 15分
    - 地质隐患区内作业: 15分
    - 可能造成导地线、光缆脱落且含重要交叉跨越: 30分
    - 其他: 0分
    """
    try:
        score = 0
        if '有限空间' in work_content:
            if '完备' in work_content or '良好' in work_content:
                score = 3
            else:
                score = 10
        elif '氧气不足' in work_content or '有毒有害' in work_content:
            score = 999
        elif '多回共塔' in work_content or '带电线路' in work_content:
            score = 10
        elif '林区' in work_content:
            score = 15
        elif '地质隐患' in work_content:
            score = 15
        elif '导地线' in work_content or '光缆脱落' in work_content or '重要交叉' in work_content:
            score = 30
        
        return {"factor_type": "作业地段", "input_value": work_content, "score": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算作业地段评分失败: {str(e)}")

@app.get("/api/risk/factor/work_type", summary="计算作业类型评分")
async def calculate_work_type(work_content: str = Query(description="工作内容描述")):
    """
    根据工作内容描述计算作业类型评分
    
    参数:
    - work_content: 工作内容描述
    
    评分规则:
    - 地面以上1.5米以下: 0分
    - 1.5米以上5米以下: 2分
    - 5米以上15米以下: 5分
    - 15米以上30米以下: 7分
    - 30米以上: 10分
    - 动火作业: 5分
    - 大型吊装作业: 5分
    """
    try:
        score = 0
        if '地面' in work_content or '1.5米以下' in work_content:
            score = 0
        elif '1.5米以上' in work_content and '5米以下' in work_content:
            score = 2
        elif '5米以上' in work_content and '15米以下' in work_content:
            score = 5
        elif '15米以上' in work_content and '30米以下' in work_content:
            score = 7
        elif '30米以上' in work_content:
            score = 10
        elif '动火' in work_content:
            score = 5
        elif '吊装' in work_content:
            score = 5
        
        return {"factor_type": "作业类型", "input_value": work_content, "score": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算作业类型评分失败: {str(e)}")

@app.get("/api/risk/factor/time_period", summary="计算作业时段评分")
async def calculate_time_period(time_period: str = Query(description="作业时段")):
    """
    计算作业时段评分
    
    参数:
    - time_period: 作业时段
    
    评分规则:
    - 正常时段作业: 0分
    - 二级保供电期间涉及保供电设备的作业: 5分
    - 站内或室内夜间作业(0点-次日6:00): 20分
    - 特级、一级保供电涉及保供电设备的作业或春节等法定节假日: 30分
    - 站外线路夜间作业(20:00-次日6:00): 20分
    """
    try:
        score = risk_rules.calculate_work_time_period_score(time_period)
        return {"factor_type": "作业时段", "input_value": time_period, "score": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算作业时段评分失败: {str(e)}")

@app.get("/api/risk/factor/weather", summary="计算天气评分")
async def calculate_weather(weather: str = Query(description="天气状况")):
    """
    计算天气评分
    
    参数:
    - weather: 天气状况
    
    评分规则:
    - 天气舒适: 0分
    - 户外作业小雨天气: 10分
    - 气象部门发布天气预报信号后，户外作业受天气影响时: 10分
    - 雷雨、雷电、风力大于五级时(台风、大风预警信号)不具备作业条件: 0分(禁止作业)
    """
    try:
        score = risk_rules.calculate_weather_score(weather)
        return {"factor_type": "天气", "input_value": weather, "score": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算天气评分失败: {str(e)}")

@app.get("/api/risk/factor/mental_state", summary="计算精神状态评分")
async def calculate_mental_state(state: str = Query(description="精神状态")):
    """
    计算精神状态评分
    
    参数:
    - state: 精神状态
    
    评分规则:
    - 很差: 999分(禁止作业)
    - 较差: 10分
    - 一般: 2分
    - 良好: 0分
    """
    try:
        score = risk_rules.calculate_mental_state_score(state)
        return {"factor_type": "精神状态", "input_value": state, "score": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算精神状态评分失败: {str(e)}")

@app.get("/api/risk/factor/key_station", summary="计算关键重要站点(线路)评分")
async def calculate_key_station(key_status: str = Query(description="关键重要站点(线路)状态")):
    """
    计算关键重要站点(线路)评分
    
    参数:
    - key_status: 关键重要站点(线路)状态
    
    评分规则:
    - 非关键重要站点(线路): 0分
    - 关键重要站点(线路): 5分
    """
    try:
        score = risk_rules.calculate_key_station_line_score(key_status)
        return {"factor_type": "关键重要站点(线路)", "input_value": key_status, "score": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算关键重要站点评分失败: {str(e)}")

@app.get("/api/risk/factor/accident_consequence", summary="计算事故后果评分")
async def calculate_accident_consequence(consequence: str = Query(description="事故后果描述")):
    """
    计算事故后果评分
    
    参数:
    - consequence: 事故后果描述
    
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
        return {"factor_type": "事故后果", "input_value": consequence, "score": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算事故后果评分失败: {str(e)}")

@app.get("/api/risk/factor/equipment_risk", summary="计算设备风险评分")
async def calculate_equipment_risk(equipment_risk: str = Query(description="设备风险描述")):
    """
    计算设备风险评分
    
    参数:
    - equipment_risk: 设备风险描述
    
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
        return {"factor_type": "设备风险", "input_value": equipment_risk, "score": score}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算设备风险评分失败: {str(e)}")

@app.get("/api/health", summary="健康检查")
async def health_check():
    """
    健康检查接口
    """
    return {"status": "healthy", "service": "risk-assessment-api"}

if __name__ == "__main__":
    # 从配置文件读取 API 服务配置
    api_config = config_loader.get_api_config()
    host = api_config.get('host', '0.0.0.0')
    port = api_config.get('port', 8080)
    reload = api_config.get('reload', False)
    
    # 启动API服务
    # 使用导入字符串方式以支持reload功能
    uvicorn.run("api:app", host=host, port=port, reload=reload)