from dataclasses import dataclass, field
from typing import Optional

@dataclass
class SkillResult:
    """Skill执行结果"""
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None
    retry: bool = False
    skipped: bool = False
    halted: bool = False

@dataclass
class TaskConfig:
    """任务配置"""
    task_id: str
    mode: str  # 'smart' or 'specified'
    positions: list[str]
    periods: list[str] = field(default_factory=list)
    combo_range: Optional[tuple[int, int]] = None
    portfolio_models: list[str] = field(default_factory=list)
    top_n: int = 10
    params: Optional[dict] = None
    strategy_max_evals: int = 2000
