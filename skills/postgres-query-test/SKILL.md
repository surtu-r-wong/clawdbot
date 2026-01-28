---
name: postgres-query-test
description: 测试 PostgreSQL API 连接和查询功能
---

# PostgreSQL API 查询测试

这个技能用于测试 PostgreSQL 数据库 API 的连接和查询功能。

## 配置

```yaml
api_url: http://100.67.45.63:8000
```

## 测试查询

### 测试 1：账户盈亏查询
```sql
SELECT 
    account_id,
    SUM(profit_loss) as total_pnl,
    COUNT(*) as trade_count,
    AVG(profit_loss) as avg_pnl
FROM account_pnl
WHERE account_id = 1
GROUP BY account_id;
```

### 测试 2：多空头寸统计
```sql
SELECT 
    account_id,
    SUM(CASE WHEN quantity > 0 THEN quantity ELSE 0 END) as long_total,
    SUM(CASE WHEN quantity < 0 THEN ABS(quantity) ELSE 0 END) as short_total
FROM positions
WHERE account_id = 1;
```

## API 端点

### 端点 1：获取账户盈亏
```
GET /api/pnl
```

### 端点 2：获取头寸汇总
```
GET /api/positions
```

## 使用方式

在对话中说"测试盈亏查询"，我会调用这些 API 端点并返回结果。
