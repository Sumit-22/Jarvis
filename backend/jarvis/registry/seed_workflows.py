"""Seed workflows used to test routing (Section 4 of the spec)."""
from __future__ import annotations

from .db import Database

SLUG = "^[a-z0-9]+(-[a-z0-9]+)*$"

SEEDS = [
    dict(
        name="youtube_play",
        canonical_intent="play a youtube video about a topic",
        params_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        steps=[
            {"tool": "search_youtube", "args_template": {"query": "{query}"}},
            {"tool": "play_youtube_result", "args_template": {"index": 0}},
        ],
        aliases=["play youtube video", "youtube play"],
        patterns=[
            r"^(play|search)( a)? (video|videos)? ?(about|on) (?P<query>.+)$",
            r"^play (?P<query>.+) on youtube$",
            r"^(search )?youtube (for )?(?P<query>.+)$",
        ],
    ),
    dict(
        name="coding_workspace",
        canonical_intent="open leetcode problem on the left and claude on the right",
        params_schema={"type": "object", "properties": {"slug": {"type": "string", "pattern": SLUG}},
                       "required": ["slug"]},
        steps=[
            {"tool": "open_leetcode_problem", "args_template": {"slug": "{slug}"}},
            {"tool": "open_claude", "args_template": {}},
            {"tool": "arrange_windows",
             "args_template": {"left_title": "LeetCode", "right_title": "Claude", "layout": "side_by_side"}},
            {"tool": "verify_workspace",
             "args_template": {"expected_windows": [{"title": "LeetCode", "position": "left"},
                                                    {"title": "Claude", "position": "right"}]}},
        ],
        aliases=["open my coding workspace", "coding workspace", "open coding workspace", "start coding",
                 "coding setup"],
        patterns=[
            r"^(open |start |launch )?(my )?coding (workspace|setup)( for| with)?( problem)? (?P<slug>[a-z0-9]+(-[a-z0-9]+)*)$",
        ],
    ),
    dict(
        name="notion_meeting_notes",
        canonical_intent="create a notion page with meeting notes",
        params_schema={"type": "object", "properties": {"title": {"type": "string"}, "notes": {"type": "string"}},
                       "required": ["title", "notes"]},
        steps=[
            {"tool": "create_notion_page", "args_template": {"title": "{title}", "content_blocks": ["{notes}"]}},
        ],
        aliases=["meeting notes", "create meeting notes", "notion meeting notes", "save meeting notes"],
        patterns=[r"^(create |save |add )?meeting notes (called|titled|named) (?P<title>.+?)( notes (?P<notes>.+))?$"],
    ),
]


def seed(db: Database) -> None:
    for s in SEEDS:
        if db.get_workflow_by_name(s["name"]) is None:
            db.save_workflow(**s)
