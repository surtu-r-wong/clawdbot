import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import sql
from typing import Optional
import requests
from collections import OrderedDict
from datetime import date, timedelta

from backtest_system.core.config import ApiConfig
from backtest_system.core.exceptions import ConfigurationError, ModuleError, NetworkError

class DatabaseAPI:
    """
    数据/任务/日志访问层。

    - 行情/连续合约：HTTP API（read_url）
    - 任务/日志/结果写入：HTTP API（write_url）
    - 历史查询/部分更新：可选直连 Postgres（db_url）
    """

    def __init__(self, db_url: Optional[str], api: ApiConfig):
        self.connection_string = db_url
        self.api = api
        self._conn = None
        self._session = requests.Session()
        # Avoid surprising failures when the environment exports a global proxy
        # (common on dev laptops). Can be enabled via BACKTEST_API_TRUST_ENV=true.
        self._session.trust_env = bool(getattr(api, "trust_env", False))
        # Small in-memory cache to reduce repeat API calls during retries.
        self._continuous_cache: "OrderedDict[tuple, list[dict]]" = OrderedDict()
        self._continuous_cache_max = 64

    def connect(self):
        if not self.connection_string:
            raise ConfigurationError("Missing BACKTEST_DB_URL (required for direct SQL reads/writes)")
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.connection_string)
        return self._conn

    def close(self):
        if self._conn and not self._conn.closed:
            self._conn.close()

    def _api_headers(self):
        headers = {"Accept": "application/json"}
        if self.api.token:
            headers["Authorization"] = f"Bearer {self.api.token}"
        return headers

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        timeout = kwargs.pop("timeout", self.api.timeout_seconds)
        try:
            resp = self._session.request(
                method,
                url,
                headers=self._api_headers(),
                timeout=timeout,
                **kwargs,
            )
            resp.raise_for_status()
            return resp
        except requests.HTTPError as e:
            status = None
            body = ""
            if e.response is not None:
                status = e.response.status_code
                try:
                    body = (e.response.text or "").strip()
                except Exception:
                    body = ""
            if body:
                body = body.replace("\n", " ")[:300]

            msg = f"{method} {url} -> HTTP {status}"
            if body:
                msg = f"{msg} ({body})"

            # 4xx are usually auth/config/user errors -> don't retry.
            if status is not None and 400 <= status < 500:
                raise ModuleError(msg) from e

            # 5xx -> retryable network/upstream failures.
            raise NetworkError(msg) from e
        except requests.RequestException as e:
            raise NetworkError(f"{method} {url} -> {e}") from e

    def get_futures_daily(
        self,
        symbols: list,
        start_date: str,
        end_date: str,
        *,
        limit: int | None = None,
    ) -> list[dict]:
        """通过API读取期货日线数据"""
        url = f"{self.api.read_url}/api/futures/daily"
        params = {
            "symbols": ",".join(symbols),
            "start_date": start_date,
            "end_date": end_date
        }
        if limit is not None:
            params["limit"] = int(limit)
        resp = self._request("GET", url, params=params)
        payload = resp.json()
        return payload.get("data", []) if isinstance(payload, dict) else []

    def get_symbol_daily(
        self,
        symbol: str,
        start_date: str = None,
        end_date: str = None,
        *,
        limit: int | None = None,
    ) -> list[dict]:
        """通过API读取单个品种日线数据"""
        url = f"{self.api.read_url}/api/data/daily/{symbol}"
        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if limit is not None:
            params["limit"] = int(limit)
        resp = self._request("GET", url, params=params)
        payload = resp.json()
        return payload.get("data", []) if isinstance(payload, dict) else []

    def get_continuous(
        self,
        base_symbol: str,
        start_date: str = None,
        end_date: str = None,
        *,
        limit: int | None = None,
    ) -> list[dict]:
        """通过API读取连续合约数据"""
        base_symbol = (base_symbol or "").strip().upper()
        url = f"{self.api.read_url}/api/continuous/{base_symbol}"
        params = {}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if limit is not None:
            params["limit"] = int(limit)

        cache_key = (base_symbol, params.get("start_date"), params.get("end_date"), params.get("limit"))
        if cache_key in self._continuous_cache:
            data = self._continuous_cache.pop(cache_key)
            self._continuous_cache[cache_key] = data
            return data

        try:
            resp = self._request("GET", url, params=params)
            payload = resp.json()
            data = payload.get("data", []) if isinstance(payload, dict) else []
        except NetworkError as e:
            # For large ranges, the backend may time out; fall back to chunked fetch when possible.
            if start_date and end_date and self._is_timeout(e):
                data = self._get_continuous_chunked(
                    base_symbol,
                    start_date=start_date,
                    end_date=end_date,
                    limit=limit,
                )
            else:
                raise

        # Update cache (LRU).
        self._continuous_cache[cache_key] = data
        if len(self._continuous_cache) > self._continuous_cache_max:
            self._continuous_cache.popitem(last=False)
        return data

    def _is_timeout(self, err: Exception) -> bool:
        cause = getattr(err, "__cause__", None)
        if cause is not None:
            try:
                if isinstance(cause, requests.exceptions.Timeout):
                    return True
            except Exception:
                pass
        msg = str(err).lower()
        return "timed out" in msg or "timeout" in msg

    def _get_continuous_chunked(
        self,
        base_symbol: str,
        *,
        start_date: str,
        end_date: str,
        limit: int | None,
        chunk_days: int = 365,
    ) -> list[dict]:
        """
        Fetch continuous data by smaller date ranges to avoid server-side timeouts on large queries.
        """
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        except Exception:
            # If parsing fails, just re-raise as a network error to trigger supervisor handling.
            raise NetworkError(f"Invalid date range for chunked fetch: {start_date}~{end_date}")

        url = f"{self.api.read_url}/api/continuous/{base_symbol}"

        all_rows: list[dict] = []
        cur = start
        step = timedelta(days=max(1, int(chunk_days)))
        while cur <= end:
            cur_end = min(cur + step - timedelta(days=1), end)
            params = {
                "start_date": cur.isoformat(),
                "end_date": cur_end.isoformat(),
            }
            if limit is not None:
                params["limit"] = int(limit)

            try:
                resp = self._request("GET", url, params=params)
                payload = resp.json()
                rows = payload.get("data", []) if isinstance(payload, dict) else []
            except NetworkError as e:
                # If a chunk is still too large for the backend, recursively shrink it.
                if self._is_timeout(e) and int(chunk_days) > 45:
                    rows = self._get_continuous_chunked(
                        base_symbol,
                        start_date=cur.isoformat(),
                        end_date=cur_end.isoformat(),
                        limit=limit,
                        chunk_days=max(30, int(chunk_days) // 2),
                    )
                else:
                    raise
            if rows:
                all_rows.extend(rows)
            cur = cur_end + timedelta(days=1)

        if not all_rows:
            return []

        # De-duplicate by trade_date (keep last) and sort.
        by_date: dict[str, dict] = {}
        for row in all_rows:
            td = row.get("trade_date")
            if td:
                by_date[str(td)] = row
        out = [by_date[k] for k in sorted(by_date.keys())]
        return out

    def write_log(self, data: dict) -> bool:
        """通过API写入日志"""
        url = f"{self.api.write_url}/api/backtest/log"
        # Logging should never block the workflow for long; use a short timeout.
        resp = self._request("POST", url, json=data, timeout=min(5, int(self.api.timeout_seconds)))
        result = resp.json()
        if not isinstance(result, dict):
            raise ModuleError("Log API returned non-JSON object")
        if not result.get("success", False):
            # Do not raise: logging failure should not kill the workflow.
            print(f"日志API返回失败: {result.get('error', 'unknown')}")
        return bool(result.get("success", False))

    def create_task(self, data: dict) -> bool:
        """通过API创建任务"""
        url = f"{self.api.write_url}/api/backtest/task"
        resp = self._request("POST", url, json=data)
        result = resp.json()
        if not isinstance(result, dict):
            raise ModuleError("Task API returned non-JSON object")
        if not result.get("success", False):
            print(f"任务创建API返回失败: {result.get('error', 'unknown')}")
        return bool(result.get("success", False))

    def write_result(self, data: dict) -> int:
        """通过API写入回测结果"""
        url = f"{self.api.write_url}/api/backtest/result"
        resp = self._request("POST", url, json=data)
        result = resp.json()
        if not isinstance(result, dict):
            raise ModuleError("Result API returned non-JSON object")
        if not result.get("success", False):
            print(f"结果API返回失败: {result.get('error', 'unknown')}")
            return 0
        return int(result.get("id", 0) or 0)

    def read(self, query: str, params: tuple = None) -> list[dict]:
        """直连读取数据（用于任务历史等）"""
        conn = self.connect()
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchall()

    def write(self, table: str, data: dict) -> int:
        """写入数据，返回插入的ID"""
        conn = self.connect()
        if not data:
            raise ModuleError("write() data must not be empty")

        query = sql.SQL("INSERT INTO {table} ({cols}) VALUES ({vals}) RETURNING id").format(
            table=sql.Identifier(table),
            cols=sql.SQL(", ").join(sql.Identifier(c) for c in data.keys()),
            vals=sql.SQL(", ").join(sql.Placeholder() for _ in data.keys()),
        )

        with conn.cursor() as cur:
            cur.execute(query, list(data.values()))
            result_id = cur.fetchone()[0]
            conn.commit()
            return result_id

    def update_where(self, table: str, data: dict, where: dict) -> int:
        """安全更新：where 使用列->值映射"""
        conn = self.connect()
        if not data:
            raise ModuleError("update_where() data must not be empty")
        if not where:
            raise ModuleError("update_where() where must not be empty")

        set_clause = sql.SQL(", ").join(
            sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder()) for k in data.keys()
        )
        where_clause = sql.SQL(" AND ").join(
            sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder()) for k in where.keys()
        )
        query = sql.SQL("UPDATE {table} SET {set_clause} WHERE {where_clause}").format(
            table=sql.Identifier(table),
            set_clause=set_clause,
            where_clause=where_clause,
        )

        values = list(data.values()) + list(where.values())
        with conn.cursor() as cur:
            cur.execute(query, values)
            conn.commit()
            return cur.rowcount

    def set_task_status(
        self,
        task_id: str,
        status: str,
        *,
        error_message: str | None = None,
        completed_at=None,
    ) -> int:
        """
        Best-effort direct DB status update (useful when HTTP API doesn't expose an update endpoint).
        No-op if BACKTEST_DB_URL is not configured.
        """
        if not self.connection_string:
            return 0

        data = {"status": status}
        if error_message is not None:
            data["error_message"] = error_message
        if completed_at is not None:
            data["completed_at"] = completed_at

        # Keep it simple: only update known columns; completed_at is set by caller if needed.
        return self.update_where("backtest_tasks", data, {"task_id": task_id})
