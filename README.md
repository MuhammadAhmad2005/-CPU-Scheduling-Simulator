# ⚡ CPU Scheduling Simulator

> A real-time interactive CPU scheduling simulator built with Python & Tkinter — visualizing six major scheduling algorithms with live Gantt charts, adaptive feedback, and dynamic process management.

**Course:** CSC 320 — Operating Systems Lab (CSL-320)  
**Institution:** Bahria University, Islamabad  
**Authors:** Muhammad Ahmad (01-134241-024) & Syed Ali Hassan (01-134241-043)  
**Class/Section:** BSCS-5A

---

## 📋 Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Algorithms](#algorithms)
- [Architecture](#architecture)
- [Performance Benchmarks](#performance-benchmarks)
- [Project Structure](#project-structure)
- [Learning Outcomes](#learning-outcomes)

---

## Overview

This simulator models the CPU scheduling subsystem of a modern operating system. It runs scheduling algorithms in a background thread while rendering a live Gantt chart, process state grid, and metrics dashboard in real time. An adaptive feedback engine monitors performance and recommends better algorithms based on workload characteristics.

This is classified as a **Complex Computing Problem (CCP)** — it integrates concurrent programming, real-time rendering, algorithm design, and adaptive heuristics within a single unified GUI.

---

## Features

- **6 Scheduling Algorithms** — FCFS, SJF (non-preemptive), SRTF (preemptive SJF), Priority (preemptive & non-preemptive), Round Robin, and MLFQ
- **Real-Time Gantt Chart** — scrollable canvas that renders execution history from t=0 with a live time cursor
- **Live Metrics Dashboard** — avg waiting time, turnaround time, response time, CPU utilization, and throughput update every tick
- **Dynamic Process Management** — add, remove, and edit processes at any time (even mid-simulation)
- **Adaptive Feedback Engine** — detects high wait times, starvation risk, and burst variance; recommends algorithm switches in real time
- **MLFQ Configuration Dialog** — configure per-queue algorithm, time quantum, and preemption for up to N priority levels
- **Aging & Starvation Prevention** — configurable aging threshold automatically boosts priority of long-waiting processes
- **Random Process Generation** — one-click generation of randomized process sets for quick testing
- **Adjustable Simulation Speed** — 0.1× to 5× speed slider for detailed inspection or fast-forward
- **Process State Visualization** — color-coded state grid (New → Ready → Running → Waiting → Completed)
- **MLFQ Live Queue Display** — shows which queue level each process occupies in real time
- **Thread-Safe Architecture** — all shared state protected by `threading.Lock`; events passed via thread-safe deque

---

## Algorithms

| Algorithm | Preemptive | Key Characteristic |
|-----------|------------|-------------------|
| **FCFS** | No | Simplest; may cause convoy effect |
| **SJF** | No | Minimizes avg waiting time; requires burst time knowledge |
| **SRTF** | Yes | Optimal avg waiting time; risk of starvation for long jobs |
| **Priority** | Optional | Supports aging to prevent indefinite starvation |
| **Round Robin** | Yes | Fair time-sharing; configurable time quantum |
| **MLFQ** | Per-level | Adaptive; combines strengths of multiple algorithms |

### Priority Convention
Lower priority number = higher urgency (priority 1 is the highest).

### Aging
Any ready process waiting longer than the `aging_threshold` has its priority decremented by 1 each check. MLFQ uses `2× aging_threshold` to promote processes to a higher-priority queue.

---

## Architecture

The project follows an **MVC-inspired architecture**:

```
┌─────────────┐    events     ┌──────────────────┐    callbacks    ┌──────────────────┐
│  User Input │ ──────────▶  │  App (View/GUI)   │ ◀────────────  │  Scheduler       │
│  (Tkinter)  │              │  tk.Tk + Canvas   │                 │  (Model+Control) │
└─────────────┘              └──────────────────┘                 └──────────────────┘
                                      │                                     │
                                      │  event deque                        │  threading.Lock
                                      │  (50ms drain)                       │  daemon thread
                                      └──────────────────────────────────── ┘
```

| Layer | Class | Responsibility |
|-------|-------|---------------|
| Model | `Process`, `GanttBlock`, `MLFQQueue` | Data structures and state |
| Controller | `Scheduler._run()`, algorithm methods | Simulation loop, scheduling decisions |
| View | `App`, `_draw_*()` methods | Gantt chart, state grid, metrics |
| Config UI | `MLFQConfigDialog` | MLFQ per-queue configuration |

### Key Design Decisions

- **`dt = 0.05s`** — simulation advances in 50ms steps for accuracy without overhead
- **Deepcopy isolation** — processes are deep-copied at simulation start so the GUI's process list is unaffected during a run
- **Callback pattern** — `Scheduler` calls `callback(event, data)` for all state changes, fully decoupling it from Tkinter
- **Event deque** — `_update_loop()` drains the event queue every 50ms on the main thread (safe for Tkinter canvas ops)
- **Gantt merging** — consecutive ticks for the same process at the same MLFQ level are merged into one `GanttBlock` for efficient rendering

### Data Structures

| Structure | Used In | Complexity |
|-----------|---------|------------|
| `Process` (dataclass) | All algorithms | O(1) field access |
| `GanttBlock` (dataclass) | Rendering | O(1) append / O(n) draw |
| `deque` | Round Robin, MLFQ | O(1) append/popleft |
| `List[Process]` | FCFS, SJF, Priority | O(n) sort per tick |
| `threading.Lock` | Shared state | — |

---

## Performance Benchmarks

Test set: 5 processes (P1–P5) with arrival times 0, 2, 4, 5, 7 and burst times 7, 4, 1, 4, 2.

| Algorithm | Avg Wait | Avg TAT | Avg Response | CPU Util | Throughput |
|-----------|----------|---------|--------------|----------|------------|
| FCFS | 5.60 s | 9.20 s | 5.60 s | 100% | 0.278 p/s |
| SJF (NP) | 4.20 s | 7.80 s | 4.20 s | 100% | 0.278 p/s |
| SRTF (P) | **3.20 s** | **6.80 s** | **0.80 s** | 100% | 0.278 p/s |
| Priority (NP) | 6.20 s | 9.80 s | 6.20 s | 100% | 0.278 p/s |
| Priority (P) | 5.80 s | 9.40 s | 4.20 s | 100% | 0.278 p/s |
| Round Robin | 6.00 s | 9.60 s | 2.40 s | 100% | 0.278 p/s |
| MLFQ | 5.60 s | 9.20 s | 0.00 s | 100% | 0.278 p/s |

**Key findings:**
- SRTF achieves the lowest average wait and turnaround but can starve long jobs
- Round Robin gives the most balanced response time at the cost of higher wait
- MLFQ achieves the best response time (0 s) by always serving new arrivals first
- No single algorithm is universally optimal — the right choice depends on workload

---

## Project Structure

```
cpu-scheduling-simulator/
├── cpu_scheduler.py          # Entire application (single-file)
├── README.md
├── docs/
│   ├── CPU_Scheduling_Simulator_Report.pdf
│   └── report_screenshots/
│       ├── main_window.png
│       ├── fcfs_running.png
│       ├── round_robin.png
│       ├── priority.png
│       ├── mlfq_config.png
│       ├── mlfq_gantt.png
│       └── sjf.png
└── screenshots/              # README image assets
```

The entire simulator is a **single self-contained Python file** with no external dependencies.

---

## Learning Outcomes

### Operating Systems
- Process state transitions: New → Ready → Running → Waiting → Completed
- Starvation, aging, convoy effect, and priority inversion in practice
- Trade-offs between scheduling metrics (fairness vs. throughput vs. response time)

### Software Engineering
- MVC architectural pattern applied to a GUI application
- Thread-safe programming with `threading.Lock` and daemon threads
- Callback-based event system for decoupled component communication
- Python `dataclass` for clean, typed data models

### Algorithm Design
- O(n) selection algorithms with tie-breaking keys
- Complexity trade-offs across scheduling approaches
- MLFQ with configurable per-level behavior
- Adaptive heuristic system for real-time anomaly detection

---

## License

This project was developed as an academic submission for CSC 320 at Bahria University, Islamabad.  
For educational and non-commercial use only.

---

*Built with Python 3 · Tkinter · threading · dataclasses · collections.deque*
