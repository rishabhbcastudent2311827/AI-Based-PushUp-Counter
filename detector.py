import cv2
import mediapipe as mp
import numpy as np
import time
import pyttsx3
import threading
import queue

# ================= VOICE SYSTEM =================
speech_queue = queue.Queue()
engine = pyttsx3.init()
engine.setProperty('rate', 160)

def voice_worker():
    while True:
        text = speech_queue.get()
        engine.say(text)
        engine.runAndWait()
        speech_queue.task_done()

threading.Thread(target=voice_worker, daemon=True).start()

# ================= ANGLE FUNCTION =================
def calculate_angle(a, b, c):
    a, b, c = np.array(a), np.array(b), np.array(c)
    radians = np.arctan2(c[1]-b[1], c[0]-b[0]) - \
              np.arctan2(a[1]-b[1], a[0]-b[0])
    angle = abs(radians * 180.0 / np.pi)
    return 360-angle if angle > 180 else angle

# ================= MEDIAPIPE =================
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(min_detection_confidence=0.6,
                    min_tracking_confidence=0.6)
mp_draw = mp.solutions.drawing_utils

# ================= CAMERA (FIXED FOR WINDOWS) =================
cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
time.sleep(2)

if not cap.isOpened():
    print("❌ Camera open nahi ho raha")
    exit()

count = 0
stage = "up"
lock = False
down_start = None

# ================= MAIN LOOP =================
while True:
    ret, frame = cap.read()
    if not ret:
        continue

    frame = cv2.flip(frame, 1)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = pose.process(rgb)

    if result.pose_landmarks:
        lm = result.pose_landmarks.landmark

        rs = [lm[mp_pose.PoseLandmark.RIGHT_SHOULDER].x,
              lm[mp_pose.PoseLandmark.RIGHT_SHOULDER].y]
        re = [lm[mp_pose.PoseLandmark.RIGHT_ELBOW].x,
              lm[mp_pose.PoseLandmark.RIGHT_ELBOW].y]
        rw = [lm[mp_pose.PoseLandmark.RIGHT_WRIST].x,
              lm[mp_pose.PoseLandmark.RIGHT_WRIST].y]

        ls = [lm[mp_pose.PoseLandmark.LEFT_SHOULDER].x,
              lm[mp_pose.PoseLandmark.LEFT_SHOULDER].y]
        le = [lm[mp_pose.PoseLandmark.LEFT_ELBOW].x,
              lm[mp_pose.PoseLandmark.LEFT_ELBOW].y]
        lw = [lm[mp_pose.PoseLandmark.LEFT_WRIST].x,
              lm[mp_pose.PoseLandmark.LEFT_WRIST].y]

        avg_angle = (calculate_angle(rs, re, rw) +
                     calculate_angle(ls, le, lw)) / 2

        # -------- PUSH-UP LOGIC --------
        if avg_angle > 165:
            if stage == "down" and lock:
                count += 1
                speech_queue.put(str(count))
                lock = False
            stage = "up"
            down_start = None

        if avg_angle < 95 and stage == "up":
            if down_start is None:
                down_start = time.time()
            elif time.time() - down_start > 0.4:
                stage = "down"
                lock = True

        mp_draw.draw_landmarks(frame, result.pose_landmarks,
                               mp_pose.POSE_CONNECTIONS)

    calories = round(count * 0.29, 2)

    # ================= UI =================
    cv2.rectangle(frame, (0, 0), (320, 120), (0, 0, 0), -1)
    cv2.putText(frame, "AI Push-up Counter",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,255), 2)
    cv2.putText(frame, f"Count: {count}",
                (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0,255,0), 3)
    cv2.putText(frame, f"Calories: {calories}",
                (10, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,255), 2)

    cv2.imshow("Professional AI Push-up Counter (Q to Exit)", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
