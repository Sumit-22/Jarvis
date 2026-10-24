"""Seed workflows (Section 4 of the spec) plus everyday commands, so common requests route locally for free.

Patterns are tried workflow by workflow in name order (see Database.list_workflows), so a pattern only has
to avoid stealing commands from workflows whose names sort after it. tests/test_daily_routing.py pins the
expected route for every everyday phrasing; add a case there when you add a pattern.
"""
from __future__ import annotations

import re

from ..tools.daily import ORDINALS, UNIT_SECONDS, app_names, installed_app_names, site_names
from .db import Database

SLUG = "^[a-z0-9]+(-[a-z0-9]+)*$"


def _alt(words: list[str]) -> str:
    return "|".join(re.escape(w) for w in words)


SITES = _alt(site_names())
APPS = _alt(app_names())
UNITS = _alt(sorted(UNIT_SECONDS, key=lambda u: (-len(u), u)))
STR = {"type": "string"}
# Hinglish verbs: "kholo" = open, "chalao/bajao/lagao" = play, "karo" = do
OPEN_HI = r"(kholo|khol do|open karo|open kro|chalu karo|start karo)"
ON_HI = r"(on karo|on kro|on kar do|chalu karo|chalu kro|on)"
ORD = _alt(sorted(ORDINALS, key=lambda o: (-len(o), o))) + r"|\d{1,2}"
VIDEO_HI = r"(video|wala video|wali video|vala video|number wala video|result)"

def _installed_app_patterns() -> list[str]:
    """Start-menu apps; names that are also known websites only match with an explicit "app" suffix."""
    names = installed_app_names()
    if not names:
        return []
    sites = set(site_names())
    plain = [n for n in names if n not in sites]
    pats = [rf"^(open|launch|start|run)( the| my)? (?P<app>{_alt(names)}) (app|application)$"]
    if plain:
        pats += [rf"^(open|launch|start|run)( the| my)? (?P<app>{_alt(plain)})$",
                 rf"^(?P<app>{_alt(plain)}) {OPEN_HI}$"]
    return pats


def build_seeds() -> list[dict]:
    return [
        dict(
            name="youtube_play",
            canonical_intent="play a youtube video about a topic",
            params_schema={"type": "object", "properties": {"query": STR}, "required": ["query"]},
            steps=[
                {"tool": "search_youtube", "args_template": {"query": "{query}"}},
                {"tool": "play_youtube_result", "args_template": {"index": 0}},
            ],
            aliases=["play youtube video", "youtube play"],
            patterns=[
                r"^(play|search)( a)? (video|videos)? ?(about|on) (?P<query>.+)$",
                r"^play (?P<query>.+) on youtube$",
                r"^youtube (pe|par) (?P<query>.+?)( chalao| bajao| lagao| play karo| search karo| dikhao)?$",
                r"^(search )?youtube (for )?(?P<query>.+)$",
                r"^(search|find|look up) (?P<query>.+) (on|in) youtube$",
                r"^play (?!(the )?(next|previous|prev)\b)(?P<query>.+?)( video| song| songs)?$",
                r"^(?P<query>.+?) (youtube (pe|par) )?(chalao|bajao|lagao|play karo|play kro)$",
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
        # ---- everyday commands ----
        # ---- Claude bridge (the tool reads target/mode/model/project out of the text) ----
        dict(
            name="claude_ask",
            canonical_intent="send a task or follow-up to Claude (Claude Code or claude.ai)",
            params_schema={"type": "object", "properties": {"prompt": STR}, "required": ["prompt"]},
            steps=[{"tool": "claude_ask", "args_template": {"prompt": "{prompt}", "parse": True}}],
            aliases=[],
            patterns=[
                r"^(?!claude( code)? (ko )?(roko|rok do|stop karo|band karo)$)(?P<prompt>(hey |ok )?((go to|open|use|ask|tell|message) )?claude( code)?(\.ai| ai| website| web| chat| site)? (pe|par|per|on|me|mein|ko|se|to|that|and|aur|:) .+)$",
                r"^(?P<prompt>(start |open )?(a )?(new|naya|nayi) (claude (code )?)?(chat|session|conversation)( (on|in|pe|par|me|mein) claude( code)?)?( (and|aur|:|-|with))? .+)$",
            ],
        ),
        dict(
            name="claude_status",
            canonical_intent="what did Claude do / is Claude done",
            params_schema={"type": "object", "properties": {}},
            steps=[{"tool": "claude_status", "args_template": {}}],
            aliases=[],
            patterns=[
                r"^what (did|has) claude( code)? (do|done|say|said|reply|replied|answer|answered|write|written|change|changed)( so far)?$",
                r"^claude( code)? ne kya (kiya|bola|likha|kaha|jawab diya|badla)( hai)?$",
                r"^(is )?claude( code)? (done|finished|ready|still working)( yet)?$",
                r"^claude( code)? (ka |ki )?(status|kaam|update|progress|reply|jawab)( kya hai| batao| kya hua| check karo)?$",
                r"^(read|show|tell) (me )?claudes? (reply|answer|response|status)$",
                r"^(kya )?claude( code)? ka kaam (khatam|ho gaya|hua)( hua| hai| kya)?$",
            ],
        ),
        dict(
            name="claude_stop",
            canonical_intent="stop what Claude is doing",
            params_schema={"type": "object", "properties": {}},
            steps=[{"tool": "claude_stop", "args_template": {}}],
            aliases=[],
            patterns=[
                r"^(stop|cancel|abort) claude( code)?$",
                r"^claude( code)? (ko )?(roko|rok do|stop karo|band karo)$",
            ],
        ),
        dict(
            name="directions",
            canonical_intent="google maps directions to a place",
            params_schema={"type": "object", "properties": {"place": STR}, "required": ["place"]},
            steps=[{"tool": "web_search", "args_template": {"query": "{place}", "engine": "directions"}}],
            aliases=[],
            patterns=[
                r"^(get |show )?(me )?(directions|route|the way|navigate|navigation) (to|for) (?P<place>.+)$",
                r"^(take me|drive me|navigate) to (?P<place>.+)$",
                r"^how (do i|to|can i|should i) ((get|go) to|reach) (?P<place>.+)$",
                r"^(?P<place>.+?) (kaise jaye|kaise jaun|kaise jayen|ka rasta|ka route)( batao| dikhao)?$",
            ],
        ),
        dict(
            name="maps_search",
            canonical_intent="find a place on google maps",
            params_schema={"type": "object", "properties": {"query": STR}, "required": ["query"]},
            steps=[{"tool": "web_search", "args_template": {"query": "{query}", "engine": "maps"}}],
            aliases=[],
            patterns=[
                r"^(show |find |search |locate )?(?P<query>.+?) (on|in) (google )?maps?$",
                r"^(where is|wheres|find|show me) (the )?(?P<query>(nearest|closest) .+)$",
                r"^(?P<query>.+? near me)$",
            ],
        ),
        dict(
            name="media_control",
            canonical_intent="play/pause, next/previous track, volume up/down, mute",
            params_schema={"type": "object", "properties": {"action": STR}, "required": ["action"]},
            steps=[{"tool": "media_key", "args_template": {"action": "{action}"}}],
            aliases=[],
            patterns=[
                r"^(?P<action>play|pause|resume|unpause|stop|mute|unmute)( the)?( music| song| video| track| audio| volume| sound| playback| it)?$",
                r"^(?P<action>next|previous|prev|skip)( song| track| video| one)?$",
                r"^(play|go to|skip to)( the)? (?P<action>next|previous) (song|track|video|one)$",
                r"^(?P<action>volume up|volume down|louder|quieter)$",
                r"^(?P<action>increase|raise|decrease|lower|turn up|turn down)( the)? (volume|sound)$",
                r"^(turn|make)( the)? (volume|sound|it|music) (?P<action>up|down|louder|quieter)$",
                r"^(awaaz|aawaz|awaz|volume|sound) (?P<action>badhao|kam karo|kam kro|tez karo|dheere karo|band karo)$",
                r"^(gaana|gana|music|song|video|youtube) (?P<action>roko|rok do|chalao|pause karo|pause kar do|play karo|play kar do|resume karo|wapas chalao|phir se chalao)$",
                r"^(?P<action>pause karo|pause kar do|play karo|play kar do|resume karo|wapas chalao|phir se chalao)$",
                r"^(?P<action>pause|play|resume) (the )?(youtube|youtube video)$",
                r"^(?P<action>agla|pichla) (gaana|gana|song|video)$",
            ],
        ),
        dict(
            name="open_app",
            canonical_intent="open a windows app or folder",
            params_schema={"type": "object", "properties": {"app": STR}, "required": ["app"]},
            steps=[{"tool": "open_app", "args_template": {"app": "{app}"}}],
            aliases=[],
            patterns=[
                rf"^(open|launch|start|run|show|turn on|switch on)( the| my| up)? (?P<app>{APPS})( app| application| window)?$",
                rf"^(?P<app>{APPS}) ({OPEN_HI}|{ON_HI})$",
                *_installed_app_patterns(),
            ],
        ),
        dict(
            name="open_site",
            canonical_intent="open a website",
            params_schema={"type": "object", "properties": {"site": STR}, "required": ["site"]},
            steps=[{"tool": "open_site", "args_template": {"site": "{site}"}}],
            aliases=[],
            patterns=[
                rf"^(open|go to|goto|visit|launch|show|check)( the| my| up)? (?P<site>{SITES})( website| site| web| page| app)?$",
                r"^(open|go to|goto|visit) (?P<site>https?://\S+)$",
                r"^(open|go to|goto|visit) (?P<site>[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?)$",
                rf"^(?P<site>{SITES}) {OPEN_HI}$",
            ],
        ),
        dict(
            name="play_visible_video",
            canonical_intent="play the 1st/2nd/... video visible on the youtube screen",
            params_schema={"type": "object", "properties": {"position": STR}, "required": ["position"]},
            steps=[{"tool": "play_visible_video", "args_template": {"position": "{position}"}}],
            aliases=[],
            patterns=[
                rf"^(play|open|click( on)?|start|watch)( the)? (?P<position>{ORD}) (video|result|one)( on (the )?(screen|page))?$",
                r"^(play |open )?(the )?(video|result) (number |no |#)?(?P<position>\d{1,2})$",
                rf"^(screen (pe|par) )?(dikh (rahe|raha|rahi) )?(?P<position>{ORD}) {VIDEO_HI}( ko)? (chalao|chala do|play karo|play kro|kholo|lagao|play)$",
            ],
        ),
        dict(
            name="rotate_screen",
            canonical_intent="rotate the screen (asks for approval)",
            params_schema={"type": "object", "properties": {"orientation": STR}},
            steps=[{"tool": "rotate_screen", "args_template": {"orientation": "{orientation}"}}],
            aliases=[],
            patterns=[
                r"^rotate (the |my )?(screen|display)( to| by)?( (?P<orientation>portrait|landscape|90|180|270|0|back|normal|upside down|left|right|default))?( degrees| degree| mode)?$",
                r"^(screen|display) (?P<orientation>rotate|ghumao|ulta|seedha|sidha|normal) (karo|kro|kar do)$",
                r"^(switch to |set |change to )?(the )?(screen |display )?(?P<orientation>portrait|landscape) mode$",
                r"^(?P<orientation>reset|undo|fix) (the )?(screen|display)? ?rotation$",
            ],
        ),
        dict(
            name="scroll_page",
            canonical_intent="scroll the page up or down",
            params_schema={"type": "object", "properties": {"direction": STR, "times": {"type": "string", "pattern": r"^\d+$"}},
                           "required": ["direction"]},
            steps=[{"tool": "scroll_page", "args_template": {"direction": "{direction}", "times": "{times}"}}],
            aliases=[],
            patterns=[
                r"^scroll( the page| it| page)? (?P<direction>up|down)( a bit| a little| more| again| please)?$",
                r"^scroll( the page)? (?P<direction>up|down) (?P<times>\d{1,2}) (times|pages|screens)$",
                r"^(scroll |go |jump )?(to )?(the )?(?P<direction>top|bottom)( of the page)?$",
                r"^(page )?(?P<direction>down|up)$",
                r"^(scroll )?(?P<direction>upar|uper|neeche|niche|nichey) (scroll )?(karo|kro|kar do|jao|chalo)$",
            ],
        ),
        dict(
            name="set_volume",
            canonical_intent="set the volume to a percentage",
            params_schema={"type": "object", "properties": {"level": {"type": "string", "pattern": r"^\d{1,3}$"}},
                           "required": ["level"]},
            steps=[{"tool": "set_volume", "args_template": {"level": "{level}"}}],
            aliases=[],
            patterns=[
                r"^(set |change |put )?(the )?volume (to |at |on )?(?P<level>\d{1,3})( percent| ?%)?$",
                r"^volume (?P<level>\d{1,3})( percent| ?%)? (karo|kro|kar do|pe karo|par karo|rakho)$",
                r"^(?P<level>\d{1,3})( percent| ?%)? (pe |par )?volume( karo| kro| kar do| rakho)?$",
            ],
        ),
        dict(
            name="skip_ad",
            canonical_intent="skip the youtube ad",
            params_schema={"type": "object", "properties": {}},
            steps=[{"tool": "skip_ad", "args_template": {}}],
            aliases=[],
            patterns=[
                r"^(please )?(skip|close|remove) (the |this )?(youtube )?(ad|ads|advert|advertisement)( please)?$",
                r"^(youtube )?(ad|ads|add|advertisement) (skip|hatao|hata do|band karo)( karo| kro| kar do)?$",
            ],
        ),
        dict(
            name="video_fullscreen",
            canonical_intent="youtube video fullscreen on/off",
            params_schema={"type": "object", "properties": {"mode": STR}},
            steps=[{"tool": "video_fullscreen", "args_template": {"mode": "{mode}"}}],
            aliases=[],
            patterns=[
                r"^(make (it|the video|video|this) |go |enter |open |video |youtube )?full[ -]?screen( mode)?( karo| kro| kar do| on| please)?$",
                r"^(?P<mode>exit|leave|close|turn off|escape) (the )?full[ -]?screen( mode)?$",
                r"^full[ -]?screen (?P<mode>band karo|hatao|off|exit|band|chhota karo)$",
            ],
        ),
        dict(
            name="set_timer",
            canonical_intent="set a timer or a reminder",
            params_schema={"type": "object", "properties": {"amount": {"type": "string", "pattern": r"^\d+$"},
                                                            "unit": STR, "label": STR},
                           "required": ["amount", "unit"]},
            steps=[{"tool": "set_timer", "args_template": {"amount": "{amount}", "unit": "{unit}", "label": "{label}"}}],
            aliases=[],
            patterns=[
                rf"^(set |start )?(a )?timer (for |of )?(?P<amount>\d+) ?(?P<unit>{UNITS})$",
                rf"^(set |start )?(a |an )?(?P<amount>\d+) ?(?P<unit>{UNITS}) timer$",
                rf"^remind me (in|after) (?P<amount>\d+) ?(?P<unit>{UNITS}) (to|about) (?P<label>.+)$",
                rf"^remind me (to|about) (?P<label>.+?) (in|after) (?P<amount>\d+) ?(?P<unit>{UNITS})$",
                rf"^(?P<amount>\d+) ?(?P<unit>{UNITS}) (ka |ke liye )?timer (laga do|lagao|set karo|set kro)$",
                rf"^(?P<amount>\d+) ?(?P<unit>{UNITS}) (baad|me|mein) (?P<label>.+?) (yaad dilana|yaad dila dena|remind karna)$",
            ],
        ),
        dict(
            name="site_search",
            canonical_intent="search on amazon, flipkart, wikipedia, github or stack overflow",
            params_schema={"type": "object", "properties": {"query": STR, "engine": STR}, "required": ["query", "engine"]},
            steps=[{"tool": "web_search", "args_template": {"query": "{query}", "engine": "{engine}"}}],
            aliases=[],
            patterns=[
                r"^(search |find |look up |look for |show |buy )?(for )?(?P<query>.+?) (on|in) (?P<engine>amazon|flipkart|wikipedia|github|stackoverflow)$",
                r"^(search )?(?P<engine>amazon|flipkart|wikipedia|github|stackoverflow) (for |search )?(?P<query>.+)$",
                r"^(?P<engine>amazon|flipkart|wikipedia|github|stackoverflow) (pe|par) (?P<query>.+?)( search karo| dikhao| dhundo)?$",
            ],
        ),
        dict(
            name="take_screenshot",
            canonical_intent="take a screenshot",
            params_schema={"type": "object", "properties": {}},
            steps=[{"tool": "take_screenshot", "args_template": {}}],
            aliases=["take a screenshot"],
            patterns=[
                r"^(take |capture |grab |save )?(a |the )?(screenshot|screen shot|screen capture|screengrab)( of (the |my )?screen)?( now)?$",
                r"^capture (the |my )?screen$",
                r"^(screenshot|ss) (lo|le lo|lelo|le do)$",
            ],
        ),
        dict(
            name="tell_time",
            canonical_intent="tell the current time or date",
            params_schema={"type": "object", "properties": {"what": STR}},
            steps=[{"tool": "tell_time", "args_template": {"what": "{what}"}}],
            aliases=["what time is it", "what is the date today"],
            patterns=[
                r"^(whats |what is |tell me |show |check )?(the )?(current |todays )?(?P<what>time|date|day)( is it| it is| now| right now| today| please)?$",
                r"^what (?P<what>time|day|date) is (it|today)( now| today| right now)?$",
                r"^(time|samay|tym) (kya hua|kya hai|batao|kya ho raha hai)$",
                r"^kitne baje( hai| hain| hai abhi)?$",
                r"^aaj (kya |kaun sa |kaunsa )?(?P<what>date|din|tareekh|day)( hai)?( kya hai)?$",
            ],
        ),
        dict(
            name="weather",
            canonical_intent="show the weather",
            params_schema={"type": "object", "properties": {"place": STR}},
            steps=[{"tool": "web_search", "args_template": {"query": "weather {place}"}}],
            aliases=[],
            patterns=[
                r"^(whats |what is |hows |how is |show |check |tell me )?(the |todays )?(weather|temperature|forecast)( forecast)?( like)?( today| now| right now| tomorrow)?$",
                r"^(whats |what is |hows |how is |show |check |tell me )?(the )?(weather|temperature|forecast)( forecast)?( like)? (in|at|for|of) (?P<place>.+?)( today| now| right now| tomorrow)?$",
                r"^(will it|is it going to|is it gonna) (rain|snow)( today| tomorrow)?$",
                r"^(aaj )?(ka )?(mausam|weather)( kaisa hai| batao| kya hai)?$",
                r"^(?P<place>.+?) (ka|me|mein) (mausam|weather)( kaisa hai| batao| kya hai)?$",
            ],
        ),
        dict(
            name="web_search",
            canonical_intent="search google or ask a question",
            params_schema={"type": "object", "properties": {"query": STR}, "required": ["query"]},
            steps=[{"tool": "web_search", "args_template": {"query": "{query}"}}],
            aliases=[],
            patterns=[
                r"^google (pe|par|me|mein) (?P<query>.+?)( search)?( karo| kro)?$",
                r"^(google|search google for|search the web for|web search|search online for|search on google for) (?P<query>.+)$",
                r"^(search for|search|look up|lookup|find) (?!(a )?videos? |youtube )(?P<query>.+?)(?<! on youtube)(?<! in youtube)( on google| online)?$",
                r"^(?P<query>(what|whats|who|whos|where|wheres|when|why|how|which|define|meaning of) .+)$",
                r"^(?P<query>.+?) (google|search) (karo|kro|kar do)$",
                r"^(?P<query>.+ (kya hai|kya hota hai|kaun hai|ka matlab))$",
            ],
        ),
    ]


SEEDS = build_seeds()


def seed(db: Database) -> None:
    """Insert missing seeds; when a seed changed in code, save it as a new version (old row kept)."""
    for s in build_seeds():
        cur = db.get_workflow_by_name(s["name"])
        if cur is None:
            db.save_workflow(**s)
        elif (cur.steps != s["steps"] or cur.params_schema != s["params_schema"] or cur.patterns != s["patterns"]
              or not set(s["aliases"]) <= set(cur.aliases) or cur.canonical_intent != s["canonical_intent"]):
            db.save_workflow(**s, replace_patterns=True)
