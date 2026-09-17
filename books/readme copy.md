First, could you clarify what you mean by **"Blocked exists"**?

That phrase is not a standard computer science term. It could refer to several different research areas, for example:

1. **Block Detection / Object Blocking in Computer Vision**

   * Detect whether an object or road is blocked.
   * Example: CCTV, autonomous driving.

2. **Blocked Exit Detection (Emergency Exit)**

   * Detect if an emergency exit is blocked.
   * Common in safety monitoring using AI.

3. **Blockage Detection in Manufacturing**

   * Conveyor belt blockage detection.
   * Factory automation.

4. **Deadlock / Blocking Detection**

   * Detect blocked processes or deadlocks in distributed systems.
   * Resource Allocation Graph, Petri Nets, Wait-for Graphs.

5. **Blockchain-related**

   * Block existence verification.
   * Verify whether a block exists in a blockchain.

---

If you actually mean **Blocked Exit Detection** (which is a very popular Computer Vision project), here is a complete roadmap.

# Step 1 — Understand the Problem

Goal:

> Detect whether an emergency exit is blocked by any object.

Input

* CCTV video
* Camera stream
* Images

Output

```text
Exit Status:

✓ Clear

OR

✗ Blocked
```

---

# Step 2 — Literature Review

Useful papers

### 1. YOLO Series

* YOLOv8
* YOLOv9
* YOLOv10
* YOLO11

for object detection.

---

### 2. Occupancy Detection

Many papers detect

* occupied region
* free region
* obstruction

instead of only objects.

---

### 3. Scene Understanding

Detect

* exit sign
* door
* person
* box
* trolley

then reason whether the exit is blocked.

---

Useful recent research includes work on obstruction detection and occupancy analysis using object detection and segmentation models. ([ScienceDirect][1])

---

# Step 3 — Existing GitHub Repositories

Search using

```
blocked exit detection yolo

emergency exit detection

door obstruction detection

occupancy detection yolo

fire exit detection

```

Good repositories usually involve

* YOLO
* Detectron2
* MMDetection
* Ultralytics

---

# Step 4 — Dataset

Collect

### Positive

Blocked

```
Door
+
Box

Door
+
Person

Door
+
Cart

Door
+
Chair
```

### Negative

Not blocked

```
Empty exit

Door only

Open corridor
```

---

# Step 5 — Annotation

Use

* CVAT
* Label Studio
* Roboflow

Label

```
exit

person

chair

box

cart

obstacle
```

---

# Step 6 — Train Object Detector

Example

YOLO11

Classes

```
Exit

Person

Obstacle

Cart

Chair

Box
```

---

# Step 7 — Define Blocking Logic

This is the most important part.

Instead of saying

```
Person detected
```

say

```
Person overlaps exit
```

Compute

```
IoU(exit, obstacle)
```

If

```
IoU > threshold

↓

Blocked
```

or

```
Obstacle center

inside exit polygon
```

↓

Blocked

---

# Step 8 — Temporal Filtering

Avoid false alarms.

Example

Blocked for

```
1 frame
```

↓

Ignore

Blocked for

```
30 frames
```

↓

Alarm

---

# Step 9 — Alarm System

If

```
Blocked > 5 sec
```

then

* Send email
* SMS
* Dashboard alert
* Sound alarm

---

# Step 10 — Evaluation

Metrics

Detection

* mAP
* Precision
* Recall

Blocking

* Accuracy
* F1 Score
* False Alarm Rate

---

# Recommended Tech Stack

| Component    | Recommendation      |
| ------------ | ------------------- |
| Detection    | YOLO11              |
| Tracking     | ByteTrack           |
| Segmentation | SAM2 (optional)     |
| Backend      | FastAPI             |
| Database     | PostgreSQL          |
| Streaming    | RTSP/OpenCV         |
| Dashboard    | React               |
| Deployment   | Docker + NVIDIA GPU |

---

# Project Architecture

```
Camera

      │

      ▼

Video Stream

      │

      ▼

YOLO Detector

      │

      ▼

Object Tracking

      │

      ▼

Exit Region Analysis

      │

      ▼

Blocked Decision

      │

      ▼

Alert System

      │

      ▼

Dashboard
```

---

# Milestones

| Week | Task                                 |
| ---- | ------------------------------------ |
| 1    | Literature review and collect papers |
| 2    | Gather and annotate dataset          |
| 3    | Train YOLO model                     |
| 4    | Implement blocking logic             |
| 5    | Add tracking and temporal filtering  |
| 6    | Build FastAPI backend                |
| 7    | Create dashboard                     |
| 8    | Evaluate, optimize, and deploy       |

If, instead, you meant something different by **"Blocked exists"** (for example **blockchain block existence**, **deadlock detection**, or another domain), let me know the exact project description or share the assignment statement, and I can provide a research plan, relevant papers, repositories, and an implementation roadmap tailored to that topic.

[1]: https://www.sciencedirect.com/science/article/pii/S0005109824001183?utm_source=chatgpt.com "Liveness and deadlock-freeness verification and enforcement in bounded Petri nets using basis reachability graphs - ScienceDirect"
