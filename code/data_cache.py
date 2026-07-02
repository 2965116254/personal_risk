# -*- coding: utf-8 -*-
"""
增量数据缓存模块
每日将已处理的工作票及其大模型评估结果缓存到 JSON 文件中。
下次运行时自动对比，只对新数据调用大模型，减少模型调用时间。
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import glob
from datetime import datetime, timedelta
from typing import List, Dict, Set, Tuple, Optional

# 缓存目录（项目根目录下的 cache/）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(BASE_DIR, "cache")


class DataCache:
    """增量数据缓存，基于 JSON 文件存储"""

    def __init__(self, cache_dir: str = None):
        self.cache_dir = cache_dir or CACHE_DIR
        os.makedirs(self.cache_dir, exist_ok=True)

    # ==================== 缓存文件路径 ====================

    def _get_cache_file(self, date_str: str) -> str:
        """获取指定日期的缓存文件路径"""
        return os.path.join(self.cache_dir, f"processed_{date_str}.json")

    def _get_all_cache_files(self) -> List[str]:
        """获取所有缓存文件路径（按日期排序）"""
        files = glob.glob(os.path.join(self.cache_dir, "processed_*.json"))
        files.sort()
        return files

    # ==================== 加载缓存 ====================

    def load_all_cache(self) -> Dict[str, Dict]:
        """
        加载所有历史缓存数据
        :return: {work_code: {llm_result, llm_location, llm_location_type, date}, ...}
        """
        all_cache = {}
        for filepath in self._get_all_cache_files():
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                date_str = data.get("date", "")
                records = data.get("records", {})
                for work_code, record in records.items():
                    record["date"] = date_str
                    all_cache[work_code] = record
            except (json.JSONDecodeError, KeyError, IOError) as e:
                print(f"警告: 读取缓存文件 {filepath} 失败: {e}，将自动删除该损坏文件")
                try:
                    os.remove(filepath)
                except OSError:
                    pass
        print(f"已加载 {len(all_cache)} 条历史缓存记录")
        return all_cache

    def get_processed_work_codes(self) -> Set[str]:
        """获取所有已处理过的 work_code 集合"""
        return set(self.load_all_cache().keys())

    def load_all_user_id_types(self, filter_user_ids: Set[str] = None) -> Dict[str, bool]:
        """
        加载所有历史缓存中的人员ID类型判断结果
        :param filter_user_ids: 可选，只加载该集合内的人员ID类型，减少内存占用
        :return: {user_id: is_chinese_name}，True=中文姓名，False=数字ID
        """
        all_types = {}
        for filepath in self._get_all_cache_files():
            if filter_user_ids is not None and not filter_user_ids:
                break
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                user_id_types = data.get("user_id_types", {})
                if filter_user_ids is not None:
                    filtered = {uid: user_id_types[uid] for uid in user_id_types if uid in filter_user_ids}
                    all_types.update(filtered)
                else:
                    all_types.update(user_id_types)
            except (json.JSONDecodeError, KeyError, IOError) as e:
                print(f"警告: 读取缓存文件 {filepath} 的人员ID类型失败: {e}，将自动删除该损坏文件")
                try:
                    os.remove(filepath)
                except OSError:
                    pass
        print(f"已加载 {len(all_types)} 条人员ID类型缓存")
        return all_types

    # ==================== 增量对比 ====================

    def find_new_tickets(self, work_tickets: List[Dict]) -> Tuple[List[Dict], Dict[str, Dict]]:
        """
        对比缓存，找出新增的工作票（按需加载，只保留当前批次需要的记录，避免全量缓存堆积内存）
        :param work_tickets: 当前查询到的所有工作票
        :return: (new_tickets, cached_llm_results)
            - new_tickets: 需要大模型评估的新票
            - cached_llm_results: 缓存中已有的大模型结果 {work_code: {llm_result, llm_location, llm_location_type}}
        """
        # 当前批次需要的 work_code 集合
        current_codes = {t.get("work_code", "") for t in work_tickets if t.get("work_code")}
        if not current_codes:
            return list(work_tickets), {}

        cached_llm_results = {}
        hit_codes = set()

        for filepath in self._get_all_cache_files():
            if not current_codes:
                break
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                records = data.get("records", {})
                for wc in records:
                    if wc in current_codes and wc not in hit_codes:
                        rec = records[wc]
                        cached_llm_results[wc] = {
                            "llm_result": rec.get("llm_result", ""),
                            "llm_location": rec.get("llm_location", ""),
                            "llm_location_type": rec.get("llm_location_type", ""),
                        }
                        hit_codes.add(wc)
            except (json.JSONDecodeError, KeyError, IOError) as e:
                print(f"警告: 读取缓存文件 {filepath} 失败: {e}，将自动删除该损坏文件")
                try:
                    os.remove(filepath)
                except OSError:
                    pass

        new_tickets = []
        for ticket in work_tickets:
            wc = ticket.get("work_code", "")
            if not wc or wc not in hit_codes:
                new_tickets.append(ticket)

        print(f"增量对比: 共 {len(work_tickets)} 条，"
              f"缓存命中 {len(cached_llm_results)} 条，"
              f"新增 {len(new_tickets)} 条需要大模型评估")
        return new_tickets, cached_llm_results

    # ==================== 保存缓存 ====================

    def save_cache(self, date_str: str, llm_results: Dict[str, Dict],
                   user_id_types: Dict[str, bool] = None) -> str:
        """
        保存当天的大模型评估结果到缓存文件
        :param date_str: 日期字符串，格式 YYYY-MM-DD
        :param llm_results: {work_code: {llm_result, llm_location, llm_location_type}, ...}
        :param user_id_types: {user_id: is_chinese_name}，人员ID类型判断结果
        :return: 缓存文件路径
        """
        if not llm_results and not user_id_types:
            print(f"没有新数据需要缓存 ({date_str})")
            return ""

        filepath = self._get_cache_file(date_str)

        # 先加载当天已有的缓存文件（支持同一天多次运行，合并而非覆盖）
        existing_records = {}
        existing_user_id_types = {}
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
                existing_records = existing.get("records", {})
                existing_user_id_types = existing.get("user_id_types", {})
            except (json.JSONDecodeError, IOError) as e:
                print(f"警告: 读取当天缓存文件失败，将重新创建: {e}")

        # 合并 records（新数据覆盖旧数据，同 work_code 以最新为准）
        merged_records = dict(existing_records)
        merged_records.update(llm_results)

        # 合并 user_id_types（新数据覆盖旧数据）
        merged_user_id_types = dict(existing_user_id_types)
        if user_id_types:
            merged_user_id_types.update(user_id_types)

        cache_data = {
            "date": date_str,
            "records": merged_records,
        }
        if merged_user_id_types:
            cache_data["user_id_types"] = merged_user_id_types

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)

        new_count = len(llm_results) + (len(user_id_types) if user_id_types else 0)
        total_count = len(merged_records) + len(merged_user_id_types)
        print(f"缓存已保存: {filepath} (本次新增 {new_count} 条，累计 {total_count} 条)")
        return filepath

    # ==================== 工具方法 ====================

    def get_today_str(self) -> str:
        """获取今天的日期字符串"""
        return datetime.now().strftime("%Y-%m-%d")

    def get_date_range_str(self, days: int = 30) -> Tuple[str, str]:
        """获取最近 N 天的日期范围字符串"""
        today = datetime.now().date()
        start = today - timedelta(days=days)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")

    def get_cache_stats(self) -> Dict:
        """获取缓存统计信息"""
        files = self._get_all_cache_files()
        total = 0
        for filepath in files:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                total += len(data.get("records", {}))
            except Exception:
                pass
        return {
            "file_count": len(files),
            "total_records": total,
            "cache_dir": self.cache_dir,
        }

    def clean_old_cache(self, keep_days: int = 30):
        """清理超过 keep_days 天的旧缓存文件（与查询窗口匹配，默认30天）"""
        cutoff = (datetime.now() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        today_str = self.get_today_str()
        for filepath in self._get_all_cache_files():
            filename = os.path.basename(filepath)
            date_str = filename.replace("processed_", "").replace(".json", "")
            # 保留当天文件（同一天多次运行场景）
            if date_str >= today_str:
                continue
            if date_str < cutoff:
                os.remove(filepath)
                print(f"已清理过期缓存: {filepath}")

    @staticmethod
    def clean_old_logs(log_dir: str = None, keep_days: int = 7):
        """
        清理超过 keep_days 天的旧日志文件
        日志文件名格式: risk_calculation_YYYYMMDD_HHMMSS.log
        :param log_dir: 日志目录，默认使用项目根目录下的 log/
        :param keep_days: 保留天数，默认7天
        """
        if log_dir is None:
            log_dir = os.path.join(BASE_DIR, "log")
        if not os.path.isdir(log_dir):
            return

        import re
        from datetime import datetime as dt
        cutoff = dt.now() - timedelta(days=keep_days)
        pattern = re.compile(r'^risk_calculation_(\d{8})_\d{6}\.log$')

        count = 0
        for filename in os.listdir(log_dir):
            match = pattern.match(filename)
            if not match:
                continue
            try:
                file_date = dt.strptime(match.group(1), "%Y%m%d")
                if file_date < cutoff:
                    filepath = os.path.join(log_dir, filename)
                    os.remove(filepath)
                    count += 1
            except ValueError:
                continue

        if count > 0:
            print(f"已清理 {count} 个过期日志文件（{keep_days}天前）")

    @staticmethod
    def clean_old_outputs(output_dir: str = None, keep_days: int = 7):
        """
        清理超过 keep_days 天的旧 Excel 输出文件
        文件名格式: 数智问安-风险评估审核-YYYY-MM-DD_HHMMSS.xlsx
        :param output_dir: 输出目录，默认使用项目根目录下的 output/
        :param keep_days: 保留天数，默认7天
        """
        if output_dir is None:
            output_dir = os.path.join(BASE_DIR, "output")
        if not os.path.isdir(output_dir):
            return

        import re
        from datetime import datetime as dt
        cutoff = dt.now() - timedelta(days=keep_days)
        pattern = re.compile(r'^数智问安-风险评估审核-(\d{4}-\d{2}-\d{2})_\d{6}\.xlsx$')

        count = 0
        for filename in os.listdir(output_dir):
            match = pattern.match(filename)
            if not match:
                continue
            try:
                file_date = dt.strptime(match.group(1), "%Y-%m-%d")
                if file_date < cutoff:
                    filepath = os.path.join(output_dir, filename)
                    os.remove(filepath)
                    count += 1
            except ValueError:
                continue

        if count > 0:
            print(f"已清理 {count} 个过期Excel文件（{keep_days}天前）")