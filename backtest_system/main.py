import click
from backtest_system.core.database import DatabaseAPI
from backtest_system.core.supervisor import Supervisor
from backtest_system.core.orchestrator import Orchestrator
from backtest_system.core.models import TaskConfig
from backtest_system.core.config import BacktestConfig, load_config
from backtest_system.skills.validate_data import ValidateDataSkill
from backtest_system.skills.backtest_strategy import BacktestStrategySkill
from backtest_system.skills.backtest_portfolio import BacktestPortfolioSkill
from backtest_system.skills.generate_report import GenerateReportSkill
from backtest_system.skills.simple_backtest import SimpleBacktestSkill

@click.group()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=str),
    default=None,
    envvar="BACKTEST_CONFIG",
    help="YAML配置文件路径（可选）。也可以用环境变量 BACKTEST_* 配置。",
)
@click.pass_context
def cli(ctx: click.Context, config_path: str | None):
    """自动策略回测系统"""
    ctx.obj = load_config(config_path)

@cli.command()
@click.argument('instruction', required=True)
@click.pass_obj
def simple(cfg: BacktestConfig, instruction):
    """简单模式 - 用自然语言指令执行回测"""
    db_api = DatabaseAPI(cfg.database.url, cfg.api)
    supervisor = Supervisor(
        db_api,
        non_interactive=cfg.app.non_interactive,
        on_escalate=cfg.app.on_escalate,
        log_dir=cfg.app.output_dir,
    )
    
    skill = SimpleBacktestSkill(supervisor)
    result = skill.execute(instruction)
    
    print(result.data.get("output", "执行完成"))

@cli.command()
@click.option(
    '--positions',
    required=True,
    help='头寸池（候选策略），逗号分隔。例: "多AU,空AG,多AU-AG:1:1"',
)
@click.option(
    '--periods',
    default='3y,5y,10y',
    help='回测周期列表，逗号分隔，支持 3m/6m/5y/90d/all（m=月）。',
)
@click.option(
    '--combo-range',
    default='3-5',
    help='组合大小范围（从 positions 中选几条策略做组合），如 2-4 或 3-5。',
)
@click.option(
    '--portfolio-models',
    default='mean_variance,equal_weight',
    help='组合权重模型，逗号分隔: mean_variance,equal_weight',
)
@click.option(
    '--top-n',
    default=10,
    help='报告输出每个周期 Top-N 组合（按 Sharpe 排序）。',
)
@click.option(
    '--strategy-max-evals',
    default=2000,
    show_default=True,
    help='每条策略每个周期参数搜索最大评估次数（随机采样/小网格）。',
)
@click.pass_obj
def smart(cfg: BacktestConfig, positions, periods, combo_range, portfolio_models, top_n, strategy_max_evals):
    """智能模式"""
    db_api = DatabaseAPI(cfg.database.url, cfg.api)
    supervisor = Supervisor(
        db_api,
        non_interactive=cfg.app.non_interactive,
        on_escalate=cfg.app.on_escalate,
        log_dir=cfg.app.output_dir,
    )
    orchestrator = Orchestrator(supervisor)

    # 注册skills
    orchestrator.register_skill(ValidateDataSkill(db_api))
    orchestrator.register_skill(BacktestStrategySkill(db_api))
    orchestrator.register_skill(BacktestPortfolioSkill(db_api))
    orchestrator.register_skill(GenerateReportSkill(db_api, output_dir=cfg.app.output_dir))

    combo_min, combo_max = map(int, combo_range.split('-'))
    config = TaskConfig(
        task_id="",
        mode="smart",
        positions=[p.strip() for p in positions.split(",") if p.strip()],
        periods=[p.strip() for p in periods.split(",") if p.strip()],
        combo_range=(combo_min, combo_max),
        portfolio_models=[p.strip() for p in portfolio_models.split(",") if p.strip()],
        top_n=top_n,
        strategy_max_evals=strategy_max_evals,
    )

    results = orchestrator.run_smart_mode(config)
    status = _summarize_status(results)
    if status["status"] == "completed":
        print(f"\n任务完成: {results['task_id']}")
    else:
        print(f"\n任务{status['status']}: {results['task_id']}")
        if status.get("error"):
            print(f"原因: {status['error']}")

    # 打印报告路径
    for step in results.get("steps", []):
        if step.get("skill") == "generate_report" and step.get("result"):
            report_data = step["result"].data
            if report_data:
                print(f"Excel报告: {report_data.get('excel_path')}")

@cli.command()
@click.option('--positions', required=True, help='头寸池（候选策略），逗号分隔。')
@click.option('--period', required=True, help='回测周期，格式同 --periods 的单值（如 5y/6m/all）。')
@click.option('--portfolio-model', default='mean_variance', help='组合权重模型（默认 mean_variance）。')
@click.option('--strategy-max-evals', default=2000, show_default=True, help='每条策略参数搜索最大评估次数（随机采样/小网格）。')
@click.pass_obj
def specified(cfg: BacktestConfig, positions, period, portfolio_model, strategy_max_evals):
    """指定模式"""
    db_api = DatabaseAPI(cfg.database.url, cfg.api)
    supervisor = Supervisor(
        db_api,
        non_interactive=cfg.app.non_interactive,
        on_escalate=cfg.app.on_escalate,
        log_dir=cfg.app.output_dir,
    )
    orchestrator = Orchestrator(supervisor)

    orchestrator.register_skill(ValidateDataSkill(db_api))
    orchestrator.register_skill(BacktestStrategySkill(db_api))
    orchestrator.register_skill(BacktestPortfolioSkill(db_api))
    orchestrator.register_skill(GenerateReportSkill(db_api, output_dir=cfg.app.output_dir))

    config = TaskConfig(
        task_id="",
        mode="specified",
        positions=[p.strip() for p in positions.split(",") if p.strip()],
        periods=[period.strip()],
        portfolio_models=[portfolio_model.strip()],
        strategy_max_evals=strategy_max_evals,
    )

    results = orchestrator.run_specified_mode(config)
    status = _summarize_status(results)
    if status["status"] == "completed":
        print(f"任务完成: {results['task_id']}")
    else:
        print(f"任务{status['status']}: {results['task_id']}")
        if status.get("error"):
            print(f"原因: {status['error']}")

@cli.command()
@click.option('--limit', default=20, help='显示条数')
@click.pass_obj
def history(cfg: BacktestConfig, limit):
    """查看历史任务"""
    db_api = DatabaseAPI(cfg.database.url, cfg.api)
    try:
        query = "SELECT * FROM backtest_tasks ORDER BY created_at DESC LIMIT %s"
        results = db_api.read(query, (limit,))
        for r in results:
            print(f"{r['task_id']} | {r['mode']} | {r['status']} | {r['created_at']}")
    except Exception as e:
        print(f"无法读取历史任务（需要配置 BACKTEST_DB_URL ）: {e}")

def _summarize_status(results: dict) -> dict:
    steps = results.get("steps", []) or []
    status = "completed"
    error = None
    for step in steps:
        r = step.get("result")
        if not r:
            continue
        if getattr(r, "halted", False):
            status = "halted"
            error = getattr(r, "error", None)
            break
        if not getattr(r, "success", True):
            status = "failed"
            if error is None:
                error = getattr(r, "error", None)
    return {"status": status, "error": error}

if __name__ == '__main__':
    cli()
