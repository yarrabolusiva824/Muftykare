import asyncio
import sys
from datetime import date, timedelta
import uuid

# Force UTF-8 encoding for Windows consoles to support the ₹ symbol
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

from db.connection import get_pool, close_pool
from userdata import MuftyKareUserData

# Import the tools we want to test
from tools.customer import save_new_customer
from tools.booking import (
    check_slot_availability,
    create_booking,
    reschedule_slot,
    cancel_booking
)
from config.constants import SERVICE_WASH_FOLD, SLOT_MORNING, SLOT_EVENING

class MockContext:
    """A simple mock context to mimic LiveKit's RunContext."""
    def __init__(self, userdata):
        self.userdata = userdata

async def test_tools():
    print("Initializing Database Pool...")
    pool = await get_pool()
    
    # Setup UserData with the requested phone number
    phone_to_test = "9381891509"
    call_id_test = f"test_call_{uuid.uuid4().hex[:8]}"
    userdata = MuftyKareUserData(
        db_pool=pool,
        call_id=call_id_test,
        call_direction="inbound",
        caller_phone=phone_to_test,
        language="te-IN"
    )
    
    ctx = MockContext(userdata)
    
    print(f"\n--- 0. Setup: Creating/Fetching User for {phone_to_test} ---")
    try:
        try:
            res_user = await save_new_customer(ctx, name="Booking Test User", phone=phone_to_test, address="Hyderabad Test Address")
        except TypeError:
            res_user = await save_new_customer.func(ctx, name="Booking Test User", phone=phone_to_test, address="Hyderabad Test Address")
        print("Result:", res_user)
        print("Customer ID set in userdata:", ctx.userdata.customer_id)
    except Exception as e:
        print("Error:", e)
        
    # Find next Monday and Tuesday to guarantee they are not Sundays
    today = date.today()
    days_ahead = 0 - today.weekday()
    if days_ahead <= 0: # Target is in the future
        days_ahead += 7
    next_monday = (today + timedelta(days=days_ahead)).isoformat()
    next_tuesday = (today + timedelta(days=days_ahead + 1)).isoformat()

    print(f"\n--- 1. Testing check_slot_availability for {next_monday} at 11 AM ---")
    try:
        try:
            res1 = await check_slot_availability(ctx, slot_date=next_monday, time_preference="11 AM")
        except TypeError:
            res1 = await check_slot_availability.func(ctx, slot_date=next_monday, time_preference="11 AM")
        print("Result:", res1)
    except Exception as e:
        print("Error:", e)

    print("\n--- 2. Testing create_booking (unconfirmed) ---")
    try:
        try:
            res2_unconfirmed = await create_booking(
                ctx, 
                service_type=SERVICE_WASH_FOLD, 
                pickup_address="123 Test St, Hyderabad", 
                confirmed=False
            )
        except TypeError:
            res2_unconfirmed = await create_booking.func(
                ctx, 
                service_type=SERVICE_WASH_FOLD, 
                pickup_address="123 Test St, Hyderabad", 
                confirmed=False
            )
        print("Result (unconfirmed):", res2_unconfirmed)
    except Exception as e:
        print("Error:", e)

    print("\n--- 3. Testing create_booking (confirmed) ---")
    try:
        try:
            res2 = await create_booking(
                ctx, 
                service_type=SERVICE_WASH_FOLD, 
                pickup_address="123 Test St, Hyderabad", 
                confirmed=True
            )
        except TypeError:
            res2 = await create_booking.func(
                ctx, 
                service_type=SERVICE_WASH_FOLD, 
                pickup_address="123 Test St, Hyderabad", 
                confirmed=True
            )
        print("Result (confirmed):", res2)
        print("Order ID in userdata:", ctx.userdata.current_order_id)
    except Exception as e:
        print("Error:", e)
        
    print(f"\n--- 4. Testing reschedule_slot to {next_tuesday} at 6 PM ---")
    try:
        try:
            res3 = await reschedule_slot(ctx, new_date=next_tuesday, new_time_preference="6 PM")
        except TypeError:
            res3 = await reschedule_slot.func(ctx, new_date=next_tuesday, new_time_preference="6 PM")
        print("Result:", res3)
    except Exception as e:
        print("Error:", e)
        
    print("\n--- 5. Testing cancel_booking (unconfirmed) ---")
    try:
        try:
            res4_unconfirmed = await cancel_booking(ctx, confirmed=False)
        except TypeError:
            res4_unconfirmed = await cancel_booking.func(ctx, confirmed=False)
        print("Result (unconfirmed):", res4_unconfirmed)
    except Exception as e:
        print("Error:", e)

    print("\n--- 6. Testing cancel_booking (confirmed) ---")
    try:
        try:
            res4 = await cancel_booking(ctx, confirmed=True)
        except TypeError:
            res4 = await cancel_booking.func(ctx, confirmed=True)
        print("Result (confirmed):", res4)
        print("Order ID in userdata after cancel:", ctx.userdata.current_order_id)
    except Exception as e:
        print("Error:", e)

    print("\nClosing Database Pool...")
    await close_pool()

if __name__ == "__main__":
    asyncio.run(test_tools())
