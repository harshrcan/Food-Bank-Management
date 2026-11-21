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
| `database/seed_data.sql` | Realistic test data: 2,070 inventory records (about 1,000 on the shelf), 206 recipients, 668 hampers |
| `database/generate_seed.py` | Rebuilds `seed_data.sql` if you want different test data |
| `setup_db.py` | Loads the schema and test data, and sets the test passwords |
| `app.py` | Small Flask server: serves the page and the `/api/...` routes |
| `ai_engine.py` | Expiry and pickup checks, alert emails, insight report, questions |
| `static/index.html` | The viewer page (plain HTML + JS, no build step) |
| `check.py` | Pre-demo checklist |
| `perf_test.py` | Performance test for the SRS target (95% under 5 seconds); saves `perf_results.txt` |
| `docs/Food_Bank_DB_and_AI_Explained.pdf` | Plain-English guide: tables, both algorithms, AI, reports, demo script |
| `run_every_6_hours.bat` | Optional Windows task so the AI check runs even when the app is closed |

## Test data
Sized for the SRS performance test (at least 1,000 inventory records and 200 recipients):

| What | Amount |
|---|---|
| Inventory records | 2,070 in total: about 1,000 on the shelf, the rest given out in hampers or expired |
| Stock expiry dates | Spread evenly from **Nov 20 to Dec 10, 2026** (48 items per day) |
| Categories | 8: Canned Goods, Dairy & Eggs, Fresh Produce, Bakery, Dry Goods & Grains, Meat & Protein, Frozen Foods, Baby & Hygiene |
| Recipients | 200 approved + 6 waiting for approval, with household size, dietary needs, emergency contact |
| Hampers | 588 past (Oct 1 to Nov 18: fulfilled, missed, delayed) + 80 upcoming (Nov 21 to Dec 10) |
| Donations | 383 from 30 donors (local businesses, groups and individuals), Sep 22 to Nov 20 |
| Waste history | About 100 items that expired before they were given out |
| Volunteers / shifts | 12 volunteers (Jackson, Pranab, Aman and 9 more), 66 shifts matched to availability |

- Quantities are realistic (for example 6 to 24 cans, 2 to 6 milk jugs, 1 to 3 kg of produce in a hamper).
  Hampers use the food that expires first and respect each household's dietary needs.
- All people and businesses are made up. Phone numbers use the reserved 555-01xx range, and test emails use
  `example.com` / `.example` / `.test` addresses that are never actually emailed.
- If you load the data after Nov 20, `setup_db.py` catches it up to today: past pickups are marked fulfilled and food
  that expired before yesterday is moved to the expiry section (food that expired yesterday is left for the live AI check).
- Every test account uses the password `Password123!` (stored as a bcrypt hash).
- Coordinators (they get every alert): Harsh and AJ.

## API routes (for merging into the main backend)
| Route | Does |
|---|---|
| `GET /api/data` | Every table the viewer shows, as JSON |
| `POST /api/login`, `POST /api/logout` | `{"email","password"}` -> `{"ok","role","user_id"}`; sets a signed login cookie |
| `GET /api/my/history?from=&to=&category=` | The logged-in recipient's own hampers, or the donor's own donations (category filter for donors) |
| `GET /api/search/distributions?recipient=&from=&to=` | Volunteer search of distribution records by recipient name and date |
| `POST /api/distribution/<id>/status` | `{"status": "Fulfilled|Missed|Delayed"}`; Missed or Delayed emails the coordinators right away |
| `GET /api/report?type=donation|waste&year=2026&month=11` | The two report types; leave `month` out for an annual report |
| `POST /api/ai/run` | Runs the expiry + pickup check now, returns a log |
| `POST /api/ai/insights` | AI insight report; send `{"question": "..."}` to ask a question |
| `POST /api/demo/date`, `/api/demo/expiry`, `/api/demo/reset` | Demo controls (remove these in the final app) |

Errors come back as JSON: `{"ok": false, "error": "plain-English reason"}`.

## How the alerts work
- Code decides what is expired, at risk or late. This keeps the data correct. The AI writes the alert emails and the
  insight report, and answers questions from live table data.
- **Missed/delayed pickups (Algorithm 4).** When a volunteer marks a pickup Missed or Delayed on the Hampers page,
  the coordinators are emailed straight away. The system also checks every 15 minutes: 30 minutes late is Delayed,
  and a pickup not collected by the end of its day is Missed (its food goes back on the shelf).
- **At-risk food (Algorithm 3).** For every item in stock:
  - expired: removed and recorded in the expiry section
  - **HIGH**: 3 days or less left
  - **WATCH**: within 7 days, and its category cannot give out everything that expires before it at the current
    pace (units given out per day over the last 28 days). This is "at risk of expiring before it can be distributed".
  - **Declining category**: the stock that will still be good a week from now would last less than 7 days.
- New HIGH items and declining categories trigger one email to the coordinators **and** the volunteers assigned to
  shifts before those items expire. The same item is not alerted again within 24 hours.
- Every alert is saved in `Email_Log`. The full check runs every 6 hours, or on demand with the button.
- Works with any OpenAI-compatible AI service. The default is Google Gemini's free tier (5 requests a minute,
  so leave a few seconds between clicks). If the AI is unreachable, a built-in template writes the email.

## Performance (SRS non-functional requirement)
Run `python perf_test.py`. It times every page load, search and report 20 times on the full test data and checks
that 95% finish under 5 seconds. Last result here: every action **PASS**, slowest 95th percentile about 0.05 s
(the full page data) with 2,070 inventory records and 206 recipients. Use `perf_results.txt` in the testing report.

## Project requirements covered by this part (Option 1)
| Requirement in the project PDF | Where it is |
|---|---|
| Four user roles, everyone logs in | `User_Account` + `Donor`, `Recipient`, `Volunteer`, `Coordinator`; `POST /api/login` |
| Donor: name, phone, email | `Donor`, `User_Account.Email` |
| Recipient: household size, dietary restrictions, emergency contact, approval | `Recipient` (`Approval_Status`, `Approved_By`) |
| Volunteer: ID, name, email, phone, profile image, availability | `Volunteer`, `Volunteer_Availability` |
| Inventory intake from donations, categories | `Donation`, `Inventory_Item`, `Category` |
| Distribution record: recipient, many items with quantities, date/time | `Distribution`, `Distribution_Item` |
| Pickup marked fulfilled, missed or delayed | `Distribution.Status`; buttons on the Hampers page |
| Shifts and volunteer assignment | `Shift`, `Shift_Assignment`, `Distribution.Shift_ID` |
| Recipient views and searches their own distribution history by date | My account page, `GET /api/my/history` |
| Donor views and searches their own donation history by date and category | My account page, `GET /api/my/history` |
| Volunteer searches distribution records by recipient name and date | Hampers page filters, `GET /api/search/distributions` |
| Email to coordinators whenever a pickup is marked missed or delayed | `POST /api/distribution/<id>/status` + `ai_engine.pickup_check` (Algorithm 4) |
| AI function that finds items at risk of expiring before distribution, and declining stock | `ai_engine.expiry_check` (Algorithm 3: HIGH, WATCH, declining) |
| Email about at-risk items to coordinators and volunteers on upcoming shifts | `ai_engine.expiry_check` -> `send_alert` |
| 95% of page loads, searches and reports under 5 s with 1,000+ items and 200+ recipients | `perf_test.py` (PASS) |
| Report 1: Donation & Distribution Summary, by month or year | `GET /api/report?type=donation` |
| Report 2: Inventory Waste Summary, by month or year | `GET /api/report?type=waste` |

The screens for each role (register, donate, request a hamper, manage inventory and so on) belong to
the frontend/backend part of the team and use these tables.

## Demo flow
1. Run `python setup_db.py` on the day, then `python app.py`.
2. **Inventory**: point out HIGH rows (3 days or less) and the expiry dates running to Dec 10.
3. **AI assistant**: click **Run AI check now**. Expired food moves to the Expiry section, HIGH and WATCH items are
   flagged, declining categories are listed, and the alert email appears under **AI alert emails**.
4. **Hampers out**: filter From = today to see upcoming pickups. Click **Missed** on one: the coordinators get an
   email right away (see **AI alert emails**).
5. **My account**: log in as a recipient (any email from the Recipients page, password `Password123!`), show their
   own hampers and filter by date. Log out, log in as a donor and filter by category.
6. **Reports**: both report types, by month or year.
7. To show expiry over time, use **Pretend today is** on the AI page (small jumps of a few days work best), then
   **Reset all test data** at the end.

## Known limits (to handle when merging)
- The viewer has no login wall. It is meant to run on your own computer (it only listens on
  `127.0.0.1`). The main app should put the API routes behind its own login and role checks.
- `/api/demo/*` can change and reset data. Leave those routes out of the final system.
