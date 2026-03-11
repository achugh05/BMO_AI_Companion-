from study_session_core import run_study_session

summary = run_study_session(
    model_path="/home/chuoidawy/study_focus_imx500/models/focus_v4/network.rpk",
    labels_path="/home/chuoidawy/study_focus_imx500/models/focus_v4/labels.txt",
    session_minutes=5,
    threshold=0.01,
    bbox_normalization=True,
    bbox_order="xy",
    preserve_aspect_ratio=True,
    summary_csv="/home/chuoidawy/study_focus_imx500/logs/study_session_summary.csv",
)

print(summary)
