import csv #python built-in csv library
import os #work with other folders
import time # timing for study sessions
from collections import Counter #how may times an events happended
from dataclasses import dataclass, field #storing session data
from datetime import datetime #timestaamps for start and end time
from functools import lru_cache

import cv2 #drawing boxes and labels 

from picamera2 import MappedArray, Picamera2 #control camera and draw 
from picamera2.devices import IMX500
from picamera2.devices.imx500 import (
    NetworkIntrinsics, #setting of AI model
    postprocess_nanodet_detection, # model output -> detection boxes using NanoDet format
)

# global parameters of the camera to use in draw_detections()
last_detections = [] #store detections
last_results = None #store most recent detections
imx500 = None 
intrinsics = None #model settings
picam2 = None #camera controller


# ---------------------------
# Scoring rules
# ---------------------------
SCORE_FACE_OPEN = 100
SCORE_HEAD_DOWN = 50
SCORE_PHONE = 30
SCORE_FACE_CLOSED = 20
SCORE_NO_FACE = 0


@dataclass # class for storing data
class SessionAccumulator: # object that monitor the study session
    session_id: str # name of the section 
    start_time_iso: str # timestamp
    duration_minutes: int # session length
    model_path: str # path to AI model 

    total_frames: int = 0 # count how many frame processed
    score_sum: float = 0.0 # sum score across all frame
    primary_state_counts: Counter = field(default_factory=Counter) # each session gets a new counter
    # how many frames contains each label
    face_open_present_frames: int = 0 
    face_closed_present_frames: int = 0
    head_down_present_frames: int = 0
    phone_present_frames: int = 0
    no_face_frames: int = 0

    def add_frame(self, labels_present: set[str]) -> None:
        primary_state, score = evaluate_frame(labels_present) # get state and score for the frame from evaluate_frame()

        self.total_frames += 1 # add frame to totale frame
        self.score_sum += score # add score to total score
        self.primary_state_counts[primary_state] += 1 # count occurance for the state

        if "face+eye-opened" in labels_present:
            self.face_open_present_frames += 1
        if "face+eye-closed" in labels_present:
            self.face_closed_present_frames += 1
        if "head-down" in labels_present:
            self.head_down_present_frames += 1
        if "phone" in labels_present:
            self.phone_present_frames += 1
        if len(labels_present) == 0:
            self.no_face_frames += 1

    def finalize(self) -> dict: #dictionary for the summary 
        end_time_iso = datetime.now().isoformat(timespec="seconds") # get time when section ends
        average_score = self.score_sum / self.total_frames if self.total_frames else 0.0 # cal avg score 
        dominant_state = ( #find state with most occurance 
            self.primary_state_counts.most_common(1)[0][0]
            if self.primary_state_counts else "no_data"
        )
        duration_seconds = self.duration_minutes * 60 # min -> sec
        approx_fps = self.total_frames / duration_seconds if duration_seconds > 0 else 0.0 # cal fps

        def pct(n: int) -> float:
            return (100.0 * n / self.total_frames) if self.total_frames else 0.0

        return {
            "session_id": self.session_id,
            "start_time": self.start_time_iso,
            "end_time": end_time_iso,
            "duration_minutes": self.duration_minutes,
            "duration_seconds": duration_seconds,
            "model_path": self.model_path,
            "total_frames": self.total_frames,
            "approx_fps": round(approx_fps, 2),
            "average_score": round(average_score, 2),
            "dominant_state": dominant_state,
            "focused_frames": self.primary_state_counts.get("focused", 0),
            "eyes_closed_frames": self.primary_state_counts.get("eyes_closed", 0),
            "head_down_frames": self.primary_state_counts.get("head_down", 0),
            "phone_detected_frames": self.primary_state_counts.get("phone_detected", 0),
            "no_face_frames": self.primary_state_counts.get("no_face", 0),
            "face_open_present_frames": self.face_open_present_frames,
            "face_closed_present_frames": self.face_closed_present_frames,
            "head_down_present_frames": self.head_down_present_frames,
            "phone_present_frames": self.phone_present_frames,
            "focused_pct": round(pct(self.primary_state_counts.get("focused", 0)), 2),
            "eyes_closed_pct": round(pct(self.primary_state_counts.get("eyes_closed", 0)), 2),
            "head_down_pct": round(pct(self.primary_state_counts.get("head_down", 0)), 2),
            "phone_detected_pct": round(pct(self.primary_state_counts.get("phone_detected", 0)), 2),
            "no_face_pct": round(pct(self.primary_state_counts.get("no_face", 0)), 2),
        }


class Detection: # class to store detection
    def __init__(self, coords, category, conf, metadata): 
        self.category = category # class ID
        self.conf = conf # confidence score
        self.box = imx500.convert_inference_coords(coords, metadata, picam2) # box coordinates 


def evaluate_frame(labels_present: set[str]) -> tuple[str, int]: #return score and state
    """
    Priority:
    phone > face+eye-closed > head-down > face+eye-opened > no_face
    """
    if "phone" in labels_present:
        return "phone_detected", SCORE_PHONE
    if "face+eye-closed" in labels_present:
        return "eyes_closed", SCORE_FACE_CLOSED
    if "head-down" in labels_present:
        return "head_down", SCORE_HEAD_DOWN
    if "face+eye-opened" in labels_present:
        return "focused", SCORE_FACE_OPEN
    return "no_face", SCORE_NO_FACE


def validate_session_minutes(session_minutes: int) -> int: #session time only allow increments by 5
    if session_minutes < 5 or session_minutes % 5 != 0:
        raise ValueError("session_minutes must be 5, 10, 15, ...")
    return session_minutes


def ensure_summary_csv(csv_path: str) -> None:
    os.makedirs(os.path.dirname(csv_path), exist_ok=True) # csv exist and correct header

    if os.path.exists(csv_path):
        return

    fieldnames = [
        "session_id",
        "start_time",
        "end_time",
        "duration_minutes",
        "duration_seconds",
        "model_path",
        "total_frames",
        "approx_fps",
        "average_score",
        "dominant_state",
        "focused_frames",
        "eyes_closed_frames",
        "head_down_frames",
        "phone_detected_frames",
        "no_face_frames",
        "face_open_present_frames",
        "face_closed_present_frames",
        "head_down_present_frames",
        "phone_present_frames",
        "focused_pct",
        "eyes_closed_pct",
        "head_down_pct",
        "phone_detected_pct",
        "no_face_pct",
    ]

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader() # first row with column names


def append_summary_csv(csv_path: str, summary: dict) -> None: # add new sessions as new rows
    ensure_summary_csv(csv_path)
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary.keys()))
        writer.writerow(summary)


def parse_detections(metadata: dict, threshold: float, iou: float, max_detections: int): # filtering detections from model output
    global last_detections

    bbox_normalization = intrinsics.bbox_normalization
    bbox_order = intrinsics.bbox_order

    np_outputs = imx500.get_outputs(metadata, add_batch=True) #get outputs from model 
    _, input_h = imx500.get_input_size()

    if np_outputs is None:
        return last_detections

    if intrinsics.postprocess == "nanodet": # post-processing fro nanodet format 
        boxes, scores, classes = postprocess_nanodet_detection( 
            outputs=np_outputs[0],
            conf=threshold,
            iou_thres=iou,
            max_out_dets=max_detections,
        )[0]
        from picamera2.devices.imx500.postprocess import scale_boxes
        input_w, input_h = imx500.get_input_size()
        boxes = scale_boxes(boxes, 1, 1, input_h, input_w, False, False)
    else: # for non-nanodet format 
        boxes, scores, classes = np_outputs[0][0], np_outputs[1][0], np_outputs[2][0]

        if bbox_normalization:
            boxes = boxes / input_h

        if bbox_order == "xy": # reorder the box coordinates 
            boxes = boxes[:, [1, 0, 3, 2]]

    last_detections = [ # filtered list of detections 
        Detection(box, category, score, metadata)
        for box, score, category in zip(boxes, scores, classes)
        if score > threshold
    ]
    return last_detections


@lru_cache
def get_labels(): 
    labels = intrinsics.labels # extracted class names 
    if intrinsics.ignore_dash_labels:
        labels = [label for label in labels if label and label != "-"]
    return labels


def labels_present_from_detections(detections) -> set[str]: #??
    labels = get_labels()
    found = set()

    for detection in detections:
        cls_idx = int(detection.category)
        if 0 <= cls_idx < len(labels):
            found.add(str(labels[cls_idx])) # add detected class into found set 

    return found


def draw_detections(request, stream="main"):
    detections = last_results
    if detections is None:
        return

    labels = get_labels() 

    with MappedArray(request, stream) as m:
        for detection in detections:
            x, y, w, h = detection.box # get exact box coordinates
            label = f"{labels[int(detection.category)]} ({detection.conf:.2f})" # text class name + confidence for preview 

            (text_width, text_height), baseline = cv2.getTextSize(
                label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
            )
            text_x = x + 5
            text_y = y + 15

            overlay = m.array.copy()
            cv2.rectangle( # draw box
                overlay,
                (text_x, text_y - text_height),
                (text_x + text_width, text_y + baseline),
                (255, 255, 255),
                cv2.FILLED,
            )

            alpha = 0.30
            cv2.addWeighted(overlay, alpha, m.array, 1 - alpha, 0, m.array)

            cv2.putText(
                m.array,
                label,
                (text_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 255),
                1,
            )

            cv2.rectangle(
                m.array,
                (x, y),
                (x + w, y + h),
                (0, 255, 0, 0),
                thickness=2,
            )

        if intrinsics.preserve_aspect_ratio:
            b_x, b_y, b_w, b_h = imx500.get_roi_scaled(request) #get ROI 
            color = (255, 0, 0)
            cv2.putText(
                m.array,
                "ROI",
                (b_x + 5, b_y + 15),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                1,
            )
            cv2.rectangle(
                m.array,
                (b_x, b_y),
                (b_x + b_w, b_y + b_h),
                (255, 0, 0, 0),
            )


def run_study_session( #calling function and variables need to be declared  
    model_path: str,
    labels_path: str | None,
    session_minutes: int = 5,
    threshold: float = 0.01,
    iou: float = 0.65,
    max_detections: int = 10,
    bbox_normalization: bool = True,
    bbox_order: str = "xy",
    preserve_aspect_ratio: bool = True,
    summary_csv: str = "",
    enable_study_ai: bool = True,
    fps: int | None = None,
) -> dict | None:
    global imx500, intrinsics, picam2, last_results

    if not enable_study_ai:
        print("Study AI disabled. Exiting without running.")
        return None

    validate_session_minutes(session_minutes)

    imx500 = IMX500(model_path)
    intrinsics = imx500.network_intrinsics

    if not intrinsics:
        intrinsics = NetworkIntrinsics()
        intrinsics.task = "object detection"
    elif intrinsics.task != "object detection":
        raise RuntimeError("Network is not an object detection task")

    intrinsics.bbox_normalization = bbox_normalization
    intrinsics.bbox_order = bbox_order
    intrinsics.preserve_aspect_ratio = preserve_aspect_ratio

    if labels_path is not None:
        with open(labels_path, "r") as f:
            intrinsics.labels = f.read().splitlines()

    if intrinsics.labels is None:
        raise ValueError("No labels available. Please provide labels_path.")

    intrinsics.update_with_defaults()

    picam2 = Picamera2(imx500.camera_num)

    frame_rate = fps if fps is not None else intrinsics.inference_rate
    config = picam2.create_preview_configuration(
        controls={"FrameRate": frame_rate},
        buffer_count=6,
    )

    imx500.show_network_fw_progress_bar()
    picam2.start(config, show_preview=True)

    if intrinsics.preserve_aspect_ratio:
        imx500.set_auto_aspect_ratio()

    session = SessionAccumulator(
        session_id=datetime.now().strftime("study_%Y%m%d_%H%M%S"),
        start_time_iso=datetime.now().isoformat(timespec="seconds"),
        duration_minutes=session_minutes,
        model_path=model_path,
    )

    session_end_time = time.monotonic() + session_minutes * 60
    last_results = None
    picam2.pre_callback = draw_detections

    try:
        while True:
            last_results = parse_detections(
                picam2.capture_metadata(),
                threshold=threshold,
                iou=iou,
                max_detections=max_detections,
            )

            labels_present = labels_present_from_detections(last_results)
            session.add_frame(labels_present)

            if time.monotonic() >= session_end_time:
                summary = session.finalize()
                append_summary_csv(summary_csv, summary)
                print("\nStudy session finished")
                print(summary)
                return summary

    except KeyboardInterrupt:
        print("\nInterrupted by user. Writing partial summary...")
        summary = session.finalize()
        append_summary_csv(summary_csv, summary)
        print(summary)
        return summary

    finally:
        picam2.stop()
