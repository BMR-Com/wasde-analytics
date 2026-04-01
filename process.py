import os, json, io, sys
import pandas as pd
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta

DATA_DIR    = Path("data")
DATA_DIR.mkdir(exist_ok=True)
MASTER_PATH = os.environ.get("MASTER_CSV_PATH", "master_wasde.csv")

# All known conversion pairs (from → to): multiply value by factor
UNIT_CONVERSIONS = {
    ("thousand metric tons",   "million metric tons"):   0.001,
    ("million metric tons",    "thousand metric tons"):  1000,
    ("thousand bushels",       "million bushels"):       0.001,
    ("million bushels",        "thousand bushels"):      1000,
    ("thousand 480-lb bales",  "million 480-lb bales"):  0.001,
    ("million 480-lb bales",   "thousand 480-lb bales"): 1000,
    ("thousand short tons",    "million short tons"):    0.001,
    ("million short tons",     "thousand short tons"):   1000,
    ("thousand cwt",           "million cwt"):           0.001,
    ("million cwt",            "thousand cwt"):          1000,
    ("thousand hectares",      "million hectares"):      0.001,
    ("million hectares",       "thousand hectares"):     1000,
    ("thousand acres",         "million acres"):         0.001,
    ("million acres",          "thousand acres"):        1000,
    ("1,000 metric tons",      "1,000,000 metric tons"): 0.001,
    ("1,000,000 metric tons",  "1,000 metric tons"):     1000,
    ("1,000 bushels",          "1,000,000 bushels"):     0.001,
    ("1,000,000 bushels",      "1,000 bushels"):         1000,
}

def normalize_unit(val, from_unit, to_unit):
    fu = str(from_unit).strip().lower()
    tu = str(to_unit).strip().lower()
    if fu == tu or fu == "" or tu == "":
        return val
    factor = UNIT_CONVERSIONS.get((fu, tu))
    if factor is not None:
        return val * factor
    # Try swapped (safety)
    factor2 = UNIT_CONVERSIONS.get((tu, fu))
    if factor2 is not None:
        print(f"  WARN: unexpected direction {from_unit} → {to_unit}, using inverse")
        return val / factor2
    return None  # unknown — flag it

def download_from_release():
    import urllib.request
    repo  = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    tag   = "data-store"
    fname = "master_wasde.csv"

    api_url = "https://api.github.com/repos/" + repo + "/releases/tags/" + tag
    req = urllib.request.Request(api_url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json"
    })
    with urllib.request.urlopen(req) as r:
        release = json.loads(r.read())

    asset = next((a for a in release["assets"] if a["name"] == fname), None)
    if not asset:
        raise FileNotFoundError(fname + " not found in release assets")

    print("Downloading " + fname + " (" + str(asset["size"]//1024//1024) + " MB)...")
    dl_req = urllib.request.Request(asset["url"], headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/octet-stream"
    })
    with urllib.request.urlopen(dl_req) as r, open(MASTER_PATH, "wb") as f:
        f.write(r.read())
    print("Downloaded — " + str(Path(MASTER_PATH).stat().st_size//1024//1024) + " MB")

def fetch_and_append():
    from curl_cffi import requests as cf

    df_master  = pd.read_csv(MASTER_PATH, low_memory=False)
    latest_num = pd.to_numeric(df_master["WasdeNumber"], errors="coerce").max()
    print("Current latest WasdeNumber: " + str(int(latest_num)))

    check = datetime.today().replace(day=1)
    for _ in range(4):
        y = check.strftime("%Y")
        m = check.strftime("%m")
        url = ("https://www.usda.gov/sites/default/files/documents/"
               "oce-wasde-report-data-" + y + "-" + m + ".csv")
        print("Checking " + y + "-" + m + "...", end=" ")
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
                    df_new["Source_Report"] = y + "-" + m
                    combined = pd.concat([df_master, df_new], ignore_index=True)
                    combined = combined.drop_duplicates(subset=[
                        "WasdeNumber","Commodity","Region","MarketYear","Attribute"])
                    combined.to_csv(MASTER_PATH, index=False, encoding="utf-8-sig")
                    print("Appended WasdeNumber " + str(int(new_num)))
                    return True
                else:
                    print("Already up to date (" + str(int(new_num)) + ")")
                    return False
            else:
                print("HTTP " + str(r.status_code))
        except Exception as e:
            print("Error: " + str(e))
        check -= relativedelta(months=1)
    return False

def upload_to_release():
    import urllib.request
    repo  = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    tag   = "data-store"
    fname = "master_wasde.csv"

    headers_json = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json"
    }

    api_url = "https://api.github.com/repos/" + repo + "/releases/tags/" + tag
    req = urllib.request.Request(api_url, headers=headers_json)
    with urllib.request.urlopen(req) as r:
        release = json.loads(r.read())
    release_id = release["id"]

    for asset in release.get("assets", []):
        if asset["name"] == fname:
            del_req = urllib.request.Request(
                "https://api.github.com/repos/" + repo + "/releases/assets/" + str(asset["id"]),
                method="DELETE", headers=headers_json)
            urllib.request.urlopen(del_req)
            print("Deleted old " + fname)
            break

    size = Path(MASTER_PATH).stat().st_size
    upload_url = ("https://uploads.github.com/repos/" + repo +
                  "/releases/" + str(release_id) + "/assets?name=" + fname)
    print("Uploading updated CSV (" + str(size//1024//1024) + " MB)...")
    with open(MASTER_PATH, "rb") as f:
        data = f.read()
    up_req = urllib.request.Request(upload_url, data=data, headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "text/csv",
        "Content-Length": str(size)
    })
    urllib.request.urlopen(up_req)
    print("Uploaded " + fname + " to release")

def generate_jsons():
    print("\nGenerating JSONs...")
    df = pd.read_csv(MASTER_PATH, low_memory=False)
    df = df.dropna(subset=["Commodity","Region","Attribute","MarketYear","Value","WasdeNumber"])
    df["WasdeNumber"] = pd.to_numeric(df["WasdeNumber"], errors="coerce")
    df["Value"]       = pd.to_numeric(df["Value"],       errors="coerce")
    df["Unit"]        = df["Unit"].fillna("").astype(str).str.strip()
    df = df.dropna(subset=["WasdeNumber","Value"])

    manifest = []
    warn_count = 0

    for commodity in sorted(df["Commodity"].unique()):
        cdf = df[df["Commodity"] == commodity].copy()
        data = {}

        # ── Per (Region, Attribute): find canonical unit ──────
        # Use the unit from the MOST RECENT releases (highest WasdeNumber)
        # to avoid old-format units dominating
        unit_map = {}
        for (region, attribute), grp in cdf.groupby(["Region","Attribute"]):
            key_norm = (region, attribute.strip().lower())
            # Get unit from the most recent 20 releases
            recent = grp.nlargest(20, "WasdeNumber")
            unit_counts = recent["Unit"].value_counts()
            canonical   = unit_counts.idxmax() if len(unit_counts) else ""
            unit_map[key_norm] = canonical

        # ── Build normalized series ───────────────────────────
        for (region, attribute, mkt_year), grp in cdf.groupby(
                ["Region","Attribute","MarketYear"]):
            key_norm  = (region, attribute.strip().lower())
            canonical = unit_map.get(key_norm, "")
            grp = grp.sort_values("WasdeNumber").reset_index(drop=True)
            grp["releaseNum"] = range(1, len(grp)+1)

            rows = []
            for _, row in grp.iterrows():
                raw_val  = float(row["Value"])
                row_unit = str(row["Unit"]).strip()
                norm_val = normalize_unit(raw_val, row_unit, canonical)

                if norm_val is None:
                    # Unknown conversion — keep raw and log
                    norm_val  = raw_val
                    used_unit = row_unit
                    warn_count += 1
                    if warn_count <= 20:
                        print(f"  WARN unit: [{row_unit}] → [{canonical}] "
                              f"({commodity}/{region}/{attribute})")
                else:
                    used_unit = canonical

                rows.append({
                    "releaseNum":    int(row["releaseNum"]),
                    "wasdeNum":      int(row["WasdeNumber"]),
                    "reportDate":    str(row.get("ReportDate", "")),
                    "value":         round(norm_val, 4),
                    "forecastYear":  int(row["ForecastYear"])
                                     if pd.notna(row.get("ForecastYear")) else None,
                    "forecastMonth": int(row["ForecastMonth"])
                                     if pd.notna(row.get("ForecastMonth")) else None,
                    "unit":          used_unit
                })

            key = region + "||" + attribute + "||" + mkt_year
            data[key] = rows

        # Unit display map (region||attr → canonical unit)
        unit_display = {}
        for (region, attr), unit in unit_map.items():
            unit_display[region + "||" + attr] = unit

        fname = commodity.replace("/","-").replace(" ","_") + ".json"
        out = {
            "commodity":   commodity,
            "regions":     sorted(cdf["Region"].unique().tolist()),
            "attributes":  sorted(cdf["Attribute"].unique().tolist()),
            "marketYears": sorted(cdf["MarketYear"].unique().tolist()),
            "unitMap":     unit_display,
            "data":        data,
            "lastUpdated": datetime.utcnow().strftime("%Y-%m-%d")
        }
        with open(DATA_DIR / fname, "w") as f:
            json.dump(out, f, separators=(",",":"))
        kb = (DATA_DIR / fname).stat().st_size // 1024
        print("  " + fname + " (" + str(kb) + " KB)")
        manifest.append({"commodity": commodity, "file": fname,
                         "regions": out["regions"]})

    with open(DATA_DIR / "manifest.json", "w") as f:
        json.dump({"commodities": manifest,
                   "lastUpdated": datetime.utcnow().strftime("%Y-%m-%d")}, f)
    print(str(len(manifest)) + " JSONs written to /data/")
    if warn_count > 0:
        print("Total unknown unit conversions: " + str(warn_count))

mode = sys.argv[1] if len(sys.argv) > 1 else "full"

if mode == "json-from-release":
    download_from_release()
    generate_jsons()
elif mode == "full":
    download_from_release()
    fetch_and_append()
    upload_to_release()
    generate_jsons()
