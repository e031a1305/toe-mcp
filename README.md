# TOE Vault MCP Server

Gives Claude full read/write access to the `toe-vault` GitHub repo, with automatic daily backups to Google Drive.

---

## Architecture

```
Claude → TOE MCP Server (Railway) → GitHub API → toe-vault repo
                                                        ↓
                                              Obsidian Git syncs
                                                        ↓
                                         Google Drive (daily backup)
                                              ├── Recent/ (30 days)
                                              └── Monthly/ (indefinite)
```

---

## Part 1 — Deploy the MCP Server to Railway

### Step 1 — Push this repo to GitHub

```bash
cd toe-mcp
git init
git add .
git commit -m "initial: TOE MCP server"
git remote add origin https://github.com/e031a1305/toe-mcp.git
git push -u origin main
```

> Create the `toe-mcp` repo on GitHub first (private)

### Step 2 — Create a GitHub Personal Access Token (PAT)

1. Go to https://github.com/settings/tokens
2. Click **Generate new token (classic)**
3. Name it: `toe-vault-mcp`
4. Select scopes: ✅ `repo` (full repo access)
5. Click **Generate token**
6. **Copy the token** — you only see it once

### Step 3 — Deploy to Railway

1. Go to https://railway.app and sign in with GitHub
2. Click **New Project → Deploy from GitHub repo**
3. Select your `toe-mcp` repo
4. Go to **Variables** tab and add:

| Variable | Value |
|---|---|
| `GITHUB_TOKEN` | your PAT from Step 2 |
| `GITHUB_OWNER` | `e031a1305` |
| `GITHUB_REPO` | `toe-vault` |
| `GITHUB_BRANCH` | `main` |

5. Railway auto-deploys. Copy the **public URL** it gives you (e.g. `https://toe-mcp.railway.app`)

### Step 4 — Test the server

```bash
curl https://your-railway-url.railway.app/health
```

Should return: `{"status":"ok","repo":"e031a1305/toe-vault"}`

### Step 5 — Register as custom connector in Claude

1. In Claude.ai → Settings → Connectors → **Add custom connector**
2. Enter your Railway URL
3. Claude now has full vault access

---

## Part 2 — Google Drive Backup

### Step 1 — Create a Google Service Account

1. Go to https://console.cloud.google.com
2. Create a new project called `toe-backup`
3. Enable the **Google Drive API**
4. Go to **IAM → Service Accounts → Create**
5. Name it `toe-backup-bot`
6. Click **Keys → Add Key → JSON** — download the file
7. Share your Google Drive backup folder with the service account email

### Step 2 — Create backup folder in Google Drive

1. Create a folder in Google Drive called `toe-vault-backups`
2. Right-click → Share → add the service account email as Editor
3. Copy the folder ID from the URL: `drive.google.com/drive/folders/THIS_PART`

### Step 3 — Add secrets to GitHub

In your `toe-vault` repo → Settings → Secrets → Actions:

| Secret | Value |
|---|---|
| `GDRIVE_CREDENTIALS` | contents of the JSON key file |
| `GDRIVE_BACKUP_FOLDER_ID` | folder ID from Step 2 |

### Step 4 — Enable the workflow

The backup runs automatically every night at midnight UTC.
To test manually: GitHub → Actions → **Vault Backup to Google Drive** → Run workflow

---

## Tools available to Claude

| Endpoint | Method | What it does |
|---|---|---|
| `/read_file?path=` | GET | Read any file |
| `/write_file` | POST | Create or update any file |
| `/delete_file` | DELETE | Delete a file |
| `/move_file` | POST | Move or rename a file |
| `/list_files?path=` | GET | List folder contents |
| `/search_vault?query=` | GET | Search by name or content |
| `/health` | GET | Server health check |
