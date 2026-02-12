from abc import ABC, abstractmethod
from backtest_system.core.models import SkillResult

class BaseSkill(ABC):
    """Skill基类"""

    @abstractmethod
    def execute(self, **kwargs) -> SkillResult:
        """执行skill"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Skill名称"""
        pass
