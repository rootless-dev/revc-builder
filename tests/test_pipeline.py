from __future__ import annotations

import pytest

from vcbuilder.errors import BuildError, CompileError
from vcbuilder.events import LogLine, Progress, StageFailed, StageFinished, StageStarted
from vcbuilder.pipeline import STAGE_IDS, Pipeline, Stage
from vcbuilder.runner import CancelToken, Cancelled


def _recording_stage(stage_id: str, ran: list[str], action=None) -> Stage:
    def run(context):
        ran.append(stage_id)
        if action:
            action(context)

    return Stage(stage_id, stage_id.title(), run)


def test_default_stage_order_matches_the_spec():
    assert STAGE_IDS == ("validate", "tools", "fetch", "deps", "compile", "verify", "install")


def test_stages_run_in_order_and_emit_events(events):
    ran: list[str] = []
    stages = [_recording_stage(name, ran) for name in ("one", "two", "three")]
    result = Pipeline(stages, emit=events.append).run(context=None)
    assert result.succeeded
    assert ran == ["one", "two", "three"]
    assert events == [
        StageStarted("one", "One"),
        StageFinished("one"),
        StageStarted("two", "Two"),
        StageFinished("two"),
        StageStarted("three", "Three"),
        StageFinished("three"),
    ]


def test_a_failing_stage_stops_the_pipeline(events):
    ran: list[str] = []
    error = CompileError("cmake exited with 1")

    def fail(context):
        raise error

    stages = [_recording_stage("one", ran), _recording_stage("two", ran, fail), _recording_stage("three", ran)]
    result = Pipeline(stages, emit=events.append).run(context=None)
    assert not result.succeeded
    assert result.failed_stage == "two"
    assert result.error is error
    assert ran == ["one", "two"]
    assert events[-1] == StageFailed("two", error)


def test_resumption_starts_at_the_failed_stage(events):
    ran: list[str] = []
    attempts = {"count": 0}

    def flaky(context):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise CompileError("first attempt fails")

    stages = [_recording_stage("one", ran), _recording_stage("two", ran, flaky), _recording_stage("three", ran)]
    pipeline = Pipeline(stages, emit=events.append)
    first = pipeline.run(context=None)
    assert first.failed_stage == "two"

    ran.clear()
    second = pipeline.run(context=None, start=first.failed_stage)
    assert second.succeeded
    assert ran == ["two", "three"]


def test_unknown_start_stage_is_rejected():
    with pytest.raises(ValueError):
        Pipeline([Stage("one", "One", lambda c: None)], emit=lambda e: None).run(None, start="nope")


def test_unexpected_exceptions_become_build_errors(events):
    def crash(context):
        raise RuntimeError("boom")

    result = Pipeline([Stage("one", "One", crash)], emit=events.append).run(context=None)
    assert isinstance(result.error, BuildError)
    assert result.error.code == "internal"
    assert any(isinstance(e, LogLine) and "boom" in e.text for e in events)


def test_cancellation_inside_a_stage_stops_without_an_error_message(events):
    token = CancelToken()
    ran: list[str] = []

    def cancel_midway(context):
        token.cancel()
        token.raise_if_cancelled()

    stages = [_recording_stage("one", ran, cancel_midway), _recording_stage("two", ran)]
    result = Pipeline(stages, emit=events.append, cancel=token).run(context=None)
    assert result.cancelled
    assert not result.succeeded
    assert result.error is None
    assert ran == ["one"]
    assert events[-1] == StageFailed("one", None, cancelled=True)


def test_cancellation_between_stages_prevents_the_next_stage(events):
    token = CancelToken()
    ran: list[str] = []
    stages = [_recording_stage("one", ran, lambda c: token.cancel()), _recording_stage("two", ran)]
    result = Pipeline(stages, emit=events.append, cancel=token).run(context=None)
    assert result.cancelled
    assert ran == ["one"]
    assert StageStarted("two", "Two") not in events


def test_cancel_token_raises_cancelled():
    token = CancelToken()
    token.raise_if_cancelled()
    token.cancel()
    with pytest.raises(Cancelled):
        token.raise_if_cancelled()


def test_stages_can_report_progress(events):
    def work(context):
        context.emit(Progress("one", 0.5, "half way"))

    class Context:
        emit = staticmethod(events.append)

    Pipeline([Stage("one", "One", work)], emit=events.append).run(Context())
    assert Progress("one", 0.5, "half way") in events


def test_stop_after_ends_early(events):
    ran: list[str] = []
    stages = [_recording_stage(name, ran) for name in ("one", "two", "three")]
    result = Pipeline(stages, emit=events.append).run(context=None, start="two", stop_after="two")
    assert result.succeeded
    assert ran == ["two"]
    with pytest.raises(ValueError):
        Pipeline(stages, emit=events.append).run(context=None, start="three", stop_after="one")
