# 工作记录

*华生完成的工作日志*

## 2025-01-27
- Git Repository Setup - 已完成
- Telegram Access Issue - 添加allowlist配置
- Notes & Lists Created - 创建待办清单和点子清单

## 2026-01-28
- Doctor Operation Impact - 诊断并记录配置问题
- Model Performance & Requirements - 记录模型性能问题

## 2026-01-29
### postgres-query skill 完善工作
- 添加头寸持仓查询脚本 (query-position.js)
- 固化当日账户盈亏计算规则（使用您给的公式）
- 添加时间校准规则（必须先执行date命令）
- 添加账户总权益计算规则（必须合并期货+股票）
- 添加盈亏百分比计算（以昨日权益为分母）
- 更新SKILL.md文档，包含详细计算方法
- 创建README.md记录更新日志

### 文件管理优化
- 区分工作记录和待办清单
- 创建 notes/worklog.md 工作记录
- 更新 notes/todo.md 只包含用户待办任务
- 添加AGENTS.md工作规则：
  - 每次更新完必须提交到GitHub
  - 重要修改要记录到MEMORY.md
  - 每完成一项工作必须记录到worklog.md

### 数据查询实践
- 查询昨天多au头寸盈亏
- 查询昨天多au-ag头寸盈亏
- 查询昨天多cu-ni头寸持仓占比
- 查询昨天账户总权益（合并期货+股票）
- 所有查询都使用正确的计算方法

### 时间约定
- 建立统一时间约定：所有时间使用北京时间（UTC+8）
- 不使用UTC时间或波士顿时间
- 北京时间 = UTC + 8小时
- 查询日期时，先确认北京时间
- 记录时间时，标注为北京时间

### 强制读取SKILL.md机制
- **触发语**："用postgres查询：[问题]"
- **执行流程**：
  1. 显示：正在读取 SKILL.md...
  2. 读取：`read skills/postgres-query/SKILL.md`
  3. 列出：相关公式
  4. 执行：按步骤计算
- **目的**：确保每次计算都读取规则，不凭记忆操作

### SKILL.md更新（2026-02-01）
- 添加"用postgres查询"触发语说明
- 更新"当日持仓头寸盈亏"计算规则
- 明确：盈亏百分比分母是账户期初权益
- 明确：每次查询都要列出具体金额和盈亏百分比
- 重要：永远不要合并账户计算，每个账户用自己的权益
