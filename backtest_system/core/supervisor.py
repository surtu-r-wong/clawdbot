from datetime import datetime
from typing import Optional
import os
from backtest_system.core.database import DatabaseAPI
from backtest_system.core.models import SkillResult
from backtest_system.core.exceptions import DataValidationError, ModuleError, NetworkError

class Supervisor:
    """监管者：监控状态、处理异常、升级人工"""

    def __init__(
        self,
        db_api: DatabaseAPI,
        *,
        non_interactive: bool = True,
        on_escalate: str = "halt",  # halt | retry | skip
        max_log_data_chars: int = 20000,
        log_dir: str | None = None,
    ):
        self.db_api = db_api
        self.current_task_id: Optional[str] = None
        self.execution_log: list = []
        self.non_interactive = non_interactive
        self.on_escalate = on_escalate
        self.max_log_data_chars = max_log_data_chars
        self.log_dir = log_dir
        self.remote_logging_enabled = True

    def set_task_id(self, task_id: str):
        self.current_task_id = task_id
        self.remote_logging_enabled = True

    def disable_remote_logging(self):
        # Used when task creation fails on the server. Keep local logs, skip DB writes.
        self.remote_logging_enabled = False

    def on_skill_start(self, skill_name: str, params: dict):
        """记录skill开始执行"""
        self._log("START", skill_name, params)
        print(f"[{skill_name}] 开始执行...")

    def on_skill_complete(self, skill_name: str, result: SkillResult):
        """记录skill完成"""
        if result.success:
            self._log("COMPLETE", skill_name, result.data)
            print(f"[{skill_name}] 执行完成")
        else:
            # Treat non-exception failures as ERROR events so dashboards/DB can see them.
            payload = {"error": result.error, "data": result.data}
            self._log("ERROR", skill_name, payload)
            print(f"[{skill_name}] 执行失败: {result.error}")

    def on_skill_error(self, skill_name: str, error: Exception) -> SkillResult:
        """处理skill执行错误"""
        self._log("ERROR", skill_name, str(error))
        action = self._decide_action(skill_name, error)

        if action == "retry":
            # Print the underlying error so operators can see which URL/status failed.
            print(f"[{skill_name}] 网络错误: {error}，准备重试...")
            return SkillResult(success=False, retry=True)
        elif action == "skip":
            print(f"[{skill_name}] 跳过此步骤")
            return SkillResult(success=False, skipped=True)
        elif action == "escalate":
            return self._escalate_to_human(skill_name, error)

        return SkillResult(success=False, halted=True)

    def _decide_action(self, skill_name: str, error: Exception) -> str:
        """根据错误类型决定处理方式"""
        if isinstance(error, NetworkError):
            return "retry"
        elif isinstance(error, (DataValidationError, ModuleError)):
            return "escalate"
        return "escalate"

    def _escalate_to_human(self, skill_name: str, error: Exception) -> SkillResult:
        """升级到人工处理"""
        if self.non_interactive:
            if self.on_escalate == "retry":
                return SkillResult(success=False, retry=True)
            if self.on_escalate == "skip":
                return SkillResult(success=False, skipped=True)
            return SkillResult(success=False, halted=True, error=str(error))

        print("\n需要人工干预")
        print(f"Skill: {skill_name}")
        print(f"错误: {error}")

        while True:
            choice = input("请选择: [r]重试 / [s]跳过 / [a]中止: ").strip().lower()
            if choice == 'r':
                return SkillResult(success=False, retry=True)
            elif choice == 's':
                return SkillResult(success=False, skipped=True)
            elif choice == 'a':
                return SkillResult(success=False, halted=True)
            print("无效选择，请重新输入")

    def _log(self, event: str, skill_name: str, data):
        """记录到数据库"""
        import json

        serializable_data = None
        if isinstance(data, dict):
            try:
                # 尝试将dict中的值转换为可序列化格式
                clean_data = {}
                for k, v in data.items():
                    if hasattr(v, "__dict__"):
                        clean_data[k] = str(v)
                    else:
                        clean_data[k] = v
                serializable_data = json.dumps(clean_data, default=str)
            except (TypeError, ValueError):
                serializable_data = str(data)
        elif data is not None:
            # Non-dict data: keep a string message and avoid double-storing.
            serializable_data = None

        if serializable_data and len(serializable_data) > self.max_log_data_chars:
            serializable_data = serializable_data[: self.max_log_data_chars] + "...(truncated)"

        log_entry = {
            "task_id": self.current_task_id,
            "skill_name": skill_name,
            "event": event,
            "message": str(data) if not isinstance(data, dict) else None,
            "data": serializable_data,
            "created_at": datetime.now().isoformat()
        }
        self.execution_log.append(log_entry)

        # Always persist a local copy when configured (helps when DB/API is flaky).
        self._append_local_log(log_entry)

        if self.db_api and self.current_task_id and self.remote_logging_enabled:
            try:
                success = self.db_api.write_log(log_entry)
                if not success:
                    print(f"[日志] 写入失败")
            except Exception as e:
                # Remote logging is best-effort. Disable it for this task after the first failure
                # to avoid repeated timeouts slowing down the workflow.
                print(f"日志写入异常: {e}（已自动关闭远程日志写入，本地日志仍写入 {self.log_dir or 'output'}）")
                self.remote_logging_enabled = False

    def _append_local_log(self, log_entry: dict) -> None:
        if not self.log_dir or not self.current_task_id:
            return
        try:
            os.makedirs(self.log_dir, exist_ok=True)
            path = os.path.join(self.log_dir, f"{self.current_task_id}.logs.jsonl")
            import json

            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=True, default=str) + "\n")
        except Exception:
            # Local logging is best-effort.
            pass
