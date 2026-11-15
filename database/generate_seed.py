"""
Rebuilds database/seed_data.sql (only needed if you want to change the test data).

    python database/generate_seed.py

Every date in the output is RELATIVE to the day the file is loaded (CURDATE() + n days),
so the test data never goes stale: there are always some expired items, some expiring soon,
past hampers and an upcoming pickup, whenever you run setup_db.py.
"""
import os, random
random.seed(2413)
H = "SET_BY_SETUP_DB"      # setup_db.py replaces this with a real password hash


def q(v): return "NULL" if v is None else ("'" + str(v).replace("'", "''") + "'")
def D(n): return f"CURDATE() + INTERVAL {n} DAY"                       # date n days from load day
def DT(n, h, m=0): return f"TIMESTAMP(CURDATE() + INTERVAL {n} DAY, '{h:02d}:{m:02d}:00')"
def WK(k, h): return f"TIMESTAMP(CURDATE() - INTERVAL WEEKDAY(CURDATE()) DAY + INTERVAL {k} DAY, '{h:02d}:00:00')"  # k days from this week's Monday


o = ["USE foodbank;"]
uid = [0]
def user(email, role):
    uid[0] += 1
    o.append(f"INSERT INTO User_Account (Email,Password_Hash,Role) VALUES ({q(email)},{q(H)},'{role}');")
    return uid[0]


cats = ["Canned Goods", "Dairy & Eggs", "Fresh Produce", "Bakery", "Dry Goods & Grains", "Protein", "Baby & Hygiene"]
o.append("INSERT INTO Category (Name) VALUES " + ",".join(f"({q(c)})" for c in cats) + ";")

# (name, category, unit, quantity range, days until expiry range)
F = [("Campbell's Tomato Soup 284 mL", 1, "can", (12, 48), (7, 14)), ("Black Beans 540 mL", 1, "can", (12, 36), (7, 14)),
     ("Chickpeas 540 mL", 1, "can", (12, 24), (7, 14)), ("Flaked Light Tuna 170 g", 1, "can", (12, 48), (7, 14)),
     ("Whole Kernel Corn 341 mL", 1, "can", (12, 24), (7, 14)), ("Diced Tomatoes 796 mL", 1, "can", (6, 24), (7, 14)),
     ("2% Milk 4 L", 2, "jug", (2, 10), (-3, 10)), ("Large Eggs", 2, "dozen", (3, 15), (-2, 14)),
     ("Plain Greek Yogurt 750 g", 2, "tub", (4, 12), (-3, 12)), ("Medium Cheddar 400 g", 2, "block", (3, 10), (0, 14)),
     ("Salted Butter 454 g", 2, "block", (2, 8), (3, 14)),
     ("Gala Apples", 3, "kg", (5, 25), (-2, 14)), ("Bananas", 3, "kg", (4, 20), (-4, 6)), ("Carrots", 3, "kg", (5, 20), (0, 14)),
     ("Russet Potatoes", 3, "kg", (10, 40), (3, 14)), ("Yellow Onions", 3, "kg", (5, 20), (3, 14)),
     ("Baby Spinach 312 g", 3, "bag", (4, 12), (-4, 5)), ("Roma Tomatoes", 3, "kg", (3, 12), (-3, 7)),
     ("Whole Wheat Bread", 4, "loaf", (5, 20), (-3, 6)), ("White Sandwich Bread", 4, "loaf", (5, 20), (-3, 6)),
     ("Plain Bagels 6-pack", 4, "pack", (3, 12), (-2, 6)), ("Flour Tortillas 10-pack", 4, "pack", (3, 10), (0, 14)),
     ("Dinner Rolls 12-pack", 4, "pack", (3, 10), (-2, 5)),
     ("Long Grain White Rice 2 kg", 5, "bag", (4, 15), (10, 14)), ("Basmati Rice 4 kg", 5, "bag", (2, 8), (10, 14)),
     ("Spaghetti 900 g", 5, "box", (6, 24), (10, 14)), ("Large Flake Oats 1 kg", 5, "bag", (4, 12), (10, 14)),
     ("Red Lentils 900 g", 5, "bag", (4, 12), (10, 14)), ("Atta Flour 10 kg", 5, "bag", (1, 4), (10, 14)),
     ("Peanut Butter 1 kg", 6, "jar", (4, 12), (10, 14)), ("Frozen Chicken Thighs", 6, "kg", (3, 10), (2, 14)),
     ("Ground Beef", 6, "kg", (2, 8), (-2, 4)), ("Firm Tofu 454 g", 6, "block", (4, 12), (-2, 10)),
     ("Diapers Size 4", 7, "pack", (2, 6), (14, 14)), ("Baby Formula 900 g", 7, "can", (2, 6), (10, 14)),
     ("Toothpaste 100 mL", 7, "tube", (6, 20), (14, 14)), ("Bar Soap 4-pack", 7, "pack", (4, 12), (14, 14))]

# coordinators: Harsh and AJ only (they receive every AI alert email)
for n, e, ph in [("Harsh", "harsh.rana1@student.kpu.ca", "604-555-0142"), ("AJ", "ajit.thapa@student.kpu.ca", "604-555-0177")]:
    o.append(f"INSERT INTO Coordinator (User_ID,Name,Phone) VALUES ({user(e, 'Coordinator')},{q(n)},{q(ph)});")

# volunteers: the rest of the team, with availability
avail = {"Jackson": [("Tue", "09:00", "13:00"), ("Fri", "09:00", "17:00")],
         "Pranab": [("Mon", "09:00", "13:00"), ("Wed", "09:00", "13:00"), ("Sun", "09:00", "14:00")],
         "Aman": [("Thu", "10:00", "18:00"), ("Sat", "09:00", "13:00")]}
for i, n in enumerate(avail):
    u = user(f"{n.lower()}@surreyfoodbank.test", "Volunteer")
    o.append(f"INSERT INTO Volunteer (User_ID,Name,Phone,Picture,Availability,Created_By) VALUES ({u},{q(n)},'778-555-01{20+i}',"
             f"'images/volunteers/{n.lower()}.jpg',{q(', '.join(f'{d} {a}-{b}' for d, a, b in avail[n]))},1);")
    for d, a, b in avail[n]:
        o.append(f"INSERT INTO Volunteer_Availability (Volunteer_ID,Day_Of_Week,Start_Time,End_Time) VALUES ({i+1},'{d}','{a}','{b}');")

donors = [("Guildford Fresh Market", "Business"), ("Fraser Valley Bakery Co.", "Business"), ("Newton Community Church", "Organization"),
          ("Sunrise Dairy Farms", "Business"), ("Patel Family Grocers", "Business"), ("KPU Student Union Food Drive", "Organization"),
          ("Margaret Thompson", "Individual"), ("Gurinder Sidhu", "Individual"), ("Daniel Kim", "Individual"), ("Olivia Martin", "Individual")]
for i, (n, t) in enumerate(donors):
    e = n.lower().replace(" ", ".").replace("'", "").replace(".co.", "").strip(".") + "@donor.test"
    o.append(f"INSERT INTO Donor (User_ID,Name,Donor_Type,Phone) VALUES ({user(e, 'Donor')},{q(n)},'{t}','604-555-{2100+i*13}');")
pref = {1: [3], 2: [4], 3: [1, 5, 7], 4: [2], 5: [3, 5, 1], 6: [1, 5, 6], 7: [1, 5], 8: [5, 1], 9: [1, 6], 10: [7, 1]}   # what each donor gives

recips = [("Maria Gonzalez", 4, "None", "Carlos Gonzalez 604-555-3311"), ("Jaspreet Kaur", 5, "Vegetarian, no eggs", "Harjit Singh 778-555-3402"),
          ("Ahmed Hassan", 3, "Halal only", "Fatima Hassan 604-555-3519"), ("Emily Chen", 1, "Lactose intolerant", "Grace Chen 778-555-3620"),
          ("Robert Wilson", 2, "Peanut allergy", "Susan Wilson 604-555-3788")]
for i, (n, h, p, e) in enumerate(recips):
    u = user(n.lower().replace(" ", ".") + "@recipient.test", "Recipient")
    o.append(f"INSERT INTO Recipient (User_ID,Name,Household_Size,Phone,Food_Preferences,Emergency_Contact,Approval_Status,Approved_By) "
             f"VALUES ({u},{q(n)},{h},'778-555-{4100+i*7}',{q(p)},{q(e)},'Approved',{1 + i % 2});")
u = user("tom.baker@recipient.test", "Recipient")
o.append(f"INSERT INTO Recipient (User_ID,Name,Household_Size,Phone,Food_Preferences,Emergency_Contact,Approval_Status) "
         f"VALUES ({u},'Tom Baker',2,'604-555-4199','None','Ann Baker 604-555-4200','Pending');")

# 24 donations over the last 3 weeks = 200 inventory items (about 10% already expired, waiting for the AI check)
item, don, items = 0, 0, []
for d in range(24):
    don += 1; donor = random.randint(1, 10)
    o.append(f"INSERT INTO Donation (Donor_ID,Date_Time,Collected_By_Volunteer_ID) VALUES ({donor},"
             f"{DT(-random.randint(0, 20), random.randint(9, 18), random.choice([0, 15, 30, 45]))},{random.randint(1, 3)});")
    for _ in range(200 // 24 + (1 if d < 200 % 24 else 0)):
        cat = random.choice(pref[donor])
        name, cc, unit, qr, er = random.choice([f for f in F if f[1] == cat])
        exp = random.randint(*er) if random.random() > 0.1 else random.randint(-5, -1)
        qty = random.randint(*qr); item += 1; items.append([item, qty, exp, name])
        o.append(f"INSERT INTO Inventory_Item (Name,Category_ID,Quantity,Unit,Expiration_Date,Donation_ID) VALUES ({q(name)},{cc},{qty},{q(unit)},{D(exp)},{don});")

# 20 older items that already expired and were removed (the expiry section)
for k in range(20):
    don += 1; back = random.randint(25, 50)
    o.append(f"INSERT INTO Donation (Donor_ID,Date_Time,Collected_By_Volunteer_ID) VALUES ({random.randint(1, 10)},{DT(-back, 11)},{random.randint(1, 3)});")
    name, cc, unit, qr, er = random.choice([f for f in F if f[1] in (2, 3, 4, 6)])
    exp = -back + random.randint(3, 10); qty = random.randint(*qr); item += 1
    o.append(f"INSERT INTO Inventory_Item (Name,Category_ID,Quantity,Unit,Expiration_Date,Donation_ID,Status) VALUES ({q(name)},{cc},0,{q(unit)},{D(exp)},{don},'Expired');")
    o.append(f"INSERT INTO Expiry_Record (Item_ID,Quantity,Expired_On,Category_ID,Recorded_At) VALUES ({item},{qty},{D(exp)},{cc},{DT(exp + 1, 6)});")

# shifts: last 3 weeks + this week + next week, each matched to a volunteer's availability
shift = 0
plan = [(2, 9, 13, "Donation pickup & intake", 2), (3, 13, 17, "Sort and shelve inventory", 3),      # Wed Pranab, Thu Aman
        (4, 13, 17, "Hamper packing", 1), (5, 9, 13, "Hamper distribution desk", 3)]                  # Fri Jackson, Sat Aman
for w in range(-3, 2):
    for dow, h1, h2, task, vol in plan:
        shift += 1
        o.append(f"INSERT INTO Shift (Start_Time,End_Time,Task,Coordinator_ID) VALUES ({WK(w*7+dow, h1)},{WK(w*7+dow, h2)},{q(task)},{1 + shift % 2});")
        o.append(f"INSERT INTO Shift_Assignment VALUES ({shift},{vol});")

# hampers: 5 recipients on different past days, one missed, one upcoming
dist = 0
bad = {2: ["Chicken", "Beef", "Eggs", "Tuna"], 3: ["Beef", "Chicken"], 4: ["Milk", "Yogurt", "Cheddar", "Butter"], 5: ["Peanut"]}
for r, off, st in [(1, -2, "Fulfilled"), (2, -5, "Fulfilled"), (3, -9, "Fulfilled"), (4, -13, "Fulfilled"), (5, -17, "Fulfilled"),
                   (2, -1, "Missed"), (4, 2, "Scheduled")]:
    dist += 1
    o.append(f"INSERT INTO Distribution (Recipient_ID,Pickup_Date_Time,Status,Given_By_Volunteer_ID) VALUES ({r},"
             f"{DT(off, random.choice([13, 14, 15, 16]), random.choice([0, 30]))},'{st}',{random.randint(1, 3)});")
    if st == "Missed":
        continue
    pool = [x for x in items if x[2] >= max(off, 0) + 3 and x[1] > 3 and not any(b in x[3] for b in bad.get(r, []))]
    for it in random.sample(pool, 6):
        take = random.randint(1, 3)
        o.append(f"INSERT INTO Distribution_Item VALUES ({dist},{it[0]},{take});")
        o.append(f"UPDATE Inventory_Item SET Quantity=Quantity-{take} WHERE Item_ID={it[0]};"); it[1] -= take

open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_data.sql"), "w", encoding="utf-8").write("\n".join(o) + "\n")
print(f"Wrote seed_data.sql: {item} items, {don} donations, {shift} shifts, {dist} hampers")
