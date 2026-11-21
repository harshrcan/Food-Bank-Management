# Surrey Community Food Bank: Database + AI

INFO 2413 team project (Option 1). This part holds the database, the test data, the logins, the automatic
alerts, the reports and a web page to see it all.

## How it is built
| Part | Made with | File |
|---|---|---|
| Database | MySQL | `database/schema.sql` |
| Test data | Python script that writes SQL | `database/generate_seed.py`, `database/seed_data.sql` |
| Backend | Python + Flask | `app.py`, `ai_engine.py` |
| Frontend | One HTML page with plain JavaScript | `static/index.html` |
| AI | Google Gemini (free) | called from `ai_engine.py` |
| Email | Gmail (SMTP) | called from `ai_engine.py` |

## What is in it
- **Database:** users and logins, donors, recipients, volunteers, coordinators, food categories, donations,
  inventory, hampers (with many items each), shifts, expired food, alerts, sent emails and reports.
- **Test data:** about 1,000 items on the shelf expiring Nov 20 to Dec 10, 206 recipients, 668 hampers,
  383 donations, 12 volunteers. All names are made up. Every test login uses the password `Password123!`.
- **Frontend pages:** overview, donations, hampers, inventory, expired food, people, shifts, AI assistant,
  sent emails, reports, logins, and **My account** (a recipient or donor sees only their own history).

## How it works
1. The **frontend** page asks the **backend** for data and shows it in tables.
2. The **backend** reads and writes MySQL, and is the only part that talks to the AI and to Gmail
   (so the keys stay hidden).
3. **Expiry check** (every 6 hours, or the button): removes expired food, marks food with 3 days or less
   as HIGH, marks food that will expire before it can all be given out as WATCH, and spots categories
   running low. It emails the coordinators and the volunteers on upcoming shifts.
4. **Pickup check:** when a volunteer marks a pickup Missed or Delayed (or it runs late), the coordinators
   get an email straight away.
5. The **AI** only writes the email text and the insight report. The rules above are plain code, so the
   results are always correct. If the AI is down, a simple template is used.
6. **Reports:** Donation & Distribution Summary and Inventory Waste Summary, by month or year.

## Run it
```
pip install -r requirements.txt
copy .env.example .env
python setup_db.py
python app.py
```
Open http://localhost:5000. Fill in `.env` first (MySQL password, AI key, Gmail details).

## Email setup (to really send to the coordinators)
1. Use a Gmail account, turn on 2-Step Verification.
2. Make an App Password at https://myaccount.google.com/apppasswords.
3. In `.env`: `SMTP_USER=` that Gmail address, `SMTP_PASS=` the 16-letter App Password.
4. Restart the app and click **Send a test email** on the AI assistant page
   (or run `python ai_engine.py --test-email`). Check the junk folder the first time.

Emails go to Harsh (harsh.rana1@student.kpu.ca) and AJ (ajit.thapa@student.kpu.ca).
Made-up test accounts (`.test`, `example.com`) are only logged, never emailed.

## Helpful extras
- `python check.py`: checks MySQL, data, logins, AI and email before a demo.
- `python perf_test.py`: proves 95% of pages, searches and reports load in under 5 seconds.
- `docs/Food_Bank_DB_and_AI_Explained.pdf`: the full explanation with diagrams.
