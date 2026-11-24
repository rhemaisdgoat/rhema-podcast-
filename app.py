import os
import re
import sqlite3
import secrets
import uuid
from datetime import datetime
from functools import wraps

import markdown
from flask import (Flask, g, render_template, request, redirect, url_for,
                   session, flash, abort, jsonify)
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
    DATABASE=os.path.join(BASE_DIR, "site.db"),
    UPLOAD_FOLDER=os.path.join(BASE_DIR, "static", "uploads"),
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,  # 8 MB uploads
)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# ---------------------------------------------------------------------------
# EDIT THIS: your brand details (shown across the site)
# ---------------------------------------------------------------------------
BRAND = {
    "name": "Rhema Podcast",
    "tagline": "A living word for every season of life.",
    "intro": "Conversations, teachings and stories that bring fresh insight "
             "to faith and everyday living. Welcome to Rhema Podcast.",
    "about": "Tell your story here. Who you are, what your brand stands for, "
             "and the kind of work you do. Edit this text in app.py.",
    "email": "hello@example.com",
    "socials": {
        "Twitter": "https://twitter.com/",
        "Instagram": "https://instagram.com/",
        "LinkedIn": "https://linkedin.com/",
    },
}

ADMIN_PASSWORD_HASH = generate_password_hash(os.environ.get("ADMIN_PASSWORD", "admin123"))
ALLOWED_IMAGES = {"png", "jpg", "jpeg", "gif", "webp"}
PER_PAGE = 6

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    excerpt TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    cover TEXT,
    published INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(app.config["DATABASE"])
    db.executescript(SCHEMA)
    db.commit()
    db.close()


init_db()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def slugify(text):
    text = re.sub(r"[^a-zA-Z0-9\s-]", "", text).strip().lower()
    return re.sub(r"[\s-]+", "-", text) or "post"


def unique_slug(title, exclude_id=None):
    base = slugify(title)
    slug, n = base, 2
    db = get_db()
    while True:
        row = db.execute("SELECT id FROM posts WHERE slug = ?", (slug,)).fetchone()
        if row is None or row["id"] == exclude_id:
            return slug
        slug = f"{base}-{n}"
        n += 1


def save_image(file):
    if not file or not file.filename:
        return None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_IMAGES:
        return None
    name = f"{uuid.uuid4().hex}.{ext}"
    file.save(os.path.join(app.config["UPLOAD_FOLDER"], name))
    return name


def render_md(text):
    html = markdown.markdown(text or "", extensions=["fenced_code", "tables", "sane_lists"])
    return Markup(html)


def reading_time(text):
    words = len((text or "").split())
    return max(1, round(words / 200))


app.jinja_env.filters["md"] = render_md
app.jinja_env.filters["reading_time"] = reading_time


@app.template_filter("date")
def format_date(value):
    try:
        return datetime.fromisoformat(value).strftime("%b %d, %Y")
    except (TypeError, ValueError):
        return value


@app.context_processor
def inject_globals():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return {"brand": BRAND, "csrf_token": session["csrf"],
            "is_admin": session.get("admin", False), "year": datetime.now().year}


@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = request.form.get("csrf") or request.headers.get("X-CSRF-Token")
        if not token or token != session.get("csrf"):
            abort(400, "Invalid CSRF token")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped

# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------


@app.route("/")
def home():
    posts = get_db().execute(
        "SELECT * FROM posts WHERE published = 1 ORDER BY created_at DESC LIMIT 3"
    ).fetchall()
    return render_template("home.html", posts=posts)


@app.route("/blog")
def blog():
    q = request.args.get("q", "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    where, params = "WHERE published = 1", []
    if q:
        where += " AND (title LIKE ? OR excerpt LIKE ? OR content LIKE ?)"
        params += [f"%{q}%"] * 3
    db = get_db()
    total = db.execute(f"SELECT COUNT(*) FROM posts {where}", params).fetchone()[0]
    posts = db.execute(
        f"SELECT * FROM posts {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [PER_PAGE, (page - 1) * PER_PAGE],
    ).fetchall()
    pages = max(1, -(-total // PER_PAGE))
    return render_template("blog.html", posts=posts, q=q, page=page, pages=pages, total=total)


@app.route("/blog/<slug>")
def post(slug):
    row = get_db().execute("SELECT * FROM posts WHERE slug = ?", (slug,)).fetchone()
    if row is None or (not row["published"] and not session.get("admin")):
        abort(404)
    return render_template("post.html", post=row)


@app.route("/about")
def about():
    return render_template("about.html")


@app.errorhandler(404)
def not_found(_e):
    return render_template("404.html"), 404

# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


@app.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if check_password_hash(ADMIN_PASSWORD_HASH, request.form.get("password", "")):
            session["admin"] = True
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/admin") else url_for("dashboard"))
        flash("Wrong password.", "error")
    return render_template("login.html")


@app.route("/admin/logout", methods=["POST"])
def logout():
    session.pop("admin", None)
    return redirect(url_for("home"))


@app.route("/admin")
@login_required
def dashboard():
    posts = get_db().execute("SELECT * FROM posts ORDER BY created_at DESC").fetchall()
    return render_template("dashboard.html", posts=posts)


def _save_post(post_id=None):
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "")
    excerpt = request.form.get("excerpt", "").strip()
    published = 1 if request.form.get("published") else 0
    if not title:
        flash("A title is required.", "error")
        return None
    if not excerpt:
        plain = re.sub(r"[#*_`>\[\]()!-]", "", content)
        excerpt = (plain[:160] + "...") if len(plain) > 160 else plain
    cover = save_image(request.files.get("cover"))
    db = get_db()
    now = datetime.now().isoformat(timespec="seconds")
    if post_id is None:
        cur = db.execute(
            "INSERT INTO posts (title, slug, excerpt, content, cover, published, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (title, unique_slug(title), excerpt, content, cover, published, now, now),
        )
        post_id = cur.lastrowid
    else:
        old = db.execute("SELECT cover FROM posts WHERE id = ?", (post_id,)).fetchone()
        if request.form.get("remove_cover"):
            cover = cover or None
        else:
            cover = cover or old["cover"]
        db.execute(
            "UPDATE posts SET title=?, slug=?, excerpt=?, content=?, cover=?, published=?, updated_at=?"
            " WHERE id=?",
            (title, unique_slug(title, post_id), excerpt, content, cover, published, now, post_id),
        )
    db.commit()
    return post_id


@app.route("/admin/new", methods=["GET", "POST"])
@login_required
def new_post():
    if request.method == "POST":
        if _save_post() is not None:
            flash("Article saved.", "success")
            return redirect(url_for("dashboard"))
    return render_template("editor.html", post=None)


@app.route("/admin/edit/<int:post_id>", methods=["GET", "POST"])
@login_required
def edit_post(post_id):
    row = get_db().execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if row is None:
        abort(404)
    if request.method == "POST":
        if _save_post(post_id) is not None:
            flash("Article updated.", "success")
            return redirect(url_for("dashboard"))
    return render_template("editor.html", post=row)


@app.route("/admin/delete/<int:post_id>", methods=["POST"])
@login_required
def delete_post(post_id):
    db = get_db()
    db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
    db.commit()
    flash("Article deleted.", "success")
    return redirect(url_for("dashboard"))


@app.route("/admin/upload-image", methods=["POST"])
@login_required
def upload_image():
    name = save_image(request.files.get("image"))
    if not name:
        return jsonify(error="Unsupported or missing image"), 400
    return jsonify(url=url_for("static", filename=f"uploads/{name}"))


@app.route("/admin/preview", methods=["POST"])
@login_required
def preview():
    return jsonify(html=str(render_md(request.form.get("content", ""))))


if __name__ == "__main__":
    app.run(debug=True)
