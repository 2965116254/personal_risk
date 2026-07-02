-- 通过作业计划编号查询工作票成员信息
SELECT 
    wp.work_code,             -- 作业计划编号
    wb.ticket_no,             -- 工作票票号
    wb.ticket_source_id,      -- 作业计划表关联ID
    wp.work_content,          -- 工作内容
    wb.work_principal_uid,    -- 工作负责人ID
    wb.work_principal_uname,  -- 工作负责人姓名
    wb.work_member_uid,       -- 工作班人员ID
    wb.work_member_uname,     -- 工作班人员姓名
    wb.guardian_uid,          -- 专责监护人ID
    wb.guardian_uname,        -- 专责监护人姓名
    wb.work_member_count,     -- 工作班人员总数
    wp.bureau_code,           -- 局编码
    CASE wp.bureau_code
        WHEN '0101' THEN '广州局'
        WHEN '0102' THEN '贵阳局'
        WHEN '0103' THEN '南宁局'
        WHEN '0104' THEN '柳州局'
        WHEN '0105' THEN '梧州局'
        WHEN '0106' THEN '百色局'
        WHEN '0107' THEN '天生桥局'
        WHEN '0108' THEN '曲靖局'
        WHEN '0109' THEN '昆明局'
        WHEN '0110' THEN '大理局'
        WHEN '0120' THEN '电科院'
        WHEN '0112' THEN '海口分局'
        ELSE ''
    END AS `地市局`,
    CASE wp.task_main
        WHEN '1.0' THEN '本单位'
        WHEN '2.0' THEN '分包作业'
        ELSE ''
    END AS `作业主体`,
    wb.work_task              -- 工作任务
FROM sp_ss_rc_work_plan wp
LEFT JOIN (
    SELECT business_name, wticket_id
    FROM (
        SELECT business_name, wticket_id,
               ROW_NUMBER() OVER (PARTITION BY business_name ORDER BY update_time DESC) AS rn
        FROM sp_pd_wticket_business_re
    ) t
    WHERE rn = 1
) re ON wp.work_code = re.business_name
LEFT JOIN sp_pd_wticket_base wb ON re.wticket_id = wb.id
where wp.work_code = '作业计划编号'

-- 查询人员id查询违章记录

SELECT 
            peccancy_uid,
            peccancy_code,
            COUNT(*) as count
        FROM sp_ss_uq_peccancy_list_log 
        WHERE peccancy_uid IN  ('工作负责人ID','工作班人员ID','专责监护人ID')
AND record_date BETWEEN DATE_SUB(CURDATE(), INTERVAL 1 YEAR) AND CURDATE()
        GROUP BY peccancy_uid, peccancy_code  


-- 查询作业计划编号的工作票票号和动火票票号

select wp.work_code, 
       wbr.ticket_no AS '工作票票号',
       wf.ticket_no AS '动火票票号'
from sp_ss_rc_work_plan wp
left join sp_pd_wticket_business_re wbr on wp.work_code = wbr.business_name
left join sp_pd_wticket_fire wf on wbr.wticket_id = wf.wticket_id
where wp.work_code = '作业计划编号';


-- 查询作业计划编号的动态风险评估结果

SELECT 
    DISTINCT
    A.WORK_CODE as '作业计划编号',
    CASE B.DIMENSION_TYPE
        WHEN '1.00' THEN '作业人员能力'
        WHEN '2.00' THEN '作业环境和时间影响'
        WHEN '3.00' THEN '电网、设备风险'
        ELSE ''
    END AS '维度类型',
    B.ITEM_NAME AS '评估因子',
    B.ASSESS_RESULT AS '评估结果项',
    B.ASSESS_VALUE AS '评估结果项风险值得分',
    B.CONTROL_MEASURES as '控制措施',
    CASE B.CONTROL_MEASURES_TYPE
        WHEN '1.00' THEN '清除'
        WHEN '2.00' THEN '替代'
        WHEN '3.00' THEN '转移'
        WHEN '4.00' THEN '工程/隔离'
        WHEN '5.00' THEN '行政管理'
        WHEN '6.00' THEN '个人防护'
        ELSE ''
    END AS '控制措施类型'
FROM sp_ss_rc_work_plan A
LEFT JOIN sp_ss_rc_dynamic_risk_assess B 
    ON A.ID = B.WORK_PLAN_ID
WHERE A.WORK_CODE = '作业计划编号';


-- 查询作业计划编号的基准关系（a值）

SELECT 
    DISTINCT A.id,
    C.BENCHMARK_NAME,
    CAST(C.RISK_VALUE AS DECIMAL) AS RISK_VALUE
FROM sp_ss_rc_work_plan A
LEFT JOIN sp_ss_rc_benchmark_relation C 
    ON A.ID = C.WORK_PLAN_ID
WHERE A.WORK_CODE = '作业计划编号'


-- 更新查询时间
SELECT 
      wp.work_code,             -- 作业计划编号
      wb.ticket_no,             -- 工作票票号
      wb.ticket_source_id,      -- 作业计划表关联ID
      wb.work_principal_uid,    -- 工作负责人ID
      wb.work_principal_uname,  -- 工作负责人姓名
      wb.work_member_uid,       -- 工作班人员ID
      wb.work_member_uname,     -- 工作班人员姓名
      wb.guardian_uid,          -- 专责监护人ID
      wb.guardian_uname,        -- 专责监护人姓名
      wb.work_member_count,     -- 工作班人员总数
      CASE wp.task_main
          WHEN '1.0' THEN '本单位'
          WHEN '2.0' THEN '分包作业'
          ELSE ''
      END AS `作业主体`,
      wb.work_task              -- 工作任务
  FROM sp_ss_rc_work_plan wp
  LEFT JOIN (
      SELECT business_name, wticket_id
      FROM (
          SELECT business_name, wticket_id,
                 ROW_NUMBER() OVER (PARTITION BY business_name ORDER BY update_time DESC) AS rn
          FROM sp_pd_wticket_business_re
      ) t
      WHERE rn = 1
  ) re ON wp.work_code = re.business_name
  LEFT JOIN sp_pd_wticket_base wb ON re.wticket_id = wb.id
WHERE 1=1 and ( NOT(wp.plan_end_time <= '2026-05-01 00:00:00')
                                OR wp.plan_start_time >= '2026-05-31 23:59:59' )