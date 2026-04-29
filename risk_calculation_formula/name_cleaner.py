# -*- coding: utf-8 -*-
# @Project ：safety 
# @FileName: name_cleaner.py
# @Author  : greenaut
# @Time    : 2026/2/12 10:54


import re
import mysql.connector
from mysql.connector import Error
import pandas as pd
from typing import List, Set, Optional, Dict, Union

# ------------------- 第三方库可选导入 -------------------
try:
    import jieba.posseg as pseg
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False
    print("警告：jieba 未安装，将跳过词性标注人名识别。安装方法：pip install jieba")

# ------------------- 全局常量配置 -------------------
# 无效关键词黑名单（匹配即剔除）
INVALID_KEYWORDS = {
    '公司', '有限', '集团', '厂', '局', '处', '站', '中心', '研究院', '大学',
    '学院', '学校', '班组', '小组', '部门', '科', '室', '供电', '电力', '电网',
    '电气', '工程', '建设', '安装', '检修', '运维', '调试', '试验', '技术',
    '广东', '北京', '上海', '天津', '重庆', '黑龙江', '吉林', '辽宁', '河北',
    '河南', '山东', '山西', '陕西', '甘肃', '青海', '四川', '贵州', '云南',
    '江苏', '浙江', '安徽', '福建', '江西', '湖南', '湖北', '台湾', '海南',
    '内蒙古', '广西', '西藏', '宁夏', '新疆', '香港', '澳门', '华北', '华东',
    '华南', '华中', '东北', '西北', '西南'
}

# 常见中国姓氏（前400个，可自行扩充）
COMMON_SURNAMES = {
    '赵','钱','孙','李','周','吴','郑','王','冯','陈','褚','卫','蒋','沈','韩','杨',
    '朱','秦','尤','许','何','吕','施','张','孔','曹','严','华','金','魏','陶','姜',
    '戚','谢','邹','喻','柏','水','窦','章','云','苏','潘','葛','奚','范','彭','郎',
    '鲁','韦','昌','马','苗','凤','花','方','俞','任','袁','柳','酆','鲍','史','唐',
    '费','廉','岑','薛','雷','贺','倪','汤','滕','殷','罗','毕','郝','邬','安','常',
    '乐','于','时','傅','皮','卞','齐','康','伍','余','元','卜','顾','孟','平','黄',
    '和','穆','萧','尹','姚','邵','湛','汪','祁','毛','禹','狄','米','贝','明','臧',
    '计','伏','成','戴','谈','宋','茅','庞','熊','纪','舒','屈','项','祝','董','梁',
    '杜','阮','蓝','闵','席','季','麻','强','贾','路','娄','危','江','童','颜','郭',
    '梅','盛','林','刁','钟','徐','邱','骆','高','夏','蔡','田','樊','胡','凌','霍',
    '虞','万','支','柯','昝','管','卢','莫','经','房','裘','缪','干','解','应','宗',
    '丁','宣','贲','邓','郁','单','杭','洪','包','诸','左','石','崔','吉','钮','龚',
    '程','嵇','邢','滑','裴','陆','荣','翁','荀','羊','於','惠','甄','麴','家','封',
    '芮','羿','储','靳','汲','邴','糜','松','井','段','富','巫','乌','焦','巴','弓',
    '牧','隗','山','谷','车','侯','宓','蓬','全','郗','班','仰','秋','仲','伊','宫',
    '宁','仇','栾','暴','甘','钭','厉','戎','祖','武','符','刘','景','詹','束','龙',
    '叶','幸','司','韶','郜','黎','蓟','薄','印','宿','白','怀','蒲','邰','从','鄂',
    '索','咸','籍','赖','卓','蔺','屠','蒙','池','乔','阴','鬱','胥','能','苍','双',
    '闻','莘','党','翟','谭','贡','劳','逄','姬','申','扶','堵','冉','宰','郦','雍',
    '郤','璩','桑','桂','濮','牛','寿','通','边','扈','燕','冀','郏','浦','尚','农',
    '温','别','庄','晏','柴','瞿','阎','充','慕','连','茹','习','宦','艾','鱼','容',
    '向','古','易','慎','戈','廖','庾','终','暨','居','衡','步','都','耿','满','弘',
    '匡','国','文','寇','广','禄','阙','东','欧','殳','沃','利','蔚','越','夔','隆',
    '师','巩','厍','聂','晁','勾','敖','融','冷','訾','辛','阚','那','简','饶','空',
    '曾','毋','沙','乜','养','鞠','须','丰','巢','关','蒯','相','查','后','荆','红',
    '游','竺','权','逯','盖','益','桓','公','万俟','司马','上官','欧阳','夏侯','诸葛',
    '闻人','东方','赫连','皇甫','尉迟','公羊','澹台','公冶','宗政','濮阳','淳于',
    '单于','太叔','申屠','公孙','仲孙','轩辕','令狐','钟离','宇文','长孙','慕容',
    '鲜于','闾丘','司徒','司空','亓官','司寇','仉','督','子车','颛孙','端木','巫马',
    '公西','漆雕','乐正','壤驷','公良','拓跋','夹谷','宰父','谷梁','晋','楚','闫',
    '法','汝','鄢','涂','钦','段干','百里','东郭','南门','呼延','归','海','羊舌',
    '微生','岳','帅','缑','亢','况','后','有','琴','梁丘','左丘','东门','西门','商',
    '牟','佘','佴','伯','赏','南宫','墨','哈','谯','笪','年','爱','阳','佟','覃','麦',
    '苗','凤','太','肖','淳','党','盘','候'
}

# 有效姓名长度范围（常规2~4汉字，少数民族转音可放宽）
MIN_NAME_LEN = 2
MAX_NAME_LEN = 4
MAX_NAME_LEN_WITH_DOT = 6  # 含间隔号

# ------------------- 核心清洗类 -------------------
class NameExtractor:
    """
    人员姓名提取器
    使用前必须初始化并传入数据库配置，自动构建白名单
    """

    def __init__(self, db_config: Dict, auto_build_whitelist: bool = True):
        self.db_config = db_config
        self.whitelist: Set[str] = set()
        if auto_build_whitelist:
            self._build_whitelist()

    def _build_whitelist(self):
        """从数据库构建人员白名单（工作负责人+违章人员）"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            # 工作负责人
            cursor.execute(
                "SELECT DISTINCT work_principal_uname FROM sp_pd_wticket_base "
                "WHERE work_principal_uname IS NOT NULL AND work_principal_uname != ''"
            )
            for (name,) in cursor:
                if self._is_valid_name_basic(name):
                    self.whitelist.add(name.strip())
            # 违章人员
            cursor.execute(
                "SELECT DISTINCT peccancy_uname FROM sp_ss_uq_peccancy_list_log "
                "WHERE peccancy_uname IS NOT NULL AND peccancy_uname != ''"
            )
            for (name,) in cursor:
                if self._is_valid_name_basic(name):
                    self.whitelist.add(name.strip())
            cursor.close()
            conn.close()
            print(f"[NameExtractor] 白名单构建完成，共 {len(self.whitelist)} 人")
        except Error as e:
            print(f"[NameExtractor] 构建白名单失败: {e}")
            self.whitelist = set()

    @staticmethod
    def _is_valid_name_basic(name: str) -> bool:
        """基础姓名验证（用于白名单构建）"""
        if not name or not isinstance(name, str):
            return False
        name = name.strip()
        if len(name) < MIN_NAME_LEN or len(name) > MAX_NAME_LEN:
            return False
        # 只允许中文和间隔号
        return bool(re.fullmatch(r'[\u4e00-\u9fa5·]{2,4}', name))

    def _contains_invalid_keyword(self, text: str) -> bool:
        """检查是否包含无效关键词"""
        for kw in INVALID_KEYWORDS:
            if kw in text:
                return True
        return False

    def _is_valid_name_strict(self, name: str) -> bool:
        """
        严格的人名验证规则（用于启发式结果）
        1. 基本格式校验
        2. 首字必须是常见姓氏
        3. 不能包含无效关键词
        """
        name = name.strip()
        # 长度校验（带间隔号放宽）
        if '·' in name or '·' in name:
            if len(name) > MAX_NAME_LEN_WITH_DOT:
                return False
        else:
            if not (MIN_NAME_LEN <= len(name) <= MAX_NAME_LEN):
                return False
        # 字符组成：仅中文、间隔号
        if not re.fullmatch(r'[\u4e00-\u9fa5·]+', name):
            return False
        # 首字姓氏校验（排除非姓氏开头的短词）
        first_char = name[0]
        if first_char not in COMMON_SURNAMES:
            return False
        # 无效关键词过滤
        if self._contains_invalid_keyword(name):
            return False
        return True

    # ---------- 三种提取策略 ----------
    def _extract_by_whitelist(self, text: str) -> Set[str]:
        """策略1：白名单匹配（优先）"""
        found = set()
        if not self.whitelist:
            return found
        # 按长度降序，避免子串误配（如“张”先于“张三”被匹配）
        sorted_names = sorted(self.whitelist, key=len, reverse=True)
        for name in sorted_names:
            if name in text:
                found.add(name)
        return found

    def _extract_by_jieba(self, text: str) -> Set[str]:
        """策略2：jieba 词性标注识别人名"""
        found = set()
        if not JIEBA_AVAILABLE or not text.strip():
            return found
        try:
            words = pseg.cut(text)
            for word, flag in words:
                if flag.startswith('nr') and MIN_NAME_LEN <= len(word) <= MAX_NAME_LEN:
                    # 初步过滤：排除含无效关键词的
                    if not self._contains_invalid_keyword(word):
                        found.add(word.strip())
        except Exception as e:
            print(f"jieba 识别出错: {e}")
        return found

    def _extract_by_rules(self, text: str) -> Set[str]:
        """
        策略3：增强的启发式规则（原extract_names_from_text的改进版）
        使用更严谨的正则 + 严格验证
        """
        found = set()
        if not text:
            return found

        cleaned = str(text)
        # 1. 将括号替换为分隔符（中文逗号），既保留内部文字，又避免与前后文合并
        cleaned = re.sub(r'[（）()]', '，', cleaned)

        # 2. 移除括号内全部内容？——不再执行，已改为只删括号符号

        # 3. 移除公司、部门前缀（冒号前内容）
        cleaned = re.sub(r'[^:：]*[:：]', '', cleaned)
        # 4. 移除“第X小组”类标识
        cleaned = re.sub(r'第[0-9零一二三四五六七八九十百千万]+小组', '', cleaned)
        cleaned = re.sub(r'小组', '', cleaned)

        # 5. 分隔符切分
        separators = r'[;；、，,\s]'  # 注意：括号字符已被移除，分隔符不再包含括号
        parts = re.split(separators, cleaned)

        for part in parts:
            part = part.strip()
            if not part or len(part) < 2:
                continue
            # 提取连续2~4个汉字（带间隔号可更长）
            candidates = re.findall(r'[\u4e00-\u9fa5]{2,4}(?:[·][\u4e00-\u9fa5]{1,3})?', part)
            for cand in candidates:
                if self._is_valid_name_strict(cand):
                    found.add(cand)

        return found

    # ---------- 对外接口 ----------
    def extract_names(self, text: Union[str, None]) -> List[str]:
        """
        综合提取人名，返回去重后的姓名列表
        优先级：白名单 > jieba > 启发式规则
        """
        if pd.isna(text) or text is None:
            return []
        text = str(text)

        # ========== 【统一处理】将括号替换为分隔符，保留内部文字并独立参与切分 ==========
        text = re.sub(r'[（）()]', '，', text)

        # 各策略结果合并
        result = set()

        # 1. 白名单
        whitelist_names = self._extract_by_whitelist(text)
        result.update(whitelist_names)

        # 2. 从剩余文本中继续提取（避免重复匹配）
        remaining = text
        for name in whitelist_names:
            remaining = remaining.replace(name, '')

        # 3. jieba 辅助
        if remaining.strip():
            jieba_names = self._extract_by_jieba(remaining)
            # jieba 结果也需要白名单校验（若已存在于白名单直接通过）
            for name in jieba_names:
                if name in self.whitelist or self._is_valid_name_strict(name):
                    result.add(name)

        # 4. 启发式规则兜底（仅对剩余文本）
        if remaining.strip():
            rule_names = self._extract_by_rules(remaining)
            for name in rule_names:
                # 避免与之前结果重复
                if name not in result:
                    result.add(name)

        # 最终排序输出
        return sorted(result, key=lambda x: (len(x), x))

# ------------------- 简易函数接口（向后兼容） -------------------
_global_extractor: Optional[NameExtractor] = None
_initialized = False

def init_name_extractor(db_config: Dict) -> NameExtractor:
    """显式初始化提取器（仅第一次有效）"""
    global _global_extractor, _initialized
    if not _initialized:
        _global_extractor = NameExtractor(db_config)
        _initialized = True
    return _global_extractor

def get_name_extractor() -> NameExtractor:
    """获取全局提取器（必须先初始化）"""
    if _global_extractor is None:
        raise RuntimeError("NameExtractor 尚未初始化，请先调用 init_name_extractor")
    return _global_extractor

def clean_worker_names(text: str) -> List[str]:
    """快速清洗函数（依赖全局提取器）"""
    return get_name_extractor().extract_names(text)

# ------------------- 单元测试/使用示例 -------------------
if __name__ == "__main__":
    # 测试数据（模拟文本）
    test_texts = [
        "工作负责人：张三；成员：李四、王五（厂家技术人员），广东电网：赵六，第01小组：钱七",
        "许继电气股份有限公司：周八，成员：吴九（调试）",
        "孙十（保护班）",
        "广东",
        "abc",
        "周家俊（厂家技术人员）",
        "（周家俊）。",
    ]

    # 此处应替换为真实数据库配置（演示用）
    demo_db_config = {
        'host': '192.168.176.229',
        'port': 23306,
        'user': 'root',
        'password': 'hyetec@2025_personal_risk',
        'database': 'personal_risk_db'
    }

    # 初始化提取器（实际使用时只需一次）
    extractor = init_name_extractor(demo_db_config)

    for text in test_texts:
        names = extractor.extract_names(text)
        print(f"原文: {text}")
        print(f"提取: {names}\n")