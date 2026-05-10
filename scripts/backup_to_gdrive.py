"""
TOE Vault → Google Drive Backup
- Daily snapshots kept for 30 days in Recent/
- Monthly snapshots kept indefinitely in Monthly/
"""

import os
import json
import zipfile
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ── Auth ──────────────────────────────────────────────────────────────────────

creds_json = json.loads(os.environ["GDRIVE_CREDENTIALS"])
creds = Credentials.from_service_account_info(
    creds_json,
    scopes=["https://www.googleapis.com/auth/drive"],
)
drive = build("drive", "v3", credentials=creds)

BACKUP_FOLDER_ID = os.environ["GDRIVE_BACKUP_FOLDER_ID"]
TODAY = datetime.utcnow()
DATE_STR = TODAY.strftime("%Y-%m-%d")
MONTH_STR = TODAY.strftime("%Y-%m")


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_or_create_folder(name: str, parent_id: str) -> str:
    """Get folder ID by name, create if missing."""
    q = f"name='{name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = drive.files().list(q=q, fields="files(id)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    folder = drive.files().create(body={
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }, fields="id").execute()
    return folder["id"]


def zip_vault() -> str:
    """Zip the current vault directory."""
    vault_path = Path(".")
    zip_path = tempfile.mktemp(suffix=".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in vault_path.rglob("*"):
            if f.is_file() and ".git" not in f.parts:
                zf.write(f, f.relative_to(vault_path))
    return zip_path


def upload_zip(zip_path: str, name: str, folder_id: str):
    """Upload zip file to Google Drive folder."""
    media = MediaFileUpload(zip_path, mimetype="application/zip")
    drive.files().create(
        body={"name": name, "parents": [folder_id]},
        media_body=media,
        fields="id",
    ).execute()
    print(f"✓ Uploaded {name} to folder {folder_id}")


def delete_old_backups(folder_id: str, keep_days: int = 30):
    """Delete daily backups older than keep_days."""
    cutoff = TODAY - timedelta(days=keep_days)
    results = drive.files().list(
        q=f"'{folder_id}' in parents and trashed=false",
        fields="files(id, name, createdTime)",
    ).execute()

    for f in results.get("files", []):
        created = datetime.fromisoformat(f["createdTime"].replace("Z", "+00:00"))
        if created.replace(tzinfo=None) < cutoff:
            drive.files().delete(fileId=f["id"]).execute()
            print(f"✓ Deleted old backup: {f['name']}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(f"Starting backup for {DATE_STR}...")

    # Zip vault
    zip_path = zip_vault()
    zip_name = f"toe-vault-{DATE_STR}.zip"

    # Daily backup → Recent/
    recent_folder = get_or_create_folder("Recent", BACKUP_FOLDER_ID)
    upload_zip(zip_path, zip_name, recent_folder)
    delete_old_backups(recent_folder, keep_days=30)

    # Monthly backup → Monthly/ (only on 1st of month)
    if TODAY.day == 1:
        monthly_folder = get_or_create_folder("Monthly", BACKUP_FOLDER_ID)
        monthly_name = f"toe-vault-{MONTH_STR}.zip"
        upload_zip(zip_path, monthly_name, monthly_folder)
        print(f"✓ Monthly backup created: {monthly_name}")

    print("Backup complete.")


if __name__ == "__main__":
    main()
