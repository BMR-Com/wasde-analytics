import os, json, io, sys
import pandas as pd
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta

DATA_DIR    = Path("data")
DATA_DIR.mkdir(exist_ok=True)
MASTER_PATH = os.environ.get("MASTER_CSV_PATH", "master_wasde.csv")

GRAIN_KEYWORDS = ["wheat","corn","maize","soybean","oilseed","rice","barley",
                  "oats","sorghum","rye","coarse grain","grain"]

MT_TO_BU = {
    "wheat":        36.7437,
    "corn":         39.3683,
    "maize":        39.3683,
    "soybean":      36.7437,
    "oilseed":      36.7437,
    "rice":         45.9296,
    "barley":       45.9296,
    "oats":         68.8944,
    "sorghum":      39.3683,
    "rye":          39.3683,
    "coarse grain": 39.3683,
}

def is_grain(commodity):
    cn = commodity.lower()
    return any(k in cn for k in GRAIN_KEYWORDS)

def get_mt_to_bu(commodity):
    cn = commodity.lower()
    for key, factor in MT_TO_BU.items():
        if key in cn:
            return factor
    return 36.7437

def unit_family(u):
    u = u.strip().lower()
    if "bushel" in u:     return "bushel"
    if "metric ton" in u: return "mt"
    if "bale" in u:       return "bale"
    if "short ton" in u:  return "ton"
    if "cwt" in u:        return "cwt"
    if "hectare" in u:    return "hectare"
    if "acre" in u:       return "acre"
    if "pound" in u:      return "pound"
    if "head" in u:       return "head"
    return "other"

def unit_scale(u):
    u = u.strip().lower()
    if "million" in u:                return 1e6
    if "thousand" in u or "1,000" in u: return 1e3
    return 1.0

def convert_to_canonical(val, from_unit, canonical_unit, commodity):
    fu = from_unit.strip().lower()
    cu = canonical_unit.strip().lower()
    if fu == cu or fu == "" or cu == "":
        return val, True
    ff = unit_family(fu)
    cf = unit_family(cu)
    if ff == cf:
        fs = unit_scale(fu)
        ts = unit_scale(cu)
        if ts == 0: return val, False
        return val * (fs / ts), True
    if ff in ("mt","bushel") and cf in ("mt","bushel") and is_grain(commodity):
        mt_bu = get_mt_to_bu(commodity)
        fs = unit_scale(fu)
        ts = unit_scale(cu)
        if ts == 0: return val, False
        val_base = val * fs
        if ff == "mt":
            val_conv = val_base * mt_bu
        else:
            val_conv = val_base / mt_bu
        return val_conv / ts, True
    return val, False

def download_from_release():
    import urllib.request
    repo  = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GITHUB_TOKEN"]
    tag   = "data-store"
    fname = "master_wasde.csv"
    api_url = "https://api.github.com/repos/" + repo + "/releases/tags/" + tag
    req = urllib.request.Request(api_url, headers={
        "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req) as r:
        release = json.loads(r.read())
    asset = next((a for a in release["assets"] if a["name"] == fname), None)
    if not asset:
        raise FileNotFoundError(fname + " not found in release assets")
    print("Downloading " + fname + " (" + str(asset["size"]//1024//1024) + " MB)...")
    dl_req = urllib.request.Request(asset["url"], headers={
        "Authorization": "Bearer " + token, "Accept": "application/octet-stream"})
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
                df_new = pd.read_csv(io.StringIO(r.content.decode("utf-8-sig")), low_memory=False)
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

    for commodity in sorted(df["Commodity"].unique()):
        cdf   = df[df["Commodity"] == commodity].copy()
        grain = is_grain(commodity)

        all_mkt_years = sorted(cdf["MarketYear"].unique().tolist())
        latest_3      = all_mkt_years[-3:] if len(all_mkt_years) >= 3 else all_mkt_years
        if cdf[cdf["MarketYear"].isin(latest_3)]["WasdeNumber"].nunique() < 2:
            print("  SKIP " + commodity + " — insufficient recent data")
            continue

        top5_w  = sorted(cdf["WasdeNumber"].unique())[-5:]
        unit_map = {}

        for (region, attribute), grp in cdf.groupby(["Region","Attribute"]):
            key_norm   = (region, attribute.strip().lower())
            recent_grp = grp[grp["WasdeNumber"].isin(top5_w)]
            if len(recent_grp) == 0:
                recent_grp = grp
            units = recent_grp["Unit"].value_counts()
            dominant = units.idxmax() if len(units) else ""
            if grain and unit_family(dominant) in ("mt","bushel"):
                canonical = "Million Bushels"
            else:
                canonical = dominant
            unit_map[key_norm] = canonical

        data = {}
        fail_keys = set()

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
                conv_val, ok = convert_to_canonical(raw_val, row_unit, canonical, commodity)
                if not ok:
                    conv_val  = raw_val
                    used_unit = row_unit
                    fk = commodity+"/"+region+"/"+attribute+": ["+row_unit+"]→["+canonical+"]"
                    if fk not in fail_keys:
                        fail_keys.add(fk)
                        print("  WARN "+fk)
                else:
                    used_unit = canonical
                rows.append({
                    "releaseNum":    int(row["releaseNum"]),
                    "wasdeNum":      int(row["WasdeNumber"]),
                    "reportDate":    str(row.get("ReportDate","")),
                    "value":         round(conv_val, 4),
                    "forecastYear":  int(row["ForecastYear"]) if pd.notna(row.get("ForecastYear")) else None,
                    "forecastMonth": int(row["ForecastMonth"]) if pd.notna(row.get("ForecastMonth")) else None,
                    "unit":          used_unit,
                    "unitOk":        ok
                })
            key = region+"||"+attribute+"||"+mkt_year
            data[key] = rows

        unit_display = {}
        for (region, attr_norm), unit in unit_map.items():
            orig = cdf[cdf["Attribute"].str.strip().str.lower()==attr_norm]["Attribute"]
            orig_attr = orig.iloc[0] if len(orig) else attr_norm
            unit_display[region+"||"+orig_attr] = unit

        fname = commodity.replace("/","-").replace(" ","_")+".json"
        out = {
            "commodity":   commodity,
            "isGrain":     grain,
            "regions":     sorted(cdf["Region"].unique().tolist()),
            "attributes":  sorted(cdf["Attribute"].unique().tolist()),
            "marketYears": all_mkt_years,
            "unitMap":     unit_display,
            "data":        data,
            "lastUpdated": datetime.utcnow().strftime("%Y-%m-%d")
        }
        with open(DATA_DIR/fname,"w") as f:
            json.dump(out, f, separators=(",",":"))
        kb = (DATA_DIR/fname).stat().st_size//1024
        print("  "+fname+" ("+str(kb)+" KB)"+(" [GRAIN→Bu]" if grain else ""))
        manifest.append({"commodity":commodity,"file":fname,"regions":out["regions"]})

    with open(DATA_DIR/"manifest.json","w") as f:
        json.dump({"commodities":manifest,"lastUpdated":datetime.utcnow().strftime("%Y-%m-%d")},f)
    print(str(len(manifest))+" JSONs written to /data/")

mode = sys.argv[1] if len(sys.argv)>1 else "full"
if mode=="json-from-release":
    download_from_release()
    generate_jsons()
elif mode=="full":
    download_from_release()
    fetch_and_append()
    upload_to_release()
    generate_jsons()
