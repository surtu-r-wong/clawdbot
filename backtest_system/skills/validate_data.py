from backtest_system.skills.base import BaseSkill
from backtest_system.core.models import SkillResult
from backtest_system.core.exceptions import NetworkError
from backtest_system.skills.backtest_strategy import parse_position, _period_to_timedelta
from datetime import date, timedelta

class ValidateDataSkill(BaseSkill):
    """数据检查Skill - 只做检查，不做修改"""

    def __init__(self, db_api):
        self.db_api = db_api

    @property
    def name(self) -> str:
        return "validate_data"

    def execute(self, positions: list[str], periods: list[str] | None = None) -> SkillResult:
        passed = []
        failed = []
        warnings = []

        # Use the longest requested period to sanity-check history coverage.
        max_delta = None
        if periods:
            deltas = []
            for p in periods:
                try:
                    d = _period_to_timedelta(p)
                except Exception:
                    d = None
                if d is not None:
                    deltas.append(d)
            max_delta = max(deltas) if deltas else None

        for position in positions:
            try:
                result = self._validate_position(position, max_delta=max_delta)
                if result["status"] == "pass":
                    passed.append(position)
                elif result["status"] == "warning":
                    warnings.append({"position": position, "message": result["message"]})
                    passed.append(position)
                else:
                    failed.append({"position": position, "message": result["message"]})
            except NetworkError:
                # Let orchestrator/supervisor handle retries.
                raise
            except Exception as e:
                failed.append({"position": position, "message": str(e)})

        if not passed:
            return SkillResult(
                success=False,
                data={"passed": passed, "failed": failed, "warnings": warnings},
                error=f"所有头寸校验失败（{len(failed)}个）",
            )

        # Allow partial success: downstream steps will use `passed` subset.
        return SkillResult(
            success=True,
            data={"passed": passed, "failed": failed, "warnings": warnings},
        )

    def _validate_position(self, position: str, *, max_delta) -> dict:
        """验证头寸数据（解析头寸格式，检查各品种数据）"""
        parsed = parse_position(position)
        symbols = [sym for sym, _ in parsed['symbols']]

        # If a max period is provided, verify we have data near the start boundary.
        today = date.today()
        if max_delta is not None:
            start = today - max_delta
            # A small window near the boundary is enough to prove the history exists.
            window_end = start + timedelta(days=45)
            start_date = start.isoformat()
            end_date = window_end.isoformat()
        else:
            # Fallback: just check recent ~1y.
            start_date = (today - timedelta(days=365)).isoformat()
            end_date = today.isoformat()

        min_count = float("inf")
        for sym in symbols:
            try:
                data = self.db_api.get_continuous(sym, start_date=start_date, end_date=end_date, limit=10000)
            except NetworkError:
                raise
            except Exception as e:
                return {"status": "fail", "message": f"API请求失败 {sym}: {e}"}

            if not data:
                if max_delta is not None:
                    return {"status": "fail", "message": f"品种 {sym} 历史数据不足（起始窗口 {start_date}~{end_date} 无数据）"}
                return {"status": "fail", "message": f"品种 {sym} 数据不存在"}

            if len(data) > 0:
                sample = data[0]
                required = ["trade_date", "close_ba"]
                missing = [c for c in required if c not in sample]
                if missing:
                    return {"status": "fail", "message": f"品种 {sym} 缺少必需字段: {missing}"}

            min_count = min(min_count, len(data))

        if max_delta is None and min_count < 50:
            return {"status": "warning", "message": f"数据量较少: {min_count}条"}

        return {"status": "pass", "message": f"验证通过，共{min_count}条数据"}
