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
    wp.plan_start_time,     -- 计划开始时间
    wp.release_time,        -- 发布时间
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

# 单条违章查询 - 根据用户ID查询违章记录
SINGLE_PECCANCY_QUERY = """
SELECT 
    peccancy_uid,
    peccancy_code,
    COUNT(*) as count
FROM sp_ss_uq_peccancy_list_log 
WHERE peccancy_uid = %s
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

# 预计算结果表建表语句
CREATE_MACHINE_DAILY_RESULT_TABLE = """
CREATE TABLE IF NOT EXISTS machine_daily_result (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    calc_date DATE NOT NULL COMMENT '计算日期（作业日期）',
    ticket_id BIGINT NOT NULL COMMENT '工作票ID',
    ticket_no VARCHAR(64) NOT NULL COMMENT '工作票票号',
    work_plan_code VARCHAR(64) COMMENT '作业计划编号',
    work_task TEXT COMMENT '工作任务',

    b_total INT DEFAULT 0 COMMENT 'B类风险总分',
    safety_awareness_score INT DEFAULT 0 COMMENT '安全意识得分',
    personnel_nature_score INT DEFAULT 0 COMMENT '人员性质得分',
    same_type_work_score INT DEFAULT 0 COMMENT '同类型作业次数得分',
    work_count_score INT DEFAULT 0 COMMENT '作业人数得分',

    c_total INT DEFAULT 0 COMMENT 'C类风险总分',
    work_location_score INT DEFAULT 0 COMMENT '作业地段得分',
    work_type_score INT DEFAULT 0 COMMENT '作业类型得分',
    plan_nature_score INT DEFAULT 0 COMMENT '计划性质得分',

    d_total INT DEFAULT 0 COMMENT 'D类风险总分',

    f_total INT DEFAULT 0 COMMENT 'F类风险总分',

    llm_work_location_rule VARCHAR(128) COMMENT '大模型评估-作业地段命中规则',
    llm_work_location_keywords VARCHAR(256) COMMENT '大模型评估-作业地段关键词',
    llm_work_type_rule VARCHAR(128) COMMENT '大模型评估-作业类型命中规则',
    llm_work_type_keywords VARCHAR(256) COMMENT '大模型评估-作业类型关键词',

    work_principal_uid VARCHAR(64) COMMENT '工作负责人ID',
    work_member_uids TEXT COMMENT '工作班成员ID列表',
    guardian_uid VARCHAR(64) COMMENT '专责监护人ID',
    task_type VARCHAR(64) COMMENT '作业类型',

    status TINYINT DEFAULT 1 COMMENT '状态: 1=有效, 0=无效',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_calc_date_ticket (calc_date, ticket_id),
    INDEX idx_ticket_no (ticket_no),
    INDEX idx_work_plan_code (work_plan_code),
    INDEX idx_calc_date (calc_date),
    INDEX idx_work_principal_uid (work_principal_uid),
    INDEX idx_task_type (task_type),
    INDEX idx_f_total (f_total)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='机器风险计算结果表（每日预计算）'
"""

# 插入预计算结果（使用ON DUPLICATE KEY UPDATE实现upsert）
INSERT_MACHINE_DAILY_RESULT = """
INSERT INTO machine_daily_result (
    calc_date, ticket_id, ticket_no, work_plan_code, work_task,
    b_total, safety_awareness_score, personnel_nature_score, same_type_work_score, work_count_score,
    c_total, work_location_score, work_type_score, plan_nature_score,
    d_total, f_total,
    llm_work_location_rule, llm_work_location_keywords, llm_work_type_rule, llm_work_type_keywords,
    work_principal_uid, work_member_uids, guardian_uid, task_type, status
) VALUES (
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s,
    %s, %s,
    %s, %s, %s, %s,
    %s, %s, %s, %s, 1
) ON DUPLICATE KEY UPDATE
    work_plan_code = VALUES(work_plan_code),
    work_task = VALUES(work_task),
    b_total = VALUES(b_total),
    safety_awareness_score = VALUES(safety_awareness_score),
    personnel_nature_score = VALUES(personnel_nature_score),
    same_type_work_score = VALUES(same_type_work_score),
    work_count_score = VALUES(work_count_score),
    c_total = VALUES(c_total),
    work_location_score = VALUES(work_location_score),
    work_type_score = VALUES(work_type_score),
    plan_nature_score = VALUES(plan_nature_score),
    d_total = VALUES(d_total),
    f_total = VALUES(f_total),
    llm_work_location_rule = VALUES(llm_work_location_rule),
    llm_work_location_keywords = VALUES(llm_work_location_keywords),
    llm_work_type_rule = VALUES(llm_work_type_rule),
    llm_work_type_keywords = VALUES(llm_work_type_keywords),
    work_principal_uid = VALUES(work_principal_uid),
    work_member_uids = VALUES(work_member_uids),
    guardian_uid = VALUES(guardian_uid),
    task_type = VALUES(task_type),
    status = 1,
    updated_at = CURRENT_TIMESTAMP
"""

# 查询指定日期范围的预计算结果
QUERY_MACHINE_DAILY_RESULT = """
SELECT 
    calc_date, ticket_id, ticket_no, work_plan_code, work_task,
    b_total, safety_awareness_score, personnel_nature_score, same_type_work_score, work_count_score,
    c_total, work_location_score, work_type_score, plan_nature_score,
    d_total, f_total,
    llm_work_location_rule, llm_work_location_keywords, llm_work_type_rule, llm_work_type_keywords,
    work_principal_uid, work_member_uids, guardian_uid, task_type, status
FROM machine_daily_result
WHERE calc_date BETWEEN %s AND %s
  AND status = 1
ORDER BY calc_date DESC, ticket_id
"""

# 查询指定工作票号的预计算结果
QUERY_MACHINE_DAILY_RESULT_BY_TICKET_NO = """
SELECT 
    calc_date, ticket_id, ticket_no, work_plan_code, work_task,
    b_total, safety_awareness_score, personnel_nature_score, same_type_work_score, work_count_score,
    c_total, work_location_score, work_type_score, plan_nature_score,
    d_total, f_total,
    llm_work_location_rule, llm_work_location_keywords, llm_work_type_rule, llm_work_type_keywords,
    work_principal_uid, work_member_uids, guardian_uid, task_type, status
FROM machine_daily_result
WHERE ticket_no IN ({placeholders})
  AND status = 1
ORDER BY calc_date DESC
"""

# 查询预计算结果（用于与人月报比对）
QUERY_MACHINE_DAILY_RESULT_FOR_COMPARE = """
SELECT 
    mdr.ticket_no,
    mdr.work_plan_code,
    mdr.f_total AS machine_risk_score,
    mdr.b_total AS machine_b_score,
    mdr.c_total AS machine_c_score,
    mdr.d_total AS machine_d_score,
    mdr.work_location_score,
    mdr.work_type_score,
    mdr.plan_nature_score,
    mdr.llm_work_location_rule,
    mdr.llm_work_type_rule,
    mdr.calc_date
FROM machine_daily_result mdr
WHERE mdr.calc_date BETWEEN %s AND %s
  AND mdr.status = 1
"""

# 查询作业计划编号的基准关系（典型基准风险值）
BENCHMARK_RELATION_QUERY = """
SELECT 
    DISTINCT A.id,
    C.BENCHMARK_NAME,
    CAST(C.RISK_VALUE AS DECIMAL) AS RISK_VALUE
FROM sp_ss_rc_work_plan A
LEFT JOIN sp_ss_rc_benchmark_relation C 
    ON A.ID = C.WORK_PLAN_ID
WHERE A.WORK_CODE IN ({placeholders})
"""
