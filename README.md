# Food Bank Database + AI (INFO 2413, Option 1)

The database part of our Online Food Bank Management System: the MySQL schema, realistic test data,
a web page to view the data, and the Muse AI engine for expiry and pickup alerts.

## Folder
| File | What it is |
|---|---|
| `database/schema.sql` | Creates the `foodbank` database and all tables + views |
| `database/seed_data.sql` | Realistic fake data (220 items, 10 donors, 5 recipients, shifts...) |
| `app.py` | Small Flask server: serves the page and the `/api/...` routes |
| `ai_engine.py` | Expiry + pickup checks, Muse AI emails, insights, Q&A |
| `static/index.html` | The database viewer page (plain HTML + JS) |
| `run_every_6_hours.bat` | Optional Windows task so the AI check runs even when the app is closed |
| `setup_db.py` | Creates the database and loads the test data (no mysql command needed) |
| `make_hash.py` | Makes bcrypt password hashes for test logins |

## Run it (Windows)
```
pip install -r requirements.txt
copy .env.example .env
notepad .env
python setup_db.py
python app.py
```
Then open http://localhost:5000

In `.env`, fill in your MySQL password and `MUSE_API_KEY`. Never commit `.env` (it is in `.gitignore`).

## API routes (for merging into the main backend)
| Route | Does |
|---|---|
| `GET /api/data` | All tables the viewer shows, as JSON |
| `POST /api/ai/run` | Runs the expiry + pickup check now, returns a log |
| `POST /api/ai/insights` | Muse AI report; send `{"question": "..."}` to ask a question |

## How the AI works
- Code decides what is expired, at risk (3 days or less) or late. This keeps the data correct.
- Muse AI writes the alert emails, the insight report, and answers questions from live table data.
- Alerts go only to the coordinators (Harsh and AJ) and are saved in `Email_Log`.
- Runs automatically every 6 hours while `app.py` is running, or on demand with the button.
- If Muse is unreachable, a built-in template is used so alerts still go out.

## Demo controls (AI assistant page)
- **Pretend today is**: set a demo date. Days left, expiry and alerts all use it.
- **Change an item's expiry date**: make any item expire, then click **Run AI check now** to watch it get removed.
- **Reset all test data**: reloads the original data.
