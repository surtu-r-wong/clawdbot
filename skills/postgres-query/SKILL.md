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

---

## ⏰ 时间校准规则（第一步）

**所有查询的第一步必须先校准时间！**

1. **获取当前日期**：执行 `date +%Y-%m-%d` 获取系统日期
2. **计算日期**：
   - "昨天" = 当前日期 - 1天
   - "今天" = 当前日期
   - "前天" = 当前日期 - 2天
3. **查询时使用计算后的日期，不要凭空推断！**

**示例**：
- 如果当前是 2026-01-29
- "昨天" = 2026-01-28
- "今天" = 2026-01-29
- "前天" = 2026-01-27

**⚠️ 永远不要凭记忆或推断日期，必须先执行 date 命令！**

---

## 💰 账户总权益计算规则

**⚠️ 所有涉及总权益的查询，必须合并计算期货账户和股票账户！**

### 计算方法
```
账户总权益 = 期货账户动态权益含期权 + 股票账户总资产
```

### 期货账户数据来源
- API接口: `/api/futures/account`
- 字段: `动态权益含期权`
- 按账号分别查询后汇总

### 股票账户数据来源
- API接口: `/api/stock/account`
- 字段: `总资产`
- 按账号分别查询后汇总

### 示例
```bash
# 查询期货账户
curl "http://100.67.45.63:8000/api/futures/account?trade_date=2026-01-28"

# 查询股票账户
curl "http://100.67.45.63:8000/api/stock/account?trade_date=2026-01-28"
```

**⚠️ 永远不要遗漏股票账户！**

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
- 头寸持仓记录（新增）

### 4. 头寸持仓查询
通过 `/api/position` 接口查询头寸持仓记录

**接口路径**: `GET /api/position`

**支持参数**:
- `trade_date`: 交易日期（如：2024-01-28）
- `account_name`: 账号名称
- `position_name`: 头寸名称
- `symbol`: 标的代码
- `start_date`: 开始日期
- `end_date`: 结束日期
- `limit`: 返回条数（默认1000，最大10000）

**⚠️ 重要**:
- `浮动盈亏` 字段是API返回的已经计算好的净浮动盈亏（包含多空方向）
- 计算头寸当日盈亏时，需要对比今日和昨日的浮动盈亏变化，再加上平仓盈亏
- 手续费已包含在API返回的 `浮动盈亏` 中，不需要单独扣除

**使用示例**:
- "查询所有持仓记录"
- "查询昨天的新开仓头寸"
- "查询账户xxx的持仓情况"
- "查询标的AAPL的持仓记录"
- "查询2024年1月的所有头寸"

### 5. 其他数据
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

**可用接口**：
1. `/api/position` - 查询头寸持仓记录
2. `/api/futures/account` - 查询期货账户
3. `/api/stock/account` - 查询股票账户
4. `/api/futures/position` - 查询期货持仓
5. `/api/futures/transactions` - 查询交易记录

**⚠️ 重要：查询账户总权益时，必须同时查询期货账户和股票账户！**

**配置方式**：
1. 直接在 SKILL.md 中填写（不安全）
2. 使用环境变量 `PGPASSWORD`（推荐）
3. 让用户运行时提供连接参数
4. 通过已配置的 API 接口查询（当前方式）

## API 接口使用

### 头寸持仓查询接口

**请求方式**: `GET`

**接口路径**: `/api/position`

**请求参数**（全部可选）:
```json
{
  "trade_date": "2024-01-28",      // 交易日期
  "account_name": "account_001",   // 账号名称
  "position_name": "position_A",  // 头寸名称
  "symbol": "AAPL",                // 标的代码
  "start_date": "2024-01-01",      // 开始日期
  "end_date": "2024-01-31",        // 结束日期
  "limit": 100                     // 返回条数（默认1000，最大10000）
}
```

**请求示例**:
```bash
# 查询所有持仓记录
curl "http://100.67.45.63:8000/api/position"

# 查询指定日期的持仓
curl "http://100.67.45.63:8000/api/position?trade_date=2024-01-28"

# 查询指定账户的持仓
curl "http://100.67.45.63:8000/api/position?account_name=account_001"

# 查询指定时间范围的持仓
curl "http://100.67.45.63:8000/api/position?start_date=2024-01-01&end_date=2024-01-31"

# 查询指定标的的持仓
curl "http://100.67.45.63:8000/api/position?symbol=AAPL"

# 组合查询
curl "http://100.67.45.63:8000/api/position?account_name=account_001&start_date=2024-01-01&limit=50"
```

**使用 Node.js 脚本查询**:
```javascript
const API_BASE = 'http://100.67.45.63:8000';

async function queryPositions(params = {}) {
  const url = new URL(`${API_BASE}/api/position`);
  Object.keys(params).forEach(key => {
    if (params[key]) url.searchParams.append(key, params[key]);
  });

  try {
    const response = await fetch(url.toString());
    const data = await response.json();
    return data;
  } catch (error) {
    console.error('查询失败:', error.message);
    return null;
  }
}

// 使用示例
(async () => {
  // 查询所有持仓
  const allPositions = await queryPositions();
  console.log('所有持仓:', allPositions);

  // 查询指定日期的持仓
  const todayPositions = await queryPositions({ trade_date: '2024-01-28' });
  console.log('今日持仓:', todayPositions);
})();
```

**返回数据格式**（实际）:
```json
{
  "count": 5,
  "data": [
    {
      "id": 3452,
      "交易日期": "2026-01-28",
      "账号名称": "朝晖多资产-国海良时期货[2]",
      "资产类别": "futures",
      "头寸类别": "单边",
      "头寸名称": "多al",
      "标的代码": "al2603",
      "标的名称": "沪铝2603",
      "多空": "多",
      "总持仓": 3.0,
      "开仓均价": 23835.0,
      "开仓成本": 357525.0,
      "保证金": 36367.5,
      "手续费": 0.0,
      "最新价": 25640.0,
      "合约价值": 384600.0,
      "浮动盈亏": 27075.0,
      "created_at": "2026-01-28T16:59:37.040969"
    }
  ]
}
```

**字段说明**:
- `id`: 记录ID
- `交易日期`: 交易日期
- `账号名称`: 账户名称
- `资产类别`: 资产类别（如：futures, stock, crypto等）
- `头寸类别`: 头寸类别（单边/对冲）
- `头寸名称`: 头寸名称
- `标的代码`: 标的代码
- `标的名称`: 标的名称
- `多空`: 多空方向（多/空）
- `总持仓`: 总持仓数量
- `开仓均价`: 开仓平均价格
- `开仓成本`: 开仓成本
- `保证金`: 保证金金额
- `手续费`: 手续费
- `最新价`: 最新价格
- `合约价值`: 合约价值
- `浮动盈亏`: 浮动盈亏金额
- `created_at`: 创建时间

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

## 脚本使用说明

### query-position.js - 头寸持仓查询脚本

**位置**: `/home/surtu/clawd/skills/postgres-query/query-position.js`

**基本用法**:
```bash
# 查询所有持仓
node query-position.js

# 查询指定日期的持仓
node query-position.js --trade-date 2024-01-28

# 查询指定账户的持仓
node query-position.js --account-name account_001

# 查询指定时间范围的持仓
node query-position.js --start-date 2024-01-01 --end-date 2024-01-31

# 查询指定标的的持仓
node query-position.js --symbol AAPL

# 组合查询
node query-position.js --account-name account_001 --start-date 2024-01-01 --limit 50
```

**程序化调用**:
```javascript
const { queryPositions } = require('/home/surtu/clawd/skills/postgres-query/query-position.js');

// 查询所有持仓
const allPositions = await queryPositions();

// 查询指定参数
const result = await queryPositions({
  trade_date: '2024-01-28',
  account_name: 'account_001',
  limit: 50
});

console.log(result);
```

**返回格式**:
```json
{
  "count": 5,
  "data": [
    {
      "id": 3452,
      "交易日期": "2026-01-28",
      "账号名称": "朝晖多资产-国海良时期货[2]",
      "资产类别": "futures",
      "头寸类别": "单边",
      "头寸名称": "多al",
      "标的代码": "al2603",
      "标的名称": "沪铝2603",
      "多空": "多",
      "总持仓": 3.0,
      "开仓均价": 23835.0,
      "开仓成本": 357525.0,
      "保证金": 36367.5,
      "手续费": 0.0,
      "最新价": 25640.0,
      "合约价值": 384600.0,
      "浮动盈亏": 27075.0,
      "created_at": "2026-01-28T16:59:37.040969"
    }
  ]
}
```

**字段说明**:
- `id`: 记录ID
- `交易日期`: 交易日期
- `账号名称`: 账户名称
- `资产类别`: 资产类别（如：futures, stock, crypto等）
- `头寸类别`: 头寸类别（单边/对冲）
- `头寸名称`: 头寸名称
- `标的代码`: 标的代码
- `标的名称`: 标的名称
- `多空`: 多空方向（多/空）
- `总持仓`: 总持仓数量
- `开仓均价`: 开仓平均价格
- `开仓成本`: 开仓成本
- `保证金`: 保证金金额
- `手续费`: 手续费
- `最新价`: 最新价格
- `合约价值`: 合约价值
- `浮动盈亏`: 浮动盈亏金额
- `created_at`: 创建时间

---

## 📊 盈亏计算方法

### 1. 当日盈亏

**数据来源**:
- `futures_account`: 交易日期, 账号名称, 动态权益含期权, 入金, 出金
- `stock_account`: 交易日期, 账号名称, 总资产
- `trading_calendar`: calendar_date, sfe

**期货账户当日盈亏**:
```
当日盈亏 = (今日动态权益含期权 - 昨日动态权益含期权) - 今日入金 + 今日出金
当日盈亏百分比 = 当日盈亏 / 昨日动态权益含期权 × 100%
```

**股票账户当日盈亏**:
```
当日盈亏 = 今日总资产 - 昨日总资产
当日盈亏百分比 = 当日盈亏 / 昨日总资产 × 100%
```

**⚠️ 固定规则：**
- **永远使用上述公式计算当日盈亏**
- **盈亏百分比必须与盈亏金额一起提供，以昨日总权益为分母计算**
- 不要使用API返回的"今日账号盈亏"字段
- 必须同时查询今日和昨日数据计算
- 所有计算以用户给的公式为准

---

### 2. 当日持仓头寸盈亏

**数据来源**:
- `position_table`: 交易日期, 账号名称, 头寸名称, 浮动盈亏, 手续费（当前持仓）
- `position_close_table`: 交易日期, 账号名称, 头寸名称, 平仓盈亏, 手续费（平仓记录）
- `futures_account`: 账号名称, 动态权益（用于计算百分比）
- `stock_account`: 账号名称, 总资产（用于计算百分比）

**计算方法**:
```
今日浮动盈亏 = SUM(浮动盈亏) - SUM(手续费)  -- 按账号、头寸名称分组
昨日浮动盈亏 = SUM(浮动盈亏) - SUM(手续费)  -- 按账号、头寸名称分组
今日平仓盈亏 = SUM(平仓盈亏) - SUM(手续费)  -- 按账号、头寸名称分组
浮动盈亏变化 = 今日浮动盈亏 - 昨日浮动盈亏
当日头寸盈亏 = 浮动盈亏变化 + 今日平仓盈亏
盈亏百分比 = 当日头寸盈亏 / 账户权益 × 100%
```

**⚠️ 重要**：
- **盈亏百分比必须与盈亏金额一起提供**
- 账户权益从 `futures_account` 表获取（期货用动态权益，股票用总资产）
- 按账号分别计算百分比

**⚠️ 固定计算规则**：
- **永远按上述公式计算**
- 浮动盈亏和手续费按账号、头寸名称分组后汇总
- 新开头寸：昨日浮动盈亏 = 0
- 当日无平仓：今日平仓盈亏 = 0
- **每次查询账户盈亏、头寸盈亏，都要列出具体金额和盈亏百分比**
- **盈亏百分比分母是账户期初权益**（不是昨日的动态权益）
- 账户期初权益从 `futures_account` 表获取（期货用期初权益，股票用总资产）
- 按账号分别列出金额和百分比，不要合并账户

---

### 3. 头寸盈亏分析（累计）

**数据来源**:
- `position_table`: 账号名称, 头寸名称, 浮动盈亏（当前浮动盈亏）
- `position_close_table`: 账号名称, 头寸名称, 平仓盈亏（历史累计平仓盈亏）
- `futures_account`: 账号名称, 交易日期, 动态权益, 入金, 出金（计算累计净投入）

**计算方法**:
```
累计净投入 = 首日权益 + 累计入金 - 累计出金
当前浮动盈亏 = SUM(浮动盈亏)  -- 最新交易日，按头寸名称分组
历史平仓盈亏 = SUM(平仓盈亏)  -- 全部历史，按头寸名称分组
头寸总盈亏 = 当前浮动盈亏 + 历史平仓盈亏
收益率 = 头寸总盈亏 / 累计净投入 × 100%
```

---

### 4. 大类资产配置

**数据来源**:
- `futures_account`: 账号名称, 交易日期, 动态权益（期货资产）
- `stock_account`: 账号名称, 交易日期, 总资产（股票资产）

**计算方法**:
```
期货资产 = 动态权益（最新交易日）
股票资产 = 总资产（最新交易日）
总资产 = 期货资产 + 股票资产
```

---

### 5. 持仓结构分析

**数据来源**:
- `position_table`: 交易日期, 账号名称, 头寸名称, 头寸类别, 合约价值

**计算方法**:
```sql
-- 按头寸名称汇总
头寸价值 = SUM(合约价值) GROUP BY 头寸名称

-- 按头寸类别汇总
类别价值 = SUM(合约价值) GROUP BY 头寸类别
```

---

### 6. 敞口比例

**数据来源**:
- `position_table`: 交易日期, 账号名称, 头寸类别, 多空, 合约价值

**计算方法**:
```
signed_value = 合约价值 (多为正, 空为负)
total_value = SUM(合约价值)
total_exposure = ABS(SUM(signed_value))
全部敞口比例 = total_exposure / total_value

-- 对冲+单边敞口比例
hedge_single_exposure = ABS(SUM(signed_value)) WHERE 头寸类别 IN ('对冲', '单边')
对冲单边敞口比例 = hedge_single_exposure / total_value

-- 单边敞口比例
single_exposure = ABS(SUM(signed_value)) WHERE 头寸类别 = '单边'
单边敞口比例 = single_exposure / total_value
```

---

### 7. 杠杆率

**数据来源**:
- `futures_account`: 交易日期, 账号名称, 合约价值, 动态权益含期权

**计算方法**:
```
杠杆率 = 合约价值 / 动态权益含期权  -- 当动态权益含期权 > 0 时计算，否则为 0
```

---

### 8. 保证金

**数据来源**:
- `futures_account`: 交易日期, 账号名称, 当前保证金, 风险度

**计算方法**:
```
保证金 = 当前保证金（直接读取）
风险度 = 风险度（直接读取）
```

---

### 9. 预警汇总

**数据来源**:
- `alert_history`: indicator_name, value, message, triggered_at, threshold_type

**计算方法**:
```sql
SELECT indicator_name, value, message, triggered_at, threshold_type
FROM alert_history
WHERE DATE(triggered_at) = CURRENT_DATE
ORDER BY triggered_at DESC
```

---

### 数据库表汇总

| 表名 | 用途 |
|------|------|
| `futures_account` | 期货账户数据（权益、保证金、杠杆率、出入金） |
| `stock_account` | 股票账户数据（总资产） |
| `position_table` | 当前持仓明细（浮动盈亏、合约价值、头寸类别） |
| `position_close_table` | 平仓记录（平仓盈亏） |
| `trading_calendar` | 交易日历（判断交易日） |
| `alert_history` | 预警历史记录 |

---

## 📝 计算示例：多au-ag头寸当日盈亏

**查询日期**: 2026-01-28
**头寸名称**: 多au-ag

### 步骤1: 获取今日持仓数据

**朝晖多资产-国海良时期货[2]**
- au2604: 浮动盈亏 = 50,550, 手续费 = 5.5
- ag2604: 浮动盈亏 = 4,005, 手续费 = 14.52

**金穗1号（国海期货）**
- au2604: 浮动盈亏 = 50,550, 手续费 = 0
- ag2604: 浮动盈亏 = 4,095, 手续费 = 0

### 步骤2: 计算今日浮动盈亏

**朝晖多资产-国海良时期货[2]**
```
今日浮动盈亏 = SUM(浮动盈亏) - SUM(手续费)
             = (50,550 + 4,005) - (5.5 + 14.52)
             = 54,555 - 20.02
             = 54,534.98
```

**金穗1号（国海期货）**
```
今日浮动盈亏 = SUM(浮动盈亏) - SUM(手续费)
             = (50,550 + 4,095) - 0
             = 54,645
```

### 步骤3: 计算浮动盈亏变化

因为"多au-ag"是新开头寸（昨日无持仓）：
```
昨日浮动盈亏 = 0
浮动盈亏变化 = 今日浮动盈亏 - 昨日浮动盈亏
             = 今日浮动盈亏 - 0
             = 今日浮动盈亏
```

### 步骤4: 计算今日平仓盈亏

当日无平仓记录：
```
今日平仓盈亏 = 0
```

### 步骤5: 计算当日头寸盈亏

```
当日头寸盈亏 = 浮动盈亏变化 + 今日平仓盈亏
             = 今日浮动盈亏 + 0
             = 今日浮动盈亏
```

### 步骤6: 获取账户权益并计算盈亏百分比

从 `futures_account` 表获取当日账户权益（动态权益）：

**朝晖多资产-国海良时期货[2]**
- 账户权益: [需要查询]
- 盈亏百分比 = 54,534.98 / 账户权益 × 100%

**金穗1号（国海期货）**
- 账户权益: [需要查询]
- 盈亏百分比 = 54,645 / 账户权益 × 100%

### 结果汇总

| 账号 | 当日头寸盈亏 | 账户权益 | 盈亏百分比 |
|------|------------|---------|-----------|
| 朝晖多资产-国海良时期货[2] | 54,534.98 元 | - | -% |
| 金穗1号（国海期货） | 54,645.00 元 | - | -% |
| **总计** | **109,179.98 元** | - | -% |

**⚠️ 注意**：盈亏百分比必须从 `futures_account` 表获取账户权益后计算

---

## 🔒 固定计算规则

**除非王小爷明确要求修改，否则永远按以下规则计算**：

1. **当日账户盈亏计算**：

   **期货账户**：
   ```
   当日盈亏 = (今日动态权益含期权 - 昨日动态权益含期权) - 今日入金 + 今日出金
   当日盈亏百分比 = 当日盈亏 / 昨日动态权益含期权 × 100%
   ```

   **股票账户**：
   ```
   当日盈亏 = 今日总资产 - 昨日总资产
   当日盈亏百分比 = 当日盈亏 / 昨日总资产 × 100%
   ```

   **⚠️ 永远使用上述公式，不要使用API返回的"今日账号盈亏"字段！**
   - **盈亏百分比必须与盈亏金额一起提供，以昨日总权益为分母计算**
   - 按账号分别计算

2. **当日头寸盈亏公式**：
   ```
   当日头寸盈亏 = 浮动盈亏变化 + 今日平仓盈亏
   浮动盈亏变化 = 今日浮动盈亏 - 昨日浮动盈亏
   今日浮动盈亏 = SUM(浮动盈亏) - SUM(手续费)
   今日平仓盈亏 = SUM(平仓盈亏) - SUM(手续费)
   盈亏百分比 = 当日头寸盈亏 / 账户权益 × 100%
   ```

3. **分组规则**：按账号、头寸名称分组计算

4. **新开头寸**：昨日浮动盈亏 = 0

5. **无平仓情况**：今日平仓盈亏 = 0

6. **手续费处理**：必须扣除所有手续费

7. **账户总权益**：必须合并期货账户（动态权益含期权）和股票账户（总资产）
