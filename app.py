# app.py
import re
import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "local-dev-fallback")

DATABASE = "subscribers.db"

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            email   TEXT NOT NULL UNIQUE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def is_valid_email(email):
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return re.match(pattern, email) is not None

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not email:
            flash("Please enter your email address.", "error")
            return redirect(url_for("index"))
        if not is_valid_email(email):
            flash("That doesn't look like a valid email. Please try again.", "error")
            return redirect(url_for("index"))
        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO subscribers (email) VALUES (?)", (email,))
            conn.commit()
            flash("You're on the list! I'll hit you when new music drops.", "success")
        except sqlite3.IntegrityError:
            flash("You're already subscribed — stay tuned.", "info")
        finally:
            conn.close()
        return redirect(url_for("index"))
    return render_template("index.html")

if __name__ == "__main__":
    init_db()
    app.run(debug=True)