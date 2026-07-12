"""
migrate.py — MuftyKare SQLite → PostgreSQL migration
Run: python migrate.py
"""

import sqlite3
import asyncio
import asyncpg
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
# SQLITE_PATH = r"C:\Users\yaswanth.k\Downloads\muftycare.db"
SQLITE_PATH = "/var/www/muftykare-voice-agents/muftykarevoiceagents/muftycare.db"

# PG_CONFIG = dict(
#     host="localhost",
#     port=5432,
#     user="muftykare",
#     password="muftykare@123",
#     database="muftykare",
# )

PG_CONFIG = dict(
    host="localhost",
    port=5432,
    user="muftykare_voice_user",
    password="Ya@9703981489",
    database="muftykare_voice",
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def to_int(val):
    """Safely convert any value to int — returns None for empty/null."""
    if val is None or val == '':
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def to_float(val):
    """Safely convert any value to float — returns None for empty/null."""
    if val is None or val == '':
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def to_str(val):
    """Safely convert to string — returns None for empty/null."""
    if val is None or val == '':
        return None
    return str(val)


def to_bool(val):
    """Convert SQLite 0/1 or None to Python bool."""
    if val is None or val == '':
        return False
    return bool(int(val))


def parse_dt(val):
    """Parse datetime string from SQLite → Python datetime."""
    if not val or val == '':
        return None
    try:
        return datetime.fromisoformat(str(val).replace('Z', '+00:00'))
    except Exception:
        try:
            # fallback for non-standard formats
            return datetime.strptime(str(val), "%Y-%m-%d %H:%M:%S.%f")
        except Exception:
            try:
                return datetime.strptime(str(val), "%Y-%m-%d %H:%M:%S")
            except Exception:
                return None


# ── Main migration ────────────────────────────────────────────────────────────

async def migrate():
    # Connect SQLite
    sqlite_conn = sqlite3.connect(SQLITE_PATH)
    sqlite_conn.row_factory = sqlite3.Row
    cur = sqlite_conn.cursor()

    # Connect PostgreSQL
    pg_pool = await asyncpg.create_pool(**PG_CONFIG)

    print("=" * 60)
    print("MuftyKare SQLite → PostgreSQL Migration")
    print("=" * 60)

    async with pg_pool.acquire() as pg:

        # ── STEP 1: Create all tables ─────────────────────────────────

        print("\n[1/3] Creating tables...")

        await pg.execute("""
        CREATE TABLE IF NOT EXISTS manager (
            id       TEXT PRIMARY KEY,
            name     TEXT,
            phone_num TEXT,
            email    TEXT,
            password TEXT,
            role     TEXT,
            pic_url  TEXT,
            status   TEXT DEFAULT 'active'
        )""")

        await pg.execute("""
        CREATE TABLE IF NOT EXISTS customer (
            id        SERIAL PRIMARY KEY,
            name      TEXT,
            phone_num TEXT,
            address   TEXT
        )""")

        await pg.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id               SERIAL PRIMARY KEY,
            cust_id          INTEGER REFERENCES customer(id),
            mng_id           TEXT    REFERENCES manager(id),
            total_price      INTEGER DEFAULT 0,
            discount         INTEGER DEFAULT 0,
            other_charges    INTEGER DEFAULT 0,
            recieved_on      TIMESTAMP,
            delivered_on     TIMESTAMP,
            status           BOOLEAN DEFAULT FALSE,
            pmt_status       TEXT    DEFAULT 'not paid',
            ready_to_deliver BOOLEAN DEFAULT FALSE
        )""")

        await pg.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id       SERIAL PRIMARY KEY,
            ord_id   INTEGER REFERENCES orders(id),
            paid_to  TEXT    REFERENCES manager(id),
            paid_amt FLOAT,
            paid_on  TIMESTAMP
        )""")

        await pg.execute("""
        CREATE TABLE IF NOT EXISTS item_categories (
            id          SERIAL PRIMARY KEY,
            name        TEXT,
            description TEXT,
            url         TEXT
        )""")

        await pg.execute("""
        CREATE TABLE IF NOT EXISTS item_type (
            id        SERIAL PRIMARY KEY,
            it_cat_id INTEGER REFERENCES item_categories(id),
            name      TEXT
        )""")

        await pg.execute("""
        CREATE TABLE IF NOT EXISTS service_category (
            id   SERIAL PRIMARY KEY,
            name TEXT
        )""")

        await pg.execute("""
        CREATE TABLE IF NOT EXISTS item_price (
            id           SERIAL PRIMARY KEY,
            item_type_id INTEGER REFERENCES item_type(id),
            serv_type_id INTEGER REFERENCES service_category(id),
            price        INTEGER
        )""")

        await pg.execute("""
        CREATE TABLE IF NOT EXISTS ordered_items (
            id           SERIAL PRIMARY KEY,
            ord_id       INTEGER REFERENCES orders(id),
            type_id      INTEGER REFERENCES item_type(id),
            serv_type_id INTEGER REFERENCES service_category(id),
            num_of_items INTEGER,
            price        INTEGER
        )""")

        await pg.execute("""
        CREATE TABLE IF NOT EXISTS other_items (
            id         SERIAL PRIMARY KEY,
            ord_id     INTEGER REFERENCES orders(id),
            item_name  TEXT,
            quantity   INTEGER,
            item_price INTEGER
        )""")

        await pg.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id         SERIAL PRIMARY KEY,
            name       TEXT,
            phone_num  TEXT,
            status     BOOLEAN DEFAULT FALSE,
            created_on TIMESTAMP
        )""")

        await pg.execute("""
        CREATE TABLE IF NOT EXISTS user_whatsapp_message (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER REFERENCES customer(id),
            message    TEXT,
            response   TEXT,
            created_on TIMESTAMP
        )""")

        # ── NEW: voice agent tables ───────────────────────────────────

        await pg.execute("""
        CREATE TABLE IF NOT EXISTS pickup_slots (
            id         SERIAL PRIMARY KEY,
            slot_date  DATE        NOT NULL,
            slot_name  VARCHAR(20) NOT NULL,
            slot_label VARCHAR(50),
            capacity   INTEGER     DEFAULT 10,
            booked     INTEGER     DEFAULT 0,
            created_at TIMESTAMP   DEFAULT NOW(),
            UNIQUE(slot_date, slot_name)
        )""")

        await pg.execute("""
        CREATE TABLE IF NOT EXISTS voice_call_log (
            id              SERIAL PRIMARY KEY,
            call_id         VARCHAR(100) UNIQUE,
            caller_phone    VARCHAR(15),
            customer_id     INTEGER REFERENCES customer(id),
            direction       VARCHAR(10),
            intent          VARCHAR(30),
            language        VARCHAR(10)  DEFAULT 'te-IN',
            order_id        INTEGER      REFERENCES orders(id),
            call_started_at TIMESTAMP    DEFAULT NOW(),
            call_ended_at   TIMESTAMP,
            duration_secs   INTEGER,
            outcome         VARCHAR(30),
            transcript_path VARCHAR(255),
            created_at      TIMESTAMP    DEFAULT NOW()
        )""")

        # Indexes for voice_call_log
        await pg.execute("CREATE INDEX IF NOT EXISTS idx_vcl_phone    ON voice_call_log(caller_phone)")
        await pg.execute("CREATE INDEX IF NOT EXISTS idx_vcl_customer ON voice_call_log(customer_id)")
        await pg.execute("CREATE INDEX IF NOT EXISTS idx_vcl_started  ON voice_call_log(call_started_at DESC)")

        print("    All tables created.")

        # ── STEP 2: Migrate data ──────────────────────────────────────

        print("\n[2/3] Migrating data...\n")

        # manager
        cur.execute("SELECT id, name, phone_num, email, password, role, pic_url, status FROM manager")
        rows = cur.fetchall()
        for r in rows:
            await pg.execute(
                """INSERT INTO manager (id, name, phone_num, email, password, role, pic_url, status)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                   ON CONFLICT DO NOTHING""",
                to_str(r['id']),
                to_str(r['name']),
                to_str(r['phone_num']),
                to_str(r['email']),
                to_str(r['password']),
                to_str(r['role']),
                to_str(r['pic_url']),
                to_str(r['status']) or 'active',
            )
        print(f"  ✓ manager            : {len(rows):>5} rows")

        # customer
        cur.execute("SELECT id, name, phone_num, address FROM customer")
        rows = cur.fetchall()
        for r in rows:
            await pg.execute(
                """INSERT INTO customer (id, name, phone_num, address)
                   VALUES ($1,$2,$3,$4)
                   ON CONFLICT DO NOTHING""",
                to_int(r['id']),
                to_str(r['name']),
                to_str(r['phone_num']),
                to_str(r['address']),
            )
        if rows:
            await pg.execute("SELECT setval('customer_id_seq', (SELECT MAX(id) FROM customer))")
        print(f"  ✓ customer           : {len(rows):>5} rows")

        # orders
        cur.execute("""
            SELECT id, cust_id, mng_id, total_price, discount, other_charges,
                   recieved_on, delivered_on, status, pmt_status, ready_to_deliver
            FROM orders
        """)
        rows = cur.fetchall()
        for r in rows:
            await pg.execute(
                """INSERT INTO orders
                   (id, cust_id, mng_id, total_price, discount, other_charges,
                    recieved_on, delivered_on, status, pmt_status, ready_to_deliver)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                   ON CONFLICT DO NOTHING""",
                to_int(r['id']),
                to_int(r['cust_id']),
                to_str(r['mng_id']),
                to_int(r['total_price']) or 0,
                to_int(r['discount']) or 0,
                to_int(r['other_charges']) or 0,
                parse_dt(r['recieved_on']),
                parse_dt(r['delivered_on']),
                to_bool(r['status']),
                to_str(r['pmt_status']) or 'not paid',
                to_bool(r['ready_to_deliver']),
            )
        if rows:
            await pg.execute("SELECT setval('orders_id_seq', (SELECT MAX(id) FROM orders))")
        print(f"  ✓ orders             : {len(rows):>5} rows")

        # item_categories
        cur.execute("SELECT id, name, description, url FROM item_categories")
        rows = cur.fetchall()
        for r in rows:
            await pg.execute(
                """INSERT INTO item_categories (id, name, description, url)
                   VALUES ($1,$2,$3,$4)
                   ON CONFLICT DO NOTHING""",
                to_int(r['id']),
                to_str(r['name']),
                to_str(r['description']),
                to_str(r['url']),
            )
        if rows:
            await pg.execute("SELECT setval('item_categories_id_seq', (SELECT MAX(id) FROM item_categories))")
        print(f"  ✓ item_categories    : {len(rows):>5} rows")

        # item_type
        cur.execute("SELECT id, it_cat_id, name FROM item_type")
        rows = cur.fetchall()
        for r in rows:
            await pg.execute(
                """INSERT INTO item_type (id, it_cat_id, name)
                   VALUES ($1,$2,$3)
                   ON CONFLICT DO NOTHING""",
                to_int(r['id']),
                to_int(r['it_cat_id']),
                to_str(r['name']),
            )
        if rows:
            await pg.execute("SELECT setval('item_type_id_seq', (SELECT MAX(id) FROM item_type))")
        print(f"  ✓ item_type          : {len(rows):>5} rows")

        # service_category
        cur.execute("SELECT id, name FROM service_category")
        rows = cur.fetchall()
        for r in rows:
            await pg.execute(
                """INSERT INTO service_category (id, name)
                   VALUES ($1,$2)
                   ON CONFLICT DO NOTHING""",
                to_int(r['id']),
                to_str(r['name']),
            )
        if rows:
            await pg.execute("SELECT setval('service_category_id_seq', (SELECT MAX(id) FROM service_category))")
        print(f"  ✓ service_category   : {len(rows):>5} rows")

        # item_price
        cur.execute("SELECT id, item_type_id, serv_type_id, price FROM item_price")
        rows = cur.fetchall()
        for r in rows:
            await pg.execute(
                """INSERT INTO item_price (id, item_type_id, serv_type_id, price)
                   VALUES ($1,$2,$3,$4)
                   ON CONFLICT DO NOTHING""",
                to_int(r['id']),
                to_int(r['item_type_id']),
                to_int(r['serv_type_id']),
                to_int(r['price']),
            )
        if rows:
            await pg.execute("SELECT setval('item_price_id_seq', (SELECT MAX(id) FROM item_price))")
        print(f"  ✓ item_price         : {len(rows):>5} rows")

        # ordered_items
        cur.execute("SELECT id, ord_id, type_id, serv_type_id, num_of_items, price FROM ordered_items")
        rows = cur.fetchall()
        for r in rows:
            await pg.execute(
                """INSERT INTO ordered_items (id, ord_id, type_id, serv_type_id, num_of_items, price)
                   VALUES ($1,$2,$3,$4,$5,$6)
                   ON CONFLICT DO NOTHING""",
                to_int(r['id']),
                to_int(r['ord_id']),
                to_int(r['type_id']),
                to_int(r['serv_type_id']),
                to_int(r['num_of_items']),
                to_int(r['price']),
            )
        if rows:
            await pg.execute("SELECT setval('ordered_items_id_seq', (SELECT MAX(id) FROM ordered_items))")
        print(f"  ✓ ordered_items      : {len(rows):>5} rows")

        # other_items
        cur.execute("SELECT id, ord_id, item_name, quantity, item_price FROM other_items")
        rows = cur.fetchall()
        for r in rows:
            await pg.execute(
                """INSERT INTO other_items (id, ord_id, item_name, quantity, item_price)
                   VALUES ($1,$2,$3,$4,$5)
                   ON CONFLICT DO NOTHING""",
                to_int(r['id']),
                to_int(r['ord_id']),
                to_str(r['item_name']),
                to_int(r['quantity']),
                to_int(r['item_price']),
            )
        if rows:
            await pg.execute("SELECT setval('other_items_id_seq', (SELECT MAX(id) FROM other_items))")
        print(f"  ✓ other_items        : {len(rows):>5} rows")

        # payments
        cur.execute("SELECT id, ord_id, paid_to, paid_amt, paid_on FROM payments")
        rows = cur.fetchall()
        for r in rows:
            await pg.execute(
                """INSERT INTO payments (id, ord_id, paid_to, paid_amt, paid_on)
                   VALUES ($1,$2,$3,$4,$5)
                   ON CONFLICT DO NOTHING""",
                to_int(r['id']),
                to_int(r['ord_id']),
                to_str(r['paid_to']),
                to_float(r['paid_amt']),
                parse_dt(r['paid_on']),
            )
        if rows:
            await pg.execute("SELECT setval('payments_id_seq', (SELECT MAX(id) FROM payments))")
        print(f"  ✓ payments           : {len(rows):>5} rows")

        # notifications
        cur.execute("SELECT id, name, phone_num, status, created_on FROM notifications")
        rows = cur.fetchall()
        for r in rows:
            await pg.execute(
                """INSERT INTO notifications (id, name, phone_num, status, created_on)
                   VALUES ($1,$2,$3,$4,$5)
                   ON CONFLICT DO NOTHING""",
                to_int(r['id']),
                to_str(r['name']),
                to_str(r['phone_num']),
                to_bool(r['status']),
                parse_dt(r['created_on']),
            )
        if rows:
            await pg.execute("SELECT setval('notifications_id_seq', (SELECT MAX(id) FROM notifications))")
        print(f"  ✓ notifications      : {len(rows):>5} rows")

        # user_whatsapp_message
        cur.execute("SELECT id, user_id, message, response, created_on FROM user_whatsapp_message")
        rows = cur.fetchall()
        for r in rows:
            await pg.execute(
                """INSERT INTO user_whatsapp_message (id, user_id, message, response, created_on)
                   VALUES ($1,$2,$3,$4,$5)
                   ON CONFLICT DO NOTHING""",
                to_int(r['id']),
                to_int(r['user_id']),
                to_str(r['message']),
                to_str(r['response']),
                parse_dt(r['created_on']),
            )
        if rows:
            await pg.execute("SELECT setval('user_whatsapp_message_id_seq', (SELECT MAX(id) FROM user_whatsapp_message))")
        print(f"  ✓ user_whatsapp_msg  : {len(rows):>5} rows")

        # ── STEP 3: Seed new tables ───────────────────────────────────

        print("\n[3/3] Seeding new voice agent tables...")

        # Seed pickup_slots — next 7 days × 3 slots
        await pg.execute("""
        INSERT INTO pickup_slots (slot_date, slot_name, slot_label, capacity)
        SELECT
            CURRENT_DATE + i,
            slot_name,
            slot_label,
            10
        FROM generate_series(0, 6) AS i,
        (VALUES
            ('morning',   '8:00 AM - 11:00 AM'),
            ('afternoon', '12:00 PM - 3:00 PM'),
            ('evening',   '4:00 PM - 7:00 PM')
        ) AS s(slot_name, slot_label)
        ON CONFLICT (slot_date, slot_name) DO NOTHING
        """)
        print("  ✓ pickup_slots       :    21 rows (7 days × 3 slots)")
        print("  ✓ voice_call_log     :     0 rows (fills during calls)")

        # ── Final verification ────────────────────────────────────────

        print("\n" + "=" * 60)
        print("VERIFICATION — Row counts in PostgreSQL")
        print("=" * 60)

        counts = await pg.fetch("""
        SELECT
            (SELECT COUNT(*) FROM manager)               AS manager,
            (SELECT COUNT(*) FROM customer)              AS customer,
            (SELECT COUNT(*) FROM orders)                AS orders,
            (SELECT COUNT(*) FROM item_categories)       AS item_categories,
            (SELECT COUNT(*) FROM item_type)             AS item_type,
            (SELECT COUNT(*) FROM service_category)      AS service_category,
            (SELECT COUNT(*) FROM item_price)            AS item_price,
            (SELECT COUNT(*) FROM ordered_items)         AS ordered_items,
            (SELECT COUNT(*) FROM other_items)           AS other_items,
            (SELECT COUNT(*) FROM payments)              AS payments,
            (SELECT COUNT(*) FROM notifications)         AS notifications,
            (SELECT COUNT(*) FROM user_whatsapp_message) AS user_whatsapp_message,
            (SELECT COUNT(*) FROM pickup_slots)          AS pickup_slots,
            (SELECT COUNT(*) FROM voice_call_log)        AS voice_call_log
        """)

        row = counts[0]
        for col in row.keys():
            print(f"  {col:<30}: {row[col]}")

        print("\n" + "=" * 60)
        print("Migration complete! DB is ready for voice agent.")
        print("=" * 60)

        # Quick sanity — show 1 real order with bill
        print("\nSample order check (most recent):")
        sample = await pg.fetchrow("""
        SELECT
            o.id,
            c.name AS customer,
            c.phone_num,
            o.total_price,
            o.discount,
            o.other_charges,
            (COALESCE(o.total_price,0) - COALESCE(o.discount,0) + COALESCE(o.other_charges,0)) AS bill,
            o.status,
            o.pmt_status
        FROM orders o
        JOIN customer c ON o.cust_id = c.id
        ORDER BY o.recieved_on DESC
        LIMIT 1
        """)
        if sample:
            print(f"  Order #{sample['id']} | {sample['customer']} | Bill: ₹{sample['bill']} | {sample['pmt_status']}")
        else:
            print("  No orders found — check migration above for errors.")

    sqlite_conn.close()
    await pg_pool.close()


if __name__ == "__main__":
    asyncio.run(migrate())