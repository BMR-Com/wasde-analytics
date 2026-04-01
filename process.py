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
    repo  = os.environ["GITHUB_REPOSITORY"]       # auto-set by Actions
    token = os.environ["GITHUB_TOKEN"]             # auto-set by Actions
    tag   = "data-store"
    fname = "master_wasde.csv"

    # Get release by tag
    api_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    req = urllib.request.Request(api_url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    })
    with urllib.request.urlopen(req) as r:
        release = json.loads(r.read())

    # Find the CSV asset
    asset = next((a for a in release["assets"] if a["name"] == fname), None)
    if not asset:
        raise FileNotFoundError(f"{fname} not found in release assets")

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

    check = datetime.today().replace(day=1)
    for _ in range(4):
        y = check.strftime("%Y")
        m = check.strftime("%m")
        url = (f"https://www.usda.gov/sites/default/files/documents/"
               f"oce-wasde-report-data-{y}-{m}.csv")
        print(f"Checking {y}-{m}...", end=" ")
        try:
            r = cf.get(url, impersonate="chrome120", timeout=60)
            if r.status_code == 200 and len(r.content) > 5000:
                df_new = pd.read_csv(
                    io.StringIO(r.content.decode("utf-8-sig")), low_memory=False)
                if "Report Title" in df_new.columns:
                    df_new = df_new[~df_new["Report Title"].str.contains(
                        "Reliability", case=False, na=False)]
                new_num = pd.to_numeric(df_new["WasdeNumber"], errors="coerce").max()
                if new_num > latest_num:
                    df_new["Source_Report"] = f"{y}-{m}"
                    combined = pd.concat([df_master, df_new], ignore_index=True)
                    combined = combined.drop_duplicates(subset=[
                        "WasdeNumber","Commodity","Region","MarketYear","Attribute"])
                    combined.to_csv(MASTER_PATH, index=False, encoding="utf-8-sig")
                    print(f"✅ Appended WasdeNumber {int(new_num)}")
                    return True
                else:
                    print(f"Already up to date ({int(new_num)})")
                    return False
            else:
                print(f"HTTP {r.status_code}")
        except Exception as e:
            print(f"Error: {e}")
        check -= relativedelta(months=1)
    return False

# ── 3. Upload updated CSV back to GitHub Release ─────────────
def upload_to_release():
    import urllib.request, urllib.error
    repo  = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    tag   = "data-store"
    fname = "master_wasde.csv"

    headers_json = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json"
    }

    # Get release id
    api_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    req = urllib.request.Request(api_url, headers=headers_json)
    with urllib.request.urlopen(req) as r:
        release = json.loads(r.read())
    release_id = release["id"]

    # Delete existing asset if present
    for asset in release.get("assets", []):
        if asset["name"] == fname:
            del_req = urllib.request.Request(
                f"https://api.github.com/repos/{repo}/releases/assets/{asset['id']}",
                method="DELETE", headers=headers_json)
            urllib.request.urlopen(del_req)
            print(f"Deleted old {fname} asset")
            break

    # Upload new asset
    size = Path(MASTER_PATH).stat().st_size
    upload_url = (f"https://uploads.github.com/repos/{repo}/"
                  f"releases/{release_id}/assets?name={fname}")
    with open(MASTER_PATH, "rb") as f:
        data = f.read()
    up_req = urllib.request.Request(upload_url, data=data, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "text/csv",
        "Content-Length": str(size)
    })
    urllib.request.urlopen(up_req)
    print(f"✅ Uploaded {fname} ({size//1024//1024} MB) to release")

# ── 4. Generate commodity JSONs ───────────────────────────────
def generate_jsons():
    print("\nGenerating JSONs...")
    df = pd.read_csv(MASTER_PATH, low_memory=False)
    df = df.dropna(subset=["Commodity","Region","Attribute","MarketYear",
                            "Value","WasdeNumber"])
    df["WasdeNumber"] = pd.to_numeric(df["WasdeNumber"], errors="coerce")
    df["Value"]       = pd.to_numeric(df["Value"],       errors="coerce")
    df = df.dropna(subset=["WasdeNumber","Value"])

    manifest = []
    for commodity in sorted(df["Commodity"].unique()):
        cdf  = df[df["Commodity"] == commodity]
        data = {}
        for (region, attribute, mkt_year), grp in cdf.groupby(
                ["Region","Attribute","MarketYear"]):
            grp = grp.sort_values("WasdeNumber").reset_index(drop=True)
            grp["releaseNum"] = range(1, len(grp)+1)
            key = f"{region}||{attribute}||{mkt_year}"
            data[key] = [
                {
                    "releaseNum":    int(row["releaseNum"]),
                    "wasdeNum":      int(row["WasdeNumber"]),
                    "reportDate":    str(row.get("ReportDate", "")),
                    "value":         round(float(row["Value"]), 4),
                    "forecastYear":  int(row["ForecastYear"])
                                     if pd.notna(row.get("ForecastYear")) else None,
                    "forecastMonth": int(row["ForecastMonth"])
                                     if pd.notna(row.get("ForecastMonth")) else None,
                    "unit":          str(row.get("Unit", ""))
                }
                for _, row in grp.iterrows()
            ]

        fname = commodity.replace("/","-").replace(" ","_") + ".json"
        out = {
            "commodity":   commodity,
            "regions":     sorted(cdf["Region"].unique().tolist()),
            "attributes":  sorted(cdf["Attribute"].unique().tolist()),
            "marketYears": sorted(cdf["MarketYear"].unique().tolist()),
            "data":        data,
            "lastUpdated": datetime.utcnow().strftime("%Y-%m-%d")
        }
        with open(DATA_DIR / fname, "w") as f:
            json.dump(out, f, separators=(",",":"))
        kb = (DATA_DIR / fname).stat().st_size // 1024
        print(f"  ✅ {fname} ({kb} KB)")
        manifest.append({"commodity": commodity, "file": fname,
                         "regions": out["regions"]})

    with open(DATA_DIR / "manifest.json", "w") as f:
        json.dump({"commodities": manifest,
                   "lastUpdated": datetime.utcnow().strftime("%Y-%m-%d")}, f)
    print(f"✅ {len(manifest)} JSONs written")

# ── Main ─────────────────────────────────────────────────────
mode = sys.argv[1] if len(sys.argv) > 1 else "full"

if mode == "json-only":
    generate_jsons()
elif mode == "full":
    download_from_release()
    new_data = fetch_and_append()
    upload_to_release()
    generate_jsons()
