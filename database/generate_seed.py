"""
Rebuilds database/seed_data.sql (only needed if you want to change the test data).

    python database/generate_seed.py

Test data timeline (matches the SRS test plan):
  - "Data date" is Nov 20, 2026. History runs from late September up to that day.
  - About 1,000 items on the shelf, with expiry dates spread evenly from Nov 20 to Dec 10, 2026
    (recent donations top up the days that hampers emptied, so every day has about the same count).
  - 800 older items: most were given out in hampers, the leftovers expired (the waste history).
  - 200 approved recipients (plus a few waiting for approval) with past hampers, and upcoming
    scheduled pickups between Nov 21 and Dec 10.
setup_db.py brings the data up to the real date when it loads it (past pickups marked fulfilled,
long-expired items moved to the expiry section), so it stays believable on demo day.
All people and businesses are made up. Phone numbers use the reserved 555-01xx range.
"""
import os, random, datetime as dt
from collections import defaultdict

random.seed(2413)
D0 = dt.date(2026, 11, 20)                # data date ("today" for the test data)
WIN_END = dt.date(2026, 12, 10)           # current stock expires between D0 and WIN_END
HIST_START = dt.date(2026, 9, 22)         # first donations
DIST_START = dt.date(2026, 10, 1)         # first hampers
N_CURRENT, N_HIST, N_RECIP = 1000, 800, 200
H = "SET_BY_SETUP_DB"                     # setup_db.py replaces this with a real password hash


def q(v):
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def ts(d, h, m=0): return f"{d:%Y-%m-%d} {h:02d}:{m:02d}:00"


CATS = ["Canned Goods", "Dairy & Eggs", "Fresh Produce", "Bakery", "Dry Goods & Grains",
        "Meat & Protein", "Frozen Foods", "Baby & Hygiene"]
WEIGHT = {1: 19, 2: 13, 3: 15, 4: 10, 5: 16, 6: 9, 7: 7, 8: 11}
LONG = 999   # shelf-stable: donation date is picked freely

# name, category, unit, quantity per donated line, shelf life in days (min, max)
P = [("Tomato Soup 284 mL", 1, "can", (6, 24), (LONG, LONG)), ("Chicken Noodle Soup 540 mL", 1, "can", (6, 18), (LONG, LONG)),
     ("Black Beans 540 mL", 1, "can", (6, 24), (LONG, LONG)), ("Chickpeas 540 mL", 1, "can", (6, 24), (LONG, LONG)),
     ("Red Kidney Beans 540 mL", 1, "can", (6, 18), (LONG, LONG)), ("Flaked Light Tuna 170 g", 1, "can", (6, 24), (LONG, LONG)),
     ("Pink Salmon 213 g", 1, "can", (4, 12), (LONG, LONG)), ("Whole Kernel Corn 341 mL", 1, "can", (6, 18), (LONG, LONG)),
     ("Cut Green Beans 398 mL", 1, "can", (6, 18), (LONG, LONG)), ("Diced Tomatoes 796 mL", 1, "can", (6, 12), (LONG, LONG)),
     ("Pasta Sauce 680 mL", 1, "jar", (4, 12), (LONG, LONG)), ("Peaches in Juice 398 mL", 1, "can", (6, 12), (LONG, LONG)),
     ("Baked Beans 398 mL", 1, "can", (6, 18), (LONG, LONG)), ("Coconut Milk 400 mL", 1, "can", (4, 12), (LONG, LONG)),
     ("2% Milk 4 L", 2, "jug", (2, 6), (10, 16)), ("Lactose-Free Milk 2 L", 2, "carton", (2, 6), (14, 21)),
     ("Large Eggs", 2, "dozen", (2, 8), (21, 35)), ("Plain Yogurt 750 g", 2, "tub", (2, 8), (14, 28)),
     ("Medium Cheddar 400 g", 2, "block", (2, 6), (30, 60)), ("Salted Butter 454 g", 2, "block", (2, 6), (30, 60)),
     ("Cottage Cheese 500 g", 2, "tub", (2, 6), (14, 21)),
     ("Gala Apples", 3, "kg", (3, 12), (14, 30)), ("Bananas", 3, "kg", (2, 8), (4, 8)), ("Carrots", 3, "kg", (3, 12), (14, 30)),
     ("Russet Potatoes", 3, "kg", (5, 20), (21, 45)), ("Yellow Onions", 3, "kg", (3, 10), (21, 45)),
     ("Baby Spinach 312 g", 3, "bag", (2, 8), (5, 8)), ("Roma Tomatoes", 3, "kg", (2, 6), (5, 10)),
     ("Navel Oranges", 3, "kg", (3, 10), (14, 28)), ("Green Cabbage", 3, "head", (2, 6), (14, 28)),
     ("Whole Wheat Bread 675 g", 4, "loaf", (3, 12), (5, 8)), ("White Sandwich Bread 675 g", 4, "loaf", (3, 12), (5, 8)),
     ("Plain Bagels 6-pack", 4, "pack", (2, 8), (5, 8)), ("Flour Tortillas 10-pack", 4, "pack", (2, 8), (14, 21)),
     ("Dinner Rolls 12-pack", 4, "pack", (2, 6), (4, 6)), ("Plain Naan 4-pack", 4, "pack", (2, 6), (6, 10)),
     ("Long Grain White Rice 2 kg", 5, "bag", (2, 8), (LONG, LONG)), ("Basmati Rice 4 kg", 5, "bag", (1, 4), (LONG, LONG)),
     ("Spaghetti 900 g", 5, "box", (4, 12), (LONG, LONG)), ("Penne 900 g", 5, "box", (4, 12), (LONG, LONG)),
     ("Large Flake Oats 1 kg", 5, "bag", (2, 8), (LONG, LONG)), ("Red Lentils 900 g", 5, "bag", (2, 8), (LONG, LONG)),
     ("Atta Flour 10 kg", 5, "bag", (1, 3), (LONG, LONG)), ("Toasted Oat Cereal 525 g", 5, "box", (2, 8), (LONG, LONG)),
     ("Peanut Butter 1 kg", 6, "jar", (2, 8), (LONG, LONG)), ("Lean Ground Beef 454 g", 6, "pack", (2, 8), (2, 4)),
     ("Chicken Thighs 1 kg", 6, "pack", (2, 6), (2, 5)), ("Halal Chicken Breast 1 kg", 6, "pack", (2, 6), (2, 5)),
     ("Firm Tofu 454 g", 6, "block", (2, 8), (14, 30)),
     ("Frozen Mixed Vegetables 750 g", 7, "bag", (3, 10), (LONG, LONG)), ("Frozen Chicken Strips 700 g", 7, "box", (2, 6), (LONG, LONG)),
     ("Frozen Fish Fillets 400 g", 7, "box", (2, 6), (LONG, LONG)), ("Frozen Perogies 1 kg", 7, "bag", (2, 6), (LONG, LONG)),
     ("Diapers Size 4 (34)", 8, "pack", (1, 4), (LONG, LONG)), ("Baby Formula 900 g", 8, "can", (1, 4), (LONG, LONG)),
     ("Toothpaste 100 mL", 8, "tube", (4, 12), (LONG, LONG)), ("Bar Soap 4-pack", 8, "pack", (3, 10), (LONG, LONG)),
     ("Shampoo 750 mL", 8, "bottle", (2, 6), (LONG, LONG)), ("Menstrual Pads 36-pack", 8, "pack", (2, 6), (LONG, LONG))]
TAKE = {"can": (2, 4), "jar": (1, 2), "jug": (1, 2), "carton": (1, 2), "dozen": (1, 1), "tub": (1, 1), "block": (1, 1), "kg": (1, 3),
        "bag": (1, 2), "head": (1, 1), "loaf": (1, 2), "pack": (1, 2), "box": (1, 2), "tube": (1, 1), "bottle": (1, 1)}

# first and last names grouped by background, so most people get a name that fits together
NAMES = {
    "south_asian": (["Aarav", "Amandeep", "Ananya", "Arjun", "Baljit", "Deepa", "Divya", "Gagandeep", "Gurpreet", "Harjit", "Jasleen",
                     "Jaspreet", "Karan", "Kavya", "Kiran", "Manpreet", "Navdeep", "Parminder", "Priya", "Rajesh", "Rohan", "Sandeep",
                     "Simran", "Sunita", "Usha", "Lakshmi", "Harpreet", "Rupinder", "Anil", "Meena"],
                    ["Sandhu", "Gill", "Dhillon", "Grewal", "Sidhu", "Brar", "Johal", "Bains", "Mann", "Sharma", "Patel", "Chopra",
                     "Malhotra", "Kaur", "Singh", "Randhawa", "Toor", "Aujla", "Gupta", "Reddy"]),
    "east_asian": (["Chen", "Jia", "Mei", "Wei", "Xin", "Hyun", "Min-jun", "Jin", "Ying", "Hao", "Soo-ah", "Kenji", "Yuki", "Lei", "Hui"],
                   ["Chen", "Wang", "Li", "Zhang", "Liu", "Huang", "Kim", "Park", "Lee", "Choi", "Wu", "Zhou", "Nakamura", "Tanaka", "Ho"]),
    "southeast_asian": (["Thi", "Quang", "Ngoc", "Minh", "Linh", "Joy", "Maricel", "Rodel", "Jericho", "Analyn", "Paolo", "Kristine"],
                        ["Nguyen", "Tran", "Le", "Pham", "Vo", "Santos", "Reyes", "Cruz", "Bautista", "Dela Cruz", "Mendoza", "Villanueva"]),
    "latin": (["Alejandro", "Carmen", "Diego", "Elena", "Javier", "Lucia", "Marisol", "Miguel", "Rafael", "Ramon", "Ricardo", "Rosa",
               "Sergio", "Sofia", "Jorge", "Patricia", "Eduardo", "Ines"],
              ["Garcia", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Perez", "Silva", "Ramirez", "Torres", "Flores", "Morales"]),
    "middle_east_africa": (["Aisha", "Amira", "Fatima", "Hassan", "Khalid", "Leila", "Mohammed", "Nadia", "Omar", "Sana", "Yasmin",
                            "Yusuf", "Zainab", "Rizwan", "Farah", "Imran", "Ayesha", "Mustafa", "Emmanuel", "Chidi", "Abena", "Tesfaye"],
                           ["Khan", "Ahmed", "Hussain", "Ali", "Rahman", "Hassan", "Haddad", "Mansour", "Okafor", "Mensah", "Adeyemi",
                            "Abebe", "Mohamed", "Siddiqui", "Qureshi"]),
    "anglo_european": (["Angela", "Ava", "Benjamin", "Brandon", "Charlotte", "Christopher", "Daniel", "Emily", "Grace", "Jacob", "Jennifer",
                        "Joseph", "Kevin", "Laura", "Liam", "Mark", "Michelle", "Nicole", "Noah", "Olivia", "Rebecca", "Samuel", "Sarah",
                        "Thomas", "William", "Zoe", "Megan", "Ryan", "Heather", "Tyler", "Brianna", "Marek", "Ana"],
                       ["Smith", "Brown", "Wilson", "Thompson", "Campbell", "Anderson", "MacDonald", "Taylor", "Martin", "Clarke", "Walker",
                        "Robinson", "Mitchell", "Fraser", "Stewart", "Morrison", "Tremblay", "Gagnon", "Roy", "Kowalski", "Nowak",
                        "Popescu", "Rossi", "Murphy", "O'Brien"])}
GROUP_W = {"south_asian": 34, "east_asian": 14, "southeast_asian": 12, "latin": 8, "middle_east_africa": 12, "anglo_european": 20}
FIRST = [f for g in NAMES.values() for f in g[0]]
DIETS = [("None", 52), ("Vegetarian", 9), ("Halal", 10), ("Lactose intolerant", 7), ("Peanut allergy", 5), ("Gluten-free", 4),
         ("Diabetic-friendly", 5), ("Vegan", 2), ("Vegetarian, no eggs", 3), ("Kosher", 1), ("Shellfish allergy", 2)]
BANNED = {"Vegetarian": ["Beef", "Chicken", "Tuna", "Salmon", "Fish"], "Vegetarian, no eggs": ["Beef", "Chicken", "Tuna", "Salmon", "Fish", "Eggs"],
          "Vegan": ["Beef", "Chicken", "Tuna", "Salmon", "Fish", "Eggs", "Milk", "Yogurt", "Cheddar", "Butter", "Cheese"],
          "Halal": ["Lean Ground Beef", "Chicken Thighs", "Chicken Strips"], "Kosher": ["Lean Ground Beef", "Chicken Thighs", "Chicken Strips"],
          "Lactose intolerant": ["2% Milk", "Yogurt", "Cheddar", "Butter", "Cottage Cheese"], "Peanut allergy": ["Peanut"],
          "Gluten-free": ["Bread", "Bagels", "Tortillas", "Rolls", "Naan", "Spaghetti", "Penne", "Flour", "Oats", "Cereal", "Perogies", "Chicken Strips"],
          "Diabetic-friendly": ["Peaches", "Cereal"], "Shellfish allergy": []}
RELATION = ["spouse", "sibling", "parent", "adult child", "cousin", "friend", "neighbour"]

PHONES = [f"{a}-555-01{n:02d}" for a in (604, 778, 236, 672) for n in range(100)]
random.shuffle(PHONES)
used_names, family = set(), {}


def person():
    while True:
        g = random.choices(list(GROUP_W), list(GROUP_W.values()))[0]
        last_g = g if random.random() < 0.88 else random.choice(list(NAMES))     # some mixed families
        n = f"{random.choice(NAMES[g][0])} {random.choice(NAMES[last_g][1])}"
        if n not in used_names:
            used_names.add(n)
            family[n] = last_g
            return n


def email_for(name, domain="example.com"):
    return name.lower().replace(" ", ".").replace("'", "").replace("-", "") + "@" + domain


o = ["USE foodbank;", "SET FOREIGN_KEY_CHECKS=0;"]


def bulk(table, cols, rows, size=200):
    for i in range(0, len(rows), size):
        o.append(f"INSERT INTO {table} ({','.join(cols)}) VALUES\n" +
                 ",\n".join("(" + ",".join(q(v) for v in r) + ")" for r in rows[i:i + size]) + ";")


users = []   # (User_ID, Email, Password_Hash, Role, Created_At)


def add_user(email, role, created):
    users.append((len(users) + 1, email, H, role, created))
    return len(users)


# ---------------- people ----------------
coords = []
for n, e in [("Harsh", "harsh.rana1@student.kpu.ca"), ("AJ", "ajit.thapa@student.kpu.ca")]:
    coords.append((len(coords) + 1, add_user(e, "Coordinator", "2026-09-01 09:00:00"), n, PHONES.pop()))

# volunteers: the three teammates, plus local volunteers
VOL = [("Jackson", "jackson@surreyfoodbank.test", [("Mon", "12:00", "18:00"), ("Fri", "12:00", "18:00"), ("Sat", "09:00", "15:00")]),
       ("Pranab", "pranab@surreyfoodbank.test", [("Mon", "09:00", "17:00"), ("Wed", "09:00", "17:00")]),
       ("Aman", "aman@surreyfoodbank.test", [("Wed", "12:00", "18:00"), ("Sat", "09:00", "15:00")])]
for days in ([("Mon", "12:00", "18:00"), ("Wed", "12:00", "18:00")], [("Fri", "12:00", "18:00"), ("Sat", "09:00", "15:00")],
             [("Wed", "09:00", "13:00"), ("Sat", "09:00", "13:00")], [("Mon", "12:00", "18:00"), ("Fri", "12:00", "18:00")],
             [("Wed", "09:00", "18:00")], [("Sat", "09:00", "15:00"), ("Mon", "12:00", "18:00")],
             [("Fri", "12:00", "18:00"), ("Wed", "12:00", "18:00")], [("Sat", "09:00", "15:00")], [("Mon", "09:00", "13:00"), ("Fri", "12:00", "18:00")]):
    n = person()
    VOL.append((n, email_for(n), days))
vols = []
for i, (n, e, days) in enumerate(VOL, 1):
    u = add_user(e, "Volunteer", "2026-09-05 10:00:00")
    vols.append((i, u, n, PHONES.pop(), f"images/volunteers/{n.split()[0].lower()}{i}.jpg",
                 ", ".join(f"{d} {a}-{b}" for d, a, b in days), 1 + i % 2, days))

# donors: local businesses and groups (made up), plus individuals
BIZ = [("Fleetwood Fresh Market", "Business", [3, 2, 4]), ("Fraser Heights Bakehouse", "Business", [4]),
       ("Sullivan Heights Community Church", "Organization", [1, 5, 8]), ("Bridgeview Dairy Co-op", "Business", [2]),
       ("Green Timbers Grocers", "Business", [3, 5, 1]), ("KPU Student Union Food Drive", "Organization", [1, 5, 8]),
       ("Cloverdale Family Farms", "Business", [3]), ("Whalley Wholesale Foods", "Business", [1, 5, 7, 6]),
       ("Panorama Ridge Rotisserie", "Business", [6, 7]), ("Newton Seniors Association", "Organization", [1, 5]),
       ("Tynehead Halal Meats", "Business", [6]), ("Guildford Family Pharmacy", "Business", [8])]
donors = []
for i, (n, t, pref) in enumerate(BIZ, 1):
    slug = n.lower().replace(" ", "").replace(".", "")
    donors.append((i, add_user(f"info@{slug}.example", "Donor", "2026-09-10 12:00:00"), n, t, PHONES.pop(), pref))
for _ in range(18):
    n = person()
    donors.append((len(donors) + 1, add_user(email_for(n), "Donor", "2026-09-15 12:00:00"), n, "Individual", PHONES.pop(),
                   random.choice([[1, 5], [1, 5, 8], [5, 1], [8, 1], [1, 7]])))

recips = []
for i in range(N_RECIP + 6):
    n = person()
    hh = random.choices([1, 2, 3, 4, 5, 6, 7], [20, 25, 18, 17, 10, 6, 4])[0]
    diet = random.choices([d for d, _ in DIETS], [w for _, w in DIETS])[0]
    rel = random.choice(RELATION)
    ec_name = (f"{random.choice(NAMES[family[n]][0])} {n.split(' ', 1)[1]}" if rel not in ("friend", "neighbour")
               else f"{random.choice(FIRST)} {random.choice(NAMES[random.choice(list(NAMES))][1])}")
    ec = f"{ec_name} ({rel}), {random.choice(['604', '778', '236'])}-555-01{random.randint(0, 99):02d}"
    created = dt.datetime(2026, 9, 1) + dt.timedelta(days=random.randint(0, 45), hours=random.randint(9, 17))
    approved = i < N_RECIP
    u = add_user(email_for(n), "Recipient", f"{created:%Y-%m-%d %H:%M:00}")
    recips.append(dict(id=i + 1, user=u, name=n, hh=hh, diet=diet, phone=PHONES.pop(), ec=ec,
                       status="Approved" if approved else "Pending", by=(1 + i % 2) if approved else None,
                       banned=BANNED.get(diet, [])))

# ---------------- shifts (Sep 28 to Dec 13) ----------------
SLOTS = {0: [("Hamper distribution desk", 13, 17)], 2: [("Donation pickup & intake", 9, 13), ("Hamper distribution desk", 13, 17)],
         4: [("Hamper distribution desk", 13, 17)], 5: [("Donation pickup & intake", 9, 12), ("Hamper distribution desk", 12, 15)]}
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
shifts, assign, dist_shifts, intake_by_day = [], [], [], {}
d = dt.date(2026, 9, 28)
while d <= dt.date(2026, 12, 13):
    for task, h1, h2 in SLOTS.get(d.weekday(), []):
        sid = len(shifts) + 1
        shifts.append((sid, ts(d, h1), ts(d, h2), task, 1 + sid % 2))
        free = [v for v in vols if any(day == DOW[d.weekday()] and int(a[:2]) <= h1 and int(b[:2]) >= h2 for day, a, b in v[7])]
        team = random.sample(free, min(len(free), 3 if "distribution" in task else 2))
        for v in team:
            assign.append((sid, v[0]))
        if "distribution" in task:
            dist_shifts.append((d, h1, h2, sid, [v[0] for v in team]))
        else:
            intake_by_day[d] = [v[0] for v in team]
    d += dt.timedelta(days=1)

# ---------------- inventory ----------------
items = []   # dicts


def pick_product(exp, start):
    """A product whose shelf life fits: donated on or after `start`, on or before D0, and before it expires."""
    latest = min(D0, exp - dt.timedelta(days=1))
    while True:
        c = random.choices(list(WEIGHT), list(WEIGHT.values()))[0]
        prods = [p for p in P if p[1] == c and (p[4][0] == LONG or (exp - latest).days <= p[4][1])]
        if not prods:
            continue
        name, cat, unit, qr, (s1, s2) = random.choice(prods)
        if s1 == LONG:
            hi = min(latest, exp - dt.timedelta(days=30))
            if hi < start:
                hi = latest
            don = start + dt.timedelta(days=random.randint(0, max(0, (hi - start).days)))
        else:
            shelf = random.randint(max(s1, (exp - latest).days), max(s2, (exp - latest).days))
            don = max(start, exp - dt.timedelta(days=shelf))
        return dict(name=name, cat=cat, unit=unit, qty=random.randint(*qr), exp=exp, don=don)


for k in range(N_CURRENT):                                  # even spread: Nov 20 .. Dec 10
    exp = D0 + dt.timedelta(days=k % ((WIN_END - D0).days + 1))
    items.append(pick_product(exp, HIST_START))
for k in range(N_HIST):                                     # older stock: Oct 6 .. Nov 19
    exp = dt.date(2026, 10, 6) + dt.timedelta(days=random.randint(0, (D0 - dt.date(2026, 10, 6)).days - 1))
    items.append(pick_product(exp, HIST_START))
random.shuffle(items)

donations = []


def group_into_donations(batch):
    """Same-day items become one donation (3 to 9 items) from a donor who gives that kind of food."""
    by_day = defaultdict(list)
    for it in batch:
        by_day[it["don"]].append(it)
    for day in sorted(by_day):
        pool = by_day[day]
        random.shuffle(pool)
        while pool:
            chunk = pool[:random.randint(3, 9)]
            pool = pool[len(chunk):]
            cats = [c["cat"] for c in chunk]
            main = max(set(cats), key=cats.count)
            dn = random.choice([dn for dn in donors if main in dn[5]] or donors)
            did = len(donations) + 1
            hour = random.choice([9, 10, 11, 12]) if day.weekday() in (2, 5) else random.randint(9, 17)
            vol = random.choice(intake_by_day.get(day) or [v[0] for v in vols])
            donations.append((did, dn[0], ts(day, hour, random.choice([0, 15, 30, 45])), vol))
            for it in chunk:
                it["did"] = did
    start = sum(1 for it in items if "id" in it)
    for i, it in enumerate(sorted(batch, key=lambda x: (x["did"], x["name"])), start + 1):
        it["id"] = i
        it["left"] = it["qty"]


group_into_donations(items)

# ---------------- hampers ----------------
dists, dist_items = [], []


def build_hamper(r, day, upcoming):
    """First-expiry-first: take items still in date at pickup, skipping anything the household can't eat."""
    want = min(9, 5 + r["hh"] // 2)
    ok_by = day + dt.timedelta(days=1 if upcoming else 0)          # still good after the pickup day
    donated_before = min(day, D0 + dt.timedelta(days=1))
    pool = [it for it in items if "id" in it and it["don"] < donated_before and it["exp"] >= ok_by and it["left"] > 0
            and not any(b in it["name"] for b in r["banned"])
            and not (r["hh"] < 3 and ("Diapers" in it["name"] or "Formula" in it["name"]))]
    pool.sort(key=lambda it: (it["exp"], random.random()))
    # volunteers mostly reach for food that expires first, but not perfectly (this is where real waste comes from)
    front = pool[:max(25, len(pool) * 1 // 8)]
    random.shuffle(front)
    chosen, cats_used, names_used = [], defaultdict(int), set()
    for it in front + pool[len(front):]:
        if it["name"] in names_used or cats_used[it["cat"]] >= (1 if it["cat"] == 8 else 2):
            continue
        lo, hi = TAKE[it["unit"]]
        take = min(it["left"], random.randint(lo, hi) + (1 if r["hh"] >= 5 and hi > 1 else 0))
        it["left"] -= take
        chosen.append((it["id"], take))
        cats_used[it["cat"]] += 1
        names_used.add(it["name"])
        if len(chosen) >= want:
            break
    return chosen


approved = [r for r in recips if r["status"] == "Approved"]
past_slots = [s for s in dist_shifts if DIST_START <= s[0] < D0]
visits = []
for r in approved:
    k = random.choices([1, 2, 3, 4, 5], [12, 26, 30, 22, 10])[0]
    weeks = sorted(random.sample(range(len(past_slots) // 4), min(k, len(past_slots) // 4)))
    for w in weeks:
        visits.append((random.choice(past_slots[w * 4:w * 4 + 4]), r))
visits.sort(key=lambda v: (v[0][0], v[0][1]))
alerts, emails = [], []
for (day, h1, h2, sid, team), r in visits:
    minute = random.randint(0, (h2 - h1) * 4 - 1) * 15
    when = dt.datetime.combine(day, dt.time(h1)) + dt.timedelta(minutes=minute)
    status = random.choices(["Fulfilled", "Missed", "Delayed"], [88, 8, 4])[0]
    if status == "Delayed" and (D0 - day).days < 10:
        status = "Fulfilled"          # recent late pickups were handed out late, so they show as fulfilled
    did = len(dists) + 1
    dists.append((did, r["id"], f"{when:%Y-%m-%d %H:%M:00}", status, random.choice(team) if team else None, sid))
    if status != "Missed":
        for iid, take in build_hamper(r, day, False):
            dist_items.append((did, iid, take))
    if status != "Fulfilled":
        aid = len(alerts) + 1
        sent = when + dt.timedelta(minutes=30 if status == "Delayed" else 0, hours=0 if status == "Delayed" else 24 - when.hour + 6)
        alerts.append((aid, status, f"{sent:%Y-%m-%d %H:%M:00}", None, did, f"{r['name']} pickup {status.lower()}"))
        for c in coords:
            subj = f"[Food Bank] Pickup {status.lower()}: {r['name']}"
            body = (f"Hi coordinators,\n\nRecipient: {r['name']}\nPhone: {r['phone']}\nScheduled pickup: {when:%Y-%m-%d %H:%M}\n"
                    f"Status: {status}\n\nPlease contact the recipient to reschedule.")
            emails.append((aid, c[1], next(u[1] for u in users if u[0] == c[1]), subj, body, "Template", "Automatic",
                           "Logged only", f"{sent:%Y-%m-%d %H:%M:00}"))

# upcoming scheduled pickups, Nov 21 .. Dec 10 (food is reserved for them now)
future_slots = [s for s in dist_shifts if D0 < s[0] <= WIN_END]
for r in random.sample(approved, 80):
    day, h1, h2, sid, team = random.choice(future_slots)
    when = dt.datetime.combine(day, dt.time(h1)) + dt.timedelta(minutes=random.randint(0, (h2 - h1) * 4 - 1) * 15)
    did = len(dists) + 1
    dists.append((did, r["id"], f"{when:%Y-%m-%d %H:%M:00}", "Scheduled", random.choice(team) if team else None, sid))
    for iid, take in build_hamper(r, day, True):
        dist_items.append((did, iid, take))

# ---------------- top up: recent donations so every expiry day has about the same stock ----------------
left_by_day = defaultdict(int)
for it in items:
    if it["exp"] >= D0 and it["left"] > 0:
        left_by_day[it["exp"]] += 1
target = round(N_CURRENT / ((WIN_END - D0).days + 1))
extra = []
for k in range((WIN_END - D0).days + 1):
    day = D0 + dt.timedelta(days=k)
    for _ in range(max(0, target - left_by_day[day])):
        extra.append(pick_product(day, D0 - dt.timedelta(days=12)))
items.extend(extra)
group_into_donations(extra)

# ---------------- what is left: current stock, given out, or wasted ----------------
expiry = []
for it in items:
    if it["exp"] < D0:
        if it["left"] > 0:
            it["status"] = "Expired"
            expiry.append((it["id"], it["left"], f"{it['exp']:%Y-%m-%d}", it["cat"], ts(it["exp"] + dt.timedelta(days=1), 6)))
        else:
            it["status"] = "Distributed"
    else:
        it["status"] = "Available" if it["left"] > 0 else "Distributed"

# ---------------- write SQL ----------------
bulk("Category", ["Category_ID", "Name"], [(i, c) for i, c in enumerate(CATS, 1)])
bulk("User_Account", ["User_ID", "Email", "Password_Hash", "Role", "Created_At"], users)
bulk("Coordinator", ["Coordinator_ID", "User_ID", "Name", "Phone"], coords)
bulk("Volunteer", ["Volunteer_ID", "User_ID", "Name", "Phone", "Picture", "Availability", "Created_By"], [v[:7] for v in vols])
bulk("Volunteer_Availability", ["Volunteer_ID", "Day_Of_Week", "Start_Time", "End_Time"],
     [(v[0], dd, a, b) for v in vols for dd, a, b in v[7]])
bulk("Donor", ["Donor_ID", "User_ID", "Name", "Donor_Type", "Phone"], [dn[:5] for dn in donors])
bulk("Recipient", ["Recipient_ID", "User_ID", "Name", "Household_Size", "Phone", "Food_Preferences", "Emergency_Contact",
                   "Approval_Status", "Approved_By"],
     [(r["id"], r["user"], r["name"], r["hh"], r["phone"], r["diet"], r["ec"], r["status"], r["by"]) for r in recips])
bulk("Donation", ["Donation_ID", "Donor_ID", "Date_Time", "Collected_By_Volunteer_ID"], donations)
bulk("Inventory_Item", ["Item_ID", "Name", "Category_ID", "Quantity", "Original_Quantity", "Unit", "Expiration_Date", "Donation_ID", "Status"],
     [(it["id"], it["name"], it["cat"], it["left"] if it["status"] != "Distributed" else 0, it["qty"], it["unit"],
       f"{it['exp']:%Y-%m-%d}", it["did"], it["status"]) for it in sorted(items, key=lambda x: x["id"])])
bulk("Shift", ["Shift_ID", "Start_Time", "End_Time", "Task", "Coordinator_ID"], shifts)
bulk("Shift_Assignment", ["Shift_ID", "Volunteer_ID"], assign)
bulk("Distribution", ["Distribution_ID", "Recipient_ID", "Pickup_Date_Time", "Status", "Given_By_Volunteer_ID", "Shift_ID"], dists)
bulk("Distribution_Item", ["Distribution_ID", "Item_ID", "Quantity"], dist_items, 400)
bulk("Expiry_Record", ["Item_ID", "Quantity", "Expired_On", "Category_ID", "Recorded_At"], expiry)
bulk("Alert", ["Alert_ID", "Type", "Date_Time", "Item_ID", "Distribution_ID", "Message"], alerts)
bulk("Email_Log", ["Alert_ID", "To_User_ID", "To_Email", "Subject", "Body", "Written_By", "Run_Mode", "Status", "Sent_At"], emails)
o.append("SET FOREIGN_KEY_CHECKS=1;")

open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_data.sql"), "w", encoding="utf-8").write("\n".join(o) + "\n")
cur = [it for it in items if it["exp"] >= D0]
print(f"Wrote seed_data.sql: {len(items)} inventory records ({len(cur)} current, expiring {D0} to {WIN_END}; "
      f"{sum(1 for it in cur if it['status'] == 'Available')} still in stock), {len(donations)} donations, "
      f"{len(approved)} approved recipients (+{len(recips) - len(approved)} pending), {len(dists)} hampers "
      f"({sum(1 for x in dists if x[3] == 'Scheduled')} upcoming), {len(dist_items)} hamper item lines, "
      f"{len(expiry)} wasted items, {len(shifts)} shifts, {len(vols)} volunteers, {len(donors)} donors")
