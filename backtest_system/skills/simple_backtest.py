"""
简单回测Skill - 自然语言指令解析
支持格式：
  - 回测 多RB 3年
  - 回测 多I-RB,多CU-NI 3年,5年
  - 组合回测 多RB,多CU-NI 3年 200000次
"""
import re
from typing import Dict, List, Optional

# 延迟导入 Orchestrator 避免循环导入
from backtest_system.skills.base import BaseSkill
from backtest_system.core.models import SkillResult, TaskConfig
from backtest_system.core.supervisor import Supervisor
from backtest_system.core.database import DatabaseAPI


class SimpleBacktestSkill(BaseSkill):
    """自然语言回测指令解析器"""

    def __init__(self, supervisor: Optional[Supervisor] = None):
        self.supervisor = supervisor

    @property
    def name(self) -> str:
        return "simple_backtest"

    def execute(self, instruction: str) -> SkillResult:
        """解析并执行回测指令"""
        try:
            if not instruction or not instruction.strip():
                return SkillResult(success=False, error="指令不能为空")

            instruction = instruction.strip()

            # 解析指令
            is_portfolio = "组合" in instruction

            # 提取评估次数（如果有）
            evals = 200000  # 默认值
            evals_match = re.search(r"(\d+)次", instruction)
            if evals_match:
                evals = int(evals_match.group(1))

            # 提取品种列表
            # 找到所有品种：多RB, 多CU-NI, 多M-LH (支持连字符品种名)
            positions_match = re.findall(r"多[A-Z\-]+", instruction)
            
            if not positions_match:
                return SkillResult(success=False, error="无法解析品种，格式如：回测 多RB 或 回测 多RB,多CU-NI")
            
            positions = positions_match  # 已经包含 "多" 前缀

            # 提取周期列表
            periods: List[str] = []
            # 匹配：3年, 5年 或 3y, 5y
            period_patterns = [
                r"(\d+)年(?:,\s*(\d+)年)?",  # 中文格式
                r"(\d+)y(?:,\s*(\d+)y)?",    # 英文格式
            ]
            
            for pattern in period_patterns:
                matches = re.findall(pattern, instruction)
                if matches:
                    for match in matches:
                        if match[0]:  # 第一个周期
                            periods.append(f"{match[0]}y")
                        if match[1]:  # 第二个周期
                            periods.append(f"{match[1]}y")
                    break
            
            if not periods:
                periods = ["3y"]  # 默认3年

            # 组合回测参数
            combo_range = None
            top_n = 10
            portfolio_models = ["mean_variance", "equal_weight"]

            if is_portfolio:
                # 提取组合范围（如果有）：3-5
                combo_match = re.search(r"(\d+)-(\d+)", instruction)
                if combo_match:
                    combo_range = (int(combo_match.group(1)), int(combo_match.group(2)))

            # 创建TaskConfig
            config = TaskConfig(
                mode="smart",
                positions=positions,
                periods=periods,
                combo_range=combo_range,
                portfolio_models=portfolio_models,
                top_n=top_n,
                strategy_max_evals=evals,
            )

            # 执行回测
            if not self.supervisor:
                # 如果没有supervisor，创建一个
                from backtest_system.core.config import get_db_api
                db_api = get_db_api()
                self.supervisor = Supervisor(db_api)

            # 延迟导入 Orchestrator 避免循环导入
            from backtest_system.core.orchestrator import Orchestrator
            orchestrator = Orchestrator(self.supervisor)
            
            # 确保必要的skill已注册
            from backtest_system.skills import (
                validate_data,
                backtest_strategy,
                backtest_portfolio,
                generate_report,
            )
            orchestrator.register_skill(validate_data.ValidateDataSkill(self.supervisor.db_api))
            orchestrator.register_skill(backtest_strategy.BacktestStrategySkill(self.supervisor.db_api))
            orchestrator.register_skill(backtest_portfolio.BacktestPortfolioSkill(self.supervisor.db_api))
            orchestrator.register_skill(generate_report.GenerateReportSkill(self.supervisor.db_api))

            # 执行
            results = orchestrator.run_smart_mode(config)

            # 格式化输出
            if "task_id" not in results:
                return SkillResult(success=False, error="回测任务执行失败")

            task_id = results["task_id"]
            steps = results.get("steps", [])

            # 提取结果摘要
            output = []
            output.append(f"✅ 回测任务完成")
            output.append(f"📋 任务ID: {task_id}")
            output.append(f"📊 品种: {', '.join(positions)}")
            output.append(f"📅 周期: {', '.join(periods)}")
            output.append("")

            # 检查是否失败
            failed = any(
                not step.get("result", {}).get("success", True) 
                for step in steps
            )

            if failed:
                # 找到失败的步骤
                for step in steps:
                    result = step.get("result", {})
                    if not result.get("success", True):
                        output.append(f"❌ {step.get('skill', '未知')} 失败")
                        if "error" in result:
                            output.append(f"   原因: {result['error']}")
                output.append("")
                output.append(f"📁 查看完整日志: output/{task_id}.logs.jsonl")

                return SkillResult(
                    success=False,
                    data={
                        "task_id": task_id,
                        "instruction": instruction,
                        "config": {
                            "positions": positions,
                            "periods": periods,
                            "evals": evals,
                        },
                        "status": "failed",
                        "output": "\n".join(output),
                    }
                )

            # 成功 - 提取组合回测结果
            output.append("📈 组合回测结果:")
            output.append("")

            for step in steps:
                if step.get("skill") == "backtest_portfolio":
                    result = step.get("result", {})
                    if result.success and result.data:
                        best = result.data.get("best", {})
                        metrics = best.get("metrics", {})
                        weights = best.get("weights", {})
                        
                        output.append(f"• 最佳夏普比率: {metrics.get('sharpe_ratio', 0):.3f}")
                        output.append(f"• 总收益率: {metrics.get('total_return', 0)*100:.2f}%")
                        output.append(f"• 最大回撤: {metrics.get('max_drawdown', 0)*100:.2f}%")
                        output.append(f"• 年化收益: {metrics.get('annualized_return', 0)*100:.2f}%")
                        output.append(f"• 年化波动: {metrics.get('annualized_volatility', 0)*100:.2f}%")
                        output.append("")
                        output.append("📊 权重分配:")
                        for pos, w in weights.items():
                            output.append(f"  • {pos}: {w*100:.2f}%")
                        output.append("")

            # 单策略结果摘要
            strategy_count = sum(1 for s in steps if s.get("skill") == "backtest_strategy")
            success_count = sum(
                1 for s in steps 
                if s.get("skill") == "backtest_strategy" and s.get("result", {}).get("success", True)
            )
            output.append(f"📊 策略优化: {success_count}/{strategy_count} 完成")

            output.append("")
            output.append(f"📁 查看详细报告: output/{task_id}.xlsx")
            output.append(f"📁 查看资金曲线: output/{task_id}_equity.png")

            return SkillResult(
                success=True,
                data={
                    "task_id": task_id,
                    "instruction": instruction,
                    "config": {
                        "positions": positions,
                        "periods": periods,
                        "evals": evals,
                    },
                    "status": "completed",
                    "output": "\n".join(output),
                    "results": results,
                },
            )

        except Exception as e:
            import traceback
            error_msg = f"指令解析失败: {str(e)}\n{traceback.format_exc()}"
            return SkillResult(success=False, error=error_msg)


# 辅助函数：格式化大数字
def _format_number(num: float) -> str:
    """格式化大数字，保留3位小数"""
    if abs(num) >= 10000:
        return f"{num/10000:.2f}万"
    return f"{num:.2f}"
