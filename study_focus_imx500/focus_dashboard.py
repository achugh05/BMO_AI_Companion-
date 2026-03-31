import os
import math
from typing import Optional, List

import pandas as pd
import plotly.graph_objects as go


# =========================================================
# STYLE CONTROLS
# Adjust these values to control fonts, sizes, spacing, etc.
# while keeping the dashboard in 800 x 480
# =========================================================
STYLE = {
    # Fixed screen size
    "screen_width": 800,
    "screen_height": 480,

    # Layout
    "page_padding": 6,
    "gap": 6,
    "border_width": 3,

    # Section heights
    "title_height": 48,
    "cards_height": 82,

    # Fonts
    "font_family": '"Pixelify Sans", sans-serif',
    "title_font_size": 28,
    "card_title_font_size": 16,
    "card_value_font_size": 20,
    "plot_base_font_size": 15,
    "legend_font_size": 13,
    "axis_title_font_size": 18,
    "axis_tick_font_size": 13,

    # Plot margins
    "plot_margin_left": 60,
    "plot_margin_right": 18,
    "plot_margin_top": 10,
    "plot_margin_bottom": 56,

    # Axis spacing
    "x_title_standoff": 8,
    "y_title_standoff": 4,

    # Line widths
    "session_line_width": 5,
    "avg_line_width": 6,
    "axis_line_width": 2,
    "grid_width": 1,

    # Tick styling
    "tick_len": 5,
    "tick_width": 2,

    # Colors
    "bg": "#A8D7D1",
    "panel": "#DCEFEB",
    "card": "#EAF8F5",
    "border": "#243B4A",
    "text": "#15313A",
    "axis": "#15313A",
    "session": "#2D7F7C",
    "avg": "#F2B134",
    "grid": "rgba(36,59,74,0.20)",

    # Score colors
    "score_red": "#C94C4C",
    "score_yellow": "#D4A017",
    "score_green": "#2E8B57",
}


def _adaptive_downsample_by_time(
    df: pd.DataFrame,
    time_col: str = "start_time",
    value_cols: Optional[List[str]] = None,
    target_points: int = 160,
) -> pd.DataFrame:
    if value_cols is None:
        value_cols = ["focused_pct", "selected_avg"]

    if len(df) <= target_points:
        return df.copy()

    df = df.sort_values(time_col).copy()
    total_seconds = (df[time_col].max() - df[time_col].min()).total_seconds()

    if total_seconds <= 0:
        return df.iloc[:target_points].copy()

    bucket_seconds = max(1, math.ceil(total_seconds / target_points))
    df["_bucket"] = df[time_col].astype("int64") // (bucket_seconds * 10**9)

    agg_dict = {col: "mean" for col in value_cols if col in df.columns}
    if "duration_minutes" in df.columns:
        agg_dict["duration_minutes"] = "sum"
    if "session_id" in df.columns:
        agg_dict["session_id"] = "last"
    if "average_score" in df.columns:
        agg_dict["average_score"] = "mean"
    if "dominant_state" in df.columns:
        agg_dict["dominant_state"] = "last"
    agg_dict[time_col] = "min"

    out = (
        df.groupby("_bucket", as_index=False)
        .agg(agg_dict)
        .sort_values(time_col)
        .drop(columns=["_bucket"], errors="ignore")
    )
    return out


def _score_color(value: float, style: dict) -> str:
    if value < 50:
        return style["score_red"]
    if value <= 70:
        return style["score_yellow"]
    return style["score_green"]


def plot_focus_dashboard_bmo_window(
    csv_path: str,
    window_days: int = 7,
    output_html: Optional[str] = None,
    auto_open: bool = False,
    target_points: int = 160,
    style: Optional[dict] = None,
):
    s = STYLE.copy()
    if style:
        s.update(style)

    if window_days not in (1, 7, 30):
        raise ValueError("window_days must be one of: 1, 7, 30")

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    df = pd.read_csv(csv_path)

    required_cols = {
        "session_id",
        "start_time",
        "duration_minutes",
        "focused_pct",
        "average_score",
        "dominant_state",
    }
    missing = required_cols - set(df.columns)
    if missing:
        raise ValueError(f"Missing required CSV columns: {sorted(missing)}")

    df["start_time"] = pd.to_datetime(df["start_time"], errors="coerce")
    df["duration_minutes"] = pd.to_numeric(df["duration_minutes"], errors="coerce")
    df["focused_pct"] = pd.to_numeric(df["focused_pct"], errors="coerce")
    df["average_score"] = pd.to_numeric(df["average_score"], errors="coerce")

    df = df.dropna(subset=["start_time", "duration_minutes", "focused_pct"]).copy()
    df = df[df["duration_minutes"] > 0].sort_values("start_time")

    if df.empty:
        raise ValueError("No valid session rows found in CSV.")

    df = df.set_index("start_time")
    df["weighted_focus"] = df["focused_pct"] * df["duration_minutes"]

    for out_col, window in [
        ("focus_avg_1d", "1D"),
        ("focus_avg_7d", "7D"),
        ("focus_avg_30d", "30D"),
    ]:
        rolling_minutes = df["duration_minutes"].rolling(window, min_periods=1).sum()
        rolling_weighted = df["weighted_focus"].rolling(window, min_periods=1).sum()
        df[out_col] = (rolling_weighted / rolling_minutes).fillna(0)

    avg_col_map = {
        1: "focus_avg_1d",
        7: "focus_avg_7d",
        30: "focus_avg_30d",
    }
    selected_avg_col = avg_col_map[window_days]

    end_time = df.index.max()
    start_cutoff = end_time - pd.Timedelta(days=window_days)
    filtered = df[df.index >= start_cutoff].copy()

    if filtered.empty:
        filtered = df.tail(1).copy()

    filtered = filtered.reset_index()
    filtered["selected_avg"] = filtered[selected_avg_col]

    plot_df = _adaptive_downsample_by_time(
        filtered,
        time_col="start_time",
        value_cols=["focused_pct", "selected_avg"],
        target_points=target_points,
    )

    latest_focus = float(filtered["focused_pct"].iloc[-1])
    latest_avg = float(filtered["selected_avg"].iloc[-1])
    session_count = int(len(filtered))
    total_hours = float(filtered["duration_minutes"].sum()) / 60.0

    now_color = _score_color(latest_focus, s)
    avg_color = _score_color(latest_avg, s)

    # Compute chart height so total layout exactly fits 800x480
    chart_outer_h = (
        s["screen_height"]
        - 2 * s["page_padding"]
        - 2 * s["gap"]
        - s["title_height"]
        - s["cards_height"]
    )

    plot_w = s["screen_width"] - 2 * s["page_padding"] - 2 * s["border_width"]
    plot_h = chart_outer_h - 2 * s["border_width"]

    if window_days == 1:
        tickformat = "%H:%M"
        dtick = 3 * 60 * 60 * 1000
    elif window_days == 7:
        tickformat = "%b %d"
        dtick = 24 * 60 * 60 * 1000
    else:
        tickformat = "%b %d"
        dtick = 3 * 24 * 60 * 60 * 1000

    # Remove left gap by using actual data bounds, not whole window bounds
    first_plot_time = plot_df["start_time"].min()
    last_plot_time = plot_df["start_time"].max()

    fig = go.Figure()

    fig.add_trace(
        go.Scattergl(
            x=plot_df["start_time"],
            y=plot_df["focused_pct"],
            mode="lines",
            name="Session",
            line=dict(color=s["session"], width=s["session_line_width"]),
            hovertemplate="Time: %{x}<br>Session Focus: %{y:.1f}%<extra></extra>",
        )
    )

    fig.add_trace(
        go.Scattergl(
            x=plot_df["start_time"],
            y=plot_df["selected_avg"],
            mode="lines",
            name=f"{window_days}D Avg",
            line=dict(color=s["avg"], width=s["avg_line_width"]),
            hovertemplate=f"{window_days}D Avg: %{{y:.1f}}%<extra></extra>",
        )
    )

    fig.update_layout(
        width=plot_w,
        height=plot_h,
        autosize=False,
        paper_bgcolor=s["panel"],
        plot_bgcolor=s["panel"],
        margin=dict(
            l=s["plot_margin_left"],
            r=s["plot_margin_right"],
            t=s["plot_margin_top"],
            b=s["plot_margin_bottom"],
        ),
        font=dict(
            family=s["font_family"],
            color=s["text"],
            size=s["plot_base_font_size"],
        ),
        hovermode="x unified",
        showlegend=True,
        legend=dict(
            orientation="h",
            x=0.98,
            y=0.98,
            xanchor="right",
            yanchor="top",
            bgcolor="rgba(0,0,0,0)",
            font=dict(
                size=s["legend_font_size"],
                color=s["text"],
                family=s["font_family"],
            ),
        ),
        xaxis=dict(
            title=dict(
                text="Date",
                font=dict(
                    size=s["axis_title_font_size"],
                    color=s["axis"],
                    family=s["font_family"],
                ),
                standoff=s["x_title_standoff"],
            ),
            type="date",
            range=[first_plot_time, last_plot_time],
            tickfont=dict(
                size=s["axis_tick_font_size"],
                color=s["axis"],
                family=s["font_family"],
            ),
            tickformat=tickformat,
            dtick=dtick,
            ticklen=s["tick_len"],
            tickwidth=s["tick_width"],
            tickcolor=s["axis"],
            showline=True,
            linewidth=s["axis_line_width"],
            linecolor=s["axis"],
            showgrid=False,
            zeroline=False,
            automargin=True,
        ),
        yaxis=dict(
            title=dict(
                text="Focus %",
                font=dict(
                    size=s["axis_title_font_size"],
                    color=s["axis"],
                    family=s["font_family"],
                ),
                standoff=s["y_title_standoff"],
            ),
            range=[0, 110],
            tickmode="array",
            tickvals=[0, 20, 40, 60, 80, 100],
            tickfont=dict(
                size=s["axis_tick_font_size"],
                color=s["axis"],
                family=s["font_family"],
            ),
            ticklen=s["tick_len"],
            tickwidth=s["tick_width"],
            tickcolor=s["axis"],
            showline=True,
            linewidth=s["axis_line_width"],
            linecolor=s["axis"],
            showgrid=True,
            gridcolor=s["grid"],
            gridwidth=s["grid_width"],
            zeroline=False,
            automargin=True,
        ),
    )

    if output_html is None:
        output_html = os.path.join(
            os.path.dirname(csv_path),
            f"bmo_focus_dashboard_{window_days}d.html",
        )

    output_dir = os.path.dirname(output_html)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    plot_html = fig.to_html(
        full_html=False,
        include_plotlyjs=True,
        config={
            "displayModeBar": False,
            "responsive": False,
            "scrollZoom": False,
            "doubleClick": "reset",
        },
    )

    title_text = f"BMO Focus · {window_days}-Day View"

    full_page_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>BMO Focus Dashboard - {window_days}D</title>
    <meta name="viewport" content="width={s["screen_width"]}, height={s["screen_height"]}, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Pixelify+Sans:wght@400;700&display=swap" rel="stylesheet">
    <style>
        html, body {{
            margin: 0;
            padding: 0;
            width: {s["screen_width"]}px;
            height: {s["screen_height"]}px;
            overflow: hidden;
            background: {s["bg"]};
            color: {s["text"]};
            font-family: {s["font_family"]};
        }}

        #dashboard {{
            box-sizing: border-box;
            width: {s["screen_width"]}px;
            height: {s["screen_height"]}px;
            padding: {s["page_padding"]}px;
            background: {s["bg"]};
            display: grid;
            grid-template-rows: {s["title_height"]}px {s["cards_height"]}px {chart_outer_h}px;
            gap: {s["gap"]}px;
            font-family: {s["font_family"]};
        }}

        .title-box {{
            background: {s["card"]};
            border: {s["border_width"]}px solid {s["border"]};
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
            box-sizing: border-box;
            overflow: hidden;
            padding: 0 8px;
            font-size: {s["title_font_size"]}px;
            line-height: 1;
        }}

        .cards {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: {s["gap"]}px;
            width: 100%;
            height: 100%;
        }}

        .card {{
            background: {s["card"]};
            border: {s["border_width"]}px solid {s["border"]};
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            padding: 4px 6px;
        }}

        .card-title {{
            font-size: {s["card_title_font_size"]}px;
            line-height: 1.05;
            text-align: center;
            margin-bottom: 3px;
        }}

        .card-value {{
            font-size: {s["card_value_font_size"]}px;
            line-height: 1.05;
            text-align: center;
        }}

        .chart-box {{
            width: 100%;
            height: {chart_outer_h}px;
            background: {s["panel"]};
            border: {s["border_width"]}px solid {s["border"]};
            box-sizing: border-box;
            overflow: hidden;
            display: flex;
            align-items: stretch;
            justify-content: stretch;
        }}

        .chart-box > div {{
            width: 100% !important;
            height: 100% !important;
        }}

        .js-plotly-plot,
        .plot-container,
        .svg-container {{
            width: 100% !important;
            height: 100% !important;
        }}

        .js-plotly-plot .plotly .modebar {{
            display: none !important;
        }}
    </style>
</head>
<body>
    <div id="dashboard">
        <div class="title-box">{title_text}</div>

        <div class="cards">
            <div class="card">
                <div class="card-title">Study Time</div>
                <div class="card-value">{total_hours:.1f} h</div>
            </div>

            <div class="card">
                <div class="card-title">Now</div>
                <div class="card-value" style="color:{now_color};">{latest_focus:.1f}%</div>
            </div>

            <div class="card">
                <div class="card-title">{window_days}D Avg</div>
                <div class="card-value" style="color:{avg_color};">{latest_avg:.1f}%</div>
            </div>

            <div class="card">
                <div class="card-title">Sessions</div>
                <div class="card-value">{session_count}</div>
            </div>
        </div>

        <div class="chart-box">
            {plot_html}
        </div>
    </div>
</body>
</html>
"""

    with open(output_html, "w", encoding="utf-8") as f:
        f.write(full_page_html)

    print(f"Dashboard saved to: {output_html}")

    if auto_open:
        import webbrowser
        webbrowser.open(f"file://{output_html}")

    return fig


# Example
# plot_focus_dashboard_bmo_window(
#     csv_path="your_file.csv",
#     window_days=7,
#     output_html="bmo_focus_dashboard_7d.html",
#     auto_open=True,
# )