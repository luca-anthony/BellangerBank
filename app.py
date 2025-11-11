import json
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from datetime import datetime, timedelta
from markupsafe import escape
from zoneinfo import ZoneInfo
import os, io, zipfile

app = Flask(__name__)
app.secret_key = "change_this_secret"

# --- Interest rate ---
DEFAULT_INTEREST_RATE = 0.05

# --- Timezone ---
CENTRAL_TZ = ZoneInfo("America/Chicago")

# --- Paths ---
USERS_FILE = "users.json"

# --- Load users ---
if os.path.exists(USERS_FILE):
    with open(USERS_FILE, "r") as f:
        USERS = json.load(f)
else:
    USERS = {
        "users": {
            "admin": {"password": "ADMIN829381", "role": "admin"},
            "dev": {"password": "luca09182", "role": "developer"}
        },
        "classes": {}
    }

# --- Save helper ---
def save_users():
    with open(USERS_FILE, "w") as f:
        json.dump(USERS, f, indent=4, default=str)

# --- Routes ---

# Home page: show classes + dev/admin
@app.route('/')
def index():
    return render_template("index.html", classes=USERS.get("classes", {}), USERS=USERS)

# Show students in a class
@app.route('/class/<class_name>')
def class_select(class_name):
    class_name = escape(class_name)
    if class_name not in USERS.get("classes", {}):
        flash("Unknown class.")
        return redirect(url_for('index'))
    students = USERS["classes"][class_name]["students"]
    return render_template("class_select.html", class_name=class_name, students=students)

# Student login page
@app.route('/user/<class_name>/<username>')
def user_password_page(class_name, username):
    class_name = escape(class_name)
    username = escape(username)
    if class_name not in USERS["classes"] or username not in USERS["classes"][class_name]["students"]:
        flash("Unknown student.")
        return redirect(url_for('index'))
    return render_template("password.html", username=username, class_name=class_name)

# Authenticate student
@app.route('/auth/<class_name>/<username>', methods=['POST'])
def authenticate(class_name, username):
    class_name = escape(class_name)
    username = escape(username)
    entered = request.form.get("password", "")
    student_data = USERS["classes"][class_name]["students"].get(username)
    if student_data and entered == student_data["password"]:
        session["user"] = username
        session["class"] = class_name
        return redirect(url_for("student"))
    else:
        flash("Incorrect password.")
        return redirect(url_for('user_password_page', class_name=class_name, username=username))

# Logout
@app.route('/logout')
def logout():
    session.pop("user", None)
    session.pop("class", None)
    flash("Logged out.")
    return redirect(url_for('index'))

# Admin panel: view students, adjust balances
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if "user" not in session or USERS["users"].get(session["user"], {}).get("role") != "admin":
        flash("Admin access required.")
        return redirect(url_for('index'))

    if request.method == "POST" and 'amount' in request.form:
        class_name = request.form.get("class")
        target = request.form.get("student")
        try:
            amount = float(request.form.get("amount", 0))
        except ValueError:
            amount = 0
        if class_name in USERS["classes"] and target in USERS["classes"][class_name]["students"]:
            USERS["classes"][class_name]["students"][target]["balance"] += amount
            save_users()
            flash(f"Added ${amount:.2f} to {target}'s balance.")
        else:
            flash("Invalid student.")

    return render_template("admin.html", classes=USERS.get("classes", {}))

# Add new class
@app.route('/add_class', methods=['GET', 'POST'])
def add_class():
    if "user" not in session or USERS["users"].get(session["user"], {}).get("role") != "admin":
        flash("Admin access required.")
        return redirect(url_for('index'))

    if request.method == "POST":
        class_name = request.form.get("class_name").strip()
        students = request.form.get("students")
        if not class_name:
            flash("Class name required.")
        elif class_name in USERS.get("classes", {}):
            flash("Class already exists.")
        else:
            USERS.setdefault("classes", {})[class_name] = {"students": {}}
            for student in students.split(","):
                s = student.strip()
                if s:
                    USERS["classes"][class_name]["students"][s] = {
                        "password": s+"pw",
                        "role": "student",
                        "balance": 100,
                        "savings_balance": 0,
                        "lock_until": None,
                        "orders": []
                    }
            save_users()
            flash(f"Class {class_name} added with students: {students}")
    return render_template("add_class.html")

# Add students to existing class
@app.route('/add_student', methods=['GET', 'POST'])
def add_student():
    if "user" not in session or USERS["users"].get(session["user"], {}).get("role") != "admin":
        flash("Admin access required.")
        return redirect(url_for('index'))

    if request.method == "POST":
        class_name = request.form.get("class_name")
        students = request.form.get("students")
        if class_name not in USERS["classes"]:
            flash("Class does not exist.")
        else:
            for s in students.split(","):
                s = s.strip()
                if s and s not in USERS["classes"][class_name]["students"]:
                    USERS["classes"][class_name]["students"][s] = {
                        "password": s+"pw",
                        "role": "student",
                        "balance": 100,
                        "savings_balance": 0,
                        "lock_until": None,
                        "orders": []
                    }
            save_users()
            flash(f"Added students: {students} to {class_name}")
    return render_template("add_student.html", classes=USERS.get("classes", {}))

# Student dashboard
@app.route('/student', methods=['GET', 'POST'])
def student():
    if "user" not in session or "class" not in session:
        return redirect(url_for('index'))
    class_name = session["class"]
    user = session["user"]
    student_data = USERS["classes"][class_name]["students"][user]

    notifications = []
    for o in student_data["orders"]:
        if not o.get("notified", True) and o["status"] != "Pending":
            if o["status"] == "Approved":
                notifications.append(f"ORDER: {o['item']} ({o['date']}) APPROVED!! Go see your teacher to claim your reward")
            elif o["status"] == "Denied":
                notifications.append(f"ORDER: {o['item']} ({o['date']}) DENIED. Reason: {o['reason']}")
            o["notified"] = True
    save_users()

    projected = student_data["savings_balance"] * (1 + DEFAULT_INTEREST_RATE)
    return render_template("student.html", username=user, class_name=class_name, info=student_data, notifications=notifications, interest_rate=DEFAULT_INTEREST_RATE*100, projected_savings=projected)

# Savings deposit
@app.route('/savings', methods=['POST'])
def savings():
    if "user" not in session or "class" not in session:
        return redirect(url_for('index'))
    class_name = session["class"]
    user = session["user"]
    student_data = USERS["classes"][class_name]["students"][user]

    try:
        amount = float(request.form.get("amount", 0))
    except ValueError:
        amount = 0

    if amount <= 0 or amount > student_data["balance"]:
        flash("Invalid amount.")
    else:
        now = datetime.now(CENTRAL_TZ)
        student_data["balance"] -= amount
        student_data["savings_balance"] += amount
        student_data["lock_until"] = now.isoformat()
        save_users()
        flash(f"${amount:.2f} moved to savings. Locked until {now + timedelta(days=7):%Y-%m-%d %H:%M %Z}")

    return redirect(url_for('student'))

# Store purchases
@app.route('/store', methods=['POST'])
def store():
    if "user" not in session or "class" not in session:
        return redirect(url_for('index'))
    class_name = session["class"]
    user = session["user"]
    student_data = USERS["classes"][class_name]["students"][user]

    item = request.form.get("item")
    prices = {"Candy": 10, "No Homework Pass": 200}

    if item not in prices:
        flash("Invalid item.")
    elif student_data["balance"] < prices[item]:
        flash("Not enough funds.")
    else:
        now = datetime.now(CENTRAL_TZ)
        student_data["balance"] -= prices[item]
        student_data["orders"].append({"item": item,"date": now.isoformat(),"status":"Pending","reason":"","notified":False})
        save_users()
        flash(f"Purchased {item}, waiting for teacher approval!")

    return redirect(url_for('student'))

# Approve/Deny orders
@app.route('/approve_order/<class_name>/<student>/<int:idx>')
def approve_order(class_name, student, idx):
    USERS["classes"][class_name]["students"][student]["orders"][idx]["status"] = "Approved"
    USERS["classes"][class_name]["students"][student]["orders"][idx]["notified"] = False
    save_users()
    flash(f"Order approved for {student}")
    return redirect(url_for('admin'))

@app.route('/deny_order/<class_name>/<student>/<int:idx>', methods=['POST'])
def deny_order(class_name, student, idx):
    reason = request.form.get("reason", "")
    USERS["classes"][class_name]["students"][student]["orders"][idx]["status"] = "Denied"
    USERS["classes"][class_name]["students"][student]["orders"][idx]["reason"] = reason
    USERS["classes"][class_name]["students"][student]["orders"][idx]["notified"] = False
    save_users()
    flash(f"Order denied for {student}")
    return redirect(url_for('admin'))

# Leaderboard
@app.route('/leaderboard')
def leaderboard():
    if "user" not in session:
        return redirect(url_for('index'))

    leaderboard_data = []
    for class_name, class_data in USERS.get("classes", {}).items():
        for name, data in class_data["students"].items():
            total = data["balance"] + data["savings_balance"]
            leaderboard_data.append({"name": name, "total": total})
    leaderboard_data.sort(key=lambda x: x["total"], reverse=True)
    return render_template("leaderboard.html", leaderboard=leaderboard_data, enumerate=enumerate)

# Developer: download all files
@app.route('/developer')
def developer():
    if "user" not in session or USERS["users"].get(session["user"], {}).get("role") != "developer":
        flash("Developer access required.")
        return redirect(url_for('index'))
    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, 'w') as zipf:
        for folder, _, files in os.walk('.'):
            for file in files:
                if file.endswith(('.py', '.html', '.json', '.txt', '.md')):
                    zipf.write(os.path.join(folder, file))
    mem_zip.seek(0)
    return send_file(mem_zip, download_name="bellangerbank_files.zip", as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)
