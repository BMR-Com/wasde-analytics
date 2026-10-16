# BMR-Com · WASDE Analytics

**Monthly USDA WASDE balance sheets with a written brief for every report.**

🔗 **Live dashboard:** https://bmr-com.github.io/wasde-analytics/

## What's on the page

| Section | What it shows |
|---|---|
| **WASDE Brief** | Pick any of the last two years of reports. **Cotton** gets a full read: headline changes, the biggest country revisions, how each revision compares with the same month in past years, a cross-check of USDA's US crop against crop condition ratings and Texas drought, US export sales and Brazil export pace against USDA's targets, speculator and mill positioning, and a price outlook. **Corn, wheat, soybeans, soy products, rice and sugar** get a short summary of US and world changes and how unusual they are. |
| **Key changes table** | Production, domestic use, exports, imports, ending stocks and stocks-to-use for the world, world ex-China and major countries, with the change from the previous report. |
| **Balance sheets** | Last two releases × three marketing years for the world, US, Brazil, China, world ex-China, India and two regions you choose. |
| **Release history and charts** | How each estimate has been revised over the season. |

## Updates

A GitHub Actions workflow runs on the 9th–13th of each month: it downloads the WASDE release from USDA, rebuilds the balance sheets (`process.py`) and writes the brief (`brief.py`). The brief also draws on other BMR-Com public datasets: crop progress, the drought monitor, US export sales, Brazil trade, cotton on-call and the COT positioning desk.

```bash
pip install pandas numpy requests curl_cffi python-dateutil
python process.py full
python brief.py
python -m http.server 8000
```

---
*BMR-Com · independent commodity research. Data: USDA. Not investment advice.*
