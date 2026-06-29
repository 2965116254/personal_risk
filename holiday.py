import datetime
from chinese_calendar import is_workday, get_holiday_detail

# 1️⃣ 定义要提取的法定节假日名称映射
target_holidays = {
    "New Year's Day": "元旦",
    "Spring Festival": "春节",
    "Tomb-sweeping Day": "清明",
    "Labour Day": "五一",
    "Dragon Boat Festival": "端午",
    "Mid-autumn Festival": "中秋",
    "National Day": "国庆",
}

def extract_holidays_by_name(start_year: int, end_year: int, target_names: dict):
    """
    按节假日名称分组提取指定范围内的法定节假日日期
    :param start_year: 开始年份
    :param end_year: 结束年份
    :param target_names: 目标节假日映射表 {英文名: 中文名}
    :return: 分组后的节假日字典 {中文名: [日期列表]}
    """
    result = {name: [] for name in target_names.values()}

    for year in range(start_year, end_year + 1):
        start_date = datetime.date(year, 1, 1)
        end_date = datetime.date(year, 12, 31)

        current_date = start_date
        while current_date <= end_date:
            # 判断是否为休息日（包含节假日和周末）
            if not is_workday(current_date):
                is_holiday, holiday_name = get_holiday_detail(current_date)
                if is_holiday and holiday_name in target_names:
                    # 如果命中目标节假日，存入对应的中文名分组
                    cn_name = target_names[holiday_name]
                    result[cn_name].append(current_date)
            current_date += datetime.timedelta(days=1)

    return result

# 2️⃣ 使用示例
current_year = datetime.date.today().year
holiday_groups = extract_holidays_by_name(current_year, current_year, target_holidays)

# 3️⃣ 输出结果
for holiday, dates in holiday_groups.items():
    print(f"\n『{holiday}』共计 {len(dates)} 天")
    for d in dates:
        print(f"  {d.strftime('%Y-%m-%d')} ({d.strftime('%A')})")