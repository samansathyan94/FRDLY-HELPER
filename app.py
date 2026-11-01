"""FRDLY HELPER - Flask backend. MySQL in production (PyMySQL); SQLite only for automated tests."""

import os
import math
import uuid
import datetime as dt

from dotenv import load_dotenv

# Load .env using an absolute path before accessing environment variables
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOTENV_PATH = os.path.join(BASE_DIR, ".env")
load_dotenv(DOTENV_PATH)

from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash


SQLITE = os.getenv("DB_BACKEND", "mysql") == "sqlite"

CATEGORIES = [
    "Vehicle Mechanic",
    "Electrician",
    "Plumber",
    "Vehicle Towing",
    "Water Supplier",
    "Medical Shop",
    "Appliance Repair",
    "Other"
]

RADII_KM = [10, 25, 50]

ACTIVE = (
    "requested",
    "accepted",
    "on_the_way",
    "arrived",
    "estimate_submitted",
    "estimate_approved",
    "in_progress",
    "awaiting_confirmation"
)

# Booking status transitions
T = {
    ("requested", "accept"): ("provider", "accepted"),
    ("requested", "reject"): ("provider", "rejected"),
    ("requested", "cancel"): ("customer", "cancelled"),
    ("accepted", "cancel"): ("customer", "cancelled"),
    ("accepted", "on_the_way"): ("provider", "on_the_way"),
    ("on_the_way", "arrived"): ("provider", "arrived"),
    ("estimate_submitted", "approve"): ("customer", "estimate_approved"),
    ("estimate_submitted", "decline"): ("customer", "cancelled"),
    ("estimate_approved", "start"): ("provider", "in_progress"),
    ("in_progress", "complete"): ("provider", "awaiting_confirmation"),
    ("awaiting_confirmation", "confirm"): ("customer", "completed")
}


app = Flask(__name__, static_folder="static", static_url_path="/static")

app.secret_key = os.getenv("SECRET_KEY") or os.urandom(32)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    MAX_CONTENT_LENGTH=1024 * 1024
)


def now():
    return dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# DATABASE TRANSACTION
# ============================================================

class Tx:
    """One DB transaction: commit on success, rollback on exception."""

    def __enter__(s):

        if SQLITE:
            import sqlite3

            s.c = sqlite3.connect(
                os.getenv("SQLITE_PATH", "frdly.db")
            )

            s.c.row_factory = sqlite3.Row

        else:
            import pymysql

            db_host = os.getenv("DB_HOST", "localhost")
            port_val = os.getenv("DB_PORT", "3306")
            try:
                db_port = int(port_val)
            except (ValueError, TypeError):
                raise RuntimeError(
                    f"Database configuration error: 'DB_PORT' must be a valid integer, got {port_val!r}."
                )

            db_user = os.getenv("DB_USER")
            db_password = os.getenv("DB_PASSWORD")
            db_name = os.getenv("DB_NAME", "frdly_helper")

            missing_keys = []
            if not db_user:
                missing_keys.append("DB_USER")
            if db_password is None:
                missing_keys.append("DB_PASSWORD")
            if not db_name:
                missing_keys.append("DB_NAME")

            if missing_keys:
                raise RuntimeError(
                    f"Database configuration error: Missing required setting(s) in .env: {', '.join(missing_keys)}. "
                    "Please configure them in your .env file."
                )

            try:
                s.c = pymysql.connect(
                    host=db_host,
                    port=db_port,
                    user=db_user,
                    password=db_password,
                    database=db_name,
                    charset="utf8mb4",
                    cursorclass=pymysql.cursors.DictCursor
                )
            except pymysql.err.OperationalError as e:
                err_code = e.args[0] if e.args else None
                err_msg = e.args[1] if len(e.args) > 1 else str(e)
                if err_code == 1045:
                    raise RuntimeError(
                        f"MySQL Authentication Failed (1045): Access denied for user '{db_user}'@'{db_host}'. "
                        "Please verify DB_USER and DB_PASSWORD in .env and ensure the user exists with appropriate permissions."
                    ) from None
                elif err_code == 1049:
                    raise RuntimeError(
                        f"MySQL Database Error (1049): Unknown database '{db_name}'. "
                        f"Please ensure the database exists in MySQL (e.g. CREATE DATABASE `{db_name}` CHARACTER SET utf8mb4;)."
                    ) from None
                elif err_code == 2003:
                    raise RuntimeError(
                        f"MySQL Connection Error (2003): Cannot connect to MySQL server on '{db_host}:{db_port}'. "
                        "Please verify that MySQL Server is running."
                    ) from None
                else:
                    raise RuntimeError(
                        f"MySQL Connection Error ({err_code}): {err_msg}"
                    ) from None

        s.cur = s.c.cursor()

        return s

    def x(s, sql, a=()):
        s.cur.execute(
            sql if SQLITE else sql.replace("?", "%s"),
            a
        )

        return s.cur

    def all(s, sql, a=()):
        return [
            dict(r)
            for r in s.x(sql, a).fetchall()
        ]

    def one(s, sql, a=()):

        r = s.x(sql, a).fetchone()

        return dict(r) if r else None

    def __exit__(s, t, v, tb):

        (s.c.rollback if t else s.c.commit)()

        s.c.close()


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_db():

    pk = (
        "INTEGER PRIMARY KEY AUTOINCREMENT"
        if SQLITE
        else "INT AUTO_INCREMENT PRIMARY KEY"
    )

    eng = "" if SQLITE else " ENGINE=InnoDB"

    ddl = [

        f"""
        CREATE TABLE IF NOT EXISTS users(
            id {pk},
            name VARCHAR(100) NOT NULL,
            email VARCHAR(150) NOT NULL UNIQUE,
            pw_hash VARCHAR(255) NOT NULL,
            role VARCHAR(10) NOT NULL,
            phone VARCHAR(20),
            created_at VARCHAR(19) NOT NULL
        ){eng}
        """,

        f"""
        CREATE TABLE IF NOT EXISTS providers(
            user_id INT PRIMARY KEY,
            category VARCHAR(40) NOT NULL,
            skills VARCHAR(255),
            available TINYINT NOT NULL DEFAULT 0,
            lat DOUBLE,
            lng DOUBLE,
            loc_at VARCHAR(19),
            verified TINYINT NOT NULL DEFAULT 1,
            FOREIGN KEY(user_id) REFERENCES users(id)
        ){eng}
        """,

        f"""
        CREATE TABLE IF NOT EXISTS bookings(
            id {pk},
            client_ref VARCHAR(40),
            customer_id INT NOT NULL,
            provider_id INT,
            category VARCHAR(40) NOT NULL,
            description VARCHAR(1000) NOT NULL,
            lat DOUBLE NOT NULL,
            lng DOUBLE NOT NULL,
            emergency TINYINT NOT NULL DEFAULT 0,
            status VARCHAR(30) NOT NULL,
            created_at VARCHAR(19) NOT NULL,
            updated_at VARCHAR(19) NOT NULL,
            UNIQUE(customer_id, client_ref),
            FOREIGN KEY(customer_id) REFERENCES users(id),
            FOREIGN KEY(provider_id) REFERENCES users(id)
        ){eng}
        """,

        f"""
        CREATE TABLE IF NOT EXISTS booking_events(
            id {pk},
            booking_id INT NOT NULL,
            status VARCHAR(30) NOT NULL,
            at VARCHAR(19) NOT NULL,
            FOREIGN KEY(booking_id) REFERENCES bookings(id)
        ){eng}
        """,

        f"""
        CREATE TABLE IF NOT EXISTS estimates(
            id {pk},
            booking_id INT NOT NULL,
            labour DOUBLE NOT NULL,
            parts DOUBLE NOT NULL,
            extra DOUBLE NOT NULL,
            total DOUBLE NOT NULL,
            note VARCHAR(500),
            created_at VARCHAR(19) NOT NULL,
            FOREIGN KEY(booking_id) REFERENCES bookings(id)
        ){eng}
        """,

        f"""
        CREATE TABLE IF NOT EXISTS reviews(
            id {pk},
            booking_id INT NOT NULL UNIQUE,
            customer_id INT NOT NULL,
            provider_id INT NOT NULL,
            rating TINYINT NOT NULL,
            comment VARCHAR(500),
            created_at VARCHAR(19) NOT NULL,
            FOREIGN KEY(booking_id) REFERENCES bookings(id)
        ){eng}
        """
    ]

    with Tx() as t:

        for d in ddl:
            t.x(d)

        ae = os.getenv("ADMIN_EMAIL")
        ap = os.getenv("ADMIN_PASSWORD")

        if ae and ap and not t.one(
            "SELECT id FROM users WHERE email=?",
            (ae.lower(),)
        ):

            t.x(
                """
                INSERT INTO users(
                    name,email,pw_hash,role,created_at
                )
                VALUES(?,?,?,?,?)
                """,
                (
                    "Admin",
                    ae.lower(),
                    generate_password_hash(ap),
                    "admin",
                    now()
                )
            )


# ============================================================
# ERROR HANDLING
# ============================================================

class Err(Exception):

    def __init__(s, msg, code=400):
        s.msg = msg
        s.code = code


@app.errorhandler(Err)
def _e(e):
    return jsonify(error=e.msg), e.code


@app.errorhandler(404)
def _404(e):
    return jsonify(error="Not found"), 404


@app.errorhandler(413)
def _413(e):
    return jsonify(error="Payload too large"), 413


@app.errorhandler(Exception)
def _500(e):

    app.logger.exception(e)

    return jsonify(error="Server error"), 500


# ============================================================
# AUTHORIZATION
# ============================================================

def role_required(*roles):

    def deco(f):

        @wraps(f)
        def w(*a, **k):

            if "uid" not in session:
                raise Err("Login required", 401)

            if session["role"] not in roles:
                raise Err("Forbidden", 403)

            return f(*a, **k)

        return w

    return deco


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def body():
    return request.get_json(silent=True) or {}


def num(v, name, lo=None, hi=None):

    try:
        n = float(v)

    except (TypeError, ValueError):
        raise Err(f"{name} must be a number")

    if (
        math.isnan(n)
        or (lo is not None and n < lo)
        or (hi is not None and n > hi)
    ):
        raise Err(f"{name} out of range")

    return n


def km(a, b, c, d):

    p = math.pi / 180

    h = (
        math.sin((c - a) * p / 2) ** 2
        + math.cos(a * p)
        * math.cos(c * p)
        * math.sin((d - b) * p / 2) ** 2
    )

    return 12742 * math.asin(math.sqrt(h))


# ============================================================
# FRONTEND
# ============================================================

@app.get("/")
def index():

    return send_from_directory("static", "index.html")


# ============================================================
# SERVICE CATEGORIES
# ============================================================

@app.get("/api/categories")
def cats():

    return jsonify(CATEGORIES)


# ============================================================
# CUSTOMER / PROVIDER REGISTRATION
# ============================================================

@app.post("/api/register")
def register():

    d = body()

    name = str(d.get("name", "")).strip()

    email = str(d.get("email", "")).strip().lower()

    pw = str(d.get("password", ""))

    role = d.get("role")

    if not (2 <= len(name) <= 100) or "@" not in email or len(email) > 150:
        raise Err("Valid name and email required")

    if len(pw) < 8:
        raise Err("Password must be at least 8 characters")

    if role not in ("customer", "provider"):
        raise Err("Role must be customer or provider")

    if role == "provider" and d.get("category") not in CATEGORIES:
        raise Err("Valid service category required")

    with Tx() as t:

        if t.one(
            "SELECT id FROM users WHERE email=?",
            (email,)
        ):
            raise Err("Email already registered", 409)

        uid = t.x(
            """
            INSERT INTO users(
                name,email,pw_hash,role,phone,created_at
            )
            VALUES(?,?,?,?,?,?)
            """,
            (
                name,
                email,
                generate_password_hash(pw),
                role,
                str(d.get("phone", ""))[:20],
                now()
            )
        ).lastrowid

        if role == "provider":

            t.x(
                """
                INSERT INTO providers(
                    user_id,category,skills
                )
                VALUES(?,?,?)
                """,
                (
                    uid,
                    d["category"],
                    str(d.get("skills", ""))[:255]
                )
            )

    return jsonify(id=uid), 201


# ============================================================
# LOGIN
# ============================================================

@app.post("/api/login")
def login():

    d = body()

    with Tx() as t:

        u = t.one(
            "SELECT * FROM users WHERE email=?",
            (str(d.get("email", "")).lower(),)
        )

    if not u or not check_password_hash(
        u["pw_hash"],
        str(d.get("password", ""))
    ):
        raise Err("Invalid credentials", 401)

    session.clear()

    session.update(
        uid=u["id"],
        role=u["role"]
    )

    return jsonify(
        id=u["id"],
        name=u["name"],
        role=u["role"]
    )


# ============================================================
# LOGOUT
# ============================================================

@app.post("/api/logout")
def logout():

    session.clear()

    return jsonify(ok=True)


# ============================================================
# USER PROFILE
# ============================================================

@app.get("/api/me")
@role_required("customer", "provider", "admin")
def me():

    with Tx() as t:

        u = t.one(
            """
            SELECT id,name,email,role,phone
            FROM users WHERE id=?
            """,
            (session["uid"],)
        )

        if u["role"] == "provider":

            u["provider"] = t.one(
                "SELECT * FROM providers WHERE user_id=?",
                (u["id"],)
            )

    return jsonify(u)


@app.put("/api/me")
@role_required("customer", "provider")
def update_me():

    d = body()

    name = str(d.get("name", "")).strip()

    if not 2 <= len(name) <= 100:
        raise Err("Valid name required")

    with Tx() as t:

        t.x(
            """
            UPDATE users
            SET name=?, phone=?
            WHERE id=?
            """,
            (
                name,
                str(d.get("phone", ""))[:20],
                session["uid"]
            )
        )

        if session["role"] == "provider":

            t.x(
                "UPDATE providers SET skills=? WHERE user_id=?",
                (
                    str(d.get("skills", ""))[:255],
                    session["uid"]
                )
            )

    return jsonify(ok=True)


# ============================================================
# PROVIDER AVAILABILITY
# ============================================================

@app.put("/api/provider/availability")
@role_required("provider")
def availability():

    d = body()

    with Tx() as t:

        t.x(
            "UPDATE providers SET available=? WHERE user_id=?",
            (
                1 if d.get("available") else 0,
                session["uid"]
            )
        )

    return jsonify(
        available=bool(d.get("available"))
    )


# ============================================================
# PROVIDER LOCATION
# ============================================================

@app.put("/api/provider/location")
@role_required("provider")
def provider_loc():

    d = body()

    la = num(d.get("lat"), "lat", -90, 90)

    ln = num(d.get("lng"), "lng", -180, 180)

    with Tx() as t:

        t.x(
            """
            UPDATE providers
            SET lat=?, lng=?, loc_at=?
            WHERE user_id=?
            """,
            (
                la,
                ln,
                now(),
                session["uid"]
            )
        )

    return jsonify(ok=True)


# ============================================================
# INTELLIGENT PROVIDER MATCHING
# ============================================================

def rank(t, category, lat, lng, emergency, radius):

    rows = t.all(
        """
        SELECT
            p.user_id id,
            u.name,
            p.category,
            p.skills,
            p.lat,
            p.lng,
            p.loc_at,

            (
                SELECT COUNT(*)
                FROM bookings b
                WHERE b.provider_id=p.user_id
                AND b.status IN (
                    'accepted',
                    'on_the_way',
                    'arrived',
                    'estimate_submitted',
                    'estimate_approved',
                    'in_progress'
                )
            ) load_,

            (
                SELECT COUNT(*)
                FROM reviews r
                WHERE r.provider_id=p.user_id
            ) n_rev,

            (
                SELECT AVG(rating)
                FROM reviews r
                WHERE r.provider_id=p.user_id
            ) avg_rating,

            (
                SELECT COUNT(*)
                FROM bookings b
                WHERE b.provider_id=p.user_id
                AND b.status IN (
                    'accepted',
                    'completed',
                    'awaiting_confirmation'
                )
            ) n_ok,

            (
                SELECT COUNT(*)
                FROM bookings b
                WHERE b.provider_id=p.user_id
                AND b.status='rejected'
            ) n_rej

        FROM providers p
        JOIN users u ON u.id=p.user_id

        WHERE p.available=1
        AND p.verified=1
        AND p.category=?
        AND p.lat IS NOT NULL
        """,
        (category,)
    )

    out = []

    for r in rows:

        d = km(
            lat,
            lng,
            r["lat"],
            r["lng"]
        )

        if d > radius:
            continue

        s = (
            100
            - min(d * 3, 60)
            - r["load_"] * 8
        )

        if r["n_rev"] >= 3:

            s += (
                float(r["avg_rating"]) - 3
            ) * 6

        if r["n_ok"] + r["n_rej"] >= 3:

            s += (
                10 * r["n_ok"]
                / (r["n_ok"] + r["n_rej"])
                - 5
            )

        r.update(
            distance_km=round(d, 2),
            score=round(
                s + (5 if emergency else 0),
                1
            )
        )

        out.append(r)

    return sorted(
        out,
        key=lambda r: -r["score"]
    )


# ============================================================
# NEARBY PROVIDERS
# ============================================================

@app.get("/api/providers")
@role_required("customer", "admin")
def providers():

    cat = request.args.get("category", "")

    if cat not in CATEGORIES:
        raise Err("Valid category required")

    la = num(
        request.args.get("lat"),
        "lat",
        -90,
        90
    )

    ln = num(
        request.args.get("lng"),
        "lng",
        -180,
        180
    )

    with Tx() as t:

        res = rank(
            t,
            cat,
            la,
            ln,
            False,
            RADII_KM[-1]
        )

    return jsonify(res)


# ============================================================
# BOOKING QUERY
# ============================================================

BSEL = """
SELECT
    b.*,
    cu.name customer_name,
    cu.phone customer_phone,
    pu.name provider_name,
    pu.phone provider_phone,
    p.lat provider_lat,
    p.lng provider_lng,
    p.loc_at provider_loc_at

FROM bookings b

JOIN users cu
ON cu.id=b.customer_id

LEFT JOIN users pu
ON pu.id=b.provider_id

LEFT JOIN providers p
ON p.user_id=b.provider_id
"""


def hydrate(t, rows):

    for b in rows:

        b["estimate"] = t.one(
            """
            SELECT labour,parts,extra,total,note,created_at
            FROM estimates
            WHERE booking_id=?
            ORDER BY id DESC
            """,
            (b["id"],)
        )

        b["history"] = t.all(
            """
            SELECT status,at
            FROM booking_events
            WHERE booking_id=?
            ORDER BY id
            """,
            (b["id"],)
        )

        b["review"] = t.one(
            """
            SELECT rating,comment
            FROM reviews
            WHERE booking_id=?
            """,
            (b["id"],)
        )

        if b["status"] not in (
            "accepted",
            "on_the_way",
            "arrived"
        ):

            b["provider_lat"] = None
            b["provider_lng"] = None
            b["provider_loc_at"] = None

        b.pop("client_ref", None)

    return rows


# ============================================================
# CREATE BOOKING
# ============================================================

@app.post("/api/bookings")
@role_required("customer")
def create_booking():

    d = body()

    cat = d.get("category")

    desc = str(
        d.get("description", "")
    ).strip()

    if cat not in CATEGORIES:
        raise Err("Valid category required")

    if not 5 <= len(desc) <= 1000:
        raise Err(
            "Describe the problem (5-1000 characters)"
        )

    la = num(d.get("lat"), "lat", -90, 90)

    ln = num(d.get("lng"), "lng", -180, 180)

    emg = 1 if d.get("emergency") else 0

    ref = str(
        d.get("client_ref") or uuid.uuid4()
    )[:40]

    with Tx() as t:

        dup = t.one(
            BSEL + """
            WHERE b.customer_id=?
            AND b.client_ref=?
            """,
            (session["uid"], ref)
        )

        if dup:

            return jsonify(
                hydrate(t, [dup])[0]
            ), 200

        if t.one(
            """
            SELECT id
            FROM bookings
            WHERE customer_id=?
            AND category=?
            AND status IN %s
            """ % str(ACTIVE),
            (session["uid"], cat)
        ):

            raise Err(
                "You already have an active request in this category",
                409
            )

        pid = d.get("provider_id")

        chosen = None

        if pid:

            chosen = next(
                (
                    r for r in rank(
                        t,
                        cat,
                        la,
                        ln,
                        emg,
                        RADII_KM[-1]
                    )
                    if r["id"] == int(pid)
                ),
                None
            )

            if not chosen:
                raise Err(
                    "Selected provider is not available",
                    409
                )

        else:

            for rad in RADII_KM:

                ranked = rank(
                    t,
                    cat,
                    la,
                    ln,
                    emg,
                    rad
                )

                if ranked:

                    chosen = ranked[0]

                    break

            if not chosen:

                raise Err(
                    "No suitable provider available right now",
                    404
                )

        bid = t.x(
            """
            INSERT INTO bookings(
                client_ref,
                customer_id,
                provider_id,
                category,
                description,
                lat,
                lng,
                emergency,
                status,
                created_at,
                updated_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ref,
                session["uid"],
                chosen["id"],
                cat,
                desc,
                la,
                ln,
                emg,
                "requested",
                now(),
                now()
            )
        ).lastrowid

        t.x(
            """
            INSERT INTO booking_events(
                booking_id,status,at
            )
            VALUES(?,?,?)
            """,
            (
                bid,
                "requested",
                now()
            )
        )

        res = hydrate(
            t,
            [
                t.one(
                    BSEL + " WHERE b.id=?",
                    (bid,)
                )
            ]
        )[0]

    return jsonify(res), 201


# ============================================================
# LIST BOOKINGS
# ============================================================

@app.get("/api/bookings")
@role_required("customer", "provider", "admin")
def list_bookings():

    col = {
        "customer": "b.customer_id=?",
        "provider": "b.provider_id=?"
    }.get(session["role"])

    with Tx() as t:

        rows = t.all(
            BSEL
            + (
                f" WHERE {col}"
                if col else ""
            )
            + " ORDER BY b.emergency DESC, b.id DESC",

            (session["uid"],)
            if col else ()
        )

        return jsonify(
            hydrate(t, rows)
        )


# ============================================================
# BOOKING OWNERSHIP
# ============================================================

def get_own(t, bid):

    b = t.one(
        BSEL + " WHERE b.id=?",
        (bid,)
    )

    key = (
        "customer_id"
        if session["role"] == "customer"
        else "provider_id"
    )

    if not b or b[key] != session["uid"]:

        raise Err(
            "Booking not found",
            404
        )

    return b


# ============================================================
# BOOKING STATUS TRANSITIONS
# ============================================================

def move(t, b, frm, to):

    # Compare-and-swap prevents concurrent duplicate transitions.

    if t.x(
        """
        UPDATE bookings
        SET status=?, updated_at=?
        WHERE id=? AND status=?
        """,
        (
            to,
            now(),
            b["id"],
            frm
        )
    ).rowcount != 1:

        raise Err(
            "Booking was already updated; refresh",
            409
        )

    t.x(
        """
        INSERT INTO booking_events(
            booking_id,status,at
        )
        VALUES(?,?,?)
        """,
        (
            b["id"],
            to,
            now()
        )
    )


@app.post("/api/bookings/<int:bid>/action")
@role_required("customer", "provider")
def action(bid):

    act = body().get("action")

    with Tx() as t:

        b = get_own(t, bid)

        rule = T.get(
            (b["status"], act)
        )

        if not rule or rule[0] != session["role"]:

            raise Err(
                f"'{act}' not allowed while status is {b['status']}",
                409
            )

        move(
            t,
            b,
            b["status"],
            rule[1]
        )

        return jsonify(
            hydrate(
                t,
                [
                    t.one(
                        BSEL + " WHERE b.id=?",
                        (bid,)
                    )
                ]
            )[0]
        )


# ============================================================
# SERVICE ESTIMATE
# ============================================================

@app.post("/api/bookings/<int:bid>/estimate")
@role_required("provider")
def estimate(bid):

    d = body()

    def parse_charge(val, name):
        if val is None or val == "":
            return 0.0
        return num(val, name, 0, 1e7)

    lab = parse_charge(d.get("labour", d.get("labour_charge", 0)), "Labour charge")
    par = parse_charge(d.get("parts", d.get("parts_charge", 0)), "Parts / materials charge")
    ext = parse_charge(d.get("extra", d.get("additional_charge", 0)), "Additional charge")

    tot = round(lab + par + ext, 2)

    if tot <= 0:

        raise Err(
            "Estimate total must be greater than zero"
        )

    with Tx() as t:

        b = get_own(t, bid)

        if b["status"] != "arrived":

            raise Err(
                "Estimate can only be submitted after arrival",
                409
            )

        t.x(
            """
            INSERT INTO estimates(
                booking_id,
                labour,
                parts,
                extra,
                total,
                note,
                created_at
            )
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                bid,
                lab,
                par,
                ext,
                tot,
                str(d.get("note", ""))[:500],
                now()
            )
        )

        move(
            t,
            b,
            "arrived",
            "estimate_submitted"
        )

        return jsonify(
            hydrate(
                t,
                [
                    t.one(
                        BSEL + " WHERE b.id=?",
                        (bid,)
                    )
                ]
            )[0]
        )


# ============================================================
# CUSTOMER REVIEWS
# ============================================================

@app.post("/api/bookings/<int:bid>/review")
@role_required("customer")
def review(bid):

    d = body()

    r = int(
        num(
            d.get("rating"),
            "rating",
            1,
            5
        )
    )

    with Tx() as t:

        b = get_own(t, bid)

        if b["status"] != "completed":

            raise Err(
                "Only completed services can be reviewed",
                409
            )

        if t.one(
            "SELECT id FROM reviews WHERE booking_id=?",
            (bid,)
        ):

            raise Err(
                "Already reviewed",
                409
            )

        t.x(
            """
            INSERT INTO reviews(
                booking_id,
                customer_id,
                provider_id,
                rating,
                comment,
                created_at
            )
            VALUES(?,?,?,?,?,?)
            """,
            (
                bid,
                session["uid"],
                b["provider_id"],
                r,
                str(d.get("comment", ""))[:500],
                now()
            )
        )

    return jsonify(ok=True), 201


# ============================================================
# ADMIN STATISTICS
# ============================================================

@app.get("/api/admin/stats")
@role_required("admin")
def stats():

    with Tx() as t:

        return jsonify(

            customers=t.one(
                """
                SELECT COUNT(*) n
                FROM users
                WHERE role='customer'
                """
            )["n"],

            providers=t.one(
                """
                SELECT COUNT(*) n
                FROM users
                WHERE role='provider'
                """
            )["n"],

            available=t.one(
                """
                SELECT COUNT(*) n
                FROM providers
                WHERE available=1
                """
            )["n"],

            bookings=t.all(
                """
                SELECT status, COUNT(*) n
                FROM bookings
                GROUP BY status
                """
            ),

            emergencies=t.one(
                """
                SELECT COUNT(*) n
                FROM bookings
                WHERE emergency=1
                """
            )["n"],

            revenue=float(t.one(
                """
                SELECT COALESCE(SUM(total), 0) rev
                FROM estimates e
                JOIN bookings b ON b.id=e.booking_id
                WHERE b.status='completed'
                """
            )["rev"] or 0),

            daily_bookings=t.all(
                """
                SELECT SUBSTR(created_at, 1, 10) d, COUNT(*) n
                FROM bookings
                GROUP BY SUBSTR(created_at, 1, 10)
                ORDER BY d DESC
                LIMIT 7
                """
            ),

            categories=t.all(
                """
                SELECT category, COUNT(*) n
                FROM bookings
                GROUP BY category
                ORDER BY n DESC
                """
            )
        )


# ============================================================
# ADMIN USER MANAGEMENT
# ============================================================

@app.get("/api/admin/users")
@role_required("admin")
def admin_users():

    with Tx() as t:

        return jsonify(
            t.all(
                """
                SELECT
                    u.id,
                    u.name,
                    u.email,
                    u.role,
                    u.created_at,
                    p.category,
                    p.available,
                    p.verified

                FROM users u

                LEFT JOIN providers p
                ON p.user_id=u.id

                ORDER BY u.id
                """
            )
        )


# ============================================================
# PROVIDER VERIFICATION
# ============================================================

@app.put("/api/admin/providers/<int:pid>/verify")
@role_required("admin")
def verify(pid):

    with Tx() as t:

        if t.x(
            """
            UPDATE providers
            SET verified=?
            WHERE user_id=?
            """,
            (
                1 if body().get("verified") else 0,
                pid
            )
        ).rowcount != 1:

            raise Err(
                "Provider not found",
                404
            )

    return jsonify(ok=True)


# ============================================================
# APPLICATION INITIALIZATION
# ============================================================

init_db()


if __name__ == "__main__":

    app.run(
        host="127.0.0.1",
        port=int(os.getenv("PORT", 5000)),
        debug=False
    )