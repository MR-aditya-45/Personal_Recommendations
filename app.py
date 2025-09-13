from flask import Flask, render_template, request, redirect, url_for, send_file, session, flash, Response
from recommender.recommender import Recommender
import pandas as pd
from datetime import datetime, timedelta
from ics import Calendar, Event
import io
import sqlite3
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "your_secret_key"  # required for sessions

# ---------------- Database Setup ----------------
def init_db():
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        username TEXT UNIQUE NOT NULL,
                        password TEXT NOT NULL
                    )''')
    conn.commit()
    conn.close()

init_db()

# ---------------- User Helpers ----------------
def get_user(username):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username=?", (username,))
    user = cursor.fetchone()
    conn.close()
    return user

def create_user(username, password):
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username, password) VALUES (?, ?)",
                       (username, generate_password_hash(password)))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

# ---------------- Authentication Routes ----------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = get_user(username)
        if user and check_password_hash(user[2], password):
            session["user"] = username
            return redirect(url_for("landing"))
        else:
            flash("Invalid credentials. Try again.")
    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if create_user(username, password):
            flash("Registration successful. Please login.")
            return redirect(url_for("login"))
        else:
            flash("Username already exists. Try a different one.")
    return render_template("register.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

# ---------------- Protected Routes ----------------
def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return func(*args, **kwargs)
    return wrapper

# ---------------- Recommender Setup ----------------
rec = Recommender(
    topic_graph_path="data/topic_graph.csv",
    student_data_path="data/student_data.csv",
    history_path="data/history.csv",
    resources_path="data/resources.csv"
)

# ---------------- Adaptive Helper Functions ----------------
try:
    _topic_graph_df = pd.read_csv("data/topic_graph.csv")
except Exception:
    _topic_graph_df = pd.DataFrame(columns=["topic", "relation", "related_topic"])

def _find_related(topic: str, relation: str):
    if _topic_graph_df.empty:
        return None
    rows = _topic_graph_df[
        (_topic_graph_df["topic"] == topic) & (_topic_graph_df["relation"].str.lower() == relation.lower())
    ]
    if not rows.empty:
        return rows.iloc[0]["related_topic"]
    return None

def _get_confidence(student_id: int, topic: str) -> int:
    vals = rec.history.loc[
        (rec.history["student_id"] == student_id) & (rec.history["topic"] == topic),
        "confidence"
    ].values
    return int(vals[0]) if len(vals) > 0 else 0

# ----------- URL cleaner for app-level resources -----------
def clean_url(url):
    """Return empty string if falsy. Ensure url starts with http:// or https://"""
    if not url or (isinstance(url, float) and pd.isna(url)):
        return ""
    u = str(url).strip()
    if u.startswith("http://") or u.startswith("https://"):
        return u
    return "https://" + u.lstrip('/')

# ----------- Robust resource lookup (handles different column names) -----------
def _get_resources(topic: str):
    """
    Returns dict with keys 'youtube' and 'docs' (absolute URLs or empty string).
    Looks for several possible column names in rec.resources or CSV.
    """
    try:
        df = rec.resources
    except Exception:
        try:
            df = pd.read_csv("data/resources.csv")
        except Exception:
            df = pd.DataFrame()

    if df is None or df.empty:
        return {"youtube": "", "docs": ""}

    row = df[df["topic"] == topic]
    if row.empty:
        return {"youtube": "", "docs": ""}

    r = row.iloc[0]

    # possible column names
    youtube_candidates = ["youtube", "youtube_link", "youtube_url", "yt", "video"]
    docs_candidates = ["docs", "documentation_link", "documentation", "docs_link", "documentation_url", "doc"]

    youtube_val = ""
    docs_val = ""

    for col in youtube_candidates:
        if col in r.index and pd.notna(r[col]) and str(r[col]).strip() != "":
            youtube_val = clean_url(r[col])
            break

    for col in docs_candidates:
        if col in r.index and pd.notna(r[col]) and str(r[col]).strip() != "":
            docs_val = clean_url(r[col])
            break

    return {"youtube": youtube_val, "docs": docs_val}

def adaptive_transform(student_id: int, recs: list[dict]) -> list[dict]:
    output = []
    seen = set()
    for r in recs:
        base_topic = r.get("topic")
        conf = int(r.get("confidence", _get_confidence(student_id, base_topic)))
        new_topic = base_topic
        strategy = "focus"

        if conf < 50:
            rel = _find_related(base_topic, "prerequisite")
            if rel:
                new_topic = rel
                strategy = "prerequisite"
        elif conf >= 80:
            rel = _find_related(base_topic, "advanced")
            if rel:
                new_topic = rel
                strategy = "advanced"

        if new_topic in seen:
            continue
        seen.add(new_topic)

        new_conf = _get_confidence(student_id, new_topic)
        res = _get_resources(new_topic)

        output.append({
            "topic": new_topic,
            "confidence": new_conf,
            "youtube": res.get("youtube", ""),
            "docs": res.get("docs", ""),
            "adapted_from": base_topic,
            "strategy": strategy
        })
    return output

def colorMap(conf):
    if conf < 50: return 'rgba(255,0,0,0.7)'
    elif conf < 80: return 'rgba(255,165,0,0.7)'
    else: return 'rgba(41,121,255,0.7)'
app.jinja_env.filters['colorMap'] = colorMap

# ---------------- Main Routes ----------------
@app.route('/landing')
@login_required
def landing():
    students = rec.list_students()
    return render_template('landing.html', students=students)

@app.route('/dashboard/<int:student_id>')
@login_required
def dashboard(student_id):
    confidences = rec.generate_confidence_scores(student_id).to_dict(orient='records')
    colors = [colorMap(c['confidence']) for c in confidences]
    return render_template('dashboard.html', student_id=student_id, confidences=confidences, colors=colors)

@app.route('/progress/<int:student_id>')
@login_required
def progress(student_id):
    """
    Display student progress, strengths, weaknesses, badges,
    and link to study plan/resources.
    """
    # Generate/update confidence scores for the student
    student_history = rec.generate_confidence_scores(student_id)

    # Safety check: ensure 'confidence' column exists
    if 'confidence' not in student_history.columns:
        student_history['confidence'] = 0

    # Convert to list of dicts for template rendering
    confidences = student_history.to_dict(orient='records')

    # Debugging output
    print(f"[DEBUG] Confidences for student {student_id}: {confidences}")

    # Classify strengths and weaknesses
    strengths = [c for c in confidences if c['confidence'] >= 80]
    weaknesses = [c for c in confidences if c['confidence'] < 50]

    # Award badges based on performance
    badges = []
    if len(strengths) >= 3:
        badges.append("Consistency Star ⭐")
    if len(weaknesses) <= 1 and len(strengths) > 0:
        badges.append("Improvement Badge 📈")
    if max([c['confidence'] for c in confidences], default=0) >= 90:
        badges.append("High Achiever 🏆")

    # Get study plan and resource links
    study_plan = rec.get_study_plan()
    resources = rec.resources.to_dict(orient='records') if not rec.resources.empty else []

    return render_template(
        'progress.html',
        student_id=student_id,
        confidences=confidences,
        strengths=strengths,
        weaknesses=weaknesses,
        badges=badges,
        study_plan=study_plan,
        resources=resources
    )
# ---------------- Recommendations Route ----------------
@app.route('/recommendations/<int:student_id>')
@login_required
def recommendations(student_id):
    # Get base recommendations
    all_recs = rec.get_next_recommendations(student_id)

    # Apply adaptive transformation
    try:
        all_recs = adaptive_transform(student_id, all_recs)
    except Exception as e:
        print("[ERROR] Adaptive transform failed:", e)

    # ---------------- Ensure Keys Exist ----------------
    for r in all_recs:
        r['youtube'] = r.get('youtube', '')
        r['docs'] = r.get('docs', '')
        r['strategy'] = r.get('strategy', 'focus')

    # ---- DEBUG PRINT: show what URL strings are being passed ----
    for r in all_recs:
        print(f"[DEBUG LINKS] topic={r.get('topic')} youtube={r.get('youtube')} docs={r.get('docs')}")

    # ---------------- Filter by Confidence ----------------
    filter_level = request.args.get('filter', 'all')
    if filter_level != 'all':
        filtered = []
        for r in all_recs:
            conf = int(r.get('confidence', 0))
            if filter_level == 'weak' and conf < 50:
                filtered.append(r)
            elif filter_level == 'moderate' and 50 <= conf < 80:
                filtered.append(r)
            elif filter_level == 'strong' and conf >= 80:
                filtered.append(r)
        all_recs = filtered

    # ---------------- Pagination ----------------
    page = max(int(request.args.get('page', 1)), 1)
    per_page = int(request.args.get('per_page', 5))
    total = len(all_recs)
    total_pages = (total + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    paginated_recs = all_recs[start:end]
    print("DEBUG RECS:", paginated_recs)

    # ---------------- Add Color for Display ----------------
    for r in paginated_recs:
        conf = int(r.get('confidence', 0))
        if conf < 50:
            r['color'] = '#e53935'  # Red
        elif conf < 80:
            r['color'] = '#fbc02d'  # Orange
        else:
            r['color'] = '#43a047'  # Green

    # ---------------- Badges ----------------
    badges = []
    confidences = [int(r.get('confidence', 0)) for r in all_recs]
    if sum(c >= 80 for c in confidences) >= 3:
        badges.append("Consistency Star ⭐")
    if sum(c < 50 for c in confidences) == 0:
        badges.append("Improvement Badge 📈")
    if any(c >= 90 for c in confidences):
        badges.append("High Achiever 🏆")

    # ---------------- Render Template ----------------
    return render_template(
        'recommendations.html',
        student_id=student_id,
        recommendations=paginated_recs,
        filter_level=filter_level,
        page=page,
        total_pages=total_pages,
        badges=badges
    )


# ---------------- Planning Route (Safe) ----------------
@app.route('/planning/<int:student_id>', methods=['GET', 'POST'])
@login_required
def planning(student_id):
    base_recs = rec.get_next_recommendations(student_id)
    try:
        all_recs = adaptive_transform(student_id, base_recs)
    except Exception:
        all_recs = base_recs

    plan = []

    if request.method == 'POST':
        start_date_str = request.form.get('start_date')
        hours_str = request.form.get('hours')
        days_str = request.form.get('days')
        selected_topics = request.form.getlist('topics')

        if start_date_str and hours_str and days_str and selected_topics:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            hours_per_day = int(hours_str)
            days_available = int(days_str)

            current_date = start_date
            topic_index = 0

            while topic_index < len(selected_topics):
                for _ in range(days_available):
                    if topic_index >= len(selected_topics):
                        break
                    plan.append({
                        'date': current_date.strftime("%Y-%m-%d"),
                        'topic': selected_topics[topic_index],
                        'hours': hours_per_day
                    })
                    topic_index += 1
                    current_date += timedelta(days=1)

            # Store plan in recommender
            rec.study_plan = pd.DataFrame(plan)
            # Save to CSV
            rec.save()

    return render_template(
        'planning.html',
        student_id=student_id,
        recommendations=all_recs,
        plan=plan
    )


# ---------------- ICS Download Route ----------------
@app.route('/download_plan/<int:student_id>')
@login_required
def download_plan(student_id):
    try:
        plan = pd.read_csv("data/study_plan.csv").to_dict(orient='records')
    except FileNotFoundError:
        return "No study plan generated yet. Please create one first."

    cal = Calendar()
    for p in plan:
        e = Event()
        e.name = p['topic']
        event_date = datetime.strptime(p['date'], "%Y-%m-%d")
        e.begin = event_date.replace(hour=9, minute=0)
        e.duration = timedelta(hours=int(p.get('hours', 1)))
        cal.events.add(e)

    output = io.BytesIO(cal.serialize().encode('utf-8'))
    output.seek(0)  # Ensure the pointer is at the start
    return send_file(
        output,
        as_attachment=True,
        download_name="study_plan.ics",
        mimetype="text/calendar"
    )


if __name__ == '__main__':
    app.run(debug=True,port=5000)
