"""
Role-based API for the Food Bank front end (Flask blueprint, mounted by app.py).

Everything the four roles do lives here: login/logout, registration, profiles, donations & inventory,
distributions (hampers), shifts, recipient approval, account management.
Reports and the AI check keep using the routes already in app.py (now coordinator-only).

Rules enforced here (from the project PDF):
  Donor        - own account, own donation history (search by date + category)
  Recipient    - own account (needs coordinator approval), request a pickup, own history (search by date)
  Volunteer    - inventory intake + distributions (add / edit / delete) for their shifts, mark pickups
  Coordinator  - everything about users, shifts, approvals, categories, reports
"""
import os, re, time, uuid, decimal, functools, threading, datetime as dt
from contextlib import contextmanager
from flask import Blueprint, jsonify, request, session
import mysql.connector
import ai_engine, setup_db

bp = Blueprint("roles", __name__, url_prefix="/api")
HERE = os.path.dirname(os.path.abspath(__file__))
UPLOADS = os.path.join(HERE, "static", "uploads")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+()\-\s.]{7,20}$")
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
ROLE_TABLE = {"Donor": "Donor", "Recipient": "Recipient", "Volunteer": "Volunteer", "Coordinator": "Coordinator"}


# ---------------------------------------------------------------- helpers
class Bad(Exception):
    def __init__(self, msg, code=400, **extra):
        super().__init__(msg)
        self.msg, self.code, self.extra = msg, code, extra


@bp.errorhandler(Bad)
def on_bad(e):
    return jsonify({"ok": False, "error": e.msg, **e.extra}), e.code


@bp.errorhandler(mysql.connector.IntegrityError)
def on_integrity(e):
    msgs = {1062: "That value already exists (for example, the email is already registered).",
            1451: "This record is used by other records, so it cannot be deleted. Disable the account or edit it instead.",
            1452: "One of the selected values (category, donor, recipient or shift) no longer exists."}
    return jsonify({"ok": False, "error": msgs.get(e.errno, f"Database error: {e.msg}")}), 409


def J(v):
    """Make a DB value JSON friendly (dates as plain strings)."""
    if isinstance(v, list):
        return [J(x) for x in v]
    if isinstance(v, dict):
        return {k: J(x) for k, x in v.items()}
    if isinstance(v, decimal.Decimal):
        return float(v) if v % 1 else int(v)
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, dt.date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, dt.timedelta):
        s = int(v.total_seconds())
        return f"{s // 3600:02d}:{s % 3600 // 60:02d}"
    return v


def out(**kw):
    return jsonify(J({"ok": True, **kw}))


@contextmanager
def tx():
    con = ai_engine.connect()
    cur = con.cursor(dictionary=True, buffered=True)
    try:
        yield cur
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def body():
    return request.get_json(silent=True) or {}


def text(b, key, n=255, req=False, label=None):
    v = str(b.get(key) if b.get(key) is not None else "").strip()
    label = label or key.replace("_", " ").capitalize()
    if req and not v:
        raise Bad(f"{label} is required.")
    if len(v) > n:
        raise Bad(f"{label} must be {n} characters or fewer.")
    return v or None


def phone(b, key="phone", req=True):
    v = text(b, key, 20, req, "Phone number")
    if v and not PHONE_RE.match(v):
        raise Bad("Enter a valid phone number, for example 604-555-0123.")
    return v


def email_of(b):
    v = (text(b, "email", 255, True, "Email") or "").lower()
    if not EMAIL_RE.match(v):
        raise Bad("Enter a valid email address.")
    return v


def pw_of(b, key="password"):
    v = str(b.get(key) or "")
    if len(v) < 8:
        raise Bad("Password must be at least 8 characters.")
    return v


def num(v, label="Quantity", zero=False):
    try:
        d = decimal.Decimal(str(v))
    except Exception:
        raise Bad(f"{label} must be a number.")
    if d < 0 or (d == 0 and not zero) or d > 100000:
        raise Bad(f"{label} must be {'0 or more' if zero else 'more than 0'}.")
    return d.quantize(decimal.Decimal("0.01"))


def pdate(v, label="Date"):
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        raise Bad(f"{label} must be a valid date.")


def pdt(v, label="Date and time"):
    try:
        return dt.datetime.fromisoformat(str(v).replace(" ", "T")[:16])
    except ValueError:
        raise Bad(f"{label} must be a valid date and time.")


def api(*roles):
    """Login required; optionally limited to some roles. Also re-checks the account is still active."""
    def deco(f):
        @functools.wraps(f)
        def wrapper(*a, **k):
            if not session.get("uid"):
                raise Bad("Please log in.", 401)
            if roles and session.get("role") not in roles:
                raise Bad("Your role cannot do this.", 403)
            with tx() as cur:
                cur.execute("SELECT Is_Active FROM User_Account WHERE User_ID=%s", (session["uid"],))
                u = cur.fetchone()
            if not u or not u["Is_Active"]:
                session.clear()
                raise Bad("This account is no longer active.", 401)
            return f(*a, **k)
        return wrapper
    return deco


def profile(cur, uid):
    cur.execute("SELECT User_ID, Email, Role, Is_Active, Last_Login FROM User_Account WHERE User_ID=%s", (uid,))
    u = cur.fetchone()
    if not u:
        raise Bad("Account not found.", 404)
    cur.execute(f"SELECT * FROM {ROLE_TABLE[u['Role']]} WHERE User_ID=%s", (uid,))
    return u, (cur.fetchone() or {})


def my_id(cur, role):
    """Donor_ID / Recipient_ID / Volunteer_ID / Coordinator_ID of the logged-in user."""
    cur.execute(f"SELECT {role}_ID id FROM {ROLE_TABLE[role]} WHERE User_ID=%s", (session["uid"],))
    r = cur.fetchone()
    if not r:
        raise Bad("Profile not found.", 404)
    return r["id"]


def today(cur):
    return ai_engine.today(cur)


# ---------------------------------------------------------------- auth
FAILS = {}


def throttled(key):
    now = time.time()
    FAILS[key] = [t for t in FAILS.get(key, []) if now - t < 600]
    return len(FAILS[key]) >= 5


@bp.post("/login")
def login():
    b = body()
    em, pw = str(b.get("email", "")).strip().lower(), str(b.get("password", ""))
    key = (request.remote_addr, em)
    if throttled(key):
        raise Bad("Too many failed attempts. Wait 10 minutes and try again.", 429)
    with tx() as cur:
        cur.execute("SELECT User_ID, Password_Hash, Role, Is_Active FROM User_Account WHERE LOWER(Email)=%s", (em,))
        u = cur.fetchone()
        if not u or not setup_db.check_password(pw, u["Password_Hash"]):
            FAILS.setdefault(key, []).append(time.time())
            raise Bad("Wrong email or password.", 401)
        if not u["Is_Active"]:
            raise Bad("This account is disabled. Ask a coordinator for help.", 403)
        cur.execute("UPDATE User_Account SET Last_Login=NOW() WHERE User_ID=%s", (u["User_ID"],))
    FAILS.pop(key, None)
    session.clear()
    session["uid"], session["role"] = u["User_ID"], u["Role"]
    return out(role=u["Role"])


@bp.post("/logout")
def logout():
    session.clear()
    return out()


@bp.get("/me")
def me():
    if not session.get("uid"):
        return jsonify({"ok": False, "error": "Not logged in."}), 401
    with tx() as cur:
        u, p = profile(cur, session["uid"])
        if not u["Is_Active"]:
            session.clear()
            return jsonify({"ok": False, "error": "Account disabled."}), 401
        cats = []
        cur.execute("SELECT Category_ID id, Name name FROM Category ORDER BY Name")
        cats = cur.fetchall()
    extra = {"approval": p.get("Approval_Status")} if u["Role"] == "Recipient" else {}
    return out(user={"id": u["User_ID"], "email": u["Email"], "role": u["Role"], "name": p.get("Name"),
                     "picture": p.get("Picture"), **extra}, categories=cats)


@bp.post("/register")
def register():
    """Self-registration for donors and recipients. Recipients start as Pending until a coordinator approves."""
    b = body()
    role = b.get("role")
    if role not in ("Donor", "Recipient"):
        raise Bad("Choose whether you are a donor or a recipient.")
    em, name, ph = email_of(b), text(b, "name", 100, True, "Name"), phone(b)
    with tx() as cur:
        cur.execute("INSERT INTO User_Account (Email,Password_Hash,Role) VALUES (%s,%s,%s)",
                    (em, setup_db.hash_password(pw_of(b)), role))
        uid = cur.lastrowid
        if role == "Donor":
            dtype = b.get("donor_type") or "Individual"
            if dtype not in ("Individual", "Business", "Organization"):
                raise Bad("Pick a donor type.")
            cur.execute("INSERT INTO Donor (User_ID,Name,Donor_Type,Phone) VALUES (%s,%s,%s,%s)", (uid, name, dtype, ph))
        else:
            try:
                hh = int(b.get("household_size"))
                assert 1 <= hh <= 30
            except (TypeError, ValueError, AssertionError):
                raise Bad("Household size must be a whole number from 1 to 30.")
            cur.execute("""INSERT INTO Recipient (User_ID,Name,Household_Size,Phone,Food_Preferences,Emergency_Contact)
                           VALUES (%s,%s,%s,%s,%s,%s)""",
                        (uid, name, hh, ph, text(b, "dietary", 1000, True, "Dietary restrictions or allergies (write None if there are none)"),
                         text(b, "emergency_contact", 150, True, "Emergency contact")))
    return out(msg="Account created. " + ("A coordinator must approve it before you can request a hamper." if role == "Recipient" else "You can log in now."))


# ---------------------------------------------------------------- profile / accounts
def save_slots(cur, vid, slots):
    clean = []
    for s in slots or []:
        d = s.get("day")
        if d not in DAYS:
            raise Bad("Availability day must be Mon to Sun.")
        a, z = str(s.get("start", ""))[:5], str(s.get("end", ""))[:5]
        if not (re.match(r"^\d\d:\d\d$", a) and re.match(r"^\d\d:\d\d$", z)) or a >= z:
            raise Bad("Each availability slot needs a start time before its end time.")
        clean.append((d, a, z))
    cur.execute("DELETE FROM Volunteer_Availability WHERE Volunteer_ID=%s", (vid,))
    for d, a, z in clean:
        cur.execute("INSERT INTO Volunteer_Availability (Volunteer_ID,Day_Of_Week,Start_Time,End_Time) VALUES (%s,%s,%s,%s)", (vid, d, a, z))
    summary = ", ".join(f"{d} {a}-{z}" for d, a, z in sorted(clean, key=lambda x: (DAYS.index(x[0]), x[1])))
    cur.execute("UPDATE Volunteer SET Availability=%s WHERE Volunteer_ID=%s", (summary or "Not set", vid))


def get_slots(cur, vid):
    cur.execute("""SELECT Day_Of_Week day, Start_Time start, End_Time end FROM Volunteer_Availability
                   WHERE Volunteer_ID=%s ORDER BY FIELD(Day_Of_Week,'Mon','Tue','Wed','Thu','Fri','Sat','Sun'), Start_Time""", (vid,))
    return cur.fetchall()


def update_account(cur, uid, b, admin):
    """One place that edits an account. Coordinators (admin) may edit anyone; everybody may edit themselves."""
    u, p = profile(cur, uid)
    role = u["Role"]
    if "email" in b:
        em = email_of(b)
        if em != u["Email"]:
            cur.execute("UPDATE User_Account SET Email=%s WHERE User_ID=%s", (em, uid))
    if b.get("new_password"):
        if not admin:
            cur.execute("SELECT Password_Hash FROM User_Account WHERE User_ID=%s", (uid,))
            pw_row = cur.fetchone()
            if not pw_row or not setup_db.check_password(str(b.get("current_password", "")), pw_row["Password_Hash"]):
                raise Bad("Your current password is not correct.")
        cur.execute("UPDATE User_Account SET Password_Hash=%s WHERE User_ID=%s", (setup_db.hash_password(pw_of(b, "new_password")), uid))
    if admin and "is_active" in b:
        if uid == session["uid"] and not b["is_active"]:
            raise Bad("You cannot disable your own account.")
        cur.execute("UPDATE User_Account SET Is_Active=%s WHERE User_ID=%s", (1 if b["is_active"] else 0, uid))
    table = ROLE_TABLE[role]
    sets, vals = [], []
    if "name" in b:
        sets.append("Name=%s"); vals.append(text(b, "name", 100, True, "Name"))
    if "phone" in b:
        sets.append("Phone=%s"); vals.append(phone(b))
    if role == "Donor" and "donor_type" in b:
        if b["donor_type"] not in ("Individual", "Business", "Organization"):
            raise Bad("Pick a donor type.")
        sets.append("Donor_Type=%s"); vals.append(b["donor_type"])
    if role == "Recipient":
        if "household_size" in b:
            try:
                hh = int(b["household_size"]); assert 1 <= hh <= 30
            except (TypeError, ValueError, AssertionError):
                raise Bad("Household size must be a whole number from 1 to 30.")
            sets.append("Household_Size=%s"); vals.append(hh)
        if "dietary" in b:
            sets.append("Food_Preferences=%s"); vals.append(text(b, "dietary", 1000, True, "Dietary restrictions"))
        if "emergency_contact" in b:
            sets.append("Emergency_Contact=%s"); vals.append(text(b, "emergency_contact", 150, True, "Emergency contact"))
    if sets:
        cur.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE User_ID=%s", (*vals, uid))
    if role == "Volunteer" and "slots" in b:
        save_slots(cur, p["Volunteer_ID"], b["slots"])


def save_picture(cur, uid):
    f = request.files.get("picture")
    if not f or not f.filename:
        raise Bad("Choose an image file first.")
    head = f.stream.read(12); f.stream.seek(0)
    ext = (".jpg" if head[:3] == b"\xff\xd8\xff" else ".png" if head[:4] == b"\x89PNG"
           else ".webp" if head[:4] == b"RIFF" and head[8:12] == b"WEBP" else None)
    if not ext:
        raise Bad("The picture must be a JPG, PNG or WebP image.")
    os.makedirs(UPLOADS, exist_ok=True)
    name = uuid.uuid4().hex + ext
    f.save(os.path.join(UPLOADS, name))
    cur.execute("UPDATE Volunteer SET Picture=%s WHERE User_ID=%s", ("uploads/" + name, uid))
    return "uploads/" + name


@bp.get("/profile")
@api()
def get_profile():
    with tx() as cur:
        u, p = profile(cur, session["uid"])
        slots = get_slots(cur, p["Volunteer_ID"]) if u["Role"] == "Volunteer" else None
    return out(account={"email": u["Email"], "role": u["Role"]}, profile=p, slots=slots)


@bp.put("/profile")
@api()
def put_profile():
    b = body()
    b.pop("is_active", None)
    with tx() as cur:
        update_account(cur, session["uid"], b, admin=False)
    return out(msg="Your changes are saved.")


@bp.post("/profile/picture")
@api("Volunteer")
def put_picture():
    with tx() as cur:
        path = save_picture(cur, session["uid"])
    return out(picture=path, msg="Profile picture updated.")


@bp.get("/categories")
@api()
def categories():
    with tx() as cur:
        cur.execute("""SELECT c.Category_ID id, c.Name name, COUNT(i.Item_ID) items FROM Category c
                       LEFT JOIN Inventory_Item i ON i.Category_ID=c.Category_ID GROUP BY c.Category_ID ORDER BY c.Name""")
        return out(categories=cur.fetchall())


@bp.post("/categories")
@api("Coordinator")
def add_category():
    name = text(body(), "name", 50, True, "Category name")
    with tx() as cur:
        cur.execute("INSERT INTO Category (Name) VALUES (%s)", (name,))
    return out(msg=f"Category {name} added.")


@bp.put("/categories/<int:cid>")
@api("Coordinator")
def edit_category(cid):
    name = text(body(), "name", 50, True, "Category name")
    with tx() as cur:
        cur.execute("UPDATE Category SET Name=%s WHERE Category_ID=%s", (name, cid))
    return out(msg="Category renamed.")


@bp.delete("/categories/<int:cid>")
@api("Coordinator")
def del_category(cid):
    with tx() as cur:
        cur.execute("SELECT COUNT(*) n FROM Inventory_Item WHERE Category_ID=%s", (cid,))
        if cur.fetchone()["n"]:
            raise Bad("This category has inventory items, so it cannot be deleted. Rename it instead.", 409)
        cur.execute("DELETE FROM Category WHERE Category_ID=%s", (cid,))
    return out(msg="Category deleted.")


# ---------------------------------------------------------------- coordinator: accounts + approvals
@bp.get("/accounts")
@api("Coordinator")
def accounts():
    q, role = (request.args.get("q") or "").strip(), request.args.get("role") or ""
    where, p = ["1=1"], []
    if q:
        where.append("(u.Email LIKE %s OR COALESCE(co.Name,v.Name,dn.Name,r.Name) LIKE %s)"); p += [f"%{q}%"] * 2
    if role in ROLE_TABLE:
        where.append("u.Role=%s"); p.append(role)
    with tx() as cur:
        cur.execute(f"""SELECT u.User_ID id, u.Email email, u.Role role, u.Is_Active active, u.Last_Login last_login,
                COALESCE(co.Name,v.Name,dn.Name,r.Name) name, COALESCE(co.Phone,v.Phone,dn.Phone,r.Phone) phone,
                r.Approval_Status approval, v.Picture picture
                FROM User_Account u LEFT JOIN Coordinator co ON co.User_ID=u.User_ID LEFT JOIN Volunteer v ON v.User_ID=u.User_ID
                LEFT JOIN Donor dn ON dn.User_ID=u.User_ID LEFT JOIN Recipient r ON r.User_ID=u.User_ID
                WHERE {' AND '.join(where)} ORDER BY FIELD(u.Role,'Coordinator','Volunteer','Donor','Recipient'), name""", p)
        return out(accounts=cur.fetchall())


@bp.get("/accounts/<int:uid>")
@api("Coordinator")
def account_detail(uid):
    with tx() as cur:
        u, p = profile(cur, uid)
        slots = get_slots(cur, p["Volunteer_ID"]) if u["Role"] == "Volunteer" else None
    return out(account={"id": uid, "email": u["Email"], "role": u["Role"], "active": bool(u["Is_Active"])}, profile=p, slots=slots)


@bp.post("/accounts/volunteer")
@api("Coordinator")
def create_volunteer():
    b = body()
    em, name, ph = email_of(b), text(b, "name", 100, True, "Name"), phone(b)
    with tx() as cur:
        cid = my_id(cur, "Coordinator")
        cur.execute("INSERT INTO User_Account (Email,Password_Hash,Role) VALUES (%s,%s,'Volunteer')", (em, setup_db.hash_password(pw_of(b))))
        uid = cur.lastrowid
        cur.execute("INSERT INTO Volunteer (User_ID,Name,Phone,Availability,Created_By) VALUES (%s,%s,%s,'Not set',%s)", (uid, name, ph, cid))
        save_slots(cur, cur.lastrowid, b.get("slots"))
    return out(msg=f"Volunteer account created for {name}.", user_id=uid)


@bp.put("/accounts/<int:uid>")
@api("Coordinator")
def edit_account(uid):
    with tx() as cur:
        update_account(cur, uid, body(), admin=True)
    return out(msg="Account updated.")


@bp.post("/accounts/<int:uid>/picture")
@api("Coordinator")
def account_picture(uid):
    with tx() as cur:
        path = save_picture(cur, uid)
    return out(picture=path, msg="Profile picture updated.")


@bp.delete("/accounts/<int:uid>")
@api("Coordinator")
def delete_account(uid):
    if uid == session["uid"]:
        raise Bad("You cannot delete your own account.")
    with tx() as cur:
        profile(cur, uid)
        cur.execute("DELETE FROM User_Account WHERE User_ID=%s", (uid,))
    return out(msg="Account deleted.")


@bp.get("/coordinator/recipients")
@api("Coordinator")
def recipients():
    st, q = request.args.get("status") or "", (request.args.get("q") or "").strip()
    where, p = ["1=1"], []
    if st in ("Pending", "Approved", "Rejected"):
        where.append("r.Approval_Status=%s"); p.append(st)
    if q:
        where.append("r.Name LIKE %s"); p.append(f"%{q}%")
    with tx() as cur:
        cur.execute(f"""SELECT r.Recipient_ID id, r.Name name, r.Household_Size household, r.Phone phone, u.Email email,
                r.Food_Preferences dietary, r.Emergency_Contact emergency, r.Approval_Status status, co.Name approved_by,
                u.Created_At registered FROM Recipient r JOIN User_Account u USING(User_ID)
                LEFT JOIN Coordinator co ON co.Coordinator_ID=r.Approved_By WHERE {' AND '.join(where)}
                ORDER BY FIELD(r.Approval_Status,'Pending','Approved','Rejected'), u.Created_At DESC""", p)
        return out(recipients=cur.fetchall())


@bp.post("/coordinator/recipients/<int:rid>/decision")
@api("Coordinator")
def decide(rid):
    d = body().get("decision")
    if d not in ("Approved", "Rejected"):
        raise Bad("Decision must be Approved or Rejected.")
    with tx() as cur:
        cid = my_id(cur, "Coordinator")
        cur.execute("UPDATE Recipient SET Approval_Status=%s, Approved_By=%s WHERE Recipient_ID=%s", (d, cid, rid))
        if not cur.rowcount:
            raise Bad("Recipient not found.", 404)
    return out(msg=f"Registration {d.lower()}.")


# ---------------------------------------------------------------- donations + inventory
def donation_rows(cur, donor_id=None):
    a = request.args
    where, p = ["1=1"], []
    if donor_id:
        where.append("d.Donor_ID=%s"); p.append(donor_id)
    elif a.get("donor"):
        where.append("dn.Name LIKE %s"); p.append(f"%{a['donor'].strip()}%")
    if a.get("from"):
        where.append("DATE(d.Date_Time)>=%s"); p.append(pdate(a["from"], "From date"))
    if a.get("to"):
        where.append("DATE(d.Date_Time)<=%s"); p.append(pdate(a["to"], "To date"))
    if a.get("category_id"):
        where.append("i.Category_ID=%s"); p.append(int(a["category_id"]))
    cur.execute(f"""SELECT d.Donation_ID id, d.Date_Time date, dn.Name donor, v.Name collected_by, d.Notes notes,
            i.Item_ID item_id, i.Name item, c.Name category, i.Original_Quantity qty, i.Unit unit,
            i.Expiration_Date expires, i.Status status
            FROM Donation d JOIN Donor dn ON dn.Donor_ID=d.Donor_ID
            LEFT JOIN Volunteer v ON v.Volunteer_ID=d.Collected_By_Volunteer_ID
            JOIN Inventory_Item i ON i.Donation_ID=d.Donation_ID JOIN Category c ON c.Category_ID=i.Category_ID
            WHERE {' AND '.join(where)} ORDER BY d.Date_Time DESC, d.Donation_ID DESC, i.Name LIMIT 600""", p)
    groups = {}
    for r in cur.fetchall():
        g = groups.setdefault(r["id"], {"id": r["id"], "date": r["date"], "donor": r["donor"], "collected_by": r["collected_by"],
                                        "notes": r["notes"], "items": []})
        g["items"].append({k: r[k] for k in ("item_id", "item", "category", "qty", "unit", "expires", "status")})
    return list(groups.values())


@bp.get("/donor/donations")
@api("Donor")
def donor_donations():
    with tx() as cur:
        return out(donations=donation_rows(cur, my_id(cur, "Donor")))


@bp.get("/donations")
@api("Volunteer", "Coordinator")
def all_donations():
    with tx() as cur:
        return out(donations=donation_rows(cur))


@bp.get("/donors")
@api("Volunteer", "Coordinator")
def donors():
    with tx() as cur:
        cur.execute("SELECT Donor_ID id, Name name, Donor_Type type FROM Donor ORDER BY Name")
        return out(donors=cur.fetchall())


@bp.post("/donations")
@api("Volunteer")
def add_donation():
    """Volunteer records a drop-off: one donation with one or more inventory items."""
    b = body()
    items = b.get("items") or []
    if not items:
        raise Bad("Add at least one item to the donation.")
    with tx() as cur:
        vid, day = my_id(cur, "Volunteer"), today(cur)
        try:
            donor = int(b.get("donor_id"))
        except (TypeError, ValueError):
            raise Bad("Choose the donor.")
        cur.execute("INSERT INTO Donation (Donor_ID,Collected_By_Volunteer_ID,Notes,Date_Time) VALUES (%s,%s,%s,%s)",
                    (donor, vid, text(b, "notes", 255), ai_engine.now(cur)))
        did = cur.lastrowid
        for n, it in enumerate(items, 1):
            q, exp = num(it.get("quantity"), f"Item {n} quantity"), pdate(it.get("expiration_date"), f"Item {n} expiry date")
            if exp < day:
                raise Bad(f"Item {n} is already past its expiry date.")
            cur.execute("""INSERT INTO Inventory_Item (Name,Category_ID,Quantity,Original_Quantity,Unit,Expiration_Date,Donation_ID)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                        (text(it, "name", 100, True, f"Item {n} name"), int(it.get("category_id") or 0), q, q,
                         text(it, "unit", 20, True, f"Item {n} unit"), exp, did))
    return out(msg=f"Donation saved with {len(items)} item line(s).", donation_id=did)


@bp.get("/donations/<int:did>")
@api("Volunteer", "Coordinator")
def get_donation(did):
    """Retrieve single donation with its items."""
    with tx() as cur:
        cur.execute("""SELECT d.Donation_ID id, d.Donor_ID donor_id, d.Date_Time date, d.Notes notes,
                              dn.Name donor_name, v.Name collected_by
                       FROM Donation d JOIN Donor dn ON dn.Donor_ID=d.Donor_ID
                       LEFT JOIN Volunteer v ON v.Volunteer_ID=d.Collected_By_Volunteer_ID
                       WHERE d.Donation_ID=%s""", (did,))
        don = cur.fetchone()
        if not don:
            raise Bad("Donation not found.", 404)
        cur.execute("""SELECT Item_ID item_id, Name name, Category_ID category_id, Quantity quantity,
                              Original_Quantity original_quantity, Unit unit, Expiration_Date expiration_date, Status status
                       FROM Inventory_Item WHERE Donation_ID=%s ORDER BY Item_ID""", (did,))
        don["items"] = cur.fetchall()
        return out(donation=don)


@bp.put("/donations/<int:did>")
@api("Volunteer", "Coordinator")
def update_donation(did):
    """Update donation data (satisfies SRS / SDD updateDonationData requirement)."""
    b = body()
    with tx() as cur:
        cur.execute("SELECT * FROM Donation WHERE Donation_ID=%s", (did,))
        don = cur.fetchone()
        if not don:
            raise Bad("Donation not found.", 404)
        if b.get("donor_id"):
            try:
                donor_id = int(b["donor_id"])
            except (TypeError, ValueError):
                raise Bad("Invalid donor ID.")
            cur.execute("UPDATE Donation SET Donor_ID=%s WHERE Donation_ID=%s", (donor_id, did))
        if "notes" in b:
            cur.execute("UPDATE Donation SET Notes=%s WHERE Donation_ID=%s", (text(b, "notes", 255), did))
        if b.get("date_time"):
            cur.execute("UPDATE Donation SET Date_Time=%s WHERE Donation_ID=%s", (pdt(b["date_time"], "Donation date and time"), did))
        if "items" in b and isinstance(b["items"], list) and b["items"]:
            # Check if any inventory item from this donation is already in a distribution
            cur.execute("""SELECT i.Item_ID, i.Name FROM Inventory_Item i
                           JOIN Distribution_Item di ON di.Item_ID=i.Item_ID
                           WHERE i.Donation_ID=%s LIMIT 1""", (did,))
            in_use = cur.fetchone()
            if in_use:
                raise Bad(f"Cannot replace items: '{in_use['Name']}' is already allocated to hamper distributions.", 409)
            cur.execute("DELETE FROM Inventory_Item WHERE Donation_ID=%s", (did,))
            day = today(cur)
            for n, it in enumerate(b["items"], 1):
                q = num(it.get("quantity"), f"Item {n} quantity")
                exp = pdate(it.get("expiration_date"), f"Item {n} expiry date")
                if exp < day:
                    raise Bad(f"Item {n} is already past its expiry date.")
                cur.execute("""INSERT INTO Inventory_Item (Name,Category_ID,Quantity,Original_Quantity,Unit,Expiration_Date,Donation_ID)
                               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                            (text(it, "name", 100, True, f"Item {n} name"), int(it.get("category_id") or 0), q, q,
                             text(it, "unit", 20, True, f"Item {n} unit"), exp, did))
    return out(msg="Donation data updated successfully.")


@bp.get("/inventory")
@api("Volunteer", "Coordinator")
def inventory():
    a = request.args
    where, p = [], []
    st = a.get("status", "available")
    if st == "available":
        where.append("i.Status='Available' AND i.Quantity>0")
    elif st == "expired":
        where.append("i.Status='Expired'")
    if a.get("q"):
        where.append("i.Name LIKE %s"); p.append(f"%{a['q'].strip()}%")
    if a.get("category_id"):
        where.append("i.Category_ID=%s"); p.append(int(a["category_id"]))
    if a.get("expires_before"):
        where.append("i.Expiration_Date<=%s"); p.append(pdate(a["expires_before"], "Expiry date"))
    if a.get("qty_min"):
        where.append("i.Quantity>=%s"); p.append(num(a["qty_min"], "Minimum quantity", True))
    if a.get("qty_max"):
        where.append("i.Quantity<=%s"); p.append(num(a["qty_max"], "Maximum quantity", True))
    with tx() as cur:
        day = today(cur)
        cur.execute(f"""SELECT i.Item_ID id, i.Name name, i.Category_ID category_id, c.Name category, i.Quantity qty,
                i.Original_Quantity original, i.Unit unit, i.Expiration_Date expires, i.Status status, i.Risk_Level risk,
                dn.Name donor, i.Donation_ID donation_id FROM Inventory_Item i JOIN Category c ON c.Category_ID=i.Category_ID
                JOIN Donation d ON d.Donation_ID=i.Donation_ID JOIN Donor dn ON dn.Donor_ID=d.Donor_ID
                {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY i.Expiration_Date, i.Name LIMIT 600""", p)
        rows = cur.fetchall()
        for r in rows:
            r["days_left"] = (r["expires"] - day).days
    return out(items=rows, today=day)


@bp.put("/inventory/<int:iid>")
@api("Volunteer")
def edit_item(iid):
    b = body()
    with tx() as cur:
        cur.execute("SELECT Status FROM Inventory_Item WHERE Item_ID=%s", (iid,))
        r = cur.fetchone()
        if not r:
            raise Bad("Item not found.", 404)
        if r["Status"] == "Expired":
            raise Bad("Expired items are locked because they feed the Inventory Waste report.", 409)
        cur.execute("""UPDATE Inventory_Item SET Name=%s, Category_ID=%s, Quantity=%s, Unit=%s, Expiration_Date=%s, Risk_Level='OK'
                       WHERE Item_ID=%s""",
                    (text(b, "name", 100, True, "Item name"), int(b.get("category_id") or 0), num(b.get("quantity"), zero=True),
                     text(b, "unit", 20, True, "Unit"), pdate(b.get("expiration_date"), "Expiry date"), iid))
    return out(msg="Item updated.")


@bp.delete("/inventory/<int:iid>")
@api("Volunteer")
def delete_item(iid):
    with tx() as cur:
        cur.execute("DELETE FROM Inventory_Item WHERE Item_ID=%s", (iid,))
        if not cur.rowcount:
            raise Bad("Item not found.", 404)
    return out(msg="Item deleted.")


# ---------------------------------------------------------------- distributions (hampers)
def scope(cur):
    """Volunteers see/manage distributions for their own shifts (or ones they handed out). Coordinators see all."""
    if session["role"] == "Volunteer":
        vid = my_id(cur, "Volunteer")
        return "(ds.Shift_ID IN (SELECT Shift_ID FROM Shift_Assignment WHERE Volunteer_ID=%s) OR ds.Given_By_Volunteer_ID=%s)", [vid, vid]
    return "1=1", []


def dist_rows(cur, where, params):
    cur.execute(f"""SELECT ds.Distribution_ID id, ds.Pickup_Date_Time pickup, ds.Status status, ds.Shift_ID shift_id,
            r.Recipient_ID recipient_id, r.Name recipient, r.Household_Size household, r.Food_Preferences dietary, r.Phone phone,
            v.Name given_by, s.Task shift_task, s.Start_Time shift_start
            FROM Distribution ds JOIN Recipient r ON r.Recipient_ID=ds.Recipient_ID
            LEFT JOIN Volunteer v ON v.Volunteer_ID=ds.Given_By_Volunteer_ID LEFT JOIN Shift s ON s.Shift_ID=ds.Shift_ID
            WHERE {where} ORDER BY ds.Pickup_Date_Time DESC LIMIT 300""", params)
    rows = cur.fetchall()
    if rows:
        ids = [r["id"] for r in rows]
        cur.execute(f"""SELECT di.Distribution_ID did, di.Item_ID item_id, i.Name item, c.Name category, di.Quantity qty, i.Unit unit
                FROM Distribution_Item di JOIN Inventory_Item i ON i.Item_ID=di.Item_ID JOIN Category c ON c.Category_ID=i.Category_ID
                WHERE di.Distribution_ID IN ({','.join(['%s'] * len(ids))}) ORDER BY i.Name""", ids)
        by = {}
        for it in cur.fetchall():
            by.setdefault(it.pop("did"), []).append(it)
        for r in rows:
            r["items"] = by.get(r["id"], [])
    return rows


def date_filters(where, p, col):
    a = request.args
    if a.get("from"):
        where.append(f"DATE({col})>=%s"); p.append(pdate(a["from"], "From date"))
    if a.get("to"):
        where.append(f"DATE({col})<=%s"); p.append(pdate(a["to"], "To date"))


@bp.get("/distributions")
@api("Volunteer", "Coordinator")
def distributions():
    with tx() as cur:
        w, p = scope(cur)
        where = [w]
        a = request.args
        if a.get("recipient"):
            where.append("r.Name LIKE %s"); p.append(f"%{a['recipient'].strip()}%")
        if a.get("status") in ("Scheduled", "Fulfilled", "Missed", "Delayed"):
            where.append("ds.Status=%s"); p.append(a["status"])
        if a.get("unassigned"):
            where.append("ds.Shift_ID IS NULL AND ds.Status IN ('Scheduled','Delayed')")
        date_filters(where, p, "ds.Pickup_Date_Time")
        return out(distributions=dist_rows(cur, " AND ".join(where), p))


@bp.get("/recipients/approved")
@api("Volunteer", "Coordinator")
def approved_recipients():
    with tx() as cur:
        cur.execute("""SELECT Recipient_ID id, Name name, Household_Size household, Food_Preferences dietary FROM Recipient
                       WHERE Approval_Status='Approved' ORDER BY Name""")
        return out(recipients=cur.fetchall())


def restore_stock(cur, did):
    """Put a distribution's items back on the shelf (same rule as the AI pickup check uses for missed pickups)."""
    cur.execute("""UPDATE Inventory_Item i JOIN Distribution_Item di ON di.Item_ID=i.Item_ID
                   SET i.Quantity=i.Quantity+di.Quantity WHERE di.Distribution_ID=%s""", (did,))
    cur.execute("""UPDATE Expiry_Record e JOIN Distribution_Item di ON di.Item_ID=e.Item_ID
                   SET e.Quantity=e.Quantity+di.Quantity WHERE di.Distribution_ID=%s""", (did,))


def apply_items(cur, did, items):
    merged = {}
    for n, it in enumerate(items or [], 1):
        try:
            iid = int(it.get("item_id"))
        except (TypeError, ValueError):
            raise Bad(f"Pick an item for line {n}.")
        merged[iid] = merged.get(iid, 0) + num(it.get("quantity"), f"Line {n} quantity")
    if not merged:
        raise Bad("Add at least one item to the hamper.")
    day = today(cur)
    for iid, q in merged.items():
        cur.execute("SELECT Name, Quantity, Status, Expiration_Date FROM Inventory_Item WHERE Item_ID=%s FOR UPDATE", (iid,))
        r = cur.fetchone()
        if not r or r["Status"] != "Available":
            raise Bad(f"Item #{iid} is not in stock.")
        if r["Expiration_Date"] < day:
            raise Bad(f"{r['Name']} has expired and cannot be given out.")
        if q > r["Quantity"]:
            raise Bad(f"Only {r['Quantity']:g} of {r['Name']} are left in stock.")
        cur.execute("INSERT INTO Distribution_Item (Distribution_ID,Item_ID,Quantity) VALUES (%s,%s,%s)", (did, iid, q))
        cur.execute("UPDATE Inventory_Item SET Quantity=Quantity-%s WHERE Item_ID=%s", (q, iid))


def own_shift_or_fail(cur, shift_id):
    if session["role"] != "Volunteer":
        return
    cur.execute("SELECT 1 FROM Shift_Assignment WHERE Shift_ID=%s AND Volunteer_ID=%s", (shift_id, my_id(cur, "Volunteer")))
    if not cur.fetchone():
        raise Bad("You can only manage distributions for shifts you are assigned to.", 403)


def get_dist(cur, did):
    w, p = scope(cur)
    cur.execute(f"SELECT ds.* FROM Distribution ds WHERE ds.Distribution_ID=%s AND {w}", [did, *p])
    d = cur.fetchone()
    if not d:
        raise Bad("Distribution not found, or it is not part of your shifts.", 404)
    return d


def attach_pickups(cur):
    """Pickups with no shift yet join the shift that covers their pickup time."""
    cur.execute("""UPDATE Distribution d JOIN Shift s ON d.Pickup_Date_Time BETWEEN s.Start_Time AND s.End_Time
                   SET d.Shift_ID=s.Shift_ID WHERE d.Shift_ID IS NULL AND d.Status IN ('Scheduled','Delayed')""")


@bp.post("/distributions")
@api("Volunteer")
def add_distribution():
    b = body()
    with tx() as cur:
        vid = my_id(cur, "Volunteer")
        shift = int(b.get("shift_id") or 0)
        own_shift_or_fail(cur, shift)
        cur.execute("SELECT Approval_Status FROM Recipient WHERE Recipient_ID=%s", (int(b.get("recipient_id") or 0),))
        r = cur.fetchone()
        if not r or r["Approval_Status"] != "Approved":
            raise Bad("Pick an approved recipient.")
        st = b.get("status", "Scheduled")
        if st not in ("Scheduled", "Fulfilled"):
            raise Bad("A new record is either Scheduled or Fulfilled.")
        cur.execute("""INSERT INTO Distribution (Recipient_ID,Pickup_Date_Time,Status,Given_By_Volunteer_ID,Shift_ID)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (int(b["recipient_id"]), pdt(b.get("pickup"), "Pickup date and time"), st, vid if st == "Fulfilled" else None, shift))
        did = cur.lastrowid
        apply_items(cur, did, b.get("items"))
    return out(msg="Distribution saved.", id=did)


@bp.put("/distributions/<int:did>")
@api("Volunteer")
def edit_distribution(did):
    b = body()
    with tx() as cur:
        d = get_dist(cur, did)
        if d["Status"] == "Missed":
            raise Bad("A missed pickup cannot be edited. Create a new pickup instead.", 409)
        if b.get("shift_id"):
            own_shift_or_fail(cur, int(b["shift_id"]))
            cur.execute("UPDATE Distribution SET Shift_ID=%s WHERE Distribution_ID=%s", (int(b["shift_id"]), did))
        if b.get("pickup"):
            cur.execute("UPDATE Distribution SET Pickup_Date_Time=%s WHERE Distribution_ID=%s", (pdt(b["pickup"], "Pickup date and time"), did))
        if "items" in b:
            restore_stock(cur, did)
            cur.execute("DELETE FROM Distribution_Item WHERE Distribution_ID=%s", (did,))
            apply_items(cur, did, b["items"])
    return out(msg="Distribution updated.")


@bp.delete("/distributions/<int:did>")
@api("Volunteer")
def delete_distribution(did):
    with tx() as cur:
        d = get_dist(cur, did)
        if d["Status"] != "Missed":          # a missed pickup's stock was already returned
            restore_stock(cur, did)
        cur.execute("DELETE FROM Distribution WHERE Distribution_ID=%s", (did,))
    return out(msg="Distribution deleted and its items returned to stock.")


@bp.post("/distributions/<int:did>/status")
@api("Volunteer")
def set_status(did):
    new = body().get("status")
    if new not in ("Fulfilled", "Missed", "Delayed"):
        raise Bad("Status must be Fulfilled, Missed or Delayed.")
    with tx() as cur:
        d = get_dist(cur, did)
        if d["Status"] in ("Fulfilled", "Missed"):
            raise Bad(f"This pickup is already {d['Status'].lower()} and cannot change.", 409)
        if new == "Delayed" and d["Status"] == "Delayed":
            raise Bad("This pickup is already marked delayed.", 409)
        cur.execute("SELECT COUNT(*) n FROM Distribution_Item WHERE Distribution_ID=%s", (did,))
        if new == "Fulfilled" and not cur.fetchone()["n"]:
            raise Bad("Add the hamper items before marking it fulfilled.")
        if new == "Missed":
            restore_stock(cur, did)
        cur.execute("UPDATE Distribution SET Status=%s, Given_By_Volunteer_ID=%s WHERE Distribution_ID=%s",
                    (new, my_id(cur, "Volunteer") if new == "Fulfilled" else d["Given_By_Volunteer_ID"], did))
    if new in ("Missed", "Delayed"):    # coordinators get the alert email right away (Algorithm 4)
        threading.Thread(target=ai_engine.run_check, kwargs={"mode": "Automatic", "pickups_only": True}, daemon=True).start()
    return out(msg=f"Marked {new.lower()}." + (" Coordinators will be emailed." if new != "Fulfilled" else ""))


@bp.post("/distributions/<int:did>/shift")
@api("Coordinator")
def assign_distribution_shift(did):
    sid = body().get("shift_id") or None
    with tx() as cur:
        cur.execute("UPDATE Distribution SET Shift_ID=%s WHERE Distribution_ID=%s", (sid, did))
    return out(msg="Pickup moved to the shift.")


# ---------------------------------------------------------------- recipient
@bp.get("/recipient/hampers")
@api("Recipient")
def my_hampers():
    with tx() as cur:
        rid = my_id(cur, "Recipient")
        cur.execute("SELECT Approval_Status s FROM Recipient WHERE Recipient_ID=%s", (rid,))
        app_row = cur.fetchone()
        approval = app_row["s"] if app_row else "Pending"
        where, p = ["ds.Recipient_ID=%s"], [rid]
        date_filters(where, p, "ds.Pickup_Date_Time")
        hampers = dist_rows(cur, " AND ".join(where), p)
        return out(hampers=hampers, approval=approval)


@bp.post("/recipient/pickups")
@api("Recipient")
def request_pickup():
    when = pdt(body().get("pickup"), "Pickup date and time")
    with tx() as cur:
        rid = my_id(cur, "Recipient")
        cur.execute("SELECT Approval_Status s FROM Recipient WHERE Recipient_ID=%s", (rid,))
        app_row = cur.fetchone()
        if not app_row or app_row["s"] != "Approved":
            raise Bad("A coordinator must approve your registration before you can request a hamper.", 403)
        now = ai_engine.now(cur)
        if when <= now:
            raise Bad("Choose a pickup time in the future.")
        if when > now + dt.timedelta(days=60):
            raise Bad("Pickups can be booked up to 60 days ahead.")
        cur.execute("SELECT Pickup_Date_Time t FROM Distribution WHERE Recipient_ID=%s AND Status IN ('Scheduled','Delayed') LIMIT 1", (rid,))
        open_one = cur.fetchone()
        if open_one:
            raise Bad(f"You already have a pickup on {open_one['t']:%b %d at %I:%M %p}. Collect it first, then request another.", 409)
        cur.execute("INSERT INTO Distribution (Recipient_ID,Pickup_Date_Time,Status) VALUES (%s,%s,'Scheduled')", (rid, when))
        attach_pickups(cur)
    return out(msg="Pickup requested. A volunteer will pack your hamper.")


# ---------------------------------------------------------------- shifts
def shift_list(cur, only_vid=None):
    cur.execute(f"""SELECT s.Shift_ID id, s.Start_Time start, s.End_Time end, s.Task task, co.Name coordinator
            FROM Shift s JOIN Coordinator co ON co.Coordinator_ID=s.Coordinator_ID
            {'WHERE s.Shift_ID IN (SELECT Shift_ID FROM Shift_Assignment WHERE Volunteer_ID=%s)' if only_vid else ''}
            ORDER BY s.Start_Time DESC LIMIT 300""", (only_vid,) if only_vid else ())
    rows = cur.fetchall()
    cur.execute("SELECT sa.Shift_ID sid, v.Volunteer_ID id, v.Name name FROM Shift_Assignment sa JOIN Volunteer v USING(Volunteer_ID)")
    vols = {}
    for r in cur.fetchall():
        vols.setdefault(r["sid"], []).append({"id": r["id"], "name": r["name"]})
    cur.execute("SELECT Shift_ID sid, COUNT(*) n FROM Distribution WHERE Shift_ID IS NOT NULL GROUP BY Shift_ID")
    pick = {r["sid"]: r["n"] for r in cur.fetchall()}
    for r in rows:
        r["volunteers"], r["pickups"] = vols.get(r["id"], []), pick.get(r["id"], 0)
    return rows


@bp.get("/shifts")
@api("Volunteer", "Coordinator")
def shifts():
    with tx() as cur:
        rows = shift_list(cur, my_id(cur, "Volunteer") if session["role"] == "Volunteer" else None)
        cur.execute("SELECT Volunteer_ID id, Name name, Availability availability FROM Volunteer ORDER BY Name")
        return out(shifts=rows, volunteers=cur.fetchall() if session["role"] == "Coordinator" else [], now=ai_engine.now(cur))


def availability_problems(cur, vids, start, end, skip_shift=None):
    """Reasons a volunteer should not be assigned: outside their availability, or already on an overlapping shift."""
    out_ = []
    for vid in vids:
        cur.execute("SELECT Name FROM Volunteer WHERE Volunteer_ID=%s", (vid,))
        v = cur.fetchone()
        if not v:
            raise Bad("One of the selected volunteers no longer exists.")
        ok = any(s["day"] == DAYS[start.weekday()] and s["start"] <= start.strftime("%H:%M") and s["end"] >= end.strftime("%H:%M")
                 and start.date() == end.date() for s in J(get_slots(cur, vid)))
        if not ok:
            out_.append(f"{v['Name']} is not available {start:%a %H:%M}-{end:%H:%M}.")
        cur.execute("""SELECT s.Task FROM Shift s JOIN Shift_Assignment sa USING(Shift_ID) WHERE sa.Volunteer_ID=%s
                       AND s.Start_Time<%s AND s.End_Time>%s AND s.Shift_ID<>%s LIMIT 1""", (vid, end, start, skip_shift or 0))
        o = cur.fetchone()
        if o:
            out_.append(f"{v['Name']} is already on another shift at that time ({o['Task']}).")
    return out_


def save_shift(cur, sid, b):
    start, end = pdt(b.get("start"), "Start time"), pdt(b.get("end"), "End time")
    if end <= start:
        raise Bad("The shift must end after it starts.")
    task = text(b, "task", 255, True, "Task")
    vids = sorted({int(v) for v in b.get("volunteer_ids") or []})
    if not vids:
        raise Bad("Assign at least one volunteer.")
    problems = availability_problems(cur, vids, start, end, sid)
    if problems and not b.get("force"):
        raise Bad("Availability check: " + " ".join(problems), 409, conflicts=problems)
    if sid:
        cur.execute("UPDATE Shift SET Start_Time=%s, End_Time=%s, Task=%s WHERE Shift_ID=%s", (start, end, task, sid))
        cur.execute("DELETE FROM Shift_Assignment WHERE Shift_ID=%s", (sid,))
    else:
        cur.execute("INSERT INTO Shift (Start_Time,End_Time,Task,Coordinator_ID) VALUES (%s,%s,%s,%s)", (start, end, task, my_id(cur, "Coordinator")))
        sid = cur.lastrowid
    for v in vids:
        cur.execute("INSERT INTO Shift_Assignment (Shift_ID,Volunteer_ID) VALUES (%s,%s)", (sid, v))
    attach_pickups(cur)
    return sid


@bp.post("/shifts")
@api("Coordinator")
def add_shift():
    with tx() as cur:
        save_shift(cur, None, body())
    return out(msg="Shift created and volunteers assigned.")


@bp.put("/shifts/<int:sid>")
@api("Coordinator")
def edit_shift(sid):
    with tx() as cur:
        save_shift(cur, sid, body())
    return out(msg="Shift updated.")


@bp.delete("/shifts/<int:sid>")
@api("Coordinator")
def delete_shift(sid):
    with tx() as cur:
        cur.execute("DELETE FROM Shift WHERE Shift_ID=%s", (sid,))
    return out(msg="Shift deleted.")


@bp.get("/availability")
@api("Volunteer")
def my_availability():
    with tx() as cur:
        return out(slots=get_slots(cur, my_id(cur, "Volunteer")))


# ---------------------------------------------------------------- dashboards + email log
@bp.get("/dashboard")
@api()
def dashboard():
    role = session["role"]
    with tx() as cur:
        day, now = today(cur), ai_engine.now(cur)
        one = lambda sql, p=(): (cur.execute(sql, p), cur.fetchone())[1]
        many = lambda sql, p=(): (cur.execute(sql, p), cur.fetchall())[1]
        risk = """SELECT i.Item_ID id, i.Name name, i.Quantity qty, i.Unit unit, i.Expiration_Date expires,
                  DATEDIFF(i.Expiration_Date,%s) days_left FROM Inventory_Item i
                  WHERE i.Status='Available' AND i.Quantity>0 AND DATEDIFF(i.Expiration_Date,%s) BETWEEN 0 AND 3
                  ORDER BY i.Expiration_Date, i.Name LIMIT 8"""
        if role == "Coordinator":
            d = one("""SELECT (SELECT COUNT(*) FROM Recipient WHERE Approval_Status='Pending') pending,
                       (SELECT COUNT(*) FROM Distribution WHERE Status IN ('Missed','Delayed') AND Pickup_Date_Time>=%s - INTERVAL 14 DAY) late,
                       (SELECT COUNT(*) FROM Distribution WHERE Status='Scheduled' AND Shift_ID IS NULL) unassigned,
                       (SELECT COUNT(*) FROM Distribution WHERE Status='Scheduled') upcoming,
                       (SELECT COUNT(*) FROM Inventory_Item WHERE Status='Available' AND Quantity>0 AND Expiration_Date>=%s) in_stock,
                       (SELECT COUNT(*) FROM Inventory_Item WHERE Status='Available' AND Quantity>0 AND Expiration_Date<%s) waiting""",
                      (day, day, day))
            d["at_risk"] = many(risk, (day, day))
            d["late_list"] = many("""SELECT ds.Distribution_ID id, r.Name recipient, ds.Pickup_Date_Time pickup, ds.Status status
                    FROM Distribution ds JOIN Recipient r USING(Recipient_ID) WHERE ds.Status IN ('Missed','Delayed')
                    ORDER BY ds.Pickup_Date_Time DESC LIMIT 6""")
        elif role == "Volunteer":
            vid = my_id(cur, "Volunteer")
            d = {"shifts": many("""SELECT s.Shift_ID id, s.Start_Time start, s.End_Time end, s.Task task FROM Shift s
                    JOIN Shift_Assignment sa USING(Shift_ID) WHERE sa.Volunteer_ID=%s AND s.End_Time>=%s ORDER BY s.Start_Time LIMIT 5""", (vid, now))}
            w, p = scope(cur)
            d["pickups"] = dist_rows(cur, f"{w} AND ds.Status IN ('Scheduled','Delayed')", p)[::-1][:8]
            d["at_risk"] = many(risk, (day, day))
        elif role == "Donor":
            d = one("""SELECT COUNT(DISTINCT d.Donation_ID) donations, COUNT(i.Item_ID) item_lines, MAX(d.Date_Time) last_donation
                       FROM Donation d LEFT JOIN Inventory_Item i USING(Donation_ID) WHERE d.Donor_ID=%s""", (my_id(cur, "Donor"),))
        else:
            rid = my_id(cur, "Recipient")
            d = one("SELECT Approval_Status approval, Household_Size household FROM Recipient WHERE Recipient_ID=%s", (rid,))
            d["next"] = one("""SELECT Pickup_Date_Time pickup, Status status FROM Distribution WHERE Recipient_ID=%s
                               AND Status IN ('Scheduled','Delayed') ORDER BY Pickup_Date_Time LIMIT 1""", (rid,))
            d["received"] = one("SELECT COUNT(*) n FROM Distribution WHERE Recipient_ID=%s AND Status='Fulfilled'", (rid,))["n"]
    return out(role=role, today=day, **d)


@bp.get("/emails")
@api("Coordinator")
def emails():
    with tx() as cur:
        cur.execute("""SELECT e.Email_ID id, e.Sent_At sent, e.To_Email to_email, ua.Role role, e.Subject subject, e.Body body,
                e.Written_By written_by, e.Run_Mode mode, e.Status status, a.Type alert_type
                FROM Email_Log e JOIN User_Account ua ON ua.User_ID=e.To_User_ID LEFT JOIN Alert a ON a.Alert_ID=e.Alert_ID
                ORDER BY e.Email_ID DESC LIMIT 150""")
        return out(emails=cur.fetchall())
