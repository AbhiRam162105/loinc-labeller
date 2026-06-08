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
2. https://share.streamlit.io → **New app** → pick the repo/branch.
3. **Main file path** = `streamlit_app.py` → **Deploy**.

## Label storage
Labels are written to a local `diagnosis_labels.csv` next to the app and read
back on every load — so **reloading the browser window keeps all labels**, and
the saved-progress counter / pre-filled fields persist.

Note: the file lives on the app's server disk for the life of the running
container. It survives reloads and reruns, but a full **reboot/redeploy** (e.g.
after the free app sleeps from inactivity) starts a fresh disk. Use the in-app
**Download labels CSV** button to keep a durable copy.
