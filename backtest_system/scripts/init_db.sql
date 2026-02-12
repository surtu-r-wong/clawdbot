-- 1. 回测任务记录
CREATE TABLE backtest_tasks (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(50) UNIQUE NOT NULL,
    mode VARCHAR(20) NOT NULL,           -- 'smart' / 'specified'
    status VARCHAR(20) NOT NULL,         -- 'running' / 'completed' / 'failed' / 'halted'
    positions TEXT NOT NULL,             -- JSON: 用户输入的头寸池
    periods TEXT,                        -- JSON: ["3y", "5y", "10y"]
    combo_range VARCHAR(20),             -- 组合范围，如 "3-5"
    portfolio_models TEXT,               -- JSON: ["mean_variance", "equal_weight"]
    top_n INTEGER,                       -- 智能模式下输出前N个结果
    config TEXT,                         -- JSON: 完整配置（备份所有参数）
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 2. 回测结果记录
CREATE TABLE backtest_results (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(50) REFERENCES backtest_tasks(task_id),
    result_type VARCHAR(20) NOT NULL,    -- 'strategy' / 'portfolio'
    position_name VARCHAR(100),          -- 单策略时的头寸名
    portfolio_positions TEXT,            -- 组合时的头寸列表 JSON（系统选择的）
    portfolio_model VARCHAR(50),         -- 'mean_variance' / 'equal_weight'
    period VARCHAR(10) NOT NULL,
    params TEXT,                         -- JSON: 最优参数
    metrics TEXT NOT NULL,               -- JSON: {sharpe, max_dd, return, ...}
    excel_path VARCHAR(255),             -- Excel报告路径
    rank INTEGER,                        -- 智能模式下的排名
    created_at TIMESTAMP DEFAULT NOW()
);

-- 3. 执行日志
CREATE TABLE task_logs (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(50) REFERENCES backtest_tasks(task_id),
    skill_name VARCHAR(50) NOT NULL,
    event VARCHAR(20) NOT NULL,          -- 'START' / 'COMPLETE' / 'ERROR' / 'RETRY'
    message TEXT,
    data TEXT,                           -- JSON
    created_at TIMESTAMP DEFAULT NOW()
);

-- 索引
CREATE INDEX idx_tasks_status ON backtest_tasks(status);
CREATE INDEX idx_results_task ON backtest_results(task_id);
CREATE INDEX idx_logs_task ON task_logs(task_id);
