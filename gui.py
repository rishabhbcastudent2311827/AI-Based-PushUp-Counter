import cv2
import time
import sqlite3
import threading
import queue
import numpy as np
import tkinter as tk
from tkinter import ttk, messagebox
import mediapipe as mp

# -------------------- SETTINGS --------------------
CAMERA_INDEX = 0
USE_DSHOW = True  # Windows ke liye stable

UP_ANGLE = 165       # "up" threshold
DOWN_ANGLE = 95      # "down" threshold
DOWN_HOLD_SEC = 0.35 # false count avoid (minimum down hold)

CAL_PER_PUSHUP = 0.29
DB_FILE = "workout.db"


# -------------------- DB --------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            duration_sec INTEGER NOT NULL,
            pushups INTEGER NOT NULL,
            calories REAL NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def save_session(duration_sec: int, pushups: int, calories: float):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sessions (created_at, duration_sec, pushups, calories) VALUES (datetime('now'), ?, ?, ?)",
        (duration_sec, pushups, round(calories, 2))
    )
    conn.commit()
    conn.close()


def fetch_sessions(limit=50):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute(
        "SELECT created_at, duration_sec, pushups, calories FROM sessions ORDER BY id DESC LIMIT ?",
        (limit,)
    )
    rows = cur.fetchall()
    conn.close()
    return rows


# -------------------- VOICE --------------------
class Voice:
    def __init__(self):
        self.enabled = False
        self.q = queue.Queue()
        self.engine = None

        try:
            import pyttsx3
            self.engine = pyttsx3.init()
            self.engine.setProperty("rate", 160)

            def worker():
                while True:
                    text = self.q.get()
                    try:
                        if self.enabled:
                            self.engine.say(text)
                            self.engine.runAndWait()
                    except Exception:
                        pass
                    finally:
                        self.q.task_done()

            threading.Thread(target=worker, daemon=True).start()
        except Exception:
            self.engine = None

    def speak(self, text: str):
        if self.engine is None:
            return
        self.q.put(text)


# -------------------- MATH --------------------
def calculate_angle(a, b, c):
    a, b, c = np.array(a), np.array(b), np.array(c)
    radians = np.arctan2(c[1] - b[1], c[0] - b[0]) - np.arctan2(a[1] - b[1], a[0] - b[0])
    angle = abs(radians * 180.0 / np.pi)
    return 360 - angle if angle > 180 else angle


# -------------------- APP --------------------
class PushupApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Push-Up Counter (GUI + DB)")
        self.root.geometry("980x620")  # ✅ FIXED (quotes needed)

        init_db()

        self.voice = Voice()

        # Mediapipe Pose
        self.mp_pose = mp.solutions.pose
        self.pose = self.mp_pose.Pose(min_detection_confidence=0.6, min_tracking_confidence=0.6)
        self.mp_draw = mp.solutions.drawing_utils

        # Camera
        self.cap = None

        # Session stats
        self.running = False
        self.count = 0
        self.stage = "up"
        self.lock = False
        self.down_start = None
        self.session_start = None

        # UI
        self._build_ui()

        # loop
        self.root.after(30, self.update_frame)

    def _build_ui(self):
        left = ttk.Frame(self.root, padding=10)
        left.pack(side="left", fill="both", expand=True)

        self.video_label = ttk.Label(left, text="Camera Preview")
        self.video_label.pack(fill="both", expand=True)

        right = ttk.Frame(self.root, padding=10)
        right.pack(side="right", fill="y")

        ttk.Label(right, text="AI Push-Up Counter", font=("Arial", 18, "bold")).pack(pady=(0, 10))

        self.count_var = tk.StringVar(value="0")
        self.cal_var = tk.StringVar(value="0.00")
        self.time_var = tk.StringVar(value="00:00")

        ttk.Label(right, text="Push-Ups", font=("Arial", 12, "bold")).pack(anchor="w")
        ttk.Label(right, textvariable=self.count_var, font=("Arial", 28, "bold")).pack(anchor="w", pady=(0, 10))

        ttk.Label(right, text="Calories (est.)", font=("Arial", 12, "bold")).pack(anchor="w")
        ttk.Label(right, textvariable=self.cal_var, font=("Arial", 18)).pack(anchor="w", pady=(0, 10))

        ttk.Label(right, text="Session Time", font=("Arial", 12, "bold")).pack(anchor="w")
        ttk.Label(right, textvariable=self.time_var, font=("Arial", 18)).pack(anchor="w", pady=(0, 15))

        btn_row = ttk.Frame(right)
        btn_row.pack(fill="x", pady=5)

        self.start_btn = ttk.Button(btn_row, text="Start", command=self.start)
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 6))

        self.stop_btn = ttk.Button(btn_row, text="Stop & Save", command=self.stop_and_save, state="disabled")
        self.stop_btn.pack(side="left", expand=True, fill="x", padx=(6, 0))

        self.reset_btn = ttk.Button(right, text="Reset Counter", command=self.reset)
        self.reset_btn.pack(fill="x", pady=6)

        self.voice_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text="Voice Count (TTS)", variable=self.voice_var, command=self.toggle_voice).pack(
            anchor="w", pady=(6, 10)
        )

        ttk.Separator(right).pack(fill="x", pady=10)

        ttk.Button(right, text="View History", command=self.show_history).pack(fill="x")

        ttk.Label(
            right,
            text="Tip: Side angle + good light = better counting.\nIf camera not showing, close Zoom/Meet/Camera apps.",
            font=("Arial", 9)
        ).pack(pady=12)

    def toggle_voice(self):
        self.voice.enabled = bool(self.voice_var.get())
        if self.voice.enabled and self.voice.engine is None:
            messagebox.showwarning("Voice not available", "pyttsx3/TTS is not working on this system.")

    def open_camera(self):
        if self.cap is not None:
            return True

        if USE_DSHOW:
            self.cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
        else:
            self.cap = cv2.VideoCapture(CAMERA_INDEX)

        time.sleep(0.6)
        if not self.cap.isOpened():
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
            return False
        return True

    def start(self):
        if not self.open_camera():
            messagebox.showerror(
                "Camera Error",
                "Camera open nahi ho raha.\nZoom/Meet/Camera app band karke try karo.\nAgar phir bhi nahi ho, CAMERA_INDEX=1 try karo."
            )
            return

        self.running = True
        self.session_start = time.time()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")

    def stop_and_save(self):
        if not self.running:
            return

        self.running = False
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

        duration = int(time.time() - self.session_start) if self.session_start else 0
        calories = self.count * CAL_PER_PUSHUP
        save_session(duration, self.count, calories)

        messagebox.showinfo(
            "Saved",
            f"Session saved!\nPush-ups: {self.count}\nCalories: {calories:.2f}\nTime: {self.format_time(duration)}"
        )

    def release_camera(self):
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
        self.cap = None

    def reset(self):
        self.count = 0
        self.stage = "up"
        self.lock = False
        self.down_start = None
        self.count_var.set("0")
        self.cal_var.set("0.00")

    def format_time(self, sec: int) -> str:
        m = sec // 60
        s = sec % 60
        return f"{m:02d}:{s:02d}"

    def show_history(self):
        win = tk.Toplevel(self.root)
        win.title("Workout History")
        win.geometry("720x380")

        cols = ("Date/Time", "Duration", "Push-ups", "Calories")
        tree = ttk.Treeview(win, columns=cols, show="headings")
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=220 if c == "Date/Time" else 140, anchor="center")
        tree.pack(fill="both", expand=True, padx=10, pady=10)

        rows = fetch_sessions(50)
        for created_at, duration_sec, pushups, calories in rows:
            tree.insert("", "end", values=(created_at, self.format_time(duration_sec), pushups, f"{calories:.2f}"))

        ttk.Label(win, text="Latest sessions shown (saved on Stop & Save).").pack(pady=(0, 10))

    def process_pushup_logic(self, avg_angle):
        # Up
        if avg_angle > UP_ANGLE:
            if self.stage == "down" and self.lock:
                self.count += 1
                self.lock = False
                self.count_var.set(str(self.count))
                self.cal_var.set(f"{self.count * CAL_PER_PUSHUP:.2f}")
                self.voice.speak(str(self.count))

            self.stage = "up"
            self.down_start = None

        # Down + hold
        if avg_angle < DOWN_ANGLE and self.stage == "up":
            if self.down_start is None:
                self.down_start = time.time()
            elif time.time() - self.down_start >= DOWN_HOLD_SEC:
                self.stage = "down"
                self.lock = True

    def update_frame(self):
        # timer
        if self.running and self.session_start:
            elapsed = int(time.time() - self.session_start)
            self.time_var.set(self.format_time(elapsed))

        frame = None
        if self.cap is not None:
            ret, frame = self.cap.read()
            if not ret:
                frame = None

        if frame is not None:
            frame = cv2.flip(frame, 1)

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = self.pose.process(rgb)

            if result.pose_landmarks:
                lm = result.pose_landmarks.landmark

                rs = [lm[self.mp_pose.PoseLandmark.RIGHT_SHOULDER].x, lm[self.mp_pose.PoseLandmark.RIGHT_SHOULDER].y]
                re = [lm[self.mp_pose.PoseLandmark.RIGHT_ELBOW].x, lm[self.mp_pose.PoseLandmark.RIGHT_ELBOW].y]
                rw = [lm[self.mp_pose.PoseLandmark.RIGHT_WRIST].x, lm[self.mp_pose.PoseLandmark.RIGHT_WRIST].y]

                ls = [lm[self.mp_pose.PoseLandmark.LEFT_SHOULDER].x, lm[self.mp_pose.PoseLandmark.LEFT_SHOULDER].y]
                le = [lm[self.mp_pose.PoseLandmark.LEFT_ELBOW].x, lm[self.mp_pose.PoseLandmark.LEFT_ELBOW].y]
                lw = [lm[self.mp_pose.PoseLandmark.LEFT_WRIST].x, lm[self.mp_pose.PoseLandmark.LEFT_WRIST].y]

                right_angle = calculate_angle(rs, re, rw)
                left_angle = calculate_angle(ls, le, lw)
                avg_angle = (right_angle + left_angle) / 2

                if self.running:
                    self.process_pushup_logic(avg_angle)

                self.mp_draw.draw_landmarks(frame, result.pose_landmarks, self.mp_pose.POSE_CONNECTIONS)
                cv2.putText(frame, f"Angle: {int(avg_angle)}", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                cv2.putText(frame, f"Stage: {self.stage}", (10, 65),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

            # show in tkinter (no pillow)
            ok, buf = cv2.imencode(".png", frame)
            if ok:
                img = tk.PhotoImage(data=buf.tobytes())
                self.video_label.configure(image=img)
                self.video_label.image = img

        self.root.after(30, self.update_frame)


def main():
    root = tk.Tk()
    app = PushupApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (app.release_camera(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()