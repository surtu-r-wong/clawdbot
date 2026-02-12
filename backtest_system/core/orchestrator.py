from typing import Dict, Optional
from datetime import datetime
import uuid
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from backtest_system.core.supervisor import Supervisor
from backtest_system.core.models import SkillResult, TaskConfig
from backtest_system.skills.base import BaseSkill
from backtest_system.skills.backtest_strategy import parse_position

class Orchestrator:
    """协调者：解析指令、管理依赖、调度执行"""

    def __init__(self, supervisor: Supervisor):
        self.supervisor = supervisor
        self.skills: Dict[str, BaseSkill] = {}

    def register_skill(self, skill: BaseSkill):
        """注册skill"""
        self.skills[skill.name] = skill

    def _execute_skill(self, skill_name: str, params: dict, max_retries: int = 3) -> SkillResult:
        """执行单个skill，向Supervisor上报状态"""
        if skill_name not in self.skills:
            return SkillResult(success=False, error=f"Skill {skill_name} not found")

        self.supervisor.on_skill_start(skill_name, params)

        for attempt in range(max_retries):
            try:
                result = self.skills[skill_name].execute(**params)
                if result is None:
                    result = SkillResult(success=False, error="Skill returned None")

                # Non-exception failures also flow through Supervisor for consistent logging.
                self.supervisor.on_skill_complete(skill_name, result)

                if result.success:
                    return result
                if result.halted or result.skipped:
                    return result
                if result.retry:
                    print(f"重试 {attempt + 1}/{max_retries}...")
                    continue

                # Plain failure (no retry/skip/halt flags).
                return result
            except Exception as e:
                error_result = self.supervisor.on_skill_error(skill_name, e)
                if error_result.halted:
                    return error_result
                if error_result.skipped:
                    return error_result
                if not error_result.retry:
                    return error_result
                print(f"重试 {attempt + 1}/{max_retries}...")

        final = SkillResult(success=False, error="Max retries exceeded")
        self.supervisor.on_skill_complete(skill_name, final)
        return final

    def run_smart_mode(self, config: TaskConfig) -> dict:
        """智能模式：全自动探索"""
        task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.supervisor.set_task_id(task_id)

        # 先创建任务记录（带重试）
        now = datetime.now().replace(microsecond=0).isoformat(sep=" ")
        task_created = False
        for attempt in range(3):
            try:
                config_snapshot = {
                    "positions": config.positions,
                    "periods": config.periods,
                    "combo_range": config.combo_range,
                    "portfolio_models": config.portfolio_models,
                    "top_n": config.top_n,
                    "strategy_max_evals": config.strategy_max_evals,
                    "params": config.params,
                }
                payload = {
                    "task_id": task_id,
                    "mode": "smart",
                    "status": "running",
                    "positions": json.dumps(config.positions, ensure_ascii=True),
                    "periods": json.dumps(config.periods or [], ensure_ascii=True),
                    "combo_range": f"{config.combo_range[0]}-{config.combo_range[1]}" if config.combo_range else None,
                    "portfolio_models": json.dumps(config.portfolio_models or [], ensure_ascii=True),
                    "top_n": int(config.top_n),
                    "config": json.dumps(config_snapshot, ensure_ascii=True),
                    "started_at": now,
                    "created_at": now,
                }
                payload = {k: v for k, v in payload.items() if v is not None}
                task_created = self.supervisor.db_api.create_task(payload)
            except Exception as e:
                task_created = False
                print(f"任务创建异常: {e}")
            if task_created:
                break
            print(f"任务创建重试 {attempt + 1}/3...")

        if not task_created:
            print("警告: 任务创建失败，日志将不会写入数据库")
            self.supervisor.disable_remote_logging()  # 禁用远程日志写入（保留本地日志）

        results = {
            "task_id": task_id,
            "mode": "smart",
            "config": {
                "positions": config.positions,
                "periods": config.periods,
                "combo_range": config.combo_range,
                "portfolio_models": config.portfolio_models,
                "top_n": config.top_n,
                "strategy_max_evals": config.strategy_max_evals,
            },
            "steps": [],
        }

        # 1. 数据检查
        validate_result = self._execute_skill("validate_data", {"positions": config.positions, "periods": config.periods})
        results["steps"].append({"skill": "validate_data", "result": validate_result})
        if not validate_result.success:
            self._finalize_task(results)
            return results

        positions = config.positions
        if validate_result.data and isinstance(validate_result.data, dict):
            passed = validate_result.data.get("passed") or []
            if passed:
                positions = passed
            else:
                # Nothing usable.
                self._finalize_task(results)
                return results

        # 2. 并行执行各头寸的参数优化（2个worker，保护API）
        from backtest_system.skills.backtest_strategy import _run_optimization_pure
        
        strategy_results = {}
        n_workers = min(2, len(positions))  # 限制并发：保护API
        api_config = self.supervisor.db_api.api  # 可序列化配置
        
        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            # 提交任务
            futures = {
                executor.submit(
                    _run_optimization_pure,
                    pos,
                    config.periods,
                    parse_position(pos)["direction"],  # 需要导入 parse_position
                    api_config,
                    config.strategy_max_evals,
                ): pos
                for pos in positions
            }
            
            # 收集结果
            for future in as_completed(futures):
                position = futures[future]
                try:
                    result = future.result(timeout=600)  # 10分钟超时
                    strategy_results[position] = result
                    print(f"✓ {position} 完成")
                except Exception as e:
                    print(f"✗ {position} 失败: {e}")
                    strategy_results[position] = {"error": str(e)}
        
        # 将结果转换为 SkillResult 格式（兼容后续流程）
        for position, raw_result in strategy_results.items():
            if "error" not in raw_result:
                bt_result = SkillResult(success=True, data=raw_result)
            else:
                bt_result = SkillResult(success=False, error=raw_result["error"])
            results["steps"].append({"skill": "backtest_strategy", "position": position, "result": bt_result})

        # 3. 组合回测
        portfolio_result = self._execute_skill("backtest_portfolio", {
            "strategy_results": strategy_results,
            "combo_range": config.combo_range,
            "portfolio_models": config.portfolio_models,
            "periods": config.periods,
            "top_n": config.top_n,
        })
        results["steps"].append({"skill": "backtest_portfolio", "result": portfolio_result})

        # 4. 生成报告
        report_result = self._execute_skill("generate_report", {
            "results": results,
            "top_n": config.top_n
        })
        results["steps"].append({"skill": "generate_report", "result": report_result})

        self._finalize_task(results)
        return results

    def run_specified_mode(self, config: TaskConfig) -> dict:
        """指定模式：按配置执行"""
        task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.supervisor.set_task_id(task_id)

        # 先创建任务记录（带重试）
        now = datetime.now().replace(microsecond=0).isoformat(sep=" ")
        task_created = False
        for attempt in range(3):
            try:
                config_snapshot = {
                    "positions": config.positions,
                    "periods": config.periods,
                    "portfolio_models": config.portfolio_models,
                    "top_n": config.top_n,
                    "strategy_max_evals": config.strategy_max_evals,
                    "params": config.params,
                }
                payload = {
                    "task_id": task_id,
                    "mode": "specified",
                    "status": "running",
                    "positions": json.dumps(config.positions, ensure_ascii=True),
                    "periods": json.dumps(config.periods or [], ensure_ascii=True),
                    "portfolio_models": json.dumps(config.portfolio_models or [], ensure_ascii=True),
                    "top_n": int(config.top_n),
                    "config": json.dumps(config_snapshot, ensure_ascii=True),
                    "started_at": now,
                    "created_at": now,
                }
                payload = {k: v for k, v in payload.items() if v is not None}
                task_created = self.supervisor.db_api.create_task(payload)
            except Exception as e:
                task_created = False
                print(f"任务创建异常: {e}")
            if task_created:
                break
            print(f"任务创建重试 {attempt + 1}/3...")

        if not task_created:
            print("警告: 任务创建失败，日志将不会写入数据库")
            self.supervisor.disable_remote_logging()  # 禁用远程日志写入（保留本地日志）

        results = {
            "task_id": task_id,
            "mode": "specified",
            "config": {
                "positions": config.positions,
                "periods": config.periods,
                "portfolio_models": config.portfolio_models,
                "strategy_max_evals": config.strategy_max_evals,
            },
            "steps": [],
        }

        # 1. 数据检查
        validate_result = self._execute_skill("validate_data", {"positions": config.positions, "periods": config.periods})
        results["steps"].append({"skill": "validate_data", "result": validate_result})
        if not validate_result.success:
            self._finalize_task(results)
            return results

        positions = config.positions
        if validate_result.data and isinstance(validate_result.data, dict):
            passed = validate_result.data.get("passed") or []
            if passed:
                positions = passed
            else:
                self._finalize_task(results)
                return results

        # 2. 单策略回测
        strategy_results = {}
        for position in positions:
            bt_result = self._execute_skill("backtest_strategy", {
                "position": position,
                "periods": config.periods,
                "params": config.params,
                "max_evals": config.strategy_max_evals,
            })
            strategy_results[position] = bt_result
            results["steps"].append({"skill": "backtest_strategy", "position": position, "result": bt_result})

        # 3. 组合回测
        portfolio_result = self._execute_skill("backtest_portfolio", {
            "strategy_results": strategy_results,
            "portfolio_models": config.portfolio_models,
            "periods": config.periods,
            "top_n": config.top_n,
        })
        results["steps"].append({"skill": "backtest_portfolio", "result": portfolio_result})

        # 4. 生成报告
        report_result = self._execute_skill("generate_report", {"results": results})
        results["steps"].append({"skill": "generate_report", "result": report_result})

        self._finalize_task(results)
        return results

    def _finalize_task(self, results: dict) -> None:
        """
        Best-effort task status update (direct DB). No-op if BACKTEST_DB_URL is not configured.
        """
        task_id = results.get("task_id")
        if not task_id:
            return

        steps = results.get("steps", []) or []
        # Prefer explicit halted, then generic failures.
        status = "completed"
        error_message = None
        for step in steps:
            r = step.get("result")
            if not r:
                continue
            if getattr(r, "halted", False):
                status = "halted"
                error_message = getattr(r, "error", None)
                break
            if not getattr(r, "success", True):
                status = "failed"
                error_message = getattr(r, "error", None)

        try:
            self.supervisor.db_api.set_task_status(
                task_id,
                status,
                error_message=error_message,
                completed_at=datetime.now(),
            )
        except Exception:
            # Status update is best-effort; ignore.
            pass
