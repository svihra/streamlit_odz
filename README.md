# Detectors On Board Dashboard

Streamlit dashboard that reads a shared spreadsheet and visualizes detector lifecycle events (Installed, Turned on, Removed, Turned on too long, Installed late). It provides:

- An interactive timeline with event points and connecting lines.
- Action tables for detectors to remove from plane and detectors ready to turn on and install.
- A table of currently turned on or installed detectors.
- A status count histogram.

## How It Works

- The app downloads the spreadsheet from a public URL stored in Streamlit secrets.
- Data is parsed into events and a latest-status table in memory (no files are written).
- Derived events are created based on a configurable number of months after “Turned on”.

## Files

- `app.py`: Streamlit UI, filters, plots, and tables.
- `data_parser.py`: Data download, parsing, and event generation logic.
- `.streamlit/secrets.toml`: Local secrets (do not commit).

## Run Locally

1. Create or activate your conda env.
2. Install dependencies.
3. Add secrets.
4. Run the app.

Example:

```bash
conda create -n streamlit python=3.11
conda activate streamlit
conda install -c conda-forge streamlit pandas plotly requests openpyxl
```

Create `.streamlit/secrets.toml`:

```toml
[public]
url = "https://docs.google.com/spreadsheets/..."

[settings]
months_after_on = 3
```

Run:

```bash
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Push this repo to GitHub (do not include `.streamlit/secrets.toml`).
2. Create a new app in Streamlit Cloud from the repo.
3. Add your secrets under App → Settings → Secrets using the same format as above.

## Notes

- The app expects the “Data” sheet in the spreadsheet.
- The “Alias” column is required and used as the primary detector ID.
- If the public link is to a published Google Sheet, the app converts it to a downloadable XLSX/CSV automatically.
