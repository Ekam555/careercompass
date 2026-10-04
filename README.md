# CareerCompass - Flask Career Guidance Platform

## Local Development
```bash
pip install -r requirements.txt
python app.py
# Visit http://127.0.0.1:5000
```

## Deploy to Render (Free)

1. Push to GitHub:
```bash
git init
git add .
git commit -m "Initial commit"
# Create repo on GitHub, then:
git remote add origin https://github.com/YOURUSER/careercompass.git
git push -u origin main
```

2. On [Render.com](https://render.com):
- New → Web Service → Connect GitHub repo
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`
- Add env vars: `SECRET_KEY` (auto-generate), `ADMIN_USER`, `ADMIN_PASS`

3. Done! Your app at `https://careercompass.onrender.com`

## Admin Login
- URL: `/admin/login`
- Default: `admin` / `admin123` (change via env vars)