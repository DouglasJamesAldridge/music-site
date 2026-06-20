# app.py
import re
import os
import sqlite3
import secrets
from flask import Flask, render_template, request, redirect, url_for, flash, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "local-dev-fallback")

DATABASE = "subscribers.db"
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "changeme")

STREAMING_PLATFORMS = [
    "Spotify",
    "Apple Music",
    "YouTube Music",
    "Amazon Music",
    "Tidal",
    "Deezer",
    "Pandora",
    "SoundCloud",
    "Other / I'll use the link provided",
]

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
            platform   TEXT,
            message    TEXT,
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            email        TEXT NOT NULL,
            drop_label   TEXT NOT NULL,
            feedback     TEXT NOT NULL,
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback_tokens (
            token      TEXT PRIMARY KEY,
            email      TEXT NOT NULL,
            drop_label TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Safe migrations
    for column, definition in [("platform", "TEXT"), ("message", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE subscribers ADD COLUMN {column} {definition}")
            conn.commit()
        except sqlite3.OperationalError:
            pass
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

def create_feedback_token(email, drop_label):
    token = secrets.token_urlsafe(32)
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO feedback_tokens (token, email, drop_label) VALUES (?, ?, ?)",
        (token, email, drop_label)
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
            from_email="doug@dougaldridgemusic.com",
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

def build_admin_notification(email, list_type, platform, message):
    list_name = "Sketches" if list_type == "sketches" else "Official Releases"
    platform_str = platform if platform else "Not specified"
    message_block = ""
    if message:
        message_block = f"""
  <div style="background: #1a1a1a; border-left: 3px solid #c8ff00; padding: 1rem 1.25rem; margin: 1.5rem 0; border-radius: 0 6px 6px 0;">
    <p style="font-size: 0.7rem; letter-spacing: 0.12em; text-transform: uppercase; color: #c8ff00; margin-bottom: 0.5rem;">Message from subscriber</p>
    <p style="font-size: 0.95rem; color: #ccc; line-height: 1.7; margin: 0;">{message}</p>
  </div>
"""
    return f"""
<div style="font-family: Georgia, serif; max-width: 540px; margin: 0 auto; padding: 2rem; background: #0d0d0d; color: #e8e8e8;">
  <p style="font-size: 0.75rem; letter-spacing: 0.15em; text-transform: uppercase; color: #c8ff00; margin-bottom: 1.5rem;">New Subscriber</p>
  <h1 style="font-size: 2rem; font-weight: normal; line-height: 1.2; margin-bottom: 1.5rem; color: #e8e8e8;">Someone just signed up.</h1>
  <table style="width: 100%; border-collapse: collapse; margin-bottom: 1.5rem;">
    <tr>
      <td style="padding: 0.6rem 0; color: #888; font-size: 0.85rem; width: 40%; border-bottom: 1px solid #222;">Email</td>
      <td style="padding: 0.6rem 0; color: #e8e8e8; font-size: 0.85rem; border-bottom: 1px solid #222;">{email}</td>
    </tr>
    <tr>
      <td style="padding: 0.6rem 0; color: #888; font-size: 0.85rem; width: 40%; border-bottom: 1px solid #222;">List</td>
      <td style="padding: 0.6rem 0; color: #e8e8e8; font-size: 0.85rem; border-bottom: 1px solid #222;">{list_name}</td>
    </tr>
    <tr>
      <td style="padding: 0.6rem 0; color: #888; font-size: 0.85rem; width: 40%;">Preferred platform</td>
      <td style="padding: 0.6rem 0; color: #e8e8e8; font-size: 0.85rem;">{platform_str}</td>
    </tr>
  </table>
  {message_block}
  <a href="https://signup.dougaldridgemusic.com/admin" style="display: inline-block; background: #c8ff00; color: #0d0d0d; padding: 0.75rem 1.5rem; text-decoration: none; border-radius: 6px; font-weight: 700; font-family: sans-serif; font-size: 0.9rem;">View in Admin</a>
  <hr style="border: none; border-top: 1px solid #2a2a2a; margin: 3rem 0 1.5rem;" />
  <p style="font-size: 0.75rem; color: #555;">This is an automated notification from your music signup site.</p>
</div>
"""

def build_email_html(link, unsubscribe_url, feedback_url, drop_type="sketches", about_text="", drop_label=""):
    if drop_type == "sketches":
        eyebrow = "New Sketch"
        heading = "Something new just dropped."
        body_text = "A new sketch is up. Click below to listen."
        btn_text = "Listen now"
    else:
        eyebrow = "New Release"
        heading = "Something new is out now."
        body_text = "A new official release is out. Click below to find it on your platform."
        btn_text = "Listen now"

    about_block = ""
    if about_text:
        about_block = f"""
  <div style="background: #1a1a1a; border-left: 3px solid #c8ff00; padding: 1rem 1.25rem; margin-bottom: 2rem; border-radius: 0 6px 6px 0;">
    <p style="font-size: 0.7rem; letter-spacing: 0.12em; text-transform: uppercase; color: #c8ff00; margin-bottom: 0.5rem;">About this drop</p>
    <p style="font-size: 0.95rem; color: #ccc; line-height: 1.7; margin: 0;">{about_text}</p>
  </div>
"""

    return f"""
<div style="font-family: Georgia, serif; max-width: 540px; margin: 0 auto; padding: 2rem; background: #0d0d0d; color: #e8e8e8;">
  <p style="font-size: 0.75rem; letter-spacing: 0.15em; text-transform: uppercase; color: #c8ff00; margin-bottom: 1.5rem;">{eyebrow}</p>
  <h1 style="font-size: 2rem; font-weight: normal; line-height: 1.2; margin-bottom: 1rem; color: #e8e8e8;">{heading}</h1>
  <p style="font-size: 1rem; color: #aaa; line-height: 1.7; margin-bottom: 1.5rem;">{body_text}</p>
  {about_block}
  <a href="{link}" style="display: inline-block; background: #c8ff00; color: #0d0d0d; padding: 0.85rem 1.8rem; text-decoration: none; border-radius: 6px; font-weight: 700; font-family: sans-serif; font-size: 0.95rem;">{btn_text}</a>

  <div style="margin-top: 3rem; padding: 1.5rem; background: #161616; border: 1px solid #2a2a2a; border-radius: 8px;">
    <p style="font-size: 0.75rem; letter-spacing: 0.12em; text-transform: uppercase; color: #888; margin-bottom: 0.5rem;">After you listen</p>
    <p style="font-size: 1rem; color: #e8e8e8; margin-bottom: 1rem; line-height: 1.5;">What did you think? I'd love to hear it.</p>
    <a href="{feedback_url}" style="display: inline-block; background: transparent; color: #c8ff00; padding: 0.7rem 1.4rem; text-decoration: none; border-radius: 6px; font-weight: 700; font-family: sans-serif; font-size: 0.88rem; border: 1px solid #c8ff00;">Leave a comment →</a>
  </div>

  <hr style="border: none; border-top: 1px solid #2a2a2a; margin: 3rem 0 1.5rem;" />
  <p style="font-size: 0.75rem; color: #555; line-height: 1.6;">
    You're receiving this because you signed up for updates at signup.dougaldridgemusic.com.<br/>
    <a href="{unsubscribe_url}" style="color: #555; text-decoration: underline;">Unsubscribe</a>
  </p>
</div>
"""

def build_welcome_email(list_type, platform=None):
    list_name = "Sketches" if list_type == "sketches" else "Official Releases"
    platform_note = ""
    if list_type == "official" and platform:
        platform_note = f"""
  <p style="font-size: 0.9rem; color: #aaa; line-height: 1.7; margin-bottom: 2rem;">
    When a new release drops, we'll send you a <strong style="color: #e8e8e8;">{platform}</strong> link so it's ready right in your preferred app.
  </p>
"""
    return f"""
<div style="font-family: Georgia, serif; max-width: 540px; margin: 0 auto; padding: 2rem; background: #0d0d0d; color: #e8e8e8;">
  <p style="font-size: 0.75rem; letter-spacing: 0.15em; text-transform: uppercase; color: #c8ff00; margin-bottom: 1.5rem;">Welcome</p>
  <h1 style="font-size: 2rem; font-weight: normal; line-height: 1.2; margin-bottom: 1.5rem; color: #e8e8e8;">You're in.</h1>
  <p style="font-size: 1rem; color: #aaa; line-height: 1.7; margin-bottom: 1rem;">
    Thanks for subscribing to the <strong style="color: #e8e8e8;">{list_name}</strong> list.
    I'll be in touch when something new drops.
  </p>
  {platform_note}
  <p style="font-size: 0.85rem; color: #aaa; line-height: 1.7; margin-bottom: 2rem;">
    To make sure you keep getting emails, add this address to your contacts.
  </p>
  <hr style="border: none; border-top: 1px solid #2a2a2a; margin: 3rem 0 1.5rem;" />
  <p style="font-size: 0.75rem; color: #555; line-height: 1.6;">
    You signed up for {list_name} updates from Douglas Aldridge at signup.dougaldridgemusic.com.
  </p>
</div>
"""

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        list_type = request.form.get("list_type", "sketches")
        platform = request.form.get("platform", "").strip()
        message = request.form.get("message", "").strip()

        if list_type not in ("sketches", "official"):
            list_type = "sketches"
        if not is_valid_email(email):
            flash("That doesn't look like a valid email. Please try again.", "error")
            return redirect(url_for("index"))

        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO subscribers (email, list, platform, message) VALUES (?, ?, ?, ?)",
                (email, list_type, platform or None, message or None)
            )
            conn.commit()
            welcome_html = build_welcome_email(list_type, platform)
            send_email(email, "You're subscribed.", welcome_html)
            admin_email = os.environ.get("ADMIN_EMAIL", "doug@dougaldridgemusic.com")
            notification_html = build_admin_notification(email, list_type, platform, message)
            send_email(admin_email, f"New subscriber: {email}", notification_html)
            if list_type == "sketches":
                flash("You're on the Sketches list. A confirmation email is on its way — if you don't see it, check your spam folder and mark it as safe.", "success")
            else:
                flash("You're on the Official Releases list. A confirmation email is on its way — if you don't see it, check your spam folder and mark it as safe.", "success")
        except sqlite3.IntegrityError:
            flash("You're already subscribed to that list.", "info")
        finally:
            conn.close()
        return redirect(url_for("index"))
    return render_template("index.html", platforms=STREAMING_PLATFORMS)

@app.route("/feedback/<token>", methods=["GET", "POST"])
def feedback(token):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT email, drop_label FROM feedback_tokens WHERE token = ?", (token,)
    ).fetchone()
    if not row:
        conn.close()
        return render_template("feedback.html", state="invalid")
    email = row["email"]
    drop_label = row["drop_label"]
    if request.method == "POST":
        text = request.form.get("feedback", "").strip()
        if not text:
            conn.close()
            return render_template("feedback.html", state="form", drop_label=drop_label, error="Please write something before submitting.")
        conn.execute(
            "INSERT INTO feedback (email, drop_label, feedback) VALUES (?, ?, ?)",
            (email, drop_label, text)
        )
        conn.commit()
        conn.close()
        return render_template("feedback.html", state="thanks", drop_label=drop_label)
    conn.close()
    return render_template("feedback.html", state="form", drop_label=drop_label)

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
            "SELECT email, list, platform, message, created_at FROM subscribers ORDER BY created_at DESC"
        ).fetchall()
        counts = conn.execute(
            "SELECT list, COUNT(*) as total FROM subscribers GROUP BY list"
        ).fetchall()
        new_subscribers = conn.execute(
            "SELECT email, list, platform, message, created_at FROM subscribers WHERE created_at >= datetime('now', '-7 days') ORDER BY created_at DESC"
        ).fetchall()
        feedback_rows = conn.execute(
            "SELECT email, drop_label, feedback, created_at FROM feedback ORDER BY created_at DESC"
        ).fetchall()
        platform_groups = {}
        for row in subscribers:
            if row["list"] == "official":
                plat = row["platform"] or "Not specified"
                if plat not in platform_groups:
                    platform_groups[plat] = []
                platform_groups[plat].append(row)
        conn.close()
        count_dict = {row["list"]: row["total"] for row in counts}
        return render_template(
            "admin.html",
            subscribers=subscribers,
            counts=count_dict,
            platform_groups=platform_groups,
            platforms=STREAMING_PLATFORMS,
            new_subscribers=new_subscribers,
            feedback_rows=feedback_rows
        )
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
    target_platform = request.form.get("target_platform", "all")
    about_text = request.form.get("about_text", "").strip()
    drop_label = request.form.get("drop_label", "").strip() or "this drop"

    if not link:
        flash("Please enter a link to send.", "error")
        return redirect(url_for("admin"))

    conn = get_db_connection()
    if target_list == "official" and target_platform and target_platform != "all":
        subscribers = conn.execute(
            "SELECT email FROM subscribers WHERE list = ? AND (platform = ? OR (platform IS NULL AND ? = 'Not specified'))",
            (target_list, target_platform, target_platform)
        ).fetchall()
    else:
        subscribers = conn.execute(
            "SELECT email FROM subscribers WHERE list = ?", (target_list,)
        ).fetchall()
    conn.close()

    if not subscribers:
        flash("No subscribers found for that selection.", "info")
        return redirect(url_for("admin"))

    sent = 0
    failed = 0
    base_url = "https://signup.dougaldridgemusic.com"
    for row in subscribers:
        email = row["email"]
        token = get_or_create_token(email)
        unsubscribe_url = f"{base_url}/unsubscribe/{token}"
        feedback_token = create_feedback_token(email, drop_label)
        feedback_url = f"{base_url}/feedback/{feedback_token}"
        html = build_email_html(link, unsubscribe_url, feedback_url, drop_type=target_list, about_text=about_text, drop_label=drop_label)
        subject = "New sketch just dropped" if target_list == "sketches" else "New release out now"
        if send_email(email, subject, html):
            sent += 1
        else:
            failed += 1

    if failed == 0:
        flash(f"Sent to {sent} subscriber{'s' if sent != 1 else ''}.", "success")
    else:
        flash(f"Sent: {sent}, Failed: {failed}. Check your SendGrid credentials.", "error")
    return redirect(url_for("admin"))

init_db()

if __name__ == "__main__":
    app.run(debug=True)
