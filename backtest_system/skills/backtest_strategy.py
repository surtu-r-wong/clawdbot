import pandas as pd
import numpy as np
import re
import hashlib
from datetime import date, timedelta
from itertools import product
from typing import Iterable, Optional

from backtest_system.skills.base import BaseSkill
from backtest_system.core.models import SkillResult
from backtest_system.core.exceptions import DataValidationError, NetworkError


def parse_position(position: str) -> dict:
    """解析头寸格式（支持合约价值比例设置）
    - '多AU' -> {'direction': 'long', 'symbols': [('AU', 1)], 'total_weight': 1}
    - '多AU:2' -> {'direction': 'long', 'symbols': [('AU', 2)], 'total_weight': 2}
    - '多l-v:1:1' -> 做多L市值1份，做空V市值1份，总市值2份
    - '多l-v:2:1' -> 做多L市值2份，做空V市值1份，总市值3份
    """
    position = position.strip()
    if position.startswith('多'):
        direction = 'long'
        rest = position[1:]
    elif position.startswith('空'):
        direction = 'short'
        rest = position[1:]
    else:
        direction = 'long'
        rest = position

    # 解析比例（冒号分隔）
    parts = rest.split(':')
    symbols_part = parts[0]

    if '-' in symbols_part:
        # 对冲头寸
        sym_parts = symbols_part.split('-')
        sym_a = sym_parts[0].strip().upper()
        sym_b = sym_parts[1].strip().upper()
        ratio_a = float(parts[1]) if len(parts) > 1 else 1.0
        ratio_b = float(parts[2]) if len(parts) > 2 else 1.0
        total_weight = ratio_a + ratio_b
        if direction == 'long':
            return {'direction': direction, 'symbols': [(sym_a, ratio_a), (sym_b, -ratio_b)], 'total_weight': total_weight}
        else:
            return {'direction': direction, 'symbols': [(sym_a, -ratio_a), (sym_b, ratio_b)], 'total_weight': total_weight}
    else:
        # 单品种
        sym = symbols_part.strip().upper()
        ratio = float(parts[1]) if len(parts) > 1 else 1.0
        weight = ratio if direction == 'long' else -ratio
        return {'direction': direction, 'symbols': [(sym, weight)], 'total_weight': ratio}


_PERIOD_RE = re.compile(r"^\s*(?P<num>\d+)\s*(?P<unit>[ymd])\s*$", re.IGNORECASE)


def _period_to_timedelta(period: str) -> Optional[timedelta]:
    """
    Convert '3y'/'6m'/'90d' into a timedelta. 'all'/'max' returns None.
    Uses 365d/year and 30d/month approximation (good enough for slicing).
    """
    p = (period or "").strip().lower()
    if p in {"all", "max", ""}:
        return None
    m = _PERIOD_RE.match(p)
    if not m:
        raise ValueError(f"Invalid period: {period} (expected like 3y/6m/90d)")
    num = int(m.group("num"))
    unit = m.group("unit").lower()
    if unit == "y":
        return timedelta(days=365 * num)
    if unit == "m":
        return timedelta(days=30 * num)
    return timedelta(days=num)


def _to_py(v):
    # Numpy scalars -> Python types for JSON friendliness.
    return v.item() if isinstance(v, np.generic) else v


def _run_optimization_pure(
    position: str,
    periods: list[str],
    direction: str,
    api_config: object,
    max_evals: int,
) -> dict:
    """
    纯函数：在子进程中重建必要组件
    返回 JSON 可序列化的结果
    """
    from backtest_system.core.database import DatabaseAPI

    # 子进程里新建 DatabaseAPI（包括 Session）
    db_api = DatabaseAPI(None, api_config)
    skill = BacktestStrategySkill(db_api)
    
    # 执行回测
    result = skill.execute(
        position=position,
        periods=periods,
        max_evals=max_evals,
    )
    
    # 只返回可 JSON 序列化的数据
    if result.success and result.data:
        return {
            "position": result.data.get("position"),
            "direction": result.data.get("direction"),
            "best_period": result.data.get("best_period"),
            "best_params": result.data.get("best_params"),
            "metrics": result.data.get("metrics"),
            "dates": result.data.get("dates"),
            "daily_returns": result.data.get("daily_returns"),
        }
    else:
        return {"position": position, "error": result.error}


class BacktestStrategySkill(BaseSkill):
    """单策略参数优化和回测Skill"""

    def __init__(self, db_api):
        self.db_api = db_api
        self.default_param_grid = {
            'low_threshold': np.arange(1, 1.05, 0.01),
            'high_threshold': np.arange(1.45, 1.5, 0.01),
            'reverse_long_threshold': np.arange(1.1, 1.15, 0.01),
            'reverse_short_threshold': np.arange(1, 1.15, 0.01),
            'stop_loss_pct': np.arange(0.01, 0.03, 0.01),
            'threshold_adjust_pct': np.arange(0.05, 0.2, 0.05),
            'max_position_pct': [1],
            'position_increase_pct': np.arange(0.1, 0.3, 0.1),
            'profit_threshold_pct': np.arange(0.1, 0.3, 0.1),
            'drawdown_threshold_pct': np.arange(0.2, 0.5, 0.1)
        }
        self.initial_capital = 10000000
        self.slippage = 0.001
        self.commission_rate = 0.0002
        self.multiplier_A = 10
        self.multiplier_B = 10
        self.margin_rate = 0.08

    @property
    def name(self) -> str:
        return "backtest_strategy"

    def execute(
        self,
        position: str,
        periods: list[str],
        params: dict = None,
        max_evals: int = 2000,
    ) -> SkillResult:
        """执行单策略回测"""
        try:
            if not periods:
                periods = ["all"]

            parsed = parse_position(position)
            direction = parsed["direction"]

            # Load only what we need (plus buffer for rolling windows) to reduce API load.
            load_start = None
            load_end = date.today().isoformat()
            deltas = []
            for p in periods:
                d = _period_to_timedelta(p)
                if d is None:
                    deltas = []
                    break
                deltas.append(d)
            if deltas:
                buffer = timedelta(days=120)
                load_start = (date.today() - (max(deltas) + buffer)).isoformat()

            df_full = self._load_data(position, start_date=load_start, end_date=load_end, limit=10000)
            if df_full is None or len(df_full) < 3:
                return SkillResult(success=False, error=f"无法加载 {position} 的数据")

            period_results: dict[str, dict] = {}
            for period in periods:
                df = self._slice_period(df_full, period)
                if df is None or len(df) < 3:
                    continue

                best_params = params if params else self._optimize_params(df, direction=direction, max_evals=max_evals)
                metrics, daily_returns = self._run_backtest(df, best_params, direction=direction)

                period_results[period] = {
                    "best_params": {k: _to_py(v) for k, v in (best_params or {}).items()},
                    "metrics": metrics,
                    "dates": [d.isoformat() for d in daily_returns.index.to_pydatetime()],
                    "daily_returns": [float(x) for x in daily_returns.values],
                }

            if not period_results:
                return SkillResult(success=False, error=f"{position} 无可用周期数据")

            # Pick the best period by Sharpe.
            best_period = max(
                period_results.keys(),
                key=lambda p: float(period_results[p]["metrics"].get("sharpe_ratio", float("-inf"))),
            )
            best = period_results[best_period]

            return SkillResult(
                success=True,
                data={
                    "position": position,
                    "direction": direction,
                    "best_period": best_period,
                    "best_params": best["best_params"],
                    "metrics": best["metrics"],
                    "dates": best["dates"],
                    "daily_returns": best["daily_returns"],
                    "period_results": period_results,
                },
            )
        except NetworkError:
            # Let orchestrator/supervisor apply retry logic.
            raise
        except DataValidationError as e:
            return SkillResult(success=False, error=str(e))
        except Exception as e:
            return SkillResult(success=False, error=str(e))

    def _slice_period(self, df: pd.DataFrame, period: str) -> pd.DataFrame:
        df = df.sort_index()
        delta = _period_to_timedelta(period)
        if delta is None:
            return df
        end = df.index.max()
        start = end - delta
        return df[df.index >= start]

    def _load_data(
        self,
        position: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        """通过API加载连续合约数据，支持单品种和对冲头寸（按合约价值比例）"""
        parsed = parse_position(position)
        symbols = parsed["symbols"]
        total_weight = float(parsed["total_weight"]) if parsed.get("total_weight") else 1.0

        dfs: dict[str, pd.DataFrame] = {}
        for sym, _weight in symbols:
            data = self.db_api.get_continuous(sym, start_date=start_date, end_date=end_date, limit=limit)
            if not data:
                raise DataValidationError(f"无数据: {sym}")
            df = pd.DataFrame(data)
            required = {"trade_date", "close_ba"}
            missing = required.difference(df.columns)
            if missing:
                raise DataValidationError(f"{sym} 缺少必需字段: {sorted(missing)}")

            df["datetime"] = pd.to_datetime(df["trade_date"])
            df = df.sort_values("datetime")
            # Defensive: some upstreams may return duplicate trade_date rows; keep the last.
            df = df.drop_duplicates(subset=["datetime"], keep="last")
            close = df["close_ba"].astype(float)
            ret = df["daily_return"].astype(float) if "daily_return" in df.columns else close.pct_change()
            leg = pd.DataFrame({"close": close.values, "daily_return": ret.values}, index=df["datetime"])
            leg = leg[~leg.index.duplicated(keep="last")].sort_index()
            dfs[sym] = leg

        # 单品种：直接用该品种数据（方向已在 weight 中体现）
        if len(symbols) == 1:
            sym, weight = symbols[0]
            result = dfs[sym].copy()
            result["daily_return"] = result["daily_return"] * (1.0 if weight > 0 else -1.0)
            result = result.dropna()
            result = result[~result.index.duplicated(keep="last")].sort_index()
            return result

        # 对冲头寸：按日期对齐
        merged = None
        for sym, weight in symbols:
            df = dfs[sym].copy()
            df = df.rename(columns={"close": f"close_{sym}", "daily_return": f"ret_{sym}"})
            if merged is None:
                merged = df
            else:
                merged = merged.join(df, how="inner")

        if merged is None or len(merged) == 0:
            raise DataValidationError(f"{position} 无法对齐两腿数据")

        # 组合收益：按合约价值比例（可近似为固定权重组合）
        result = pd.DataFrame(index=merged.index)
        result["daily_return"] = (
            sum(merged[f"ret_{sym}"] * float(weight) for sym, weight in symbols) / total_weight
        )

        # 信号价格：用多头腿/空头腿的价格比值（更适合阈值类策略）
        long_leg = next(((sym, w) for sym, w in symbols if w > 0), None)
        short_leg = next(((sym, w) for sym, w in symbols if w < 0), None)
        if not long_leg or not short_leg:
            # Fallback: 退化为加权绝对价格和
            result["close"] = sum(merged[f"close_{sym}"] * abs(float(weight)) for sym, weight in symbols)
        else:
            long_sym, long_w = long_leg
            short_sym, short_w = short_leg
            num = merged[f"close_{long_sym}"] * abs(float(long_w))
            den = merged[f"close_{short_sym}"] * abs(float(short_w))
            result["close"] = (num / den).replace([np.inf, -np.inf], np.nan)

        result = result.dropna()
        result = result[~result.index.duplicated(keep="last")].sort_index()
        return result

    def _optimize_params(self, df: pd.DataFrame, *, direction: str, max_evals: int) -> dict:
        """随机采样/小规模网格搜索参数优化（避免组合爆炸）"""
        if max_evals <= 0:
            return self._default_params()

        seed_src = f"{direction}|{df.index.min()}|{df.index.max()}".encode("utf-8")
        seed = int(hashlib.md5(seed_src).hexdigest()[:8], 16)
        rng = np.random.default_rng(seed)
        best_sharpe = float("-inf")
        best_params = None

        for param_dict in self._iter_param_candidates(max_evals, rng):
            metrics, _ = self._run_backtest(df, param_dict, direction=direction)
            sharpe = float(metrics.get("sharpe_ratio", 0) or 0)
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_params = param_dict

        return best_params or self._default_params()

    def _iter_param_candidates(self, max_evals: int, rng: np.random.Generator) -> Iterable[dict]:
        keys = list(self.default_param_grid.keys())
        values_list = [list(self.default_param_grid[k]) for k in keys]

        total = 1
        for v in values_list:
            total *= max(1, len(v))

        if total <= max_evals:
            for combo in product(*values_list):
                yield {k: _to_py(v) for k, v in zip(keys, combo)}
            return

        for _ in range(max_evals):
            candidate = {}
            for k, vs in zip(keys, values_list):
                candidate[k] = _to_py(rng.choice(vs))
            yield candidate

    def _default_params(self) -> dict:
        # A deterministic fallback (use the first element of each grid).
        return {k: _to_py(list(v)[0]) for k, v in self.default_param_grid.items()}

    def _run_backtest(self, df: pd.DataFrame, params: dict, *, direction: str) -> tuple[dict, pd.Series]:
        """运行回测：阈值策略(基于 close 信号) -> exposure -> 组合 daily_return"""
        if "daily_return" not in df.columns or "close" not in df.columns:
            return self._empty_metrics(), pd.Series(dtype=float)

        base_returns = df["daily_return"].astype(float).fillna(0.0)
        signal = self._compute_signal(df["close"].astype(float))
        strategy_returns, n_trades = self._simulate_threshold_strategy(
            base_returns=base_returns,
            signal=signal,
            direction=direction,
            params=params or {},
        )

        metrics = self._calculate_metrics(strategy_returns)
        metrics["n_trades"] = int(n_trades)
        return metrics, strategy_returns

    def _compute_signal(self, close: pd.Series, window: int = 60) -> pd.Series:
        ma = close.rolling(window=window, min_periods=max(5, window // 3)).mean()
        signal = (close / ma).replace([np.inf, -np.inf], np.nan)
        return signal.bfill().fillna(1.0)

    def _simulate_threshold_strategy(
        self,
        *,
        base_returns: pd.Series,
        signal: pd.Series,
        direction: str,
        params: dict,
    ) -> tuple[pd.Series, int]:
        """
        A simple timing strategy:
          - long direction: enter when signal <= low_threshold, exit when signal >= reverse_long_threshold
          - short direction: enter when signal >= high_threshold, exit when signal <= reverse_short_threshold

        Position sizing:
          - scale in by position_increase_pct as signal becomes more extreme, using threshold_adjust_pct as step.

        Risk:
          - stop_loss_pct (trade-level)
          - profit_threshold_pct (trade-level take profit)
          - drawdown_threshold_pct (trade-level trailing drawdown)
        """
        low_th = float(params.get("low_threshold", 1.02))
        high_th = float(params.get("high_threshold", 1.45))
        rev_long = float(params.get("reverse_long_threshold", 1.12))
        rev_short = float(params.get("reverse_short_threshold", 1.08))
        stop_loss = float(params.get("stop_loss_pct", 0.02))
        th_step = float(params.get("threshold_adjust_pct", 0.05))
        max_pos = float(params.get("max_position_pct", 1.0))
        pos_step = float(params.get("position_increase_pct", 0.2))
        take_profit = float(params.get("profit_threshold_pct", 0.2))
        max_trade_dd = float(params.get("drawdown_threshold_pct", 0.3))

        cost_rate = float(self.slippage) + float(self.commission_rate)

        idx = base_returns.index
        rets = base_returns.values
        sig = signal.reindex(idx).fillna(1.0).values

        exposure = 0.0
        next_exposure = 0.0
        entry_equity = 1.0
        trade_peak = 1.0
        trade_equity = 1.0
        in_trade = False
        n_trades = 0
        n_adds = 0

        out = np.zeros(len(idx), dtype=float)

        def want_enter_long(s: float) -> bool:
            return s <= low_th

        def want_exit_long(s: float) -> bool:
            return s >= rev_long

        def want_enter_short(s: float) -> bool:
            return s >= high_th

        def want_exit_short(s: float) -> bool:
            return s <= rev_short

        for i in range(len(idx)):
            # Apply today's return with yesterday's exposure (close->close convention).
            out[i] = exposure * float(rets[i])

            # Update trade equity for risk checks.
            trade_equity *= (1.0 + out[i])
            if in_trade:
                trade_peak = max(trade_peak, trade_equity)

            # Decide next exposure based on today's signal (trade at close).
            s = float(sig[i])
            next_exposure = exposure

            if direction == "long":
                if not in_trade and want_enter_long(s):
                    next_exposure = min(max_pos, pos_step)
                    in_trade = True
                    n_trades += 1
                    n_adds = 0
                    entry_equity = trade_equity
                    trade_peak = trade_equity
                elif in_trade:
                    # Scale in if signal moves further down in steps.
                    add_level = low_th - th_step * (n_adds + 1)
                    if s <= add_level and next_exposure < max_pos:
                        next_exposure = min(max_pos, next_exposure + pos_step)
                        n_adds += 1

                    trade_ret = trade_equity / entry_equity - 1.0
                    trade_dd = trade_equity / trade_peak - 1.0 if trade_peak else 0.0
                    if (
                        want_exit_long(s)
                        or trade_ret <= -stop_loss
                        or trade_ret >= take_profit
                        or trade_dd <= -max_trade_dd
                    ):
                        next_exposure = 0.0
                        in_trade = False
            else:  # short
                if not in_trade and want_enter_short(s):
                    next_exposure = min(max_pos, pos_step)
                    in_trade = True
                    n_trades += 1
                    n_adds = 0
                    entry_equity = trade_equity
                    trade_peak = trade_equity
                elif in_trade:
                    add_level = high_th + th_step * (n_adds + 1)
                    if s >= add_level and next_exposure < max_pos:
                        next_exposure = min(max_pos, next_exposure + pos_step)
                        n_adds += 1

                    trade_ret = trade_equity / entry_equity - 1.0
                    trade_dd = trade_equity / trade_peak - 1.0 if trade_peak else 0.0
                    if (
                        want_exit_short(s)
                        or trade_ret <= -stop_loss
                        or trade_ret >= take_profit
                        or trade_dd <= -max_trade_dd
                    ):
                        next_exposure = 0.0
                        in_trade = False

            # Transaction cost when adjusting exposure (charged on decision day).
            delta = abs(next_exposure - exposure)
            if delta:
                out[i] -= delta * cost_rate

            exposure = next_exposure

        return pd.Series(out, index=idx, name="strategy_return"), n_trades

    def _empty_metrics(self) -> dict:
        return {
            "sharpe_ratio": 0.0,
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "annualized_return": 0.0,
            "annualized_volatility": 0.0,
            "n_days": 0,
        }

    def _calculate_metrics(self, returns: pd.Series) -> dict:
        returns = returns.dropna()
        if len(returns) < 2:
            return self._empty_metrics()

        cum = (1.0 + returns).cumprod()
        total_return = float(cum.iloc[-1] - 1.0)

        n = len(returns)
        annualized_return = float((1.0 + total_return) ** (252.0 / n) - 1.0) if n > 0 else 0.0
        vol = float(returns.std(ddof=0) * np.sqrt(252.0))
        sharpe = float((returns.mean() / returns.std(ddof=0)) * np.sqrt(252.0)) if returns.std(ddof=0) != 0 else 0.0

        peak = cum.cummax()
        max_dd = float((cum / peak - 1.0).min())

        return {
            "sharpe_ratio": sharpe,
            "total_return": total_return,
            "max_drawdown": max_dd,
            "annualized_return": annualized_return,
            "annualized_volatility": vol,
            "n_days": int(n),
        }
