"""
Base engine interface for all grantforge engines.
Each engine implements this contract for type-safe composition.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from pydantic import BaseModel


class EngineInput(BaseModel):
    """Base input for all engines."""
    pass


class EngineOutput(BaseModel):
    """Base output for all engines."""
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] = {}


InputT = TypeVar("InputT", bound=EngineInput)
OutputT = TypeVar("OutputT", bound=EngineOutput)


class Engine(ABC, Generic[InputT, OutputT]):
    """Abstract base class for grantforge engines."""

    name: str = "base"
    version: str = "1.0.0"

    @abstractmethod
    async def execute(self, input: InputT) -> OutputT:
        """Execute the engine with given input."""
        ...

    async def validate_input(self, input: InputT) -> bool:
        """Optional input validation hook."""
        return True

    async def health_check(self) -> dict[str, Any]:
        """Health check for monitoring."""
        return {"engine": self.name, "status": "healthy", "version": self.version}


class EngineRegistry:
    """Registry for engine discovery and composition."""

    def __init__(self):
        self._engines: dict[str, Engine] = {}

    def register(self, engine: Engine) -> None:
        self._engines[engine.name] = engine

    def get(self, name: str) -> Engine | None:
        return self._engines.get(name)

    def all(self) -> list[Engine]:
        return list(self._engines.values())

    async def health_check_all(self) -> dict[str, Any]:
        results = {}
        for engine in self._engines.values():
            results[engine.name] = await engine.health_check()
        return results


# Global registry instance
registry = EngineRegistry()