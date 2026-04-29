# -*- coding: utf-8 -*-
# @Project ：personal_risk_prevention_algo 
# @FileName: risk_rules.py
# @Author  : 
# @Time    : 2026/4/22

# 安全意识评分映射表
AWARENESS_MAP = {
    '1年内累计1次及以上A类违章': 6,
    '1年内累计1次及以上B类违章': 5,
    '1年内累计1次及以上C类违章': 3,
    '1年内累计3次及以上D类违章': 2,
    '1年内0-2次D类违章': 0
}

# 作业人员临时变更评分映射表
TEMPORARY_CHANGE_MAP = {
    '不超过5人': 0,
    '作业当日临时变更工作负责人': 5,
    '工作负责人在作业前(含工作间断后)1日确认': 0
}

# 人员性质评分映射表
PERSONNEL_NATURE_MAP = {
    '外施工单位劳务分包人员': 8,
    '外施工单位人员': 5,
    '本单位人员': 0
}

# 作业经验评分映射表
EXPERIENCE_MAP = {
    '第一次承担该类作业': 6,
    '累计不足3次但不是第一次': 5,
    '累计不足5次但不小于3次': 3,
    '不满足上述要求，但累计5次及以上': 2,
    '1年内2次及以上或2年内5次及以上': 0
}

# 精神状态评分映射表
MENTAL_STATE_MAP = {
    '很差': 999,
    '较差': 10,
    '一般': 2,
    '良好': 0
}

# 天气评分映射表
WEATHER_MAP = {
    '天气舒适': 0,
    '户外作业小雨天气': 10,
    '气象部门发布天气预报信号后，户外作业受天气影响时': 10,
    '雷雨、雷电、风力大于五级时(台风、大风预警信号)不具备': 0
}

# 作业地段评分映射表
WORK_LOCATION_MAP = {
    '无特殊地段': 0,
    '有限空间内作业:风、水、电和空气监测设施完备、信号传': 3,
    '有限空间内作业:风、水、电和空气监测设施不完备、信号传': 10,
    '有限空间环境当氧气不足或有毒有害气体含量超标时，禁止': 999,
    '作业区段内包含(双)多回共塔带电线路': 10,
    '林区内作业': 15,
    '地质隐患区内作业': 15,
    '可能造成导、地线、光缆脱落的作业，区段内包含重要交叉': 30
}

# 作业类型评分映射表
WORK_TYPE_MAP = {
    '地面以上1.5米以下': 0,
    '1.5米以上5米以下': 2,
    '5米以上15米以下': 5,
    '15米以上30米以下': 7,
    '30米以上': 10,
    '动火作业': 5,
    '大型吊装作业': 5
}

# 作业时段评分映射表
WORK_TIME_PERIOD_MAP = {
    '正常时段作业': 0,
    '二级保供电期间涉及保供电设备的作业': 5,
    '站内或室内夜间作业(0点-次日6:00)': 20,
    '特级、一级保供电涉及保供电设备的作业、或春节等法定假': 30,
    '站外线路夜间作业(20:00-次日6:00)': 20
}

# 计划性质评分映射表
PLAN_NATURE_MAP = {
    '计划性作业': 0,
    '提前一日制定的临时性作业任务': 10,
    '当日制定的临时性作业任务': 20
}

# 关键重要站点(线路)评分映射表
KEY_STATION_LINE_MAP = {
    '非关键重要站点(线路)': 0,
    '关键重要站点(线路)': 5
}

# 事故后果评分映射表
ACCIDENT_CONSEQUENCE_MAP = {
    '无事故事件': 0,
    '造成电力安全四级及以下事件(相关风险': 0,
    '造成电力安全三级事件': 10,
    '造成电力安全二级事件': 40,
    '造成电力安全一级事件': 160,
    '造成一般电力安全事故': 180,
    '造成较大及以上电力安全事故或县域及以上大面积停电': 200
}

# 设备风险评分映射表
EQUIPMENT_RISK_MAP = {
    '无设备风险影响作业典型场景': 0,
    '对《设备风险预警通知单》揭示的隐患设备开展作业，相关': 0,
    '在运行回路上使用万用表、螺丝刀等工器具开展作业，工器': 0,
    '开展保护装置、安自装置、操作箱及智能终端定检/维护/消': 45,
    '开展带电水冲洗作业': 140,
    '开展保护装置、安自装置、测控装置、操作箱及智能终端兑': 0,
    '开展双母线热倒母操作，操作涉及的母线侧刀闸存在超期未': 90,
    '手动操作隔离开关，操作涉及的隔离开关为单轴、单电机三': 70,
    '开展电气操作，操作涉及的设备在监控后台无法正确显示设': 70,
    '开展电气操作，操作涉及的设备存在微机五防、机械防误、': 70
}

# 单位属性映射表
UNIT_ATTRIBUTE_MAP = {
    '1': {'desc': '系统内', 'score': 0},        # 本单位人员
    '2': {'desc': '系统外', 'score': 5},        # 外施工单位人员
    '21': {'desc': '多经企业', 'score': 8},     # 外施工单位劳务分包人员
    'default': {'desc': '未知', 'score': 5}     # 默认外施工单位人员
}

# 同类型作业次数评分规则
def get_same_type_score(count):
    # if count == 1:
    #     return 6  # 第一次承担该类作业
    # elif count < 3:
    #     return 5  # 累计不足3次但不是第一次
    # elif count < 5:
    #     return 3  # 累计不足5次但不小于3次
    # else:
    #     return 2  # 累计5次及以上
    
    # 现在默认0分
    if count == 0:
        return 0  # 默认分数为0分
    elif count == 1:
        return 6  # 第一次承担该类作业
    elif count < 3:
        return 5  # 累计不足3次但不是第一次

# 作业总人数评分规则
def get_work_count_score(count):
    if not count:
        return 0
    
    # 尝试将count转换为整数
    try:
        count = int(count)
    except (ValueError, TypeError):
        return 0
    
    if count >= 50:
        return 15
    elif 24 <= count < 50:
        return 8
    elif 16 <= count < 24:
        return 5
    elif 8 <= count < 16:
        return 3
    elif 5 <= count < 8:
        return 1
    else:
        return 0

# 单日持续作业时长评分规则
def get_single_day_work_hours_score(hours):
    if not hours:
        return 0
    
    if hours <= 4:
        return 0
    elif 4 < hours <= 8:
        return 2
    elif 8 < hours <= 12:
        return 10
    else:
        return 20

# 安全意识评分
def calculate_safety_awareness_score(awareness_level):
    """计算安全意识评分"""
    if not awareness_level:
        return 0
    
    return AWARENESS_MAP.get(awareness_level, 0)

# 根据人员违章记录计算安全意识评分
def calculate_person_safety_awareness_score(peccancy_records):
    """根据人员违章记录计算安全意识评分"""
    if not peccancy_records:
        return 0
    
    score = 0
    
    # 检查是否有A类违章
    if 'A' in peccancy_records:
        score += 6
    # 检查是否有B类违章
    elif 'B' in peccancy_records:
        score += 5
    # 检查是否有C类违章
    elif 'C' in peccancy_records:
        score += 3
    # 检查是否有D类违章
    elif 'D' in peccancy_records:
        d_count = peccancy_records['D']
        if d_count >= 3:
            score += 2
        else:
            score += 0
    
    return score

# 作业总人数评分
def calculate_work_total_count_score(count):
    """计算作业总人数评分"""
    return get_work_count_score(count)

# 作业人员临时变更评分
def calculate_temporary_change_score(change_status):
    """计算作业人员临时变更评分"""
    if not change_status:
        return 0
    
    return TEMPORARY_CHANGE_MAP.get(change_status, 0)

# 人员性质评分
def calculate_personnel_nature_score(nature):
    """计算人员性质评分"""
    if not nature:
        return 0
    
    return PERSONNEL_NATURE_MAP.get(nature, 0)

# 作业经验评分
def calculate_experience_score(experience):
    """计算作业经验评分"""
    if not experience:
        return 0
    
    return EXPERIENCE_MAP.get(experience, 0)

# 精神状态评分
def calculate_mental_state_score(state):
    """计算精神状态评分"""
    if not state:
        return 0
    
    return MENTAL_STATE_MAP.get(state, 0)

# 天气评分
def calculate_weather_score(weather):
    """计算天气评分"""
    if not weather:
        return 0
    
    return WEATHER_MAP.get(weather, 0)

# 作业地段评分
def calculate_work_location_score(location):
    """计算作业地段评分"""
    if not location:
        return 0
    
    return WORK_LOCATION_MAP.get(location, 0)

# 作业类型评分
def calculate_work_type_score(work_type):
    """计算作业类型评分"""
    if not work_type:
        return 0
    
    return WORK_TYPE_MAP.get(work_type, 0)

# 作业时段评分
def calculate_work_time_period_score(time_period):
    """计算作业时段评分"""
    if not time_period:
        return 0
    
    return WORK_TIME_PERIOD_MAP.get(time_period, 0)

# 单日持续作业时长评分
def calculate_single_day_work_hours_score(hours):
    """计算单日持续作业时长评分"""
    return get_single_day_work_hours_score(hours)

# 计划性质评分
def calculate_plan_nature_score(plan_nature):
    """计算计划性质评分"""
    if not plan_nature:
        return 0
    
    return PLAN_NATURE_MAP.get(plan_nature, 0)

# 关键重要站点(线路)评分
def calculate_key_station_line_score(key_status):
    """计算关键重要站点(线路)评分"""
    if not key_status:
        return 0
    
    return KEY_STATION_LINE_MAP.get(key_status, 0)

# 事故后果评分
def calculate_accident_consequence_score(consequence):
    """计算事故后果评分"""
    if not consequence:
        return 0
    
    return ACCIDENT_CONSEQUENCE_MAP.get(consequence, 0)

# 设备风险评分
def calculate_equipment_risk_score(equipment_risk):
    """计算设备风险评分"""
    if not equipment_risk:
        return 0
    
    return EQUIPMENT_RISK_MAP.get(equipment_risk, 0)
