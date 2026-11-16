# Rate Limiting in CareerCompass

CareerCompass uses **Flask-Limiter** to protect its login, registration, assessment, admin, and resource-redirect routes from abuse. This document explains the limits that are configured, how to test them locally, how to enable shared storage on Render, and how to change or troubleshoot them.

## 1. Overview

Rate limiting caps how many requests a single client may make in a given time window. When a client exceeds a limit, Flask-Limiter stops the request before the view function runs and returns **HTTP 429 Too Many Requests**. The response includes a `Retry-After` header telling the client how long to wait before trying again.

In this project the client identity is the request's remote IP address:

```python
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URL", "memory://"),
)
```

The default strategy is a **fixed window** (for example, a 60-second window for `"5 per minute"`). Counts are stored in memory during local development, or in Redis when `RATELIMIT_STORAGE_URL` is set on Render.

### Why rate limiting matters for CareerCompass

- **Brute-force protection.** `/login` and `/admin/login` are the obvious targets for automated password guessing and credential-stuffing attacks. A tight per-minute limit makes those attacks impractical.
- **Spam and fake accounts.** `/register` can create database rows. A limit prevents a script from filling the students table with bogus accounts.
- **Database and CPU protection.** `/assessment` writes a result plus one row per answer, and `/go/<rid>` records a resource view. Unlimited calls would bloat the database and slow down the free-tier Render instance.
- **Expensive admin actions.** The admin area can create, edit, and delete content. Limiting POST and delete requests reduces the damage from a runaway script or a stolen admin session.
- **Fairness and availability.** A handful of abusive clients should not consume the server's limited resources or prevent real students from using the site.

### How limits are applied

- Every request from the same public IP address counts toward the same limit (one bucket per route and time window).
- Routes decorated with `@limiter.limit(...)` use that limit. **An explicit route limit replaces the app-wide defaults for that route** (Flask-Limiter's `override_defaults` defaults to `True`).
- Routes without an explicit decorator use the default limits: **50 requests per hour and 200 requests per day**.
- Unless a decorator specifies `methods=[...]`, the limit covers **all HTTP methods**. In particular, loading a page with GET also consumes the allowance.

## 2. Current rate limits

| Route | Methods counted | Limit | Rationale |
|---|---|---:|---|
| `/register` | GET + POST | **5 per minute** | Prevents mass fake-account creation. Five attempts per minute still leaves room for correcting a typo or a taken email. |
| `/login` | GET + POST | **10 per minute** | Slows down password guessing while allowing a student a few legitimate retries. Ten per minute is roughly one attempt every six seconds. |
| `/assessment` | GET + POST (student login required) | **3 per minute** | Each submission writes a result and many answer rows. The limit blocks scripted submissions and rapid double-clicks; a real student normally submits once. |
| `/go/<rid>` | GET | **30 per minute** | This endpoint writes a resource-view row and redirects. The limit prevents bots from inflating view counts or using the app as a redirect proxy; normal clicking stays far below it. |
| `/admin/login` | GET + POST | **5 per minute** | The admin account is the highest-value target in the app, so it gets the tightest login limit. |
| `/admin/<kind>` | POST only | **20 per minute** | Staff content creation/editing. Twenty per minute is generous for manual work but stops a runaway form-submission script. |
| `/admin/<kind>/<id>/delete` | POST | **10 per minute** | Delete is destructive; the limit prevents mass deletion through automation or an accidental loop. |
| All other routes (no explicit decorator) | All | **50 per hour + 200 per day** | Baseline protection for browsing routes such as `/`, `/careers`, `/resources`, `/results`, and `/dashboard`. |

> **Note:** `/assessment` limits GET page loads as well as POST submissions because no `methods=["POST"]` filter is set. Opening or refreshing the assessment page three times in a minute can therefore produce a 429 before the student submits. See [Troubleshooting](#6-troubleshooting) for the fix.

## 3. The 429 response and `Retry-After`

When a limit is exceeded, the app's error handler renders a friendly page instead of Flask's default error text:

```python
@app.errorhandler(429)
def ratelimit_handler(e):
    return render_template("429.html", retry_after=e.retry_after), 429
```

The **429 response includes a `Retry-After` header** (in seconds by default) that tells browsers and scripts when they may retry. The same value is passed to `templates/429.html` as `retry_after`, so the page can display a message such as "Please try again in 42 seconds."

A response looks like this:

```http
HTTP/1.1 429 TOO MANY REQUESTS
Retry-After: 42
Content-Type: text/html; charset=utf-8
...
```

If you replace the custom handler, keep the header explicit when building a new response:

```python
from flask import make_response

@app.errorhandler(429)
def ratelimit_handler(e):
    resp = make_response(render_template("429.html", retry_after=e.retry_after), 429)
    resp.headers["Retry-After"] = str(e.retry_after)
    return resp
```

> `templates/429.html` must exist. If it is missing, Jinja raises `TemplateNotFound` and the client receives a 500 instead of the 429 page.

## 4. Testing locally

Start the app normally:

```bash
python app.py
```

The default `memory://` storage means counters are kept inside the running Python process, so a restart clears them.

### Reproduce a 429 on `/login`

The limit is 10 requests per minute. Send 12 POST requests quickly with fake credentials:

```bash
for i in $(seq 1 12); do
  printf "attempt %2d: " "$i"
  curl -s -o /dev/null -w "%{http_code}\n" \
    -X POST http://127.0.0.1:5000/login \
    -d "email=nobody@example.com&password=wrong"
done
```

Expected output (assuming no other `/login` requests in the last minute):

```text
attempt  1: 200
attempt  2: 200
...
attempt 10: 200
attempt 11: 429
attempt 12: 429
```

The first ten requests reach the view and show the normal "Email or password is incorrect" message. The eleventh and twelfth are stopped by the limiter.

### Inspect the 429 headers

```bash
curl -i -X POST http://127.0.0.1:5000/login \
  -d "email=nobody@example.com&password=wrong"
```

Once the limit is exhausted, the output begins with:

```http
HTTP/1.1 429 TOO MANY REQUESTS
Retry-After: 43
Content-Type: text/html; charset=utf-8
```

### Reproduce a 429 on `/register`

The limit is 5 per minute and includes GET requests. Six page loads are enough:

```bash
for i in $(seq 1 6); do
  curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5000/register
done
```

The first five return `200`; the sixth returns `429`.

### PowerShell equivalent

```powershell
1..12 | ForEach-Object {
  $code = curl.exe -s -o NUL -w "%{http_code}" -X POST `
    http://127.0.0.1:5000/login `
    -d "email=nobody@example.com&password=wrong"
  "attempt $_ -> $code"
}
```

### Resetting the counters

- **Restart the development server** (`Ctrl+C`, then `python app.py`). With `memory://`, this clears all counters.
- Or **wait for the window to end** (at most 60 seconds for the per-minute limits).
- In production with Redis, restarting the app does **not** reset counters. Wait for the window to expire, or clear the relevant Redis keys if you have access.

## 5. Production setup on Render

### Why Redis is needed

With the default `memory://` storage:

- Every Gunicorn worker/process keeps its **own** counters, so the effective limit is multiplied by the number of workers.
- Counters are lost on every deploy, restart, or free-tier spin-down.
- Limits are not shared between multiple instances.

A Redis instance gives all workers and instances one shared, persistent counter store. Render provides a Redis-compatible **Key Value** service.

### Steps

1. In the Render dashboard, choose **New → Key Value** (or **Redis**, depending on the current dashboard wording). Create it in the **same region** as the CareerCompass web service.
2. Open the new instance and copy its **Internal Connection URL**, for example:
   ```text
   redis://red-xxxxxxxxxxxxxxxxxxxx:6379
   ```
   Use the **internal** URL for a service running on Render. The external URL is for connections from outside Render, is slower, and may not be reachable in the same way.
3. Open the CareerCompass web service → **Environment** and add:
   ```text
   RATELIMIT_STORAGE_URL = redis://red-xxxxxxxxxxxxxxxxxxxx:6379
   ```
   The app reads this exact variable name. Do not commit the URL to Git if it contains a password.
4. Make sure the deployment installs both Flask-Limiter and the Redis client. The convenient form in `requirements.txt` is:
   ```text
   Flask-Limiter[redis]
   ```
   The `[redis]` extra pulls in the `redis` Python package.
5. Also confirm `SECRET_KEY` is set in the same Environment tab. On Render the app raises `RuntimeError` at startup if `SECRET_KEY` is missing; local development falls back to a development key. `DATABASE_URL` should already be configured for PostgreSQL.
6. Save the changes. Render redeploys the service automatically.
7. Verify in the service logs that there are no Redis connection errors, then run the 12-request login loop against the deployed URL:
   ```bash
   for i in $(seq 1 12); do
     curl -s -o /dev/null -w "%{http_code}\n" \
       -X POST https://YOUR-APP.onrender.com/login \
       -d "email=nobody@example.com&password=wrong"
   done
   ```
   You should see `429` after the tenth request. Wait a minute afterwards so the test does not affect real users on the same public IP.

### Environment variables related to this setup

| Variable | Required | Purpose |
|---|---|---|
| `RATELIMIT_STORAGE_URL` | Recommended on Render | Redis connection URL. Defaults to `memory://` when unset. |
| `SECRET_KEY` | Yes on Render | Signs session cookies. The app refuses to start on Render without it. |
| `DATABASE_URL` | Yes on Render | PostgreSQL connection. Local development falls back to the bundled SQLite database. |

> **Without Redis, limits reset on every deploy.** This is acceptable for a short classroom demo but not for a public production site.

## 6. Troubleshooting

### Legitimate users hit 429 too quickly (shared IPs / NAT)

All limits are keyed on the client IP. Students on the same campus Wi-Fi, school network, office, or mobile carrier NAT can share one public IP, so they also share one bucket. Five registrations per minute can block a whole class.

Options:

- Raise the limits for the event/demo, or temporarily disable rate limiting.
- Key authenticated routes by student ID instead of IP. Keep IP-based limits on `/login` and `/register`, where no user is authenticated yet:

  ```python
  from flask import session

  def student_key():
      return f"student:{session['sid']}" if session.get("sid") else get_remote_address()

  @app.route("/assessment", methods=["GET", "POST"])
  @student_required
  @limiter.limit("3 per minute", key_func=student_key)
  def assessment():
      ...
  ```

- If the app is behind a proxy and every visitor appears to have the same IP, fix the client-IP detection as described next.

### Wrong IP behind Render's proxy / `X-Forwarded-For`

`get_remote_address()` returns `request.remote_addr`, which is the direct peer of the Flask app. Behind Render's reverse proxy that may be the proxy itself rather than the student's real IP, causing every visitor to share one rate-limit bucket.

The usual fix is Werkzeug's `ProxyFix`, applied once near app creation:

```python
from werkzeug.middleware.proxy_fix import ProxyFix

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
```

`x_for=1` means "trust exactly one proxy in front of the app" (Render's proxy). This makes `request.remote_addr` reflect the client address from `X-Forwarded-For`.

Alternatively, use a custom key function:

```python
def real_client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() or get_remote_address()
```

Then pass `key_func=real_client_ip` to `Limiter(...)` or to an individual `@limiter.limit(...)`.

> `X-Forwarded-For` can be spoofed by clients. Only trust it when the app is genuinely reachable only through a proxy you control, and only trust the correct number of proxy hops. Do not accept an arbitrary whole header chain.

To confirm what the app sees, temporarily log both values:

```python
@app.before_request
def log_client_ip():
    app.logger.info("remote=%s xff=%s",
                    request.remote_addr,
                    request.headers.get("X-Forwarded-For"))
```

### Limits reset after every deploy or restart

The app defaults to `memory://`. That storage is local to each Python process, so it resets on restart, deploy, or free-tier spin-down, and each Gunicorn worker counts separately. Configure Redis and set `RATELIMIT_STORAGE_URL` as described in section 5.

### Changing a limit has no effect

- Restart the development server or redeploy on Render; limits are read when the module is imported.
- Remember that an explicit `@limiter.limit` **replaces** the default limits for that route. Changing `default_limits` will not change `/login`, `/register`, `/assessment`, or the admin routes.
- With Redis, existing counters remain until their window expires. Wait for the window or clear the limiter keys before retesting.
- Check that the decorator is directly above the view function and below `@app.route(...)`.

### A student gets a 429 just from opening `/assessment`

The `"3 per minute"` rule applies to GET and POST because no `methods` filter is set. If only submissions should count, change it to:

```python
@limiter.limit("3 per minute", methods=["POST"])
```

The same pattern is already used on `/admin/<kind>`.

### `TemplateNotFound: 429.html` or an ugly 500 instead of 429

Make sure `templates/429.html` exists and is deployed. The handler passes only `retry_after` to the template, so the page should guard against it being absent:

```html
{% if retry_after %}
  <p>Please try again in {{ retry_after }} seconds.</p>
{% else %}
  <p>Please wait a moment and try again.</p>
{% endif %}
```

### How to temporarily disable rate limiting

For a quick local demo, comment out the `@limiter.limit(...)` decorators you want to bypass and restart the app. This is the least invasive option because it makes no change to the limiter setup.

For a switch controlled by an environment variable, add `enabled` when the limiter is created:

```python
limiter = Limiter(
    get_remote_address,
    app=app,
    enabled=os.environ.get("RATELIMIT_ENABLED", "1") == "1",
    default_limits=["200 per day", "50 per hour"],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URL", "memory://"),
)
```

Then set `RATELIMIT_ENABLED=0` locally or in the Render Environment tab and restart/redeploy. Alternatively, set `app.config["RATELIMIT_ENABLED"] = False` **before** the `Limiter` is initialized.

> Disable rate limiting only for debugging or a supervised demo. Re-enable it before the site is public.

### How to change limits

- **Per route:** edit the decorator string, for example `"10 per minute"` → `"20 per minute"`.
- **App-wide defaults:** edit the `default_limits` list in the `Limiter(...)` constructor.
- **Several limits at once:** stack decorators or use a semicolon-separated string:
  ```python
  @limiter.limit("10 per minute; 100 per day")
  ```
- **Defaults plus a route limit:** explicit limits replace defaults by default. Add `override_defaults=False` if you want both:
  ```python
  @limiter.limit("5 per minute", override_defaults=False)
  ```

After editing, restart or redeploy. Supported units include `second`, `minute`, `hour`, `day`, `month`, and `year`, with optional multipliers such as `"10 per 2 hours"`.

### Redis connection errors

If the logs show `redis.exceptions.ConnectionError` or repeated timeouts:

- Confirm `RATELIMIT_STORAGE_URL` is the **Internal Connection URL**, not the external one.
- Confirm the Redis/Key Value service and the web service are in the same region and the Redis service is running.
- Confirm the deployment includes `Flask-Limiter[redis]` (or the `redis` package).
- Check for typos or copied whitespace in the environment variable.
- No in-memory fallback is configured, so a Redis outage can cause request errors. For a production deployment, consider `in_memory_fallback_enabled=True` if you prefer degraded rate limiting over errors.

## 7. Adding a new rate-limited route

Put `@app.route(...)` on top, then `@limiter.limit(...)` directly above the view function:

```python
@app.route("/feedback", methods=["POST"])
@limiter.limit("5 per minute")
def feedback():
    ...
```

More examples:

```python
# Limit only the write operation; normal page loads are unrestricted.
@app.route("/profile", methods=["GET", "POST"])
@student_required
@limiter.limit("10 per minute", methods=["POST"])
def profile():
    ...

# Two limits apply to the same route.
@app.route("/api/careers")
@limiter.limit("30 per minute")
@limiter.limit("500 per day")
def api_careers():
    ...
```

If you add a custom key function, it must return a non-empty string for every request; an empty key causes Flask-Limiter to skip the limit. Keep expensive or privileged endpoints on a tighter limit, and prefer `methods=["POST"]` when only state-changing requests should count. New routes without a decorator automatically fall under the 50/hour and 200/day defaults.
