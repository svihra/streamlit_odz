import datetime as dt
import io
import re
from bisect import bisect_left

import pandas as pd
import requests

SHEET_NAME = "Data"

COLUMN_MAP = {
    "Detektor": "Detector_Name",
    "SN#": "Serial",
    "Identifikační číslo": "Inventory",
    "Alias": "Alias",
    "Letadlo": "Aircraft",
    "Umístěn": "Installed",
    "Odebrán": "Removed",
    "Flightradar": "Flightradar_Status",
    "Poznámka": "Note",
    "Společnost": "Company",
    "Kontakt": "Contact",
    "Zapnut": "Turned_On",
    "Zapnuto": "Turned_On"
}

EXPECTED_HEADERS = set(COLUMN_MAP.keys())


def _looks_like_xlsx(content):
    return isinstance(content, (bytes, bytearray)) and content[:4] == b"PK\x03\x04"


def _looks_like_html(content):
    if not isinstance(content, (bytes, bytearray)):
        return False
    head = content[:200].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def _excel_serial_to_datetime(value):
    return pd.to_datetime(value, unit="d", origin="1899-12-30", errors="coerce")


def _parse_datetime_mixed(value):
    if pd.isna(value):
        return pd.NaT
    if isinstance(value, (dt.datetime, dt.date)):
        return pd.to_datetime(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value > 59:
            return _excel_serial_to_datetime(value)
    text = str(value).strip()
    if not text:
        return pd.NaT
    text = text.lstrip("<").strip()
    text = _extract_date_text(text)
    try:
        num = float(text)
        if num > 59:
            return _excel_serial_to_datetime(num)
    except ValueError:
        pass
    return pd.to_datetime(text, dayfirst=True, errors="coerce")


def _extract_date_text(text):
    if not text:
        return text
    cleaned = text.strip()
    cleaned = cleaned.replace("?", " ").replace(",", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)

    patterns = [
        r"\d{4}-\d{1,2}-\d{1,2}",
        r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}",
    ]
    for pat in patterns:
        m = re.search(pat, cleaned)
        if not m:
            continue
        date_part = m.group(0)
        tail = cleaned[m.end() :].strip()
        time_match = re.match(r"(\d{1,2}:\d{2})", tail)
        if time_match:
            return f"{date_part} {time_match.group(1)}"
        return date_part

    return cleaned


def _extract_on_datetime_from_note(note):
    if note is None or (isinstance(note, float) and pd.isna(note)):
        return pd.NaT
    text = str(note).strip()
    if not text:
        return pd.NaT
    text_l = text.lower()
    patterns = [
        r"zapnut[oa]?\s+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})(?:\s*[vV]?\s*(\d{1,2}:\d{2}))?",
        r"zapnuto\s+(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})(?:\s*[vV]?\s*(\d{1,2}:\d{2}))?",
    ]
    for pat in patterns:
        m = re.search(pat, text_l)
        if m:
            date_part = m.group(1)
            time_part = m.group(2)
            candidate = f"{date_part} {time_part}" if time_part else date_part
            return pd.to_datetime(candidate, dayfirst=True, errors="coerce")
    return pd.NaT


def _extract_gdrive_file_id(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "http" not in text and "drive.google.com" not in text and "docs.google.com" not in text:
        return text
    patterns = [
        r"/d/e/([a-zA-Z0-9_-]+)",
        r"/d/([a-zA-Z0-9_-]+)",
        r"id=([a-zA-Z0-9_-]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1)
    return None


def _normalize_public_url(url):
    if not url:
        return url
    text = str(url).strip()
    if "docs.google.com/spreadsheets/d/e/" in text:
        text = text.replace("/pubhtml", "/pub")
        if "output=" not in text:
            text += ("&output=xlsx" if "?" in text else "?output=xlsx")
        return text
    if "drive.google.com" in text or "docs.google.com" in text:
        file_id = _extract_gdrive_file_id(text)
        if file_id:
            if "spreadsheets" in text:
                return f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx"
            return f"https://drive.google.com/uc?export=download&id={file_id}"
    if "/s/" in text and "download=" not in text:
        return text + ("&download=1" if "?" in text else "?download=1")
    return text


def fetch_public_file(url):
    dl_url = _normalize_public_url(url)
    resp = requests.get(dl_url, timeout=60)
    if resp.status_code != 200:
        raise ValueError(f"Download failed ({resp.status_code}). Check URL.")
    content = resp.content
    if _looks_like_html(content) and "docs.google.com/spreadsheets" in dl_url:
        csv_url = dl_url.replace("output=xlsx", "output=csv")
        if csv_url != dl_url:
            resp2 = requests.get(csv_url, timeout=60)
            if resp2.status_code == 200:
                return resp2.content
    return content


def _normalize_header(value):
    return str(value).strip().lower()


def _match_count(values):
    return sum(1 for v in values if _normalize_header(v) in {h.lower() for h in EXPECTED_HEADERS})


def load_dataframe(content):
    if _looks_like_xlsx(content):
        try:
            df_raw = pd.read_excel(
                io.BytesIO(content),
                sheet_name=SHEET_NAME,
                dtype=object,
                header=None,
            )
        except ValueError:
            sheet_names = pd.ExcelFile(io.BytesIO(content)).sheet_names
            raise ValueError(f"Sheet '{SHEET_NAME}' not found. Available: {', '.join(sheet_names)}")
    else:
        try:
            df_raw = pd.read_csv(io.BytesIO(content), dtype=object, header=None)
        except Exception as exc:
            raise ValueError(f"Downloaded file not readable: {exc}")

    if df_raw.empty:
        return df_raw

    df_raw = df_raw.dropna(axis=1, how="all")

    header_row_idx = None
    scan_rows = min(10, len(df_raw))
    for i in range(scan_rows):
        row = df_raw.iloc[i].tolist()
        if _match_count(row) >= 3:
            header_row_idx = i
            break

    if header_row_idx is None:
        header_row_idx = 0

    header = df_raw.iloc[header_row_idx].tolist()
    df = df_raw.iloc[header_row_idx + 1 :].copy()
    df.columns = [str(c).strip() if c is not None else "" for c in header]

    return df


def normalize_columns(df):
    return df.rename(columns={k: v for k, v in COLUMN_MAP.items() if k in df.columns})


def ensure_alias(df):
    if "Alias" in df.columns:
        return
    preview_cols = ", ".join([c for c in df.columns if c][:12])
    raise ValueError(
        "Alias column not found. Expected 'Alias' in the Data sheet."
        f" Detected columns: {preview_cols}"
    )


def _add_event(events, df, col, event_type):
    if col not in df.columns:
        return
    tmp = df[["Detector_ID"] + [c for c in ["Aircraft", "Note", "Company", "Contact", col] if c in df.columns]].copy()
    tmp = tmp.dropna(subset=[col])
    tmp["DateTime"] = tmp[col].apply(_parse_datetime_mixed)
    tmp = tmp.dropna(subset=["DateTime"])
    tmp["Event_Type"] = event_type
    tmp["Detail"] = tmp.get("Note", "").fillna("")
    tmp = tmp.drop(columns=[col], errors="ignore")
    events.append(tmp)


def _series_from_column(df, col):
    if col not in df.columns:
        return pd.Series([pd.NaT] * len(df), index=df.index)
    return df[col].apply(_parse_datetime_mixed)


def _event_from_series(df, series, event_type):
    tmp = df[["Detector_ID"] + [c for c in ["Aircraft", "Note", "Company", "Contact"] if c in df.columns]].copy()
    tmp["DateTime"] = series
    tmp = tmp.dropna(subset=["DateTime"])
    if tmp.empty:
        return None
    tmp["Event_Type"] = event_type
    tmp["Detail"] = tmp.get("Note", "").fillna("")
    return tmp


def _next_start_per_row(df, base_dt):
    result = pd.Series(pd.NaT, index=df.index)
    for det_id, idx in df.groupby("Detector_ID").groups.items():
        s = base_dt.loc[idx].dropna().sort_values()
        if s.empty:
            continue
        next_vals = s.shift(-1)
        result.loc[s.index] = next_vals.values
    return result


def _prior_turned_on_per_installed(df, turned_on_dt, installed_dt):
    prior = pd.Series(pd.NaT, index=df.index)
    for det_id, idx in df.groupby("Detector_ID").groups.items():
        t_on = turned_on_dt.loc[idx].dropna().sort_values()
        inst = installed_dt.loc[idx].dropna().sort_values()
        if t_on.empty or inst.empty:
            continue

        inst_items = list(inst.items())
        for pos, (row_idx, inst_time) in enumerate(inst_items):
            prev_inst_time = inst_items[pos - 1][1] if pos > 0 else pd.NaT
            if pd.isna(prev_inst_time):
                candidates = t_on[t_on <= inst_time]
            else:
                candidates = t_on[(t_on > prev_inst_time) & (t_on <= inst_time)]
            if not candidates.empty:
                prior.at[row_idx] = candidates.iloc[-1]
    return prior


def _prior_event_type_before_installed(df, turned_on_dt, installed_dt, removed_dt):
    prev_type = pd.Series(pd.NA, index=df.index, dtype=object)
    for det_id, idx in df.groupby("Detector_ID").groups.items():
        records = []
        for row_idx in idx:
            dt_on = turned_on_dt.at[row_idx]
            if pd.notna(dt_on):
                records.append((pd.Timestamp(dt_on), "Turned on"))
            dt_inst = installed_dt.at[row_idx]
            if pd.notna(dt_inst):
                records.append((pd.Timestamp(dt_inst), "Installed", row_idx))
            dt_rem = removed_dt.at[row_idx]
            if pd.notna(dt_rem):
                records.append((pd.Timestamp(dt_rem), "Removed"))
        if not records:
            continue
        records.sort(key=lambda x: x[0])
        dt_list = [r[0] for r in records]
        type_list = [r[1] for r in records]
        for rec in records:
            if len(rec) == 3 and rec[1] == "Installed":
                inst_dt = rec[0]
                row_idx = rec[2]
                pos = bisect_left(dt_list, inst_dt)
                if pos > 0:
                    prev_type.at[row_idx] = type_list[pos - 1]
    return prev_type


def _n_months_series(df, turned_on_dt, installed_dt, months_after):
    explicit_n = _series_from_column(df, "Months_After_On")
    removed_dt = _series_from_column(df, "Removed")

    offset = pd.DateOffset(months=months_after)
    prev_event_type = _prior_event_type_before_installed(df, turned_on_dt, installed_dt, removed_dt)
    use_installed = turned_on_dt.isna() & installed_dt.notna() & (prev_event_type != "Turned on")
    base_dt = turned_on_dt.copy()
    base_dt.loc[use_installed] = installed_dt.loc[use_installed]

    next_start = _next_start_per_row(df, base_dt)
    derived_n = base_dt + offset

    explicit_mask = explicit_n.notna()
    derived_mask = explicit_n.isna() & base_dt.notna()

    final_n = explicit_n.copy()
    final_n = final_n.where(explicit_mask, derived_n)

    removed_relevant = removed_dt.notna() & base_dt.notna() & (removed_dt >= base_dt)
    has_closer_start = next_start.notna() & derived_n.notna() & (next_start <= derived_n)
    keep_mask = explicit_mask | (
        derived_mask & (~has_closer_start) & (~removed_relevant | (removed_dt >= final_n))
    )
    today = pd.Timestamp.today().normalize()
    not_in_future = final_n.notna() & (final_n <= today)
    final_n = final_n.where(keep_mask & not_in_future, pd.NaT)

    return final_n


def parse_detector_data(df, months_after=3):
    ensure_alias(df)
    df["Detector_ID"] = df["Alias"].astype(str).str.strip()
    df.loc[df["Detector_ID"].isin(["nan", "None", ""]), "Detector_ID"] = pd.NA
    df = df.dropna(subset=["Detector_ID"])

    static_cols = [
        c
        for c in [
            "Detector_Name",
            "Alias",
            "Serial",
            "Inventory",
            "Box_SN",
            "HW_Version",
            "FW_Version",
            "Flightradar_Status",
            "Extra",
            "Company",
            "Contact",
        ]
        if c in df.columns
    ]
    static_df = df[["Detector_ID"] + static_cols].drop_duplicates("Detector_ID") if static_cols else None

    events = []
    _add_event(events, df, "Removed", "Removed")
    _add_event(events, df, "Seen", "Seen on ODZ")

    installed_dt = _series_from_column(df, "Installed")
    turned_on_dt = _series_from_column(df, "Turned_On")
    if "Note" in df.columns:
        note_on = df["Note"].apply(_extract_on_datetime_from_note)
        turned_on_dt = turned_on_dt.fillna(note_on)

    label = "Turned on too long"
    installed_after_label = "Installed late"
    n_months_dt = _n_months_series(df, turned_on_dt, installed_dt, months_after)

    offset = pd.DateOffset(months=months_after)
    prior_turn_on = _prior_turned_on_per_installed(df, turned_on_dt, installed_dt)
    late_threshold = prior_turn_on + offset
    installed_late = installed_dt.notna() & prior_turn_on.notna() & (installed_dt > late_threshold)

    if installed_late.any():
        late_events = _event_from_series(
            df[installed_late], installed_dt[installed_late], installed_after_label
        )
        if late_events is not None:
            events.append(late_events)
    normal_installed = _event_from_series(df[~installed_late], installed_dt[~installed_late], "Installed")
    if normal_installed is not None:
        events.append(normal_installed)

    turned_on_events = _event_from_series(df, turned_on_dt, "Turned on")
    if turned_on_events is not None:
        events.append(turned_on_events)

    n_events = _event_from_series(df, n_months_dt, label)
    if n_events is not None:
        events.append(n_events)

    if not events:
        raise ValueError("No events found in Installed/Removed/Seen/Turned on columns.")

    ev = pd.concat(events, ignore_index=True)
    if "Aircraft" not in ev.columns:
        ev["Aircraft"] = ""
    if static_df is not None:
        merge_cols = [c for c in static_cols if c not in ev.columns]
        if merge_cols:
            ev = ev.merge(static_df[["Detector_ID"] + merge_cols], on="Detector_ID", how="left")

    event_order = {
        "Removed": 4,
        "Installed": 3,
        installed_after_label: 3,
        "Seen on ODZ": 2,
        "Turned on": 1,
        label: 0,
    }
    ev["Event_Order"] = ev["Event_Type"].map(event_order).fillna(0)
    ev = ev.sort_values(["Detector_ID", "DateTime", "Event_Order"])

    latest = ev.groupby("Detector_ID").tail(1).copy()
    latest = latest.rename(columns={"Event_Type": "Latest_Event", "DateTime": "Latest_Time"})
    latest["Status"] = latest["Latest_Event"]
    if static_df is not None:
        merge_cols = [c for c in static_cols if c not in latest.columns]
        if merge_cols:
            latest = latest.merge(static_df[["Detector_ID"] + merge_cols], on="Detector_ID", how="left")

    base_cols = ["Detector_ID", "Status", "Latest_Time", "Aircraft", "Detail"]
    extra_cols = [c for c in static_cols if c in latest.columns and c not in base_cols]
    latest = latest[base_cols + extra_cols]

    return ev, latest
