from __future__ import annotations

import asyncio

from jarvis.tools.base import ToolResult

from .conftest import plan_json


async def test_saved_workflow_makes_zero_planner_calls(make_jarvis):
    j = make_jarvis(responder=lambda s, u: plan_json())
    r = await j.handle_command("play a video about python decorators")
    assert r["route"] == "local" and r["status"] == "succeeded"
    assert j.provider.calls == []  # the core cost requirement
    assert j.fakes["search_youtube"].calls == [{"query": "python decorators"}]
    assert j.fakes["play_youtube_result"].calls == [{"index": 0}]
    assert j.db.usage_summary()["planner_calls"] == 0


async def test_miss_calls_planner_once_and_records_usage(make_jarvis):
    j = make_jarvis(responder=lambda s, u: plan_json(("open_url", {"url": "https://example.com"})))
    r = await j.handle_command("open example dot com in my browser")
    assert r["route"] == "llm" and r["status"] == "succeeded"
    assert len(j.provider.calls) == 1
    usage = j.db.usage_for_execution(r["execution_id"])
    assert len(usage) == 1 and usage[0]["purpose"] == "planner"
    assert r["offer_save"]["suggested_name"]


async def test_invalid_plan_gets_one_repair_then_fails(make_jarvis):
    j = make_jarvis(responder=lambda s, u: plan_json(("run_shell", {"cmd": "del *"})))
    r = await j.handle_command("delete everything")
    assert r["kind"] == "error" and "invalid plan twice" in r["message"]
    assert len(j.provider.calls) == 2  # original + one repair
    assert j.db.usage_summary()["planner_calls"] == 2


async def test_repair_attempt_can_succeed(make_jarvis):
    answers = iter(["not json at all", plan_json(("open_url", {"url": "https://example.com"}))])
    j = make_jarvis(responder=lambda s, u: next(answers))
    r = await j.handle_command("open example dot com in my browser")
    assert r["status"] == "succeeded" and len(j.provider.calls) == 2


async def test_invalid_args_in_plan_rejected(make_jarvis):
    j = make_jarvis(responder=lambda s, u: plan_json(("open_url", {"url": "ftp://nope"})))
    r = await j.handle_command("open some ftp thing")
    assert r["kind"] == "error"
    assert j.fakes["open_url"].calls == []


async def test_retry_limit_respected(make_jarvis):
    j = make_jarvis()
    fake = j.fakes["search_youtube"]
    fake.behaviour = lambda a: ToolResult(ok=False, error="boom")
    r = await j.handle_command("play a video about cats")
    assert r["status"] == "failed"
    assert len(fake.calls) == 1 + j.settings.max_retries  # 3 attempts total
    assert j.fakes["play_youtube_result"].calls == []


async def test_timeout_gives_failed(make_jarvis):
    j = make_jarvis(max_retries=0)
    fake = j.fakes["search_youtube"]
    fake.timeout_s = 0.2

    async def slow(a):
        await asyncio.sleep(5)
        return ToolResult(ok=True)

    fake.behaviour = slow
    r = await j.handle_command("play a video about cats")
    assert r["status"] == "failed" and "timed out" in r["error"]


async def test_approval_required_tool_does_not_run_without_approval(make_jarvis):
    j = make_jarvis()
    r = await j.run_workflow("notion_meeting_notes", {"title": "Standup", "notes": "Shipped M2"})
    assert r["status"] == "cancelled"  # approval timed out (1s in tests)
    assert j.fakes["create_notion_page"].calls == []


async def test_approval_granted_runs_tool(make_jarvis):
    j = make_jarvis()
    q = j.bus.subscribe()

    async def approver():
        while True:
            ev = await q.get()
            if ev["type"] == "approval_request":
                assert "Standup" in ev["description"]
                j.approvals.resolve(ev["approval_id"], True)
                return

    task = asyncio.create_task(approver())
    r = await j.run_workflow("notion_meeting_notes", {"title": "Standup", "notes": "Shipped M2"})
    await task
    assert r["status"] == "succeeded"
    assert j.fakes["create_notion_page"].calls == [
        {"title": "Standup", "content_blocks": ["Shipped M2"], "parent_id": None}]


async def test_approval_denied(make_jarvis):
    j = make_jarvis()
    q = j.bus.subscribe()

    async def denier():
        while True:
            ev = await q.get()
            if ev["type"] == "approval_request":
                j.approvals.resolve(ev["approval_id"], False)
                return

    task = asyncio.create_task(denier())
    r = await j.run_workflow("notion_meeting_notes", {"title": "T", "notes": "N"})
    await task
    assert r["status"] == "cancelled" and j.fakes["create_notion_page"].calls == []


async def test_stop_cancels_within_two_seconds(make_jarvis):
    j = make_jarvis(step_timeout_s=30.0)
    fake = j.fakes["search_youtube"]
    fake.timeout_s = 30.0

    async def slow(a):
        await asyncio.sleep(30)
        return ToolResult(ok=True)

    fake.behaviour = slow
    run = asyncio.create_task(j.handle_command("play a video about cats"))
    await asyncio.sleep(0.3)
    t0 = asyncio.get_running_loop().time()
    assert j.stop() == 1
    r = await asyncio.wait_for(run, 2.0)
    assert r["status"] == "cancelled"
    assert asyncio.get_running_loop().time() - t0 < 2.0


async def test_dry_run_calls_no_tool(make_jarvis):
    j = make_jarvis(dry_run=True)
    r = await j.handle_command("play a video about cats")
    assert r["status"] == "succeeded"
    assert all(not f.calls for f in j.fakes.values())


async def test_repeat_last_workflow_reads_executions(make_jarvis):
    j = make_jarvis(responder=lambda s, u: plan_json())
    await j.handle_command("play a video about lofi beats")
    j.fakes["search_youtube"].calls.clear()
    r = await j.handle_command("repeat the last workflow")
    assert r["via"] == "history" and r["workflow"] == "youtube_play" and r["status"] == "succeeded"
    assert j.fakes["search_youtube"].calls == [{"query": "lofi beats"}]
    assert j.provider.calls == []


async def test_repeat_with_no_history(make_jarvis):
    j = make_jarvis()
    r = await j.handle_command("repeat the last workflow")
    assert r["kind"] == "error" and j.provider.calls == []


async def test_repeat_today_with_several_asks_which(make_jarvis):
    j = make_jarvis()
    await j.handle_command("play a video about cats")
    await j.handle_command("play a video about dogs")
    r = await j.handle_command("repeat what we did today")
    assert r["kind"] == "choose" and len(r["options"]) == 2


async def test_save_llm_plan_then_rerun_locally(make_jarvis):
    j = make_jarvis(responder=lambda s, u: plan_json(("open_url", {"url": "https://news.ycombinator.com"})))
    r = await j.handle_command("open hacker news")
    assert r["route"] == "llm" and r["status"] == "succeeded"
    wf = j.save_from_execution(r["execution_id"], "hacker_news")
    assert wf.version == 1 and "open hacker news" in wf.aliases
    r2 = await j.handle_command("open hacker news")
    assert r2["route"] == "local" and r2["workflow"] == "hacker_news" and r2["status"] == "succeeded"
    assert len(j.provider.calls) == 1  # second run made zero planner calls


async def test_never_auto_saves_and_rejects_failed_run(make_jarvis):
    j = make_jarvis(responder=lambda s, u: plan_json(("open_url", {"url": "https://example.com"})))
    j.fakes["open_url"].behaviour = lambda a: ToolResult(ok=False, error="x")
    r = await j.handle_command("open example dot com in my browser")
    assert r["status"] == "failed" and "offer_save" not in r
    assert j.db.get_workflow_by_name("open_flow") is None
    import pytest
    with pytest.raises(ValueError):
        j.save_from_execution(r["execution_id"], "nope")


async def test_editing_workflow_bumps_version_keeps_old(make_jarvis):
    j = make_jarvis()
    old = j.db.get_workflow_by_name("youtube_play")
    new = j.db.save_workflow(name="youtube_play", steps=old.steps, params_schema=old.params_schema, aliases=["yt"])
    assert new.version == old.version + 1
    assert j.db.get_workflow(old.id) is not None and not j.db.get_workflow(old.id).enabled


async def test_ufo_workflow_flagged_uses_llm(make_jarvis):
    j = make_jarvis(responder=lambda s, u: plan_json(("ufo_desktop_task", {"task": "open notepad and type hello"}),
                                                     reason="no deterministic tool types into notepad"))
    q = j.bus.subscribe()

    async def approver():
        while True:
            ev = await q.get()
            if ev["type"] == "approval_request":
                j.approvals.resolve(ev["approval_id"], True)
                return

    t = asyncio.create_task(approver())
    r = await j.handle_command("open notepad and type hello")
    await t
    assert r["status"] == "succeeded" and r["uses_llm_per_run"] is True
    wf = j.save_from_execution(r["execution_id"], "notepad_hello")
    assert wf.uses_llm_per_run is True
