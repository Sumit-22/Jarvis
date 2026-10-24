"""skip_ad clicks YouTube's Skip button in JARVIS's browser and reads back whether the ad is gone."""
from __future__ import annotations

import pytest

from jarvis.tools.base import ToolContext
from jarvis.tools.daily import MediaKeyInput, SkipAd, SkipAdInput


class AdPage:
    def __init__(self, ad=True, skip_after_ticks=0, url="https://www.youtube.com/watch?v=abc", ads_in_break=1):
        self.url, self.ad, self.ticks, self.skip_after = url, ad, 0, skip_after_ticks
        self.ads_left, self.clicks = ads_in_break, 0

    async def evaluate(self, js, arg=None):
        assert "ad-showing" in js
        return self.ad

    async def wait_for_timeout(self, ms):
        self.ticks += 1

    def locator(self, sel):
        page = self

        class Button:
            async def is_visible(self):
                return page.ad and page.skip_after is not None and page.ticks >= page.skip_after

            async def click(self):
                page.clicks += 1
                page.ads_left -= 1
                page.ad = page.ads_left > 0

        class Buttons:
            async def count(self):
                return 1

            def nth(self, i):
                return Button()
        return Buttons()


class FakeBrowser:
    def __init__(self, page):
        self.page_ = page

    def current_page(self, window):
        return self.page_


async def _run(page, **kw):
    tool = SkipAd(ToolContext(browser=FakeBrowser(page)))
    args = SkipAdInput(**kw)
    r = await tool.run(args)
    return r, (await tool.verify(args, r) if r.ok else None)  # the executor only verifies ok results


async def test_clicks_skip_once_it_appears():
    page = AdPage(skip_after_ticks=8)  # button shows after ~2s countdown
    r, v = await _run(page)
    assert page.clicks == 1 and not page.ad and v.passed and r.data["say"] == "Ad skipped."


async def test_no_ad_is_a_pass_without_clicking():
    page = AdPage(ad=False)
    r, v = await _run(page)
    assert page.clicks == 0 and v.passed and r.data["say"] == "No ad is playing."


async def test_unskippable_ad_fails_verification():
    page = AdPage(skip_after_ticks=None)
    r, v = await _run(page, wait_s=1)
    assert page.clicks == 0 and not v.passed and "unskippable" in v.detail


async def test_second_ad_in_break_still_counts_as_skipped():
    page = AdPage(ads_in_break=2)
    r, v = await _run(page)
    assert page.clicks == 1 and page.ad and v.passed and "another ad" in r.data["say"]


async def test_needs_a_youtube_video():
    r, _ = await _run(AdPage(url="https://www.google.com/"))
    assert not r.ok


def test_hinglish_play_pause_words():
    assert MediaKeyInput(action="play karo").action == "play"
    assert MediaKeyInput(action="pause kar do").action == "pause"
    assert MediaKeyInput(action="wapas chalao").action == "play"
    assert MediaKeyInput(action="skip").action == "next"  # plain "skip" still means next track, not skip ad
