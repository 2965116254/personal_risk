# -*- coding: utf-8 -*-
# @Project ：safety 
# @FileName: config_loader.py
# @Author  : greenaut
# @Time    : 2026/2/12 16:32

import os
import yaml

# 配置文件名
CONFIG_FILE_NAME = "config.yaml"

def get_config_path():
    """
    获取配置文件路径：
    1. 优先使用容器内标准配置目录 /app/config/config.yaml
    2. 若不存在，则使用脚本所在目录的 config/config.yaml
    3. 若不存在，则使用脚本所在目录的 config.yaml（用于本地开发或旧方式）
    """
    # 检查脚本所在目录下的config子目录（优先，因为现在配置文件在config目录中）
    local_config_dir_path = os.path.join(os.path.dirname(__file__), "config", CONFIG_FILE_NAME)
    if os.path.exists(local_config_dir_path):
        return local_config_dir_path

    # 容器内挂载的配置目录路径
    container_config_path = os.path.join("/app/config", CONFIG_FILE_NAME)
    if os.path.exists(container_config_path):
        return container_config_path

    # 回退到脚本所在目录
    local_config_path = os.path.join(os.path.dirname(__file__), CONFIG_FILE_NAME)
    if os.path.exists(local_config_path):
        return local_config_path

    # 如果都找不到，抛出异常（由上层处理）
    raise FileNotFoundError(f"配置文件不存在，尝试路径: {local_config_dir_path} 或 {container_config_path} 或 {local_config_path}")

def load_config():
    """加载 YAML 配置文件，返回字典"""
    config_path = get_config_path()
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return config

# 全局配置对象（单例加载）
_CONFIG = None

def get_config():
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = load_config()
    return _CONFIG

def get_db_config():
    """获取数据库配置字典"""
    return get_config()['database']

def get_db_new_config():
    """获取新数据库配置字典"""
    return get_config()['database_new']

def get_minio_config():
    """获取 MinIO 配置字典"""
    return get_config()['minio']

def get_schedule_interval():
    """获取定时任务间隔（秒），若无则返回0"""
    return get_config().get('schedule_interval', 0)

def get_schedule():
    """获取调度配置（cron 或 interval）"""
    return get_config().get('schedule', {})

def get_query_limit():
    """根据 test_mode 返回 limit 值，全量时返回 None"""
    cfg = get_config()
    if cfg.get('test_mode', False):
        return cfg.get('query_limit', 10)
    return None

def get_output_dir():
    """获取输出目录（注意：此函数可能不再使用，因为 connect.py 中已改为固定 ./excel_output）"""
    return get_config()['output_dir']

def get_current_year():
    """获取当前年份（动态计算）"""
    import datetime
    return datetime.date.today().year

def get_d_score_path():
    """获取 D_score.csv 路径（始终从脚本所在目录查找）"""
    base = os.path.dirname(__file__)
    return os.path.join(base, get_config().get('d_score_csv', 'D_score.csv'))

def get_fault_scene_path():
    """获取 fault_scene.csv 路径（始终从脚本所在目录查找）"""
    base = os.path.dirname(__file__)
    return os.path.join(base, get_config().get('fault_scene_csv', 'fault_scene.csv'))

def get_mcp_config():
    """获取 MCP 服务配置"""
    return get_config().get('mcp_server', {})


def get_api_config():
    """获取 API 服务配置"""
    return get_config().get('api_server', {})


def get_mcp_single_config():
    """获取 MCP 单条查询服务配置"""
    return get_config().get('mcp_single_server', {})


def get_elink_config():
    """获取 elink 配置字典"""
    return get_config().get('elink', {})


def get_elink_enabled():
    """获取 elink 是否启用"""
    return get_elink_config().get('enabled', False)


def get_elink_touser_id():
    """获取 elink 接收方用户ID"""
    return get_elink_config().get('touser_id', '')


def get_elink_type():
    """获取 elink 消息类型"""
    return get_elink_config().get('type', 1)


def get_query_time_range():
    """获取查询时间范围配置"""
    return get_config().get('query_time_range', {})


def get_query_time_range_enabled():
    """获取查询时间范围是否启用"""
    return get_config().get('query_time_range', {}).get('enabled', False)


def get_query_time_mode():
    """获取时间范围模式"""
    return get_config().get('query_time_range', {}).get('mode', 'fixed')


def get_query_year_enabled():
    """获取查询年份时间是否启用"""
    return get_config().get('query_year_enabled', False)


def get_query_year_start_date():
    """根据 query_year 配置获取查询开始日期"""
    cfg = get_config()
    if not cfg.get('query_year_enabled', False):
        return None
    year = cfg.get('query_year')
    month = cfg.get('query_start_month', 1)
    day = cfg.get('query_start_day', 1)
    return f"{year}-{int(month):02d}-{int(day):02d}"


def get_query_year_end_date():
    """根据 query_year 配置获取查询结束日期"""
    cfg = get_config()
    if not cfg.get('query_year_enabled', False):
        return None
    year = cfg.get('query_year')
    month = cfg.get('query_end_month', 12)
    day = cfg.get('query_end_day', 31)
    return f"{year}-{int(month):02d}-{int(day):02d}"


def get_start_date():
    """获取查询开始日期（支持动态计算）"""
    import datetime
    cfg = get_config().get('query_time_range', {})
    mode = cfg.get('mode', 'fixed')
    
    if mode == 'fixed':
        return cfg.get('start_date', None)
    elif mode == '1month':
        # 一个月前的日期（30天）
        return (datetime.date.today() - datetime.timedelta(days=30)).strftime('%Y-%m-%d')
    elif mode == '3month':
        # 三个月前的日期（90天）
        return (datetime.date.today() - datetime.timedelta(days=90)).strftime('%Y-%m-%d')
    elif mode == '6month':
        # 半年前的日期（180天）
        return (datetime.date.today() - datetime.timedelta(days=180)).strftime('%Y-%m-%d')
    elif mode == '1year':
        # 一年前的日期（365天）
        return (datetime.date.today() - datetime.timedelta(days=365)).strftime('%Y-%m-%d')
    elif mode == 'custom':
        return cfg.get('start_date', None)
    return None


def get_end_date():
    """获取查询结束日期（支持动态计算）"""
    import datetime
    cfg = get_config().get('query_time_range', {})
    mode = cfg.get('mode', 'fixed')
    
    if mode == 'fixed':
        return cfg.get('end_date', None)
    elif mode in ['1month', '3month', '6month', '1year']:
        # 默认使用当天日期
        return datetime.date.today().strftime('%Y-%m-%d')
    elif mode == 'custom':
        return cfg.get('end_date', None)
    return None


def get_filter_config():
    """获取过滤配置"""
    return get_config().get('filter', {})


def get_bracket_filter_words():
    """获取括号内容过滤词列表（用于清除人员ID中括号内的角色描述）"""
    return get_config().get('filter', {}).get('bracket_filter_words')


def get_holiday_check_enabled():
    """获取法定节假日判断是否启用"""
    return get_config().get('holiday_check_enabled', True)


def get_ai_config():
    """获取 AI 模型配置"""
    return get_config().get('ai', {})


def get_llm_config():
    """获取 LLM 大模型配置（与 TWXH_NEW 一致）"""
    return get_config().get('llm', {})


def get_llm_max_concurrent():
    """获取大模型最大并发调用数，默认50"""
    return get_config().get('llm', {}).get('max_concurrent', 50)


def get_violation_api_config():
    """获取违规待处理记录API配置"""
    return get_config().get('violation_api', {})


def get_retention_days():
    """
    获取预计算结果保留天数。
    优先使用配置中的 retention_days，如果未配置则根据 query_time_range.mode 动态计算。
    """
    import datetime
    cfg = get_config()

    retention_cfg = cfg.get('daily_precalc', {}).get('retention_days')
    if retention_cfg is not None:
        return retention_cfg

    query_cfg = cfg.get('query_time_range', {})
    mode = query_cfg.get('mode', 'fixed')

    mode_days_map = {
        '1month': 30,
        '3month': 90,
        '6month': 180,
        '1year': 365,
    }

    return mode_days_map.get(mode, 90)