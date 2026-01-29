#!/usr/bin/env node

/**
 * 头寸持仓查询脚本
 * 使用方式: node query-position.js [options]
 */

const API_BASE = 'http://100.67.45.63:8000';

async function queryPositions(params = {}) {
  const url = new URL(`${API_BASE}/api/position`);

  // 添加查询参数
  Object.keys(params).forEach(key => {
    if (params[key] !== undefined && params[key] !== null && params[key] !== '') {
      url.searchParams.append(key, params[key]);
    }
  });

  console.log(`请求: ${url.toString()}`);

  try {
    const response = await fetch(url.toString(), {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      }
    });

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }

    const data = await response.json();
    return data;
  } catch (error) {
    console.error('查询失败:', error.message);
    console.error('错误详情:', error);
    return { code: -1, message: error.message, data: null };
  }
}

function printHelp() {
  console.log(`
头寸持仓查询工具

使用方式:
  node query-position.js [options]

选项:
  --trade-date <date>      交易日期 (YYYY-MM-DD)
  --account-name <name>    账号名称
  --position-name <name>   头寸名称
  --symbol <symbol>        标的代码
  --start-date <date>      开始日期 (YYYY-MM-DD)
  --end-date <date>        结束日期 (YYYY-MM-DD)
  --limit <number>         返回条数 (默认1000，最大10000)
  --help                   显示帮助信息

示例:
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
`);
}

// 命令行参数解析
function parseArgs(args) {
  const params = {};

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case '--trade-date':
      case '-d':
        params.trade_date = args[++i];
        break;
      case '--account-name':
      case '-a':
        params.account_name = args[++i];
        break;
      case '--position-name':
      case '-p':
        params.position_name = args[++i];
        break;
      case '--symbol':
      case '-s':
        params.symbol = args[++i];
        break;
      case '--start-date':
      case '--start':
        params.start_date = args[++i];
        break;
      case '--end-date':
      case '--end':
        params.end_date = args[++i];
        break;
      case '--limit':
      case '-l':
        params.limit = parseInt(args[++i], 10);
        break;
      case '--help':
      case '-h':
        printHelp();
        process.exit(0);
        break;
      default:
        if (args[i].startsWith('-')) {
          console.error(`未知选项: ${args[i]}`);
          printHelp();
          process.exit(1);
        }
    }
  }

  // 验证 limit
  if (params.limit !== undefined) {
    if (isNaN(params.limit) || params.limit < 1) {
      console.error('limit 必须是正整数');
      process.exit(1);
    }
    if (params.limit > 10000) {
      console.error('limit 最大值为 10000');
      process.exit(1);
    }
  }

  return params;
}

// 主函数
async function main() {
  const args = process.argv.slice(2);
  const params = parseArgs(args);

  console.log('查询参数:', params);
  console.log('');

  const result = await queryPositions(params);

  if (result && result.data) {
    console.log('✅ 查询成功');
    const count = result.count || result.data?.length || 0;
    console.log(`共 ${count} 条记录`);
    console.log('');
    console.log(JSON.stringify(result.data, null, 2));
  } else {
    console.log('❌ 查询失败');
    console.log(`返回结果:`, JSON.stringify(result, null, 2));
    process.exit(1);
  }
}

// 如果直接运行此脚本
if (require.main === module) {
  main().catch(error => {
    console.error('未捕获的错误:', error);
    process.exit(1);
  });
}

// 导出函数供其他模块使用
module.exports = {
  queryPositions,
  API_BASE
};
