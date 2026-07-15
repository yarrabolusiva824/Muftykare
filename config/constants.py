"""
config/constants.py — All string constants for MuftyKare voice agent.
Import from here instead of hardcoding strings anywhere.
"""
from config.settings import AGENT_LANGUAGE

_IS_ENGLISH = AGENT_LANGUAGE == "en-IN"

# ── SIP participant attribute keys ─────────────────────────────────────────
SIP_ATTR_PHONE          = "sip.phoneNumber"      # caller's phone number
SIP_ATTR_CALL_ID        = "sip.callID"           # LiveKit unique call ID
SIP_ATTR_CALL_STATUS    = "sip.callStatus"       # active / dialing / ringing / hangup
SIP_ATTR_TRUNK_ID       = "sip.trunkID"          # which trunk the call came through
SIP_ATTR_TRUNK_PHONE    = "sip.trunkPhoneNumber" # MuftyKare's number that was dialled
SIP_CALL_STATUS_ACTIVE  = "active"

# ── Call direction ─────────────────────────────────────────────────────────
DIRECTION_INBOUND   = "inbound"
DIRECTION_OUTBOUND  = "outbound"

# ── Outbound call types (passed via FastAPI POST /call/outbound) ───────────
CALL_TYPE_REMINDER     = "reminder"            # pickup reminder 30min before slot
CALL_TYPE_DELIVERY     = "delivery"            # delivery confirmation
CALL_TYPE_PAYMENT      = "payment"             # payment reminder
CALL_TYPE_PROSPECTING  = "dry_cleaning_promo"  # outbound dry-cleaning pitch campaign

# ── Intent names (written to voice_call_log.intent) ───────────────────────
INTENT_BOOKING      = "booking"
INTENT_STATUS       = "status_check"
INTENT_BILLING      = "billing"
INTENT_COMPLAINT    = "complaint"
INTENT_INQUIRY      = "general_inquiry"
INTENT_UNKNOWN      = "unknown"

# ── Call outcomes (written to voice_call_log.outcome) ─────────────────────
OUTCOME_BOOKING_CREATED     = "booking_created"
OUTCOME_STATUS_PROVIDED     = "status_provided"
OUTCOME_ESCALATED           = "escalated"
OUTCOME_REWASH_CREATED      = "rewash_created"
OUTCOME_PAYMENT_REMINDED    = "payment_reminded"
OUTCOME_NO_ACTION           = "no_action"
OUTCOME_MISSED              = "missed"
OUTCOME_WRONG_NUMBER        = "wrong_number"

# ── Campaign outcomes (prospecting calls, written to voice_call_log.outcome) ─
OUTCOME_BOOKED               = "booked"
OUTCOME_INTERESTED           = "interested"
OUTCOME_NOT_INTERESTED       = "not_interested"
OUTCOME_BUSY                 = "busy"
OUTCOME_EXISTING_QUERY       = "existing_query"

# ── Pickup slot names ──────────────────────────────────────────────────────
SLOT_MORNING    = "morning"
SLOT_AFTERNOON  = "afternoon"
SLOT_EVENING    = "evening"

SLOT_LABELS = {
    SLOT_MORNING:   "8:00 AM - 11:00 AM",
    SLOT_AFTERNOON: "12:00 PM - 3:00 PM",
    SLOT_EVENING:   "4:00 PM - 7:00 PM",
}

# ── Service types ──────────────────────────────────────────────────────────
SERVICE_WASH_FOLD   = "WASH_FOLD"
SERVICE_DRY_CLEAN   = "DRY_CLEAN"
SERVICE_EXPRESS     = "EXPRESS"
SERVICE_SHOE_CLEAN  = "SHOE_CLEAN"

SERVICE_LABELS = {
    SERVICE_WASH_FOLD:  "Normal Wash",
    SERVICE_DRY_CLEAN:  "Dry Cleaning",
    SERVICE_EXPRESS:    "Express Service",
    SERVICE_SHOE_CLEAN: "Shoe Cleaning",
}

# ── Order status → voice response mapping ──────────────────────────────────
# Used by StatusAgent to convert DB booleans into natural speech.
# Picked by AGENT_LANGUAGE — Telugu (default) or English.
_ORDER_STATUS_RESPONSES_TE = {
    # (status=False, ready_to_deliver=False) → being cleaned
    "cleaning":   "మీ బట్టలు cleaning లో ఉన్నాయి, కొంచెం సమయం పడుతుంది",
    # (status=False, ready_to_deliver=True) → ready, out for delivery
    "ready":      "మీ బట్టలు ready అయ్యాయి, delivery కి వెళ్తున్నాయి",
    # (status=True) → delivered
    "delivered":  "మీ బట్టలు deliver అయ్యాయి",
    # not found
    "not_found":  "మీ phone number తో ఏ order కనుగొనబడలేదు",
}

_ORDER_STATUS_RESPONSES_EN = {
    "cleaning":   "Your clothes are still being cleaned, it'll take a little more time",
    "ready":      "Your clothes are ready and are on their way for delivery",
    "delivered":  "Your clothes have been delivered",
    "not_found":  "We couldn't find any order with that phone number",
}

_PAYMENT_STATUS_RESPONSES_TE = {
    "not paid":   "payment pending ఉంది",
    "paid":       "payment complete అయింది",
    "semi-paid":  "partial payment మాత్రమే జరిగింది, మిగిలిన amount pending ఉంది",
}

_PAYMENT_STATUS_RESPONSES_EN = {
    "not paid":   "payment is still pending",
    "paid":       "payment is complete",
    "semi-paid":  "only partial payment has been made, the remaining amount is pending",
}

ORDER_STATUS_RESPONSES = _ORDER_STATUS_RESPONSES_EN if _IS_ENGLISH else _ORDER_STATUS_RESPONSES_TE
PAYMENT_STATUS_RESPONSES = _PAYMENT_STATUS_RESPONSES_EN if _IS_ENGLISH else _PAYMENT_STATUS_RESPONSES_TE

# ── Complaint severity keywords ────────────────────────────────────────────
# ComplaintAgent uses these to classify severity before routing
COMPLAINT_CRITICAL_KEYWORDS = [
    "damage", "damaged", "missing", "wrong clothes", "colour bleed",
    "color bleed", "shrink", "shrinkage", "torn",
    "damage అయింది", "పోయింది", "తప్పు బట్టలు", "రంగు పోయింది",
]

COMPLAINT_MEDIUM_KEYWORDS = [
    "rude", "late", "delay", "3 days", "3 rojulu", "not delivered",
    "raaledu", "chaaala time", "wrong number",
]

# ── Agent persona ───────────────────────────────────────────────────────────
AGENT_NAME              = "Kavya"          # spoken name used across all prompts

# ── Sarvam plugin config ────────────────────────────────────────────────────
# "kavya" is a bulbul:v3 voice that speaks both te-IN and en-IN, so only the
# target language code needs to change — the speaker/voice identity stays the same.
SARVAM_STT_MODEL        = "saaras:v3"
SARVAM_TTS_MODEL        = "bulbul:v3"
# SARVAM_TTS_SPEAKER      = "amelia"          # warm female voice, Telugu + English
SARVAM_TTS_SPEAKER      = "kavya"          # warm female voice, Telugu + English
SARVAM_LANGUAGE         = AGENT_LANGUAGE   # "te-IN" (default) or "en-IN"
SARVAM_ENDPOINTING_MS   = 0.07             # 70ms — Sarvam's processing latency

# ── LLM config ─────────────────────────────────────────────────────────────
LLM_MODEL               = "GPT-4o"
LLM_MAX_TOOL_STEPS      = 5               # max tool call chain per turn

# ── Agent names (registered in LiveKit) ────────────────────────────────────
AGENT_GREETER   = "greeter"
AGENT_BOOKING   = "booking"
AGENT_STATUS    = "status"
AGENT_COMPLAINT = "complaint"
AGENT_OUTBOUND  = "outbound"

# ── Chat context carry-over (restaurant_agent.py pattern) ─────────────────
CHAT_CTX_MAX_ITEMS = 6   # last N messages carried to next agent on handoff

# ── Background audio ────────────────────────────────────────────────────────
THINKING_AUDIO_VOLUME   = 0.6   # keyboard typing volume during tool calls
HOLD_AUDIO_VOLUME       = 0.7   # hold music during warm transfer

# ── Timeouts ───────────────────────────────────────────────────────────────
USER_AWAY_TIMEOUT_SECS  = 15.0  # silence before user_state_changed fires
OUTBOUND_MAX_RING_SECS  = 30    # give up outbound call after 30s no answer
