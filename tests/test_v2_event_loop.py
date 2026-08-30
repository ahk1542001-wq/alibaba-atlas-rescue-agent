"""Audit finding #7: the FastAPI event loop must never be blocked by the
qwen brain. Agent construction and deterministic tool calls must run via
asyncio.to_thread, not synchronously on the request loop thread.
"""
import json
import threading

import pytest

from services.qwen_brain import agent as agent_mod
from services.qwen_brain.agent import run_qwen_conversation
from services.qwen_brain.conversation import run_qwen_goal_intake
from services.qwen_brain.tools.conversation import GoalIntakeTool, ClarifyLoopTool


class _FakeBot:
    def run(self, messages, stream=False):
        yield [{"role": "assistant", "content": "ok"}]


@pytest.mark.anyio
async def test_agent_build_runs_off_the_event_loop(monkeypatch):
    build_threads = []

    def fake_build(tools=None, system_message=None):
        build_threads.append(threading.current_thread())
        return _FakeBot()

    monkeypatch.setattr(agent_mod, "build_travelcare_agent", fake_build)
    out = await run_qwen_conversation([{"role": "user", "content": "hi"}])

    assert out, "run_qwen_conversation must return the bot history"
    assert len(build_threads) == 1
    assert build_threads[0] is not threading.main_thread(), (
        "build_travelcare_agent() ran on the FastAPI event-loop thread; "
        "it must be constructed inside the asyncio.to_thread closure"
    )


@pytest.mark.anyio
async def test_goal_intake_tool_calls_run_off_the_event_loop(monkeypatch):
    call_threads = []

    def _spy(cls):
        real_call = cls.call

        def spy_call(self, *args, **kwargs):
            call_threads.append(threading.current_thread())
            return real_call(self, *args, **kwargs)

        return spy_call

    monkeypatch.setattr(GoalIntakeTool, "call", _spy(GoalIntakeTool))
    monkeypatch.setattr(ClarifyLoopTool, "call", _spy(ClarifyLoopTool))

    goal_out, clarify_out = await run_qwen_goal_intake(
        goal_text="Fly from Bangkok to Yangon on 2026-09-28 to 2026-09-30",
        user_id="event_loop_tester",
        context={},
    )

    assert goal_out.get("goal", {}).get("origin_city") == "BKK"
    assert call_threads, "tool.call() was never invoked"
    assert all(t is not threading.main_thread() for t in call_threads), (
        "goal-intake tool calls ran on the event-loop thread; "
        "they must be dispatched via await asyncio.to_thread(...)"
    )
