#!/usr/bin/env python3
"""
brief.py — BMR-Com WASDE brief.

For each of the latest WASDE releases, writes data/brief/<YYYY-MM>.json (+ index.json):
  • key changes vs the previous report for the world and major countries
  • how this month's revisions compare with the same month in past years
  • cotton: cross-check against crop conditions, Texas drought, US export sales,
    Brazil exports, on-call and COT positioning, and a written outlook
  • other commodities: a short summary of the main US / world changes

Inputs: data/*.json (this repo) plus public BMR-Com datasets fetched from GitHub
(crop progress, drought monitor, export sales, Brazil trade, on-call, COT, prices).
Set BRIEF_LOCAL=<dir with clones> to read local copies instead.
"""
import io, json, os, glob
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = DATA / "brief"
N_RELEASES = 24
RAW = "https://raw.githubusercontent.com/BMR-Com"
LOCAL = os.getenv("BRIEF_LOCAL")
KG_PER_BALE = 217.724
BALES_PER_CONTRACT = 50000 / 480.0

COTTON_REGIONS = ["World", "World Less China", "United States", "China", "India", "Brazil", "Australia",
                  "Pakistan", "Bangladesh", "Vietnam", "Turkey", "Central Asia", "Afr. Fr. Zone"]
ATTRS = ["Production", "Domestic Use", "Exports", "Imports", "Ending Stocks"]
ALIAS = {"Beginning stocks": "Beginning Stocks", "Domestic use": "Domestic Use", "Ending stocks": "Ending Stocks",
         "Output": "Production", "Exports, Total": "Exports", "Exports, total": "Exports",
         "Yield per harvested acre": "Yield per Harvested Acre", "Use, total": "Total Use", "Use, Total": "Total Use",
         "Total foreign": "Total Foreign", "Domestic, Total": "Domestic Use", "Domestic Total": "Domestic Use",
         "Total  Domestic": "Domestic Use", "Domestic Disappearance": "Domestic Use", "Major exporters": "Major Exporters", "Major importers": "Major Importers"}
OTHERS = {"Corn": "Corn.json", "Wheat": "Wheat.json", "Soybeans": "Oilseed,_Soybean.json", "Soybean Meal": "Meal,_Soybean.json",
          "Soybean Oil": "Oil,_Soybean.json", "Rice": "Rice.json", "Sugar": "Sugar.json"}


# ─────────────────────────── loaders ───────────────────────────
def remote(path_in_org, local_rel):
    if LOCAL:
        return (Path(LOCAL) / local_rel).read_bytes()
    import requests
    r = requests.get(f"{RAW}/{path_in_org}", timeout=180); r.raise_for_status(); return r.content


def load_wasde(fname):
    d = json.load(open(DATA / fname))
    rows = []
    for key, vals in d["data"].items():
        reg, attr, my = key.split("||")
        attr = ALIAS.get(attr, attr); reg = ALIAS.get(reg, reg)
        for v in vals:
            if v.get("value") is None:
                continue
            rows.append((reg, attr, my, pd.Timestamp(year=v["forecastYear"], month=v["forecastMonth"], day=1), float(v["value"]), v.get("unit", "")))
    df = pd.DataFrame(rows, columns=["reg", "attr", "my", "rd", "val", "unit"])
    return df.drop_duplicates(["reg", "attr", "my", "rd"], keep="last")


def crop_conditions():
    files = ["cotton_2001_2005", "cotton_2006_2010", "cotton_2011_2015", "cotton_2016_2020", "cotton_2021_2025", "cotton_2026_2030"]
    parts = []
    for f in files:
        try:
            raw = remote(f"cotton-crop-progress/main/data/{f}.csv", f"bmr-com/cotton-crop-progress/data/{f}.csv")
        except Exception as e:
            print("crop progress missing", f, e); continue
        d = pd.read_csv(io.BytesIO(raw), low_memory=False, usecols=["state_alpha", "statisticcat_desc", "unit_desc", "week_ending", "Value"])
        parts.append(d[(d.state_alpha == "US") & (d.statisticcat_desc.isin(["CONDITION", "PROGRESS"]))])
    c = pd.concat(parts)
    c["Value"] = pd.to_numeric(c.Value, errors="coerce"); c["we"] = pd.to_datetime(c.week_ending)
    p = c.pivot_table(index="we", columns="unit_desc", values="Value", aggfunc="first").sort_index()
    p["GE"] = p.get("PCT EXCELLENT") + p.get("PCT GOOD"); p["PVP"] = p.get("PCT POOR") + p.get("PCT VERY POOR")
    return p


def texas_drought():
    raw = remote("drought-monitor/main/data/state/TX.csv", "bmr-com/drought-monitor/data/state/TX.csv")
    d = pd.read_csv(io.BytesIO(raw), parse_dates=["Week"]).set_index("Week").sort_index()
    return d["D2-D4"]


def export_sales():
    raw = remote("usd-export-sales-email/main/cotton_history_1404.csv", "bmr-com/usd-export-sales-email/cotton_history_1404.csv")
    e = pd.read_csv(io.BytesIO(raw), parse_dates=["weekEndingDate"], low_memory=False)
    for c in ["accumulatedExports", "outstandingSales", "nextMYOutstandingSales", "weeklyExports", "currentMYNetSales"]:
        e[c] = pd.to_numeric(e[c], errors="coerce").fillna(0)
    g = e.groupby(["weekEndingDate", "marketYear"])[["accumulatedExports", "outstandingSales", "nextMYOutstandingSales", "currentMYNetSales", "weeklyExports"]].sum().reset_index()
    return g


def brazil_exports():
    raw = remote("Brazil--trade/main/data/exports_2015on.csv", "bmr-com/Brazil--trade/data/exports_2015on.csv")
    d = pd.read_csv(io.BytesIO(raw), usecols=["year", "month", "commodity", "kg_net"])
    c = d[d.commodity == "cotton"].groupby(["year", "month"]).kg_net.sum() / KG_PER_BALE / 1e6
    return c  # million 480-lb bales per month


def cot_cotton():
    s = json.loads(remote("cftc-cot-full/main/data/web/series/CT.json", "cftc-cot-full/data/web/series/CT.json"))
    a = s["ct"]["all"]; o = s["ct"].get("old") or a; idx = pd.to_datetime(s["dates"])
    f = lambda x: pd.to_numeric(pd.Series(x, index=idx), errors="coerce")
    df = pd.DataFrame({"mm_net": f(a["managed_money"]["l"]) - f(a["managed_money"]["s"]),
                       "pmu_l_old": f(o["prod_merc"]["l"]), "pmu_s_old": f(o["prod_merc"]["s"])})
    lo, hi = df.mm_net.rolling(156, min_periods=52).min(), df.mm_net.rolling(156, min_periods=52).max()
    df["mm_idx"] = (df.mm_net - lo) / (hi - lo) * 100
    df["ls_old"] = df.pmu_l_old / df.pmu_s_old
    return df


def oncall():
    raw = remote("cotton-on-call/main/data/cotton_oncall.csv", "cotton-on-call/data/cotton_oncall.csv")
    d = pd.read_csv(io.BytesIO(raw)); d["date"] = pd.to_datetime(d["Report Date"])
    d = d[(d["Futures Based On"].astype(str).str.strip() != "Totals") & ~d["Futures Based On"].astype(str).str.contains("October") & (d["Old/New"] == "old")]
    g = d.groupby("date")[["Unfixed Call Sales", "Unfixed Call Purchases"]].sum()
    g.columns = ["S_old", "P_old"]
    return g.mask(g <= 0)


def prices():
    raw = remote("cftc-cot-full/main/data/prices/daily.csv", "cftc-cot-full/data/prices/daily.csv")
    p = pd.read_csv(io.BytesIO(raw), parse_dates=["date"])
    return p[p.ticker == "CT"].set_index("date")["close"].dropna()


# ─────────────────────────── helpers ───────────────────────────
def get(df, reg, attr, my, rd):
    x = df[(df.reg == reg) & (df.attr == attr) & (df.my == my) & (df.rd == rd)]
    return float(x.val.iloc[0]) if len(x) else None


def focus_my(df, rd):
    mys = sorted(df[df.rd == rd].my.unique())
    return mys[-1] if mys else None


def su(df, reg, my, rd, world_like):
    es = get(df, reg, "Ending Stocks", my, rd); du = get(df, reg, "Domestic Use", my, rd); ex = get(df, reg, "Exports", my, rd)
    tu = get(df, reg, "Total Use", my, rd)
    if es is None or (du is None and tu is None):
        return None
    use = tu if tu else (du if world_like else du + (ex or 0))
    return es / use if use else None


def changes_table(df, rd, prev, my, regions):
    rows = []
    for reg in regions:
        u = df[(df.reg == reg) & (df.attr == "Production") & (df.my == my) & (df.rd == rd)].unit
        r = {"region": reg, "unit": u.iloc[0] if len(u) else ""}
        any_ = False
        for a in ATTRS:
            now = get(df, reg, a, my, rd); was = get(df, reg, a, my, prev) if prev is not None else None
            r[a] = {"now": now, "prev": was, "chg": (round(now - was, 3) if now is not None and was is not None else None)}
            any_ = any_ or now is not None
        wl = reg in ("World", "World Less China")
        s_now = su(df, reg, my, rd, wl); s_prev = su(df, reg, my, prev, wl) if prev is not None else None
        r["S/U"] = {"now": s_now, "prev": s_prev, "chg": (s_now - s_prev if s_now is not None and s_prev is not None else None)}
        if any_:
            rows.append(r)
    return rows


def month_history(df, reg, attr, rd):
    """Change in this month's report (focus MY) vs the same calendar month in prior years."""
    rels = sorted(df.rd.unique()); hist = []
    for t in rels:
        if t.month != rd.month or t >= rd:
            continue
        i = rels.index(t)
        if i == 0:
            continue
        my = focus_my(df, t); a, b = get(df, reg, attr, my, t), get(df, reg, attr, my, rels[i - 1])
        if a is not None and b is not None:
            hist.append((t.year, a - b))
    i = rels.index(rd); my = focus_my(df, rd)
    a, b = get(df, reg, attr, my, rd), (get(df, reg, attr, my, rels[i - 1]) if i > 0 else None)
    if a is None or b is None or len(hist) < 4:
        return None
    ch = a - b; h = np.array([x[1] for x in hist])
    M = rd.strftime('%B'); n = len(h); pct = float((np.abs(h) < abs(ch)).mean() * 100)
    if ch == 0:
        k_ = int((h == 0).sum())
        note = f"unchanged ({k_} of {n} past {M} reports also left it unchanged)" if k_ else f"unchanged, unusually — every past {M} report since {hist[0][0]} revised it"
    elif pct < 40:
        note = f"small by {M} standards"
    else:
        same = [y for y, v in hist if (v >= ch if ch > 0 else v <= ch)]
        word = "increase" if ch > 0 else "cut"
        if not same:
            note = f"largest {M} {word} in {n + 1} years"
        elif pct >= 60 and max(same) < rd.year - 2:
            note = f"largest {M} {word} since {max(same)}"
        else:
            note = f"{len(same)} of {n} past {M} reports {'raised' if ch > 0 else 'cut'} it by as much"
    return {"region": reg, "attr": attr, "chg": round(ch, 3), "now": a, "avg_abs": round(float(np.mean(np.abs(h))), 3),
            "up_share": round(float((h > 0).mean()), 2), "pct_abs": round(pct, 0),
            "n": len(h), "since": min(x[0] for x in hist), "note": note}


def fmt(v, nd=2, sign=False):
    if v is None:
        return "–"
    return (f"{v:+.{nd}f}" if sign else f"{v:.{nd}f}")


# ─────────────────────────── cotton deep dive ───────────────────────────
def cotton_checks(df, rd, prev, my, ctx):
    y0 = int(my[:4]); out = {}; cut = rd + pd.Timedelta(days=9)          # WASDE ≈ 9th–12th
    pcut = prev + pd.Timedelta(days=9) if prev is not None else None
    us_prod = get(df, "United States", "Production", my, rd); planted = get(df, "United States", "Planted", my, rd)
    prod_prev = get(df, "United States", "Production", my, prev) if prev is not None else None

    # crop conditions + condition-implied production (Aug–Dec reports)
    cond = ctx.get("cond")
    if cond is not None and rd.month in (7, 8, 9, 10, 11, 12) and planted:
        s = cond[(cond.index.year == y0) & (cond.index <= cut)].dropna(subset=["GE"])
        if len(s):
            ge, pvp = float(s.GE.iloc[-1]), float(s.PVP.iloc[-1])
            sp = cond[(cond.index.year == y0) & (cond.index <= pcut)].dropna(subset=["GE"]) if pcut is not None else pd.DataFrame()
            ly = cond[(cond.index.year == y0 - 1) & (cond.index <= cut - pd.DateOffset(years=1))].dropna(subset=["GE"])
            out["conditions"] = {"week": s.index[-1].strftime("%Y-%m-%d"), "GE": ge, "PVP": pvp,
                                 "GE_prev_report": float(sp.GE.iloc[-1]) if len(sp) else None,
                                 "GE_last_year": float(ly.GE.iloc[-1]) if len(ly) else None,
                                 "harvested_pct": float(s["PCT HARVESTED"].dropna().iloc[-1]) if "PCT HARVESTED" in s and s["PCT HARVESTED"].notna().any() else None}
            # implied production per planted acre from late-season conditions (fit on prior seasons only)
            def late(yr, upto=None):
                z = cond[(cond.index.year == yr)]
                if upto is not None:
                    z = z[z.index <= upto]
                z = z[(z.index.month >= 9) | ((z.index.month == 8) & (z.index.day > 15))].dropna(subset=["GE"])
                return (z.GE.mean(), z.PVP.mean()) if len(z) else (None, None)
            X, Y = [], []
            for yr in range(2007, y0):
                myr = f"{yr}/{str(yr + 1)[-2:]}"
                fin = df[(df.reg == "United States") & (df.my == myr)]
                pr = fin[fin.attr == "Production"].sort_values("rd").val; pl = fin[fin.attr == "Planted"].sort_values("rd").val
                g_, p_ = late(yr)
                if len(pr) and len(pl) and g_ is not None:
                    X.append([1, g_, p_]); Y.append(pr.iloc[-1] * 480 / pl.iloc[-1])
            g_now, p_now = late(y0, cut)
            if len(X) >= 8 and g_now is not None and rd.month >= 9:
                X, Y = np.array(X), np.array(Y); beta = np.linalg.lstsq(X, Y, rcond=None)[0]
                sd = float(np.std(Y - X @ beta)); lbpa = float(beta @ [1, g_now, p_now])
                impl = lbpa * planted / 480
                out["implied"] = {"prod": round(impl, 2), "band": round(sd * planted / 480, 2), "usda": us_prod,
                                  "gap": round(us_prod - impl, 2), "lb_planted_usda": round(us_prod * 480 / planted), "lb_planted_impl": round(lbpa)}

    dr = ctx.get("drought")
    if dr is not None and rd.month in (5, 6, 7, 8, 9, 10):
        s = dr[dr.index <= cut]
        if len(s):
            out["tx_drought"] = {"week": s.index[-1].strftime("%Y-%m-%d"), "D2_D4": float(s.iloc[-1]),
                                 "prev_report": float(dr[dr.index <= pcut].iloc[-1]) if pcut is not None else None,
                                 "last_year": float(dr[dr.index <= cut - pd.DateOffset(years=1)].iloc[-1])}

    # US export sales pace vs USDA
    es = ctx.get("esr"); usda_exp = get(df, "United States", "Exports", my, rd)
    if es is not None and usda_exp:
        mkt = y0 + 1
        cur = es[(es.marketYear == mkt) & (es.weekEndingDate <= cut)]
        if len(cur):
            w = cur.weekEndingDate.max(); r = cur[cur.weekEndingDate == w].iloc[0]
            commit = (r.accumulatedExports + r.outstandingSales) / 1e6; ship = r.accumulatedExports / 1e6
            wk = (w - pd.Timestamp(year=y0, month=8, day=1)).days // 7
            hist = []
            for yy in range(y0 - 5, y0):
                h = es[(es.marketYear == yy + 1)]
                if h.empty:
                    continue
                target = pd.Timestamp(year=yy, month=8, day=1) + pd.Timedelta(weeks=wk)
                hh = h.iloc[(h.weekEndingDate - target).abs().argsort()[:1]]
                fin = df[(df.reg == "United States") & (df.attr == "Exports") & (df.my == f"{yy}/{str(yy + 1)[-2:]}")].sort_values("rd").val
                if len(hh) and len(fin):
                    hist.append((hh.accumulatedExports.iloc[0] + hh.outstandingSales.iloc[0]) / 1e6 / fin.iloc[-1])
            out["export_sales"] = {"week": w.strftime("%Y-%m-%d"), "commit_mrb": round(commit, 2), "ship_mrb": round(ship, 2),
                                   "pace": round(commit / usda_exp, 3), "pace_5y": round(float(np.mean(hist)), 3) if hist else None,
                                   "usda": usda_exp, "usda_prev": get(df, "United States", "Exports", my, prev) if prev is not None else None}

    # Brazil exports (SECEX, Aug–Jul MY) vs USDA
    br = ctx.get("brazil"); usda_br = get(df, "Brazil", "Exports", my, rd)
    if br is not None and usda_br:
        def mytd(yy, upto):
            tot, n = 0.0, 0
            for (yr, mo), v in br.items():
                t = pd.Timestamp(year=yr, month=mo, day=1)
                if pd.Timestamp(year=yy, month=8, day=1) <= t <= upto:
                    tot += v; n += 1
            return tot, n
        last_m = pd.Timestamp(year=int(br.index[-1][0]), month=int(br.index[-1][1]), day=1)
        upto = min(last_m, (cut - pd.offsets.MonthBegin(1)).normalize())
        # Brazil's crop sells mostly in the later months; compare with the same months of past seasons
        tot, n = mytd(y0, upto)
        if n:
            share = []
            for yy in range(max(2015, y0 - 5), y0):
                a, _ = mytd(yy, upto - pd.DateOffset(years=y0 - yy)); full, _ = mytd(yy, pd.Timestamp(year=yy + 1, month=7, day=1))
                if full:
                    share.append(a / full)
            ly, _ = mytd(y0 - 1, upto - pd.DateOffset(years=1))
            out["brazil"] = {"through": upto.strftime("%b %Y"), "months": n, "mytd": round(tot, 2), "mytd_ly": round(ly, 2),
                             "usda": usda_br, "usda_prev": get(df, "Brazil", "Exports", my, prev) if prev is not None else None,
                             "pace": round(tot / usda_br, 3), "pace_norm": round(float(np.mean(share)), 3) if share else None}

    # positioning at report time
    cot = ctx.get("cot")
    if cot is not None:
        c = cot[cot.index <= cut].dropna(subset=["mm_net"])
        if len(c):
            r = c.iloc[-1]; ls3 = cot.ls_old[(cot.index <= cut)].dropna().iloc[-156:]
            out["cot"] = {"date": c.index[-1].strftime("%Y-%m-%d"), "mm_net": float(r.mm_net), "mm_idx": float(r.mm_idx) if pd.notna(r.mm_idx) else None,
                          "ls_old": float(r.ls_old) if pd.notna(r.ls_old) else None,
                          "ls_pct": float((ls3 < r.ls_old).mean() * 100) if len(ls3) > 50 and pd.notna(r.ls_old) else None}
    oc = ctx.get("oncall")
    if oc is not None:
        o = oc[oc.index <= cut].dropna()
        if len(o):
            w_trade = get(df, "World", "Exports", my, rd)
            out["oncall"] = {"date": o.index[-1].strftime("%Y-%m-%d"), "S_old": float(o.S_old.iloc[-1]), "P_old": float(o.P_old.iloc[-1]),
                             "S_pct_trade": float(o.S_old.iloc[-1] * BALES_PER_CONTRACT / 1e6 / w_trade) if w_trade else None}
    px = ctx.get("px")
    if px is not None:
        s = px[px.index <= cut]
        if len(s) > 22:
            out["price"] = {"date": s.index[-1].strftime("%Y-%m-%d"), "close": float(s.iloc[-1]), "chg_1m": float(s.iloc[-1] / s.iloc[-22] - 1)}
    return out


def cotton_outlook(df, rd, prev, my, ch, hist, chk):
    """Factor-by-factor read and an overall tilt. Plain rules, stated in the text."""
    F = []
    def add(name, tilt, text):
        F.append({"factor": name, "tilt": tilt, "text": text})
    us = next((r for r in ch if r["region"] == "United States"), None); wl = next((r for r in ch if r["region"] == "World"), None)
    wxc = next((r for r in ch if r["region"] == "World Less China"), None)
    if us and us["Ending Stocks"]["chg"] is not None:
        c = us["Ending Stocks"]["chg"]
        add("US balance sheet", "bearish" if c > 0.05 else "bullish" if c < -0.05 else "neutral",
            f"US ending stocks {fmt(us['Ending Stocks']['now'])}m ({fmt(c, 2, True)}m), stocks/use {fmt((us['S/U']['now'] or 0) * 100, 1)}%.")
    if wxc and wxc["Ending Stocks"]["chg"] is not None:
        c = wxc["Ending Stocks"]["chg"]
        add("World ex-China stocks", "bearish" if c > 0.3 else "bullish" if c < -0.3 else "neutral",
            f"World ex-China ending stocks {fmt(wxc['Ending Stocks']['now'])}m ({fmt(c, 2, True)}m); ex-China stocks/use {fmt((wxc['S/U']['now'] or 0) * 100, 1)}%.")
    im = chk.get("implied")
    if im:
        g = im["gap"]; tilt = "bullish" if g > 0.5 * im["band"] else "bearish" if g < -0.5 * im["band"] else "neutral"
        add("US crop vs conditions", tilt,
            f"Late-season crop ratings point to about {fmt(im['prod'])}m bales (±{fmt(im['band'], 1)}m) vs USDA {fmt(im['usda'])}m — "
            + ("USDA looks generous; downside risk to its crop." if tilt == "bullish" else "USDA looks conservative; upside risk to its crop." if tilt == "bearish" else "USDA is within the normal range implied by conditions."))
    tx = chk.get("tx_drought")
    if tx and tx.get("prev_report") is not None and rd.month in (6, 7, 8, 9, 10):
        d = tx["D2_D4"] - tx["prev_report"]
        if abs(d) >= 8:
            add("Texas drought", "bullish" if d > 0 else "bearish", f"Texas D2–D4 drought {tx['D2_D4']:.0f}% of area ({d:+.0f} pts since the last report).")
    ex = chk.get("export_sales")
    if ex and ex.get("pace_5y"):
        d = ex["pace"] - ex["pace_5y"]
        add("US export sales", "bullish" if d > 0.05 else "bearish" if d < -0.05 else "neutral",
            f"US commitments {fmt(ex['commit_mrb'])}m running bales = {ex['pace']*100:.0f}% of USDA's {fmt(ex['usda'], 1)}m target vs a 5-yr norm of "
            f"{ex['pace_5y']*100:.0f}% at this point — " + ("ahead of pace, supports the target or a raise." if d > 0.05 else "behind pace, risk of a cut." if d < -0.05 else "on pace."))
    b = chk.get("brazil")
    if b and b.get("pace_norm"):
        d = b["pace"] - b["pace_norm"]
        add("Brazil exports", "bearish" if d > 0.04 else "bullish" if d < -0.04 else "neutral",
            f"Brazil shipped {fmt(b['mytd'])}m bales Aug–{b['through']} ({b['pace']*100:.0f}% of USDA's {fmt(b['usda'], 1)}m vs a norm of "
            f"{b['pace_norm']*100:.0f}%; last year {fmt(b['mytd_ly'])}m) — " + ("running strong, more competition for US cotton." if d > 0.04 else "running slow, less competition for US cotton." if d < -0.04 else "on pace."))
    cot = chk.get("cot"); oc = chk.get("oncall")
    if cot and cot.get("mm_idx") is not None:
        i_ = cot["mm_idx"]
        add("Speculators", "bearish" if i_ > 80 else "bullish" if i_ < 20 else "neutral",
            f"Managed money net {cot['mm_net']/1000:+.1f}k (3-yr COT index {i_:.0f}) — " + ("crowded long, liquidation risk." if i_ > 80 else "short and crowded, covering fuel." if i_ < 20 else "not at an extreme."))
    if oc and cot and cot.get("ls_pct") is not None:
        n_old = oc["S_old"] - oc["P_old"]; lp = cot["ls_pct"]
        tilt = "bullish" if n_old > 0 and lp < 30 else "bearish" if lp > 70 else "neutral"
        add("Mill fixation", tilt, f"Net old-crop on-call {n_old/1000:+.1f}k contracts; commercials' old-crop long/short ratio at the {lp:.0f}th pct of 3 yrs — "
            + ("mills light on futures cover, fixing should add buying." if tilt == "bullish" else "commercials already long, fixing can pass by EFP." if tilt == "bearish" else "cover in its normal range."))
    score = sum(1 if f["tilt"] == "bullish" else -1 if f["tilt"] == "bearish" else 0 for f in F)
    label = "bullish" if score >= 2 else "modestly bullish" if score == 1 else "bearish" if score <= -2 else "modestly bearish" if score == -1 else "neutral"
    return F, score, label


def cotton_text(df, rd, prev, my, ch, hist, chk, F, label):
    T = []
    us = next((r for r in ch if r["region"] == "United States"), {}); wl = next((r for r in ch if r["region"] == "World"), {})
    wxc = next((r for r in ch if r["region"] == "World Less China"), {})
    g = lambda r, a, k_: (r.get(a) or {}).get(k_)
    head = (f"The {rd.strftime('%B %Y')} WASDE puts {my} US production at {fmt(g(us,'Production','now'))}m bales ({fmt(g(us,'Production','chg'),2,True)}m), "
            f"exports {fmt(g(us,'Exports','now'))}m ({fmt(g(us,'Exports','chg'),2,True)}m) and ending stocks {fmt(g(us,'Ending Stocks','now'))}m "
            f"({fmt(g(us,'Ending Stocks','chg'),2,True)}m). World ending stocks {fmt(g(wl,'Ending Stocks','now'))}m ({fmt(g(wl,'Ending Stocks','chg'),2,True)}m), "
            f"world ex-China {fmt(g(wxc,'Ending Stocks','now'))}m ({fmt(g(wxc,'Ending Stocks','chg'),2,True)}m).")
    T.append({"h": "Headline", "t": head})
    movers = sorted([r for r in ch if r["region"] not in ("World", "World Less China")], key=lambda r: -max(abs((r[a] or {}).get("chg") or 0) for a in ATTRS))[:4]
    mv = []
    for r in movers:
        parts = [f"{a.lower()} {fmt(r[a]['chg'],2,True)}" for a in ATTRS if r[a]["chg"] not in (None, 0)]
        if parts:
            mv.append(f"{r['region']} ({', '.join(parts)})")
    if mv:
        T.append({"h": "Biggest country changes", "t": "; ".join(mv) + " (million bales)."})
    hs = [h for h in hist if h and h["chg"] != 0]
    if hs:
        T.append({"h": f"vs past {rd.strftime('%B')} reports", "t": " ".join(
            f"{h['region']} {h['attr'].lower()} {fmt(h['chg'],2,True)}m — {h['note']} (avg {rd.strftime('%B')} move ±{h['avg_abs']:.2f}m since {h['since']})." for h in hs[:5])})
    c = chk.get("conditions"); im = chk.get("implied"); tx = chk.get("tx_drought"); pc = g(us, "Production", "chg")
    if c:
        t = (f"US crop rated {c['GE']:.0f}% good/excellent and {c['PVP']:.0f}% poor/very poor (week of {c['week']})"
             + (f", vs {c['GE_prev_report']:.0f}% G/E at the last report" if c.get("GE_prev_report") is not None else "")
             + (f" and {c['GE_last_year']:.0f}% a year ago" if c.get("GE_last_year") is not None else "") + ".")
        if c.get("harvested_pct") is not None:
            t += f" Harvest {c['harvested_pct']:.0f}% done."
        pc = g(us, "Production", "chg")
        if c.get("GE_prev_report") is not None and pc is not None:
            dge = c["GE"] - c["GE_prev_report"]
            if (dge <= -1 and pc > 0.05) or (dge >= 1 and pc < -0.05):
                t += f" **USDA moved production {'up' if pc > 0 else 'down'} {abs(pc):.2f}m even though ratings {'fell' if dge < 0 else 'rose'} {abs(dge):.0f} pt{'s' if abs(dge)>=1.5 else ''} since the last report — we disagree with the direction.**"
            elif (dge >= 1 and pc > 0.05) or (dge <= -1 and pc < -0.05):
                t += f" USDA's {'increase' if pc > 0 else 'cut'} is in line with ratings {'improving' if dge > 0 else 'slipping'} {abs(dge):.0f} pts."
            elif abs(pc) > 0.05:
                t += f" USDA {'raised' if pc > 0 else 'cut'} production with ratings broadly unchanged, so the revision comes from acreage, abandonment or survey yield rather than conditions."
        if im:
            t += (f" Late-season ratings imply about {fmt(im['prod'])}m bales (±{fmt(im['band'],1)}m; {im['lb_planted_impl']} lb per planted acre vs USDA's "
                  f"{im['lb_planted_usda']}) — USDA is {fmt(abs(im['gap']),2)}m {'above' if im['gap'] > 0 else 'below'} that.")
        if tx:
            t += f" Texas area in D2–D4 drought: {tx['D2_D4']:.0f}% (last report {fmt(tx['prev_report'],0)}%, a year ago {tx['last_year']:.0f}%)."
            if tx.get("prev_report") is not None and tx["D2_D4"] - tx["prev_report"] >= 8 and (pc or 0) >= 0:
                t += " **Drought in Texas has spread sharply since the last report while USDA did not cut — risk of higher abandonment and a smaller crop in later reports.**"
        T.append({"h": "Crop vs conditions", "t": t})
    for f in F:
        if f["factor"] in ("US export sales", "Brazil exports"):
            T.append({"h": f["factor"], "t": f["text"]})
    pos = [f["text"] for f in F if f["factor"] in ("Speculators", "Mill fixation")]
    if pos:
        T.append({"h": "Positioning", "t": " ".join(pos)})
    bull = [f["factor"] for f in F if f["tilt"] == "bullish"]; bear = [f["factor"] for f in F if f["tilt"] == "bearish"]
    pxs = chk.get("price")
    T.append({"h": "Price outlook", "t":
              f"**{label.capitalize()}.** " + (f"Supportive: {', '.join(bull)}. " if bull else "") + (f"Weighing: {', '.join(bear)}. " if bear else "")
              + (f"ICE front month {pxs['close']:.2f}¢ ({pxs['chg_1m']*100:+.1f}% over the past month). " if pxs else "")
              + "Watch the next crop progress and export sales releases to confirm or challenge USDA's numbers."})
    return T


# ─────────────────────────── other commodities ───────────────────────────
def basic_brief(df, rd, prev, name):
    my = focus_my(df, rd)
    if my is None or prev is None:
        return None
    regs = [r for r in ["World", "United States"] if r in df.reg.unique()]
    ch = changes_table(df, rd, prev, my, regs)
    if not ch:
        return None
    hist = [month_history(df, r, a, rd) for r in regs for a in ("Production", "Ending Stocks")]
    hist = [h for h in hist if h]
    unit = df[(df.rd == rd)].unit.mode().iloc[0] if len(df[df.rd == rd]) else ""
    lines = []
    for r in ch:
        nd = 0 if abs(r["Production"]["now"] or 0) > 2000 else 2
        bits = [f"{a.lower()} {fmt(r[a]['now'],nd)} ({fmt(r[a]['chg'],nd,True)})" for a in ("Production", "Exports", "Ending Stocks") if r[a]["now"] is not None]
        if bits:
            lines.append(f"{r['region']} ({r['unit'].lower()}): " + ", ".join(bits) + (f"; stocks/use {r['S/U']['now']*100:.1f}%" if r["S/U"]["now"] else "") + ".")
    big = [h for h in hist if h["chg"] != 0 and h["pct_abs"] >= 75]
    if big:
        lines.append("Notable vs history: " + "; ".join(f"{h['region']} {h['attr'].lower()} {fmt(h['chg'],0 if abs(h['chg'])>=10 else 2,True)} — {h['note']}" for h in big) + ".")
    return {"my": my, "unit": unit, "changes": ch, "history": hist, "brief": [{"h": f"{name} — {my}", "t": " ".join(lines)}]}


# ─────────────────────────── main ───────────────────────────
def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cot_df = load_wasde("Cotton.json")
    rels = sorted(cot_df.rd.unique())[-N_RELEASES:]
    ctx = {}
    for key, fn in [("cond", crop_conditions), ("drought", texas_drought), ("esr", export_sales), ("brazil", brazil_exports),
                    ("cot", cot_cotton), ("oncall", oncall), ("px", prices)]:
        try:
            ctx[key] = fn()
        except Exception as e:
            print(f"source {key} unavailable: {e}")
    others = {n: load_wasde(f) for n, f in OTHERS.items() if (DATA / f).exists()}
    index = []
    all_rels = sorted(cot_df.rd.unique())
    for rd in rels:
        i = all_rels.index(rd); prev = all_rels[i - 1] if i > 0 else None
        my = focus_my(cot_df, rd)
        ch = changes_table(cot_df, rd, prev, my, COTTON_REGIONS)
        hist = [month_history(cot_df, r, a, rd) for r, a in [("United States", "Production"), ("United States", "Exports"),
                ("United States", "Ending Stocks"), ("World", "Production"), ("World", "Domestic Use"), ("World", "Ending Stocks"),
                ("World Less China", "Ending Stocks"), ("China", "Imports"), ("Brazil", "Exports"), ("India", "Production")]]
        hist = [h for h in hist if h]
        chk = cotton_checks(cot_df, rd, prev, my, ctx)
        F, score, label = cotton_outlook(cot_df, rd, prev, my, ch, hist, chk)
        cotton = {"my": my, "changes": ch, "history": hist, "checks": chk, "factors": F, "score": score, "outlook": label,
                  "brief": cotton_text(cot_df, rd, prev, my, ch, hist, chk, F, label)}
        oth = {}
        for n, d in others.items():
            if rd in set(d.rd.unique()):
                j = sorted(d.rd.unique()); k_ = j.index(rd)
                b = basic_brief(d, rd, j[k_ - 1] if k_ > 0 else None, n)
                if b:
                    oth[n] = b
        key = rd.strftime("%Y-%m")
        (OUT / f"{key}.json").write_text(json.dumps({"report": key, "label": rd.strftime("%B %Y"), "Cotton": cotton, **oth},
                                                    separators=(",", ":"), default=lambda o: None if pd.isna(o) else float(o)))
        index.append({"report": key, "label": rd.strftime("%B %Y"), "cotton_outlook": label})
    (OUT / "index.json").write_text(json.dumps({"generated": pd.Timestamp.now("UTC").strftime("%Y-%m-%d %H:%M UTC"), "reports": index[::-1]}))
    latest = json.load(open(OUT / f"{rels[-1].strftime('%Y-%m')}.json"))
    print("reports:", len(index), "| latest:", latest["label"], "| cotton outlook:", latest["Cotton"]["outlook"])
    for b in latest["Cotton"]["brief"]:
        print(f"\n[{b['h']}] {b['t']}")
    for n in OTHERS:
        if n in latest:
            print(f"\n{latest[n]['brief'][0]['t']}")


if __name__ == "__main__":
    main()
