# -*- coding: utf-8 -*-
# @Project ：personal_risk_prevention_algo 
# @FileName: sql_queries.py
# @Author  : 
# @Time    : 2026/4/22

# 操作票表查询（关联作业计划表）
WORK_TICKET_QUERY = """
SELECT 
    wb.id,                  -- 主键ID
    wb.ticket_no,           -- 工作票票号
    wb.ticket_source_id,    -- 作业计划表关联ID
    wb.work_principal_uid,  -- 工作负责人ID
    wb.work_member_uid,     -- 工作班人员ID
    wb.guardian_uid,        -- 专责监护人ID
    wb.work_member_count,   -- 工作班人员总数
    wp.task_main,           -- 作业主体
    wp.work_code,           -- 作业计划编号
    wp.task_type,           -- 作业类型
    wb.work_task            -- 工作任务
FROM sp_pd_wticket_base wb
JOIN sp_ss_rc_work_plan wp ON wb.ticket_source_id = wp.id
"""

# 操作票表查询（带时间范围过滤）
WORK_TICKET_QUERY_WITH_TIME = """
SELECT 
    wb.id,                  -- 主键ID
    wb.ticket_no,           -- 工作票票号
    wb.ticket_source_id,    -- 作业计划表关联ID
    wb.work_principal_uid,  -- 工作负责人ID
    wb.work_member_uid,     -- 工作班人员ID
    wb.guardian_uid,        -- 专责监护人ID
    wb.work_member_count,   -- 工作班人员总数
    wp.task_main,           -- 作业主体
    wp.work_code,           -- 作业计划编号
    wp.task_type,           -- 作业类型
    wb.work_task            -- 工作任务
FROM sp_pd_wticket_base wb
JOIN sp_ss_rc_work_plan wp ON wb.ticket_source_id = wp.id
WHERE wp.create_time >= %s AND wp.create_time <= %s
"""

# 违章记录查询（使用时间范围过滤）
PECCANCY_QUERY = """
SELECT 
    peccancy_uid,
    peccancy_code,
    COUNT(*) as count
FROM sp_ss_uq_peccancy_list_log 
WHERE peccancy_uid IN ({placeholders})
AND record_date BETWEEN DATE_SUB(CURDATE(), INTERVAL 1 YEAR) AND CURDATE()
GROUP BY peccancy_uid, peccancy_code
"""

# 作业计划表查询 - 获取作业主体和作业计划编号
WORK_PLAN_QUERY = """
SELECT task_main, work_code FROM sp_ss_rc_work_plan WHERE id = %s ORDER BY release_time DESC
"""

# 作业计划表查询 - 获取作业类型
TASK_TYPE_QUERY = """
SELECT task_type FROM sp_ss_rc_work_plan WHERE id = %s
"""

# 作业计划表查询 - 获取工作地点、专业二级分类、工作内容
WORK_DETAIL_QUERY = """
SELECT work_place, major_sub_type, work_content FROM sp_ss_rc_work_plan WHERE id = %s
"""

# 作业计划表查询 - 获取计划性质
PLAN_NATURE_QUERY = """
SELECT plan_nature FROM sp_ss_rc_work_plan WHERE id = %s
"""

# 同类型作业次数查询 - 工作负责人（包含最近1年和2年的统计）
SAME_TYPE_PRINCIPAL_QUERY = """
WITH task_stats AS (
    SELECT
        work_master_uid AS leader_uid,
        work_master_uname AS leader_name,
        task_type,
        COUNT(1) AS total_count,
        SUM(CASE WHEN create_time >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR) THEN 1 ELSE 0 END) AS cnt_last_1year,
        SUM(CASE WHEN create_time >= DATE_SUB(CURDATE(), INTERVAL 2 YEAR) THEN 1 ELSE 0 END) AS cnt_last_2year
    FROM sp_ss_rc_work_plan
    WHERE work_master_uid IS NOT NULL
      AND task_type IS NOT NULL
    GROUP BY work_master_uid, work_master_uname, task_type
)
SELECT
    leader_uid,
    leader_name,
    task_type,
    total_count AS same_type_work_count,
    CASE
        WHEN cnt_last_1year >= 2 OR cnt_last_2year >= 5 THEN 0
        WHEN total_count = 1 THEN 6
        WHEN total_count < 3 THEN 5
        WHEN total_count BETWEEN 3 AND 4 THEN 3
        WHEN total_count >= 5 THEN 2
        ELSE NULL
    END AS risk_score
FROM task_stats
WHERE leader_uid = %s AND task_type = %s
"""

# 同类型作业次数查询 - 工作班成员
SAME_TYPE_MEMBER_QUERY = """
SELECT COUNT(*) as count 
FROM sp_ss_rc_work_plan p
WHERE p.work_master_uid = %s AND p.task_type = %s
"""

# 同类型作业次数查询 - 监护人（包含最近1年和2年的统计）
SAME_TYPE_GUARDIAN_QUERY = """
SELECT
    COUNT(*) AS total_count,
    SUM(CASE WHEN create_time >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR) THEN 1 ELSE 0 END) AS cnt_last_1year,
    SUM(CASE WHEN create_time >= DATE_SUB(CURDATE(), INTERVAL 2 YEAR) THEN 1 ELSE 0 END) AS cnt_last_2year
FROM sp_ss_rc_work_plan
WHERE work_master_uid = %s AND task_type = %s
"""

# 计划性质查询（包含类型转换）
PLAN_TYPE_QUERY = """
SELECT
    id,
    plan_type,
    CASE CAST(plan_type AS SIGNED)
        WHEN 1 THEN '计划性工作'
        WHEN 2 THEN '临时性工作'
        ELSE '未知'
    END AS work_nature
FROM sp_ss_rc_work_plan
WHERE id = %s
"""

# 作业计划表查询 - 获取作业主体、作业计划编号和作业类型
WORK_PLAN_FULL_QUERY = """
SELECT task_main, work_code, task_type FROM sp_ss_rc_work_plan WHERE id = %s
"""

# 作业计划表查询 - 获取工作地点、专业二级分类、工作内容和计划类型
WORK_DETAIL_FULL_QUERY = """
SELECT work_place, major_sub_type, work_content, plan_type FROM sp_ss_rc_work_plan WHERE id = %s
"""

# 工作班成员ID拆分查询
SPLIT_MEMBERS_QUERY = """
WITH RECURSIVE split_members AS (
    SELECT 
        id,
        SUBSTRING_INDEX(work_member_uid, ',', 1) AS member_uid,
        SUBSTRING(work_member_uid, LENGTH(SUBSTRING_INDEX(work_member_uid, ',', 1)) + 2) AS remaining
    FROM sp_pd_wticket_base
    WHERE id = %s AND work_member_uid IS NOT NULL AND work_member_uid != ''
    UNION ALL
    SELECT 
        id,
        SUBSTRING_INDEX(remaining, ',', 1),
        SUBSTRING(remaining, LENGTH(SUBSTRING_INDEX(remaining, ',', 1)) + 2)
    FROM split_members
    WHERE remaining != ''
)
SELECT member_uid FROM split_members
"""

# 监护人ID拆分查询
SPLIT_GUARDIANS_QUERY = """
WITH RECURSIVE split_guardians AS (
    SELECT 
        id,
        SUBSTRING_INDEX(guardian_uid, ',', 1) AS guardian_id,
        SUBSTRING(guardian_uid, LENGTH(SUBSTRING_INDEX(guardian_uid, ',', 1)) + 2) AS remaining
    FROM sp_pd_wticket_base
    WHERE id = %s AND guardian_uid IS NOT NULL AND guardian_uid != ''
    UNION ALL
    SELECT 
        id,
        SUBSTRING_INDEX(remaining, ',', 1),
        SUBSTRING(remaining, LENGTH(SUBSTRING_INDEX(remaining, ',', 1)) + 2)
    FROM split_guardians
    WHERE remaining != ''
)
SELECT guardian_id FROM split_guardians
"""

# 单位属性查询
UNIT_ATTRIBUTE_QUERY = """
SELECT unit_attribute FROM sp_ss_uq_operator_archive WHERE user_uid = %s
"""

# 批量同类型作业次数查询（支持多个人员ID）
BATCH_SAME_TYPE_QUERY = """
WITH task_stats AS (
    SELECT
        work_master_uid AS leader_uid,
        task_type,
        COUNT(1) AS total_count,
        SUM(CASE WHEN create_time >= DATE_SUB(CURDATE(), INTERVAL 1 YEAR) THEN 1 ELSE 0 END) AS cnt_last_1year,
        SUM(CASE WHEN create_time >= DATE_SUB(CURDATE(), INTERVAL 2 YEAR) THEN 1 ELSE 0 END) AS cnt_last_2year
    FROM sp_ss_rc_work_plan
    WHERE work_master_uid IN ({placeholders})
      AND work_master_uid IS NOT NULL
      AND task_type IS NOT NULL
    GROUP BY work_master_uid, task_type
)
SELECT
    leader_uid,
    task_type,
    total_count AS same_type_work_count,
    CASE
        WHEN cnt_last_1year >= 2 OR cnt_last_2year >= 5 THEN 0
        WHEN total_count = 1 THEN 6
        WHEN total_count < 3 THEN 5
        WHEN total_count BETWEEN 3 AND 4 THEN 3
        WHEN total_count >= 5 THEN 2
        ELSE 0
    END AS risk_score
FROM task_stats
"""
