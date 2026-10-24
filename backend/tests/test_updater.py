"""The updater against real git repos: an 'origin' with main, and an installed clone of it."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from jarvis.updater import Updater, UpdateError


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, name: str, text: str, msg: str) -> None:
    f = repo / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)


@pytest.fixture
def repos(tmp_path: Path) -> tuple[Path, Path]:
    dev = tmp_path / "dev"
    dev.mkdir()
    git(dev, "init", "-q", "-b", "main")
    commit(dev, "README.md", "v1", "first")
    app = tmp_path / "app"
    git(tmp_path, "clone", "-q", "--branch", "main", str(dev), str(app))
    (app / "frontend" / "dist").mkdir(parents=True)  # a built dashboard, so a code-only update needs no npm
    return dev, app


async def test_up_to_date(repos):
    _, app = repos
    st = await Updater(app).check()
    assert st["supported"] and st["behind"] == 0 and not st["can_update"]


async def test_finds_and_applies_new_commits(repos):
    dev, app = repos
    commit(dev, "README.md", "v2", "Skip ad added")
    events = []
    upd = Updater(app, emit=lambda t, **k: events.append((t, k)))
    st = await upd.check()
    assert st["behind"] == 1 and st["can_update"] and st["commits"][0]["subject"] == "Skip ad added"
    r = await upd.apply()
    assert r["updated"] and r["restart_required"]
    assert (app / "README.md").read_text(encoding="utf-8") == "v2"
    assert ("update_done", ) == events[-1][:1] and any(t == "update_progress" for t, _ in events)
    assert (await upd.check())["behind"] == 0


async def test_local_changes_block_the_update(repos):
    dev, app = repos
    commit(dev, "README.md", "v2", "new")
    (app / "README.md").write_text("edited here", encoding="utf-8")
    upd = Updater(app)
    st = await upd.check()
    assert st["behind"] == 1 and not st["can_update"] and "local changes" in st["reason"]
    r = await upd.apply()
    assert not r["updated"] and (app / "README.md").read_text(encoding="utf-8") == "edited here"


async def test_other_branch_is_not_updated(repos):
    _, app = repos
    git(app, "checkout", "-q", "-b", "FB_001")
    st = await Updater(app).check()
    assert not st["supported"] and "FB_001" in st["reason"]


async def test_failed_dashboard_build_rolls_back(repos, monkeypatch):
    dev, app = repos
    before = git(app, "rev-parse", "HEAD")
    commit(dev, "frontend/src/App.tsx", "broken", "UI change")
    upd = Updater(app)

    def fail(reinstall: bool) -> None:
        raise UpdateError("npm run build failed")
    monkeypatch.setattr(upd, "_build_dashboard", fail)
    with pytest.raises(UpdateError):
        await upd.apply()
    assert git(app, "rev-parse", "HEAD") == before  # code back where it was, matching the old dashboard
