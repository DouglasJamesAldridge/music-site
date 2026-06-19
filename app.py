# app.py

import re
import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "local-dev-fallback")

DATABASE = "subscribers.db"


# --- Database Helpers ---

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    conn.execute("DROP TABLE IF EXISTS subscribers")
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
        # 'list_type' comes from a hidden input in each form
        list_type = request.form.get("list_type", "").strip()

        # Validate list_type
        if list_type not in ("sketches", "official"):
            flash("Something went wrong. Please try again.", "error")
            return redirect(url_for("index"))

        # Validate email
        if not email:
            flash("Please enter your email address.", "error")
            return redirect(url_for("index"))

        if not is_valid_email(email):
            flash("That doesn't look like a valid email. Please try again.", "error")
            return redirect(url_for("index"))

        # Save to database
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


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
