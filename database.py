import sqlite3

conn = sqlite3.connect("workout.db")
cursor = conn.cursor()

# sab tables ka naam nikalega
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")

tables = cursor.fetchall()

print("Tables in database:")
for table in tables:
    print(table[0])

conn.close()