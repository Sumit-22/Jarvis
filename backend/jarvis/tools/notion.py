"""Notion API client and tools. Payloads are built only from user-provided text."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx
from pydantic import Field

from .base import Tool, ToolInput, ToolResult, VerificationResult

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
MAX_TEXT = 2000  # Notion rich_text content limit per item


class NotionError(Exception):
    pass


def _rich(text: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": {"content": text[i:i + MAX_TEXT]}} for i in range(0, len(text), MAX_TEXT)] or [
        {"type": "text", "text": {"content": ""}}]


def paragraph_blocks(contents: list[str]) -> list[dict[str, Any]]:
    blocks = []
    for c in contents:
        for line in c.split("\n"):
            if line.strip():
                blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich(line)}})
    return blocks[:100]  # API limit per request


def page_payload(parent_id: str, title: str, contents: list[str]) -> dict[str, Any]:
    return {
        "parent": {"page_id": parent_id},
        "properties": {"title": {"title": _rich(title)}},
        "children": paragraph_blocks(contents),
    }


class NotionClient:
    def __init__(self, token: str, *, transport: httpx.AsyncBaseTransport | None = None, max_retries: int = 4,
                 base_delay: float = 1.0):
        self._headers = {"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION,
                         "Content-Type": "application/json"}
        self._transport = transport
        self.max_retries = max_retries
        self.base_delay = base_delay

    async def request(self, method: str, path: str, json: dict | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=NOTION_API, headers=self._headers, timeout=30,
                                     transport=self._transport) as c:
            for attempt in range(self.max_retries + 1):
                r = await c.request(method, path, json=json)
                if r.status_code == 429 and attempt < self.max_retries:
                    retry_after = float(r.headers.get("Retry-After", self.base_delay * 2 ** attempt))
                    await asyncio.sleep(min(retry_after, 30))
                    continue
                if r.status_code >= 400:
                    try:
                        msg = r.json().get("message", r.text)
                    except Exception:
                        msg = r.text
                    raise NotionError(f"Notion {r.status_code}: {msg}")
                return r.json()
        raise NotionError("Notion rate limit: retries exhausted")

    async def check_parent(self, page_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/pages/{page_id}")

    async def create_page(self, parent_id: str, title: str, contents: list[str]) -> dict[str, Any]:
        return await self.request("POST", "/pages", page_payload(parent_id, title, contents))

    async def create_db_entry(self, database_id: str, properties: dict[str, Any]) -> dict[str, Any]:
        return await self.request("POST", "/pages", {"parent": {"database_id": database_id}, "properties": properties})


def _client(ctx: Any) -> NotionClient:
    c = ctx.get("notion")
    if c is None:
        raise NotionError("NOTION_TOKEN is not set in .env")
    return c


class CreatePageInput(ToolInput):
    title: str = Field(min_length=1, max_length=200)
    content_blocks: list[str] = Field(default_factory=list)
    parent_id: str | None = None


class CreateNotionPage(Tool):
    name = "create_notion_page"
    description = "Create a Notion page under the configured parent page, with the user's own text."
    input_model = CreatePageInput
    requires_approval = True
    timeout_s = 60.0

    def _parent(self, args: CreatePageInput) -> str:
        return args.parent_id or self.ctx.settings.notion_parent_page_id

    def describe_approval(self, args: CreatePageInput) -> str:
        body = "\n".join(args.content_blocks)
        return (f"Create a Notion page titled \"{args.title}\" under parent {self._parent(args) or '(not set)'} "
                f"with this content:\n{body[:1500]}")

    async def run(self, args: CreatePageInput) -> ToolResult:
        parent = self._parent(args)
        if not parent:
            return ToolResult(ok=False, error="NOTION_PARENT_PAGE_ID is not set")
        try:
            r = await _client(self.ctx).create_page(parent, args.title, args.content_blocks)
        except NotionError as e:
            return ToolResult(ok=False, error=str(e))
        return ToolResult(ok=True, data={"id": r.get("id"), "url": r.get("url")})

    async def verify(self, args: CreatePageInput, result: ToolResult) -> VerificationResult:
        ok = bool(result.data.get("id") and result.data.get("url"))
        return VerificationResult(passed=ok, detail=result.data.get("url") or "no page id/url in response")


class CreateDbEntryInput(ToolInput):
    database_id: str | None = None
    properties: dict[str, Any]


class CreateNotionDbEntry(Tool):
    name = "create_notion_db_entry"
    description = "Add an entry to a Notion database. properties uses Notion's property JSON format."
    input_model = CreateDbEntryInput
    requires_approval = True
    timeout_s = 60.0

    def describe_approval(self, args: CreateDbEntryInput) -> str:
        db = args.database_id or self.ctx.settings.notion_database_id
        return f"Add an entry to Notion database {db or '(not set)'} with properties: {args.properties}"

    async def run(self, args: CreateDbEntryInput) -> ToolResult:
        db = args.database_id or self.ctx.settings.notion_database_id
        if not db:
            return ToolResult(ok=False, error="No database_id given and NOTION_DATABASE_ID is not set")
        try:
            r = await _client(self.ctx).create_db_entry(db, args.properties)
        except NotionError as e:
            return ToolResult(ok=False, error=str(e))
        return ToolResult(ok=True, data={"id": r.get("id"), "url": r.get("url")})

    async def verify(self, args: CreateDbEntryInput, result: ToolResult) -> VerificationResult:
        return VerificationResult(passed=bool(result.data.get("id")), detail=result.data.get("url") or "")
