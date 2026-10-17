"""Typed progress events emitted by the pipeline (spec section 4).

The GUI and the CLI render the same stream; neither runs build work itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Union

from vcbuilder.errors import BuildError


@dataclass(frozen=True)
class StageStarted:
    stage: str
    title: str


@dataclass(frozen=True)
class Progress:
    stage: str
    fraction: float | None
    message: str = ""


@dataclass(frozen=True)
class LogLine:
    stage: str
    text: str


@dataclass(frozen=True)
class StageFailed:
    stage: str
    error: BuildError | None
    cancelled: bool = False


@dataclass(frozen=True)
class StageFinished:
    stage: str


Event = Union[StageStarted, Progress, LogLine, StageFailed, StageFinished]
Emit = Callable[[Event], None]


def fan_out(*sinks: Emit) -> Emit:
    """Return an emitter that forwards every event to each sink in order."""

    def emit(event: Event) -> None:
        for sink in sinks:
            sink(event)

    return emit
