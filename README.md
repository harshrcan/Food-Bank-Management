# Food Bank Database + AI (INFO 2413, Option 1)

The database and AI part of our Online Food Bank Management System: the MySQL schema, realistic
test data, user logins, reports, a web page to view everything, and the AI engine for expiry and
pickup alerts.

## Run it (Windows)
```
pip install -r requirements.txt
copy .env.example .env
notepad .env
python setup_db.py
python app.py
```
Then open http://localhost:5000

In `.env`, fill in your MySQL password and `AI_API_KEY` (free Gemini key from
https://aistudio.google.com/apikey). Never commit `.env` (it is in `.gitignore`).

Before a demo, run `python check.py`. It checks MySQL, the test data, the logins and the AI
connection, and tells you what to fix.

## Folder
| File | What it is |
|---|---|
| `database/schema.sql` | Creates the `foodbank` database: all tables and views |
| `database/seed_data.sql` | Realistic test data (220 items, 10 donors, 6 recipients, shifts, hampers) |
| `database/generate_seed.py` | Rebuilds `seed_data.sql` if you want different test data |
| `setup_db.py` | Loads the schema and test data, and sets the test passwords |
| `app.py` | Small Flask server: serves the page and the `/api/...` routes |
| `ai_engine.py` | Expiry and pickup checks, alert emails, insight report, questions |
| `static/index.html` | The viewer page (plain HTML + JS, no build step) |
| `check.py` | Pre-demo checklist |
| `run_every_6_hours.bat` | Optional Windows task so the AI check runs even when the app is closed |

## Test data
- Dates are relative to the day you run `setup_db.py`, so the data is always fresh: some items
  already expired, some expiring soon, past hampers, one missed pickup and one upcoming pickup.
- Every test account uses the password `Password123!` (stored as a bcrypt hash).
- Coordinators (they get the alert emails): Harsh and AJ. Volunteers: Jackson, Pranab, Aman.

## API routes (for merging into the main backend)
| Route | Does |
|---|---|
| `GET /api/data` | Every table the viewer shows, as JSON |
| `POST /api/login` | `{"email","password"}` -> `{"ok","role","user_id"}`; updates `Last_Login` |
| `GET /api/report?type=donation|waste&year=2026&month=11` | The two report types; leave `month` out for an annual report |
| `POST /api/ai/run` | Runs the expiry + pickup check now, returns a log |
| `POST /api/ai/insights` | AI insight report; send `{"question": "..."}` to ask a question |
| `POST /api/demo/date`, `/api/demo/expiry`, `/api/demo/reset` | Demo controls (remove these in the final app) |

Errors come back as JSON: `{"ok": false, "error": "plain-English reason"}`.

## How the AI works
- Code decides what is expired, at risk (3 days or less) or late. This keeps the data correct.
- The AI writes the alert emails and the insight report, and answers questions from live table data.
- It works with any OpenAI-compatible service. The default is Google Gemini's free tier
  (5 requests a minute, so leave a few seconds between clicks). Muse AI also works with a paid key.
- Alerts go only to the coordinators and are saved in `Email_Log`.
- The check runs automatically every 6 hours while `app.py` is running, or on demand with the button.
- If the AI is unreachable, a built-in template is used so alerts still go out.

## Demo flow (AI assistant page)
1. Click **Reset all test data**.
2. Under **Change an item's expiry date**, pick an item and set it to yesterday.
   Or use **Pretend today is** to jump a few days ahead.
3. Click **Run AI check now**. Expired items move to the Expiry section, at-risk items are
   flagged, the upcoming pickup becomes missed if its date has passed, and the alert emails appear
   under **AI alert emails**.
4. Open **Reports** for the Donation & Distribution Summary and the Inventory Waste Summary.

## Known limits (to handle when merging)
- The viewer has no login wall. It is meant to run on your own computer (it only listens on
  `127.0.0.1`). The main app should put the API routes behind its own login and role checks.
- `/api/demo/*` can change and reset data. Leave those routes out of the final system.
