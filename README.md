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

## How the alerts work
- Code decides what is expired, at risk (3 days or less) or late. This keeps the data correct.
- The AI writes the alert emails and the insight report, and answers questions from live table data.
- **Missed/delayed pickup alerts** go to the coordinators. Pickups are checked every 15 minutes while
  `app.py` is running.
- **Expiry risk alerts** go to the coordinators and to volunteers assigned to upcoming shifts before
  the items expire. The full check runs every 6 hours, or on demand with the button.
- Every alert is saved in `Email_Log`. Addresses ending in `.test` are never emailed, only logged.
- It works with any OpenAI-compatible AI service. The default is Google Gemini's free tier
  (5 requests a minute, so leave a few seconds between clicks). Muse AI also works with a paid key.
- If the AI is unreachable, a built-in template is used so alerts still go out.

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
| Automatic email to coordinators on missed/delayed pickup | `ai_engine.pickup_check` (Algorithm 4) |
| AI function for at-risk items, alert to coordinators + shift volunteers | `ai_engine.expiry_check` (Algorithm 3) |
| Report 1: Donation & Distribution Summary, by month or year | `GET /api/report?type=donation` |
| Report 2: Inventory Waste Summary, by month or year | `GET /api/report?type=waste` |

The screens for each role (register, donate, request a hamper, manage inventory and so on) belong to
the frontend/backend part of the team and use these tables.

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
