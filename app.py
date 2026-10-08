"""CareerCompass - Youth Career Orientation & Skill Assessment Platform (CEP)
Run:  pip install -r requirements.txt  &&  python app.py
Admin login: admin / admin123  (override with ADMIN_USER / ADMIN_PASS env vars)
"""
import os, json, csv, io, sqlite3
from functools import wraps
from urllib.parse import urlparse

try:
    import psycopg2
    import psycopg2.extras
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

from flask import (Flask, g, render_template, request, redirect, url_for,
                   session, flash, abort, Response)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret")
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin123")
LEVELS = ["School", "Diploma", "Undergraduate", "Postgraduate", "Other"]

DATABASE_URL = os.environ.get("DATABASE_URL", "")
USE_POSTGRES = DATABASE_URL.startswith("postgres") and HAS_POSTGRES

if USE_POSTGRES:
    url = urlparse(DATABASE_URL)
    PG_CONFIG = {
        "database": url.path[1:],
        "user": url.username,
        "password": url.password,
        "host": url.hostname,
        "port": url.port,
    }
else:
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "careercompass.db")

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS students(id INTEGER PRIMARY KEY, name TEXT, email TEXT UNIQUE,
  password TEXT, education TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY, text TEXT, options TEXT);
CREATE TABLE IF NOT EXISTS careers(id INTEGER PRIMARY KEY, name TEXT UNIQUE, description TEXT, opportunities TEXT);
CREATE TABLE IF NOT EXISTS skills(id INTEGER PRIMARY KEY, career_id INTEGER, name TEXT);
CREATE TABLE IF NOT EXISTS resources(id INTEGER PRIMARY KEY, title TEXT, provider TEXT, type TEXT,
  cost TEXT, url TEXT, career_id INTEGER);
CREATE TABLE IF NOT EXISTS results(id INTEGER PRIMARY KEY, student_id INTEGER, scores TEXT,
  top_career TEXT, taken TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS answers(id INTEGER PRIMARY KEY, result_id INTEGER, student_id INTEGER,
  question_id INTEGER, choice INTEGER, career TEXT);
CREATE TABLE IF NOT EXISTS views(id INTEGER PRIMARY KEY, student_id INTEGER, resource_id INTEGER);
"""

SCHEMA_POSTGRES = """
CREATE TABLE IF NOT EXISTS students(id SERIAL PRIMARY KEY, name TEXT, email TEXT UNIQUE,
  password TEXT, education TEXT, created TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS questions(id SERIAL PRIMARY KEY, text TEXT, options TEXT);
CREATE TABLE IF NOT EXISTS careers(id SERIAL PRIMARY KEY, name TEXT UNIQUE, description TEXT, opportunities TEXT);
CREATE TABLE IF NOT EXISTS skills(id SERIAL PRIMARY KEY, career_id INTEGER REFERENCES careers(id), name TEXT);
CREATE TABLE IF NOT EXISTS resources(id SERIAL PRIMARY KEY, title TEXT, provider TEXT, type TEXT,
  cost TEXT, url TEXT, career_id INTEGER REFERENCES careers(id));
CREATE TABLE IF NOT EXISTS results(id SERIAL PRIMARY KEY, student_id INTEGER REFERENCES students(id), scores TEXT,
  top_career TEXT, taken TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS answers(id SERIAL PRIMARY KEY, result_id INTEGER REFERENCES results(id), student_id INTEGER REFERENCES students(id),
  question_id INTEGER REFERENCES questions(id), choice INTEGER, career TEXT);
CREATE TABLE IF NOT EXISTS views(id SERIAL PRIMARY KEY, student_id INTEGER REFERENCES students(id), resource_id INTEGER REFERENCES resources(id));
"""

CAREERS = {
 "Web Development": ("Build and maintain websites and web applications.",
   "Frontend Developer|Backend Developer|Full Stack Developer|Web Designer",
   "HTML,CSS,JavaScript,React,Problem Solving"),
 "Data Science": ("Turn data into insight using statistics and programming.",
   "Data Analyst|Data Scientist|BI Developer",
   "Python,Statistics,Data Analysis,SQL,Visualization"),
 "AI & Machine Learning": ("Create systems that learn from data.",
   "ML Engineer|AI Researcher|NLP Engineer",
   "Python,Mathematics,Machine Learning,Deep Learning"),
 "Cybersecurity": ("Protect systems, networks and data from attacks.",
   "Security Analyst|Ethical Hacker|SOC Engineer",
   "Networking,Linux,Cryptography,Risk Analysis"),
 "UI/UX Design": ("Design products that are easy and pleasant to use.",
   "UX Designer|UI Designer|Product Designer",
   "Figma,Visual Design,User Research,Creativity"),
 "Digital Marketing": ("Reach and grow audiences through online channels.",
   "SEO Specialist|Content Strategist|Social Media Manager",
   "Communication,SEO,Content Writing,Analytics"),
 "Business Management": ("Lead teams, plan operations and grow organisations.",
   "Business Analyst|Project Manager|Entrepreneur",
   "Leadership,Communication,Planning,Finance Basics"),
 "Healthcare": ("Support the health and wellbeing of people.",
   "Nurse|Lab Technologist|Public Health Officer",
   "Biology,Empathy,Communication,Attention to Detail"),
 "Teaching & Education": ("Help others learn and grow.",
   "Teacher|Trainer|Instructional Designer",
   "Communication,Patience,Subject Knowledge,Presentation"),
}
QUESTIONS = [
  ("Which subject do you enjoy the most?", ["Computers and coding|Web Development","Maths and statistics|Data Science","Art and design|UI/UX Design","Biology and health|Healthcare"]),
  ("Which type of activities do you enjoy the most?", ["Solving logical problems|Web Development","Working with data|Data Science","Creating creative designs|UI/UX Design","Helping and communicating with people|Teaching & Education"]),
  ("What would you most like to build?", ["A website or app|Web Development","A model that predicts things|AI & Machine Learning","A secure network|Cybersecurity","A brand campaign|Digital Marketing"]),
  ("How do you prefer to work?", ["Alone, deep in a problem|Cybersecurity","In a team, leading it|Business Management","With people one-to-one|Healthcare","Explaining ideas to groups|Teaching & Education"]),
  ("Which headline would you read first?", ["New AI model beats humans|AI & Machine Learning","Major data breach exposed|Cybersecurity","Startup raises funding|Business Management","Viral campaign breaks records|Digital Marketing"]),
  ("Pick a weekend project.", ["Analyse a cricket dataset|Data Science","Redesign an app screen|UI/UX Design","Volunteer at a health camp|Healthcare","Tutor younger students|Teaching & Education"]),
  ("Which skill do you want to grow?", ["Programming|Web Development","Machine learning|AI & Machine Learning","Public speaking|Business Management","Writing and storytelling|Digital Marketing"]),
  ("What frustrates you most?", ["Slow, clumsy software|UI/UX Design","Guesswork without evidence|Data Science","Weak security|Cybersecurity","Disorganised plans|Business Management"]),
  ("Which describes you best?", ["Curious about how things work|AI & Machine Learning","Caring and patient|Healthcare","Creative and visual|UI/UX Design","Logical and precise|Web Development"]),
  ("Where do you see yourself in 5 years?", ["Building products|Web Development","Doing research with data|Data Science","Running my own business|Business Management","Teaching or mentoring|Teaching & Education"]),
]
RESOURCES = [
  ("Full Stack Web Development","Coursera","Courses","Paid","https://www.coursera.org","Web Development"),
  ("freeCodeCamp Web Development","freeCodeCamp","Courses","Free","https://www.freecodecamp.org","Web Development"),
  ("MDN Web Docs","Mozilla","Websites","Free","https://developer.mozilla.org","Web Development"),
  ("Python for Data Science","NPTEL / Udemy","Courses","Free","https://nptel.ac.in","Data Science"),
  ("Google Data Analytics","Google","Courses","Paid","https://grow.google/certificates","Data Science"),
  ("Machine Learning Crash Course","Google","Courses","Free","https://developers.google.com/machine-learning/crash-course","AI & Machine Learning"),
  ("Intro to Cybersecurity","Cisco Networking Academy","Courses","Free","https://www.netacad.com","Cybersecurity"),
  ("Google UX Design Basics","Google","Courses","Paid","https://grow.google/certificates","UI/UX Design"),
  ("National Scholarship Portal","Government of India","Scholarships","Free","https://scholarships.gov.in",None),
  ("Internshala","Internshala","Internships","Free","https://internshala.com",None),
]

def get_db():
    if "db" not in g:
        if USE_POSTGRES:
            g.db = psycopg2.connect(**PG_CONFIG, cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            g.db = sqlite3.connect(DB_PATH)
            g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d: d.close()

def execute(query, params=(), fetch=None, commit=False):
    db = get_db()
    if USE_POSTGRES:
        query = query.replace("?", "%s")
        cur = db.cursor()
        cur.execute(query, params)
        if fetch == "one":
            return cur.fetchone()
        if fetch == "all":
            return cur.fetchall()
        if commit:
            db.commit()
            return cur.lastrowid if hasattr(cur, 'lastrowid') else cur.fetchone()[0] if cur.description else None
        return cur
    else:
        cur = db.execute(query, params)
        if fetch == "one":
            return cur.fetchone()
        if fetch == "all":
            return cur.fetchall()
        if commit:
            db.commit()
            return cur.lastrowid
        return cur

def init_db():
    schema = SCHEMA_POSTGRES if USE_POSTGRES else SCHEMA_SQLITE
    db = get_db()
    if USE_POSTGRES:
        cur = db.cursor()
        for stmt in schema.strip().split(";"):
            if stmt.strip():
                cur.execute(stmt)
    else:
        db.executescript(schema)
    
    if not execute("SELECT 1 FROM careers", fetch="one"):
        for name, (desc, opp, skills) in CAREERS.items():
            cid = execute(
                "INSERT INTO careers(name,description,opportunities) VALUES(?,?,?)",
                (name, desc, opp), commit=True
            )
            for s in skills.split(","):
                execute("INSERT INTO skills(career_id,name) VALUES(?,?)", (cid, s), commit=True)
        for text, opts in QUESTIONS:
            o = [{"t": x.split("|")[0], "c": x.split("|")[1]} for x in opts]
            execute("INSERT INTO questions(text,options) VALUES(?,?)", (text, json.dumps(o)), commit=True)
        for t, p, ty, co, u, cn in RESOURCES:
            row = execute("SELECT id FROM careers WHERE name=?", (cn,), fetch="one") if cn else None
            execute("INSERT INTO resources(title,provider,type,cost,url,career_id) VALUES(?,?,?,?,?,?)",
                    (t, p, ty, co, u, row[0] if row else None), commit=True)
    if USE_POSTGRES:
        db.commit()

def student_required(f):
    @wraps(f)
    def w(*a, **k):
        if "sid" not in session:
            flash("Please log in to continue."); return redirect(url_for("login"))
        return f(*a, **k)
    return w

def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("admin"): return redirect(url_for("admin_login"))
        return f(*a, **k)
    return w

@app.context_processor
def inject():
    return {"user": session.get("sname"), "is_admin": session.get("admin")}

# ---------------- student side ----------------
@app.route("/")
def home():
    return render_template("home.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        name, email, pw = f["name"].strip(), f["email"].strip().lower(), f["password"]
        if not name or not email or len(pw) < 6:
            flash("Enter your name, email and a password of at least 6 characters.")
        elif pw != f["confirm"]:
            flash("The two passwords do not match.")
        elif execute("SELECT 1 FROM students WHERE email=?", (email,), fetch="one"):
            flash("This email is already registered. Log in instead.")
        else:
            execute("INSERT INTO students(name,email,password,education) VALUES(?,?,?,?)",
                    (name, email, generate_password_hash(pw), f.get("education", "Other")), commit=True)
            flash("Account created. Log in to start."); return redirect(url_for("login"))
    return render_template("register.html", levels=LEVELS)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        s = execute("SELECT * FROM students WHERE email=?", (request.form["email"].strip().lower(),), fetch="one")
        if s and check_password_hash(s["password"], request.form["password"]):
            session.clear(); session["sid"], session["sname"] = s["id"], s["name"]
            return redirect(url_for("dashboard"))
        flash("Email or password is incorrect.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("home"))

@app.route("/assessment", methods=["GET", "POST"])
@student_required
def assessment():
    qs = [dict(id=q["id"], text=q["text"], options=json.loads(q["options"]))
          for q in execute("SELECT * FROM questions ORDER BY id", fetch="all")]
    if request.method == "POST":
        counts, picks, answered = {}, [], 0
        for q in qs:
            v = request.form.get(f"q{q['id']}")
            if v is None: continue
            i = int(v); c = q["options"][i]["c"]
            counts[c] = counts.get(c, 0) + 1; picks.append((q["id"], i, c)); answered += 1
        if not answered:
            flash("Answer at least one question."); return redirect(url_for("assessment"))
        scores = {k: round(v * 100 / answered) for k, v in counts.items()}
        top = max(scores, key=scores.get)
        rid = execute("INSERT INTO results(student_id,scores,top_career) VALUES(?,?,?)",
                       (session["sid"], json.dumps(scores), top), commit=True)
        for qid, i, c in picks:
            execute("INSERT INTO answers(result_id,student_id,question_id,choice,career) VALUES(?,?,?,?,?)",
                    (rid, session["sid"], qid, i, c), commit=True)
        return redirect(url_for("results", rid=rid))
    return render_template("assessment.html", qs=qs)

@app.route("/results")
@app.route("/results/<int:rid>")
@student_required
def results(rid=None):
    q = "SELECT * FROM results WHERE student_id=? " + ("AND id=?" if rid else "ORDER BY id DESC")
    r = execute(q, (session["sid"], rid) if rid else (session["sid"],), fetch="one")
    if not r:
        flash("Take the assessment to see your results."); return redirect(url_for("assessment"))
    scores = sorted(json.loads(r["scores"]).items(), key=lambda x: -x[1])[:3]
    items = []
    for name, pct in scores:
        c = execute("SELECT * FROM careers WHERE name=?", (name,), fetch="one")
        if c: items.append(dict(pct=pct, c=c))
    skills = []
    for it in items[:2]:
        for s in execute("SELECT name FROM skills WHERE career_id=?", (it["c"]["id"],), fetch="all"):
            if s["name"] not in skills: skills.append(s["name"])
    return render_template("results.html", items=items, skills=skills[:8], r=r)

@app.route("/careers")
def careers():
    allc = execute("SELECT * FROM careers ORDER BY id", fetch="all")
    if not allc: return render_template("careers.html", allc=[], c=None)
    cid = request.args.get("c", type=int) or allc[0]["id"]
    c = execute("SELECT * FROM careers WHERE id=?", (cid,), fetch="one") or allc[0]
    skills = [s["name"] for s in execute("SELECT name FROM skills WHERE career_id=?", (c["id"],), fetch="all")]
    res = execute("SELECT * FROM resources WHERE career_id=?", (c["id"],), fetch="all")
    return render_template("careers.html", allc=allc, c=c, skills=skills, res=res,
                           opps=(c["opportunities"] or "").split("|"))

@app.route("/resources")
def resources():
    t = request.args.get("type", "All")
    if t == "All":
        rows = execute("SELECT * FROM resources ORDER BY id", fetch="all")
    else:
        rows = execute("SELECT * FROM resources WHERE type=? ORDER BY id", (t,), fetch="all")
    return render_template("resources.html", rows=rows, t=t,
                           types=["All", "Courses", "Websites", "Videos", "Articles", "Scholarships", "Internships"])

@app.route("/go/<int:rid>")
def go(rid):
    r = execute("SELECT url FROM resources WHERE id=?", (rid,), fetch="one") or abort(404)
    if "sid" in session:
        execute("INSERT INTO views(student_id,resource_id) VALUES(?,?)", (session["sid"], rid), commit=True)
    return redirect(r["url"])

@app.route("/dashboard")
@student_required
def dashboard():
    sid = session["sid"]
    last = execute("SELECT scores FROM results WHERE student_id=? ORDER BY id DESC", (sid,), fetch="one")
    top = sorted(json.loads(last["scores"]).items(), key=lambda x: -x[1])[:3] if last else []
    n_assess = execute("SELECT COUNT(*) FROM results WHERE student_id=?", (sid,), fetch="one")[0]
    n_views = execute("SELECT COUNT(*) FROM views WHERE student_id=?", (sid,), fetch="one")[0]
    return render_template("dashboard.html", top=top, n_assess=n_assess, n_views=n_views)

# ---------------- admin side ----------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if request.form["username"] == ADMIN_USER and request.form["password"] == ADMIN_PASS:
            session.clear(); session["admin"] = True; return redirect(url_for("admin"))
        flash("Username or password is incorrect.")
    return render_template("admin_login.html")

@app.route("/admin")
@admin_required
def admin():
    pop = execute("SELECT top_career n, COUNT(*) c FROM results GROUP BY top_career ORDER BY c DESC", fetch="all")
    edu = execute("SELECT education n, COUNT(*) c FROM students GROUP BY education ORDER BY c DESC", fetch="all")
    stats = [
        ("Students", execute("SELECT COUNT(*) FROM students", fetch="one")[0]),
        ("Assessments", execute("SELECT COUNT(*) FROM results", fetch="one")[0]),
        ("Careers", execute("SELECT COUNT(*) FROM careers", fetch="one")[0]),
        ("Resources", execute("SELECT COUNT(*) FROM resources", fetch="one")[0]),
    ]
    return render_template("admin.html", pop=pop, edu=edu, stats=stats)

@app.route("/admin/<kind>", methods=["GET", "POST"])
@admin_required
def manage(kind):
    if kind not in ("questions", "careers", "resources"): abort(404)
    f = request.form
    if request.method == "POST":
        if kind == "questions":
            o = [{"t": f[f"t{i}"], "c": f[f"c{i}"]} for i in range(4) if f.get(f"t{i}")]
            execute("INSERT INTO questions(text,options) VALUES(?,?)", (f["text"], json.dumps(o)), commit=True)
        elif kind == "careers":
            cid = execute("INSERT INTO careers(name,description,opportunities) VALUES(?,?,?)",
                (f["name"], f["description"], "|".join(x.strip() for x in f["opportunities"].split(",") if x.strip())), commit=True)
            for s in f["skills"].split(","):
                if s.strip(): execute("INSERT INTO skills(career_id,name) VALUES(?,?)", (cid, s.strip()), commit=True)
        else:
            execute("INSERT INTO resources(title,provider,type,cost,url,career_id) VALUES(?,?,?,?,?,?)",
                (f["title"], f["provider"], f["type"], f["cost"], f["url"], f.get("career_id") or None), commit=True)
        flash("Added."); return redirect(url_for("manage", kind=kind))
    rows = execute(f"SELECT * FROM {kind} ORDER BY id", fetch="all")
    cs = execute("SELECT id,name FROM careers ORDER BY name", fetch="all")
    if kind == "questions":
        rows = [dict(id=r["id"], text=r["text"], options=json.loads(r["options"])) for r in rows]
    return render_template("manage.html", kind=kind, rows=rows, cs=cs)

@app.route("/admin/<kind>/<int:i>/delete", methods=["POST"])
@admin_required
def delete(kind, i):
    if kind not in ("questions", "careers", "resources"): abort(404)
    if kind == "careers": execute("DELETE FROM skills WHERE career_id=?", (i,), commit=True)
    execute(f"DELETE FROM {kind} WHERE id=?", (i,), commit=True)
    flash("Deleted."); return redirect(url_for("manage", kind=kind))

@app.route("/admin/students")
@admin_required
def students():
    rows = execute("""SELECT s.name,s.email,s.education,s.created,
      (SELECT COUNT(*) FROM results r WHERE r.student_id=s.id) n,
      (SELECT top_career FROM results r WHERE r.student_id=s.id ORDER BY r.id DESC LIMIT 1) top
      FROM students s ORDER BY s.id DESC""", fetch="all")
    return render_template("students.html", rows=rows)

@app.route("/admin/report.csv")
@admin_required
def report():
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["student", "email", "education", "taken", "top_career", "scores"])
    for r in execute("""SELECT s.name,s.email,s.education,r.taken,r.top_career,r.scores
        FROM results r JOIN students s ON s.id=r.student_id ORDER BY r.id""", fetch="all"):
        w.writerow(list(r))
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=careercompass_report.csv"})

if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(debug=True, host="0.0.0.0")