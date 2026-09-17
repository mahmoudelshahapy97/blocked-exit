I searched specifically for **computer vision repositories and datasets** related to **blocked emergency exits / door obstruction detection**.

The result is that **there is no mature open-source repository that directly solves this problem end-to-end**. Most published work is very recent (2025–2026), so you'll need to build the solution by combining existing CV repositories.

## 1. The Most Important Paper ⭐⭐⭐⭐⭐

**Real Time Exit Blockage Detection via Door-Centric Change Monitoring for Emergency Evacuation (ICAART 2026)**

This is currently the closest research to your project. It proposes detecting **the visible area of the door** instead of recognizing every possible obstacle. It uses **YOLOv11s** and measures the percentage of the door that remains accessible. 

This paper should be your primary reference.

---

# 2. Best Repositories

## A. Ultralytics YOLO (Recommended)

Repository

* [Ultralytics YOLO](https://github.com/ultralytics/ultralytics?utm_source=chatgpt.com)

Why use it

* Detection
* Segmentation
* Tracking
* Pose
* Easy training
* Production-ready

Supports

* YOLO11
* YOLO26
* Segmentation
* ByteTrack integration
* ONNX
* TensorRT
* OpenVINO ([GitHub][1])

---

## B. Official YOLOv9 Repository

Repository

* [YOLOv9 Official Repository](https://github.com/MultimediaTechLab/YOLO?utm_source=chatgpt.com)

Useful if you want to reproduce research papers or compare with YOLO11. ([GitHub][2])

---

## C. Segment Anything (SAM2)

Repository

* [Segment Anything 2 (SAM2)](https://github.com/facebookresearch/sam2?utm_source=chatgpt.com)

Use it to

* Segment the exit door
* Segment obstacles
* Calculate occupied area

---

## D. ByteTrack

Repository

* [ByteTrack](https://github.com/ifzhang/ByteTrack?utm_source=chatgpt.com)

Use it to

* Track people
* Track carts
* Ignore people walking past
* Trigger alarms only for persistent blockages

---

## E. Supervision

Repository

* [Supervision by Roboflow](https://github.com/roboflow/supervision?utm_source=chatgpt.com)

Very useful for

* Drawing zones
* Polygon overlap
* Tracking visualization
* Analytics

---

# 3. Repositories You Can Reuse (Partial Solutions)

Although none solve blocked exits directly, these projects implement similar techniques:

| Repository  | Reusable Component                        |
| ----------- | ----------------------------------------- |
| Ultralytics | Detection + Segmentation                  |
| ByteTrack   | Multi-object tracking                     |
| SAM2        | Door segmentation                         |
| Supervision | Polygon occupancy and analytics           |
| OpenCV      | Background subtraction and ROI processing |

---

# 4. Datasets

### Existing blocked emergency exit dataset

A small dataset (52 images) already exists and can be used as a starting point:

* Blocked Emergency Exit Dataset (Roboflow) ([Roboflow][3])

---

### Emergency Exit Signs Dataset

Useful for detecting exit signs before analyzing the exit itself.

* Emergency Exit Signs Dataset (Roboflow) ([Roboflow][4])

---

# 5. Repository Architecture I Recommend

```text
Blocked-Exit-AI/
│
├── detection/
│   ├── YOLO11
│   ├── Door Detector
│   └── Obstacle Detector
│
├── segmentation/
│   ├── SAM2
│   └── YOLO11-seg
│
├── tracking/
│   └── ByteTrack
│
├── reasoning/
│   ├── Occupancy Calculator
│   ├── Accessibility Score
│   └── Risk Score
│
├── alert/
│   ├── Email
│   ├── MQTT
│   └── Dashboard
│
└── backend/
    ├── FastAPI
    ├── PostgreSQL
    └── Redis
```

---

# 6. Novel Features to Make It Research-Level

Instead of outputting only:

```
Blocked
```

your system could produce:

```json
{
  "door_visible": 27.5,
  "blocked": true,
  "blocking_objects": [
    "person",
    "cart"
  ],
  "risk_level": "HIGH",
  "blocked_duration": 18.2,
  "recommended_action": "Clear Exit Immediately"
}
```

You can also add:

* Accessibility percentage (0–100%)
* Partial vs. full blockage classification
* Temporal persistence (ignore brief occlusions)
* Multi-camera fusion
* Heatmaps of frequently blocked exits
* Automatic incident reports
* Explainable AI overlays showing exactly why the exit is considered blocked

## My recommendation

Given your experience with **YOLO, FastAPI, Docker, and AI systems**, I would build this as a **hybrid vision pipeline** rather than a simple object detector:

1. **YOLO11/YOLO26** → detect doors and obstacles.
2. **SAM2 or YOLO11-seg** → estimate the exact visible door area.
3. **ByteTrack** → ensure obstacles persist before raising an alert.
4. **Occupancy analysis** → compute accessibility percentage.
5. **Rule engine** → classify the exit as Clear, Partially Blocked, or Fully Blocked.
6. **FastAPI + React dashboard** → monitor multiple cameras and generate alerts.

This would be a strong foundation for both an academic research project and a production-ready safety monitoring system.

[1]: https://github.com/ultralytics/ultralytics?utm_source=chatgpt.com "GitHub - ultralytics/ultralytics: Ultralytics YOLO 🚀 · GitHub"
[2]: https://github.com/MultimediaTechLab/YOLO?utm_source=chatgpt.com "GitHub - MultimediaTechLab/YOLO: An MIT License of YOLOv9, YOLOv7, YOLO-RD · GitHub"
[3]: https://universe.roboflow.com/yolodata-sovyh/blocked-emergency-exit-f6a2h-9fl9h?utm_source=chatgpt.com "blocked emergency exit Object Detection Dataset by yolodata"
[4]: https://universe.roboflow.com/anshuls-workspace-mipan/emergency-exit-signs-v2-rppdf/dataset/1?utm_source=chatgpt.com "Emergency Exit Signs v2 Object Detection Model (v1, 2026-04-03 3:15pm) by Anshuls Workspace"
