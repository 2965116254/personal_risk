# -*- coding: utf-8 -*-
# @Project ：personal_risk_prevention_algo 
# @FileName: new_rule.py
# @Author  : 
# @Time    : 2026/4/21

import config_loader
import time
import traceback
from datetime import datetime

# 导入定时任务库
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

# 直接导入main模块的核心函数
from main import run_risk_calculation


def job_listener(event):
    """任务执行监听器"""
    if event.exception:
        print(f"任务执行出错: {event.exception}")
        print(f"错误详情: {traceback.format_exc()}")
    else:
        print(f"任务执行成功: {event.job_id}")


def run_job_with_timeout():
    """执行任务并记录执行时间"""
    start_time = datetime.now()
    print(f"[{start_time.strftime('%Y-%m-%d %H:%M:%S')}] 开始执行任务...")
    
    try:
        run_risk_calculation()
        end_time = datetime.now()
        duration = end_time - start_time
        print(f"[{end_time.strftime('%Y-%m-%d %H:%M:%S')}] 任务执行完成，耗时: {duration}")
    except Exception as e:
        end_time = datetime.now()
        print(f"[{end_time.strftime('%Y-%m-%d %H:%M:%S')}] 任务执行异常: {e}")
        traceback.print_exc()


def main():
    """主函数，配置和启动定时任务"""
    print("初始化...")
    
    # 获取配置
    config = config_loader.get_config()
    schedule_config = config.get('schedule', {})
    
    # 检查是否有schedule配置
    if schedule_config:
        # 有定时任务配置，启动调度器
        print("初始化定时任务调度器...")
        
        # 创建后台调度器
        scheduler = BackgroundScheduler()
        
        # 添加任务监听器
        scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
        
        # 检查是否使用新的times配置格式
        times = schedule_config.get('times', [])
        if times:
            # 使用新的times配置格式
            print(f"定时任务配置: {times}")
            print("定时任务已配置")
            
            # 为每个时间点添加定时任务
            for i, time_config in enumerate(times):
                # 将配置值转换为整数
                hour = int(time_config.get('hour', 0))
                minute = int(time_config.get('minute', 0))
                
                # 添加定时任务
                scheduler.add_job(
                    run_job_with_timeout,
                    CronTrigger(hour=hour, minute=minute),
                    id=f'risk_calculation_{i}',
                    name=f'风险评估定时任务_{hour}:{minute:02d}',
                    replace_existing=True,
                    max_instances=1,  # 确保同一时间只有一个实例在运行
                    misfire_grace_time=300  # 允许5分钟的容错时间
                )
                print(f"添加定时任务: 每天 {hour}:{minute:02d} 执行")
        else:
            # 使用旧的cron表达式格式
            cron_expression = schedule_config.get('cron', "0 9,18 * * *")
            
            print(f"定时任务配置: {cron_expression}")
            print("定时任务已配置")
            
            # 添加定时任务
            scheduler.add_job(
                run_job_with_timeout,
                CronTrigger.from_crontab(cron_expression),
                id='risk_calculation',
                name='风险评估定时任务',
                replace_existing=True,
                max_instances=1,
                misfire_grace_time=300
            )
        
        # 启动调度器
        scheduler.start()
        print("定时任务调度器已启动")
        print("按Ctrl+C退出...")
        
        # 保持程序运行
        try:
            while True:
                time.sleep(2)
        except KeyboardInterrupt:
            print("正在关闭调度器...")
            scheduler.shutdown()
            print("调度器已关闭")
    else:
        # 没有定时任务配置，直接执行一次
        print("没有定时任务配置，直接执行风险评估...")
        run_job_with_timeout()
        print("风险评估完成")


if __name__ == "__main__":
    main()
