import pandas as pd
import numpy as np
from scipy.optimize import minimize
from itertools import combinations
from backtest_system.skills.base import BaseSkill
from backtest_system.core.models import SkillResult


class BacktestPortfolioSkill(BaseSkill):
    """组合回测Skill - 不做参数优化"""

    def __init__(self, db_api=None):
        self.db_api = db_api

    @property
    def name(self) -> str:
        return "backtest_portfolio"

    def execute(self, strategy_results: dict, combo_range: tuple = None,
                portfolio_models: list = None, periods: list = None, top_n: int | None = None) -> SkillResult:
        """执行组合回测"""
        try:
            if portfolio_models is None:
                portfolio_models = ["mean_variance", "equal_weight"]

            # Extract per-period returns for each strategy.
            print(f"[DEBUG backtest_portfolio] ===== 开始解析 strategy_results =====")
            print(f"[DEBUG] strategy_results 类型: {type(strategy_results)}")
            
            per_position_period: dict[str, dict[str, dict]] = {}
            for position, result in strategy_results.items():
                result_type = type(result).__name__
                print(f"[DEBUG] 处理 {position}, result 类型: {result_type}")
                
                # 防御性处理：检查所有可能的数据结构
                period_data = None
                
                if isinstance(result, dict):
                    # 情况1：result 是字典
                    print(f"[DEBUG]   字典键: {result.keys()}")
                    if "period_results" in result:
                        period_data = result["period_results"]
                    elif "data" in result and isinstance(result["data"], dict):
                        period_data = result["data"].get("period_results")
                
                elif hasattr(result, 'data') and result.data:
                    # 情况2：result 是 SkillResult 对象
                    if isinstance(result.data, dict):
                        period_data = result.data.get("period_results")
                
                if period_data and isinstance(period_data, dict):
                    per_position_period[position] = period_data
                    print(f"[DEBUG]   ✓ 成功提取 period_results，周期: {list(period_data.keys())}")
                else:
                    print(f"[DEBUG]   ✗ 无法提取 period_results")
            
            print(f"[DEBUG] 最终 per_position_period: {list(per_position_period.keys())}")
            print(f"[DEBUG] ===== 解析完成 =====")
            
            if len(per_position_period) < 2:
                return SkillResult(success=False, error="需要至少2个成功的策略结果进行组合")

            # Periods to run: use requested order if provided, else intersection.
            available_periods = None
            for _, pr in per_position_period.items():
                keys = set(pr.keys())
                available_periods = keys if available_periods is None else (available_periods & keys)
            available_periods = sorted(available_periods or [])

            if periods:
                periods_to_run = [p for p in periods if p in available_periods]
            else:
                periods_to_run = available_periods

            if not periods_to_run:
                return SkillResult(success=False, error="策略结果的周期不一致，无法组合")

            positions_all = list(per_position_period.keys())
            if combo_range:
                min_size, max_size = combo_range
            else:
                min_size, max_size = 2, len(positions_all)

            period_results: dict[str, dict] = {}
            best_overall = None

            for period in periods_to_run:
                returns_series = {}
                for position, pr in per_position_period.items():
                    item = pr.get(period)
                    if not item:
                        continue
                    dates = item.get("dates") or []
                    rets = item.get("daily_returns") or []
                    if not dates or not rets or len(dates) != len(rets):
                        continue
                    idx = pd.to_datetime(pd.Index(dates))
                    s = pd.Series(pd.Series(rets, dtype=float).values, index=idx, dtype=float)
                    # Some data sources may contain duplicate trade_date rows; pandas alignment
                    # will fail later unless we de-duplicate the index.
                    if not s.index.is_unique:
                        s = s[~s.index.duplicated(keep="last")]
                    returns_series[position] = s.sort_index()

                if len(returns_series) < 2:
                    continue

                all_results = []
                usable_positions = list(returns_series.keys())
                for size in range(min_size, min(max_size + 1, len(usable_positions) + 1)):
                    for combo in combinations(usable_positions, size):
                        combo_returns = pd.DataFrame({p: returns_series[p] for p in combo}).dropna(how="any")
                        if len(combo_returns) < 2:
                            continue
                        for model in portfolio_models:
                            weights = self._get_weights(combo_returns, model)
                            portfolio_returns = combo_returns.dot(weights)
                            metrics = self._calculate_metrics(portfolio_returns)
                            all_results.append({
                                "period": period,
                                "positions": list(combo),
                                "model": model,
                                "weights": dict(zip(combo, weights.tolist())),
                                "metrics": metrics,
                            })

                all_results.sort(key=lambda x: float(x["metrics"].get("sharpe_ratio", 0) or 0), reverse=True)
                if not all_results:
                    continue

                top = all_results[: max(1, int(top_n))] if top_n else all_results
                best = all_results[0]

                # Recompute best returns for storage/report.
                best_combo = best["positions"]
                best_model = best["model"]
                combo_returns = pd.DataFrame({p: returns_series[p] for p in best_combo}).dropna(how="any")
                weights = self._get_weights(combo_returns, best_model)
                portfolio_returns = combo_returns.dot(weights)

                period_results[period] = {
                    "best": {
                        **best,
                        "dates": [d.isoformat() for d in portfolio_returns.index.to_pydatetime()],
                        "portfolio_returns": [float(x) for x in portfolio_returns.values],
                    },
                    "top": top,
                }

                if best_overall is None:
                    best_overall = period_results[period]["best"]
                else:
                    if float(best["metrics"].get("sharpe_ratio", 0) or 0) > float(
                        best_overall["metrics"].get("sharpe_ratio", 0) or 0
                    ):
                        best_overall = period_results[period]["best"]

            if not period_results or not best_overall:
                return SkillResult(success=False, error="无法生成有效组合")

            return SkillResult(
                success=True,
                data={
                    "best": best_overall,
                    "period_results": period_results,
                    # Backwards-friendly top-level fields
                    "period": best_overall.get("period"),
                    "weights": best_overall.get("weights"),
                    "portfolio_returns": best_overall.get("portfolio_returns"),
                    "dates": best_overall.get("dates"),
                    "metrics": best_overall.get("metrics"),
                    "positions": best_overall.get("positions"),
                    "model": best_overall.get("model"),
                },
            )
        except Exception as e:
            return SkillResult(success=False, error=str(e))

    def _get_weights(self, returns_df: pd.DataFrame, model: str) -> np.ndarray:
        """根据模型获取权重"""
        num_strats = returns_df.shape[1]
        if model == "equal_weight":
            return np.array([1.0 / num_strats] * num_strats)
        elif model == "mean_variance":
            return self._optimize_weights(returns_df)
        return np.array([1.0 / num_strats] * num_strats)

    def _optimize_weights(self, returns_df: pd.DataFrame) -> np.ndarray:
        """均值-方差优化"""
        returns_df = returns_df.dropna(how="any")
        if len(returns_df) < 2:
            num_strats = returns_df.shape[1]
            return np.array([1.0 / num_strats] * num_strats) if num_strats else np.array([])

        num_strats = returns_df.shape[1]
        mean_returns = returns_df.mean() * 252
        cov_matrix = returns_df.cov() * 252

        def neg_sharpe(weights):
            port_return = np.dot(weights, mean_returns)
            port_vol = np.sqrt(np.dot(weights.T, np.dot(cov_matrix, weights)))
            return -(port_return / port_vol) if port_vol != 0 else 0

        constraints = {'type': 'eq', 'fun': lambda x: np.sum(x) - 1}
        bounds = tuple((0, 1) for _ in range(num_strats))
        init_guess = np.array([1.0 / num_strats] * num_strats)

        result = minimize(neg_sharpe, init_guess, method='SLSQP', bounds=bounds, constraints=constraints)
        return result.x if result.success else init_guess

    def _calculate_metrics(self, returns: pd.Series) -> dict:
        """计算绩效指标"""
        returns = returns.dropna()
        if len(returns) < 2:
            return {"sharpe_ratio": 0.0, "total_return": 0.0, "max_drawdown": 0.0, "annualized_return": 0.0, "annualized_volatility": 0.0}

        cum_returns = (1 + returns).cumprod()
        total_return = cum_returns.iloc[-1] - 1
        annualized_return = (1 + total_return) ** (252 / len(returns)) - 1
        std = returns.std(ddof=0)
        annualized_vol = std * np.sqrt(252)
        sharpe_ratio = (returns.mean() / std) * np.sqrt(252) if std != 0 else 0.0
        max_drawdown = (cum_returns / cum_returns.cummax() - 1).min()

        return {
            "sharpe_ratio": float(sharpe_ratio),
            "total_return": float(total_return),
            "max_drawdown": float(max_drawdown),
            "annualized_return": float(annualized_return),
            "annualized_volatility": float(annualized_vol),
            "n_days": int(len(returns)),
        }
