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
| `docs/Food_Bank_DB_and_AI_Explained.pdf` | Plain-English guide: tables, both algorithms, AI, reports, demo script |
| `run_every_6_hours.bat` | Optional Windows task so the AI check also runs when the app is closed |

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
| `POST /api/pickup/status` | `{"distribution_id","status"}` (Fulfilled/Missed/Delayed). Missed/Delayed alerts go out immediately |
| `POST /api/ai/insights` | AI insight report; send `{"question": "..."}` to ask a question |
| `POST /api/demo/date`, `/api/demo/expiry`, `/api/demo/reset` | Demo controls (remove these in the final app) |

Errors come back as JSON: `{"ok": false, "error": "plain-English reason"}`.

## How the alerts work (fully automatic, no button)
- The check runs **by itself**: when `app.py` starts, right after any data change (expiry date, demo
  date, pickup marked missed/delayed, data reset), every `AI_EVERY_HOURS` (default 1), when the day
  changes, and a quick pickup check every `PICKUP_CHECK_MINUTES`. The AI page shows the latest run live.
- The main app should call `trigger_check("reason")` (in `app.py`) after it saves inventory, pickups or shifts.
- **Who gets each email:** every active coordinator **and every volunteer working a shift that day**.
  Expiry alerts also go to volunteers on any shift before the items expire (SRS 3.1.3).
- **Expiry risk (Algorithm 3):** an item is at risk if it expires within `RISK_DAYS` (3) days **or before
  the next distribution shift**. Expired items are moved to `Expiry_Record` and their quantity drops to 0.
- **Declining stock:** categories with fewer than `LOW_STOCK` (5) item lines left get an `Inventory Trend` alert.
- **Missed/delayed pickups (Algorithm 4):** late pickups are marked automatically, and a volunteer marking
  one through `/api/pickup/status` sends the email straight away.
- Code decides what is expired, at risk or late, so the data is always correct. The AI only writes the
  email text, the insight report and answers. If the AI is unreachable, a built-in template is used.
- Every email is saved in `Email_Log` (Sent / Logged only / Failed). Test accounts end in `.test`; set
  `ALERT_REDIRECT_TO` in `.env` and their emails are delivered to that real inbox, marked with who they were for.
- Real sending needs `SMTP_USER` + `SMTP_PASS` (Gmail App Password) in `.env`. `python check.py` tests the login.

## Project requirements covered by this part (Option 1)
| Requirement in the project PDF | Where it is |
|---|---|
| Four user roles, everyone logs in | `User_Account` + `Donor`, `Recipient`, `Volunteer`, `Coordinator`; `POST /api/login` |
| Donor: name, phone, email | `Donor`, `User_Account.Email` |
| Recipient: household size, dietary restrictions, emergency contact, approval | `Recipient` (`Approval_Status`, `Approved_By`) |
| Volunteer: ID, name, email, phone, profile image, availability | `Volunteer`, `Volunteer_Availability` |
| Inventory intake from donations, categories | `Donation`, `Inventory_Item`, `Category` |
| Distribution record: recipient, many items with quantities, date/time | `Distribution`, `Distribution_Item` |
| Pickup marked fulfilled, missed or delayed | `Distribution.Status` |
| Shifts and volunteer assignment | `Shift`, `Shift_Assignment`, `Distribution.Shift_ID` |
| Search donation history by date/category, distributions by recipient/date | Views `Donation_Details`, `Distribution_Details` |
| Automatic email to coordinators on missed/delayed pickup (SRS 3.1.3) | `ai_engine.pickup_check` (Algorithm 4), `/api/pickup/status` |
| AI function for items at risk of expiring before distribution + declining stock, alert to coordinators + shift volunteers (SRS 3.1.3) | `ai_engine.expiry_check`, `ai_engine.declining_stock` |
| Quantity reduced when expired items are removed (SRS 3.1.2) | `ai_engine.expiry_check` |
| Hamper status pending/scheduled/fulfilled/missed/delayed (SRS 3.1.2) | `Distribution.Status` |
| Passwords hashed with bcrypt, work factor 12 (SRS 3.2.2) | `setup_db.hash_password` |
| Report 1: Donation & Distribution Summary, by month or year | `GET /api/report?type=donation` |
| Report 2: Inventory Waste Summary, by month or year | `GET /api/report?type=waste` |

The screens for each role (register, donate, request a hamper, manage inventory and so on) belong to
the frontend/backend part of the team and use these tables.

## Demo flow (AI assistant page)
1. Click **Reset all test data**. The AI check runs by itself a moment later.
2. Under **Change an item's expiry date**, set an item to tomorrow, or use **Pretend today is** to jump
   to a shift day. The check runs automatically and the new emails appear under **AI alert emails**.
3. Open **Reports** for the Donation & Distribution Summary and the Inventory Waste Summary.

## Known limits (to handle when merging)
- The viewer has no login wall. It is meant to run on your own computer (it only listens on
  `127.0.0.1`). The main app should put the API routes behind its own login and role checks.
- `/api/demo/*` can change and reset data. Leave those routes out of the final system.
