from __future__ import annotations

from jarvis.router.local_match import match
from jarvis.router.normalize import normalize
from jarvis.router.router import parameterize

from .conftest import plan_json


def test_normalize_strips_filler_and_punctuation():
    assert normalize("  Jarvis, can you PLEASE open my coding workspace?! ") == "open my coding workspace"
    assert normalize("coding workspace two-sum") == "coding workspace two-sum"


def test_alias_exact_hit(make_jarvis):
    j = make_jarvis()
    m = match(j.db, normalize("Open my coding workspace"))
    assert m.kind == "hit" and m.via == "alias" and m.workflow.name == "coding_workspace"


def test_fuzzy_hit(make_jarvis):
    j = make_jarvis()
    m = match(j.db, normalize("workspace coding"))  # token_set_ratio == 100
    assert m.kind == "hit" and m.via == "fuzzy" and m.workflow.name == "coding_workspace"


def test_fuzzy_confirm_band(make_jarvis):
    j = make_jarvis()
    m = match(j.db, normalize("open my cdng wrkspc"))
    assert m.kind == "confirm", (m.kind, m.score)
    assert 75 <= m.score < 90
    assert m.workflow.name == "coding_workspace"


def test_miss(make_jarvis):
    j = make_jarvis()
    m = match(j.db, normalize("order a pizza from dominos"))
    assert m.kind == "miss"


def test_pattern_slot_extraction_youtube(make_jarvis):
    j = make_jarvis()
    for text in ("play a video about python decorators", "Play videos on python decorators",
                 "search video about python decorators"):
        m = match(j.db, normalize(text))
        assert m.kind == "hit" and m.via == "pattern", text
        assert m.workflow.name == "youtube_play"
        assert m.params == {"query": "python decorators"}


def test_pattern_slot_extraction_coding_workspace(make_jarvis):
    j = make_jarvis()
    m = match(j.db, normalize("open my coding workspace for two-sum"))
    assert m.kind == "hit" and m.params == {"slug": "two-sum"}


async def test_missing_param_asks_user_not_llm(make_jarvis):
    j = make_jarvis(responder=lambda s, u: plan_json())
    r = await j.handle_command("open my coding workspace")
    assert r["kind"] == "needs_input" and r["missing"] == ["slug"]
    assert j.provider.calls == []


async def test_invalid_params_rejected(make_jarvis):
    j = make_jarvis()
    r = await j.run_workflow("coding_workspace", {"slug": "Two Sum!!"})
    assert r["kind"] == "error" and "does not match" in r["message"]
    assert j.fakes["open_leetcode_problem"].calls == []


def test_parameterize_extracts_values():
    steps, schema, patterns = parameterize("search youtube for lofi beats", [
        {"tool": "search_youtube", "args": {"query": "lofi beats"}},
        {"tool": "play_youtube_result", "args": {"index": 0}},
    ])
    assert steps[0]["args_template"] == {"query": "{query}"}
    assert steps[1]["args_template"] == {"index": 0}
    assert schema["required"] == ["query"]
    import re
    m = re.match(patterns[0], "search youtube for jazz")
    assert m and m.group("query") == "jazz"


async def test_slot_values_keep_user_case_and_punctuation(make_jarvis):
    j = make_jarvis()
    r = await j.handle_command("Jarvis, meeting notes titled Q3 Standup notes Shipped M4, fixed 2 bugs.")
    assert r["params"] == {"title": "Q3 Standup", "notes": "Shipped M4, fixed 2 bugs"}


def test_strip_fillers():
    from jarvis.router.normalize import strip_fillers
    assert strip_fillers("Hey Jarvis, can you play a video about C++ Templates?") == "play a video about C++ Templates"


async def test_slug_case_is_coerced(make_jarvis):
    j = make_jarvis()
    r = await j.handle_command("Open my coding workspace for Two-Sum")
    assert r["params"] == {"slug": "two-sum"} and r["status"] == "succeeded"
