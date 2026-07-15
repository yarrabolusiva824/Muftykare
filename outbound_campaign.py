"""
outbound_campaign.py — MuftyKare outbound dry cleaning prospecting dialer.

Dispatches muftykare-agent into a fresh room with prospecting metadata, then
dials the customer into that room via the configured SIP outbound trunk.
agent.py's entrypoint reads the dispatch metadata (call_type=dry_cleaning_promo)
to start OutboundAgent with the customer's dry-cleaning history/context.

Usage:
    # Single call
    python outbound_campaign.py --phone +919XXXXXXXXX --name "Customer Name"

    # From CSV (columns: phone, name)
    python outbound_campaign.py --csv customers.csv

    # Dry run (show who would be called, no actual calls)
    python outbound_campaign.py --csv customers.csv --dry-run
"""
import asyncio
import argparse
import csv
import json
import time
from dotenv import load_dotenv
load_dotenv()

from livekit import api
from config.settings import AGENT_NAME, SIP_OUTBOUND_TRUNK_ID
from config.constants import CALL_TYPE_PROSPECTING

DELAY_BETWEEN_CALLS_SECS = 30   # wait 30 seconds between each dial
DISPATCH_SETTLE_SECS = 3        # brief pause for agent to initialize before dialing


async def dial_customer(phone: str, name: str, dry_run: bool = False) -> None:
    """Dispatch agent and dial one customer."""
    room_name = f"outbound-prospect-{int(time.time())}"

    print(f"[CALLING] {name} — {phone} — room: {room_name}")

    if dry_run:
        print(f"  [DRY RUN] Would call {phone}")
        return

    if not SIP_OUTBOUND_TRUNK_ID:
        print("  [ERROR] SIP_OUTBOUND_TRUNK_ID is not configured — cannot dial.")
        return

    lk = api.LiveKitAPI()

    try:
        # Step 1 — dispatch agent to room with prospecting metadata
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=AGENT_NAME,
                room=room_name,
                metadata=json.dumps({
                    "call_type": CALL_TYPE_PROSPECTING,
                    "customer_phone": phone,
                    "customer_name": name,
                    "campaign": CALL_TYPE_PROSPECTING,
                }),
            )
        )
        print(f"  [AGENT] Dispatched to room {room_name}")

        # Brief pause for agent to initialize
        await asyncio.sleep(DISPATCH_SETTLE_SECS)

        # Step 2 — dial the customer via SIP outbound trunk
        await lk.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                sip_trunk_id=SIP_OUTBOUND_TRUNK_ID,
                sip_call_to=phone,
                room_name=room_name,
                participant_identity=phone,
                participant_name=name,
                wait_until_answered=False,
            )
        )
        print(f"  [SIP] Dialing {phone}")

    except Exception as e:
        print(f"  [ERROR] Failed to call {phone}: {e}")
    finally:
        await lk.aclose()


async def run_campaign(calls: list[dict], dry_run: bool = False) -> None:
    """Run through a list of calls with delay between each."""
    total = len(calls)
    print(f"\n{'[DRY RUN] ' if dry_run else ''}Starting campaign — {total} customers\n")

    for i, call in enumerate(calls, 1):
        phone = call["phone"].strip()
        name = call["name"].strip()

        print(f"[{i}/{total}] ", end="")
        await dial_customer(phone, name, dry_run=dry_run)

        if i < total:
            print(f"  Waiting {DELAY_BETWEEN_CALLS_SECS}s before next call...\n")
            if not dry_run:
                await asyncio.sleep(DELAY_BETWEEN_CALLS_SECS)

    print(f"\nCampaign complete — {total} calls {'simulated' if dry_run else 'placed'}.")


def parse_args():
    parser = argparse.ArgumentParser(description="MuftyKare outbound campaign dialer")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--phone", help="Single phone number to call (E.164 format)")
    group.add_argument("--csv", help="CSV file with columns: phone, name")
    parser.add_argument("--name", help="Customer name (required with --phone)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without making calls")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.phone:
        if not args.name:
            print("Error: --name is required with --phone")
            return
        calls = [{"phone": args.phone, "name": args.name}]

    else:
        calls = []
        with open(args.csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("phone") and row.get("name"):
                    calls.append({"phone": row["phone"], "name": row["name"]})
        if not calls:
            print("Error: CSV must have 'phone' and 'name' columns with data")
            return

    asyncio.run(run_campaign(calls, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
