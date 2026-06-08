# LOINC Labeller

Streamlit tool for an external labeller to assign the correct LOINC code to
diagnosis tests where the claude / gpt / gemini picks disagreed or returned none.

## Files
- `streamlit_app.py` — the app (main file for Streamlit Community Cloud)
- `diagnosis_data_slim.json` — slim data (test + model picks + picked-code names)
- `requirements.txt` — `streamlit`

## Run locally
```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deploy on Streamlit Community Cloud (free)
1. Push this folder to a GitHub repo.
2. Go to https://share.streamlit.io → **New app**.
3. Pick the repo/branch, set **Main file path** = `streamlit_app.py`, Deploy.

## ⚠️ Label storage on the cloud
Labels are written to a local `diagnosis_labels.csv`. On Streamlit Community
Cloud the filesystem is **ephemeral** — the CSV survives a live session but is
**wiped on every reboot/redeploy**. Use the in-app **Download labels CSV** button
to save your work, or switch the storage backend to a Google Sheet / database for
durable multi-session collection.
