"""
TOE Vault MCP Server
Uses the official MCP Python SDK (FastMCP) with Streamable HTTP transport.
Gives Claude full read/write access to the toe-vault GitHub repo.
"""

import os
import base64
from typing import Optional
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("toe-vault")

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_OWNER = os.environ["GITHUB_OWNER"]
GITHUB_REPO = os.environ.get("GITHUB_REPO", "toe-vault")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

GH_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

BASE_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"


# ── Helpers ───────────────────────────────────────────────────────────────────

async def get_sha(path: str) -> Optional[str]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/contents/{path}",
            headers=GH_HEADERS,
            params={"ref": GITHUB_BRANCH},
        )
    return r.json().get("sha") if r.status_code == 200 else None


# ── Tools ─────────────────────────────────────────────────────────────────────

@mcp.tool()
async def read_file(path: str) -> str:
    """Read any file from the TOE vault. Path example: '00 - Index/note.md'"""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/contents/{path}",
            headers=GH_HEADERS,
            params={"ref": GITHUB_BRANCH},
        )
    if r.status_code == 404:
        return f"Error: File not found: {path}"
    if r.status_code != 200:
        return f"Error: {r.text}"
    content = base64.b64decode(r.json()["content"]).decode("utf-8")
    return content


@mcp.tool()
async def write_file(path: str, content: str, message: str = "") -> str:
    """Create or update any file in the TOE vault."""
    sha = await get_sha(path)
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    payload = {
        "message": message or f"claude: write {path}",
        "content": encoded,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha
    async with httpx.AsyncClient() as client:
        r = await client.put(
            f"{BASE_URL}/contents/{path}",
            headers=GH_HEADERS,
            json=payload,
        )
    if r.status_code not in (200, 201):
        return f"Error: {r.text}"
    return f"{'Updated' if sha else 'Created'}: {path}"


@mcp.tool()
async def delete_file(path: str, message: str = "") -> str:
    """Delete a file from the TOE vault."""
    sha = await get_sha(path)
    if not sha:
        return f"Error: File not found: {path}"
    payload = {
        "message": message or f"claude: delete {path}",
        "sha": sha,
        "branch": GITHUB_BRANCH,
    }
    async with httpx.AsyncClient() as client:
        r = await client.request(
            "DELETE",
            f"{BASE_URL}/contents/{path}",
            headers=GH_HEADERS,
            json=payload,
        )
    if r.status_code != 200:
        return f"Error: {r.text}"
    return f"Deleted: {path}"


@mcp.tool()
async def move_file(old_path: str, new_path: str, message: str = "") -> str:
    """Move or rename a file in the TOE vault."""
    content = await read_file(old_path)
    if content.startswith("Error:"):
        return content
    result = await write_file(new_path, content, message or f"claude: move {old_path} to {new_path}")
    if result.startswith("Error:"):
        return result
    await delete_file(old_path, f"claude: move cleanup {old_path}")
    return f"Moved: {old_path} → {new_path}"


@mcp.tool()
async def list_files(path: str = "") -> str:
    """List files and folders in the TOE vault at the given path."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/contents/{path}",
            headers=GH_HEADERS,
            params={"ref": GITHUB_BRANCH},
        )
    if r.status_code == 404:
        return f"Error: Path not found: {path}"
    if r.status_code != 200:
        return f"Error: {r.text}"
    items = r.json()
    lines = [f"{'[dir]' if i['type'] == 'dir' else '[file]'} {i['path']}" for i in items]
    return "\n".join(lines)


@mcp.tool()
async def search_vault(query: str) -> str:
    """Search the TOE vault by filename or content."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.github.com/search/code",
            headers=GH_HEADERS,
            params={"q": f"{query} repo:{GITHUB_OWNER}/{GITHUB_REPO}", "per_page": 20},
        )
    if r.status_code != 200:
        return f"Error: {r.text}"
    results = r.json().get("items", [])
    if not results:
        return "No results found."
    lines = [f"{i['path']}" for i in results]
    return "\n".join(lines)


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(mcp.streamable_http_app(), host="0.0.0.0", port=port)
