import argparse
from study_session_core import run_study_session


def get_args():
    parser = argparse.ArgumentParser()

    parser.add_argument("--model", required=True, help="Path to .rpk model")
    parser.add_argument("--labels", default=None, help="Path to labels.txt")
    parser.add_argument("--session-minutes", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=0.01)
    parser.add_argument("--iou", type=float, default=0.65)
    parser.add_argument("--max-detections", type=int, default=10)
    parser.add_argument("--bbox-normalization", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--bbox-order", choices=["yx", "xy"], default="xy")
    parser.add_argument("-r", "--preserve-aspect-ratio", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--summary-csv",
        default="/home/chuoidawy/study_focus_imx500/logs/study_session_summary.csv",
    )
    parser.add_argument("--enable-study-ai", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--fps", type=int, default=None)

    return parser.parse_args()


if __name__ == "__main__":
    args = get_args()

    summary = run_study_session(
        model_path=args.model,
        labels_path=args.labels,
        session_minutes=args.session_minutes,
        threshold=args.threshold,
        iou=args.iou,
        max_detections=args.max_detections,
        bbox_normalization=args.bbox_normalization,
        bbox_order=args.bbox_order,
        preserve_aspect_ratio=args.preserve_aspect_ratio,
        summary_csv=args.summary_csv,
        enable_study_ai=args.enable_study_ai,
        fps=args.fps,
    )

    print(summary)
