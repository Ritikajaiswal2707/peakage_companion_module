# PeakAge Companion Academy (LMS)

PeakAge-branded training platform for companions. Companions create an account with their mobile number, follow a visual journey through 9 online modules with interactive quizzes, then complete 4 offline steps with their coordinator. When everything is done, they get a **PeakAge Certified Companion** certificate with a public verification link. Every attempt and score is saved per companion. Admins see everyone's progress, tick off offline steps, reset attempts and passwords, and download a CSV.

**The journey:** 9 online modules → offline practice day → police verification and references → shadow visit → supervised visit → 🏅 certificate.

## What's inside

**9 modules (everything needed to go solo), unlocked one after another:**

| # | Code | Module | Lessons | Quiz |
|---|---|---|---|---|
| 1 | B1 | The 5 roles of a PeakAge companion | 3 | 5 of 8 |
| 2 | P1 | Conduct, dress and punctuality | 3 | 5 of 7 |
| 3 | M1 | Companion, not doctor | 3 | 5 of 7 |
| 4 | S1 | Money rules | 3 | 5 of 7 |
| 5 | S2 | Companion safety and boundaries | 3 | 5 of 7 |
| 6 | B3 | Elder personas | 4 | 8 of 12 |
| 7 | T2 | Hospital visit SOP | 8 | 10 of 16 |
| 8 | T3 | The WhatsApp visit report | 3 | 5 of 6 |
| 9 | E1 | Red flags and emergencies | 3 | 8 of 10 |

"5 of 8" means each quiz draws 5 random questions from a bank of 8.

**Interactive quiz:** one question at a time, with a live progress bar and score. Each answer is locked in when tapped and checked on the server immediately: green for right, red with an explanation for wrong. The result page has an animated score ring and confetti on a pass.

**Quiz rules (set per module in its JSON file):**
- The companion must open every lesson before the quiz unlocks.
- Pass mark 80%. Questions and answer order are shuffled for each attempt.
- 2 attempts. After that the module is blocked until an admin resets it (the "call your coordinator" step).
- Reloading the quiz page keeps the same questions and the answers already locked in, so it can't be used to fish for easier questions or change an answer.
- Correct answers never reach the phone before an answer is locked in; everything is graded on the server.
- Passing a module unlocks the next one.

**Certificate:** issued automatically once all online modules and all offline steps are done. It has a unique ID (e.g. `PA-503C1825`), a Print / Save as PDF button, and a public page at `/verify/<ID>` that anyone (a family, a college) can use to check it's genuine.

**Admin dashboard (`/admin`):**
- A grid of every companion × every module, plus offline steps and certificate: passed, best score, blocked, open or locked
- Filter by city, download everything as CSV
- Open a companion to tick off offline steps, see their full quiz history, reset attempts on a blocked module, or set a new password

## Deploy on Render

1. Push this folder to a GitHub repo.
2. In Render: **New → Blueprint**, pick the repo. Render reads `render.yaml` and creates the web service and a Postgres database.
3. When asked, fill in:
   - `ADMIN_PHONES`: your 10-digit mobile number (comma-separate several, e.g. `9876543210,9123456789`)
   - `REGISTRATION_CODE`: a code you give companions so strangers can't sign up (e.g. `PEAKAGE2026`). Leave empty to allow anyone.
4. Deploy. When it's live, open the URL and **register with an admin phone number**. You'll land on the admin dashboard.
5. Share the URL and the registration code with companions.

> ⚠️ **Upgrade the database before day 30.** Render's free Postgres database expires 30 days after it's created, and all companion scores are in it. Before then, either upgrade it to a paid instance in the Render dashboard, or point `DATABASE_URL` at another Postgres provider. The free web service also sleeps when nobody uses it, so the first page load after a quiet spell can take up to a minute.

## Editing content (no coding needed)

Each module is one file in `content/modules/`. Open it on GitHub, edit, commit; Render redeploys automatically.

- **Lesson text:** the `body` field, in Markdown (`**bold**`, `- lists`, `| tables |`, `> quotes`).
- **Videos:** paste a YouTube link (unlisted is fine) into a lesson's `video_url`. It's embedded above the text.
- **Questions:** each has an `id` (must be unique, never reuse an old one), `text`, `options`, and `answer` = the position of the correct option counting from 0 (first option = 0).
- **Rules:** `pass_percent`, `questions_per_quiz` (must be ≤ the number of questions), `max_attempts`.
- **New module:** copy a file, give it a new `code` and `order`. Modules unlock in `order`.
- **Offline steps:** edit `content/offline_steps.json`. Each step needs a unique `code`, a `title` and a `description`. Don't rename a `code` once companions have it ticked.
- **Branding:** the logo files are in `app/static/img/`, and colours are at the top of `app/static/style.css` (`--orange` is the PeakAge orange from the logo, `--navy` the header).

If a file has a mistake (e.g. an `answer` out of range), the app refuses to start and the Render log names the file and the problem.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export ADMIN_PHONES=9876543210        # Windows: set ADMIN_PHONES=9876543210
uvicorn app.main:app --reload
```

Open http://localhost:8000. Without `DATABASE_URL`, data goes into a local `lms.db` SQLite file. Run the tests with `pytest`.

## Environment variables

| Name | What it does |
|---|---|
| `DATABASE_URL` | Postgres connection string (Render fills it in). Unset = local SQLite. |
| `SECRET_KEY` | Signs login cookies. Render generates it. |
| `ADMIN_PHONES` | Mobile numbers that get admin access. Checked at every login. |
| `REGISTRATION_CODE` | Optional code required to sign up. |
| `HTTPS_ONLY` | `true` on Render, `false` locally. |

## Project layout

```
app/
  main.py        routes: sign-up, login, modules, lessons, quiz, admin
  content.py     loads and checks content/modules/*.json
  progress.py    works out locked / open / passed / blocked per module, issues certificates
  models.py      tables: users, lesson_views, quiz_attempts, offline_steps, certificates
  db.py          database connection
  security.py    password hashing
  templates/     pages (Jinja)
  static/        style.css, app.js (quiz, progress rings, confetti), img/ (logo, favicon)
content/modules/ one JSON file per module
content/offline_steps.json  the offline steps
tests/           end-to-end tests
render.yaml      Render Blueprint
```
