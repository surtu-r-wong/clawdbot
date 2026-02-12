import os
from datetime import datetime
import pandas as pd
import json

# Force a headless-friendly backend (common in servers/CI).
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from backtest_system.skills.base import BaseSkill
from backtest_system.core.models import SkillResult

class GenerateReportSkill(BaseSkill):
    """报告生成Skill - 只做报告生成，不做计算"""

    def __init__(self, db_api, output_dir: str = "output"):
        self.db_api = db_api
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    @property
    def name(self) -> str:
        return "generate_report"

    def execute(self, results: dict, top_n: int = 10) -> SkillResult:
        """生成报告"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            task_id = results.get("task_id", timestamp)

            # 生成Excel报告
            excel_path = self._generate_excel(results, task_id, top_n=top_n)

            # 生成可视化图表
            charts = self._generate_charts(results, task_id)

            # 记录到数据库
            db_record_id = self._save_to_db(results, excel_path, task_id)

            return SkillResult(
                success=True,
                data={
                    "excel_path": excel_path,
                    "charts": charts,
                    "db_record_id": db_record_id
                }
            )
        except Exception as e:
            return SkillResult(success=False, error=str(e))

    def _generate_excel(self, results: dict, task_id: str, *, top_n: int = 10) -> str:
        """生成Excel报告"""
        excel_path = os.path.join(self.output_dir, f"{task_id}.xlsx")

        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            cfg = results.get("config") or {}

            # Summary
            summary_rows = [
                {"key": "task_id", "value": task_id},
                {"key": "mode", "value": results.get("mode")},
                {"key": "timestamp", "value": datetime.now().isoformat()},
                {"key": "positions", "value": ",".join((cfg.get("positions") or []))},
                {"key": "periods", "value": ",".join((cfg.get("periods") or []))},
                {"key": "combo_range", "value": str(cfg.get("combo_range"))},
                {"key": "portfolio_models", "value": ",".join((cfg.get("portfolio_models") or []))},
                {"key": "top_n", "value": str(cfg.get("top_n"))},
                {"key": "strategy_max_evals", "value": str(cfg.get("strategy_max_evals"))},
            ]
            pd.DataFrame(summary_rows).to_excel(writer, sheet_name="Summary", index=False)

            steps = results.get("steps", []) or []

            # Steps
            steps_data = []
            for step in steps:
                r = step.get("result")
                steps_data.append({
                    "skill": step.get("skill"),
                    "position": step.get("position", ""),
                    "success": bool(getattr(r, "success", False)) if r is not None else False,
                    "error": getattr(r, "error", None) if r is not None else None,
                })
            pd.DataFrame(steps_data).to_excel(writer, sheet_name="Steps", index=False)

            # Validation details
            validate = next((s for s in steps if s.get("skill") == "validate_data"), None)
            if validate and validate.get("result") and getattr(validate["result"], "data", None):
                vdata = validate["result"].data or {}
                rows = []
                for p in vdata.get("passed", []) or []:
                    rows.append({"position": p, "status": "pass", "message": ""})
                for w in vdata.get("warnings", []) or []:
                    rows.append({"position": w.get("position"), "status": "warning", "message": w.get("message")})
                for f in vdata.get("failed", []) or []:
                    rows.append({"position": f.get("position"), "status": "fail", "message": f.get("message")})
                pd.DataFrame(rows).to_excel(writer, sheet_name="Validation", index=False)

            # Strategy results (flatten per period)
            strat_rows = []
            for step in steps:
                if step.get("skill") != "backtest_strategy" or not step.get("result"):
                    continue
                r = step["result"]
                if not (r.success and r.data):
                    continue
                pos = r.data.get("position") or step.get("position")
                direction = r.data.get("direction")
                best_period = r.data.get("best_period")
                pr = r.data.get("period_results") or {}
                if isinstance(pr, dict):
                    for period, item in pr.items():
                        m = (item or {}).get("metrics") or {}
                        strat_rows.append({
                            "position": pos,
                            "direction": direction,
                            "period": period,
                            "is_best_period": period == best_period,
                            "sharpe_ratio": m.get("sharpe_ratio"),
                            "annualized_return": m.get("annualized_return"),
                            "annualized_volatility": m.get("annualized_volatility"),
                            "max_drawdown": m.get("max_drawdown"),
                            "total_return": m.get("total_return"),
                            "n_trades": m.get("n_trades"),
                            "n_days": m.get("n_days"),
                            "best_params": json.dumps((item or {}).get("best_params") or {}, ensure_ascii=True),
                        })
            if strat_rows:
                pd.DataFrame(strat_rows).to_excel(writer, sheet_name="Strategies", index=False)

            # Portfolio results (top-N per period)
            port_step = next((s for s in steps if s.get("skill") == "backtest_portfolio"), None)
            if port_step and port_step.get("result") and getattr(port_step["result"], "data", None):
                pdata = port_step["result"].data or {}
                period_results = pdata.get("period_results") or {}
                port_rows = []
                for period, item in period_results.items():
                    top = (item or {}).get("top") or []
                    for rank, entry in enumerate(top[:top_n], start=1):
                        m = (entry or {}).get("metrics") or {}
                        port_rows.append({
                            "period": period,
                            "rank": rank,
                            "model": entry.get("model"),
                            "positions": ",".join(entry.get("positions") or []),
                            "sharpe_ratio": m.get("sharpe_ratio"),
                            "annualized_return": m.get("annualized_return"),
                            "annualized_volatility": m.get("annualized_volatility"),
                            "max_drawdown": m.get("max_drawdown"),
                            "total_return": m.get("total_return"),
                            "n_days": m.get("n_days"),
                            "weights": json.dumps(entry.get("weights") or {}, ensure_ascii=True),
                        })
                if port_rows:
                    pd.DataFrame(port_rows).to_excel(writer, sheet_name="Portfolios", index=False)

        return excel_path

    def _generate_charts(self, results: dict, task_id: str) -> list:
        """生成可视化图表"""
        charts: list[str] = []
        steps = results.get("steps", []) or []
        port_step = next((s for s in steps if s.get("skill") == "backtest_portfolio"), None)
        if not (port_step and port_step.get("result") and getattr(port_step["result"], "data", None)):
            return charts

        best = (port_step["result"].data or {}).get("best") or {}
        rets = best.get("portfolio_returns") or []
        dates = best.get("dates") or []
        if not rets or not dates or len(rets) != len(dates):
            return charts

        try:
            idx = pd.to_datetime(pd.Series(dates))
            s = pd.Series(rets, index=idx, dtype=float)
            equity = (1.0 + s).cumprod()

            path = os.path.join(self.output_dir, f"{task_id}_equity.png")
            plt.figure(figsize=(10, 4))
            plt.plot(equity.index, equity.values)
            plt.title(f"Equity Curve ({best.get('period')}, {best.get('model')})")
            plt.tight_layout()
            plt.savefig(path)
            plt.close()
            charts.append(path)
        except Exception:
            # Charts are optional; ignore.
            pass

        return charts

    def _save_to_db(self, results: dict, excel_path: str, task_id: str) -> int:
        """记录到数据库"""
        if not self.db_api:
            return 0

        steps = results.get("steps", []) or []
        port_step = next((s for s in steps if s.get("skill") == "backtest_portfolio"), None)
        best = {}
        if port_step and port_step.get("result") and getattr(port_step["result"], "data", None):
            best = (port_step["result"].data or {}).get("best") or {}

        period = best.get("period") or "unknown"
        metrics = best.get("metrics") or {}
        positions = best.get("positions") or []
        model = best.get("model") or ""
        weights = best.get("weights") or {}

        # Keep API payload backward-compatible by storing extra fields inside metrics JSON.
        metrics_payload = dict(metrics)
        metrics_payload.update({"positions": positions, "model": model, "weights": weights})

        record = {
            "task_id": task_id,
            "result_type": "portfolio",
            "period": period,
            "metrics": json.dumps(metrics_payload, ensure_ascii=True) if metrics_payload else "{}",
            "excel_path": excel_path,
            "created_at": datetime.now().isoformat()
        }
        try:
            return self.db_api.write_result(record)
        except Exception as e:
            print(f"结果写入数据库失败: {e}")
            return 0
