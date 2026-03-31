from focus_dashboard import plot_focus_dashboard_bmo_window
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, "logs", "study_session_summary.csv")
HTML_PATH = os.path.join(BASE_DIR, "logs", "bmo_focus_dashboard_7d.html")

plot_focus_dashboard_bmo_window(
    csv_path=CSV_PATH,
    window_days=7,
    output_html=HTML_PATH,
    auto_open=False,
)