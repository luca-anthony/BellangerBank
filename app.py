import json
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from datetime import datetime, timedelta
from markupsafe import escape
from zoneinfo import ZoneInfo
import os

app = Flask(__name__)
app.secret_key = "change_this_secret"

# --- Interest rate ---
DEFAULT_INTEREST_RATE = 0.05  # 5% per week

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
        "admin": {"password": "ADMIN829381", "role": "admin"},
        "dev": {"password": "luca09182", "role": "developer"}
        # add other students here or via users.json
    }

# --- Save users helper ---
def save_users():
    with open(USERS_FILE, "w") as f:
        json.dump(USERS, f, indent=4, default=str)

# --- Routes ---

@app.route('/')
def index():
    return render_template("index.html", users=USERS)

@app.route('/user/<username>')
def user_password_page(username):
    username = escape(username)
    if username not in USERS:
        flash("Unknown user.")
        return redirect(url_for('index'))
    return render_template("password.html", username=username)

@app.route('/auth/<username>', methods=['POST'])
def authenticate(username):
    username = escape(username)
    entered = request.form.get("password", "")
    if username in USERS and entered == USERS[username]["password"]:
        session["user"] = username
        role = USERS[username]["role"]
        return redirect(url_for(role))
    else:
        flash("Incorrect password.")
        return redirect(url_for('user_password_page', username=username))

@app.route('/logout')
def logout():
    session.pop("user", None)
    flash("Logged out.")
    return redirect(url_for('index'))

# --- Admin ---
@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if "user" not in session or USERS[session["user"]]["role"] != "admin":
        flash("Admin access required.")
        return redirect(url_for('index'))

    if request.method == "POST" and 'amount' in request.form:
        target = request.form.get("student")
        try:
            amount = float(request.form.get("amount", "0"))
        except ValueError:
            amount = 0
        if target in USERS and USERS[target]["role"] == "student":
            USERS[target]["balance"] += amount
            save_users()
            flash(f"Added ${amount:.2f} to {target}'s balance.")
        else:
            flash("Invalid student.")

    return render_template("admin.html", users=USERS, enumerate=enumerate)

# --- Student ---
@app.route('/student', methods=['GET', 'POST'])
def student():
    if "user" not in session:
        return redirect(url_for('index'))

    user = session["user"]
    if USERS[user]["role"] != "student":
        return redirect(url_for('index'))

    notifications = []
    for o in USERS[user]["orders"]:
        if not o.get("notified", True) and o["status"] != "Pending":
            if o["status"] == "Approved":
                notifications.append(f"ORDER: {o['item']} ({o['date']}) APPROVED!! Go see your teacher to claim your reward")
            elif o["status"] == "Denied":
                notifications.append(f"ORDER: {o['item']} ({o['date']}) DENIED. Reason: {o['reason']}")
            o["notified"] = True
    save_users()

    projected = USERS[user]["savings_balance"] * (1 + DEFAULT_INTEREST_RATE)

    return render_template(
        "student.html",
        username=user,
        info=USERS[user],
        notifications=notifications,
        interest_rate=DEFAULT_INTEREST_RATE * 100,
        projected_savings=projected
    )

# --- Savings ---
@app.route('/savings', methods=['POST'])
def savings():
    if "user" not in session:
        return redirect(url_for('index'))
    user = session["user"]
    amount = float(request.form.get("amount", "0"))

    if amount <= 0 or amount > USERS[user]["balance"]:
        flash("Invalid amount.")
    else:
        now = datetime.now(CENTRAL_TZ)
        USERS[user]["balance"] -= amount
        USERS[user]["savings_balance"] += amount
        USERS[user]["lock_until"] = now.isoformat()
        save_users()
        flash(f"${amount:.2f} moved to savings. Locked until {now + timedelta(days=7):%Y-%m-%d %H:%M %Z}")

    return redirect(url_for('student'))

# --- Store ---
@app.route('/store', methods=['POST'])
def store():
    if "user" not in session:
        return redirect(url_for('index'))
    user = session["user"]
    item = request.form.get("item")
    prices = {"Candy": 10, "No Homework Pass": 200}

    if item not in prices:
        flash("Invalid item.")
    elif USERS[user]["balance"] < prices[item]:
        flash("Not enough funds.")
    else:
        now = datetime.now(CENTRAL_TZ)
        USERS[user]["balance"] -= prices[item]
        USERS[user]["orders"].append({
            "item": item,
            "date": now.isoformat(),
            "status": "Pending",
            "reason": "",
            "notified": False
        })
        save_users()
        flash(f"Purchased {item}, waiting for teacher approval!")

    return redirect(url_for('student'))

# --- Orders (Admin) ---
@app.route('/approve_order/<student>/<int:idx>')
def approve_order(student, idx):
    USERS[student]["orders"][idx]["status"] = "Approved"
    USERS[student]["orders"][idx]["notified"] = False
    save_users()
    flash(f"Order approved for {student}")
    return redirect(url_for('admin'))

@app.route('/deny_order/<student>/<int:idx>', methods=['POST'])
def deny_order(student, idx):
    reason = request.form.get("reason", "")
    USERS[student]["orders"][idx]["status"] = "Denied"
    USERS[student]["orders"][idx]["reason"] = reason
    USERS[student]["orders"][idx]["notified"] = False
    save_users()
    flash(f"Order denied for {student}")
    return redirect(url_for('admin'))

# --- Leaderboard ---
@app.route('/leaderboard')
def leaderboard():
    if "user" not in session:
        return redirect(url_for('index'))

    leaderboard_data = []
    for name, data in USERS.items():
        if data["role"] == "student":
            total = data["balance"] + data["savings_balance"]
            leaderboard_data.append({"name": name, "total": total})

    leaderboard_data.sort(key=lambda x: x["total"], reverse=True)
    return render_template("leaderboard.html", leaderboard=leaderboard_data, enumerate=enumerate)

# --- Developer: download all files ---
@app.route('/developer')
def developer():
    if "user" not in session or USERS[session["user"]]["role"] != "developer":
        flash("Developer access required.")
        return redirect(url_for('index'))

    import zipfile
    import io

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
