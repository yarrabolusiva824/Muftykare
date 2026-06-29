import asyncio
import sys
import uuid

# Force UTF-8 encoding for Windows consoles to support the ₹ symbol
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

from db.connection import get_pool, close_pool
from userdata import MuftyKareUserData

# Import tools for testing
from tools.customer import save_new_customer
from tools.booking import create_booking, check_slot_availability
from tools.status import get_order_status
from config.constants import SERVICE_WASH_FOLD
from datetime import date, timedelta

class MockContext:
    """A simple mock context to mimic LiveKit's RunContext."""
    def __init__(self, userdata):
        self.userdata = userdata

async def test_status_tools():
    print("Initializing Database Pool...")
    pool = await get_pool()
    
    # Setup UserData with a test phone number
    phone_to_test = "9381891509"
    call_id_test = f"test_status_{uuid.uuid4().hex[:8]}"
    userdata = MuftyKareUserData(
        db_pool=pool,
        call_id=call_id_test,
        call_direction="inbound",
        caller_phone=phone_to_test,
        language="te-IN"
    )
    
    ctx = MockContext(userdata)
    
    print(f"\n--- 0. Setup: Creating/Fetching User & Booking for {phone_to_test} ---")
    try:
        try:
            res_user = await save_new_customer(ctx, name="Status Test User", phone=phone_to_test, address="Hyderabad Test Address")
        except TypeError:
            res_user = await save_new_customer.func(ctx, name="Status Test User", phone=phone_to_test, address="Hyderabad Test Address")
        print("User Result:", res_user)
        print("Customer ID set in userdata:", ctx.userdata.customer_id)
        
        # We need an order to test status. Let's create one.
        today = date.today()
        days_ahead = 0 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        next_monday = (today + timedelta(days=days_ahead)).isoformat()
        
        try:
            await check_slot_availability(ctx, slot_date=next_monday, time_preference="11 AM")
        except TypeError:
            await check_slot_availability.func(ctx, slot_date=next_monday, time_preference="11 AM")
            
        try:
            res_booking = await create_booking(
                ctx, 
                service_type=SERVICE_WASH_FOLD, 
                pickup_address="123 Test St, Hyderabad", 
                confirmed=True
            )
        except TypeError:
            res_booking = await create_booking.func(
                ctx, 
                service_type=SERVICE_WASH_FOLD, 
                pickup_address="123 Test St, Hyderabad", 
                confirmed=True
            )
        print("Booking Result:", res_booking)
    except Exception as e:
        print("Setup Error:", e)
        
    print("\n--- 1. Testing get_order_status (Valid Customer) ---")
    try:
        try:
            res_status = await get_order_status(ctx)
        except TypeError:
            res_status = await get_order_status.func(ctx)
        print("Result:", res_status)
    except Exception as e:
        print("Error:", e)

    print("\n--- 2. Testing get_order_status (No Customer ID) ---")
    try:
        # Create a new context without customer ID
        no_cust_ctx = MockContext(MuftyKareUserData(db_pool=pool, call_id="test", call_direction="inbound", caller_phone="0000000000", language="te-IN"))
        try:
            res_status_empty = await get_order_status(no_cust_ctx)
        except TypeError:
            res_status_empty = await get_order_status.func(no_cust_ctx)
        print("Result:", res_status_empty)
    except Exception as e:
        print("Error:", e)

    print("\nClosing Database Pool...")
    await close_pool()

if __name__ == "__main__":
    asyncio.run(test_status_tools())
