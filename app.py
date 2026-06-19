# app.py
import re
import os
import sqlite3
import smtplib
import secrets
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, redirect, url_for, flash, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "local-dev-fallback")

DATABASE = "subscribers.db"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS unsubscribe_tokens (
            token      TEXT PRIMARY KEY,
            email      TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def get_or_create_token(email):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT token FROM unsubscribe_tokens WHERE email = ?", (email,)
    ).fetchone()
    if row:
        token = row["token"]
    else:
        token = secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO unsubscribe_tokens (token, email) VALUES (?, ?)",
            (token, email)
        )
        conn.commit()
    conn.close()
    return token

def is_valid_email(email):
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return re.match(pattern, email) is not None

def send_email(to_email, subject, html_body):
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
        message = Mail(
            from_email=GMAIL_ADDRESS,
            to_emails=to_email,
            subject=subject,
            html_content=html_body
        )
        sg = SendGridAPIClient(os.environ.get("SENDGRID_API_KEY"))
        sg.send(message)
        return True
    except Exception as e:
        print(f"Failed to send to {to_email}: {e}")
        return False

def build_email_html(link, unsubscribe_url):
    return f"""
<div style="font-family: Georgia, serif; max-width: 540px; margin: 0 auto; padding: 2rem; background: #0d0d0d; color: #e8e8e8;">
  <p style="font-size: 0.75rem; letter-spacing: 0.15em; text-transform: uppercase; color: #c8ff00; margin-bottom: 1.5rem;">New Drop</p>
  <h1 style="font-size: 2rem; font-weight: normal; line-height: 1.2; margin-bottom: 1.5rem; color: #e8e8e8;">Something new just dropped.</h1>
  <p style="font-size: 1rem; color: #aaa; line-height: 1.7; margin-bottom: 2rem;">A new sketch is up. Click below to listen.</p>
  <a href="{link}" style="display: inline-block; background: #c8ff00; color: #0d0d0d; padding: 0.85rem 1.8rem; text-decoration: none; border-radius: 6px; font-weight: 700; font-family: sans-serif; font-size: 0.95rem;">Listen now</a>
  <hr style="border: none; border-top: 1px solid #2a2a2a; margin: 3rem 0 1.5rem;" />
  <p style="font-size: 0.75rem; color: #555; line-height: 1.6;">
    You're receiving this because you signed up for updates.<br/>
    <a href="{unsubscribe_url}" style="color: #555; text-decoration: underline;">Unsubscribe</a>
  </p>
</div>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        list_type = request.form.get("list_type", "sketches")
        if list_type not in ("sketches", "official"):
            list_type = "sketches"
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
                flash("You're on the Sketches list - expect raw drops in your inbox.", "success")
            else:
                flash("You're on the Official Releases list - I'll hit you when it's official.", "success")
        except sqlite3.IntegrityError:
            flash("You're already subscribed to that list.", "info")
        finally:
            conn.close()
        return redirect(url_for("index"))
    return render_template("index.html")

@app.route("/unsubscribe/<token>")
def unsubscribe(token):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT email FROM unsubscribe_tokens WHERE token = ?", (token,)
    ).fetchone()
    if not row:
        conn.close()
        return render_template("unsubscribe.html", success=False)
    email = row["email"]
    conn.execute("DELETE FROM subscribers WHERE email = ?", (email,))
    conn.execute("DELETE FROM unsubscribe_tokens WHERE token = ?", (token,))
    conn.commit()
    conn.close()
    return render_template("unsubscribe.html", success=True)

@app.route("/admin", methods=["GET", "POST"])
def admin():
    if session.get("admin_logged_in"):
        conn = get_db_connection()
        subscribers = conn.execute(
            "SELECT email, list, created_at FROM subscribers ORDER BY created_at DESC"
        ).fetchall()
        counts = conn.execute(
            "SELECT list, COUNT(*) as total FROM subscribers GROUP BY list"
        ).fetchall()
        conn.close()
        count_dict = {row["list"]: row["total"] for row in counts}
        return render_template("admin.html", subscribers=subscribers, counts=count_dict)
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
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin"))

@app.route("/admin/send", methods=["POST"])
def admin_send():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin"))
    link = request.form.get("link", "").strip()
    target_list = request.form.get("target_list", "sketches")
    if not link:
        flash("Please enter a link to send.", "error")
        return redirect(url_for("admin"))
    conn = get_db_connection()
    subscribers = conn.execute(
        "SELECT email FROM subscribers WHERE list = ?", (target_list,)
    ).fetchall()
    conn.close()
    if not subscribers:
        flash(f"No subscribers on the {target_list} list yet.", "info")
        return redirect(url_for("admin"))
    sent = 0
    failed = 0
    base_url = request.host_url.rstrip("/")
    for row in subscribers:
        email = row["email"]
        token = get_or_create_token(email)
        unsubscribe_url = f"{base_url}/unsubscribe/{token}"
        html = build_email_html(link, unsubscribe_url)
        subject = "New sketch just dropped" if target_list == "sketches" else "New release out now"
        if send_email(email, subject, html):
            sent += 1
        else:
            failed += 1
    if failed == 0:
        flash(f"Sent to {sent} subscriber{'s' if sent != 1 else ''}.", "success")
    else:
        flash(f"Sent: {sent}, Failed: {failed}. Check your Gmail credentials.", "error")
    return redirect(url_for("admin"))

init_db()

if __name__ == "__main__":
    app.run(debug=True)
