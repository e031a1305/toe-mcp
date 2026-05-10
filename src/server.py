"""
TOE Vault MCP Server
Gives Claude full read/write access to the toe-vault GitHub repo.
"""

import os
import base64
import json
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
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


# ── Models ────────────────────────────────────────────────────────────────────

class WriteFile(BaseModel):
    path: str
    content: str
    message: Optional[str] = None

class MoveFile(BaseModel):
    old_path: str
    new_path: str
    message: Optional[str] = None

class DeleteFile(BaseModel):
    path: str
    message: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

async def get_file_sha(path: str) -> Optional[str]:
    """Get the SHA of an existing file (required for updates/deletes)."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/contents/{path}",
            headers=HEADERS,
            params={"ref": GITHUB_BRANCH},
        )
        if r.status_code == 200:
            return r.json().get("sha")
        return None


# ── Tools ─────────────────────────────────────────────────────────────────────

@app.get("/read_file")
async def read_file(path: str):
    """Read any file from the vault."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/contents/{path}",
            headers=HEADERS,
            params={"ref": GITHUB_BRANCH},
        )
    if r.status_code == 404:
        raise HTTPException(404, f"File not found: {path}")
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)

    data = r.json()
    content = base64.b64decode(data["content"]).decode("utf-8")
    return {"path": path, "content": content, "sha": data["sha"]}


@app.post("/write_file")
async def write_file(body: WriteFile):
    """Create or update a file in the vault."""
    sha = await get_file_sha(body.path)
    encoded = base64.b64encode(body.content.encode("utf-8")).decode("utf-8")

    payload = {
        "message": body.message or f"claude: write {body.path}",
        "content": encoded,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha  # required for updates

    async with httpx.AsyncClient() as client:
        r = await client.put(
            f"{BASE_URL}/contents/{body.path}",
            headers=HEADERS,
            json=payload,
        )

    if r.status_code not in (200, 201):
        raise HTTPException(r.status_code, r.text)

    action = "updated" if sha else "created"
    return {"status": "ok", "action": action, "path": body.path}


@app.delete("/delete_file")
async def delete_file(body: DeleteFile):
    """Delete a file from the vault."""
    sha = await get_file_sha(body.path)
    if not sha:
        raise HTTPException(404, f"File not found: {body.path}")

    payload = {
        "message": body.message or f"claude: delete {body.path}",
        "sha": sha,
        "branch": GITHUB_BRANCH,
    }

    async with httpx.AsyncClient() as client:
        r = await client.request(
            "DELETE",
            f"{BASE_URL}/contents/{body.path}",
            headers=HEADERS,
            json=payload,
        )

    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)

    return {"status": "ok", "action": "deleted", "path": body.path}


@app.post("/move_file")
async def move_file(body: MoveFile):
    """Move or rename a file (read → write new → delete old)."""
    # Read original
    read = await read_file(body.old_path)

    # Write to new path
    await write_file(WriteFile(
        path=body.new_path,
        content=read["content"],
        message=body.message or f"claude: move {body.old_path} → {body.new_path}",
    ))

    # Delete original
    await delete_file(DeleteFile(
        path=body.old_path,
        message=f"claude: move cleanup {body.old_path}",
    ))

    return {"status": "ok", "action": "moved", "from": body.old_path, "to": body.new_path}


@app.get("/list_files")
async def list_files(path: str = ""):
    """List files and folders at a given path."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{BASE_URL}/contents/{path}",
            headers=HEADERS,
            params={"ref": GITHUB_BRANCH},
        )

    if r.status_code == 404:
        raise HTTPException(404, f"Path not found: {path}")
    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)

    items = r.json()
    return {
        "path": path,
        "items": [
            {"name": i["name"], "type": i["type"], "path": i["path"]}
            for i in items
        ],
    }


@app.get("/search_vault")
async def search_vault(query: str):
    """Search vault files by name or content."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"https://api.github.com/search/code",
            headers=HEADERS,
            params={
                "q": f"{query} repo:{GITHUB_OWNER}/{GITHUB_REPO}",
                "per_page": 20,
            },
        )

    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)

    results = r.json().get("items", [])
    return {
        "query": query,
        "results": [
            {"name": i["name"], "path": i["path"]}
            for i in results
        ],
    }


@app.get("/health")
async def health():
    return {"status": "ok", "repo": f"{GITHUB_OWNER}/{GITHUB_REPO}"}
