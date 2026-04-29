# 个人风险防控算法 - 风险评估模块 v1.1

## 项目简介

本项目是个人风险防控算法的风险评估模块，用于对电力作业工作票进行风险评估，计算作业人员能力风险值(B)、作业环境和时间影响风险值(C)、电网设备风险联动值(D)，并综合计算总风险值(F)。

## 功能特性

- **风险评估计算**：支持规则B(人员能力)、规则C(环境时间)、规则D(设备联动)的风险评估
- **定时任务调度**：支持按配置的时间自动执行风险评估
- **API 服务**：提供 RESTful API 接口供外部系统调用
- **MCP 服务**：提供 MCP (Model Context Protocol) 服务供大模型调用
- **结果输出**：支持将评估结果导出为 Excel 文件
- **文件上传**：支持将结果文件上传到 MinIO
- **消息通知**：支持通过 elink 发送消息通知

## 技术栈

- **语言**：Python 3.8+
- **框架**：FastAPI、APScheduler
- **数据库**：MySQL
- **文件存储**：MinIO
- **Excel处理**：openpyxl
- **MCP服务**：fastmcp

## 目录结构

```
risk_calculation_formulav1.1/
├── config/              # 配置文件目录
│   └── config.yaml      # 主配置文件
├── log/                 # 日志目录（自动生成）
├── output/              # 输出目录（自动生成）
├── api.py               # API 服务入口
├── mcp_risk_server.py   # MCP 服务入口
├── main.py              # 风险评估主函数
├── new_rule.py          # 定时任务调度器
├── calculators.py       # 风险计算核心模块
├── risk_rules.py        # 风险评估规则定义
├── config_loader.py     # 配置加载模块
├── sql_queries.py       # SQL 查询语句定义
├── elink_client.py      # elink 客户端
├── requirements.txt     # 依赖列表
└── Dockerfile           # Docker 构建文件
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置文件

编辑 `config/config.yaml`，配置数据库连接、MinIO、elink 等参数：

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

# 查询时间范围配置
query_time_range:
  mode: "3month"  # fixed | 1month | 3month | 6month | 1year | custom
```

### 3. 启动方式

#### 方式一：定时任务模式（推荐）

```bash
python new_rule.py
```

#### 方式二：单次执行

```bash
python main.py
```

#### 方式三：API 服务

```bash
python api.py
```

#### 方式四：MCP 服务

```bash
python mcp_risk_server.py
```

## API 接口

### 基础路径：`/api/risk`

| 接口 | 方法 | 描述 |
|------|------|------|
| `/api/risk/calculate` | GET | 计算所有风险值 |
| `/api/risk/B` | GET | 计算规则B（人员能力风险） |
| `/api/risk/C` | GET | 计算规则C（环境时间风险） |
| `/api/risk/D` | GET | 计算规则D（设备联动风险） |
| `/api/health` | GET | 健康检查 |

### 示例请求

```bash
# 获取所有风险评估结果
curl http://localhost:8080/api/risk/calculate

# 获取规则B评估结果
curl http://localhost:8080/api/risk/B?limit=10

# 获取规则C评估结果（指定日期范围）
curl "http://localhost:8080/api/risk/C?start_date=2026-01-01&end_date=2026-04-30"
```

## MCP 工具

MCP 服务提供以下工具函数供大模型调用：

| 工具名称 | 描述 |
|----------|------|
| `query_risk_all` | 查询全类风险评分 |
| `query_risk_b` | 查询B类风险评分 |
| `query_risk_c` | 查询C类风险评分 |
| `query_risk_d` | 查询D类风险评分 |
| `calculate_safety_awareness` | 计算安全意识评分 |
| `calculate_work_count` | 计算作业总人数评分 |
| `calculate_personnel_nature` | 计算人员性质评分 |
| `calculate_experience` | 计算作业经验评分 |
| `calculate_work_hours` | 计算单日持续作业时长评分 |
| `calculate_plan_nature` | 计算计划性质评分 |
| `calculate_time_period` | 计算作业时段评分 |
| `calculate_weather` | 计算天气评分 |
| `calculate_mental_state` | 计算精神状态评分 |
| `calculate_key_station` | 计算关键重要站点评分 |
| `calculate_accident_consequence` | 计算事故后果评分 |
| `calculate_equipment_risk` | 计算设备风险评分 |
| `health_check` | 健康检查 |

## 风险评估规则

### 规则B - 作业人员能力风险值

| 评估因子 | 评分规则 |
|----------|----------|
| 安全意识 | A类违章6分，B类5分，C类3分，D类≥3次2分，D类<3次0分 |
| 作业总人数 | ≥50人15分，24-49人8分，16-23人5分，8-15人3分，5-7人1分，<5人0分 |
| 人员性质 | 外施工单位劳务分包8分，外施工单位5分，本单位0分 |
| 同类型作业次数 | 第一次6分，不足3次5分，3-4次3分，5次及以上2分 |
| 计划性质 | 计划性0分，提前一日临时10分，当日临时20分 |

### 规则C - 作业环境和时间影响风险值

| 评估因子 | 评分规则 |
|----------|----------|
| 作业地段 | 有限空间(完备)3分，有限空间(不完备)10分，氧气不足999分，多回共塔10分，林区15分，地质隐患15分 |
| 作业类型 | 1.5米以下0分，1.5-5米2分，5-15米5分，15-30米7分，30米以上10分 |
| 天气 | 舒适0分，小雨10分，预警信号10分，雷雨大风0分(禁止) |
| 作业时段 | 正常时段0分，二级保供电5分，夜间作业20分，特级保供电30分 |
| 持续作业时长 | ≤4小时0分，4-8小时2分，8-12小时10分，>12小时20分 |
| 关键重要站点 | 是5分，否0分 |

### 规则D - 电网、设备风险联动值

| 评估因子 | 评分规则 |
|----------|----------|
| 事故后果 | 四级及以下0分，三级10分，二级40分，一级160分，一般事故180分，较大事故200分 |
| 设备风险 | 保护装置定检45分，带电水冲洗140分，热倒母90分，隔离开关70分，状态异常70分 |

### 风险等级判定

| 总分范围 | 风险等级 |
|----------|----------|
| 0-20 | 可接受 |
| 21-70 | 低 |
| 71-200 | 中 |
| 201-400 | 高 |
| >400 | 特高 |

## 配置说明

### 查询时间范围模式

| 模式 | 说明 |
|------|------|
| `fixed` | 使用固定日期（需配置 start_date 和 end_date） |
| `1month` | 近一个月 |
| `3month` | 近三个月 |
| `6month` | 近半年 |
| `1year` | 近一年 |
| `custom` | 自定义日期范围 |

### 人员过滤配置

可配置过滤词过滤特定人员（如吊车、厂家、公司、单位、司机、指挥）。

## 许可证

本项目为内部项目，仅供内部使用。

## 联系方式

如有问题，请联系项目负责人。
