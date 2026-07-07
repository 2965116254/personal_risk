# -*- coding: utf-8 -*-
"""
定时任务调度器（重构版）
使用重构后的 RiskAssessor 类执行定时风险评估和预计算任务。
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import time
import traceback
from datetime import datetime

import config_loader
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

from risk_assessor import RiskAssessor
from main import run_risk_calculation, get_query_params
from night_shift_detector import run_night_shift_detection, NightShiftDetector


def job_listener(event):
    """任务执行监听器"""
    if event.exception:
        print(f"任务执行出错: {event.exception}")
        print(f"错误详情: {traceback.format_exc()}")
    else:
        print(f"任务执行成功: {event.job_id}")


def run_job_with_timeout():
    """执行风险评估任务（9:00/18:00）：重新执行评估（复用凌晨预计算的LLM缓存），导出Excel"""
    start_time = datetime.now()
    print(f"[{start_time.strftime('%Y-%m-%d %H:%M:%S')}] 开始执行任务...")
    try:
        run_risk_calculation()
        end_time = datetime.now()
        print(f"[{end_time.strftime('%Y-%m-%d %H:%M:%S')}] 任务执行完成，耗时: {end_time - start_time}")
    except Exception as e:
        end_time = datetime.now()
        print(f"[{end_time.strftime('%Y-%m-%d %H:%M:%S')}] 任务执行异常: {e}")
        traceback.print_exc()


def run_daily_precalculation():
    """执行日预计算任务：运行完整评估（含大模型），缓存LLM结果，不输出Excel"""
    start_time = datetime.now()
    print(f"[{start_time.strftime('%Y-%m-%d %H:%M:%S')}] 开始执行日预计算任务（含大模型评估）...")

    try:
        config = config_loader.get_config()
        db_config = config_loader.get_db_new_config()

        # 查询参数（复用共享函数）
        limit, query_start_date, query_end_date = get_query_params()

        print(f"查询参数: limit={limit}, 时间过滤: 查询时间区间 {query_start_date} ~ {query_end_date}（区间重叠判断）")

        # 执行完整评估（含大模型），DataCache 自动保存 LLM 结果到 processed_*.json
        assessor = RiskAssessor(db_config)
        results = assessor.assess(limit=limit, query_start_date=query_start_date, query_end_date=query_end_date)

        if not results:
            print("预计算未获取到数据")
            return

        print(f"预计算评估完成，共 {len(results)} 条工作计划编号，LLM结果已缓存")

        end_time = datetime.now()
        duration = end_time - start_time
        print(f"[{end_time.strftime('%Y-%m-%d %H:%M:%S')}] 日预计算任务完成，耗时: {duration}")
    except Exception as e:
        end_time = datetime.now()
        print(f"[{end_time.strftime('%Y-%m-%d %H:%M:%S')}] 日预计算任务执行异常: {e}")
        traceback.print_exc()


def main():
    """主函数，配置和启动定时任务"""
    print("初始化...")

    config = config_loader.get_config()
    schedule_config = config.get('schedule', {})
    precalc_config = config.get('daily_precalc', {})

    scheduler = BackgroundScheduler()
    scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

    # 配置定时任务
    times = schedule_config.get('times', [])
    if times:
        print(f"定时任务配置: {times}")
        for i, time_config in enumerate(times):
            hour = int(time_config.get('hour', 0))
            minute = int(time_config.get('minute', 0))
            scheduler.add_job(
                run_job_with_timeout,
                CronTrigger(hour=hour, minute=minute),
                id=f'risk_calculation_{i}',
                name=f'风险评估定时任务_{hour}:{minute:02d}',
                replace_existing=True,
                max_instances=1,
                misfire_grace_time=300,
            )
            print(f"添加定时任务: 每天 {hour}:{minute:02d} 执行")
    else:
        cron_expression = schedule_config.get('cron', "0 9,18 * * *")
        print(f"定时任务配置: {cron_expression}")
        scheduler.add_job(
            run_job_with_timeout,
            CronTrigger.from_crontab(cron_expression),
            id='risk_calculation',
            name='风险评估定时任务',
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=300,
        )

    # 配置预计算任务
    if precalc_config.get('enabled', True):
        precalc_hour = int(precalc_config.get('hour', 2))
        precalc_minute = int(precalc_config.get('minute', 0))
        scheduler.add_job(
            run_daily_precalculation,
            CronTrigger(hour=precalc_hour, minute=precalc_minute),
            id='daily_precalculation',
            name=f'日预计算任务_{precalc_hour}:{precalc_minute:02d}',
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
        print(f"添加日预计算定时任务: 每天 {precalc_hour}:{precalc_minute:02d} 执行")
    else:
        print("日预计算任务未启用")

    # ==================== 夜间作业检测任务 ====================
    night_shift_cfg = config.get('night_shift', {})
    if night_shift_cfg.get('enabled', True):
        # 厂站工作票夜间作业检测
        station_cfg = night_shift_cfg.get('station', {})
        if station_cfg.get('enabled', True):
            sh = int(station_cfg.get('hour', 0))
            sm = int(station_cfg.get('minute', 0))
            scheduler.add_job(
                run_night_shift_detection,
                CronTrigger(hour=sh, minute=sm),
                id='night_shift_station',
                name=f'夜间作业检测-厂站票_{sh:02d}:{sm:02d}',
                replace_existing=True,
                max_instances=1,
                misfire_grace_time=300,
            )
            print(f"添加夜间作业检测定时任务（厂站票）: 每天 {sh:02d}:{sm:02d} 执行")

        # 线路工作票夜间作业检测
        line_cfg = night_shift_cfg.get('line', {})
        if line_cfg.get('enabled', True):
            lh = int(line_cfg.get('hour', 20))
            lm = int(line_cfg.get('minute', 0))
            scheduler.add_job(
                run_night_shift_detection,
                CronTrigger(hour=lh, minute=lm),
                id='night_shift_line',
                name=f'夜间作业检测-线路票_{lh:02d}:{lm:02d}',
                replace_existing=True,
                max_instances=1,
                misfire_grace_time=300,
            )
            print(f"添加夜间作业检测定时任务（线路票）: 每天 {lh:02d}:{lm:02d} 执行")
    else:
        print("夜间作业检测任务未启用")

    scheduler.start()
    print("定时任务调度器已启动")
    print("按Ctrl+C退出...")

    try:
        while True:
            time.sleep(2)
    except KeyboardInterrupt:
        print("正在关闭调度器...")
        scheduler.shutdown()
        print("调度器已关闭")


if __name__ == "__main__":
    main()