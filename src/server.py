"""
TOE Vault MCP Server
Gives Claude full read/write access to the toe-vault GitHub repo.
Implements the MCP protocol over HTTP+SSE.
"""

import os
import base64
import json
import asyncio
from typing import Optional, Any
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
import httpx

app = FastAPI(title="TOE Vault MCP Server")

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_OWNER = os.environ["GITHUB_OWNER"]
GITHUB_REPO = os.environ.get("GITHUB_REPO", "toe-vault")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

BASE_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"

# ── MCP Tool Definitions ──────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "read_file",
        "description": "Read any file from the TOE vault GitHub repo.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path in the repo e.g. '00 - Index/note.md'"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "write_file",
        "description": "Create or update a file in the TOE vault GitHub repo.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path in the repo"},
                "content": {"type": "string", "description": "Full file content"},
                "message": {"type": "string", "description": "Optional commit message"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "delete_file",
        "description": "Delete a file from the TOE vault GitHub repo.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to delete"},
                "message": {"type": "string", "description": "Optional commit message"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "move_file",
        "description": "Move or rename a file in the TOE vault GitHub repo.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "old_path": {"type": "string", "description": "Current file path"},
                "new_path": {"type": "string", "description": "New file path"},
                "message": {"type": "string", "description": "Optional commit message"}
            },
            "required": ["old_path", "new_path"]
        }
    },
    {
        "name": "list_files",
        "description": "List files and folders at a given path in the TOE vault.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Folder path, empty string for root"}
            },
            "required": []
        }
    },
    {
        "name": "search_vault",
        "description": "Search TOE vault files by name or content.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"]
        }
    }
]

# ── GitHub Helpers ────────────────────────────────────────────────────────────

async def get_file_sha(path: str) -> Optional[str]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/contents/{path}",
            headers=HEADERS,
            params={"ref": GITHUB_BRANCH},
        )
        if r.status_code == 200:
            return r.json().get("sha")
        return None


async def gh_read_file(path: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/contents/{path}",
            headers=HEADERS,
            params={"ref": GITHUB_BRANCH},
        )
    if r.status_code == 404:
        raise ValueError(f"File not found: {path}")
    if r.status_code != 200:
        raise ValueError(f"GitHub error: {r.text}")
    data = r.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return {"path": path, "content": content, "sha": data["sha"]}


async def gh_write_file(path: str, content: str, message: Optional[str] = None) -> dict:
    sha = await get_file_sha(path)
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    payload = {
        "message": message or f"claude: write {path}",
        "content": encoded,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha
    async with httpx.AsyncClient() as client:
        r = await client.put(f"{BASE_URL}/contents/{path}", headers=HEADERS, json=payload)
    if r.status_code not in (200, 201):
        raise ValueError(f"GitHub error: {r.text}")
    return {"status": "ok", "action": "updated" if sha else "created", "path": path}


async def gh_delete_file(path: str, message: Optional[str] = None) -> dict:
    sha = await get_file_sha(path)
    if not sha:
        raise ValueError(f"File not found: {path}")
    payload = {"message": message or f"claude: delete {path}", "sha": sha, "branch": GITHUB_BRANCH}
    async with httpx.AsyncClient() as client:
        r = await client.request("DELETE", f"{BASE_URL}/contents/{path}", headers=HEADERS, json=payload)
    if r.status_code != 200:
        raise ValueError(f"GitHub error: {r.text}")
    return {"status": "ok", "action": "deleted", "path": path}


async def gh_move_file(old_path: str, new_path: str, message: Optional[str] = None) -> dict:
    read = await gh_read_file(old_path)
    await gh_write_file(new_path, read["content"], message or f"claude: move {old_path} to {new_path}")
    await gh_delete_file(old_path, f"claude: move cleanup {old_path}")
    return {"status": "ok", "action": "moved", "from": old_path, "to": new_path}


async def gh_list_files(path: str = "") -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/contents/{path}",
            headers=HEADERS,
            params={"ref": GITHUB_BRANCH}
        )
    if r.status_code == 404:
        raise ValueError(f"Path not found: {path}")
    if r.status_code != 200:
        raise ValueError(f"GitHub error: {r.text}")
    items = r.json()
    return {"path": path, "items": [{"name": i["name"], "type": i["type"], "path": i["path"]} for i in items]}


async def gh_search_vault(query: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.github.com/search/code",
            headers=HEADERS,
            params={"q": f"{query} repo:{GITHUB_OWNER}/{GITHUB_REPO}", "per_page": 20},
        )
    if r.status_code != 200:
        raise ValueError(f"GitHub error: {r.text}")
    results = r.json().get("items", [])
    return {"query": query, "results": [{"name": i["name"], "path": i["path"]} for i in results]}


async def call_tool(name: str, arguments: dict) -> Any:
    if name == "read_file":
        return await gh_read_file(arguments["path"])
    elif name == "write_file":
        return await gh_write_file(arguments["path"], arguments["content"], arguments.get("message"))
    elif name == "delete_file":
        return await gh_delete_file(arguments["path"], arguments.get("message"))
    elif name == "move_file":
        return await gh_move_file(arguments["old_path"], arguments["new_path"], arguments.get("message"))
    elif name == "list_files":
        return await gh_list_files(arguments.get("path", ""))
    elif name == "search_vault":
        return await gh_search_vault(arguments["query"])
    else:
        raise ValueError(f"Unknown tool: {name}")


# ── MCP Protocol Handler ──────────────────────────────────────────────────────

async def handle_mcp_message(message: dict) -> Optional[dict]:
    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "toe-vault", "version": "1.0.0"}
            }
        }

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "result": {"tools": TOOLS}
        }

    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        try:
            result = await call_tool(tool_name, arguments)
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, indent=2)}]
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                    "isError": True
                }
            }

    elif method == "notifications/initialized":
        return None

    else:
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }


# ── MCP SSE Endpoints ─────────────────────────────────────────────────────────

@app.get("/sse")
async def sse_endpoint(request: Request):
    """SSE endpoint — Claude connects here to discover the message endpoint."""
    async def event_stream():
        yield f"event: endpoint\ndata: /messages\n\n"
        while True:
            if await request.is_disconnected():
                break
            yield ": ping\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


@app.post("/messages")
async def messages_endpoint(request: Request):
    """Handle MCP JSON-RPC messages."""
    body = await request.json()
    response = await handle_mcp_message(body)
    if response is None:
        return JSONResponse(content={})
    return JSONResponse(content=response)


@app.get("/health")
async def health():
    return {"status": "ok", "repo": f"{GITHUB_OWNER}/{GITHUB_REPO}"}
