import aiohttp
import re
import os
import logging
from config_loader import get_llm_config

# 使用 main.py 统一配置的日志，此处不再重复配置

# 禁用代理（与 TWXH_NEW 一致，避免代理导致无法连接大模型）
os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"
os.environ["HTTP_PROXY"] = ""
os.environ["HTTPS_PROXY"] = ""

# ====================== 工作任务评估 ======================
async def evaluate_work_task_with_llm(work_task, semaphore, session=None):
    async with semaphore:
        try:
            work_task = str(work_task).strip() if work_task else ""
            
            if not work_task:
                return {'score': 0, 'rule': '无', 'keywords': '无'}

            # 工作任务规则
            WORK_TASK_RULES = [
                {'keywords': ['地面', '1.5米以下'], 'score': 0, 'description': '地面以上1.5米以下作业'},
                {'keywords': ['1.5米以上', '5米以下'], 'score': 2, 'description': '1.5米以上5米以下作业'},
                {'keywords': ['5米以上', '15米以下'], 'score': 5, 'description': '5米以上15米以下作业'},
                {'keywords': ['15米以上', '30米以下'], 'score': 7, 'description': '15米以上30米以下作业'},
                {'keywords': ['30米以上'], 'score': 10, 'description': '30米以上高空作业'},
                {'keywords': ['塔', '杆塔', '铁塔', '登塔'], 'score': 5, 'description': '杆塔/铁塔上作业（含登塔、塔上作业）'},
                {'keywords': ['吊装'], 'score': 5, 'description': '大型吊装作业'},
            ]
            
            rules_text = "\n".join([f"{i+1}. {rule['description']}: 关键词={rule['keywords']}, 分值={rule['score']}" 
                                   for i, rule in enumerate(WORK_TASK_RULES)])
            
            prompt = f"""
你是一个工作经验丰富的电力安全风险评估专家。请根据以下工作任务描述，判断该作业是否属于高空作业，并评估其作业高度，根据给定的规则匹配出对应的风险分值。

工作任务：{work_task}

评估规则：
{rules_text}

### 作业高度判断原则（请严格遵循）
1. **基准面定义**：坠落高度基准面是指作业人员可能坠落到的**最低水平面**（通常是地面、楼面或平台面）。
2. **地面/低矮作业**：
   - 作业人员双脚站在地面（或楼板）上，且身体、工具不伸向高处，高度视为**0米**（实际低于1.5米归入此类）。
   - 描述含“地面组装”、“地面整理”、“地脚螺栓”、“基础开挖”等→ 高度 < 1.5m。
3. **杆塔/构架/支架作业**：
   - 描述含“登塔”、“杆塔上”、“构架上”、“横担”、“绝缘子串”、“避雷线”、“金具”等 → 为高空作业。
   - **电压等级推算**（若提及电压等级）：
     - 110kV 杆塔：高度约 15~20 米
     - 220kV 杆塔：高度约 25~30 米
     - 500kV 杆塔：高度约 30~40 米
     - 配电线路（10kV/35kV）：高度约 8~15 米（构架约 5~10 米）
   - 若未提供电压等级，请根据常识（如“高压”、“输电”等词汇）推断，并给出估算依据。
4. **移动升降平台/斗臂车作业**：
   - 描述含“高空作业车”、“升降平台”、“斗臂车”、“绝缘斗” → 高度按平台**升起后**的高度计算，通常取决于作业对象（如线路高度），可根据上下文推测。
5. **临近带电体作业**：
   - 即使站在地面，若身体、工器具可能延伸至高处带电体附近（存在坠落风险），应评估**可能达到的最高点**作为等效作业高度。
6. **屋顶/高处平台作业**：
   - 若在建筑物屋顶作业，基准面为屋顶下方地面，高度按屋顶离地高度（每层约3米，可估算）。
7. **不明确描述**：
   - 如果描述中完全未提及高度信息，请结合“作业对象”或“设备名称”合理推断（如“主变检修”通常在地面或平台，“母线侧刀闸”可能在构架上）。
   - 在答案中必须明确写出“推断的作业高度”和“推断依据”。

### 高度区间与分值映射（请从规则中匹配）
- **地面以上1.5米以下** → 0 分
- **1.5米以上5米以下** → 2 分
- **5米以上15米以下** → 5 分
- **杆塔/铁塔上作业（含登塔、塔上作业）** → 5 分
- **15米以上30米以下** → 7 分
- **30米以上** → 10 分

### 其他高风险作业（需单独加分）
- 出现“吊装”、“起重”、“吊车” → 大型吊装作业，加 5 分
- 若同时命中多项，分值不累加，仅取最大分值（但请确保不重复计算同一风险）。

### 输出格式（必须严格遵守）
请按以下格式输出评估结果（每行一条）：

- 推断的作业高度：[数值] 米（推断依据：[简要说明]）
- 命中规则：[规则描述]
- 命中关键词：[实际命中的关键词]
- 应加分值：[最终总分值]

若未命中任何规则（高度≤1.5m且无吊装），则输出：
- 推断的作业高度：[数值] 米（推断依据：[简要说明]）
- 命中规则：无
- 命中关键词：无
- 应加分值：0
""".strip()

            llm_config = get_llm_config()
            headers = {"Authorization": f"Bearer {llm_config['api_key']}"}
            payload = {
                "model": llm_config['model'],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": llm_config.get('max_tokens_work_task', 8192),
                
            }

            logging.debug(f"[大模型调用] 开始评估工作任务，服务地址: {llm_config['api_base']}, 任务长度: {len(work_task)}, 工作任务: {work_task}")
            
            _owns = session is None
            if _owns:
                session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=llm_config.get('timeout_work_task', 300)))
            try:
                async with session.post(
                    f"{llm_config['api_base']}/chat/completions",
                    json=payload, headers=headers
                ) as resp:
                    if resp.status != 200:
                        logging.warning(f"[大模型-工作任务] HTTP失败 status={resp.status}, 任务: {work_task}")
                        return {'score': 0, 'rule': '转态非200', 'keywords': '无'}
                    
                    j = await resp.json()
                    msg = j.get('choices', [{}])[0].get('message', {}) or {}
                    content = msg.get('content') or msg.get('reasoning') or ''
                    content = content.strip() if content else ''

                    score = 0
                    rule = "无"
                    keywords = "无"
                    inferred_height = ""

                    for line in content.split('\n'):
                        if line and '应加分值' in line:
                            try:
                                score = int(re.search(r'：\[?(\d+)\]?', line).group(1))
                            except:
                                pass
                        elif line and '命中规则' in line:
                            rule = re.split(r'：', line, 1)[-1].strip() if '：' in line else line.strip()
                        elif line and '命中关键词' in line:
                            keywords = re.split(r'：', line, 1)[-1].strip() if '：' in line else line.strip()
                        elif line and '推断的作业高度' in line:
                            inferred_height = re.split(r'：', line, 1)[-1].strip() if '：' in line else line.strip()

                    log_msg = f"[大模型-工作任务] 任务={work_task}, 规则={rule}, 关键词={keywords}, 分值={score}"
                    if inferred_height:
                        log_msg += f", 推断依据={inferred_height}"
                    logging.info(log_msg)
                    logging.debug(f"[大模型-工作任务] 原始响应: {content}")

                    return {'score': score, 'rule': rule, 'keywords': keywords, 'inferred': inferred_height}
            finally:
                if _owns:
                    await session.close()

        except Exception as e:
            logging.error(f"[大模型-工作任务] 异常: {str(e)}, 任务: {work_task}")
            return {'score': 0, 'rule': '无', 'keywords': '无', 'inferred': ''}

# ====================== 作业地段评估 ======================
async def evaluate_work_location_with_llm(work_content, semaphore, session=None):
    async with semaphore:
        try:
            work_content = str(work_content).strip() if work_content else ""
            
            if not work_content:
                return {'score': 0, 'rule': '无', 'keywords': '无'}

            # 作业地段规则
            WORK_LOCATION_RULES = [
                {'keywords': ['无特殊地段'], 'score': 0, 'description': '无特殊地段'},
                {'keywords': ['多回共塔', '带电线路'], 'score': 10, 'description': '作业区段内包含(双)多回共塔带电线路'},
                {'keywords': ['林区'], 'score': 15, 'description': '林区内作业'},
                {'keywords': ['地质隐患'], 'score': 15, 'description': '地质隐患区内作业'},
                {'keywords': ['导地线', '光缆脱落', '重要交叉', '跨铁路', '跨公路', '跨航道'], 'score': 30, 'description': '可能造成导、地线、光缆脱落的作业，区段内包含重要交叉跨越（如跨铁路、公路、航道）'},
            ]
            
            rules_text = "\n".join([f"{i+1}. {rule['description']}: 关键词={rule['keywords']}, 分值={rule['score']}" 
                                   for i, rule in enumerate(WORK_LOCATION_RULES)])
            
            prompt = f"""
请分析以下工作内容，根据给定的规则判断作业地段应添加的风险分值：

工作内容：{work_content}

评估规则：
{rules_text}

特殊地段判断原则（请严格遵循）
优先关键词匹配：根据作业描述中出现的特定关键词或场景，直接命中对应的特殊地段类型。

临近带电体/共塔线路：
描述含“共塔”、“多回”、“同塔”、“邻近带电”、“安全距离不足”、“临近高压线”等 → 属于此类。

林区内作业：
描述含“林区”、“森林”、“树木茂密”、“植被”、“防火林”等 → 属于此类，存在火灾、生物伤害、视线受阻风险。

地质隐患区内作业：
描述含“地质隐患”、“滑坡”、“塌方”、“泥石流”、“不稳定边坡”、“地面沉降”等 → 属于此类。

特殊跨越/交叉作业：
描述含“跨越铁路”、“跨越公路”、“跨越航道”、“交叉跨越”、“光缆脱落”、“导线脱落”等，且作业可能导致导、地线、光缆脱落 → 属于此类。

综合判断：若同时命中多个类型，取最高分值（不累加，因为地段风险通常以最严重者计）。
不确定时：若无法明确判断，视为“无特殊区段”，分值为0，并说明理由。

地段类型与分值映射（请从规则中匹配）
无特殊区段 → 0 分
临近带电体/共塔线路 → 10 分
林区内作业 → 15 分
地质隐患区内作业 → 15 分
特殊跨越/交叉作业 → 30 分

注意：有限空间作业若未明确说明通风监测良好，一律按 10 分处理，并在输出推断依据中注明“默认按最严重情况（设施不完备/有毒有害）”。

### 输出格式（必须严格遵守）
请按以下格式输出评估结果（每行一条）：

推断的特殊地段：[类型名称]（推断依据：[简要说明]）
命中规则：[匹配的规则描述，如“林区内作业 分值15”]
命中关键词：[实际命中的关键词]
应加分值：[最终分值]
若未命中任何特殊地段，则输出：

推断的特殊地段：无特殊区段（推断依据：[简要说明]）
命中规则：无
命中关键词：无
应加分值：0
""".strip()

            llm_config = get_llm_config()
            headers = {"Authorization": f"Bearer {llm_config['api_key']}"}
            payload = {
                "model": llm_config['model'],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": llm_config.get('max_tokens_work_location', 8192),
                
            }

            logging.debug(f"[大模型调用] 开始评估作业地段，服务地址: {llm_config['api_base']}, 内容长度: {len(work_content)}, 工作内容: {work_content}")
            
            _owns = session is None
            if _owns:
                session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=llm_config.get('timeout_work_location', 300)))
            try:
                async with session.post(
                    f"{llm_config['api_base']}/chat/completions",
                    json=payload, headers=headers
                ) as resp:
                    if resp.status != 200:
                        logging.warning(f"[大模型-作业地段] HTTP失败 status={resp.status}, 内容: {work_content}")
                        return {'score': 0, 'rule': '无', 'keywords': '无'}
                    
                    j = await resp.json()
                    msg = j.get('choices', [{}])[0].get('message', {}) or {}
                    content = msg.get('content') or msg.get('reasoning') or ''
                    content = content.strip() if content else ''

                    score = 0
                    rule = "无"
                    keywords = "无"
                    inferred_location = ""

                    for line in content.split('\n'):
                        if line and '应加分值' in line:
                            try:
                                score = int(re.search(r'：\[?(\d+)\]?', line).group(1))
                            except:
                                pass
                        elif line and ('命中规则' in line or '命中地段类型' in line):
                            rule = re.split(r'：', line, 1)[-1].strip() if '：' in line else line.strip()
                        elif line and '命中关键词' in line:
                            keywords = re.split(r'：', line, 1)[-1].strip() if '：' in line else line.strip()
                        elif line and '推断的特殊地段' in line:
                            inferred_location = re.split(r'：', line, 1)[-1].strip() if '：' in line else line.strip()

                    log_msg = f"[大模型-作业地段] 内容={work_content}, 规则={rule}, 关键词={keywords}, 分值={score}"
                    if inferred_location:
                        log_msg += f", 推断依据={inferred_location}"
                    logging.info(log_msg)
                    logging.debug(f"[大模型-作业地段] 原始响应: {content}")

                    return {'score': score, 'rule': rule, 'keywords': keywords, 'inferred': inferred_location}
            finally:
                if _owns:
                    await session.close()

        except Exception as e:
            logging.error(f"[大模型-作业地段] 异常: {str(e)}, 内容: {work_content}")
            return {'score': 0, 'rule': '无', 'keywords': '无', 'inferred': ''}

# ====================== 人员ID类型判断 ======================
async def is_chinese_name_with_llm(user_id, semaphore, session=None):
    async with semaphore:
        try:
            user_id = str(user_id).strip() if user_id else ""
            
            if not user_id:
                return False

            prompt = f"""
你是一个智能身份识别助手。请判断以下字符串是人员的数字ID还是中文姓名。

待判断字符串：{user_id}

判断规则：
1. 数字ID：
   - 只包含数字、字母（大小写）、下划线或短横线，不包含中文字符（如00035236_cgy）
   - 十六进制字符串（如36267D6D655A4ACCA0BD3BF892F824C0）

2. 中文姓名：
   - 包含中文字符，且通常为2-4个汉字（如张三、李四、王小明、欧阳明）
   - 包含姓名的完整字符串（如"张三（公司名）"中的张三）

3. 特殊情况：
   - "（王杰"、"闫茂华）"等不完整的括号内容判定为ID（无效数据）
   - "4人）"、"1人）"等只包含数字和"人"字的判定为ID

请按照以下格式输出：
- 类型：[数字ID/中文姓名/无效信息]
- 理由：[简要说明判断依据]

示例：

输入：4F1C57B3190B4E868E51EA4228343803
输出：
- 类型：数字ID
- 理由：十六进制字符串，不包含中文字符

输入：张三
输出：
- 类型：中文姓名
- 理由：包含2个中文字符，符合姓名特征

输入：王小明
输出：
- 类型：中文姓名
- 理由：包含3个中文字符，符合姓名特征

输入：张三（公司名）
输出：
- 类型：中文姓名
- 理由：包含中文字符"张三"，符合姓名特征，但只需要"张三"这个姓名

输入：（王杰
输出：
- 类型：中文姓名
- 理由：包含中文字符"王杰"，符合姓名特征，但只需要"王杰"这个姓名

输入：4人）
输出：
- 类型：无效信息
- 理由：只包含数字和"人"字，不是姓名，也不是id

输入：国电南瑞南京控制系统有限公司：赵华明
输出：
- 类型：中文姓名
- 理由：包含中文字符"赵华明"，符合姓名特征，但只需要"赵华明"这个姓名
""".strip()

            llm_config = get_llm_config()
            headers = {"Authorization": f"Bearer {llm_config['api_key']}"}
            payload = {
                "model": llm_config['model'],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": llm_config.get('max_tokens_user_id', 2048),
                
            }

            logging.debug(f"[大模型调用] 开始判断人员ID类型，服务地址: {llm_config['api_base']}, ID: {user_id}")
            
            _owns = session is None
            if _owns:
                session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=llm_config.get('timeout_user_id', 60)))
            try:
                async with session.post(
                    f"{llm_config['api_base']}/chat/completions",
                    json=payload, headers=headers
                ) as resp:
                    if resp.status != 200:
                        logging.warning(f"[大模型-人员ID] HTTP失败 status={resp.status}, ID: {user_id}")
                        return False
                    
                    j = await resp.json()
                    msg = j.get('choices', [{}])[0].get('message', {}) or {}
                    content = msg.get('content') or msg.get('reasoning') or ''
                    content = content.strip() if content else ''

                    result_type = "未知"
                    for line in content.split('\n'):
                        if line and '类型' in line:
                            result_type = re.split(r'：', line, 1)[-1].strip() if '：' in line else line.strip()
                            if result_type == '中文姓名':
                                logging.info(f"[大模型-人员ID] ID={user_id}, 结果={result_type}")
                                logging.debug(f"[大模型-人员ID] 原始响应: {content}")
                                return True
                            elif result_type == '数字ID' or result_type == '无效信息':
                                logging.info(f"[大模型-人员ID] ID={user_id}, 结果={result_type}")
                                logging.debug(f"[大模型-人员ID] 原始响应: {content}")
                                return False

                    logging.info(f"[大模型-人员ID] ID={user_id}, 结果={result_type}")
                    logging.debug(f"[大模型-人员ID] 原始响应: {content}")
                    return False
            finally:
                if _owns:
                    await session.close()

        except Exception as e:
            logging.error(f"[大模型-人员ID] 异常: {str(e)}, ID: {user_id}")
            return False

# ====================== 站内/站外判断 ======================
async def evaluate_location_type_with_llm(work_task, semaphore, session=None):
    async with semaphore:
        try:
            work_task = str(work_task).strip() if work_task else ""
            
            if not work_task:
                return {'location_type': '站内作业', 'reason': '未提供工作任务'}

            prompt = f"""
你是一名电力安全工作规程专家，擅长根据工作任务描述判断作业地点是站内还是站外。请阅读以下"工作任务"，判断该作业属于站内作业还是站外线路作业。

工作任务：{work_task}

判断依据：
- 站内作业：作业地点位于建筑实体内部，具备屋顶、墙壁等遮蔽结构（如变电、配电室内作业）
- 站外线路作业：作业地点位于变电站围墙外，属于输电、配电架空线路或电缆线路沿线的工作；作业内容直接涉及线路本体（杆塔、导地线、绝缘子、金具、电缆等）的巡视、检修、施工、拆除或抢险

请按照以下格式输出：
- 判断结果：[站内作业/站外线路作业]
- 判断依据：[简要说明判断理由]

如果无法明确判断，则输出：
- 判断结果：站内作业
- 判断依据：无法明确判断，默认按站内作业处理
""".strip()

            llm_config = get_llm_config()
            headers = {"Authorization": f"Bearer {llm_config['api_key']}"}
            payload = {
                "model": llm_config['model'],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": llm_config.get('max_tokens_station', 2048),
                
            }

            logging.debug(f"[大模型调用] 开始判断站内/站外，服务地址: {llm_config['api_base']}, 任务长度: {len(work_task)}")
            
            _owns = session is None
            if _owns:
                session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=llm_config.get('timeout_station', 60)))
            try:
                async with session.post(
                    f"{llm_config['api_base']}/chat/completions",
                    json=payload, headers=headers
                ) as resp:
                    if resp.status != 200:
                        logging.warning(f"[大模型-站内/站外] HTTP失败 status={resp.status}, 任务: {work_task}")
                        return {'location_type': '站内作业', 'reason': 'API调用失败'}
                    
                    j = await resp.json()
                    msg = j.get('choices', [{}])[0].get('message', {}) or {}
                    content = msg.get('content') or msg.get('reasoning') or ''
                    content = content.strip() if content else ''

                    location_type = "站内作业"
                    reason = "无法明确判断，默认按站内作业处理"

                    for line in content.split('\n'):
                        if line and '判断结果' in line:
                            result = re.split(r'：', line, 1)[-1].strip() if '：' in line else line.strip()
                            if '站外' in result:
                                location_type = '站外线路作业'
                            else:
                                location_type = '站内作业'
                        elif line and '判断依据' in line:
                            reason = re.split(r'：', line, 1)[-1].strip() if '：' in line else line.strip()

                    logging.info(f"[大模型-站内/站外] 任务={work_task}, 结果={location_type}, 依据={reason}")
                    logging.debug(f"[大模型-站内/站外] 原始响应: {content}")

                    return {'location_type': location_type, 'reason': reason}
            finally:
                if _owns:
                    await session.close()

        except Exception as e:
            logging.error(f"[大模型-站内/站外] 异常: {str(e)}, 任务: {work_task}")
            return {'location_type': '站内作业', 'reason': '大模型判断失败，默认按站内作业处理'}

# ====================== 规则判断对比分析 ======================
async def evaluate_rule_judgment_with_llm(detailed_results, semaphore):
    async with semaphore:
        try:
            # 提取有差异的项目
            differences = []
            for detail in detailed_results:
                rule_score = detail.get('风险值得分', 0)
                customer_score = detail.get('客户填入分值', 0)
                if rule_score != customer_score:
                    differences.append({
                        '评估因子': detail.get('评估因子', ''),
                        '评估结果名称': detail.get('评估结果名称', ''),
                        '评估结果': detail.get('评估结果', ''),
                        '规则计算分值': rule_score,
                        '客户填写分值': customer_score
                    })

            if not differences:
                prompt = "请分析以下风险评估结果：\n\n评估项目：\n" + "\n".join([
                    f"- {detail.get('评估因子', '')}: 规则计算分值={detail.get('风险值得分', 0)}分，客户填写分值={detail.get('客户填入分值', 0)}分（两者一致）"
                    for detail in detailed_results
                ]) + "\n\n分析：所有评估项目的规则计算结果与客户填写结果一致，请给出确认说明。"
            else:
                prompt = "请分析以下风险评估结果中规则计算分值与客户填写分值的差异：\n\n"
                prompt += "有差异的评估项目：\n"
                for diff in differences:
                    prompt += f"- 评估因子：{diff['评估因子']}\n"
                    prompt += f"  评估结果名称：{diff['评估结果名称']}\n"
                    prompt += f"  评估结果：{diff['评估结果']}\n"
                    prompt += f"  规则计算分值：{diff['规则计算分值']}分\n"
                    prompt += f"  客户填写分值：{diff['客户填写分值']}分\n"
                    prompt += f"  差异：规则计算分值与客户填写分值不一致\n"

                if len(differences) < len(detailed_results):
                    prompt += "\n无差异的评估项目：\n"
                    for detail in detailed_results:
                        rule_score = detail.get('风险值得分', 0)
                        customer_score = detail.get('客户填入分值', 0)
                        if rule_score == customer_score:
                            prompt += f"- {detail.get('评估因子', '')}: 规则计算分值={rule_score}分，客户填写分值={customer_score}分（一致）\n"

                prompt += "\n请对比分析规则计算结果与客户填写结果，指出不一致的项目，分析可能的原因，并给出建议。"

            llm_config = get_llm_config()
            headers = {"Authorization": f"Bearer {llm_config['api_key']}"}
            payload = {
                "model": llm_config['model'],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": llm_config.get('max_tokens_rule_compare', 1024),
                
            }

            logging.debug(f"[大模型调用] 开始规则判断对比分析，服务地址: {llm_config['api_base']}, 评估项目数: {len(detailed_results)}")
            
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=llm_config.get('timeout_rule_compare', 90))) as session:
                async with session.post(
                    f"{llm_config['api_base']}/chat/completions",
                    json=payload, headers=headers
                ) as resp:
                    if resp.status != 200:
                        logging.warning(f"[大模型-规则对比] HTTP失败 status={resp.status}")
                        return "规则计算结果与客户填写结果一致"
                    
                    j = await resp.json()
                    msg = j.get('choices', [{}])[0].get('message', {}) or {}
                    content = msg.get('content') or msg.get('reasoning') or ''
                    content = content.strip() if content else ''
                    
                    logging.info(f"[大模型-规则对比] 项目数={len(detailed_results)}, 结果={content[:200]}..." if len(content) > 200 else f"[大模型-规则对比] 项目数={len(detailed_results)}, 结果={content}")
                    logging.debug(f"[大模型-规则对比] 原始响应: {content}")
                    
                    return content

        except Exception as e:
            logging.error(f"[大模型-规则对比] 异常: {str(e)}")
            differences = []
            for detail in detailed_results:
                rule_score = detail.get('风险值得分', 0)
                customer_score = detail.get('客户填入分值', 0)
                if rule_score != customer_score:
                    differences.append(f"{detail.get('评估因子', '')}: 规则计算{rule_score}分，客户填写{customer_score}分")

            if differences:
                return "发现以下差异：\n" + "\n".join(differences)
            else:
                return "规则计算结果与客户填写结果一致"