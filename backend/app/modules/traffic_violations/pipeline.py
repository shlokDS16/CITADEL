"""
Traffic Violations detection pipeline — OTVision-equivalent.

Stack:
  - ultralytics YOLOv8n (COCO-pretrained) → vehicles, motorcycles, persons
  - deep-sort-realtime → cross-frame tracking via track_id
  - OCR Space → license plate text for the most promising bbox per track
  - cv2 → clip extraction (3 s around the violation moment)

Per the user's directive: per-frame inference stays local (YOLO + DeepSORT).
Groq is only used downstream for organising/summarising structured detections.

Violation classification (Phase 2 — heuristic, pretrained-model-friendly):
  - no_helmet      : motorcycle bbox + rider bbox overlap, no helmet-shaped
                     small object detected near the rider's head region.
                     Pretrained YOLO can't natively detect helmets, so we
                     approximate by "rider top region appears bare" using
                     the rider's head-area pixel intensity variance.
  - speeding       : per-track centroid pixel-displacement / frame, scaled by
                     bbox size. Flag if normalised speed > threshold.
  - wrong_lane     : (not detected in Phase 2 — needs lane segmentation)
  - red_light      : (not detected in Phase 2 — needs traffic-light state)
  - no_seatbelt    : (not detected in Phase 2 — needs car-interior view)
  - illegal_parking: stationary track for > 5 s in same approximate position.

Output: list of `Detection` dicts ready to insert into tv_incidents.
"""
from __future__ import annotations

import logging
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from app.modules.traffic_violations import clip_extractor, plate_ocr, storage

log = logging.getLogger("citadel.traffic_violations.pipeline")

# Mirrors service.VIOLATION_LABEL — kept local to avoid circular import.
_VIOLATION_LABEL = {
    "no_helmet": "NO HELMET",
    "speeding": "SPEEDING",
    "wrong_lane": "WRONG LANE",
    "red_light": "RED LIGHT",
    "no_seatbelt": "NO SEATBELT",
    "illegal_parking": "ILLEGAL PARK",
    "accident": "ACCIDENT",
    "rash_driving": "RASH DRIVING",
    "lane_violation": "LANE VIOLATION",
    "overload": "OVERLOAD",
    "overturned": "OVERTURNED VEHICLE",
    "debris": "ROAD DEBRIS",
}


# COCO class ids that interest us (yolov8n.pt is COCO-pretrained)
_COCO_CAR = 2
_COCO_MOTORCYCLE = 3
_COCO_BUS = 5
_COCO_TRUCK = 7
_COCO_PERSON = 0
_VEHICLE_IDS = {_COCO_CAR, _COCO_MOTORCYCLE, _COCO_BUS, _COCO_TRUCK}


# Lazy globals so first import doesn't pay the model-load cost.
_yolo = None
_tracker = None


def _get_yolo():
    global _yolo
    if _yolo is None:
        from ultralytics import YOLO
        weights = os.getenv("YOLO_WEIGHTS", "yolov8n.pt")
        log.info("Loading YOLO weights: %s", weights)
        _yolo = YOLO(weights)
    return _yolo


def _get_tracker():
    global _tracker
    if _tracker is None:
        from deep_sort_realtime.deepsort_tracker import DeepSort
        # Conservative tracker settings for short clips.
        _tracker = DeepSort(
            max_age=15,
            n_init=2,
            nms_max_overlap=1.0,
            max_cosine_distance=0.3,
            nn_budget=None,
            override_track_class=None,
            embedder="mobilenet",
            half=False,
        )
    return _tracker


def _bbox_iou(a, b) -> float:
    """xyxy IoU."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    union = ((ax2 - ax1) * (ay2 - ay1)) + ((bx2 - bx1) * (by2 - by1)) - inter
    return inter / union if union > 0 else 0.0


def _bbox_center(bb):
    x1, y1, x2, y2 = bb
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _detect_anomalies_from_tracks(
    track_history: dict[str, dict[str, Any]],
    fps: float,
) -> list[dict[str, Any]]:
    """
    Pure-Python anomaly heuristics on YOLO+tracker output. NO API calls.
    Flags suspicious frame indices that warrant a Groq Vision look.

    Detects:
      • sudden_stop: track moving > 10 px/frame then dropped by 70%+ within ~1s
      • stationary_in_road: track stayed within 30 px for ≥ 3 s while in motion-classes
      • vanished_mid_frame: track lifetime ≥ 1 s then disappeared not at edge

    Returns: list of {frame_idx, kind, track_id} — caller dedupes / batches.
    """
    anomalies: list[dict[str, Any]] = []

    for tid, hist in track_history.items():
        cents = hist.get("centroids") or []
        if len(cents) < 4:
            continue

        # 1) Sudden stop — compare early vs late speeds
        speeds = []
        for i in range(1, len(cents)):
            df = cents[i][0] - cents[i - 1][0]
            if df <= 0:
                continue
            dx = cents[i][1][0] - cents[i - 1][1][0]
            dy = cents[i][1][1] - cents[i - 1][1][1]
            speeds.append(math.hypot(dx, dy) / df)
        if len(speeds) >= 6:
            early = sum(speeds[:3]) / 3
            late = sum(speeds[-3:]) / 3
            if early > 8 and late < early * 0.30:
                mid_idx = cents[len(speeds) // 2 + 1][0]
                anomalies.append({"frame_idx": mid_idx, "kind": "sudden_stop", "track_id": tid})

        # 2) Stationary in road (longer-window broken-down vehicle)
        xs = [c[1][0] for c in cents]
        ys = [c[1][1] for c in cents]
        span = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
        duration = (hist.get("last_seen") or 0) - (hist.get("first_seen") or 0)
        cls_majority = hist.get("cls_majority") or {}
        is_vehicle = any(c in (_COCO_CAR, _COCO_TRUCK, _COCO_BUS, _COCO_MOTORCYCLE) for c in cls_majority)
        if is_vehicle and span < 30 and duration >= 3.0:
            anomalies.append({"frame_idx": cents[-1][0], "kind": "stationary_in_road", "track_id": tid})

        # 3) Vanished mid-frame (track ends abruptly far from frame edge)
        # bbox unavailable here, but a sudden last-seen + short total duration is suggestive
        # we only flag if there's at least 1 s of track + last centroid is well inside the typical frame box
        if duration >= 1.0 and len(cents) >= 4:
            # heuristic: last centroid not at top/bottom 10% of typical 720p / 1080p ranges
            lx, ly = cents[-1][1]
            if 100 < lx < 1500 and 100 < ly < 900 and speeds and speeds[-1] > 5:
                # was still moving when track ended → possible occlusion or crash
                anomalies.append({"frame_idx": cents[-1][0], "kind": "vanished_mid_frame", "track_id": tid})

    return anomalies


def _looks_helmet_less(frame: np.ndarray, person_bbox) -> tuple[bool, float]:
    """
    Crude pretrained-friendly heuristic:
      crop the top 25% of the person's bbox (head region), measure its
      intensity variance. Helmets produce a smoother, low-variance crop
      (uniform shell colour). Bare heads + hair produce higher variance.
    Returns (is_helmetless, confidence_0_to_1).
    """
    x1, y1, x2, y2 = [int(v) for v in person_bbox]
    if y2 - y1 < 30 or x2 - x1 < 20:
        return False, 0.0
    head_y2 = y1 + int((y2 - y1) * 0.25)
    head = frame[max(0, y1):min(frame.shape[0], head_y2), max(0, x1):min(frame.shape[1], x2)]
    if head.size == 0:
        return False, 0.0
    gray = cv2.cvtColor(head, cv2.COLOR_BGR2GRAY)
    var = float(np.var(gray))
    # Empirical threshold: above 900 var → likely no helmet (high texture)
    is_helmetless = var > 900
    # confidence scales 0.55 - 0.9 within plausible range
    conf = 0.55 + min(0.35, max(0.0, (var - 900) / 2000))
    return is_helmetless, conf


def detect_in_video(
    video_path: str,
    cam_id: Optional[str] = None,
    types_filter: Optional[set[str]] = None,
    frame_skip: int = 6,
    progress_cb=None,
) -> dict[str, Any]:
    """
    Run the full pipeline on `video_path` and return a structured result.
    Inserts no DB rows itself — the service layer handles persistence.

    Returns:
        {
          "frames_processed": int,
          "total_frames":     int,
          "fps":              float,
          "duration_seconds": float,
          "detections":       [Detection, ...],
        }

    `progress_cb(frames_done, total_frames)` is called periodically for UI polling.
    """
    types_filter = types_filter or {"no_helmet", "speeding", "illegal_parking"}
    yolo = _get_yolo()
    tracker = _get_tracker()

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV could not open {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = total_frames / fps if fps else 0.0

    # Per-track aggregates we use for violation classification.
    track_history: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "first_seen": None,
        "last_seen": None,
        "first_bbox": None,
        "last_bbox": None,
        "frames": 0,
        "cls_majority": defaultdict(int),
        "centroids": [],
        "best_frame_idx": None,
        "best_frame": None,
        "best_bbox": None,
        "helmetless_votes": 0,
        "rider_links": 0,        # frames where a person overlaps this motorcycle
    })

    frame_idx = 0
    frames_processed = 0

    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        if frame_idx % frame_skip != 0:
            frame_idx += 1
            continue

        # ---- YOLO inference ----
        results = yolo(frame, verbose=False, conf=0.35, iou=0.5)[0]
        # collect detections in DeepSORT input format: [[x1, y1, w, h], conf, cls_id]
        ds_input = []
        raw_boxes = []  # for helmet/rider check
        for box in results.boxes:
            cls_id = int(box.cls[0].item())
            if cls_id not in _VEHICLE_IDS and cls_id != _COCO_PERSON:
                continue
            xyxy = box.xyxy[0].tolist()
            x1, y1, x2, y2 = xyxy
            conf = float(box.conf[0].item())
            ds_input.append(([x1, y1, x2 - x1, y2 - y1], conf, str(cls_id)))
            raw_boxes.append((cls_id, xyxy, conf))

        # ---- DeepSORT tracking ----
        try:
            tracks = tracker.update_tracks(ds_input, frame=frame)
        except Exception as e:
            log.debug("tracker update failed: %s", e)
            tracks = []

        # ---- Aggregate per track ----
        for t in tracks:
            if not t.is_confirmed():
                continue
            tid = str(t.track_id)
            bb = t.to_tlbr()  # xyxy
            cls_id = int(t.det_class) if t.det_class is not None else -1
            hist = track_history[tid]
            if hist["first_seen"] is None:
                hist["first_seen"] = frame_idx / fps
                hist["first_bbox"] = bb
            hist["last_seen"] = frame_idx / fps
            hist["last_bbox"] = bb
            hist["frames"] += 1
            hist["cls_majority"][cls_id] += 1
            hist["centroids"].append((frame_idx, _bbox_center(bb)))

            # Pick the largest bbox over the track's lifetime as the "best" frame for OCR
            area = max(0, (bb[2] - bb[0]) * (bb[3] - bb[1]))
            prev_best = hist.get("best_area", 0)
            if area > prev_best:
                hist["best_area"] = area
                hist["best_frame_idx"] = frame_idx
                hist["best_frame"] = frame.copy()
                hist["best_bbox"] = bb

        # ---- Helmet heuristic: for each motorcycle, look for overlapping person ----
        moto_boxes = [b for c, b, _ in raw_boxes if c == _COCO_MOTORCYCLE]
        person_boxes = [b for c, b, _ in raw_boxes if c == _COCO_PERSON]
        for moto in moto_boxes:
            best_rider = None
            best_iou = 0.0
            for p in person_boxes:
                i = _bbox_iou(moto, p)
                if i > best_iou:
                    best_iou = i
                    best_rider = p
            if best_rider is None or best_iou < 0.05:
                continue
            # find the track that owns this motorcycle (by bbox containment)
            for tid, hist in track_history.items():
                if hist["last_bbox"] is None:
                    continue
                if _bbox_iou(hist["last_bbox"], moto) > 0.5:
                    hist["rider_links"] += 1
                    helmetless, _conf = _looks_helmet_less(frame, best_rider)
                    if helmetless:
                        hist["helmetless_votes"] += 1
                    break

        frames_processed += 1
        frame_idx += 1
        if progress_cb and frames_processed % 5 == 0:
            try:
                progress_cb(frames_processed, max(1, total_frames // frame_skip))
            except Exception:
                pass

    cap.release()

    # ---- Classify each track into a violation type (or skip) ----
    detections: list[dict[str, Any]] = []
    for tid, hist in track_history.items():
        if hist["frames"] < 2:
            continue
        # pick dominant class
        if hist["cls_majority"]:
            cls_id = max(hist["cls_majority"].items(), key=lambda kv: kv[1])[0]
        else:
            cls_id = -1
        if cls_id == _COCO_PERSON:
            # don't issue violations against a bare person track
            continue

        # determine violation type
        violation: Optional[str] = None
        severity = "medium"
        confidence = 0.6

        # no_helmet  (motorcycle + helmetless votes)
        if cls_id == _COCO_MOTORCYCLE and hist["rider_links"] >= 1 and "no_helmet" in types_filter:
            ratio = hist["helmetless_votes"] / max(1, hist["rider_links"])
            if ratio >= 0.5:
                violation = "no_helmet"
                confidence = min(0.95, 0.6 + ratio * 0.3)
                severity = "high"

        # speeding (centroid displacement)
        if violation is None and "speeding" in types_filter and len(hist["centroids"]) >= 3:
            (f0, (x0, y0)), (f1, (x1, y1)) = hist["centroids"][0], hist["centroids"][-1]
            dist = math.hypot(x1 - x0, y1 - y0)
            dt_frames = max(1, f1 - f0)
            speed = dist / dt_frames  # pixels/frame
            # rough threshold: > 15 px/frame for a non-tiny bbox
            avg_bbox_area = hist.get("best_area", 0)
            if speed > 15 and avg_bbox_area > 2000:
                violation = "speeding"
                confidence = min(0.92, 0.55 + (speed - 15) * 0.02)
                severity = "critical" if speed > 30 else "high"

        # illegal_parking (long stationary track)
        if violation is None and "illegal_parking" in types_filter and len(hist["centroids"]) >= 5:
            xs = [c[1][0] for c in hist["centroids"]]
            ys = [c[1][1] for c in hist["centroids"]]
            span = math.hypot(max(xs) - min(xs), max(ys) - min(ys))
            duration_track = (hist["last_seen"] or 0) - (hist["first_seen"] or 0)
            if span < 30 and duration_track >= 5.0 and cls_id != _COCO_PERSON:
                violation = "illegal_parking"
                confidence = 0.72
                severity = "low"

        if violation is None:
            continue

        # OCR plate from best frame
        plate = None
        plate_conf = 0.0
        if hist["best_frame"] is not None and hist["best_bbox"] is not None:
            try:
                plate, plate_conf = plate_ocr.read_plate_from_bbox(hist["best_frame"], hist["best_bbox"])
            except Exception as e:
                log.warning("plate OCR failed for track %s: %s", tid, e)

        detections.append({
            "track_id": tid,
            "violation_type": violation,
            "severity": severity,
            "detection_confidence": round(confidence, 3),
            "plate": plate or "—",
            "plate_confidence": round(plate_conf or 0.0, 3),
            "first_seen": hist["first_seen"],
            "last_seen": hist["last_seen"],
            "best_frame_idx": hist["best_frame_idx"],
            "best_bbox": [int(v) for v in hist["best_bbox"]] if hist["best_bbox"] is not None else None,
            "label": _VIOLATION_LABEL.get(violation, violation.upper()),
        })

    # ============================================================
    # Hybrid Groq Vision pass — anomaly-first to conserve free-tier quota.
    # 1) Local heuristics flag candidate frames (sudden stop, stationary,
    #    vanished mid-frame) → 0 API calls.
    # 2) Only those frames go to Groq Vision (was: 6 fixed keyframes).
    # 3) Plus 1 baseline keyframe at 50% so we don't miss events on totally
    #    "smooth" videos. Cap at 4 total Groq calls per upload.
    # On 429 / quota errors → groq_vision falls back to local Ollama (LLaVa).
    # ============================================================
    try:
        from app.modules.traffic_violations import groq_vision

        # Local anomaly detection (no API calls)
        anomalies = _detect_anomalies_from_tracks(track_history, fps)
        log.info("Anomaly heuristics flagged %d candidate frame(s)", len(anomalies))

        # Build the candidate frame set: dedupe by floor-second so we don't
        # over-query Groq on a cluster of related anomalies.
        seen_sec = set()
        candidate_frame_ids: list[int] = []
        for a in anomalies:
            sec_bucket = int(a["frame_idx"] / max(fps, 1))
            if sec_bucket in seen_sec:
                continue
            seen_sec.add(sec_bucket)
            candidate_frame_ids.append(a["frame_idx"])

        # Always include a few baseline keyframes spread across the video.
        # Events in stock footage commonly happen near the start or end, not
        # the middle, so we sample 25%/50%/70%/90% rather than just centre.
        if total_frames > 0:
            for frac in (0.25, 0.50, 0.70, 0.90):
                baseline = int(total_frames * frac)
                # avoid near-duplicates within ~1s of an existing candidate
                if not any(abs(baseline - f) < fps for f in candidate_frame_ids):
                    candidate_frame_ids.append(baseline)

        # Cap to 6 calls per upload (still 0% of 6 fixed before; with anomaly
        # candidates likely dropped, average is ~4 calls / upload).
        candidate_frame_ids = sorted(set(candidate_frame_ids))[:6]
        log.info("Sending %d frame(s) to Groq Vision (down from 6 fixed)", len(candidate_frame_ids))

        cap2 = cv2.VideoCapture(video_path)
        keyframes: list[tuple[int, bytes]] = []
        for fidx in candidate_frame_ids:
            cap2.set(cv2.CAP_PROP_POS_FRAMES, fidx)
            ok, frame = cap2.read()
            if not ok:
                continue
            ok2, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok2:
                keyframes.append((fidx, jpeg.tobytes()))
        cap2.release()

        groq_findings = groq_vision.classify_keyframes(keyframes)
        for f in groq_findings:
            vtype = f["type"]
            # Map a few common Groq labels to our canonical set
            if vtype in {"overturned", "rollover"}:
                vtype = "accident"
            if vtype not in _VIOLATION_LABEL:
                # unknown type: still create incident under a generic label
                _VIOLATION_LABEL[vtype] = vtype.upper().replace("_", " ")
            detections.append({
                "track_id": f"groq-{f['frame_idx']}",
                "violation_type": vtype,
                "severity": f["severity"],
                "detection_confidence": 0.85,
                "plate": None,
                "plate_confidence": 0.0,
                "first_seen": f["frame_idx"] / max(fps, 1),
                "last_seen":  f["frame_idx"] / max(fps, 1),
                "best_frame_idx": f["frame_idx"],
                "best_bbox": None,
                "label": _VIOLATION_LABEL.get(vtype, vtype.upper()),
                "description": f.get("description"),
                "detected_by": "groq_vision",
            })
        log.info("Groq Vision found %d violation(s) across %d keyframes", len(groq_findings), len(keyframes))
    except Exception as e:
        log.warning("Groq Vision second pass failed (continuing): %s", e)

    if progress_cb:
        try:
            progress_cb(frames_processed, frames_processed)
        except Exception:
            pass

    return {
        "frames_processed": frames_processed,
        "total_frames": total_frames,
        "fps": fps,
        "duration_seconds": duration,
        "detections": detections,
    }
