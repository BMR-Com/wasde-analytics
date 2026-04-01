import os, json, io, sys
import pandas as pd
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta

DATA_DIR    = Path("data")
DATA_DIR.mkdir(exist_ok=True)
MASTER_PATH = os.environ.get("MASTER_CSV_PATH", "master_wasde.csv")

# ── 1. Download CSV from GitHub Release ──────────────────────
def download_from_release():
    import urllib.request
    repo  = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    tag   = "data-store"
    fname = "master_wasde.csv"

    api_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    req = urllib.request.Request(api_url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    })
    with urllib.request.urlopen(req) as r:
        release = json.loads(r.read())

    asset = next((a for a in release["assets"] if a["name"] == fname), None)
    if not asset:
        raise FileNotFoundError(f"{fname} not found in release assets. "
                                f"Did you upload it to the data-store release?")

    print(f"Downloading {fname} ({asset['size']//1024//1024} MB)...")
    dl_req = urllib.request.Request(asset["url"], headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/octet-stream"
    })
    with urllib.request.urlopen(dl_req) as r, open(MASTER_PATH, "wb") as f:
        f.write(r.read())
    print(f"✅ Downloaded — {Path(MASTER_PATH).stat().st_size//1024//1024} MB")

# ── 2. Fetch & append latest WASDE month ─────────────────────
def fetch_and_append():
    from curl_cffi import requests as cf

    df_master  = pd.read_csv(MASTER_PATH, low_memory=False)
    latest_num = pd.to_numeric(df_master["WasdeNumber"], errors="coerce").max()
    print(f"Current latest WasdeNumber: {int(latest_num)}")
