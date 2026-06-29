# 个人风险防控算法 - 风险评估模块 v3.2

## 项目简介

本项目是个人风险防控算法的风险评估模块，用于对电力作业工作票进行风险评估。系统通过规则引擎 + 大模型（LLM）双重评估，计算作业人员能力风险值(B)、作业环境和时间影响风险值(C)、电网设备风险联动值(D)，并综合计算总风险值(F)，最终生成包含问题描述和违章信息的 Excel 评估报告。

## 功能特性

- **风险评估计算**：支持规则B(人员能力)、规则C(环境时间)、规则D(设备联动)的风险评估
- **大模型智能评估**：通过 LLM 对工作任务（高空作业高度）、作业地段（有限空间/多回共塔等）、站内/站外判断、人员ID类型分类进行智能评估
- **增量缓存机制**：每日缓存 LLM 评估结果，后续运行自动跳过已评估的工作票，大幅减少模型调用时间
- **日预计算任务**：凌晨自动执行含 LLM 的完整评估并缓存结果，日间定时任务直接复用缓存
- **定时任务调度**：支持 9:00/18:00 定时评估 + 凌晨预计算，基于 APScheduler
- **MCP 服务**：提供独立的 MCP (Model Context Protocol) 服务供大模型/智能体按单票查询风险评分
- **结果输出**：生成包含风险分值、风险等级、问题描述、违章代码/条款的 Excel 报告
- **文件上传**：支持将评估结果上传到 MinIO
- **消息通知**：支持通过 elink 发送文件通知
- **测试工具**：支持按指定作业计划编号列表进行批量评估测试

## 技术栈

- **语言**：Python 3.10+
- **数据库**：MySQL (mysql-connector-python)
- **大模型**：OpenAI 兼容 API (aiohttp 异步调用，Semaphore 并发控制)
- **定时调度**：APScheduler
- **文件存储**：MinIO
- **Excel处理**：openpyxl
- **MCP服务**：fastmcp
- **节假日判断**：chinese_calendar
- **容器化**：Docker

## 目录结构

```
risk_calculation_formulav3.2/
├── code/                    # 核心代码（重构后模块化）
│   ├── main.py              # 风险评估主入口（含 MinIO上传、elink发送）
│   ├── new_rule.py          # 定时任务调度器（含日预计算任务）
│   ├── risk_assessor.py     # 风险评估编排层（主流程编排、并发LLM评估）
│   ├── risk_rule_engine.py  # 风险规则引擎（所有评分规则 + 工具方法）
│   ├── data_fetcher.py      # 数据库查询层（操作票、违章、动态风险、基准关系等）
│   ├── data_cache.py        # 增量缓存模块（LLM结果缓存、自动清理）
│   └── excel_exporter.py    # Excel输出层（含富文本标红、美化）
├── config/                  # 配置文件目录
│   └── config.yaml          # 主配置文件
├── mcp_zlg/                 # 独立 MCP 服务模块
│   ├── mcp_risk_assessment.py  # MCP 服务（按单票查询风险评估）
│   ├── config.yaml          # MCP 配置文件
│   └── requirements.txt     # MCP 依赖列表
├── test/                    # 测试目录
│   ├── test_problem_description.py  # 问题描述测试脚本
│   ├── data.json            # 测试用作业计划编号
│   ├── data.txt             # 测试数据
│   └── data.py              # 测试数据
├── cache/                   # 缓存目录（LLM评估结果，自动生成）
├── log/                     # 日志目录（自动生成）
├── output/                  # 输出目录（Excel文件，自动生成）
├── ai_client.py             # 大模型客户端（异步调用、prompt模板）
├── config_loader.py         # 配置加载模块
├── sql_queries.py           # SQL 查询语句定义
├── elink_client.py          # elink 消息/文件发送客户端
├── holiday.py               # 法定节假日提取工具
├── requirements.txt         # 依赖列表
├── Dockerfile               # Docker 构建文件
└── fxpg.sql                 # 数据库初始化 SQL
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置文件

编辑 `config/config.yaml`，配置数据库连接、MinIO、elink、LLM 等参数：

```yaml
# 数据库配置
database_new:
  host: "your-db-host"
  port: 3306
  user: "your-db-user"
  password: "your-db-password"
  database: "your-db-name"

# MinIO 配置
minio:
  endpoint: "your-minio-endpoint"
  access_key: "your-access-key"
  secret_key: "your-secret-key"
  bucket_name: "your-bucket-name"

# 定时任务配置
schedule:
  times:
    - hour: 9
      minute: 0
    - hour: 18
      minute: 0

# 日预计算任务配置
daily_precalc:
  enabled: true
  hour: 2        # 凌晨2:00执行
  minute: 0

# 查询年份配置
query_year_enabled: true
query_year: 2026
query_start_month: 5
query_start_day: 17
query_end_month: 6
query_end_day: 17

# 大模型配置
llm:
  api_base: "http://your-llm-api/v1"
  api_key: "your-api-key"
  model: "your-model"
  max_concurrent: 10    # 最大并发调用数（建议10-15）
```

### 3. 启动方式

#### 方式一：定时任务模式（推荐生产环境）

```bash
python code/new_rule.py
```

包含 9:00/18:00 定时评估 + 凌晨 2:00 日预计算。

#### 方式二：单次执行

```bash
python code/main.py
```

执行一次完整的风险评估流程（含 LLM 评估），导出 Excel 并上传/发送。

#### 方式三：MCP 服务

```bash
cd mcp_zlg && python mcp_risk_assessment.py
```

启动独立的 MCP 服务，供智能体/大模型按单票查询风险评分。

#### 方式四：测试模式

```bash
python test/test_problem_description.py
```

从 `test/data.json` 读取作业计划编号列表，批量评估并生成问题描述 Excel。

## 风险评估规则

### 规则B - 作业人员能力风险值

| 评估因子 | 评分规则 |
|----------|----------|
| 安全意识 | A类违章6分，B类5分，C类3分，D类≥3次2分，D类<3次0分 |
| 作业总人数 | ≥50人15分，24-49人8分，16-23人5分，8-15人3分，5-7人1分，<5人0分 |
| 人员性质 | 本单位0分，总包单位作业3分，外单位5分 |
| 计划性质 | 计划性0分，提前一日临时10分，当日临时20分 |

### 规则C - 作业环境和时间影响风险值

| 评估因子 | 评分规则 |
|----------|----------|
| 作业地段 | 由大模型根据工作内容判断（有限空间/Multi-回共塔/林区/地质隐患等） |
| 作业类型（高度） | 由大模型根据工作任务判断（地面~30米以上，含杆塔/吊装等特殊场景） |
| 动火作业 | 关联动火作业票额外 +5分 |
| 作业时段 | 正常0分，室内夜间20分，站外夜间20分，法定节假日30分 |
| 关键重要站点 | 是5分，否0分 |

### 规则D - 电网、设备风险联动值

| 评估因子 | 评分规则 |
|----------|----------|
| 事故后果 | 四级及以下0分，三级10分，二级40分，一级160分 |
| 设备风险 | 保护装置定检45分，带电水冲洗140分，热倒母90分，隔离开关70分，状态异常70分 |

### 风险等级判定

| 总分范围 | 风险等级 |
|----------|----------|
| 0-20 | 可接受 |
| 21-70 | 低 |
| 71-200 | 中 |
| 201-400 | 高 |
| >400 | 特高 |

## MCP 工具（mcp_zlg 模块）

| 工具名称 | 描述 |
|----------|------|
| `query_risk_all_by_code` | 查询全类风险评分（F=B+C+D） |
| `query_risk_b_by_code` | 查询B类风险评分（人员能力） |
| `query_risk_c_by_code` | 查询C类风险评分（环境时间） |
| `query_risk_d_by_code` | 查询D类风险评分（设备联动） |
| `health_check` | 健康检查 |

## 配置说明

### 查询时间范围

支持两种模式（可同时启用）：

| 配置项 | 说明 |
|--------|------|
| `query_year_enabled` | 按年份+月份范围查询计划开始时间 |
| `query_time_range` | 按固定模式（1month/3month/6month/1year）过滤已结束计划 |

### 测试模式

```yaml
test_mode: true        # 启用后限制查询数量
query_limit: 50        # 测试模式下最大查询记录数
```

### 人员过滤配置

- `filter.bracket_filter_words`：括号内容过滤词，清除人员ID中括号内的角色描述

### 日预计算任务

凌晨自动执行完整评估（含 LLM），缓存结果。日间 9:00/18:00 定时任务直接复用缓存，无需重新调用大模型。

## Docker 部署

```bash
docker build -t risk-calculation:v3.2 .
docker run -d -v /path/to/config:/app/config risk-calculation:v3.2
```

## 许可证

本项目为内部项目，仅供内部使用。

## 联系方式

如有问题，请联系项目负责人。