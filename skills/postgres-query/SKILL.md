---
name: postgres-query
description: PostgreSQL 数据库查询助手。支持查询行情数据、账户盈亏、多l-v头寸等。使用安全的参数化查询，防止 SQL 注入。

---

# PostgreSQL 数据库查询助手

这个技能用于安全地查询 PostgreSQL 数据库中的行情、盈亏、头寸等数据。

## 使用方法

在对话中直接询问，例如：
- "昨天多l-v头寸赚了多少钱"
- "查询账户总盈亏"
- "今日行情汇总"
- "查询持有头寸列表"

我会直接执行查询并返回结果，不需要复杂的对话流程。

## 支持的查询类型

### 1. 行情数据
- 最新价格
- 涨跌幅
- 成交量
- 持仓量

### 2. 账户盈亏
- 总盈亏金额
- 盈利/亏损明细
- 收益率

### 3. 头寸管理
- 多l-v头寸
- 空l-v头寸
- 持仓量

### 4. 其他数据
- 用户信息
- 系统日志
- 交易记录

## 数据库连接配置

这个技能支持两种查询方式：

### 选项 1：直接连接 PostgreSQL
```yaml
host: localhost  # 或远程服务器地址
port: 5432
database: your_database_name
user: your_username
password: your_password
# 注意：密码不要明文存储，建议使用环境变量
```

### 选项 2：通过 API 接口（已配置）
```yaml
api_url: http://100.67.45.63:8000
# 已配置：用户提供的外部 API 服务
```

**当前配置**：
- API URL: http://100.67.45.63:8000
- 状态：✅ 已启用

**配置方式**：
1. 直接在 SKILL.md 中填写（不安全）
2. 使用环境变量 `PGPASSWORD`（推荐）
3. 让用户运行时提供连接参数
4. 通过已配置的 API 接口查询（当前方式）

## 查询执行

所有查询都会使用参数化 SQL，防止注入攻击。

### SQL 模板示例

```sql
-- 查询最新行情
SELECT instrument, price, change_pct, volume, timestamp
FROM market_data
WHERE instrument = $1
ORDER BY timestamp DESC
LIMIT 10;

-- 查询账户盈亏
SELECT 
    SUM(profit_loss) as total_pnl,
    COUNT(*) as trade_count,
    AVG(profit_loss) as avg_pnl
FROM account_pnl
WHERE account_id = $1;

-- 查询头寸汇总
SELECT 
    instrument,
    SUM(quantity) as total_quantity,
    AVG(entry_price) as avg_entry,
    SUM(quantity * (current_price - entry_price)) as unrealized_pnl
FROM positions
WHERE account_id = $1
GROUP BY instrument;
```

## 使用 psql 工具

在 VPS 上安装 PostgreSQL 客户端：
```bash
# Debian/Ubuntu
sudo apt-get install postgresql-client

# 验证安装
psql --version
```

连接测试：
```bash
psql -h localhost -U username -d database_name
```

### 安全注意事项

⚠️ **重要**：
1. **永远不要在配置文件中存储明文密码**
2. **使用环境变量**：`export PGPASSWORD='your_password'`
3. **参数化所有查询**，不要拼接 SQL
4. **限制查询结果**，避免返回过多数据

## 故障排除

如果查询失败：
1. 检查数据库连接配置
2. 确认 PostgreSQL 服务是否运行
3. 验证用户权限
4. 检查防火墙设置

## 数据库模式建议

为了让查询更准确，建议在数据库中创建以下视图：

```sql
-- 账户盈亏汇总视图
CREATE VIEW v_account_pnl_summary AS
SELECT 
    account_id,
    SUM(profit_loss) as total_pnl,
    SUM(CASE WHEN profit_loss > 0 THEN profit_loss ELSE 0 END) as total_profit,
    SUM(CASE WHEN profit_loss < 0 THEN ABS(profit_loss) ELSE 0 END) as total_loss,
    COUNT(*) as trade_count
FROM account_pnl
GROUP BY account_id;

-- 头寸汇总视图
CREATE VIEW v_position_summary AS
SELECT 
    account_id,
    instrument,
    SUM(quantity) as total_quantity,
    SUM(CASE WHEN quantity > 0 THEN quantity ELSE 0 END) as long_quantity,
    SUM(CASE WHEN quantity < 0 THEN ABS(quantity) ELSE 0 END) as short_quantity,
    AVG(current_price) as avg_price,
    SUM(quantity * (current_price - entry_price)) as unrealized_pnl
FROM positions
GROUP BY account_id, instrument;
```

## 下一步

**需要王小爷提供**：
1. PostgreSQL 数据库连接信息（host, port, database, user）
2. 或提供 RESTful API 接口地址，我可以集成
3. 数据库表结构和字段信息

**我会根据提供的信息配置这个技能，确保查询准确！**
