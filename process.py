import os, json, io, sys
import pandas as pd
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta

DATA_DIR    = Path("data")
DATA_DIR.mkdir(exist_ok=True)
MASTER_PATH = os.environ.get("MASTER_CSV_PATH", "master_wasde.csv")

# ── Complete unit conversion table ────────────────────────────
# Every pair must be listed in BOTH directions
CONV = {
    # Metric tons
    ("thousand metric tons",        "million metric tons"):         0.001,
    ("million metric tons",         "thousand metric tons"):        1000.0,
    ("1,000 metric tons",           "million metric tons"):         0.001,
    ("million metric tons",         "1,000 metric tons"):           1000.0,
    ("1,000 metric tons",           "thousand metric tons"):        1.0,
    ("thousand metric tons",        "1,000 metric tons"):           1.0,
    ("metric tons",                 "million metric tons"):         0.000001,
    ("million metric tons",         "metric tons"):                 1000000.0,
    ("metric tons",                 "thousand metric tons"):        0.001,
    ("thousand metric tons",        "metric tons"):                 1000.0,
    # Bushels
    ("thousand bushels",            "million bushels"):             0.001,
    ("million bushels",             "thousand bushels"):            1000.0,
    ("1,000 bushels",               "million bushels"):             0.001,
    ("million bushels",             "1,000 bushels"):               1000.0,
    ("1,000 bushels",               "thousand bushels"):            1.0,
    ("thousand bushels",            "1,000 bushels"):               1.0,
    ("bushels",                     "million bushels"):             0.000001,
    ("million bushels",             "bushels"):                     1000000.0,
    ("bushels",                     "thousand bushels"):            0.001,
    ("thousand bushels",            "bushels"):                     1000.0,
    # MT ↔ Bushels (grain conversions - wheat/corn/soy approx)
    # NOTE: We intentionally do NOT auto-convert between MT and bushels
    # because the conversion factor differs per commodity. Instead we
    # normalise within the same family only.
    # Bales
    ("thousand 480-lb bales",       "million 480-lb bales"):        0.001,
    ("million 480-lb bales",        "thousand 480-lb bales"):       1000.0,
    ("1,000 480-lb bales",          "million 480-lb bales"):        0.001,
    ("million 480-lb bales",        "1,000 480-lb bales"):          1000.0,
    ("1,000 480-lb bales",          "thousand 480-lb bales"):       1.0,
    ("thousand 480-lb bales",       "1,000 480-lb bales"):          1.0,
    # Short tons
    ("thousand short tons",         "million short tons"):          0.001,
    ("million short tons",          "thousand short tons"):         1000.0,
    # CWT
    ("thousand cwt",                "million cwt"):                 0.001,
    ("million cwt",                 "thousand cwt"):                1000.0,
    # Hectares
    ("thousand hectares",           "million hectares"):            0.001,
    ("million hectares",            "thousand hectares"):           1000.0,
    # Acres
    ("thousand acres",              "million acres"):               0.001,
    ("million acres",               "thousand acres"):              1000.0,
    # Pounds
    ("thousand pounds",             "million pounds"):              0.001,
    ("million pounds",              "thousand pounds"):             1000.0,
    # Head
    ("thousand head",               "million head"):                0.001,
    ("million head",                "thousand head"):               1000.0,
}

def same_unit_family(u1, u2):
    """Return True if units measure the same thing (weight vs weight, volume vs volume)."""
    # Detect unit family by keywords
    BUSHEL_KW   = ["bushel"]
    MT_KW       = ["metric ton"]
    BALE_KW     = ["bale"]
    TON_KW      = ["short ton"]
    HECTARE_KW  = ["hectare"]
    ACRE_KW     = ["acre"]
    POUND_KW    = ["pound"]
    HEAD_KW     = ["head"]
    CWT_KW      = ["cwt"]

    def family(u):
        u = u.lower()
        for kw in BUSHEL_KW:
            if kw in u: return "bushel"
        for kw in MT_KW:
            if kw in u: return "mt"
        for kw in BALE_KW:
            if kw in u: return "bale"
        for kw in TON_KW:
            if kw in u: return "ton"
        for kw in HECTARE_KW:
            if kw in u: return "hectare"
        for kw in ACRE_KW:
            if kw in u: return "acre"
        for kw in POUND_KW:
            if kw in u: return "pound"
        for kw in HEAD_KW:
            if kw in u: return "head"
        for kw in CWT_KW:
            if kw in u: return "cwt"
        return "other"

    return family(u1) == family(u2)

def convert_val(val, from_unit, to_unit):
    """
    Convert val from from_unit to to_unit.
    Returns (converted_value, success).
    success=False means incompatible families (e.g. bushels vs MT) — keep raw.
    """
    fu = str(from_unit).strip().lower()
    tu = str(to_unit).strip().lower()
    if fu == tu or fu == "" or tu == "":
        return val, True
    # Check same family first
    if not same_unit_family(fu, tu):
        # Different families (e.g. bushels vs metric tons) - cannot convert
        return val, False
    factor = CONV.get((fu, tu))
    if factor is not None:
        return val * factor, True
    # Try inverse
    factor_inv = CONV.get((tu, fu))
    if factor_inv is not None:
        return val / factor_inv, True
    # Same family but unknown scale — return raw
    return val, False

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

    # Latest WasdeNumber across all data
    latest_wasde = int(df["WasdeNumber"].max())
    # Latest 3 market years from most recent WASDE
    recent_df = df[df["WasdeNumber"] == latest_wasde]

    manifest  = []
    bad_conv  = {}  # track unit conversion failures

    for commodity in sorted(df["Commodity"].unique()):
        cdf = df[df["Commodity"] == commodity].copy()

        # ── Check if commodity has data in last 3 market years ──
        all_mkt_years = sorted(cdf["MarketYear"].unique().tolist())
        latest_3      = all_mkt_years[-3:] if len(all_mkt_years) >= 3 else all_mkt_years
        recent_cdf    = cdf[cdf["MarketYear"].isin(latest_3)]
        # Must have at least 2 WasdeNumbers in latest 3 years
        if recent_cdf["WasdeNumber"].nunique() < 2:
            print("  SKIP " + commodity + " — insufficient recent data")
            continue

        data = {}

        # ── Canonical unit = unit used in the MOST RECENT 5 WasdeNumbers ──
        # This ensures we use the current standard, not historical
        max_w   = cdf["WasdeNumber"].max()
        top5_w  = sorted(cdf["WasdeNumber"].unique())[-5:]
        unit_map = {}  # (region, attr_norm) → canonical_unit

        for (region, attribute), grp in cdf.groupby(["Region","Attribute"]):
            key_norm   = (region, attribute.strip().lower())
            recent_grp = grp[grp["WasdeNumber"].isin(top5_w)]
            if len(recent_grp) == 0:
                recent_grp = grp  # fallback to all
            unit_counts = recent_grp["Unit"].value_counts()
            canonical   = unit_counts.idxmax() if len(unit_counts) else ""
            unit_map[key_norm] = canonical

        # ── Build normalized series ───────────────────────────
        fail_count = 0
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
                conv_val, ok = convert_val(raw_val, row_unit, canonical)

                if not ok:
                    fail_count += 1
                    fail_key = commodity + "/" + region + "/" + attribute
                    if fail_key not in bad_conv:
                        bad_conv[fail_key] = set()
                    bad_conv[fail_key].add(row_unit + " → " + canonical)
                    # Use raw value but mark with original unit so frontend can flag
                    used_unit = row_unit
                    conv_val  = raw_val
                else:
                    used_unit = canonical

                rows.append({
                    "releaseNum":    int(row["releaseNum"]),
                    "wasdeNum":      int(row["WasdeNumber"]),
                    "reportDate":    str(row.get("ReportDate", "")),
                    "value":         round(conv_val, 4),
                    "forecastYear":  int(row["ForecastYear"])
                                     if pd.notna(row.get("ForecastYear")) else None,
                    "forecastMonth": int(row["ForecastMonth"])
                                     if pd.notna(row.get("ForecastMonth")) else None,
                    "unit":          used_unit,
                    "unitOk":        ok     # flag for frontend
                })

            key = region + "||" + attribute + "||" + mkt_year
            data[key] = rows

        # Unit display map (region||attr → canonical unit)
        unit_display = {}
        for (region, attr_norm), unit in unit_map.items():
            # Find original casing
            orig_attr = cdf[cdf["Attribute"].str.strip().str.lower() == attr_norm]["Attribute"].iloc[0] \
                        if len(cdf[cdf["Attribute"].str.strip().str.lower() == attr_norm]) else attr_norm
            unit_display[region + "||" + orig_attr] = unit

        fname = commodity.replace("/","-").replace(" ","_") + ".json"
        out = {
            "commodity":   commodity,
            "regions":     sorted(cdf["Region"].unique().tolist()),
            "attributes":  sorted(cdf["Attribute"].unique().tolist()),
            "marketYears": all_mkt_years,
            "unitMap":     unit_display,
            "data":        data,
            "lastUpdated": datetime.utcnow().strftime("%Y-%m-%d")
        }
        with open(DATA_DIR / fname, "w") as f:
            json.dump(out, f, separators=(",",":"))
        kb = (DATA_DIR / fname).stat().st_size // 1024
        flag = " *** " + str(fail_count) + " unit errors" if fail_count else ""
        print("  " + fname + " (" + str(kb) + " KB)" + flag)
        manifest.append({
            "commodity": commodity,
            "file":      fname,
            "regions":   sorted(cdf["Region"].unique().tolist())
        })

    # Print all conversion failures for debugging
    if bad_conv:
        print("\n=== UNIT CONVERSION FAILURES (incompatible families) ===")
        for k, vs in bad_conv.items():
            print("  " + k + ": " + str(vs))
        print("These indicate the same attribute uses different unit families")
        print("(e.g. bushels vs metric tons) — values kept as-is with original unit")

    with open(DATA_DIR / "manifest.json", "w") as f:
        json.dump({"commodities": manifest,
                   "lastUpdated": datetime.utcnow().strftime("%Y-%m-%d")}, f)
    print("\n" + str(len(manifest)) + " JSONs written to /data/")

mode = sys.argv[1] if len(sys.argv) > 1 else "full"

if mode == "json-from-release":
    download_from_release()
    generate_jsons()
elif mode == "full":
    download_from_release()
    fetch_and_append()
    upload_to_release()
    generate_jsons()
