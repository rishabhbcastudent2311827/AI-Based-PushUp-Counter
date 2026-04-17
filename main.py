import cv2
import time
import sqlite3
import numpy as np
import tkinter as tk
from tkinter import ttk, messagebox
import mediapipe as mp
import os, hashlib, base64

# ---------------- SETTINGS ----------------
DB_FILE = "workout.db"
CAL_PER_PUSHUP = 0.29

mp_pose = mp.solutions.pose
mp_draw = mp.solutions.drawing_utils

# ---------------- SECURITY ----------------
def hash_password(password, salt=None):
    if salt is None:
        salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000)
    return base64.b64encode(salt).decode(), base64.b64encode(dk).decode()

def verify_password(password, salt_b64, hash_b64):
    salt = base64.b64decode(salt_b64)
    _, new_hash = hash_password(password, salt)
    return new_hash == hash_b64

# ---------------- DATABASE ----------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        salt TEXT,
        passhash TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        created_at TEXT,
        duration INTEGER,
        pushups INTEGER,
        calories REAL
    )""")

    conn.commit()
    conn.close()

def create_user(u, p):
    u = u.strip().lower()
    if len(u) < 3 or len(p) < 3:
        return False
    salt, h = hash_password(p)
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.execute("INSERT INTO users(username,salt,passhash) VALUES(?,?,?)",(u,salt,h))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def login_user(u,p):
    u = u.strip().lower()
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT id,salt,passhash FROM users WHERE username=?",(u,))
    row = cur.fetchone()
    conn.close()
    if row and verify_password(p,row[1],row[2]):
        return row[0]
    return None

def save_session(uid, dur, push, cal):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO sessions (user_id, created_at, duration, pushups, calories)
        VALUES (?, datetime('now'), ?, ?, ?)
    """, (uid, dur, push, cal))
    conn.commit()
    conn.close()

def fetch_sessions(uid):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        SELECT created_at, duration, pushups, calories
        FROM sessions
        WHERE user_id=?
        ORDER BY id DESC
    """,(uid,))
    data = cur.fetchall()
    conn.close()
    return data

# ---------------- ANGLE ----------------
def calculate_angle(a,b,c):
    a=np.array(a); b=np.array(b); c=np.array(c)
    radians=np.arctan2(c[1]-b[1],c[0]-b[0]) - np.arctan2(a[1]-b[1],a[0]-b[0])
    angle=abs(radians*180.0/np.pi)
    if angle>180: angle=360-angle
    return angle

# ---------------- PUSHUP APP ----------------
class PushupApp:
    def __init__(self, root, uid, username):
        self.root = root
        self.uid = uid
        self.username = username

        self.count = 0
        self.stage = "up"
        self.cap = None
        self.start_time = None
        self.running = False

        self.root.title(f"AI Push-Up Counter - {username}")
        self.root.geometry("800x600")

        self.label = tk.Label(root,text="Push-Ups: 0",font=("Arial",30,"bold"))
        self.label.pack(pady=20)

        self.cal_label = tk.Label(root,text="Calories: 0.00",font=("Arial",18))
        self.cal_label.pack()

        tk.Button(root,text="Start",width=20,command=self.start).pack(pady=5)
        tk.Button(root,text="Stop & Save",width=20,command=self.stop).pack(pady=5)
        tk.Button(root,text="View History",width=20,command=self.history).pack(pady=5)

        self.pose = mp_pose.Pose()

    def start(self):
        if self.running:
            return

        self.count = 0
        self.label.config(text="Push-Ups: 0")
        self.cal_label.config(text="Calories: 0.00")

        self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        time.sleep(0.5)

        self.start_time = time.time()
        self.running = True

        self.update_frame()

    def update_frame(self):
        if self.running and self.cap:
            ret, frame = self.cap.read()
            if ret:
                frame=cv2.flip(frame,1)
                rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
                res=self.pose.process(rgb)

                if res.pose_landmarks:
                    lm=res.pose_landmarks.landmark

                    rs=[lm[12].x,lm[12].y]
                    re=[lm[14].x,lm[14].y]
                    rw=[lm[16].x,lm[16].y]

                    ls=[lm[11].x,lm[11].y]
                    le=[lm[13].x,lm[13].y]
                    lw=[lm[15].x,lm[15].y]

                    angle=(calculate_angle(rs,re,rw)+calculate_angle(ls,le,lw))/2

                    if angle>160:
                        self.stage="up"

                    if angle<90 and self.stage=="up":
                        self.stage="down"
                        self.count+=1

                        self.label.config(text=f"Push-Ups: {self.count}")
                        calories=self.count*CAL_PER_PUSHUP
                        self.cal_label.config(text=f"Calories: {calories:.2f}")

                    mp_draw.draw_landmarks(frame,res.pose_landmarks,mp_pose.POSE_CONNECTIONS)

                cv2.putText(frame,f'Count: {self.count}',(10,40),
                            cv2.FONT_HERSHEY_SIMPLEX,1,(0,255,0),2)

                cv2.imshow("Camera",frame)

        if self.running:
            self.root.after(10,self.update_frame)

    def stop(self):
        if not self.running:
            return

        self.running = False

        if self.cap:
            self.cap.release()
            self.cap = None

        cv2.destroyAllWindows()

        duration=int(time.time()-self.start_time)
        calories=self.count*CAL_PER_PUSHUP

        save_session(self.uid,duration,self.count,calories)

        messagebox.showinfo("Saved","Workout saved successfully!")

    def history(self):
        win=tk.Toplevel(self.root)
        win.title("History")

        tree=ttk.Treeview(win,columns=("date","dur","push","cal"),show="headings")
        for c in ("date","dur","push","cal"):
            tree.heading(c,text=c)
        tree.pack(fill="both",expand=True)

        data=fetch_sessions(self.uid)

        if not data:
            messagebox.showinfo("Empty","No history found")
            return

        for r in data:
            tree.insert("", "end", values=r)

# ---------------- LOGIN ----------------
class LoginWindow:
    def __init__(self,root):
        self.root=root
        self.root.geometry("420x350")
        self.root.configure(bg="#e6e6e6")

        init_db()

        card=tk.Frame(root,bg="white")
        card.place(relx=0.5,rely=0.5,anchor="center",width=320,height=280)

        tk.Label(card,text="AI PUSH-UP COUNTER",
                 font=("Arial",16,"bold"),bg="white").pack(pady=5)

        tk.Label(card,text="Login",
                 font=("Arial",18,"bold"),bg="white").pack(pady=5)

        self.u=tk.StringVar()
        self.p=tk.StringVar()
        self.show_pass=tk.BooleanVar()

        tk.Entry(card,textvariable=self.u,font=("Arial",12),width=25).pack(pady=8)

        self.pass_entry=tk.Entry(card,textvariable=self.p,show="*",font=("Arial",12),width=25)
        self.pass_entry.pack(pady=8)

        tk.Checkbutton(card,text="Show Password",variable=self.show_pass,
                       command=self.toggle_password,bg="white").pack()

        tk.Button(card,text="Login",bg="green",fg="white",
                  width=15,command=self.login).pack(pady=8)

        tk.Button(card,text="Register",bg="blue",fg="white",
                  width=15,command=self.register).pack()

    def toggle_password(self):
        self.pass_entry.config(show="" if self.show_pass.get() else "*")

    def register(self):
        if create_user(self.u.get(),self.p.get()):
            messagebox.showinfo("Success","Registered Successfully")
        else:
            messagebox.showerror("Error","User exists or invalid")

    def login(self):
        uid=login_user(self.u.get(),self.p.get())
        if uid:
            for w in self.root.winfo_children():
                w.destroy()
            PushupApp(self.root,uid,self.u.get())
        else:
            messagebox.showerror("Error","Wrong Username/Password")

# ---------------- MAIN ----------------
root=tk.Tk()
LoginWindow(root)
root.mainloop()