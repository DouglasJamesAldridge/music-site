# app.py

import re
import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "local-dev-fallback")

DATABASE = "subscribers.db"

# Admin password — set this as an environment variable on Render
# so your password isn't stored in your code
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")


# --- Database Helpers ---

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            email      TEXT NOT NULL,
            list       TEXT NOT NULL CHECK(list IN ('sketches', 'official')),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(email, list)
        )
    """)
    conn.commit()
    conn.close()


# --- Email Validation ---

def is_valid_email(email):
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return re.match(pattern, email) is not None


# --- Routes ---

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        list_type = request.form.get("list_type", "").strip()

        if list_type not in ("sketches", "official"):
            flash("Something went wrong. Please try again.", "error")
            return redirect(url_for("index"))

        if not email:
            flash("Please enter your email address.", "error")
            return redirect(url_for("index"))

        if not is_valid_email(email):
            flash("That doesn't look like a valid email. Please try again.", "error")
            return redirect(url_for("index"))

        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO subscribers (email, list) VALUES (?, ?)",
                (email, list_type)
            )
            conn.commit()
            if list_type == "sketches":
                flash("You're on the Sketches list — expect raw drops in your inbox.", "success")
            else:
                flash("You're on the Official Releases list — I'll hit you when it's official.", "success")
        except sqlite3.IntegrityError:
            flash("You're already subscribed to that list.", "info")
        finally:
            conn.close()

        return redirect(url_for("index"))

    return render_template("index.html")


# --- Admin Routes ---

@app.route("/admin", methods=["GET", "POST"])
def admin():
    """
    Admin page — protected by a simple password stored in session.
    Session is a secure cookie that remembers if you've logged in.
    """
    # If already logged in, show the subscriber list
    if session.get("admin_logged_in"):
        conn = get_db_connection()

        # Fetch all subscribers, newest first
        subscribers = conn.execute(
            "SELECT email, list, created_at FROM subscribers ORDER BY created_at DESC"
        ).fetchall()

        # Count each list separately for the summary
        counts = conn.execute(
            "SELECT list, COUNT(*) as total FROM subscribers GROUP BY list"
        ).fetchall()
        conn.close()

        # Turn counts into a simple dict: {'sketches': 5, 'official': 3}
        count_dict = {row["list"]: row["total"] for row in counts}

        return render_template("admin.html",
                               subscribers=subscribers,
                               counts=count_dict)

    # Handle login form submission
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin"))
        else:
            flash("Incorrect password.", "error")

    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    """Clear the admin session and redirect to login."""
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin"))


# Run init_db when the module loads (works with both gunicorn and python app.py)
init_db()

if __name__ == "__main__":
    app.run(debug=True)
