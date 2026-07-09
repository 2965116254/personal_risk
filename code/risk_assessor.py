# -*- coding: utf-8 -*-
"""
风险评估核心编排层
使用 DataFetcher 获取数据，使用 RiskRuleEngine 计算规则得分，
使用 ai_client 调用大模型，最终生成结构化评估结果。
"""

import os
import sys
import time
import logging
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncio
import aiohttp
from asyncio import Semaphore
from typing import List, Dict, Optional, Tuple, Set

from data_fetcher import DataFetcher
from risk_rule_engine import RiskRuleEngine
from data_cache import DataCache
from config_loader import get_llm_max_concurrent


class RiskAssessor:
    """风险评估核心编排类"""

    # 局编码与地市局映射
    BUREAU_MAP = {
        '0101': '广州局',
        '0102': '贵阳局',
        '0103': '南宁局',
        '0104': '柳州局',
        '0105': '梧州局',
        '0106': '百色局',
        '0107': '天生桥局',
        '0108': '曲靖局',
        '0109': '昆明局',
        '0110': '大理局',
        '0120': '电科院',
        '0112': '海口分局',
    }

    def __init__(self, db_config: Dict):
        self.db_config = db_config
        self.fetcher = DataFetcher(db_config)
        self.engine = RiskRuleEngine()
        self._user_name_map: Dict[str, str] = {}

    # ==================== 主评估流程 ====================

    def assess(self, limit: int = None, query_start_date: str = None, query_end_date: str = None,
               use_cache: bool = True, work_codes: List[str] = None,
               incremental_output: bool = False,
               night_shift_work_codes: Set[str] = None,
               night_shift_detection_desc: str = '',
               night_shift_details: Dict = None) -> List[Dict]:
        """执行风险评估主流程，返回评估结果列表
        :param work_codes: 若指定，则按作业计划编号列表查询，忽略 limit/query_start_date/query_end_date
        :param incremental_output: 是否只返回增量数据（跳过缓存中已存在的工作票），用于 Excel 增量输出
        :param night_shift_work_codes: 夜间作业 work_code 集合，其中包含的票的C3（作业时段）将被强制判定为夜间作业
        :param night_shift_detection_desc: 夜间作业检测时间描述，如 "线路检测: 2026-07-08 20:05:00, 厂站检测: 2026-07-09 00:02:00"
        :param night_shift_details: 夜间作业详细检测信息 {work_code: {ticket_type, last_gap_time, last_gap_start_time, detected_at, ...}}
        """
        self.fetcher.connect()
        cache = DataCache()
        try:
            # ==================== 1. 两阶段查询优化 ====================
            # 增量模式 + 启用缓存 → 先轻量查 work_code 列表，对比缓存后只查新增的完整数据
            if work_codes:
                # 指定 work_codes：直接查完整数据
                work_tickets = self.fetcher.fetch_work_tickets_by_codes(work_codes)
            elif use_cache and incremental_output:
                # 阶段1: 轻量查询 work_code 列表（仅1列，不关联工作票表）
                all_work_codes = self.fetcher.fetch_work_codes(query_start_date, query_end_date)
                if not all_work_codes:
                    print("没有找到任何工作计划编号")
                    return []
                print(f"查询到 {len(all_work_codes)} 条工作计划编号")

                # 加载缓存中的 work_code 集合（只读key，轻量）
                cached_codes = cache.get_all_cached_work_codes()
                # 找出新增的 work_code
                new_codes = [wc for wc in all_work_codes if wc not in cached_codes]

                # 夜间作业：即使已缓存，C3分值已变动，需要重新拉取处理
                ns_codes = night_shift_work_codes or set()
                ns_reprocess = [wc for wc in all_work_codes if wc in cached_codes and wc in ns_codes]
                if ns_reprocess:
                    print(f"夜间作业重新拉取: {len(ns_reprocess)} 条（已缓存但C3分值变动）")
                    new_codes.extend(ns_reprocess)

                if not new_codes:
                    print(f"所有 {len(all_work_codes)} 条均已缓存（增量模式），跳过处理")
                    return []

                print(f"缓存命中 {len(all_work_codes) - len(new_codes)} 条，新增 {len(new_codes)} 条（含夜间作业重新拉取 {len(ns_reprocess)} 条）")
                # 阶段2: 只查新增的完整数据
                work_tickets = self.fetcher.fetch_work_tickets_by_codes(new_codes)
            else:
                # 非增量模式：全量查询（预计算等场景）
                work_tickets = self.fetcher.fetch_work_tickets(limit, query_start_date, query_end_date)

            if not work_tickets:
                print("没有找到任何工作计划编号")
                return []

            print(f"获取到 {len(work_tickets)} 条工作计划编号")

            # 2. 增量对比：找出需要大模型评估的新票
            # 注意：增量模式下 work_tickets 已全是新增，find_new_tickets 会全部返回为新增
            new_tickets = work_tickets
            cached_llm = {}  # {work_code: {llm_result, llm_location}}
            if use_cache:
                new_tickets, cached_llm = cache.find_new_tickets(work_tickets)
                skip_work_codes = set(cached_llm.keys())
            else:
                skip_work_codes = set()

            # 3. 收集所有人员ID
            all_user_ids = self._collect_user_ids(work_tickets)

            # 4. 查询违章记录
            peccancy_dict = self.fetcher.fetch_peccancy_records(all_user_ids)

            # 4.1 查询用户ID对应的姓名映射（用于Excel中ID→姓名转换）
            self._user_name_map = self.fetcher.fetch_user_name_map(all_user_ids)

            # 5. 加载人员ID类型缓存（全量加载，user_id_types 体积小无需过滤）
            user_id_type_cache = cache.load_all_user_id_types() if use_cache else {}
            user_ids, user_names, need_llm_classify, cache_hit_count = self._fast_classify_user_ids(
                all_user_ids, peccancy_dict, user_id_type_cache=user_id_type_cache
            )
            print(f"快速过滤完成，{len(need_llm_classify)} 项需要大模型判断（缓存命中 {cache_hit_count} 项）")

            # 6. 查询动火作业票
            work_codes = {t.get('work_code') for t in work_tickets if t.get('work_code')}
            hot_work_dict = self.fetcher.fetch_hot_work_tickets(list(work_codes))

            # 7. 合并并发：人员分类 + 工作票评估（共享同一个事件循环和信号量）
            # 优化：无新票 + 所有人员ID已缓存 → 跳过LLM调用，直接用缓存结果
            can_skip_llm = (use_cache
                            and len(new_tickets) == 0
                            and len(need_llm_classify) == 0
                            and len(cached_llm) > 0)
            if can_skip_llm:
                print(f"所有 {len(work_tickets)} 条工作票和人员ID均已缓存，跳过LLM调用")
                llm_results, loc_results = {}, {}
                classify_results = {}
                new_user_id_types = {}
            else:
                llm_results, loc_results, classify_results = self._run_llm_evaluations(
                    work_tickets, skip_work_codes=skip_work_codes,
                    classify_items=need_llm_classify
                )

                # 7.1 完成人员分类
                new_user_id_types = {}
                if classify_results:
                    for item, is_name in classify_results.items():
                        new_user_id_types[item] = is_name
                        if is_name:
                            user_names.append(item)
                        else:
                            user_ids.append(item)
                print(f"分类结果：数字ID {len(user_ids)} 个，中文名字 {len(user_names)} 个"
                      f"（本次新增 {len(new_user_id_types)} 项）")

            # 8. 合并缓存的大模型结果
            if cached_llm:
                self._merge_cached_llm_results(llm_results, loc_results,
                                               cached_llm, work_tickets)

            # 9. 批量查询作业计划详情
            t0 = time.time()
            work_plan_details = self.fetcher.fetch_work_plan_details(list(work_codes))
            print(f"[耗时] 查询作业计划详情: {time.time() - t0:.1f}s, 获取 {len(work_plan_details)} 条")

            # 10. 批量查询客户填入的动态风险分值
            t0 = time.time()
            dynamic_risk_dict = self.fetcher.fetch_dynamic_risk_scores(list(work_codes))
            print(f"[耗时] 查询动态风险分值: {time.time() - t0:.1f}s, 获取 {len(dynamic_risk_dict)} 条")

            # 10.1 批量查询电网、设备风险维度（DIMENSION_TYPE = '3.00'）的人工评估分值
            t0 = time.time()
            dynamic_risk_d_dict = self.fetcher.fetch_dynamic_risk_scores_d(list(work_codes))
            print(f"[耗时] 查询电网设备风险分值: {time.time() - t0:.1f}s, 获取 {len(dynamic_risk_d_dict)} 条")

            # 11. 批量查询基准关系
            t0 = time.time()
            benchmark_dict = self.fetcher.fetch_benchmark_relations(list(work_codes), work_plan_details)
            print(f"[耗时] 查询基准关系: {time.time() - t0:.1f}s, 获取 {len(benchmark_dict)} 条")

            # 11.1 批量查询班组成员变更记录
            t0 = time.time()
            change_member_dict = self.fetcher.fetch_change_members(list(work_codes))
            if change_member_dict:
                print(f"[耗时] 查询变更记录: {time.time() - t0:.1f}s, "
                      f"{sum(len(v) for v in change_member_dict.values())} 条变更记录")
            else:
                print(f"[耗时] 查询变更记录: {time.time() - t0:.1f}s, 无变更记录")

            # 11.2 大模型解析变更内容 + 查询新增人员的违章记录
            change_info = {}  # {work_code: {added_names, removed_names, added_peccancy, member_adjustment}}
            if change_member_dict:
                change_info = self._process_change_members(
                    change_member_dict, peccancy_dict,
                )

            # 12. 逐张计算风险值
            t0 = time.time()
            results = []
            # 夜间作业 work_code 集合
            night_shift_codes = night_shift_work_codes or set()
            for idx, ticket in enumerate(work_tickets):
                result = self._calc_single_ticket(
                    ticket, idx, peccancy_dict, hot_work_dict,
                    llm_results, loc_results,
                    work_plan_details, dynamic_risk_dict, dynamic_risk_d_dict, benchmark_dict,
                    change_member_dict=change_member_dict,
                    change_info=change_info,
                    night_shift_work_codes=night_shift_codes,
                    night_shift_detection_desc=night_shift_detection_desc,
                    night_shift_details=night_shift_details,
                )
                results.append(result)
            print(f"[耗时] 逐张计算风险值: {time.time() - t0:.1f}s, 共 {len(results)} 条")

            print(f"共评估 {len(results)} 条工作计划编号")

            # 12.5 增量输出模式：只输出本次新增的工作票（即不在缓存中的票）
            # 但夜间作业的票始终保留（即使已被缓存，也需要重新输出到Excel）
            if incremental_output and use_cache:
                new_work_codes = {t.get('work_code', '') for t in new_tickets if t.get('work_code')}
                night_shift_codes_filtered = night_shift_work_codes or set()
                results = [
                    r for r in results
                    if r.get('作业计划编号', '') in new_work_codes
                    or r.get('is_night_shift', False)
                ]
                # 统计新增中夜间作业的数量
                ns_in_new = sum(1 for r in results if r.get('is_night_shift', False))
                print(f"增量输出: 过滤后剩余 {len(results)} 条（其中夜间作业 {ns_in_new} 条）")

            # 13. 保存当天新增的大模型评估结果和人员ID类型到缓存
            if use_cache:
                new_llm_for_cache = self._extract_new_llm_results(
                    new_tickets, llm_results, loc_results, work_tickets
                )
                cache.save_cache(cache.get_today_str(), new_llm_for_cache,
                                 user_id_types=new_user_id_types)
                # 清理超过查询窗口的旧缓存文件（默认30天，与查询窗口匹配）
                cache.clean_old_cache(keep_days=30)
                # 清理超过7天的旧日志文件
                cache.clean_old_logs(keep_days=7)
                # 清理超过7天的旧Excel输出文件
                cache.clean_old_outputs(keep_days=7)

            # 统计汇总
            cached_count = len(work_tickets) - len(new_tickets) if use_cache else 0
            logging.info(f"本次运行统计: 共获取 {len(work_tickets)} 条数据, "
                         f"缓存命中(已过滤) {cached_count} 条, "
                         f"新增评估 {len(new_tickets)} 条, "
                         f"最终输出 {len(results)} 条")
            print(f"本次运行统计: 共获取 {len(work_tickets)} 条, "
                  f"缓存命中 {cached_count} 条, 新增 {len(new_tickets)} 条, 输出 {len(results)} 条")

            return results

        finally:
            self.fetcher.close()

    # ==================== 单张票评估 ====================

    def _calc_single_ticket(
        self, ticket: Dict, ticket_idx: int,
        peccancy_dict: Dict, hot_work_dict: Dict,
        llm_results: Dict, llm_location_results: Dict,
        work_plan_details: Dict, dynamic_risk_dict: Dict, dynamic_risk_d_dict: Dict, benchmark_dict: Dict,
        change_member_dict: Dict = None, change_info: Dict = None,
        night_shift_work_codes: Set[str] = None,
        night_shift_detection_desc: str = '',
        night_shift_details: Dict = None,
    ) -> Dict:
        """计算单张工作票的风险值"""
        work_code = ticket.get('work_code', '')
        work_task = ticket.get('work_task', '') or ''
        ticket_key = f"{ticket.get('ticket_no', '')}_{ticket_idx}"
        customer_scores = dynamic_risk_dict.get(work_code, {})
        work_plan = work_plan_details.get(work_code, {})

        # --- B: 作业人员能力风险值 ---
        B = 0

        # B1: 现场作业负责人 + 监护人安全意识
        principal_guardian_score, principal_guardian_results = self._calc_principal_guardian_awareness(
            ticket, peccancy_dict
        )
        B += principal_guardian_score

        # B2: 主要工作班成员安全意识
        member_score = self._calc_member_awareness(ticket, peccancy_dict)
        B += member_score

        # B3: 作业总人数
        work_count_score = self.engine.calc_work_count(ticket.get('work_member_count'))
        B += work_count_score

        # B4: 负责人的人员性质
        principal_nature, principal_nature_score = self.engine.calc_personnel_nature(
            ticket.get('task_main'),
            ticket.get('whether_outer_dept'),
            ticket.get('work_principal_oname'),
        )
        B += principal_nature_score

        # --- C: 作业环境和时间影响风险值 ---
        C = 0

        # C1: 作业地段（大模型优先）
        work_location_score = self._get_llm_score(llm_location_results, ticket_key)
        C += work_location_score

        # C2: 作业类型（大模型优先 + 动火作业）
        work_type_score = self._get_llm_score(llm_results, ticket_key)
        has_hot_work = work_code in hot_work_dict
        if has_hot_work:
            work_type_score += 5
        C += work_type_score

        # C3: 作业时段
        # 如果该工作票被检测为夜间作业，强制判定为夜间作业
        is_night_shift = night_shift_work_codes and work_code in night_shift_work_codes
        night_shift_judgment = ''

        # 即使检测为夜间作业，如果工作内容包含【机巡】、【智能巡检】、【智能巡视】等关键词，也不计入夜间作业
        if is_night_shift:
            # 优先从检测详情获取工作内容，回退到 ticket 自身字段
            ns_detail = (night_shift_details or {}).get(work_code, {})
            ns_work_task = ns_detail.get('work_task', '') or ''
            ticket_work_task = ticket.get('work_task', '') or ''
            work_task_check = ns_work_task or ticket_work_task
            if work_task_check and any(kw in work_task_check for kw in
                                       ['机巡', '智能巡检', '智能巡视']):
                logging.info(
                    f"夜间作业检测命中但工作内容包含排除关键词（{work_code}），"
                    f"取消夜间作业判定: {work_task_check[:60]}"
                )
                is_night_shift = False

        if is_night_shift:
            # 从夜间作业检测详情中获取该 work_code 的检测信息
            ns_detail = (night_shift_details or {}).get(work_code, {})
            # ticket_type 优先从检测详情获取（新JSON），回退到 ticket 自身字段（旧JSON或数据库）
            ticket_type_val = str(ns_detail.get('ticket_type', '') or ticket.get('ticket_type', '') or '')
            detected_at = ns_detail.get('detected_at', '') or ''

            # last_gap_time/last_gap_start_time：优先从检测详情（新JSON有details字段），
            # 回退到 ticket（数据库查询已包含 wb.last_gap_time/wb.last_gap_start_time），
            # 处理 datetime 对象 → 字符串格式化
            def _fmt_gap(val):
                if val is None:
                    return None
                if isinstance(val, str):
                    return val
                if hasattr(val, 'strftime'):
                    return val.strftime('%Y-%m-%d %H:%M:%S')
                return str(val)

            last_gap_time = _fmt_gap(
                ns_detail.get('last_gap_time') or ticket.get('last_gap_time')
            )
            last_gap_start_time = _fmt_gap(
                ns_detail.get('last_gap_start_time') or ticket.get('last_gap_start_time')
            )

            # 检测时间回退：从检测时间描述中提取
            if not detected_at and night_shift_detection_desc:
                # 尝试从 "线路检测: 2026-07-08 20:05:00, 厂站检测: 2026-07-09 00:02:00" 中提取
                import re
                if ticket_type_val in ('21', '22'):
                    m = re.search(r'线路检测:\s*([\d\-]+\s[\d:]+)', night_shift_detection_desc)
                    if m:
                        detected_at = m.group(1)
                elif ticket_type_val in ('11', '12', '13'):
                    m = re.search(r'厂站检测:\s*([\d\-]+\s[\d:]+)', night_shift_detection_desc)
                    if m:
                        detected_at = m.group(1)
                else:
                    m = re.search(r'(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})', night_shift_detection_desc)
                    if m:
                        detected_at = m.group(1)

            # 根据工作票类型判定室内/室外，构建C3列值和问题描述判定文本
            if ticket_type_val in ('11', '12', '13'):
                # 厂站工作票 → 室内夜间作业
                c3_label = '室内夜间作业(0点-次日6:00)'
                if last_gap_time:
                    night_shift_judgment = (
                        f'室内夜间作业(0点-次日6:00)，系统时间{detected_at}，'
                        f'最后一次开工时间{last_gap_start_time}大于'
                        f'最后一次间断时间{last_gap_time}，判定为夜间作业'
                    )
                else:
                    night_shift_judgment = (
                        f'室内夜间作业(0点-次日6:00)，系统时间{detected_at}，'
                        f'无最后一次间断时间，但系统时间内工作票状态在执行中，判定为夜间作业'
                    )
            elif ticket_type_val in ('21', '22'):
                # 线路工作票 → 室外夜间作业
                c3_label = '室外夜间作业(19:00-次日6:00)'
                night_shift_judgment = (
                    f'室外夜间作业(19:00-次日6:00)，系统时间{detected_at}，'
                    f'系统时间内工作票状态在执行中，判定为夜间作业'
                )
            else:
                # 无详细检测信息（旧JSON格式或未知类型）
                c3_label = '夜间作业'
                night_shift_judgment = (
                    f'夜间作业，系统时间{detected_at}，'
                    f'工作票状态在执行中，判定为夜间作业'
                )

            # C3列值：显示"室内夜间作业(0点-次日6:00) [系统时间: XXX]"
            work_time_period = f'{c3_label} [系统时间: {detected_at}]'
            work_time_period_score = 20

            print(f"  夜间作业强制判定: {work_code} -> {night_shift_judgment[:80]}...")
        else:
            work_time_period = self._calc_work_time_period(work_plan, work_task)
            work_time_period_score = self.engine.calc_work_time_period_score(work_time_period)
        C += work_time_period_score

        # D: 电网、设备风险联动值（从数据库 DIMENSION_TYPE='3.00' 的人工评估中获取）
        d_items = dynamic_risk_d_dict.get(work_code, [])
        D = sum(item.get('风险值得分', 0) for item in d_items)

        # A: 基准风险值（典型基准风险值）
        # 输电风险值A = Amax * an
        # Amax = 最高的单项作业风险值
        # an = 作业风险系数: n=1→1, 1<n≤3→1.1, n>3→1.2
        benchmark_items = benchmark_dict.get(work_code, [])
        A = 0
        A_details = {'Amax': 0, 'an': 0, 'n': 0}
        if benchmark_items:
            n = len(benchmark_items)
            if n == 1:
                an = 1.0
            elif n <= 3:  # 1 < n <= 3
                an = 1.1
            else:  # n > 3
                an = 1.2
            risk_values = []
            for item in benchmark_items:
                rv = item.get('risk_value')
                if rv is not None:
                    risk_values.append(float(rv))
            Amax = max(risk_values) if risk_values else 0
            A = Amax * an
            A_details = {'Amax': Amax, 'an': an, 'n': n}

        # F: 总风险值（含基准风险值A）
        F = B + C + D + A

        # 变更成员信息（先提取，用于传递给 _build_detailed_results 和查询数据）
        change_info_for_ticket = (change_info or {}).get(work_code, {})
        # 计算调整后人数（将人员变动反映到 B3 作业总人数评分中）
        original_count = ticket.get('work_member_count')
        member_adjustment = change_info_for_ticket.get('member_adjustment', 0)
        adjusted_work_count = original_count
        if member_adjustment:
            try:
                adjusted_work_count = max(0, int(original_count or 0) + member_adjustment)
                # 重新计算 B3 分值（人员变动影响总人数），然后更新 B 和 F
                work_count_score = self.engine.calc_work_count(adjusted_work_count)
                B = principal_guardian_score + member_score + work_count_score + principal_nature_score
                F = B + C + D + A
                print(f"  人员变动调整: {work_code} 原始人数 {original_count} -> 调整后 {adjusted_work_count} (调整{member_adjustment:+d}), B3分值更新")
            except (ValueError, TypeError):
                adjusted_work_count = original_count
        # 保存调整后人数（供 _build_query_data 的'调整后人数'字段使用）
        change_info_for_ticket['adjusted_count'] = adjusted_work_count

        # --- 生成详细评估结果 ---
        detailed_results = self._build_detailed_results(
            ticket, ticket_key, work_code, customer_scores,
            principal_guardian_results, peccancy_dict,
            principal_guardian_score, member_score, work_count_score,
            principal_nature, principal_nature_score,
            work_location_score, work_type_score, has_hot_work,
            work_time_period, work_time_period_score,
            llm_results, llm_location_results,
            work_plan, A, A_details,
            change_info=change_info_for_ticket,
            adjusted_work_count=adjusted_work_count,
        )

        bureau_code = ticket.get('bureau_code', '')
        return {
            '工作票票号': ticket.get('ticket_no'),
            '作业计划编号': work_code,
            '工作内容': ticket.get('work_content', ''),
            '工作任务': work_task,
            '局编码': bureau_code,
            '地市局': self.BUREAU_MAP.get(bureau_code, ''),
            '基准关系': benchmark_dict.get(work_code, []),
            'A（基准风险值）': A,
            'B（作业人员能力风险值）': B,
            'C（作业环境和时间影响风险值）': C,
            'D（电网、设备风险联动值）': D,
            'D_items': d_items,
            'F（总风险值）': F,
            '详细评估结果': detailed_results,
            '查询数据': self._build_query_data(ticket, peccancy_dict, work_code, change_info),
            '变更成员': change_info_for_ticket,
            'is_night_shift': is_night_shift,
            'night_shift_judgment': night_shift_judgment,
        }

    # ==================== 查询数据构建 ====================

    def _build_query_data(self, ticket: Dict, peccancy_dict: Dict,
                          work_code: str = None, change_info: Dict = None) -> Dict:
        """构建查询数据工作表所需的原始数据库字段"""

        def _fmt_viol(uid):
            """格式化单个人员的违章记录"""
            if not uid:
                return ''
            viol = peccancy_dict.get(uid, {})
            if not viol:
                return '无违章'
            return ','.join(f'{k}类{viol[k]}次' for k in viol)

        def _build_member_name_map(uids_str, unames_str):
            """构建 uid -> uname 的映射（按位置对应）"""
            if not uids_str:
                return {}
            uid_parts = []
            for uid in uids_str.split(','):
                uid = uid.strip()
                if not uid:
                    continue
                sub_parts = self.engine.split_member_ids(uid)
                if sub_parts:
                    uid_parts.extend(sub_parts)
                else:
                    uid_parts.append(uid)

            uname_parts = []
            if unames_str:
                for uname in unames_str.split(','):
                    uname = uname.strip()
                    if not uname:
                        continue
                    sub_parts = self.engine.split_member_ids(uname)
                    if sub_parts:
                        uname_parts.extend(sub_parts)
                    else:
                        uname_parts.append(uname)

            name_map = {}
            for i, uid in enumerate(uid_parts):
                if i < len(uname_parts) and uname_parts[i]:
                    name_map[uid] = uname_parts[i]
            return name_map

        member_name_map = _build_member_name_map(
            ticket.get('work_member_uid', ''),
            ticket.get('work_member_uname', '')
        )

        def _fmt_members(uids_str):
            """格式化班组成员姓名列表"""
            if not uids_str:
                return ''
            uids = [u.strip() for u in uids_str.split(',') if u.strip()]
            names = []
            for uid in uids:
                parts = self.engine.split_member_ids(uid)
                if not parts:
                    parts = [uid]
                for part in parts:
                    display = self.engine.clean_bracket_content(part) or part
                    if not self.engine.contains_chinese(display):
                        resolved = (member_name_map.get(part, '') or
                                    self._user_name_map.get(part, '') or
                                    member_name_map.get(display, '') or
                                    self._user_name_map.get(display, ''))
                        if resolved:
                            display = resolved
                    names.append(display)
            return '、'.join(names)

        def _fmt_members_viol(uids_str):
            """格式化班组成员的违章记录"""
            if not uids_str:
                return ''
            uids = [u.strip() for u in uids_str.split(',') if u.strip()]
            viols = []
            for uid in uids:
                parts = self.engine.split_member_ids(uid)
                if not parts:
                    parts = [uid]
                for part in parts:
                    viol = peccancy_dict.get(part, {})
                    if not viol:
                        viols.append('无违章')
                    else:
                        viols.append(','.join(f'{k}类{viol[k]}次' for k in viol))
            return '；'.join(viols)

        def _fmt_name(uid, uname):
            """格式化单个人员姓名"""
            if uname:
                return uname
            if uid:
                return self._user_name_map.get(uid, uid)
            return ''

        # 变更成员信息
        cinfo = (change_info or {}).get(work_code or ticket.get('work_code', ''), {})
        change_member_text = ''
        if cinfo.get('added_names') or cinfo.get('removed_names'):
            parts = []
            if cinfo.get('added_names'):
                for n in cinfo['added_names']:
                    parts.append(f"新增：{n}")
            if cinfo.get('removed_names'):
                for n in cinfo['removed_names']:
                    parts.append(f"退出：{n}")
            change_member_text = '，'.join(parts)

        # 新增人员违章记录
        added_peccancy_text = ''
        if cinfo.get('added_peccancy'):
            added_peccancy_text = '；'.join(
                f"{n}: {','.join(f'{k}类{v[k]}次' for k in v)}"
                for n, v in cinfo['added_peccancy'].items()
            ) if any(cinfo['added_peccancy'].values()) else '新增人员无违章'

        return {
            '地市局': self.BUREAU_MAP.get(ticket.get('bureau_code', ''), ''),
            '作业计划编号': ticket.get('work_code', ''),
            '作业人数': ticket.get('work_member_count', ''),
            '负责人': _fmt_name(ticket.get('work_principal_uid', ''), ticket.get('work_principal_uname', '')),
            '负责人违章': _fmt_viol(ticket.get('work_principal_uid', '')),
            '班组成员': _fmt_members(ticket.get('work_member_uid', '')),
            '班组成员违章': _fmt_members_viol(ticket.get('work_member_uid', '')),
            '监护人': _fmt_name(ticket.get('guardian_uid', ''), ticket.get('guardian_uname', '')),
            '监护人违章': _fmt_viol(ticket.get('guardian_uid', '')),
            '班组成员变更': change_member_text,
            '新增人员违章': added_peccancy_text,
            '人数调整': cinfo.get('member_adjustment', 0),
            '调整后人数': cinfo.get('adjusted_count', ticket.get('work_member_count', '')),
            '工作内容': ticket.get('work_content', ''),
            '工作任务': ticket.get('work_task', ''),
        }

    # ==================== 变更成员处理 ====================

    def _process_change_members(self, change_member_dict: Dict,
                                 peccancy_dict: Dict) -> Dict[str, Dict]:
        """
        处理班组成员变更记录：
        1. 大模型解析 change_content 提取新增/退出人员姓名
        2. 通过姓名查询新增人员的违章记录
        3. 计算人数调整值
        :return: {work_code: {added_names, removed_names, added_peccancy, member_adjustment, adjusted_count}}
        """
        import asyncio
        import aiohttp

        result = {}
        # 收集所有 change_content 用于大模型解析
        items_to_parse = []  # [(work_code, change_content), ...]
        for wc, records in change_member_dict.items():
            if records:
                content = records[0].get('change_content', '')
                if content:
                    items_to_parse.append((wc, content))

        if not items_to_parse:
            return result

        print(f"班组成员变更解析: 共 {len(items_to_parse)} 条变更记录等待大模型解析...")

        # 并发调用大模型解析
        loop = asyncio.new_event_loop()
        try:
            async def parse_all():
                async with aiohttp.ClientSession() as session:
                    from config_loader import get_llm_max_concurrent
                    sem = asyncio.Semaphore(get_llm_max_concurrent())
                    coros = [
                        self.engine.parse_change_content(content, sem, session)
                        for _, content in items_to_parse
                    ]
                    if coros:
                        batch_size = 200
                        all_results = []
                        for i in range(0, len(coros), batch_size):
                            batch = coros[i:i + batch_size]
                            all_results.extend(await asyncio.gather(*batch))
                        return all_results
                    return []

            parse_results = loop.run_until_complete(parse_all())
        finally:
            loop.close()

        # 收集所有新增人员的姓名，统一批量查违章
        all_added_names = set()
        for (wc, _), parse_result in zip(items_to_parse, parse_results):
            added_names = parse_result.get('added', [])
            all_added_names.update(added_names)

        # 批量按姓名查询违章记录
        name_peccancy_dict = {}
        if all_added_names:
            name_peccancy_dict = self.fetcher.fetch_peccancy_by_names(list(all_added_names))
            print(f"  按姓名查询违章: {len(all_added_names)} 人, 有违章记录 {sum(1 for v in name_peccancy_dict.values() if v)} 人")

        # 处理解析结果
        for (wc, _), parse_result in zip(items_to_parse, parse_results):
            added_names = parse_result.get('added', [])
            removed_names = parse_result.get('removed', [])

            # 从批量查询结果中提取该 work_code 的新增人员违章
            added_peccancy = {}
            for name in added_names:
                added_peccancy[name] = name_peccancy_dict.get(name, {})

            # 计算人数调整
            member_adjustment = len(added_names) - len(removed_names)

            result[wc] = {
                'added_names': added_names,
                'removed_names': removed_names,
                'added_peccancy': added_peccancy,
                'member_adjustment': member_adjustment,
            }

            if added_names or removed_names:
                add_str = f"新增{added_names}" if added_names else ""
                rem_str = f"退出{removed_names}" if removed_names else ""
                adj_str = f"调整{member_adjustment:+d}人" if member_adjustment != 0 else "人数不变"
                print(f"  变更: {wc} -> {add_str} {rem_str} ({adj_str})")
                if added_peccancy:
                    for name, viol in added_peccancy.items():
                        if viol:
                            viol_str = ','.join(f'{k}类{viol[k]}次' for k in viol)
                            print(f"    新增人员违章: {name} -> {viol_str}")

        return result

    # ==================== B 值子计算 ====================

    def _calc_principal_guardian_awareness(self, ticket: Dict, peccancy_dict: Dict) -> Tuple[int, List[Dict]]:
        """计算工作负责人+监护人的安全意识得分（取最高分）"""
        persons = []
        if ticket.get('work_principal_uid'):
            persons.append(('工作负责人', ticket['work_principal_uid'], ticket.get('work_principal_uname', '')))
        if ticket.get('guardian_uid'):
            persons.append(('监护人', ticket['guardian_uid'], ticket.get('guardian_uname', '')))

        results = []
        max_score = 0
        for ptype, puid, pname in persons:
            parts = self.engine.split_member_ids(puid)
            if not parts:
                parts = [puid]
            for part in parts:
                score = self.engine.calc_person_awareness(peccancy_dict, part)
                display_name = pname
                if not display_name and not self.engine.contains_chinese(part):
                    display_name = self._user_name_map.get(part, part)
                elif not display_name:
                    display_name = part
                results.append({'type': ptype, 'uid': part, 'uname': display_name, 'score': score})
                if score > max_score:
                    max_score = score
        return max_score, results

    def _calc_member_awareness(self, ticket: Dict, peccancy_dict: Dict) -> int:
        """计算主要工作班成员的安全意识得分（取最高分）"""
        work_member_uid = ticket.get('work_member_uid')
        if not work_member_uid:
            return 0
        max_score = 0
        for mid in work_member_uid.split(','):
            if not mid.strip():
                continue
            parts = self.engine.split_member_ids(mid.strip())
            if not parts:
                parts = [mid.strip()]
            for part in parts:
                score = self.engine.calc_person_awareness(peccancy_dict, part)
                if score > max_score:
                    max_score = score
        return max_score

    # ==================== C 值子计算 ====================

    def _get_llm_score(self, llm_dict: Dict, ticket_key: str) -> int:
        """从大模型评估结果中获取分数"""
        result = llm_dict.get(ticket_key, {})
        rule = result.get('rule', '无')
        score = result.get('score', 0) if rule != '无' else 0
        if score > 0:
            keywords = result.get('keywords', '')
            logging.info(f"[评分获取] ticket_key={ticket_key}, score={score}, rule={rule}, keywords={keywords}")
        elif result and result != {}:
            logging.debug(f"[评分获取] ticket_key={ticket_key}, score=0, rule={rule}")
        return score

    def _calc_work_time_period(self, work_plan: Dict, work_task: str) -> str:
        """计算作业时段"""
        plan_start = work_plan.get('plan_start_time')
        plan_end = work_plan.get('plan_end_time')
        actual_start = work_plan.get('actual_start_time')
        actual_end = work_plan.get('actual_end_time')

        return self.engine.determine_work_time_period(
            plan_start, plan_end, actual_start, actual_end,
            work_task, None,
        )

    # ==================== 详细评估结果构建 ====================

    def _build_detailed_results(
        self, ticket: Dict, ticket_key: str, work_code: str,
        customer_scores: Dict, principal_guardian_results: List[Dict],
        peccancy_dict: Dict,
        principal_guardian_score: int, member_score: int, work_count_score: int,
        principal_nature: str, principal_nature_score: int,
        work_location_score: int, work_type_score: int, has_hot_work: bool,
        work_time_period: str, work_time_period_score: int,
        llm_results: Dict, llm_location_results: Dict,
        work_plan: Dict,
        A: float = 0, A_details: Dict = None,
        change_info: Dict = None,
        adjusted_work_count=None,
    ) -> List[Dict]:
        """构建详细评估结果列表"""
        results = []

        # 1. 现场作业负责人及监护人安全意识
        awareness_parts = []
        for person in principal_guardian_results:
            viol = peccancy_dict.get(person['uid'], {})
            viol_desc = '无违章' if not viol else ','.join([f'{k}类{viol[k]}次' for k in viol])
            awareness_parts.append(f"{person['type']}【{person['uname']}】{'存在' if viol else ''}{viol_desc}(得分:{person['score']})")
        principal_guardian_result = '; '.join(awareness_parts) if awareness_parts else '无人员'
        results.append(self._make_detail(
            ticket, work_code, '现场作业负责人（含小组工作负责人）及监护人（含专职监护人）安全意识',
            '安全意识', principal_guardian_result, principal_guardian_score,
            customer_scores.get('现场作业负责人（含小组工作负责人）及监护人（含专职监护人）安全意识', 0),
        ))

        # 2. 主要工作班成员安全意识
        member_result, member_violations = self._build_member_result(ticket, peccancy_dict, change_info)
        results.append(self._make_detail(
            ticket, work_code, '主要工作班成员(辅助工除外)安全意识',
            '安全意识', member_result, member_score,
            customer_scores.get('主要工作班成员（辅助工除外）安全意识', 0),
        ))

        # 3. 作业总人数（如有人员变动，显示调整后人数）
        display_count = adjusted_work_count if adjusted_work_count is not None else ticket.get('work_member_count', '未知')
        results.append(self._make_detail(
            ticket, work_code, '作业总人数', '作业总人数',
            str(display_count),
            work_count_score, customer_scores.get('作业总人数', 0),
        ))

        # 4. 负责人的人员性质
        results.append(self._make_detail(
            ticket, work_code, '负责人的人员性质', '人员性质',
            principal_nature, principal_nature_score,
            customer_scores.get('负责人的人员性质', 0),
        ))

        # 5. 作业地段
        llm_loc = llm_location_results.get(ticket_key, {})
        llm_loc_rule = llm_loc.get('rule', '无')
        work_location_result = f"作业地段：未知"
        if llm_loc_rule != '无':
            work_location_result += f"\n大模型评估:{llm_loc_rule} (关键词: {llm_loc.get('keywords', '无')})"
        results.append(self._make_detail_with_llm(
            ticket, work_code, '作业地段', '作业地段', work_location_result,
            work_location_score, customer_scores.get('作业地段', 0),
            llm_loc_rule, llm_loc.get('keywords', '无'), llm_loc.get('score', 0),
            llm_loc.get('inferred', ''),
        ))

        # 6. 作业类型
        llm_task = llm_results.get(ticket_key, {})
        llm_rule = llm_task.get('rule', '无')
        work_type_result = f"作业计划：{ticket.get('work_task', '')}"
        if llm_rule != '无':
            work_type_result += f"\n大模型评估:{llm_rule} (关键词: {llm_task.get('keywords', '无')})"
        if has_hot_work:
            work_type_result += '\n存在动火作业票'
        results.append(self._make_detail_with_llm(
            ticket, work_code, '作业类型', '作业类型', work_type_result,
            work_type_score, customer_scores.get('作业类型', 0),
            llm_rule, llm_task.get('keywords', '无'), llm_task.get('score', 0),
            llm_task.get('inferred', ''),
        ))

        # 7. 作业时段
        time_period_result = self._format_time_period_result(
            work_time_period, work_plan,
        )
        results.append(self._make_detail(
            ticket, work_code, '作业时段', '作业时段',
            time_period_result, work_time_period_score,
            customer_scores.get('作业时段', 0),
        ))

        # 8. 基准风险值（A值）
        # 基准风险值由规则计算得出，模型评估和人工评估采用相同分值
        A_details = A_details or {'Amax': 0, 'an': 0, 'n': 0}
        Amax = A_details.get('Amax', 0)
        an = A_details.get('an', 0)
        n = A_details.get('n', 0)
        if n > 0:
            benchmark_result = f"Amax={Amax}, an={an}, n={n}, A={A}分"
        else:
            benchmark_result = "无基准项目"
        results.append(self._make_detail(
            ticket, work_code, '基准风险值', '基准风险值',
            benchmark_result, int(A),
            int(A),  # 基准风险值由规则计算，人工评估同分
        ))

        return results

    def _build_member_result(self, ticket: Dict, peccancy_dict: Dict,
                             change_info: Dict = None) -> Tuple[str, Dict]:
        """构建班组成员评估结果"""
        work_member_uid = ticket.get('work_member_uid')
        work_member_uname = ticket.get('work_member_uname', '')
        member_parts = []
        member_violations = {}

        def _parse_member_list(s):
            if not s:
                return []
            result = []
            for item in s.split(','):
                item = item.strip()
                if not item:
                    continue
                parts = self.engine.split_member_ids(item)
                if parts:
                    result.extend(parts)
                else:
                    result.append(item)
            return result

        uid_list = _parse_member_list(work_member_uid)
        uname_list = _parse_member_list(work_member_uname)

        name_map = {}
        for i, uid in enumerate(uid_list):
            if i < len(uname_list) and uname_list[i]:
                name_map[uid] = uname_list[i]

        if work_member_uid:
            for part in uid_list:
                display = self.engine.clean_bracket_content(part) or part
                if not self.engine.contains_chinese(display):
                    resolved_name = (name_map.get(part, '') or
                                     self._user_name_map.get(part, '') or
                                     name_map.get(display, '') or
                                     self._user_name_map.get(display, ''))
                    if resolved_name:
                        display = resolved_name
                viol = peccancy_dict.get(part, {})
                viol_desc = '无违章' if not viol else ','.join([f'{k}类{viol[k]}次' for k in viol])
                member_parts.append(f"工作班成员【{display}】{'存在' if viol else ''}{viol_desc}")
                for k, v in viol.items():
                    member_violations[k] = member_violations.get(k, 0) + v

        # 追加变更新增人员的违章记录
        if change_info:
            added_peccancy = change_info.get('added_peccancy', {})
            added_names = change_info.get('added_names', [])
            if added_peccancy:
                for name in added_names:
                    viol = added_peccancy.get(name, {})
                    if viol:
                        viol_desc = ','.join([f'{k}类{viol[k]}次' for k in viol])
                        member_parts.append(f"工作班成员【{name}】(新增)存在{viol_desc}")
                        for k, v in viol.items():
                            member_violations[k] = member_violations.get(k, 0) + v

        return '; '.join(member_parts) if member_parts else '无人员', member_violations

    def _format_time_period_result(self, work_time_period: str, work_plan: Dict) -> str:
        """格式化作业时段评估结果"""
        plan_start = work_plan.get('plan_start_time')
        plan_end = work_plan.get('plan_end_time')
        actual_start = work_plan.get('actual_start_time')
        actual_end = work_plan.get('actual_end_time')

        if work_time_period == '时间段超过一天':
            ps = self._fmt_time(plan_start)
            pe = self._fmt_time(plan_end)
            return f'{work_time_period}（作业实际开展时间：{ps}至{pe}）' if ps and pe else work_time_period
        elif actual_end:
            a_s = self._fmt_time(actual_start)
            a_e = self._fmt_time(actual_end)
            return f'{work_time_period}（作业实际开展时间：{a_s}至{a_e}）' if a_s and a_e else work_time_period
        else:
            a_s = self._fmt_time(actual_start)
            return f'{work_time_period}（作业实际开展时间：{a_s}）' if a_s else work_time_period

    @staticmethod
    def _fmt_time(dt) -> str:
        if dt and hasattr(dt, 'strftime'):
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        return str(dt) if dt else ''

    # ==================== 详细评估结果辅助方法 ====================

    @staticmethod
    def _make_detail(ticket, work_code, factor, result_name, result_text, score, customer_score):
        return {
            '工作票票号': ticket.get('ticket_no'),
            '作业计划编号': work_code,
            '评估因子': factor,
            '评估结果名称': result_name,
            '评估结果': result_text,
            '风险值得分': score,
            '客户填入分值': customer_score,
            '分值差异': '有差异' if customer_score != score else '',
        }

    @staticmethod
    def _make_detail_with_llm(ticket, work_code, factor, result_name, result_text,
                               score, customer_score, llm_rule, llm_keywords, llm_score, llm_inferred=''):
        return {
            '工作票票号': ticket.get('ticket_no'),
            '作业计划编号': work_code,
            '评估因子': factor,
            '评估结果名称': result_name,
            '评估结果': result_text,
            '风险值得分': score,
            '大模型命中规则': llm_rule,
            '大模型命中关键词': llm_keywords,
            '大模型加分': llm_score,
            '大模型推断依据': llm_inferred,
            '客户填入分值': customer_score,
            '分值差异': '有差异' if customer_score != score else '',
        }

    # ==================== 人员ID分类 ====================

    def _collect_user_ids(self, work_tickets: List[Dict]) -> List[str]:
        """收集所有操作票中的人员ID"""
        all_ids = set()
        for t in work_tickets:
            for field in ['work_principal_uid', 'guardian_uid']:
                uid = t.get(field)
                if uid:
                    parts = self.engine.split_member_ids(uid)
                    if parts:
                        all_ids.update(parts)
                    else:
                        all_ids.add(uid)
            member_uid = t.get('work_member_uid')
            if member_uid:
                for mid in member_uid.split(','):
                    mid = mid.strip()
                    if not mid:
                        continue
                    parts = self.engine.split_member_ids(mid)
                    if parts:
                        all_ids.update(parts)
                    else:
                        all_ids.add(mid)
        return list(all_ids)

    def _fast_classify_user_ids(self, all_user_ids: List[str], peccancy_dict: Dict,
                                user_id_type_cache: Dict[str, bool] = None) -> Tuple[List[str], List[str], List[str], int]:
        """快速分类人员ID（正则 + 缓存，不调LLM）
        :param user_id_type_cache: 历史缓存 {user_id: is_chinese_name}
        :return: (user_ids, user_names, need_llm, cache_hit_count)
            - need_llm: 需要大模型判断的中文项列表
        """
        user_id_type_cache = user_id_type_cache or {}
        user_ids = []
        user_names = []
        need_llm = []
        cache_hit_count = 0

        for uid in all_user_ids:
            parts = self.engine.split_member_ids(uid)
            if not parts:
                parts = [uid]
            for part in parts:
                cleaned = self.engine.clean_bracket_content(part)
                if not cleaned:
                    continue
                if self._is_invalid_id(part):
                    user_ids.append(part)
                    continue

                if self.engine.contains_chinese(cleaned):
                    if cleaned in user_id_type_cache:
                        cache_hit_count += 1
                        if user_id_type_cache[cleaned]:
                            user_names.append(cleaned)
                        else:
                            user_ids.append(cleaned)
                    else:
                        need_llm.append(cleaned)
                else:
                    user_ids.append(part)

        return user_ids, user_names, need_llm, cache_hit_count

    @staticmethod
    def _is_invalid_id(part: str) -> bool:
        """检查是否为无效ID"""
        import re
        # 检查括号不完整
        if ('（' in part and '）' not in part) or ('(' in part and ')' not in part):
            return True
        if ('）' in part and '（' not in part) or (')' in part and '(' not in part):
            return True
        if re.match(r'^\d+人[）\)]?$', part):
            return True
        return False

    # ==================== 大模型并发评估 ====================

    def _run_llm_evaluations(self, work_tickets: List[Dict],
                              skip_work_codes: Set[str] = None,
                              classify_items: List[str] = None) -> Tuple[Dict, Dict, Dict]:
        """并发执行所有大模型评估（人员分类 + 工作任务 + 作业地段）
        :param skip_work_codes: 需要跳过的 work_code 集合（缓存已命中）
        :param classify_items: 需要大模型判断是否为中文姓名的项
        :return: (task_results, loc_results, classify_results)
            - classify_results: {item: is_chinese_name} 或空 dict
        """
        skip_work_codes = skip_work_codes or set()
        classify_items = classify_items or []
        tasks = []
        locations = []

        for idx, ticket in enumerate(work_tickets):
            work_task = (ticket.get('work_task') or '').strip()
            if not work_task:
                continue
            work_code = ticket.get('work_code', '')
            ticket_key = f"{ticket.get('ticket_no', '')}_{idx}"

            # 缓存命中：跳过，用占位符 None 填充
            if work_code in skip_work_codes:
                tasks.append((ticket_key, None))
                locations.append((ticket_key, None))
            else:
                tasks.append((ticket_key, work_task))
                locations.append((ticket_key, work_task))

        if not tasks and not classify_items:
            return {}, {}, {}

        new_count = sum(1 for _, wt in tasks if wt is not None)
        cached_count = len(tasks) - new_count
        classify_msg = f" + {len(classify_items)} 项人员分类" if classify_items else ""
        print(f"开始并发评估：{new_count} 个新增 + {cached_count} 个缓存命中{classify_msg}，"
              f"共 {len(tasks)} 个任务...")

        loop = asyncio.new_event_loop()
        try:
            async def evaluate_all():
                async with aiohttp.ClientSession() as session:
                    sem = Semaphore(get_llm_max_concurrent())
                    task_coros = [
                        None if wt is None else self.engine.evaluate_work_task(wt, sem, session)
                        for _, wt in tasks
                    ]
                    loc_coros = [
                        None if wc is None else self.engine.evaluate_work_location(wc, sem, session)
                        for _, wc in locations
                    ]
                    classify_coros = [
                        self.engine.is_chinese_name(item, sem, session) for item in classify_items
                    ]

                    # 只并发执行非 None 的协程
                    all_coros = [c for c in (task_coros + loc_coros + classify_coros) if c is not None]
                    if all_coros:
                        results = []
                        batch_size = 200
                        for i in range(0, len(all_coros), batch_size):
                            batch = all_coros[i:i + batch_size]
                            results.extend(await asyncio.gather(*batch))
                        return results
                    return []

            results = loop.run_until_complete(evaluate_all())

            result_idx = 0
            task_results = {}
            for i, (key, wt) in enumerate(tasks):
                if wt is not None:
                    task_results[key] = results[result_idx]
                    result_idx += 1

            loc_results = {}
            for i, (key, wt) in enumerate(locations):
                if wt is not None:
                    loc_results[key] = results[result_idx]
                    result_idx += 1

            # 人员分类结果
            classify_results = {}
            for item in classify_items:
                classify_results[item] = results[result_idx]
                result_idx += 1

            print(f"大模型并发评估完成")
            return task_results, loc_results, classify_results
        finally:
            loop.close()

    # ==================== 缓存合并方法 ====================

    def _merge_cached_llm_results(self, llm_results: Dict, loc_results: Dict,
                                   cached_llm: Dict, work_tickets: List[Dict]):
        """将缓存的大模型结果合并到当前结果字典中"""
        merged_count = 0
        empty_count = 0
        for idx, ticket in enumerate(work_tickets):
            work_code = ticket.get('work_code', '')
            if work_code not in cached_llm:
                continue
            ticket_key = f"{ticket.get('ticket_no', '')}_{idx}"
            cached = cached_llm[work_code]

            if ticket_key not in llm_results:
                llm_result = cached.get('llm_result', {})
                llm_results[ticket_key] = llm_result
                if not llm_result or llm_result == {}:
                    empty_count += 1
            if ticket_key not in loc_results:
                loc_results[ticket_key] = cached.get('llm_location', {})
            merged_count += 1

        if empty_count > 0:
            logging.warning(f"[缓存合并] 共合并 {merged_count} 条，其中 {empty_count} 条大模型结果为空！"
                            f"建议删除缓存文件重新运行以获取有效评估结果。")
        print(f"已合并 {merged_count} 条缓存的大模型结果")

    def _extract_new_llm_results(self, new_tickets: List[Dict],
                                  llm_results: Dict, loc_results: Dict,
                                  work_tickets: List[Dict]) -> Dict[str, Dict]:
        """从评估结果中提取新增票的大模型结果，用于保存到缓存"""
        new_llm = {}
        # 建立 work_code -> idx 的映射
        wc_to_idx = {}
        for idx, ticket in enumerate(work_tickets):
            wc = ticket.get('work_code', '')
            if wc:
                wc_to_idx[wc] = idx

        for ticket in new_tickets:
            wc = ticket.get('work_code', '')
            if not wc or wc not in wc_to_idx:
                continue
            idx = wc_to_idx[wc]
            ticket_key = f"{ticket.get('ticket_no', '')}_{idx}"

            llm_result = llm_results.get(ticket_key)
            loc_result = loc_results.get(ticket_key, {})
            new_llm[wc] = {
                'llm_result': llm_result if llm_result is not None else {},
                'llm_location': loc_result,
            }
            if llm_result is None:
                logging.debug(f"[缓存保存] work_code={wc}, 大模型未评估（可能 work_task 为空或评估失败），仍标记为已处理")
        logging.info(f"[缓存保存] 本次新增 {len(new_tickets)} 条，全部保存（含 {len(new_tickets) - sum(1 for v in new_llm.values() if v['llm_result'])} 条无LLM评估结果）")
        return new_llm

    # ==================== 预计算流程 ====================

    def precalculate(self, target_date: str = None) -> Optional[int]:
        """执行日预计算，将结果存入预计算表"""
        from datetime import datetime, timedelta
        if target_date is None:
            target_date = (datetime.now().date() - timedelta(days=1)).strftime('%Y-%m-%d')

        print(f"[预计算] 开始计算 {target_date} 的风险结果...")

        self.fetcher.connect()
        try:
            self.fetcher.create_daily_result_table()

            work_tickets = self.fetcher.fetch_precalc_work_tickets(target_date)
            print(f"[预计算] 查询到 {len(work_tickets)} 条工作计划编号")
            if not work_tickets:
                return 0

            # 收集人员ID
            all_user_ids = set()
            all_same_type_ids = set()
            for t in work_tickets:
                for field in ['work_principal_uid', 'guardian_uid']:
                    uid = t.get(field)
                    if uid:
                        parts = self.engine.split_member_ids(uid)
                        if parts:
                            all_user_ids.update(parts)
                            all_same_type_ids.update(parts)
                        else:
                            all_user_ids.add(uid)
                            all_same_type_ids.add(uid)
                member_uid = t.get('work_member_uid')
                if member_uid:
                    for mid in member_uid.split(','):
                        mid = mid.strip()
                        if not mid:
                            continue
                        parts = self.engine.split_member_ids(mid)
                        if parts:
                            all_user_ids.update(parts)
                            all_same_type_ids.update(parts)
                        else:
                            all_user_ids.add(mid)
                            all_same_type_ids.add(mid)

            # 查询违章
            peccancy_dict = self.fetcher.fetch_peccancy_records(list(all_user_ids))

            # 查询同类型作业次数
            same_type_dict = self.fetcher.fetch_batch_same_type_scores(list(all_same_type_ids))

            # 大模型评估
            llm_results, llm_location_results = self._precalc_llm_evaluations(work_tickets)

            # 逐张计算
            stored_count = 0
            for idx, ticket in enumerate(work_tickets):
                record = self._precalc_single_ticket(
                    ticket, idx, peccancy_dict, same_type_dict, llm_results, llm_location_results,
                )
                self.fetcher.insert_daily_result(record)
                stored_count += 1

            self.fetcher.connection.commit()
            print(f"[预计算] 成功存储 {stored_count} 条记录")
            return stored_count
        finally:
            self.fetcher.close()

    def _precalc_llm_evaluations(self, work_tickets: List[Dict]) -> Tuple[Dict, Dict]:
        """预计算的大模型评估"""
        tasks = []
        for idx, ticket in enumerate(work_tickets):
            wt = (ticket.get('work_task') or '').strip()
            if wt:
                key = f"{ticket.get('ticket_no', '')}_{idx}"
                tasks.append((key, wt))

        if not tasks:
            return {}, {}

        loop = asyncio.new_event_loop()
        try:
            async def evaluate_all():
                async with aiohttp.ClientSession() as session:
                    sem = Semaphore(get_llm_max_concurrent())
                    task_coros = [self.engine.evaluate_work_task(wt, sem, session) for _, wt in tasks]
                    loc_coros = [self.engine.evaluate_work_location(wt, sem, session) for _, wt in tasks]
                    # 分批执行，避免一次性调度过多协程导致 event loop 阻塞
                    all_coros = task_coros + loc_coros
                    results = []
                    batch_size = 200
                    for i in range(0, len(all_coros), batch_size):
                        batch = all_coros[i:i + batch_size]
                        results.extend(await asyncio.gather(*batch))
                    return results

            results = loop.run_until_complete(evaluate_all())
            n = len(tasks)
            task_results = {tasks[i][0]: results[i] for i in range(n)}
            loc_results = {tasks[i][0]: results[n + i] for i in range(n)}
            return task_results, loc_results
        finally:
            loop.close()

    def _precalc_single_ticket(self, ticket: Dict, ticket_idx: int,
                                peccancy_dict: Dict, same_type_dict: Dict,
                                llm_results: Dict, llm_location_results: Dict) -> Dict:
        """预计算单张票"""
        ticket_key = f"{ticket.get('ticket_no', '')}_{ticket_idx}"
        work_task = ticket.get('work_task', '')
        work_content = ticket.get('work_content', '')
        task_type = ticket.get('task_type')

        # 安全意识（取最高分，与主评估路径 _calc_principal_guardian_awareness / _calc_member_awareness 一致）
        # B1: 负责人 + 监护人（取最高分）
        principal_guardian_score = 0
        for uid_field in ['work_principal_uid', 'guardian_uid']:
            uid = ticket.get(uid_field)
            if uid:
                parts = self.engine.split_member_ids(uid)
                if not parts:
                    parts = [uid]
                for part in parts:
                    score = self.engine.calc_person_awareness(peccancy_dict, part)
                    if score > principal_guardian_score:
                        principal_guardian_score = score

        # B2: 主要工作班成员（取最高分）
        member_score = 0
        member_uid = ticket.get('work_member_uid')
        if member_uid:
            for mid in member_uid.split(','):
                mid = mid.strip()
                if not mid:
                    continue
                parts = self.engine.split_member_ids(mid)
                if not parts:
                    parts = [mid]
                for part in parts:
                    score = self.engine.calc_person_awareness(peccancy_dict, part)
                    if score > member_score:
                        member_score = score

        safety_score = principal_guardian_score + member_score

        # 作业总人数
        work_count_score = self.engine.calc_work_count(ticket.get('work_member_count'))

        # 人员性质
        nature_desc, nature_score = self.engine.calc_personnel_nature(
            ticket.get('task_main'),
            ticket.get('whether_outer_dept'),
            ticket.get('work_principal_oname'),
        )

        # 同类型作业经验
        same_type_score = 0
        if task_type:
            for uid_field in ['work_principal_uid', 'guardian_uid']:
                uid = ticket.get(uid_field)
                if uid:
                    parts = self.engine.split_member_ids(uid)
                    if not parts:
                        parts = [uid]
                    for part in parts:
                        if part in same_type_dict and task_type in same_type_dict[part]:
                            same_type_score += same_type_dict[part][task_type]['score']
            if member_uid:
                for mid in member_uid.split(','):
                    mid = mid.strip()
                    if not mid:
                        continue
                    parts = self.engine.split_member_ids(mid)
                    if not parts:
                        parts = [mid]
                    for part in parts:
                        if part in same_type_dict and task_type in same_type_dict[part]:
                            s = same_type_dict[part][task_type]['score']
                            if s > same_type_score:
                                same_type_score = s

        # 作业地段（大模型优先）
        llm_loc = llm_location_results.get(ticket_key, {})
        if llm_loc.get('rule', '无') != '无':
            work_location_score = llm_loc.get('score', 0)
        else:
            work_location_score = 0
            loc_rules = [
                (['有限空间', '完备', '良好'], 3),
                (['有限空间', '不完备', '不良'], 10),
                (['氧气不足', '有毒有害'], 999),
                (['多回共塔', '带电线路'], 10),
                (['林区'], 15),
                (['地质隐患'], 15),
                (['导地线', '光缆脱落', '重要交叉'], 30),
            ]
            for keywords, score in loc_rules:
                if all(kw in work_content for kw in keywords):
                    work_location_score = score
                    break

        # 作业类型（大模型优先）
        llm_task = llm_results.get(ticket_key, {})
        if llm_task.get('rule', '无') != '无':
            work_type_score = llm_task.get('score', 0)
        else:
            work_type_score = 0
            type_rules = [
                (['30米以上'], 10),
                (['15米以上', '30米以下'], 7),
                (['5米以上', '15米以下'], 5),
                (['1.5米以上', '5米以下'], 2),
                (['吊装'], 5),
            ]
            for keywords, score in type_rules:
                if all(kw in work_content for kw in keywords):
                    work_type_score = score
                    break

        B = safety_score + work_count_score + nature_score + same_type_score
        C = work_location_score + work_type_score
        F = B + C

        return {
            'ticket_no': ticket.get('ticket_no'),
            'work_code': ticket.get('work_code'),
            'work_task': work_task,
            'risk_score': F,
            'b_score': B,
            'c_score': C,
            'd_score': 0,
            'work_member_count': ticket.get('work_member_count'),
            'principal_nature': nature_desc,
            'work_location': ticket.get('work_place', ''),
            'work_type': ticket.get('major_sub_type', ''),
            'plan_nature': '计划性作业',
        }