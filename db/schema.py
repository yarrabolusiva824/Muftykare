"""
db/schema.py — MuftyKare Database Schema Reference
===================================================
Single source of truth for:
  - Table definitions (for documentation and asyncpg query building)
  - Column descriptions (for LLM context and tool docstrings)
  - Key relationships (for JOIN query construction)
  - Business rules embedded in schema (status values, bill formula)

This file is NEVER executed — it is imported as a reference by:
  - db/queries.py       → knows which columns to SELECT
  - tools/*.py          → knows what data to pass/return
  - prompts.py          → DB_SCHEMA string injected into system prompt
  - agent tests         → validates tool return shapes

Author: MuftyKare Voice Agent
"""

# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA STRING — injected into GPT-4o system prompt
# Keep this in sync with actual PostgreSQL tables
# ─────────────────────────────────────────────────────────────────────────────

DB_SCHEMA = """
customer (
    id          INTEGER PRIMARY KEY,
    name        TEXT,
    phone_num   TEXT    -- stored as plain 10-digit string e.g. "9876543210"
                        -- normalize: strip +91 prefix, use last 10 digits
    address     TEXT    -- full address string
)

orders (
    id               INTEGER PRIMARY KEY,
    cust_id          INTEGER → customer.id,
    mng_id           TEXT    → manager.id,
    total_price      INTEGER,          -- item total in ₹ before discount
    discount         INTEGER,          -- discount amount in ₹
    other_charges    INTEGER,          -- delivery / packaging charges in ₹
    recieved_on      TIMESTAMP,        -- when order was received (NOTE: typo in original — "recieved")
    delivered_on     TIMESTAMP,        -- actual delivery timestamp (NULL if not delivered)
    status           BOOLEAN,          -- FALSE = not delivered, TRUE = delivered
    pmt_status       TEXT,             -- 'not paid' | 'paid' | 'semi-paid'
    ready_to_deliver BOOLEAN           -- FALSE = not ready, TRUE = ready for delivery
)

-- BILL FORMULA (always use this):
-- final_bill = COALESCE(total_price, 0) - COALESCE(discount, 0) + COALESCE(other_charges, 0)

item_categories (
    id          INTEGER PRIMARY KEY,
    name        TEXT,   -- e.g. "Saree", "Shirt", "Blazer"
    description TEXT,
    url         TEXT
)

item_type (
    id        INTEGER PRIMARY KEY,
    it_cat_id INTEGER → item_categories.id,
    name      TEXT    -- e.g. "Cotton", "Silk", "Wool"
)

service_category (
    id   INTEGER PRIMARY KEY,
    name TEXT    -- e.g. "Dry Clean", "Steam Iron", "Laundry"
)

item_price (
    id           INTEGER PRIMARY KEY,
    item_type_id INTEGER → item_type.id,
    serv_type_id INTEGER → service_category.id,
    price        INTEGER  -- price in ₹ per item
)

ordered_items (
    id           INTEGER PRIMARY KEY,
    ord_id       INTEGER → orders.id,
    type_id      INTEGER → item_type.id,
    serv_type_id INTEGER → service_category.id,
    num_of_items INTEGER,
    price        INTEGER  -- total price for this line item
)

other_items (
    id         INTEGER PRIMARY KEY,
    ord_id     INTEGER → orders.id,
    item_name  TEXT,    -- free-text item name
    quantity   INTEGER,
    item_price INTEGER  -- price per item
)

payments (
    id       INTEGER PRIMARY KEY,
    ord_id   INTEGER → orders.id,
    paid_to  TEXT    → manager.id,
    paid_amt FLOAT,  -- amount paid in ₹
    paid_on  TIMESTAMP
)

manager (
    id        TEXT PRIMARY KEY,
    name      TEXT,
    phone_num TEXT,
    email     TEXT,
    role      TEXT,
    status    TEXT  -- 'active' | 'inactive'
)

notifications (
    id         INTEGER PRIMARY KEY,
    name       TEXT,
    phone_num  TEXT,
    status     BOOLEAN,   -- FALSE = unread, TRUE = read
    created_on TIMESTAMP
)

user_whatsapp_message (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER → customer.id,
    message    TEXT,      -- customer's WhatsApp message
    response   TEXT,      -- bot's response
    created_on TIMESTAMP
)

-- NEW: Voice agent tables (not in original WhatsApp system)

pickup_slots (
    id         INTEGER PRIMARY KEY,
    slot_date  DATE,
    slot_name  TEXT,   -- 'morning' | 'afternoon' | 'evening'
    slot_label TEXT,   -- '8:00 AM - 11:00 AM' | '12:00 PM - 3:00 PM' | '4:00 PM - 7:00 PM'
    capacity   INTEGER DEFAULT 10,
    booked     INTEGER DEFAULT 0
    -- available = capacity - booked
)

voice_call_log (
    id              INTEGER PRIMARY KEY,
    call_id         TEXT,       -- LiveKit room name
    caller_phone    TEXT,       -- last 4 digits only (PII masked)
    customer_id     INTEGER → customer.id,
    direction       TEXT,       -- 'inbound' | 'outbound'
    intent          TEXT,       -- 'booking' | 'status_check' | 'billing' | 'complaint' | 'unknown'
    language        TEXT,       -- 'te-IN' | 'en-IN' | 'hi-IN'
    order_id        INTEGER → orders.id,
    call_started_at TIMESTAMP,
    call_ended_at   TIMESTAMP,
    duration_secs   INTEGER,
    outcome         TEXT,       -- 'booking_created' | 'status_provided' | 'escalated' | 'no_action'
    transcript_path TEXT        -- path to daily log file for this call
)

call_recordings (
    id              INTEGER PRIMARY KEY,
    call_id         TEXT,
    customer_id     INTEGER → customer.id,
    caller_phone    TEXT,
    egress_id       TEXT UNIQUE,
    file_path       TEXT,
    file_size_bytes BIGINT,
    duration_secs   INTEGER,
    recorded_at     TIMESTAMPTZ,
    call_log_id     INTEGER → voice_call_log.id
)
"""

# ─────────────────────────────────────────────────────────────────────────────
# TABLE METADATA — used by tools and query builders
# ─────────────────────────────────────────────────────────────────────────────

TABLES = {
    "customer": {
        "pk": "id",
        "lookup_by": "phone_num",
        "columns": ["id", "name", "phone_num", "address"],
        "notes": "Phone stored as 10-digit string. Always normalize: strip +91, take last 10 digits.",
    },
    "orders": {
        "pk": "id",
        "fk": {"cust_id": "customer.id", "mng_id": "manager.id"},
        "columns": [
            "id", "cust_id", "mng_id", "total_price", "discount",
            "other_charges", "recieved_on", "delivered_on",
            "status", "pmt_status", "ready_to_deliver",
        ],
        "status_values": {
            "status": {False: "not delivered", True: "delivered"},
            "pmt_status": ["not paid", "paid", "semi-paid"],
            "ready_to_deliver": {False: "not ready", True: "ready for pickup"},
        },
        "bill_formula": "COALESCE(total_price,0) - COALESCE(discount,0) + COALESCE(other_charges,0)",
        "notes": "NOTE: column is 'recieved_on' (typo in original schema — do not correct in queries).",
    },
    "ordered_items": {
        "pk": "id",
        "fk": {
            "ord_id": "orders.id",
            "type_id": "item_type.id",
            "serv_type_id": "service_category.id",
        },
        "columns": ["id", "ord_id", "type_id", "serv_type_id", "num_of_items", "price"],
        "notes": "Join with item_type and item_categories to get readable names.",
    },
    "other_items": {
        "pk": "id",
        "fk": {"ord_id": "orders.id"},
        "columns": ["id", "ord_id", "item_name", "quantity", "item_price"],
        "notes": "Free-text items not in item_type catalog. Always UNION with ordered_items for full order.",
    },
    "item_categories": {
        "pk": "id",
        "columns": ["id", "name", "description", "url"],
        "notes": "Top-level category e.g. Saree, Shirt, Blazer. Has 56 rows.",
    },
    "item_type": {
        "pk": "id",
        "fk": {"it_cat_id": "item_categories.id"},
        "columns": ["id", "it_cat_id", "name"],
        "notes": "Sub-type e.g. Cotton, Silk, Wool. Has 92 rows.",
    },
    "service_category": {
        "pk": "id",
        "columns": ["id", "name"],
        "notes": "Only 3 rows — Dry Clean, Steam Iron, Laundry.",
    },
    "item_price": {
        "pk": "id",
        "fk": {"item_type_id": "item_type.id", "serv_type_id": "service_category.id"},
        "columns": ["id", "item_type_id", "serv_type_id", "price"],
        "notes": "Price lookup: item_type × service_category. Has 226 rows.",
    },
    "payments": {
        "pk": "id",
        "fk": {"ord_id": "orders.id", "paid_to": "manager.id"},
        "columns": ["id", "ord_id", "paid_to", "paid_amt", "paid_on"],
        "notes": "Multiple payments possible per order (partial payments).",
    },
    "pickup_slots": {
        "pk": "id",
        "columns": ["id", "slot_date", "slot_name", "slot_label", "capacity", "booked"],
        "notes": "Voice agent only. Check (capacity - booked) > 0 for availability.",
    },
    "voice_call_log": {
        "pk": "id",
        "fk": {"customer_id": "customer.id", "order_id": "orders.id"},
        "columns": [
            "id", "call_id", "caller_phone", "customer_id", "direction",
            "intent", "language", "order_id", "call_started_at",
            "call_ended_at", "duration_secs", "outcome", "transcript_path",
        ],
        "notes": "Filled during every call. caller_phone stores last 4 digits only.",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# KEY QUERIES — canonical SQL used across the voice agent
# Referenced in db/queries.py — defined here for single source of truth
# ─────────────────────────────────────────────────────────────────────────────

QUERIES = {

    "lookup_customer_by_phone": """
        SELECT id, name, phone_num, address
        FROM customer
        WHERE RIGHT(COALESCE(phone_num, ''), 10) = RIGHT($1, 10)
        LIMIT 1
    """,

    "get_outbound_customer_context": """
        SELECT
            c.id,
            c.name,
            c.address,
            COUNT(o.id)                                                     AS total_orders,
            MAX(o.recieved_on)                                              AS last_order_date,
            COALESCE(SUM(CASE WHEN o.pmt_status = 'not paid'
                               THEN COALESCE(o.total_price,0) - COALESCE(o.discount,0) + COALESCE(o.other_charges,0)
                               ELSE 0 END), 0)                              AS pending_amount,
            BOOL_OR(sc.name = 'Dry Clean')                                  AS has_used_dry_cleaning
        FROM customer c
        LEFT JOIN orders o           ON o.cust_id = c.id
        LEFT JOIN ordered_items oi   ON oi.ord_id = o.id
        LEFT JOIN service_category sc ON oi.serv_type_id = sc.id
        WHERE RIGHT(COALESCE(c.phone_num, ''), 10) = RIGHT($1, 10)
        GROUP BY c.id, c.name, c.address
        LIMIT 1
    """,

    "get_latest_order": """
        SELECT
            o.id,
            o.total_price,
            o.discount,
            o.other_charges,
            (COALESCE(o.total_price,0)
             - COALESCE(o.discount,0)
             + COALESCE(o.other_charges,0))     AS bill,
            o.status,
            o.ready_to_deliver,
            o.pmt_status,
            o.recieved_on,
            o.delivered_on
        FROM orders o
        WHERE o.cust_id = $1
        ORDER BY o.recieved_on DESC, o.id DESC
        LIMIT 1
    """,

    "get_order_items": """
        SELECT
            ic.name          AS category,
            it.name          AS item_type,
            sc.name          AS service,
            oi.num_of_items,
            oi.price
        FROM ordered_items oi
        JOIN item_type it        ON oi.type_id      = it.id
        JOIN item_categories ic  ON it.it_cat_id    = ic.id
        JOIN service_category sc ON oi.serv_type_id = sc.id
        WHERE oi.ord_id = $1

        UNION ALL

        SELECT
            'Other'          AS category,
            o2.item_name     AS item_type,
            'Custom'         AS service,
            o2.quantity      AS num_of_items,
            o2.item_price    AS price
        FROM other_items o2
        WHERE o2.ord_id = $1
    """,

    "get_delivery_status": """
        SELECT
            o.id,
            o.status             AS is_delivered,
            o.ready_to_deliver,
            o.delivered_on,
            o.pmt_status,
            o.recieved_on
        FROM orders o
        WHERE o.cust_id = $1
        ORDER BY o.recieved_on DESC, o.id DESC
        LIMIT 1
    """,

    "check_slot_availability": """
        SELECT
            slot_name,
            slot_label,
            capacity,
            booked,
            (capacity - booked) AS remaining
        FROM pickup_slots
        WHERE slot_date = $1
          AND (capacity - booked) > 0
        ORDER BY
            CASE slot_name
                WHEN 'morning'   THEN 1
                WHEN 'afternoon' THEN 2
                WHEN 'evening'   THEN 3
            END
    """,

    "create_order": """
        INSERT INTO orders
            (cust_id, total_price, discount, other_charges,
             status, pmt_status, ready_to_deliver, recieved_on)
        VALUES ($1, 0, 0, 0, FALSE, 'not paid', FALSE, NOW())
        RETURNING id
    """,

    "increment_slot_booked": """
        UPDATE pickup_slots
        SET booked = booked + 1
        WHERE slot_date = $1 AND slot_name = $2
    """,

    "insert_customer": """
        INSERT INTO customer (name, phone_num, address)
        VALUES ($1, $2, $3)
        RETURNING id
    """,

    "log_call_start": """
        INSERT INTO voice_call_log
            (call_id, caller_phone, customer_id, direction, language, call_started_at)
        VALUES ($1, $2, $3, $4, $5, NOW())
        RETURNING id
    """,

    "log_call_end": """
        UPDATE voice_call_log
        SET
            call_ended_at   = NOW(),
            duration_secs   = EXTRACT(EPOCH FROM (NOW() - call_started_at))::INTEGER,
            intent          = $2,
            order_id        = $3,
            outcome         = $4,
            transcript_path = $5
        WHERE call_id = $1
    """,
}

# ─────────────────────────────────────────────────────────────────────────────
# BUSINESS RULES — used in system prompt and tool validation
# ─────────────────────────────────────────────────────────────────────────────

BUSINESS_RULES = {
    "support_phone": "7075232425",
    "website": "muftykare.com",
    "working_hours": "Monday – Saturday, 10:00 AM – 7:00 PM",
    # TEMP: swapped for a US test location — revert to this once testing is done
    "location": (
        "Beside Vishnu Honda Balaji Hills,"
        "NH-16, Balayya Sastri Layout, Seethammadhara, "
        "Visakhapatnam"
    ),
    "maps_link": "https://maps.app.goo.gl/BmbSpo1FgXDwfaky9",
    # "location": "123 Market Street, San Francisco, CA 94103",
    # "maps_link": "https://www.google.com/maps/search/?api=1&query=123+Market+Street+San+Francisco+CA+94103",
    "service_types": {
        "EXPRESS":   "Express Service — within 12 hours",
        "DRY_CLEAN": "Dry Cleaning — within 4 days",
        "LAUNDRY":   "Laundry by Weight — within 24 hours",
    },
    "pickup_slots": {
        "morning":   "8:00 AM - 11:00 AM",
        "afternoon": "12:00 PM - 3:00 PM",
        "evening":   "4:00 PM - 7:00 PM",
    },
    "order_status_voice_responses": {
        # status=False, ready_to_deliver=False → clothes received, being cleaned
        "received":    "మీ బట్టలు మాతో ఉన్నాయి, cleaning జరుగుతోంది",
        # status=False, ready_to_deliver=True → ready, not yet delivered
        "ready":       "మీ బట్టలు ready అయ్యాయి, delivery కి వెళ్తున్నాయి",
        # status=True → delivered
        "delivered":   "మీ బట్టలు deliver అయ్యాయి",
        # pmt_status
        "not_paid":    "payment pending ఉంది",
        "paid":        "payment complete అయింది",
        "semi_paid":   "partial payment మాత్రమే జరిగింది",
    },
    "order_status_voice_responses_en": {
        "received":    "your clothes are with us, cleaning is in progress",
        "ready":       "your clothes are ready and are on their way for delivery",
        "delivered":   "your clothes have been delivered",
        "not_paid":    "payment is still pending",
        "paid":        "payment is complete",
        "semi_paid":   "only partial payment has been made",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# STATS (from migration — for reference)
# ─────────────────────────────────────────────────────────────────────────────

DB_STATS = {
    "manager":               3,
    "customer":              695,
    "orders":                1659,
    "item_categories":       56,
    "item_type":             92,
    "service_category":      3,
    "item_price":            226,
    "ordered_items":         2392,
    "other_items":           2786,
    "payments":              234,
    "notifications":         9,
    "user_whatsapp_message": 455,
    "pickup_slots":          21,
    "voice_call_log":        0,
}
