After searching the latest research, I think there is a much better direction than simply building a "detect objects in front of a door" system.

The newest research is moving toward **door-centric scene understanding**, where the model learns the normal appearance of each exit and detects any change that reduces accessibility, instead of trying to recognize every possible obstacle. This is more robust because you don't need to train on every object that could block an exit. ([ScitePress][1])

# Latest Research Trends (2025–2026)

## 1. Door-Centric Change Detection ⭐⭐⭐⭐⭐ (Best)

This is currently the most promising approach.

Instead of:

```
Detect person
Detect chair
Detect box
...
```

the system does

```
Learn the normal door

↓

Compare current frame

↓

Estimate visible door area

↓

Blocked or Not Blocked
```

Advantages:

* Works with unseen objects
* Better generalization
* Less annotation effort
* Suitable for edge devices
* Lower false positives

The recent ICAART 2026 paper used **YOLOv11s** to monitor the visible door region rather than catalog every obstacle, and demonstrated deployment on a Raspberry Pi. ([ScitePress][1])

---

## 2. Instance Segmentation

Instead of bounding boxes:

```
□□□□
 Chair
```

use pixel-level masks.

Models:

* YOLO11-seg
* SAM2
* MobileSAM
* Mask R-CNN

Benefits

* Exact occupied area
* Better overlap calculation
* More accurate blockage percentage

This is especially valuable when only part of an exit is obstructed. ([ScienceDirect][2])

---

## 3. Multi-Object Tracking

Instead of processing every frame independently:

```
Frame 1

Person #5

↓

Frame 50

Still Person #5
```

Models

* ByteTrack
* BoT-SORT
* DeepSORT

Benefits

* Ignore temporary passersby
* Track persistent obstacles
* Reduce false alarms

---

## 4. State Classification

Rather than predicting only:

```
Blocked
```

predict multiple states:

```
Clear

↓

Partially Blocked

↓

Fully Blocked

↓

Emergency
```

This is more useful for facility management.

---

## 5. Accessibility Percentage

Rather than a binary output:

```
Blocked
```

estimate:

```
Accessible

87%
```

or

```
Door visible

35%
```

The 2026 door-centric work evaluates accessible door area directly. ([ScitePress][1])

---

# Models I Recommend

| Task                      | Best Model                                                                    |
| ------------------------- | ----------------------------------------------------------------------------- |
| Object Detection          | YOLO11                                                                        |
| Segmentation              | YOLO11-seg                                                                    |
| Zero-shot Segmentation    | SAM2                                                                          |
| Object Tracking           | ByteTrack                                                                     |
| Pose Estimation           | YOLO11-pose                                                                   |
| OCR (Exit Signs)          | PaddleOCR                                                                     |
| Scene Understanding       | Florence-2 or Qwen2.5-VL                                                      |
| Vision-Language Reasoning | Qwen2.5-VL / GPT-4.1 Vision / GPT-5 Vision (if available in your environment) |

---

# New Features You Can Add

## 1. Blockage Percentage

```
Door

82% visible
```

instead of

```
Blocked
```

---

## 2. Explain Why

Instead of

```
Blocked
```

return

```
Blocked by

2 people

1 cart

1 box
```

---

## 3. Heatmap

Generate

```
Most blocked exits

this week
```

Useful for management dashboards.

---

## 4. Risk Score

```
Risk

94/100
```

computed from:

* obstacle size
* blockage duration
* people nearby
* smoke/fire presence
* evacuation priority

---

## 5. Predictive Alert

Instead of waiting until the exit is blocked:

```
Cart moving

↓

Near exit

↓

Warning
```

using object tracking and trajectory prediction.

---

## 6. Multi-Camera Fusion

If multiple cameras monitor one corridor:

```
Camera 1

↓

Camera 2

↓

One decision
```

---

## 7. Digital Twin

Display a building map:

```
Floor 1

Exit A ✔

Exit B ❌

Exit C ⚠
```

---

## 8. Smart Notifications

Only send alerts if:

```
Blocked

>

10 sec
```

instead of every frame.

---

## 9. Automatic Report Generation

Every day generate:

```
Exit 1

Blocked

12 times

Average

4 min
```

---

## 10. Explainable AI

Display:

* detected obstacle
* occupied area
* confidence
* reason for alarm

---

# Advanced AI Pipeline (Recommended)

```text
RTSP Camera
      │
      ▼
Frame Extraction
      │
      ▼
YOLO11 Detection
      │
      ▼
YOLO11-Seg / SAM2
      │
      ▼
ByteTrack
      │
      ▼
Door Polygon Detection
      │
      ▼
Occupancy Analysis
      │
      ▼
Accessibility %
      │
      ▼
Temporal Filter
      │
      ▼
Risk Scoring
      │
      ▼
Alert Service
      │
      ▼
Dashboard
```

---

# Research Papers Worth Reading

1. **Real Time Exit Blockage Detection via Door-Centric Change Monitoring for Emergency Evacuation (2026)** — Introduces a door-centric change-detection framework using YOLOv11s and accessible-door-area estimation. ([ScitePress][1])

2. **Improving Object Classification Accuracy for Detecting Obstacles on Indoor Evacuation Paths Using YOLOv8 (2025)** — Focuses on obstacle detection and evacuation-path analysis in indoor environments. ([kieae.kr][3])

3. **Real-time Semi-Occluded Fire Detection and Evacuation Route Generation (2025)** — Combines fire detection with evacuation planning using instance segmentation. ([ScienceDirect][2])

4. **Fast Highway Abandoned Object Detection (2025)** — Useful for understanding persistent obstacle detection and background modeling techniques. ([Nature][4])

## My recommendation

If you're aiming for a **publication-quality or industry-level project**, I would avoid building a standard YOLO object detector. Instead, I'd propose a **hybrid AI system** that combines:

* **YOLO11** for detecting doors and obstacles,
* **SAM2 or YOLO11-seg** for precise occupancy estimation,
* **ByteTrack** for temporal consistency,
* **Vision-Language Models (e.g., Florence-2 or Qwen2.5-VL)** to generate human-readable explanations,
* **Door-centric change detection** to identify unknown or novel obstructions,
* **Risk scoring and analytics** for operational decision-making.

This architecture is more aligned with the latest research and is substantially more innovative than a conventional object detection pipeline.

[1]: https://www.scitepress.org/Papers/2026/143129/143129.pdf?utm_source=chatgpt.com "Real Time Exit Blockage Detection via Door-Centric Change Monitoring"
[2]: https://www.sciencedirect.com/science/article/pii/S0379711225000025?utm_source=chatgpt.com "Real-time semi-occluded fire detection and evacuation route generation: Leveraging instance segmentation for damage estimation - ScienceDirect"
[3]: https://www.kieae.kr/_PR/view/?aidx=47782&bidx=4308&utm_source=chatgpt.com "Improving Object Classification Accuracy for Detecting Obstacles on Indoor Evacuation Paths Using YOLOv8"
[4]: https://www.nature.com/articles/s41598-025-20331-z?utm_source=chatgpt.com "Fast highway abandoned object detection via block-based multi-group foreground extraction | Scientific Reports"
