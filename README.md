# LOINC Labeller

Streamlit tool for an external labeller to assign the correct LOINC code to
diagnosis tests where the claude / gpt / gemini picks disagreed or returned none.
Labels are **synced to a Google Sheet after every save**.

## Files
- `streamlit_app.py` — the app (main file for Streamlit Community Cloud)
- `diagnosis_data_slim.json` — slim data (test + model picks + picked-code names)
- `requirements.txt` — streamlit, gspread, google-auth
- `.streamlit/secrets.toml.example` — template for the Google Sheets credentials

## Google Sheet setup (one time)
1. In Google Cloud Console: create a **service account**, enable the **Google
   Sheets API** and **Google Drive API**, and create + download a **JSON key**.
2. Create a Google Sheet. **Share** it (Editor) with the service account's
   `client_email` (looks like `name@project.iam.gserviceaccount.com`).
3. Copy `.streamlit/secrets.toml.example` → `.streamlit/secrets.toml`, paste the
   JSON key fields under `[gcp_service_account]`, and set `gsheet_url`.

The app writes to a worksheet named `labels` (created automatically with a header
row). Each "Done" upserts that test's row immediately. Columns:
`test_name, correct_loinc, correct_label, labeller_email, claude_pick, gpt_pick,
gemini_pick, timestamp`.

If no secrets are configured, the app falls back to a local `diagnosis_labels.csv`.

## Run locally
```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deploy on Streamlit Community Cloud (free)
1. Push this folder to a GitHub repo.
2. https://share.streamlit.io → **New app** → pick repo/branch.
3. **Main file path** = `streamlit_app.py`.
4. **Advanced settings → Secrets**: paste the contents of your
   `.streamlit/secrets.toml` (service account + `gsheet_url`).
5. **Deploy.** The Google Sheet now collects labels durably across reboots.
