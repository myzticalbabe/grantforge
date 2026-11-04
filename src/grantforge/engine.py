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
        """Input validation hook, run by ``run`` before every execution."""
        return True

    async def run(self, input: InputT) -> OutputT:
        """Validate, then execute. The entry point callers should use.

        ``execute`` stays public for subclasses and tests, but going through
        ``run`` is what makes the validation hook part of the call path instead
        of a method nothing reaches.
        """
        if not await self.validate_input(input):
            raise ValueError(f"{self.name}: input rejected by validate_input")
        return await self.execute(input)

    async def health_check(self) -> dict[str, Any]:
        """Report what was probed. The base engine probes nothing.

        This used to answer ``status: healthy`` unconditionally, and subclasses
        that added their own probes inherited it: discovery reported
        ``ov_embed_server: unknown`` next to ``status: healthy``. A monitoring
        hook that cannot go false protects nothing.
        """
        return {
            "engine": self.name,
            "status": "unprobed",
            "detail": "no dependency probe is wired for this engine",
            "version": self.version,
        }


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