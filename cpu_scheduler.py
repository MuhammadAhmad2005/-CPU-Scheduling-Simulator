import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import threading, time, random, copy
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional, Dict

# ═══════════════════════════════ COLOR PALETTE ════════════════════════════════
BG          = "#0b0d1a"
BG2         = "#111428"
BG3         = "#181c35"
CARD        = "#1e2240"
CARD2       = "#252a4a"
INPUT_BG    = "#161930"
BORDER      = "#2a305a"
BORDER2     = "#3a4080"

NEON_BLUE   = "#00d4ff"
NEON_PURPLE = "#b44eff"
NEON_GREEN  = "#00ff9d"
NEON_ORANGE = "#ff8c00"
NEON_RED    = "#ff3860"
NEON_CYAN   = "#00f0d0"
NEON_YELLOW = "#ffe135"
NEON_PINK   = "#ff5fad"

TEXT1 = "#e8eaf6"
TEXT2 = "#8892b0"
TEXT3 = "#4a5280"

PROC_COLORS = [
    "#00d4ff","#b44eff","#00ff9d","#ff8c00","#ff3860",
    "#ffe135","#ff5fad","#00f0d0","#7c6dfa","#4de1c1",
    "#f95959","#46d9b0","#ffd460","#ff6b9d","#59b8ff",
]

STATE_COLORS = {
    "new":       NEON_PURPLE,
    "ready":     NEON_BLUE,
    "running":   NEON_GREEN,
    "waiting":   NEON_ORANGE,
    "completed": TEXT3,
}

# ═══════════════════════════════ DATA CLASSES ═════════════════════════════════
@dataclass
class Process:
    pid: int
    name: str
    arrival_time: float
    burst_time: float
    priority: int = 1
    remaining_time: float = 0.0
    start_time: Optional[float] = None
    finish_time: Optional[float] = None
    waiting_time: float = 0.0
    turnaround_time: float = 0.0
    response_time: Optional[float] = None
    state: str = "new"
    color: str = "#00d4ff"
    queue_level: int = 0
    time_in_queue: float = 0.0

    def reset(self):
        self.remaining_time  = self.burst_time
        self.start_time      = None
        self.finish_time     = None
        self.waiting_time    = 0.0
        self.turnaround_time = 0.0
        self.response_time   = None
        self.state           = "new"
        self.queue_level     = 0
        self.time_in_queue   = 0.0


@dataclass
class GanttBlock:
    pid:   int
    name:  str
    start: float
    end:   float
    color: str
    level: int = 0


# ══════════════════════════════ MLFQ CONFIG ═══════════════════════════════════
MLFQ_ALGO_OPTIONS = ["FCFS", "SJF", "Priority", "RR"]


@dataclass
class MLFQQueue:
    level:      int
    algorithm:  str   = "RR"
    time_quantum: float = 2.0
    preemptive: bool  = False


# ══════════════════════════════ SCHEDULER ENGINE ══════════════════════════════
class Scheduler:
    def __init__(self, callback):
        self.callback   = callback
        self.processes: List[Process] = []
        self.algorithm  = "FCFS"
        self.preemptive = False
        self.time_quantum     = 2.0
        self.aging_threshold  = 10.0
        self.mlfq_queues_config: List[MLFQQueue] = [
            MLFQQueue(0, "RR", 2),
            MLFQQueue(1, "RR", 4),
            MLFQQueue(2, "FCFS"),
        ]
        self.running  = False
        self.paused   = False
        self.current_time   = 0.0
        self.speed          = 1.0
        self.gantt: List[GanttBlock] = []
        self.completed: List[Process] = []
        self.cpu_busy_time  = 0.0
        self._thread        = None
        self._lock          = threading.Lock()
        self._pid_counter   = 1
        self.adaptive_log: List[str] = []

    # ── process management ──────────────────────────────────────────────────
    def add_process(self, arrival, burst, priority=1, name=None) -> Process:
        with self._lock:
            color = PROC_COLORS[self._pid_counter % len(PROC_COLORS)]
            p = Process(
                pid=self._pid_counter,
                name=name or f"P{self._pid_counter}",
                arrival_time=float(arrival),
                burst_time=float(burst),
                priority=int(priority),
                remaining_time=float(burst),
                color=color,
            )
            self.processes.append(p)
            self._pid_counter += 1
            self.callback("process_added", p)
            return p

    def remove_process(self, pid):
        with self._lock:
            self.processes = [p for p in self.processes if p.pid != pid]
            self.callback("process_removed", pid)

    def modify_process(self, pid, **kw):
        with self._lock:
            for p in self.processes:
                if p.pid == pid:
                    for k, v in kw.items():
                        if hasattr(p, k):
                            setattr(p, k, v)
                        if k == "burst_time" and p.state in ("new", "ready"):
                            p.remaining_time = float(v)
                        if k == "arrival_time":
                            p.arrival_time = float(v)
                    self.callback("process_modified", p)
                    return

    # ── control ─────────────────────────────────────────────────────────────
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self.running = True
        self.paused  = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self):
        self.paused = True
        self.callback("paused", None)

    def resume(self):
        self.paused = False
        self.callback("resumed", None)

    def stop(self):
        self.running = False
        self.paused  = False

    def reset(self):
        self.stop()
        time.sleep(0.1)
        with self._lock:
            for p in self.processes:
                p.reset()
            self.gantt.clear()
            self.completed.clear()
            self.current_time  = 0.0
            self.cpu_busy_time = 0.0
            self.adaptive_log.clear()
        self.callback("reset", None)

    def switch_algorithm(self, algo, preemptive=False):
        with self._lock:
            self.algorithm  = algo
            self.preemptive = preemptive
            self.callback("algo_switched", algo)

    # ── helpers ─────────────────────────────────────────────────────────────
    @staticmethod
    def _gantt_append(gantt: List[GanttBlock], pid, name, t, dt, color, level=0):
        """Append or extend the last Gantt block — same pid+level merges."""
        if gantt and gantt[-1].pid == pid and gantt[-1].level == level:
            gantt[-1].end = round(t + dt, 3)
        else:
            gantt.append(GanttBlock(pid, name, round(t, 3), round(t + dt, 3), color, level))

    # ── main simulation loop ─────────────────────────────────────────────────
    def _run(self):
        with self._lock:
            procs = [copy.deepcopy(p) for p in self.processes]
        for p in procs:
            p.reset()

        DT = 0.05          # simulation time step (seconds)
        EPS = DT * 0.5     # tolerance for floating-point comparisons

        t          = 0.0
        completed  : List[Process] = []
        gantt      : List[GanttBlock] = []

        # ── per-algorithm state ──────────────────────────────────────────────
        # RR
        rr_queue     : deque  = deque()
        rr_queue_set : set    = set()    # pid set to avoid duplicates
        rr_slice     : float  = 0.0
        rr_current   : Optional[Process] = None

        # MLFQ  (one deque + one pid-set per level)
        mlfq_qs      : List[deque] = []
        mlfq_sets    : List[set]   = []
        mlfq_slices  : List[float] = []
        mlfq_admitted: set = set()   # pids ever admitted to any queue

        with self._lock:
            n_mlfq = len(self.mlfq_queues_config)
        for _ in range(n_mlfq):
            mlfq_qs.append(deque())
            mlfq_sets.append(set())
            mlfq_slices.append(0.0)

        self.callback("sim_start", procs)

        # ── simulation tick loop ─────────────────────────────────────────────
        while self.running:
            while self.paused and self.running:
                time.sleep(0.05)
            if not self.running:
                break

            with self._lock:
                algo        = self.algorithm
                preemptive  = self.preemptive
                quantum     = self.time_quantum
                aging       = self.aging_threshold
                mlfq_cfg    = copy.deepcopy(self.mlfq_queues_config)
                n_mlfq      = len(mlfq_cfg)

            # Expand MLFQ state arrays if config grew
            while len(mlfq_qs) < n_mlfq:
                mlfq_qs.append(deque())
                mlfq_sets.append(set())
                mlfq_slices.append(0.0)

            # ── arrive new processes ────────────────────────────────────────
            for p in procs:
                if p.state == "new" and p.arrival_time <= t + EPS:
                    p.state = "ready"
                    if algo == "RR":
                        if p.pid not in rr_queue_set:
                            rr_queue.append(p)
                            rr_queue_set.add(p.pid)
                    elif algo == "MLFQ":
                        if p.pid not in mlfq_admitted:
                            mlfq_qs[0].append(p)
                            mlfq_sets[0].add(p.pid)
                            mlfq_admitted.add(p.pid)
                            p.queue_level = 0
                    self.callback("process_state", p)

            # ── pick next process ───────────────────────────────────────────
            ready   = [p for p in procs if p.state == "ready"]
            running = next((p for p in procs if p.state == "running"), None)

            if algo == "FCFS":
                cur = self._fcfs(ready, running)

            elif algo == "SJF":
                cur = self._sjf(ready, running, preemptive)

            elif algo == "Priority":
                cur = self._priority_sched(ready, running, preemptive, aging, t)

            elif algo == "RR":
                cur, rr_slice, rr_current = self._rr(
                    ready, running, rr_queue, rr_queue_set,
                    rr_slice, rr_current, quantum, DT)

            elif algo == "MLFQ":
                cur = self._mlfq(
                    mlfq_qs, mlfq_sets, mlfq_slices, mlfq_admitted,
                    running, mlfq_cfg, n_mlfq, DT, procs, t, aging)
            else:
                cur = None

            # ── execute one DT slice ────────────────────────────────────────
            if cur:
                if cur.state != "running":
                    cur.state = "running"
                    if cur.start_time is None:
                        cur.start_time = t
                    if cur.response_time is None:
                        cur.response_time = t - cur.arrival_time
                    self.callback("process_state", cur)

                self._gantt_append(gantt, cur.pid, cur.name, t, DT,
                                   cur.color, cur.queue_level)
                cur.remaining_time = round(cur.remaining_time - DT, 6)
                self.cpu_busy_time += DT

                if cur.remaining_time <= EPS:
                    cur.remaining_time   = 0.0
                    cur.state            = "completed"
                    cur.finish_time      = round(t + DT, 3)
                    cur.turnaround_time  = round(cur.finish_time - cur.arrival_time, 3)
                    cur.waiting_time     = round(cur.turnaround_time - cur.burst_time, 3)
                    completed.append(cur)
                    # clean up RR
                    if cur.pid in rr_queue_set:
                        rr_queue_set.discard(cur.pid)
                        rr_queue = deque(p for p in rr_queue if p.pid != cur.pid)
                    if cur is rr_current:
                        rr_current = None
                        rr_slice   = 0.0
                    # clean up MLFQ
                    lvl = cur.queue_level
                    if 0 <= lvl < len(mlfq_sets):
                        mlfq_sets[lvl].discard(cur.pid)
                    self.callback("process_state", cur)
                    self.callback("process_completed", cur)
            else:
                # CPU idle
                self._gantt_append(gantt, -1, "IDLE", t, DT, TEXT3)

            # ── accumulate waiting time for READY processes only ────────────
            for p in procs:
                if p.state == "ready":
                    p.time_in_queue = round(p.time_in_queue + DT, 6)

            t = round(t + DT, 3)

            with self._lock:
                self.current_time = t
                self.gantt        = gantt[:]
                self.completed    = completed[:]

            self.callback("tick", (t, gantt[:], procs[:], completed[:]))

            # adaptive analysis every ~1 s
            if round(t * 20) % 20 == 0:
                self._adaptive_check(procs, t)

            all_done = all(p.state == "completed" for p in procs)
            if all_done:
                break

            time.sleep(DT / max(self.speed, 0.1))

        self.callback("sim_done", (gantt[:], completed[:], t))

    # ══ SCHEDULING ALGORITHMS ═══════════════════════════════════════════════

    # ── FCFS ─────────────────────────────────────────────────────────────────
    def _fcfs(self, ready, running):
        if running:
            return running
        return min(ready, key=lambda p: p.arrival_time) if ready else None

    # ── SJF ──────────────────────────────────────────────────────────────────
    def _sjf(self, ready, running, preemptive):
        if not preemptive:
            if running:
                return running
            return min(ready, key=lambda p: p.remaining_time) if ready else None

        # Preemptive SJF (SRTF)
        cands = ready + ([running] if running else [])
        if not cands:
            return None
        best = min(cands, key=lambda p: p.remaining_time)
        if running and best.pid != running.pid:
            running.state = "ready"
            self.callback("process_state", running)
        return best

    # ── Priority ─────────────────────────────────────────────────────────────
    def _priority_sched(self, ready, running, preemptive, aging, t):

        # ── aging ──────────────────────────────────────────────────────────
        running_priority = running.priority if running else float("inf")

        for p in ready:
            if p.time_in_queue >= aging:
                new_prio = max(1, p.priority - 1)
                # Only apply the decrement; do NOT force an immediate preemption.
                # The scheduler loop below decides whether to preempt.
                p.priority      = new_prio
                p.time_in_queue = 0.0          # reset so it doesn't fire again next tick
                self.adaptive_log.append(
                    f"t={t:.1f}: Aging → {p.name} priority→{p.priority}")

        if not preemptive:
            # Non-preemptive: keep the running process until it finishes.
            if running:
                return running
            if not ready:
                return None
            # Tiebreaker: lowest priority number wins; ties broken by arrival_time then pid.
            return min(ready, key=lambda p: (p.priority, p.arrival_time, p.pid))

        # ── Preemptive: find the best candidate among ALL (ready + running) ─
        cands = ready + ([running] if running else [])
        if not cands:
            return None

        # Tiebreaker key: (priority_number, arrival_time, pid)
        # The running process naturally wins ties because it has been here
        # longer (earlier arrival_time or lower pid).
        best = min(cands, key=lambda p: (p.priority, p.arrival_time, p.pid))

        # Only preempt if a DIFFERENT process has STRICTLY better priority.
        if running and best.pid != running.pid and best.priority < running.priority:
            running.state = "ready"
            self.callback("process_state", running)
            return best

        # Otherwise keep running (or start best if CPU was idle).
        if running:
            return running
        return best

    # ── Round Robin ──────────────────────────────────────────────────────────
    def _rr(self, ready, running, rr_queue, rr_queue_set,
            rr_slice, rr_current, quantum, dt):

        # Admit any newly-ready processes (those not yet in queue and not running)
        for p in ready:
            if p.pid not in rr_queue_set:
                rr_queue.append(p)
                rr_queue_set.add(p.pid)

        if rr_current and rr_current.state == "running":
            rr_slice = round(rr_slice - dt, 6)
            if rr_slice > 1e-6:
                return rr_current, rr_slice, rr_current   # keep running

            # Slice expired → preempt
            rr_current.state = "ready"
            self.callback("process_state", rr_current)
            if rr_current.pid not in rr_queue_set:
                rr_queue.append(rr_current)
                rr_queue_set.add(rr_current.pid)
            rr_current = None
            rr_slice   = 0.0

        # Dequeue next eligible process
        while rr_queue:
            nxt = rr_queue.popleft()
            rr_queue_set.discard(nxt.pid)
            if nxt.state in ("ready", "running") and nxt.remaining_time > 1e-6:
                rr_current = nxt
                rr_slice   = quantum
                return nxt, rr_slice, rr_current

        return None, 0.0, None

    # ── MLFQ ─────────────────────────────────────────────────────────────────
    def _mlfq(self, qs, sets, slices, admitted,
               running, cfg, n, dt, procs, t, aging):

        # ── aging ───────────────────────────────────────────────────────────
        for lvl in range(1, n):
            promote = []
            for p in list(qs[lvl]):
                if p.time_in_queue >= aging * 2:
                    promote.append(p)
            for p in promote:
                qs[lvl].remove(p)
                sets[lvl].discard(p.pid)
                new_lvl = lvl - 1
                if p.pid not in sets[new_lvl]:
                    qs[new_lvl].append(p)
                    sets[new_lvl].add(p.pid)
                p.queue_level   = new_lvl
                p.time_in_queue = 0.0

        # ── quantum countdown for running process ────────────────────────────
        if running and running.state == "running":
            lvl     = min(running.queue_level, n - 1)
            q_cfg   = cfg[lvl]
            if q_cfg.algorithm == "RR":
                slices[lvl] = round(slices[lvl] - dt, 6)
                if slices[lvl] > 1e-6:
                    return running   # keep running in same queue

                # Quantum expired → demote
                running.state   = "ready"
                new_lvl         = min(running.queue_level + 1, n - 1)
                running.queue_level = new_lvl
                running.time_in_queue = 0.0
                sets[running.queue_level].discard(running.pid)  # old level
                if running.pid not in sets[new_lvl]:
                    qs[new_lvl].append(running)
                    sets[new_lvl].add(running.pid)
                self.callback("process_state", running)
                running = None
            else:
                # Non-RR queue: run until completion (no quantum limit)
                return running

        # ── admit newly ready processes to Q0 ───────────────────────────────
        for p in procs:
            if p.state == "ready" and p.pid not in admitted:
                admitted.add(p.pid)
                if p.pid not in sets[0]:
                    qs[0].append(p)
                    sets[0].add(p.pid)
                p.queue_level = 0

        # ── pick from highest priority non-empty queue ───────────────────────
        for lvl in range(n):
            q_cfg = cfg[lvl]
            while qs[lvl]:
                p = qs[lvl].popleft()
                sets[lvl].discard(p.pid)
                if p.state in ("ready", "running") and p.remaining_time > 1e-6:
                    p.queue_level   = lvl
                    p.time_in_queue = 0.0
                    if q_cfg.algorithm == "RR":
                        slices[lvl] = q_cfg.time_quantum
                    return p

        return None

    # ── adaptive hints ───────────────────────────────────────────────────────
    def _adaptive_check(self, procs, t):
        ready = [p for p in procs if p.state == "ready"]
        if not ready:
            return
        avg_wait = sum(p.waiting_time for p in ready) / len(ready)
        bursts   = [p.remaining_time for p in ready]
        variance = (max(bursts) - min(bursts)) if len(bursts) > 1 else 0
        with self._lock:
            algo = self.algorithm
        msgs = []
        if avg_wait > 15 and algo == "FCFS":
            msgs.append(f"⚠ t={t:.1f}: High avg wait ({avg_wait:.1f}s). Consider SJF or Priority.")
        if variance > 10 and algo not in ("SJF", "MLFQ"):
            msgs.append(f"💡 t={t:.1f}: High burst variance. SJF/MLFQ would improve throughput.")
        if any(p.waiting_time > 20 for p in ready) and algo == "Priority":
            msgs.append(f"🚨 t={t:.1f}: Starvation risk! Enable aging or switch algorithm.")
        for m in msgs:
            if m not in self.adaptive_log[-5:]:
                self.adaptive_log.append(m)
                self.callback("adaptive", m)

    # ── metrics ──────────────────────────────────────────────────────────────
    def compute_metrics(self):
        with self._lock:
            done = self.completed[:]
            t    = max(self.current_time, 0.001)
            busy = self.cpu_busy_time
        if not done:
            return {}
        awt  = sum(p.waiting_time     for p in done) / len(done)
        att  = sum(p.turnaround_time  for p in done) / len(done)
        resp = [p.response_time for p in done if p.response_time is not None]
        art  = sum(resp) / len(resp) if resp else 0
        return {
            "Avg Waiting Time":    f"{awt:.2f}s",
            "Avg Turnaround Time": f"{att:.2f}s",
            "Avg Response Time":   f"{art:.2f}s",
            "CPU Utilization":     f"{(busy/t)*100:.1f}%",
            "Throughput":          f"{len(done)/t:.3f} p/s",
            "Completed":           str(len(done)),
        }


# ══════════════════════════════ MLFQ CONFIG DIALOG ═══════════════════════════
class MLFQConfigDialog(tk.Toplevel):
    def __init__(self, parent, current_cfg):
        super().__init__(parent)
        self.title("Configure MLFQ")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.result = None
        self._row_vars = []
        self._build(current_cfg)
        self.grab_set()
        self.transient(parent)
        self.wait_window()

    def _build(self, cfg):
        tk.Label(self, text="Multilevel Feedback Queue Configuration",
                 bg=BG, fg=NEON_CYAN, font=("Consolas", 13, "bold")).pack(
            pady=(18, 4), padx=20)
        tk.Label(self, text="Define queues from highest (Q0) to lowest priority.",
                 bg=BG, fg=TEXT2, font=("Consolas", 9)).pack(pady=(0, 12))

        self._rows_frame = tk.Frame(self, bg=BG)
        self._rows_frame.pack(padx=20, fill="x")

        hdr = tk.Frame(self._rows_frame, bg=BG)
        hdr.pack(fill="x", pady=(0, 4))
        for col_txt, col_w in [("Queue", 50), ("Algorithm", 110),
                                ("Time Quantum (RR)", 140), ("Preemptive (SJF/Prio)", 160)]:
            tk.Label(hdr, text=col_txt, bg=BG, fg=TEXT2,
                     font=("Consolas", 8, "bold"),
                     width=col_w // 8, anchor="w").pack(side="left", padx=4)

        for q in cfg:
            self._add_row(q.algorithm, q.time_quantum, q.preemptive)

        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(pady=8)
        tk.Button(btn_row, text="＋ Add Queue", command=self._add_empty_row,
                  bg=NEON_BLUE, fg=BG, font=("Consolas", 9, "bold"),
                  relief="flat", padx=10, pady=4).pack(side="left", padx=4)
        tk.Button(btn_row, text="－ Remove Last", command=self._remove_last_row,
                  bg=NEON_RED, fg="white", font=("Consolas", 9, "bold"),
                  relief="flat", padx=10, pady=4).pack(side="left", padx=4)

        ok_row = tk.Frame(self, bg=BG)
        ok_row.pack(pady=12)
        tk.Button(ok_row, text="✓  Apply", command=self._ok,
                  bg=NEON_GREEN, fg=BG, font=("Consolas", 10, "bold"),
                  relief="flat", padx=20, pady=6).pack(side="left", padx=6)
        tk.Button(ok_row, text="✗  Cancel", command=self.destroy,
                  bg=CARD2, fg=TEXT2, font=("Consolas", 10, "bold"),
                  relief="flat", padx=20, pady=6).pack(side="left", padx=6)

    def _add_row(self, algo="RR", quantum=2, preemptive=False):
        idx = len(self._row_vars)
        row = tk.Frame(self._rows_frame, bg=CARD,
                       highlightbackground=BORDER, highlightthickness=1)
        row.pack(fill="x", pady=3)

        tk.Label(row, text=f"Q{idx}", bg=CARD, fg=NEON_CYAN,
                 font=("Consolas", 10, "bold"), width=5).pack(side="left", padx=6)

        algo_var = tk.StringVar(value=algo)
        cb = ttk.Combobox(row, textvariable=algo_var, values=MLFQ_ALGO_OPTIONS,
                          state="readonly", width=12, font=("Consolas", 9))
        cb.pack(side="left", padx=6, pady=6)

        tk.Label(row, text="Quantum:", bg=CARD, fg=TEXT2,
                 font=("Consolas", 8)).pack(side="left")
        q_var   = tk.StringVar(value=str(quantum))
        q_entry = tk.Entry(row, textvariable=q_var, width=5,
                           relief="flat", font=("Consolas", 9),
                           highlightthickness=1, highlightcolor=NEON_BLUE,
                           highlightbackground=BORDER)
        q_entry.pack(side="left", padx=6)

        p_var = tk.BooleanVar(value=preemptive)
        p_cb  = tk.Checkbutton(row, text="Preemptive", variable=p_var,
                                bg=CARD, selectcolor=INPUT_BG,
                                activebackground=CARD, font=("Consolas", 8))
        p_cb.pack(side="left", padx=6)

        def _refresh(*_):
            a = algo_var.get()
            if a == "RR":
                q_entry.config(state="normal", bg=INPUT_BG, fg=TEXT1)
            else:
                q_var.set("—")
                q_entry.config(state="disabled",
                               disabledbackground=BG3, disabledforeground=TEXT3)
            if a in ("SJF", "Priority"):
                p_cb.config(state="normal", fg=TEXT1)
            else:
                p_var.set(False)
                p_cb.config(state="disabled", fg=TEXT3)

        algo_var.trace_add("write", _refresh)
        _refresh()
        self._row_vars.append((algo_var, q_var, p_var, row))

    def _add_empty_row(self):
        if len(self._row_vars) < 6:
            self._add_row()

    def _remove_last_row(self):
        if len(self._row_vars) > 2:
            _, _, _, row = self._row_vars.pop()
            row.destroy()

    def _ok(self):
        cfg = []
        for i, (av, qv, pv, _) in enumerate(self._row_vars):
            try:
                raw = qv.get().strip()
                q   = max(0.5, float(raw)) if raw not in ("", "—") else 2.0
            except Exception:
                q = 2.0
            cfg.append(MLFQQueue(i, av.get(), q, pv.get()))
        self.result = cfg
        self.destroy()
        
# ══════════════════════════════ MAIN APPLICATION ══════════════════════════════
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CPU Scheduling Simulator")
        self.geometry("1600x920")
        self.configure(bg=BG)
        self.minsize(1280, 760)
        self._setup_styles()
        self.scheduler = Scheduler(self._on_event)
        self._evt_queue: deque = deque()
        self._sim_procs: List[Process] = []
        self._current_edit_pid = None
        self._last_was_random  = False
        self._build_ui()
        self._update_loop()

    # ── styles ───────────────────────────────────────────────────────────────
    def _setup_styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TFrame",     background=BG)
        s.configure("TLabel",     background=BG, foreground=TEXT1, font=("Consolas", 10))
        s.configure("TCombobox",  fieldbackground=INPUT_BG, background=INPUT_BG,
                    foreground=TEXT1, selectbackground=NEON_BLUE, font=("Consolas", 10))
        s.map("TCombobox", fieldbackground=[("readonly", INPUT_BG)])
        s.configure("TNotebook",     background=BG2, tabmargins=[2, 5, 2, 0])
        s.configure("TNotebook.Tab", background=CARD, foreground=TEXT2,
                    padding=[14, 6], font=("Consolas", 9))
        s.map("TNotebook.Tab",
              background=[("selected", BG2)],
              foreground=[("selected", NEON_CYAN)])
        s.configure("Treeview", background=CARD, foreground=TEXT1,
                    fieldbackground=CARD, rowheight=26, font=("Consolas", 9))
        s.configure("Treeview.Heading", background=BG2, foreground=NEON_BLUE,
                    font=("Consolas", 9, "bold"))
        s.map("Treeview",
              background=[("selected", NEON_BLUE)],
              foreground=[("selected", BG)])
        s.configure("TScrollbar", background=CARD, troughcolor=BG,
                    bordercolor=BORDER, arrowcolor=TEXT2)

    # ── BUILD UI ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        topbar = tk.Frame(self, bg=BG2, height=52)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)
        tk.Label(topbar, text="⚡  CPU SCHEDULING SIMULATOR",
                 bg=BG2, fg=NEON_CYAN, font=("Consolas", 14, "bold")).pack(
            side="left", padx=20, pady=12)
        self._clock_var = tk.StringVar(value="t = 0.00s")
        tk.Label(topbar, textvariable=self._clock_var,
                 bg=BG2, fg=NEON_GREEN, font=("Consolas", 14, "bold")).pack(
            side="right", padx=20)

        pw = tk.PanedWindow(self, orient="horizontal", bg=BG,
                            sashwidth=4, sashrelief="flat")
        pw.pack(fill="both", expand=True)

        left = tk.Frame(pw, bg=BG2, width=290)
        pw.add(left, minsize=270)
        self._build_left(left)

        mid = tk.Frame(pw, bg=BG)
        pw.add(mid, minsize=750)
        self._build_center(mid)

        right = tk.Frame(pw, bg=BG2, width=310)
        pw.add(right, minsize=280)
        self._build_right(right)

    # ── LEFT PANEL ───────────────────────────────────────────────────────────
    def _build_left(self, p):
        sec = self._section(p, "ALGORITHM")
        arow = tk.Frame(sec, bg=BG2)
        arow.pack(fill="x", pady=(0, 4))
        self._algo_var = tk.StringVar(value="FCFS")
        algos = ["FCFS", "SJF", "Priority", "Round Robin", "MLFQ"]
        self._algo_cb = ttk.Combobox(arow, textvariable=self._algo_var,
                                     values=algos, state="readonly", width=18)
        self._algo_cb.pack(side="left", fill="x", expand=True)
        self._algo_cb.bind("<<ComboboxSelected>>", self._algo_changed)

        self._preempt_var = tk.BooleanVar(value=False)
        self._preempt_check = tk.Checkbutton(
            arow, text="Preempt", variable=self._preempt_var,
            bg=BG2, fg=TEXT1, selectcolor=INPUT_BG,
            activebackground=BG2, font=("Consolas", 8),
            command=self._algo_changed)
        self._preempt_check.pack(side="left", padx=(6, 0))
        self._preempt_check.config(state="disabled")

        self._mlfq_btn = tk.Button(
            sec, text="⚙  Configure MLFQ Queues",
            command=self._open_mlfq_config,
            bg=NEON_PURPLE, fg="white", font=("Consolas", 8, "bold"),
            relief="flat", padx=8, pady=4, cursor="hand2")
        self._mlfq_btn.pack(fill="x", pady=(4, 0))
        self._mlfq_btn.pack_forget()

        ps = self._section(p, "PARAMETERS")
        g  = tk.Frame(ps, bg=BG2)
        g.pack(fill="x")
        self._quantum_var = tk.StringVar(value="2")
        self._aging_var   = tk.StringVar(value="10")
        self._param_row(g, "Time Quantum (RR):", self._quantum_var, 0)
        self._param_row(g, "Aging Threshold:  ", self._aging_var,   1)
        g.columnconfigure(1, weight=1)

        spf = tk.Frame(ps, bg=BG2)
        spf.pack(fill="x", pady=(6, 0))
        tk.Label(spf, text="Speed:", bg=BG2, fg=TEXT2,
                 font=("Consolas", 9)).pack(side="left")
        self._speed_var = tk.DoubleVar(value=1.0)
        ttk.Scale(spf, from_=0.1, to=10.0, variable=self._speed_var,
                  orient="horizontal",
                  command=self._speed_changed).pack(side="left", fill="x",
                                                    expand=True, padx=6)
        self._speed_lbl = tk.Label(spf, text="1.0x", bg=BG2, fg=NEON_CYAN,
                                   font=("Consolas", 9, "bold"), width=5)
        self._speed_lbl.pack(side="left")

        ads = self._section(p, "ADD PROCESS")
        self._pname_var    = tk.StringVar(value="")
        self._parrival_var = tk.StringVar(value="0")
        self._pburst_var   = tk.StringVar(value="5")
        self._pprio_var    = tk.StringVar(value="1")
        for lbl, var in [("Name (opt):", self._pname_var),
                         ("Arrival:   ", self._parrival_var),
                         ("Burst:     ", self._pburst_var),
                         ("Priority:  ", self._pprio_var)]:
            r = tk.Frame(ads, bg=BG2)
            r.pack(fill="x", pady=1)
            tk.Label(r, text=lbl, bg=BG2, fg=TEXT2,
                     font=("Consolas", 9), width=12, anchor="w").pack(side="left")
            tk.Entry(r, textvariable=var, bg=INPUT_BG, fg=TEXT1,
                     insertbackground=TEXT1, relief="flat",
                     font=("Consolas", 10), width=10,
                     highlightthickness=1, highlightcolor=NEON_BLUE,
                     highlightbackground=BORDER).pack(side="left", fill="x", expand=True)

        btnr = tk.Frame(ads, bg=BG2)
        btnr.pack(fill="x", pady=(8, 0))
        self._btn(btnr, "＋ Add Process", self._add_process, NEON_BLUE).pack(
            side="left", fill="x", expand=True)
        self._btn(btnr, "🎲 Random", self._add_random_dialog, NEON_PURPLE, px=2).pack(
            side="left")

        cs = self._section(p, "SIMULATION")
        r1 = tk.Frame(cs, bg=BG2)
        r1.pack(fill="x")
        self._start_btn = self._btn(r1, "▶  Start", self._start, NEON_GREEN)
        self._start_btn.pack(side="left", fill="x", expand=True, padx=(0, 2))
        self._pause_btn = self._btn(r1, "⏸  Pause", self._toggle_pause, NEON_ORANGE)
        self._pause_btn.pack(side="left", fill="x", expand=True, padx=(2, 0))
        r2 = tk.Frame(cs, bg=BG2)
        r2.pack(fill="x", pady=(4, 0))
        self._btn(r2, "⏹  Stop",  self._stop,  NEON_RED).pack(
            side="left", fill="x", expand=True, padx=(0, 2))
        self._btn(r2, "↺  Reset", self._reset, TEXT3).pack(
            side="left", fill="x", expand=True, padx=(2, 0))

    def _param_row(self, g, lbl, var, row):
        tk.Label(g, text=lbl, bg=BG2, fg=TEXT2,
                 font=("Consolas", 9), anchor="w").grid(
            row=row, column=0, sticky="w", pady=2)
        tk.Entry(g, textvariable=var, bg=INPUT_BG, fg=TEXT1,
                 insertbackground=TEXT1, relief="flat",
                 font=("Consolas", 10), width=7,
                 highlightthickness=1, highlightcolor=NEON_BLUE,
                 highlightbackground=BORDER).grid(
            row=row, column=1, sticky="ew", padx=(8, 0), pady=2)

    # ── CENTER PANEL ─────────────────────────────────────────────────────────
    def _build_center(self, p):
        nb = ttk.Notebook(p)
        nb.pack(fill="both", expand=True, padx=4, pady=4)

        sim_tab  = tk.Frame(nb, bg=BG);  nb.add(sim_tab,  text="  📊 Simulation  ")
        self._build_sim_tab(sim_tab)
        proc_tab = tk.Frame(nb, bg=BG);  nb.add(proc_tab, text="  ⚙ Processes  ")
        self._build_proc_tab(proc_tab)
        tbl_tab  = tk.Frame(nb, bg=BG);  nb.add(tbl_tab,  text="  📋 Process Table  ")
        self._build_table_tab(tbl_tab)
        met_tab  = tk.Frame(nb, bg=BG);  nb.add(met_tab,  text="  📈 Metrics  ")
        self._build_metrics_tab(met_tab)

    def _build_sim_tab(self, p):
        gf = tk.Frame(p, bg=CARD, highlightbackground=BORDER2, highlightthickness=1)
        gf.pack(fill="x", padx=8, pady=(8, 4))
        hdr = tk.Frame(gf, bg=CARD)
        hdr.pack(fill="x", padx=10, pady=(6, 2))
        tk.Label(hdr, text="GANTT CHART", bg=CARD, fg=NEON_CYAN,
                 font=("Consolas", 10, "bold")).pack(side="left")
        self._gantt_scroll_x = tk.Scrollbar(gf, orient="horizontal")
        self._gantt_scroll_x.pack(fill="x", side="bottom", padx=8)
        self._gantt_canvas = tk.Canvas(gf, bg=CARD, height=110,
                                       highlightthickness=0,
                                       xscrollcommand=self._gantt_scroll_x.set)
        self._gantt_canvas.pack(fill="x", padx=8, pady=(0, 2))
        self._gantt_scroll_x.config(command=self._gantt_canvas.xview)

        self._mlfq_gantt_frame = tk.Frame(p, bg=CARD,
                                          highlightbackground=BORDER2, highlightthickness=1)
        self._mlfq_gantt_frame.pack(fill="x", padx=8, pady=(0, 4))
        tk.Label(self._mlfq_gantt_frame, text="MLFQ QUEUE GANTT",
                 bg=CARD, fg=NEON_PURPLE,
                 font=("Consolas", 9, "bold")).pack(anchor="w", padx=10, pady=(4, 0))
        self._mlfq_gantt_canvas = tk.Canvas(self._mlfq_gantt_frame, bg=CARD,
                                            height=130, highlightthickness=0)
        self._mlfq_gantt_canvas.pack(fill="x", padx=8, pady=(0, 6))
        self._mlfq_gantt_frame.pack_forget()

        qf = tk.Frame(p, bg=CARD, highlightbackground=BORDER2, highlightthickness=1)
        qf.pack(fill="x", padx=8, pady=4)
        tk.Label(qf, text="READY QUEUE", bg=CARD, fg=NEON_ORANGE,
                 font=("Consolas", 10, "bold")).pack(anchor="w", padx=10, pady=(5, 2))
        self._queue_canvas = tk.Canvas(qf, bg=CARD, height=52, highlightthickness=0)
        self._queue_canvas.pack(fill="x", padx=8, pady=(0, 6))

        sf = tk.Frame(p, bg=BG)
        sf.pack(fill="both", expand=True, padx=8, pady=4)
        tk.Label(sf, text="PROCESS STATES", bg=BG, fg=TEXT2,
                 font=("Consolas", 9, "bold")).pack(anchor="w", pady=(0, 4))
        self._state_canvas = tk.Canvas(sf, bg=BG, highlightthickness=0)
        self._state_canvas.pack(fill="both", expand=True)

    def _build_proc_tab(self, p):
        hdr = tk.Frame(p, bg=BG)
        hdr.pack(fill="x", padx=10, pady=(10, 4))
        tk.Label(hdr, text="Added Processes  (right-click to edit/remove)",
                 bg=BG, fg=TEXT2, font=("Consolas", 9)).pack(side="left")

        cols = ("PID", "Name", "Arrival", "Burst", "Priority", "Color")
        self._proc_list_tree = ttk.Treeview(p, columns=cols, show="headings", height=18)
        for col, w in zip(cols, [50, 80, 70, 70, 70, 80]):
            self._proc_list_tree.heading(col, text=col)
            self._proc_list_tree.column(col, width=w, anchor="center", minwidth=w)

        ys = ttk.Scrollbar(p, orient="vertical",
                           command=self._proc_list_tree.yview)
        self._proc_list_tree.configure(yscrollcommand=ys.set)
        self._proc_list_tree.pack(fill="both", expand=True, side="left",
                                  padx=(8, 0), pady=4)
        ys.pack(side="right", fill="y", pady=4, padx=(0, 8))

        self._proc_menu = tk.Menu(self, tearoff=0, bg=CARD2, fg=TEXT1,
                                  activebackground=NEON_BLUE, activeforeground=BG,
                                  font=("Consolas", 9))
        self._proc_menu.add_command(label="✏  Edit",   command=self._edit_proc_list)
        self._proc_menu.add_command(label="🗑  Remove", command=self._remove_proc_list)
        self._proc_list_tree.bind("<Button-3>", self._show_proc_menu)

    def _build_table_tab(self, p):
        cols = ("PID","Name","Arrival","Burst","Priority",
                "Remaining","State","Wait","TAT","Response")
        self._proc_tree = ttk.Treeview(p, columns=cols, show="headings", height=18)
        for c, w in zip(cols, [45, 70, 60, 60, 60, 75, 80, 65, 65, 75]):
            self._proc_tree.heading(c, text=c)
            self._proc_tree.column(c, width=w, anchor="center", minwidth=w)
        ys = ttk.Scrollbar(p, orient="vertical", command=self._proc_tree.yview)
        self._proc_tree.configure(yscrollcommand=ys.set)
        self._proc_tree.pack(fill="both", expand=True, side="left",
                             padx=(4, 0), pady=4)
        ys.pack(side="right", fill="y", pady=4, padx=(0, 4))
        for st, col in STATE_COLORS.items():
            self._proc_tree.tag_configure(st, foreground=col)

    def _build_metrics_tab(self, p):
        cf = tk.Frame(p, bg=BG)
        cf.pack(fill="x", padx=8, pady=8)
        self._met_lbl = {}
        keys  = ["Avg Waiting Time","Avg Turnaround Time","Avg Response Time",
                 "CPU Utilization","Throughput","Completed"]
        cols  = [NEON_ORANGE, NEON_PURPLE, NEON_CYAN, NEON_GREEN, NEON_BLUE, NEON_YELLOW]
        for i, (k, c) in enumerate(zip(keys, cols)):
            card = tk.Frame(cf, bg=CARD, padx=14, pady=12,
                            highlightbackground=c, highlightthickness=1)
            card.grid(row=i // 3, column=i % 3, sticky="nsew", padx=4, pady=4)
            cf.columnconfigure(i % 3, weight=1)
            tk.Label(card, text=k, bg=CARD, fg=TEXT2, font=("Consolas", 9)).pack(anchor="w")
            lbl = tk.Label(card, text="—", bg=CARD, fg=c, font=("Consolas", 20, "bold"))
            lbl.pack(anchor="w")
            self._met_lbl[k] = lbl

        tk.Label(p, text="Completed Processes", bg=BG, fg=TEXT2,
                 font=("Consolas", 9, "bold")).pack(anchor="w", padx=12, pady=(6, 2))
        ccols = ("Name","Arrival","Burst","Priority","Start","Finish","Wait","TAT","Response")
        self._comp_tree = ttk.Treeview(p, columns=ccols, show="headings", height=10)
        for c in ccols:
            self._comp_tree.heading(c, text=c)
            self._comp_tree.column(c, width=80, anchor="center", minwidth=60)
        cys = ttk.Scrollbar(p, orient="vertical", command=self._comp_tree.yview)
        self._comp_tree.configure(yscrollcommand=cys.set)
        self._comp_tree.pack(fill="both", expand=True, side="left",
                             padx=(8, 0), pady=4)
        cys.pack(side="right", fill="y", pady=4, padx=(0, 8))

    # ── RIGHT PANEL ──────────────────────────────────────────────────────────
    def _build_right(self, p):
        ms = self._section(p, "MLFQ LIVE QUEUES")
        self._mlfq_canvas = tk.Canvas(ms, bg=BG2, height=140, highlightthickness=0)
        self._mlfq_canvas.pack(fill="x")

        af = self._section(p, "ADAPTIVE FEEDBACK")
        self._feedback = tk.Text(af, bg=INPUT_BG, fg=TEXT1, font=("Consolas", 9),
                                 height=8, relief="flat", wrap="word", state="disabled",
                                 highlightthickness=1, highlightbackground=BORDER)
        self._feedback.pack(fill="x")
        self._feedback.tag_config("warn",  foreground=NEON_ORANGE)
        self._feedback.tag_config("alert", foreground=NEON_RED)
        self._feedback.tag_config("tip",   foreground=NEON_CYAN)
        self._feedback.tag_config("ok",    foreground=NEON_GREEN)

        ls = self._section(p, "STATE LEGEND")
        lg = tk.Frame(ls, bg=BG2)
        lg.pack(fill="x")
        for i, (name, color) in enumerate(STATE_COLORS.items()):
            row = tk.Frame(lg, bg=BG2)
            row.grid(row=i // 2, column=i % 2, sticky="w", padx=4, pady=2)
            tk.Canvas(row, bg=color, width=10, height=10,
                      highlightthickness=0).pack(side="left", padx=(0, 4))
            tk.Label(row, text=name.capitalize(), bg=BG2, fg=TEXT2,
                     font=("Consolas", 8)).pack(side="left")

        es = self._section(p, "EDIT SELECTED PROCESS")
        self._edit_pid_lbl = tk.Label(es, text="No process selected",
                                      bg=BG2, fg=NEON_BLUE,
                                      font=("Consolas", 9, "bold"))
        self._edit_pid_lbl.pack(anchor="w")
        ef = tk.Frame(es, bg=BG2)
        ef.pack(fill="x", pady=4)
        self._edit_burst   = tk.StringVar()
        self._edit_prio    = tk.StringVar()
        self._edit_arrival = tk.StringVar()
        for lbl, var in [("Arrival:   ", self._edit_arrival),
                         ("Burst Time:", self._edit_burst),
                         ("Priority:  ", self._edit_prio)]:
            r = tk.Frame(ef, bg=BG2)
            r.pack(fill="x", pady=2)
            tk.Label(r, text=lbl, bg=BG2, fg=TEXT2,
                     font=("Consolas", 9), width=11, anchor="w").pack(side="left")
            tk.Entry(r, textvariable=var, bg=INPUT_BG, fg=TEXT1,
                     insertbackground=TEXT1, relief="flat",
                     font=("Consolas", 10), width=8,
                     highlightthickness=1, highlightcolor=NEON_BLUE,
                     highlightbackground=BORDER).pack(side="left", fill="x", expand=True)
        self._btn(es, "Apply Changes", self._apply_edit, NEON_BLUE).pack(
            fill="x", pady=(4, 0))

    # ── HELPERS ──────────────────────────────────────────────────────────────
    def _section(self, parent, title):
        f = tk.Frame(parent, bg=BG2)
        f.pack(fill="x", padx=8, pady=(0, 4))
        hdr = tk.Frame(f, bg=BG2)
        hdr.pack(fill="x")
        tk.Label(hdr, text=title, bg=BG2, fg=NEON_CYAN,
                 font=("Consolas", 8, "bold")).pack(side="left", pady=(10, 2))
        tk.Frame(f, bg=BORDER, height=1).pack(fill="x", pady=(0, 5))
        return f

    def _btn(self, parent, text, cmd, color, px=0):
        fg = BG if color not in (TEXT3, TEXT2) else TEXT1
        return tk.Button(parent, text=text, command=cmd,
                         bg=color, fg=fg, activebackground=color,
                         font=("Consolas", 9, "bold"), relief="flat",
                         padx=8 + px, pady=6, cursor="hand2", borderwidth=0)

    # ── DRAWING ──────────────────────────────────────────────────────────────
    def _draw_gantt(self, gantt: List[GanttBlock], t: float):
        c = self._gantt_canvas
        c.delete("all")

        MARGIN_LEFT = 8
        bar_h, y0   = 40, 14
        y1          = y0 + bar_h
        canvas_w    = c.winfo_width() or 900

        if not gantt:
            total_w = max(canvas_w, 200)
            c.configure(scrollregion=(0, 0, total_w, 110))
            c.create_line(MARGIN_LEFT, y1 + 3, MARGIN_LEFT, y1 + 10, fill=BORDER2)
            c.create_text(MARGIN_LEFT, y1 + 18, text="0",
                          fill=TEXT2, font=("Consolas", 7))
            return

        max_t = max(b.end for b in gantt)
        if max_t <= 0:
            return

        natural_w      = canvas_w - MARGIN_LEFT - 20
        min_px_per_unit = 40
        scale  = max(natural_w / max_t, min_px_per_unit)
        total_w = int(MARGIN_LEFT + max_t * scale + 40)
        c.configure(scrollregion=(0, 0, max(total_w, canvas_w), 110))

        # t=0 marker
        c.create_line(MARGIN_LEFT, y0 - 4, MARGIN_LEFT, y1 + 10,
                      fill=BORDER2, width=1)
        c.create_text(MARGIN_LEFT, y1 + 18, text="0",
                      fill=TEXT2, font=("Consolas", 7))

        # blocks
        for b in gantt:
            x0 = MARGIN_LEFT + b.start * scale
            x1 = MARGIN_LEFT + b.end   * scale
            if x1 - x0 < 0.5:
                continue
            color = b.color if b.pid != -1 else TEXT3
            c.create_rectangle(x0, y0, x1, y1, fill=color, outline="")
            c.create_rectangle(x0, y1, x1, y1 + 3,
                               fill=color, outline="", stipple="gray50")
            if x1 - x0 > 20 and b.pid != -1:
                nm = b.name if x1 - x0 > 38 else b.name[:2]
                c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=nm,
                              fill="white" if color != TEXT3 else TEXT2,
                              font=("Consolas", 8, "bold"))

        # time ticks
        step = max(1, int(max_t / 20))
        for tick in range(step, int(max_t) + 2, step):
            x = MARGIN_LEFT + tick * scale
            c.create_line(x, y1 + 3, x, y1 + 10, fill=BORDER2)
            c.create_text(x, y1 + 18, text=str(tick),
                          fill=TEXT2, font=("Consolas", 7))

        # current-time cursor
        if t <= max_t:
            cx = MARGIN_LEFT + t * scale
            c.create_line(cx, y0 - 4, cx, y1 + 14,
                          fill=NEON_CYAN, width=2, dash=(4, 3))

    def _draw_mlfq_gantt(self, gantt: List[GanttBlock], t: float, n_levels: int):
        c = self._mlfq_gantt_canvas
        c.delete("all")
        if not gantt:
            return
        max_t = max(b.end for b in gantt)
        if max_t <= 0:
            return

        w       = c.winfo_width() or 800
        scale   = max(w - 80, 600) / max_t
        row_h   = 28
        y_start = 6
        colors_q = [NEON_GREEN, NEON_ORANGE, NEON_RED, NEON_PURPLE,
                    NEON_CYAN, NEON_YELLOW]

        for lvl in range(n_levels):
            y0 = y_start + lvl * (row_h + 4)
            y1 = y0 + row_h
            lcolor = colors_q[lvl % len(colors_q)]
            c.create_text(28, (y0 + y1) / 2, text=f"Q{lvl}",
                          fill=lcolor, font=("Consolas", 8, "bold"), anchor="center")
            c.create_rectangle(42, y0, w - 4, y1, fill=INPUT_BG, outline=BORDER)
            for b in gantt:
                if b.level != lvl or b.pid == -1:
                    continue
                x0 = 42 + b.start / max_t * (w - 46)
                x1 = 42 + b.end   / max_t * (w - 46)
                x0 = max(42, min(x0, w - 4))
                x1 = max(42, min(x1, w - 4))
                if x1 - x0 < 0.5:
                    continue
                c.create_rectangle(x0, y0 + 2, x1, y1 - 2, fill=b.color, outline="")
                if x1 - x0 > 18:
                    c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=b.name[:3],
                                  fill="white", font=("Consolas", 7, "bold"))

        step = max(1, int(max_t / 15))
        for tick in range(0, int(max_t) + 2, step):
            x = 42 + tick / max_t * (w - 46)
            c.create_text(x, y_start + n_levels * (row_h + 4) + 4,
                          text=str(tick), fill=TEXT2, font=("Consolas", 7))

    def _draw_queue(self, procs):
        c = self._queue_canvas
        c.delete("all")
        w     = c.winfo_width() or 800
        ready = [p for p in procs if p.state == "ready"]
        if not ready:
            c.create_text(w // 2, 26, text="Queue empty",
                          fill=TEXT3, font=("Consolas", 10))
            return
        bw, bh, gap = 60, 36, 6
        x = 12
        y0 = 8
        for p in ready[:14]:
            c.create_rectangle(x, y0, x + bw, y0 + bh, fill=p.color, outline="")
            c.create_text(x + bw / 2, y0 + 13, text=p.name,
                          fill="white", font=("Consolas", 9, "bold"))
            c.create_text(x + bw / 2, y0 + 27, text=f"{p.remaining_time:.1f}",
                          fill="white", font=("Consolas", 7))
            if x + bw + gap + bw < w:
                c.create_text(x + bw + gap // 2, y0 + bh // 2, text="→",
                              fill=TEXT2, font=("Consolas", 10))
            x += bw + gap
        if len(ready) > 14:
            c.create_text(x + 18, y0 + bh // 2, text=f"+{len(ready)-14}",
                          fill=TEXT2, font=("Consolas", 9))

    def _draw_states(self, procs):
        c    = self._state_canvas
        c.delete("all")
        w    = c.winfo_width() or 800
        if not procs:
            return
        cols = max(3, w // 130)
        bw, bh, gx, gy = 120, 58, 6, 6
        for i, p in enumerate(procs[:24]):
            col = i % cols
            row = i // cols
            gw  = (w - cols * bw) // (cols + 1)
            x0  = gw + col * (bw + gx)
            y0  = gy + row * (bh + gy)
            sc  = STATE_COLORS.get(p.state, TEXT3)
            c.create_rectangle(x0, y0, x0 + bw, y0 + bh,
                               fill=CARD, outline=sc, width=1)
            c.create_rectangle(x0, y0, x0 + 5, y0 + bh, fill=p.color, outline="")
            c.create_oval(x0 + 11, y0 + 8, x0 + 23, y0 + 20, fill=sc, outline="")
            c.create_text(x0 + 17, y0 + 14, text=str(p.pid),
                          fill="white", font=("Consolas", 7, "bold"))
            c.create_text(x0 + 65, y0 + 16, text=p.name, fill=TEXT1,
                          font=("Consolas", 9, "bold"), anchor="center")
            c.create_text(x0 + 65, y0 + 30, text=p.state.upper(), fill=sc,
                          font=("Consolas", 7, "bold"), anchor="center")
            if p.burst_time > 0:
                bf    = bw - 14
                ratio = p.remaining_time / p.burst_time
                c.create_rectangle(x0 + 7, y0 + bh - 10,
                                   x0 + 7 + bf, y0 + bh - 4,
                                   fill=INPUT_BG, outline="")
                bl = int(bf * ratio)
                if bl > 0:
                    c.create_rectangle(x0 + 7, y0 + bh - 10,
                                       x0 + 7 + bl, y0 + bh - 4,
                                       fill=p.color, outline="")

    def _draw_mlfq_live(self, procs):
        c = self._mlfq_canvas
        c.delete("all")
        w = c.winfo_width() or 290
        n = len(self.scheduler.mlfq_queues_config)
        if n == 0:
            return
        qs = [[] for _ in range(n)]
        for p in procs:
            if p.state in ("ready", "running") and 0 <= p.queue_level < n:
                qs[p.queue_level].append(p)
        qlabels = [f"Q{i} ({self.scheduler.mlfq_queues_config[i].algorithm})"
                   for i in range(n)]
        qcolors = [NEON_GREEN, NEON_ORANGE, NEON_RED, NEON_PURPLE, NEON_CYAN, NEON_YELLOW]
        row_h   = min(32, 120 // max(n, 1))
        for i, (q, lbl, col) in enumerate(zip(qs, qlabels, qcolors)):
            y = 6 + i * row_h
            c.create_text(8, y + row_h // 2, text=lbl,
                          fill=col, font=("Consolas", 8, "bold"), anchor="w")
            c.create_rectangle(100, y + 3, w - 6, y + row_h - 3,
                               fill=INPUT_BG, outline=BORDER)
            x = 103
            for p2 in q[:7]:
                bw2 = 26
                c.create_rectangle(x, y + 5, x + bw2, y + row_h - 5,
                                   fill=p2.color, outline="")
                c.create_text(x + bw2 // 2, y + row_h // 2, text=p2.name[:3],
                              fill="white", font=("Consolas", 7, "bold"))
                x += bw2 + 2
                if x < w - 30:
                    c.create_text(x, y + row_h // 2, text="→",
                                  fill=TEXT3, font=("Consolas", 8))
                    x += 10
        if n > 1:
            for i in range(n - 1):
                ya = 6 + i * row_h + row_h - 3
                yb = 6 + (i + 1) * row_h + 3
                c.create_line(w - 18, ya, w - 18, yb,
                              fill=qcolors[i], arrow="last",
                              width=1, arrowshape=(6, 8, 3), dash=(3, 2))
                c.create_text(w - 28, (ya + yb) // 2, text="↓",
                              fill=qcolors[i], font=("Consolas", 8))

    # ── TABLE UPDATES ────────────────────────────────────────────────────────
    def _update_table(self, procs):
        tree = self._proc_tree
        tree.delete(*tree.get_children())
        for p in procs:
            vals = (
                p.pid, p.name,
                f"{p.arrival_time:.1f}", f"{p.burst_time:.1f}",
                p.priority, f"{p.remaining_time:.2f}", p.state,
                f"{p.waiting_time:.2f}",
                f"{p.turnaround_time:.2f}" if p.finish_time else "—",
                f"{p.response_time:.2f}"   if p.response_time is not None else "—",
            )
            tree.insert("", "end", values=vals, tags=(p.state,))

    def _update_proc_list(self):
        tree = self._proc_list_tree
        tree.delete(*tree.get_children())
        for p in self.scheduler.processes:
            tree.insert("", "end", iid=str(p.pid),
                        values=(p.pid, p.name, p.arrival_time,
                                p.burst_time, p.priority, "●"),
                        tags=(str(p.pid),))
            tree.tag_configure(str(p.pid), foreground=p.color)

    def _update_metrics(self):
        m = self.scheduler.compute_metrics()
        for k, lbl in self._met_lbl.items():
            lbl.config(text=m.get(k, "—"))

    def _update_completed(self, done):
        tree = self._comp_tree
        tree.delete(*tree.get_children())
        for p in sorted(done, key=lambda x: x.finish_time or 0):
            tree.insert("", "end", values=(
                p.name,
                f"{p.arrival_time:.1f}",
                f"{p.burst_time:.1f}",
                p.priority,
                f"{p.start_time:.2f}"  if p.start_time  is not None else "—",
                f"{p.finish_time:.2f}" if p.finish_time is not None else "—",
                f"{p.waiting_time:.2f}",
                f"{p.turnaround_time:.2f}",
                f"{p.response_time:.2f}" if p.response_time is not None else "—",
            ))

    def _append_feedback(self, msg):
        t = self._feedback
        t.config(state="normal")
        tag = ("alert" if "🚨" in msg else
               "warn"  if "⚠"  in msg else
               "ok"    if "✅" in msg else "tip")
        t.insert("end", msg + "\n", tag)
        t.see("end")
        t.config(state="disabled")

    # ── EVENT SYSTEM ─────────────────────────────────────────────────────────
    def _on_event(self, ev, data):
        self._evt_queue.append((ev, data))

    def _update_loop(self):
        while self._evt_queue:
            ev, data = self._evt_queue.popleft()
            self._handle(ev, data)
        self.after(50, self._update_loop)

    def _handle(self, ev, data):
        if ev == "tick":
            t, gantt, procs, done = data
            self._clock_var.set(f"t = {t:.2f}s")
            self._draw_gantt(gantt, t)
            self._draw_queue(procs)
            self._draw_states(procs)
            self._draw_mlfq_live(procs)
            if self.scheduler.algorithm == "MLFQ":
                n = len(self.scheduler.mlfq_queues_config)
                self._draw_mlfq_gantt(gantt, t, n)
            self._update_table(procs)
            self._update_metrics()
            self._update_completed(done)

        elif ev == "adaptive":
            self._append_feedback(data)

        elif ev == "algo_switched":
            self._append_feedback(f"🔄 Algorithm → {data}")

        elif ev == "sim_done":
            gantt, done, t = data
            self._draw_gantt(gantt, t)
            self._update_metrics()
            self._update_completed(done)
            self._append_feedback("✅ Simulation completed.")

        elif ev == "reset":
            for c in (self._gantt_canvas, self._queue_canvas,
                      self._state_canvas, self._mlfq_canvas,
                      self._mlfq_gantt_canvas):
                c.delete("all")
            self._proc_tree.delete(*self._proc_tree.get_children())
            self._comp_tree.delete(*self._comp_tree.get_children())
            for lbl in self._met_lbl.values():
                lbl.config(text="—")
            self._clock_var.set("t = 0.00s")

        elif ev in ("process_added", "process_removed", "process_modified"):
            self._update_proc_list()

    # ── UI ACTIONS ───────────────────────────────────────────────────────────
    def _algo_changed(self, _=None):
        algo_map = {"FCFS": "FCFS", "SJF": "SJF", "Priority": "Priority",
                    "Round Robin": "RR", "MLFQ": "MLFQ"}
        algo = algo_map.get(self._algo_var.get(), "FCFS")

        if algo in ("SJF", "Priority"):
            self._preempt_check.config(state="normal")
        else:
            self._preempt_var.set(False)
            self._preempt_check.config(state="disabled")

        if algo == "MLFQ":
            self._mlfq_btn.pack(fill="x", pady=(4, 0))
            self._mlfq_gantt_frame.pack(fill="x", padx=8, pady=(0, 4))
        else:
            self._mlfq_btn.pack_forget()
            self._mlfq_gantt_frame.pack_forget()

        self._sync_params()
        self.scheduler.switch_algorithm(algo, self._preempt_var.get())

    def _open_mlfq_config(self):
        dlg = MLFQConfigDialog(self, self.scheduler.mlfq_queues_config)
        if dlg.result:
            self.scheduler.mlfq_queues_config = dlg.result
            self._append_feedback(
                f"💡 MLFQ reconfigured: {len(dlg.result)} queues")

    def _sync_params(self):
        try:
            self.scheduler.time_quantum = max(0.1, float(self._quantum_var.get()))
        except Exception:
            pass
        try:
            self.scheduler.aging_threshold = max(1.0, float(self._aging_var.get()))
        except Exception:
            pass

    def _speed_changed(self, _=None):
        self.scheduler.speed = round(self._speed_var.get(), 1)
        self._speed_lbl.config(text=f"{self.scheduler.speed:.1f}x")

    def _add_process(self):
        try:
            arrival  = float(self._parrival_var.get())
            burst    = float(self._pburst_var.get())
            priority = int(self._pprio_var.get())
            name     = self._pname_var.get().strip() or None
            if burst <= 0:
                raise ValueError("Burst time must be > 0")
            if arrival < 0:
                raise ValueError("Arrival time cannot be negative")

            if self._last_was_random and self.scheduler.processes:
                pids = [p.pid for p in self.scheduler.processes]
                for pid in pids:
                    self.scheduler.remove_process(pid)
                self.scheduler._pid_counter = 1
                self._parrival_var.set("0")
                arrival = 0.0
                self._append_feedback("🗑 Random processes cleared — starting fresh.")
                self._last_was_random = False

            self.scheduler.add_process(arrival, burst, priority, name)
            self._parrival_var.set(str(round(arrival + random.uniform(0, 2), 1)))
        except Exception as e:
            messagebox.showerror("Invalid Input", str(e), parent=self)

    def _add_random_dialog(self):
        if self.scheduler.processes:
            answer = messagebox.askyesnocancel(
                "Existing Processes",
                f"You already have {len(self.scheduler.processes)} process(es).\n\n"
                "Yes   → Clear them and add fresh random ones\n"
                "No    → Keep them and add random ones on top\n"
                "Cancel → Abort",
                parent=self)
            if answer is None:
                return
            if answer is True:
                pids = [p.pid for p in self.scheduler.processes]
                for pid in pids:
                    self.scheduler.remove_process(pid)
                self.scheduler._pid_counter = 1
                self._append_feedback("🗑 Cleared all previous processes.")

        count = simpledialog.askinteger(
            "Random Processes", "How many random processes to add?",
            parent=self, minvalue=1, maxvalue=20)
        if count:
            for _ in range(count):
                self.scheduler.add_process(
                    arrival=round(random.uniform(0, 12), 1),
                    burst=round(random.uniform(1, 14), 1),
                    priority=random.randint(1, 5))
            self._append_feedback(f"🎲 Added {count} random processes.")
            self._last_was_random = True

    def _start(self):
        self._sync_params()
        self._algo_changed()
        if not self.scheduler.processes:
            messagebox.showinfo("No Processes",
                                "Please add processes first!\n\n"
                                "Use '＋ Add Process' or '🎲 Random' buttons.",
                                parent=self)
            return
        self.scheduler.start()

    def _toggle_pause(self):
        if self.scheduler.paused:
            self.scheduler.resume()
            self._pause_btn.config(text="⏸  Pause")
        else:
            self.scheduler.pause()
            self._pause_btn.config(text="▶  Resume")

    def _stop(self):
        self.scheduler.stop()

    def _reset(self):
        self.scheduler.reset()
        self.scheduler._pid_counter = 1
        self._last_was_random = False
        self._parrival_var.set("0")
        self._pause_btn.config(text="⏸  Pause")
        self._feedback.config(state="normal")
        self._feedback.delete("1.0", "end")
        self._feedback.config(state="disabled")

    def _show_proc_menu(self, event):
        row = self._proc_list_tree.identify_row(event.y)
        if row:
            self._proc_list_tree.selection_set(row)
            self._proc_menu.post(event.x_root, event.y_root)

    def _edit_proc_list(self):
        sel = self._proc_list_tree.selection()
        if not sel:
            return
        pid  = int(self._proc_list_tree.item(sel[0], "values")[0])
        proc = next((p for p in self.scheduler.processes if p.pid == pid), None)
        if not proc:
            return
        self._current_edit_pid = pid
        self._edit_pid_lbl.config(text=f"Editing: {proc.name} (PID {pid})")
        self._edit_arrival.set(str(proc.arrival_time))
        self._edit_burst.set(str(proc.burst_time))
        self._edit_prio.set(str(proc.priority))

    def _remove_proc_list(self):
        sel = self._proc_list_tree.selection()
        if not sel:
            return
        pid = int(self._proc_list_tree.item(sel[0], "values")[0])
        if messagebox.askyesno("Confirm", f"Remove process PID {pid}?", parent=self):
            self.scheduler.remove_process(pid)

    def _apply_edit(self):
        pid = getattr(self, "_current_edit_pid", None)
        if pid is None:
            messagebox.showinfo("No Selection",
                                "Select a process from the Processes tab first.",
                                parent=self)
            return
        try:
            arr = float(self._edit_arrival.get())
            b   = float(self._edit_burst.get())
            pr  = int(self._edit_prio.get())
            if b <= 0:
                raise ValueError("Burst must be > 0")
            if arr < 0:
                raise ValueError("Arrival cannot be negative")
            self.scheduler.modify_process(pid, arrival_time=arr, burst_time=b, priority=pr)
            self._edit_pid_lbl.config(text="Changes applied ✓")
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)


# ══════════════════════════════ ENTRY POINT ═══════════════════════════════════
if __name__ == "__main__":
    app = App()
    app.mainloop()