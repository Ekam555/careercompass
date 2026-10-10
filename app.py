"""CareerCompass - Youth Career Orientation & Skill Assessment Platform (CEP)
Run:  pip install -r requirements.txt  &&  python app.py
Admin login: admin / admin123  (override with ADMIN_USER / ADMIN_PASS env vars)
"""
import os, json, csv, io, sqlite3
from functools import wraps
from flask import (Flask, g, render_template, request, redirect, url_for,
                   session, flash, abort, Response)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret")
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "careercompass.db")
ADMIN_USER = os.environ.get("ADMIN_USER", "omkar")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "omkar123")
LEVELS = ["School", "Diploma", "Undergraduate", "Postgraduate", "Other"]

SCHEMA = """
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
 
]

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB); g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d: d.close()

def init_db():
    c = sqlite3.connect(DB); c.executescript(SCHEMA)
    if not c.execute("SELECT 1 FROM careers").fetchone():
        for name, (desc, opp, skills) in CAREERS.items():
            cid = c.execute("INSERT INTO careers(name,description,opportunities) VALUES(?,?,?)", (name, desc, opp)).lastrowid
            for s in skills.split(","):
                c.execute("INSERT INTO skills(career_id,name) VALUES(?,?)", (cid, s))
        for text, opts in QUESTIONS:
            o = [{"t": x.split("|")[0], "c": x.split("|")[1]} for x in opts]
            c.execute("INSERT INTO questions(text,options) VALUES(?,?)", (text, json.dumps(o)))
        for t, p, ty, co, u, cn in RESOURCES:
            row = c.execute("SELECT id FROM careers WHERE name=?", (cn,)).fetchone() if cn else None
            c.execute("INSERT INTO resources(title,provider,type,cost,url,career_id) VALUES(?,?,?,?,?,?)",
                      (t, p, ty, co, u, row[0] if row else None))
    c.commit(); c.close()

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
        elif db().execute("SELECT 1 FROM students WHERE email=?", (email,)).fetchone():
            flash("This email is already registered. Log in instead.")
        else:
            db().execute("INSERT INTO students(name,email,password,education) VALUES(?,?,?,?)",
                         (name, email, generate_password_hash(pw), f.get("education", "Other")))
            db().commit(); flash("Account created. Log in to start."); return redirect(url_for("login"))
    return render_template("register.html", levels=LEVELS)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        s = db().execute("SELECT * FROM students WHERE email=?", (request.form["email"].strip().lower(),)).fetchone()
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
          for q in db().execute("SELECT * FROM questions ORDER BY id")]
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
        rid = db().execute("INSERT INTO results(student_id,scores,top_career) VALUES(?,?,?)",
                           (session["sid"], json.dumps(scores), top)).lastrowid
        for qid, i, c in picks:
            db().execute("INSERT INTO answers(result_id,student_id,question_id,choice,career) VALUES(?,?,?,?,?)",
                         (rid, session["sid"], qid, i, c))
        db().commit(); return redirect(url_for("results", rid=rid))
    return render_template("assessment.html", qs=qs)

@app.route("/results")
@app.route("/results/<int:rid>")
@student_required
def results(rid=None):
    q = "SELECT * FROM results WHERE student_id=? " + ("AND id=?" if rid else "ORDER BY id DESC")
    r = db().execute(q, (session["sid"], rid) if rid else (session["sid"],)).fetchone()
    if not r:
        flash("Take the assessment to see your results."); return redirect(url_for("assessment"))
    scores = sorted(json.loads(r["scores"]).items(), key=lambda x: -x[1])[:3]
    items = []
    for name, pct in scores:
        c = db().execute("SELECT * FROM careers WHERE name=?", (name,)).fetchone()
        if c: items.append(dict(pct=pct, c=c))
    skills = []
    for it in items[:2]:
        for s in db().execute("SELECT name FROM skills WHERE career_id=?", (it["c"]["id"],)):
            if s["name"] not in skills: skills.append(s["name"])
    return render_template("results.html", items=items, skills=skills[:8], r=r)

@app.route("/careers")
def careers():
    allc = db().execute("SELECT * FROM careers ORDER BY id").fetchall()
    if not allc: return render_template("careers.html", allc=[], c=None)
    cid = request.args.get("c", type=int) or allc[0]["id"]
    c = db().execute("SELECT * FROM careers WHERE id=?", (cid,)).fetchone() or allc[0]
    skills = [s["name"] for s in db().execute("SELECT name FROM skills WHERE career_id=?", (c["id"],))]
    res = db().execute("SELECT * FROM resources WHERE career_id=?", (c["id"],)).fetchall()
    return render_template("careers.html", allc=allc, c=c, skills=skills, res=res,
                           opps=(c["opportunities"] or "").split("|"))

@app.route("/resources")
def resources():
    t = request.args.get("type", "All")
    rows = db().execute("SELECT * FROM resources" + ("" if t == "All" else " WHERE type=?") + " ORDER BY id",
                        () if t == "All" else (t,)).fetchall()
    return render_template("resources.html", rows=rows, t=t,
                           types=["All", "Courses", "Websites", "Videos", "Articles", "Scholarships", "Internships"])

@app.route("/go/<int:rid>")
def go(rid):
    r = db().execute("SELECT url FROM resources WHERE id=?", (rid,)).fetchone() or abort(404)
    if "sid" in session:
        db().execute("INSERT INTO views(student_id,resource_id) VALUES(?,?)", (session["sid"], rid)); db().commit()
    return redirect(r["url"])

@app.route("/dashboard")
@student_required
def dashboard():
    sid = session["sid"]; one = lambda q: db().execute(q, (sid,)).fetchone()[0]
    last = db().execute("SELECT scores FROM results WHERE student_id=? ORDER BY id DESC", (sid,)).fetchone()
    top = sorted(json.loads(last["scores"]).items(), key=lambda x: -x[1])[:3] if last else []
    return render_template("dashboard.html", top=top,
        n_assess=one("SELECT COUNT(*) FROM results WHERE student_id=?"),
        n_views=one("SELECT COUNT(*) FROM views WHERE student_id=?"))

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
    one = lambda q: db().execute(q).fetchone()[0]
    pop = db().execute("SELECT top_career n, COUNT(*) c FROM results GROUP BY top_career ORDER BY c DESC").fetchall()
    edu = db().execute("SELECT education n, COUNT(*) c FROM students GROUP BY education ORDER BY c DESC").fetchall()
    return render_template("admin.html", pop=pop, edu=edu,
        stats=[("Students", one("SELECT COUNT(*) FROM students")), ("Assessments", one("SELECT COUNT(*) FROM results")),
               ("Careers", one("SELECT COUNT(*) FROM careers")), ("Resources", one("SELECT COUNT(*) FROM resources"))])

@app.route("/admin/<kind>", methods=["GET", "POST"])
@admin_required
def manage(kind):
    if kind not in ("questions", "careers", "resources"): abort(404)
    f = request.form
    if request.method == "POST":
        if kind == "questions":
            o = [{"t": f[f"t{i}"], "c": f[f"c{i}"]} for i in range(4) if f.get(f"t{i}")]
            db().execute("INSERT INTO questions(text,options) VALUES(?,?)", (f["text"], json.dumps(o)))
        elif kind == "careers":
            cid = db().execute("INSERT INTO careers(name,description,opportunities) VALUES(?,?,?)",
                (f["name"], f["description"], "|".join(x.strip() for x in f["opportunities"].split(",") if x.strip()))).lastrowid
            for s in f["skills"].split(","):
                if s.strip(): db().execute("INSERT INTO skills(career_id,name) VALUES(?,?)", (cid, s.strip()))
        else:
            db().execute("INSERT INTO resources(title,provider,type,cost,url,career_id) VALUES(?,?,?,?,?,?)",
                (f["title"], f["provider"], f["type"], f["cost"], f["url"], f.get("career_id") or None))
        db().commit(); flash("Added."); return redirect(url_for("manage", kind=kind))
    rows = db().execute(f"SELECT * FROM {kind} ORDER BY id").fetchall()
    cs = db().execute("SELECT id,name FROM careers ORDER BY name").fetchall()
    if kind == "questions":
        rows = [dict(id=r["id"], text=r["text"], options=json.loads(r["options"])) for r in rows]
    return render_template("manage.html", kind=kind, rows=rows, cs=cs)

@app.route("/admin/<kind>/<int:i>/delete", methods=["POST"])
@admin_required
def delete(kind, i):
    if kind not in ("questions", "careers", "resources"): abort(404)
    if kind == "careers": db().execute("DELETE FROM skills WHERE career_id=?", (i,))
    db().execute(f"DELETE FROM {kind} WHERE id=?", (i,)); db().commit()
    flash("Deleted."); return redirect(url_for("manage", kind=kind))

@app.route("/admin/students")
@admin_required
def students():
    rows = db().execute("""SELECT s.name,s.email,s.education,s.created,
      (SELECT COUNT(*) FROM results r WHERE r.student_id=s.id) n,
      (SELECT top_career FROM results r WHERE r.student_id=s.id ORDER BY r.id DESC LIMIT 1) top
      FROM students s ORDER BY s.id DESC""").fetchall()
    return render_template("students.html", rows=rows)

@app.route("/admin/report.csv")
@admin_required
def report():
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["student", "email", "education", "taken", "top_career", "scores"])
    for r in db().execute("""SELECT s.name,s.email,s.education,r.taken,r.top_career,r.scores
        FROM results r JOIN students s ON s.id=r.student_id ORDER BY r.id"""):
        w.writerow(list(r))
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=careercompass_report.csv"})

init_db()
if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
