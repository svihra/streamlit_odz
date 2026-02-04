from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data_parser import fetch_public_file, load_dataframe, normalize_columns, parse_detector_data


@st.cache_data(show_spinner=False)
def get_content(url):
    return fetch_public_file(url)


st.set_page_config(page_title="Detectors on board", layout="wide")
st.title("Detectors on board: status dashboard")

with st.sidebar:
    st.header("Source")
    public_url = st.secrets.get("public", {}).get("url", "")
    col_test, col_reload = st.columns(2)
    if col_test.button("Test connection"):
        try:
            _ = get_content(public_url)
            st.success("OK. File downloaded.")
        except Exception as exc:
            st.error(str(exc))
    if col_reload.button("Reload data"):
        st.cache_data.clear()

if not public_url:
    st.info("Configure a public share URL in `.streamlit/secrets.toml` under `[public]`.")
    st.stop()

try:
    content = get_content(public_url)
    df = load_dataframe(content)
    df = normalize_columns(df)
    months_after = int(st.secrets.get("settings", {}).get("months_after_on", 3))
    ev, latest = parse_detector_data(df, months_after=months_after)
    n_months_label = "Turned on too long"
    installed_after_label = "Installed late"
except Exception as exc:
    st.error(str(exc))
    st.stop()

display_id_col = "Alias" if "Alias" in latest.columns else "Detector_ID"

st.subheader("Filters")
f1, f2, f3, f4 = st.columns(4)

det_filter = f1.multiselect("Detector", sorted(latest[display_id_col].dropna().unique()))
air_values = sorted([x for x in latest.get("Aircraft", pd.Series()).unique() if str(x).strip() not in ("", "nan", "None")])
air_filter = f2.multiselect("Aircraft", air_values)
type_filter = f3.multiselect("Event type", sorted(ev["Event_Type"].dropna().unique()))

if ev["DateTime"].notna().any():
    min_date = ev["DateTime"].min().date()
    max_date = ev["DateTime"].max().date()
    date_range = f4.date_input("Date range", value=(min_date, max_date))
else:
    date_range = None

flt_latest = latest.copy()
if det_filter:
    flt_latest = flt_latest[flt_latest[display_id_col].isin(det_filter)]
if air_filter and "Aircraft" in flt_latest.columns:
    flt_latest = flt_latest[flt_latest["Aircraft"].isin(air_filter)]

flt_ev = ev.copy()
if det_filter:
    flt_ev = flt_ev[flt_ev[display_id_col].isin(det_filter)]
if air_filter and "Aircraft" in flt_ev.columns:
    flt_ev = flt_ev[flt_ev["Aircraft"].isin(air_filter)]
if type_filter:
    flt_ev = flt_ev[flt_ev["Event_Type"].isin(type_filter)]
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    start, end = date_range
    flt_ev = flt_ev[(flt_ev["DateTime"].dt.date >= start) & (flt_ev["DateTime"].dt.date <= end)]

flt_ev = flt_ev.copy()
flt_ev["PlotDate"] = flt_ev["DateTime"].dt.date

def _build_timeline_lines(events_df, id_col, color_map, n_months_label):
    lines = []
    if events_df.empty:
        return lines
    for det_id, g in events_df.sort_values("PlotDate").groupby(id_col):
        g = g.sort_values("PlotDate")
        starts = g[g["Event_Type"].isin(["Installed", installed_after_label])]
        for _, start in starts.iterrows():
            start_time = start["PlotDate"]
            if pd.isna(start_time):
                continue
            after = g[g["PlotDate"] > start_time]
            if after.empty:
                lines.append(
                    (
                        start_time,
                        date.today(),
                        det_id,
                        color_map.get(start["Event_Type"], color_map.get("Installed", "#1f77b4")),
                        start["Event_Type"],
                    )
                )
                continue
            target = after.head(1)
            if not target.empty:
                t = target["PlotDate"].iloc[0]
                color = color_map.get(start["Event_Type"], color_map.get("Installed", "#1f77b4"))
                lines.append((start_time, t, det_id, color, start["Event_Type"]))

        n_months = g[g["Event_Type"] == n_months_label]
        today = date.today()
        for _, t3 in n_months.iterrows():
            t3_time = t3["PlotDate"]
            if pd.isna(t3_time):
                continue
            if t3_time > today:
                continue
            after = g[g["PlotDate"] > t3_time]
            if after.empty:
                lines.append(
                    (
                        t3_time,
                        date.today(),
                        det_id,
                        color_map.get(n_months_label, "#999999"),
                        n_months_label,
                    )
                )
                continue
            target = after.head(1)
            t = target["PlotDate"].iloc[0]
            lines.append(
                (t3_time, t, det_id, color_map.get(n_months_label, "#999999"), n_months_label)
            )

        removed = g[g["Event_Type"] == "Removed"]
        for _, rem in removed.iterrows():
            rem_time = rem["PlotDate"]
            if pd.isna(rem_time):
                continue
            after = g[g["PlotDate"] > rem_time]
            if after.empty:
                lines.append(
                    (
                        rem_time,
                        today,
                        det_id,
                        color_map.get("Removed", "#d62728"),
                        "Removed",
                    )
                )
                continue
            target = after.head(1)
            t = target["PlotDate"].iloc[0]
            lines.append(
                (
                    rem_time,
                    t,
                    det_id,
                    color_map.get("Removed", "#d62728"),
                    "Removed",
                )
            )

        turned_on = g[g["Event_Type"] == "Turned on"]
        for _, ton in turned_on.iterrows():
            ton_time = ton["PlotDate"]
            if pd.isna(ton_time):
                continue
            after = g[g["PlotDate"] > ton_time]
            if after.empty:
                lines.append(
                    (
                        ton_time,
                        today,
                        det_id,
                        color_map.get("Turned on", "#2ca02c"),
                        "Turned on",
                    )
                )
                continue
            target = after.head(1)
            t = target["PlotDate"].iloc[0]
            lines.append(
                (
                    ton_time,
                    t,
                    det_id,
                    color_map.get("Turned on", "#2ca02c"),
                    "Turned on",
                )
            )
    return lines


st.subheader("Event timeline")
scatter_fig = px.scatter(
    flt_ev,
    x="PlotDate",
    y=display_id_col,
    color="Event_Type",
    hover_data=[
        c
        for c in [
            "Aircraft",
            "Detail",
            "Alias",
            "Detector_Name",
            "Serial",
            "Inventory",
            "Box_SN",
            "Flightradar_Status",
            "Company",
            "Contact",
        ]
        if c in flt_ev.columns
    ],
    height=500,
)

for tr in scatter_fig.data:
    if getattr(tr, "name", None):
        tr.legendgroup = tr.name
    if getattr(tr, "name", None) == installed_after_label:
        tr.marker.color = "#ff7f0e"

color_map = {}
for tr in scatter_fig.data:
    if hasattr(tr, "name") and hasattr(tr, "marker") and tr.marker is not None:
        if isinstance(tr.marker.color, str):
            color_map[tr.name] = tr.marker.color

line_traces = []
for start_t, end_t, det_id, color, group in _build_timeline_lines(
    flt_ev, display_id_col, color_map, n_months_label
):
    line_traces.append(
        go.Scatter(
            x=[start_t, end_t],
            y=[det_id, det_id],
            mode="lines",
            line={"color": color, "width": 30},
            hoverinfo="skip",
            showlegend=False,
            legendgroup=group,
        )
    )

fig = go.Figure(data=line_traces)
for tr in scatter_fig.data:
    fig.add_trace(tr)
fig.update_layout(scatter_fig.layout)
fig.update_layout(legend=dict(groupclick="togglegroup"))
sorted_ids = sorted(flt_ev[display_id_col].dropna().unique())
fig.update_yaxes(categoryorder="array", categoryarray=sorted_ids, autorange="reversed")
for tr in fig.data:
    if getattr(tr, "mode", "") and "markers" in tr.mode:
        tr.marker.size = 14
        tr.marker.line = {"width": 0.5, "color": "white"}
        tr.marker.symbol = "hourglass"

st.plotly_chart(fig, width="stretch")

def _format_latest_table(df):
    out = df.copy()
    if display_id_col != "Detector_ID" and "Detector_ID" in out.columns:
        out = out.drop(columns=["Detector_ID"])
    if "Alias" in out.columns:
        ordered = ["Alias"] + [c for c in out.columns if c != "Alias"]
        out = out[ordered]
    if "Latest_Time" in out.columns:
        out["Latest_Date"] = out["Latest_Time"].dt.date
        out = out.drop(columns=["Latest_Time"])
    return out

st.subheader("Detectors to remove from plane")
to_remove = flt_latest[flt_latest["Status"].isin([n_months_label, installed_after_label])].copy()
if to_remove.empty:
    st.info("No detectors currently marked for removal.")
else:
    to_remove["Action"] = "Remove from plane"
    st.dataframe(
        _format_latest_table(to_remove).sort_values([display_id_col]),
        width="stretch",
        hide_index=True,
    )

st.subheader("Detectors ready to turn on and install")
removed_now = flt_latest[flt_latest["Status"] == "Removed"].copy()
if removed_now.empty:
    st.info("No detectors currently removed.")
else:
    removed_now["Action"] = "Turn on and install"
    st.dataframe(
        _format_latest_table(removed_now).sort_values([display_id_col]),
        width="stretch",
        hide_index=True,
    )

st.subheader("Currently turned on or installed")
active_statuses = ["Turned on", "Installed"]
active_latest = flt_latest[flt_latest["Status"].isin(active_statuses)].copy()
if active_latest.empty:
    st.info("No detectors currently turned on or installed.")
else:
    display_active = _format_latest_table(active_latest)
    st.dataframe(
        display_active.sort_values([display_id_col]),
        width="stretch",
        hide_index=True,
    )

st.subheader("Current status count")
status_counts = latest["Status"].value_counts(dropna=False).rename_axis("Status").reset_index(name="Count")
fig_status = px.bar(status_counts, x="Status", y="Count")
st.plotly_chart(fig_status, width="stretch")
