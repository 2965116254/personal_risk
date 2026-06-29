# -*- coding: utf-8 -*-
"""
风险评估核心编排层
使用 DataFetcher 获取数据，使用 RiskRuleEngine 计算规则得分，
使用 ai_client 调用大模型，最终生成结构化评估结果。
"""

import os
import sys
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

    def __init__(self, db_config: Dict):
        self.db_config = db_config
        self.fetcher = DataFetcher(db_config)
        self.engine = RiskRuleEngine()

    # ==================== 主评估流程 ====================

    def assess(self, limit: int = None, cutoff_date: str = None, start_date: str = None, end_date: str = None,
               use_cache: bool = True, work_codes: List[str] = None,
               incremental_output: bool = False) -> List[Dict]:
        """执行风险评估主流程，返回评估结果列表
        :param work_codes: 若指定，则按作业计划编号列表查询，忽略 limit/cutoff_date/start_date/end_date
        :param incremental_output: 是否只返回增量数据（跳过缓存中已存在的工作票），用于 Excel 增量输出
        """
        self.fetcher.connect()
        cache = DataCache()
        try:
            # 1. 查询操作票
            if work_codes:
                work_tickets = self.fetcher.fetch_work_tickets_by_codes(work_codes)
            else:
                work_tickets = self.fetcher.fetch_work_tickets(limit, cutoff_date, start_date, end_date)
            if not work_tickets:
                print("没有找到任何工作计划编号")
                return []

            print(f"找到 {len(work_tickets)} 条工作计划编号")

            # 2. 增量对比：找出需要大模型评估的新票
            new_tickets = work_tickets
            cached_llm = {}  # {work_code: {llm_result, llm_location, llm_location_type}}
            if use_cache:
                new_tickets, cached_llm = cache.find_new_tickets(work_tickets)
                skip_work_codes = set(cached_llm.keys())
            else:
                skip_work_codes = set()

            # 3. 收集所有人员ID
            all_user_ids = self._collect_user_ids(work_tickets)

            # 4. 查询违章记录
            peccancy_dict = self.fetcher.fetch_peccancy_records(all_user_ids)

            # 5. 加载人员ID类型缓存，快速分类（正则 + 缓存，不调LLM）
            user_id_type_cache = cache.load_all_user_id_types() if use_cache else {}
            user_ids, user_names, need_llm_classify, cache_hit_count = self._fast_classify_user_ids(
                all_user_ids, peccancy_dict, user_id_type_cache=user_id_type_cache
            )
            print(f"快速过滤完成，{len(need_llm_classify)} 项需要大模型判断（缓存命中 {cache_hit_count} 项）")

            # 6. 查询动火作业票
            work_codes = {t.get('work_code') for t in work_tickets if t.get('work_code')}
            hot_work_dict = self.fetcher.fetch_hot_work_tickets(list(work_codes))

            # 7. 合并并发：人员分类 + 工作票评估（共享同一个事件循环和信号量）
            llm_results, loc_results, lt_results, classify_results = self._run_llm_evaluations(
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
                self._merge_cached_llm_results(llm_results, loc_results, lt_results,
                                               cached_llm, work_tickets)

            # 9. 批量查询作业计划详情
            work_plan_details = self.fetcher.fetch_work_plan_details(list(work_codes))

            # 10. 批量查询客户填入的动态风险分值
            dynamic_risk_dict = self.fetcher.fetch_dynamic_risk_scores(list(work_codes))

            # 11. 批量查询基准关系
            benchmark_dict = self.fetcher.fetch_benchmark_relations(list(work_codes), work_plan_details)

            # 12. 逐张计算风险值
            results = []
            for idx, ticket in enumerate(work_tickets):
                result = self._calc_single_ticket(
                    ticket, idx, peccancy_dict, hot_work_dict,
                    llm_results, loc_results, lt_results,
                    work_plan_details, dynamic_risk_dict, benchmark_dict,
                )
                results.append(result)

            print(f"共评估 {len(results)} 条工作计划编号")

            # 12.5 增量输出模式：只输出本次新增的工作票（即不在缓存中的票）
            if incremental_output and use_cache:
                new_work_codes = {t.get('work_code', '') for t in new_tickets if t.get('work_code')}
                results = [r for r in results if r.get('作业计划编号', '') in new_work_codes]
                print(f"增量输出: 过滤后剩余 {len(results)} 条新增工作计划编号")

            # 13. 保存当天新增的大模型评估结果和人员ID类型到缓存
            if use_cache:
                new_llm_for_cache = self._extract_new_llm_results(
                    new_tickets, llm_results, loc_results, lt_results, work_tickets
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
        llm_results: Dict, llm_location_results: Dict, llm_location_type_results: Dict,
        work_plan_details: Dict, dynamic_risk_dict: Dict, benchmark_dict: Dict,
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
        principal_nature, principal_nature_score = self.engine.calc_personnel_nature(ticket.get('task_main'))
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
        work_time_period = self._calc_work_time_period(work_plan, work_task, ticket_key, llm_location_type_results)
        work_time_period_score = self.engine.calc_work_time_period_score(work_time_period)
        C += work_time_period_score

        # D: 电网、设备风险联动值（暂不计算）
        D = 0

        # F: 总风险值
        F = B + C + D

        # --- 生成详细评估结果 ---
        detailed_results = self._build_detailed_results(
            ticket, ticket_key, work_code, customer_scores,
            principal_guardian_results, peccancy_dict,
            principal_guardian_score, member_score, work_count_score,
            principal_nature, principal_nature_score,
            work_location_score, work_type_score, has_hot_work,
            work_time_period, work_time_period_score,
            llm_results, llm_location_results,
            work_plan,
        )

        return {
            '工作票票号': ticket.get('ticket_no'),
            '作业计划编号': work_code,
            '工作任务': work_task,
            '基准关系': benchmark_dict.get(work_code, []),
            'B（作业人员能力风险值）': B,
            'C（作业环境和时间影响风险值）': C,
            'D（电网、设备风险联动值）': D,
            'F（总风险值）': F,
            '详细评估结果': detailed_results,
        }

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
            score = self.engine.calc_person_awareness(peccancy_dict, puid)
            results.append({'type': ptype, 'uid': puid, 'uname': pname, 'score': score})
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

    def _calc_work_time_period(self, work_plan: Dict, work_task: str,
                                ticket_key: str, llm_location_type_results: Dict) -> str:
        """计算作业时段"""
        plan_start = work_plan.get('plan_start_time')
        plan_end = work_plan.get('plan_end_time')
        actual_start = work_plan.get('actual_start_time')
        actual_end = work_plan.get('actual_end_time')

        location_type = None
        lt_result = llm_location_type_results.get(ticket_key, {})
        if lt_result:
            location_type = lt_result.get('location_type')

        return self.engine.determine_work_time_period(
            plan_start, plan_end, actual_start, actual_end,
            work_task, location_type,
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
        member_result, member_violations = self._build_member_result(ticket, peccancy_dict)
        results.append(self._make_detail(
            ticket, work_code, '主要工作班成员(辅助工除外)安全意识',
            '安全意识', member_result, member_score,
            customer_scores.get('主要工作班成员（辅助工除外）安全意识', 0),
        ))

        # 3. 作业总人数
        results.append(self._make_detail(
            ticket, work_code, '作业总人数', '作业总人数',
            str(ticket.get('work_member_count', '未知')),
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

        return results

    def _build_member_result(self, ticket: Dict, peccancy_dict: Dict) -> Tuple[str, Dict]:
        """构建班组成员评估结果"""
        work_member_uid = ticket.get('work_member_uid')
        member_parts = []
        member_violations = {}
        if work_member_uid:
            for mid in work_member_uid.split(','):
                if not mid.strip():
                    continue
                parts = self.engine.split_member_ids(mid.strip())
                if not parts:
                    parts = [mid.strip()]
                for part in parts:
                    display = self.engine.clean_bracket_content(part) or part
                    viol = peccancy_dict.get(part, {})
                    viol_desc = '无违章' if not viol else ','.join([f'{k}类{viol[k]}次' for k in viol])
                    member_parts.append(f"工作班成员【{display}】{'存在' if viol else ''}{viol_desc}")
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
                    all_ids.add(uid)
            member_uid = t.get('work_member_uid')
            if member_uid:
                for mid in member_uid.split(','):
                    if mid.strip():
                        all_ids.add(mid.strip())
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
                              classify_items: List[str] = None) -> Tuple[Dict, Dict, Dict, Dict]:
        """并发执行所有大模型评估（人员分类 + 工作任务 + 作业地段 + 站内/站外判断）
        :param skip_work_codes: 需要跳过的 work_code 集合（缓存已命中）
        :param classify_items: 需要大模型判断是否为中文姓名的项
        :return: (task_results, loc_results, lt_results, classify_results)
            - classify_results: {item: is_chinese_name} 或空 dict
        """
        skip_work_codes = skip_work_codes or set()
        classify_items = classify_items or []
        tasks = []
        locations = []
        location_types = []

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
                location_types.append((ticket_key, None))
            else:
                tasks.append((ticket_key, work_task))
                locations.append((ticket_key, work_task))
                location_types.append((ticket_key, work_task))

        if not tasks and not classify_items:
            return {}, {}, {}, {}

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
                    lt_coros = [
                        None if wt is None else self.engine.evaluate_location_type(wt, sem, session)
                        for _, wt in location_types
                    ]
                    classify_coros = [
                        self.engine.is_chinese_name(item, sem, session) for item in classify_items
                    ]

                    # 只并发执行非 None 的协程
                    all_coros = [c for c in (task_coros + loc_coros + lt_coros + classify_coros) if c is not None]
                    if all_coros:
                        return await asyncio.gather(*all_coros)
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

            lt_results = {}
            for i, (key, wt) in enumerate(location_types):
                if wt is not None:
                    lt_results[key] = results[result_idx]
                    result_idx += 1

            # 人员分类结果
            classify_results = {}
            for item in classify_items:
                classify_results[item] = results[result_idx]
                result_idx += 1

            print(f"大模型并发评估完成")
            return task_results, loc_results, lt_results, classify_results
        finally:
            loop.close()

    # ==================== 缓存合并方法 ====================

    def _merge_cached_llm_results(self, llm_results: Dict, loc_results: Dict, lt_results: Dict,
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
            if ticket_key not in lt_results:
                lt_results[ticket_key] = cached.get('llm_location_type', {})
            merged_count += 1

        if empty_count > 0:
            logging.warning(f"[缓存合并] 共合并 {merged_count} 条，其中 {empty_count} 条大模型结果为空！"
                            f"建议删除缓存文件重新运行以获取有效评估结果。")
        print(f"已合并 {merged_count} 条缓存的大模型结果")

    def _extract_new_llm_results(self, new_tickets: List[Dict],
                                  llm_results: Dict, loc_results: Dict, lt_results: Dict,
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
            lt_result = lt_results.get(ticket_key, {})
            new_llm[wc] = {
                'llm_result': llm_result if llm_result is not None else {},
                'llm_location': loc_result,
                'llm_location_type': lt_result,
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
                        all_user_ids.add(uid)
                        all_same_type_ids.add(uid)
                member_uid = t.get('work_member_uid')
                if member_uid:
                    for mid in member_uid.split(','):
                        if mid.strip():
                            all_user_ids.add(mid.strip())
                            all_same_type_ids.add(mid.strip())

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
                    return await asyncio.gather(*task_coros, *loc_coros)

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

        # 安全意识
        safety_score = 0
        for uid_field in ['work_principal_uid', 'guardian_uid']:
            uid = ticket.get(uid_field)
            if uid:
                safety_score += self.engine.calc_person_awareness(peccancy_dict, uid)

        member_uid = ticket.get('work_member_uid')
        if member_uid:
            for mid in member_uid.split(','):
                if mid.strip():
                    safety_score += self.engine.calc_person_awareness(peccancy_dict, mid.strip())

        # 作业总人数
        work_count_score = self.engine.calc_work_count(ticket.get('work_member_count'))

        # 人员性质
        _, nature_score = self.engine.calc_personnel_nature(ticket.get('task_main'))

        # 同类型作业经验
        same_type_score = 0
        if task_type:
            for uid_field in ['work_principal_uid', 'guardian_uid']:
                uid = ticket.get(uid_field)
                if uid and uid in same_type_dict and task_type in same_type_dict[uid]:
                    same_type_score += same_type_dict[uid][task_type]['score']
            if member_uid:
                for mid in member_uid.split(','):
                    if mid.strip() and mid.strip() in same_type_dict and task_type in same_type_dict[mid.strip()]:
                        s = same_type_dict[mid.strip()][task_type]['score']
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
            'principal_nature': '本单位-系统内人员' if ticket.get('task_main') in ['1.0', '本单位'] else '外单位-系统外人员',
            'work_location': ticket.get('work_place', ''),
            'work_type': ticket.get('major_sub_type', ''),
            'plan_nature': '计划性作业',
        }