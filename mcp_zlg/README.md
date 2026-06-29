# 风险评估 MCP 服务

## 简介

独立的 MCP (Model Context Protocol) 服务，供大模型/智能体按作业计划编号查询单票风险评分。规则引擎与主项目 v3.2 保持一致。

## 启动方式

```bash
cd mcp_zlg
python mcp_risk_assessment.py
```

MCP 服务默认监听 `0.0.0.0:8766`，使用 `streamable-http` 传输协议。

## 配置

MCP 专属配置在 `mcp_zlg/config.yaml`（host、port、timeout），数据库配置使用主项目 `config/config.yaml` 中的 `database_new`。

## MCP 工具

| 工具名称 | 描述 |
|----------|------|
| `query_risk_all_by_code` | 查询全类风险评分（F=B+C+D） |
| `query_risk_b_by_code` | 查询B类风险评分（人员能力） |
| `query_risk_c_by_code` | 查询C类风险评分（环境时间） |
| `query_risk_d_by_code` | 查询D类风险评分（设备联动） |
| `health_check` | 健康检查 |

## 评估规则

与主项目 v3.2 完全一致，复用 `code/risk_rule_engine.RiskRuleEngine`：

- **B 值**：安全意识（负责人+监护人取最高+班组成员取最高）、作业总人数、人员性质、计划性质
- **C 值**：作业地段（关键词匹配）、作业类型高度（关键词匹配）、作业时段（含法定节假日判断）
- **D 值**：暂未实现（与主项目一致，当前为 0）

注意：MCP 不含大模型，作业地段和作业类型高度使用关键词规则匹配作为替代方案。