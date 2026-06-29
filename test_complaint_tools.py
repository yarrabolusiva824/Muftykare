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

# Import the tools we want to test
from tools.customer import save_new_customer
from tools.booking import create_booking
from tools.complaint import log_complaint
from config.constants import SERVICE_WASH_FOLD

class MockContext:
    """A simple mock context to mimic LiveKit's RunContext."""
    def __init__(self, userdata):
        self.userdata = userdata

async def test_complaint_tools():
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
            res_user = await save_new_customer(ctx, name="Complaint Test User", phone=phone_to_test, address="Hyderabad Test Address")
        except TypeError:
            res_user = await save_new_customer.func(ctx, name="Complaint Test User", phone=phone_to_test, address="Hyderabad Test Address")
        print("Result:", res_user)
        print("Customer ID set in userdata:", ctx.userdata.customer_id)
    except Exception as e:
        print("Error:", e)
        
    print("\n--- 0.5. Setup: Creating a booking for testing complaint ---")
    try:
        from tools.booking import check_slot_availability
        from datetime import date, timedelta
        
        # Find next Monday
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
            res_booking = await create_booking(ctx, service_type=SERVICE_WASH_FOLD, pickup_address="Hyderabad Test Address", confirmed=True)
        except TypeError:
            res_booking = await create_booking.func(ctx, service_type=SERVICE_WASH_FOLD, pickup_address="Hyderabad Test Address", confirmed=True)
            
        print("Result:", res_booking)
        print("Order ID set in userdata:", ctx.userdata.current_order_id)
    except Exception as e:
        print("Error:", e)

        
    print(f"Using current_order_id: {ctx.userdata.current_order_id}")

    print("\n--- 1. Testing log_complaint (Low Severity) ---")
    try:
        try:
            res1 = await log_complaint(
                ctx, 
                complaint_type="stain", 
                description="Stain not removed from shirt", 
                severity="low"
            )
        except TypeError:
            res1 = await log_complaint.func(
                ctx, 
                complaint_type="stain", 
                description="Stain not removed from shirt", 
                severity="low"
            )
        print("Result:", res1)
        print("Outcome set in userdata:", getattr(ctx.userdata, 'outcome', None))
    except Exception as e:
        print("Error:", e)

    print("\n--- 2. Testing log_complaint (Medium Severity) ---")
    try:
        try:
            res2 = await log_complaint(
                ctx, 
                complaint_type="late_delivery", 
                description="Delivery delayed by 3 days", 
                severity="medium"
            )
        except TypeError:
            res2 = await log_complaint.func(
                ctx, 
                complaint_type="late_delivery", 
                description="Delivery delayed by 3 days", 
                severity="medium"
            )
        print("Result:", res2)
        print("Outcome set in userdata:", getattr(ctx.userdata, 'outcome', None))
    except Exception as e:
        print("Error:", e)

    print("\n--- 3. Testing log_complaint (Critical Severity) ---")
    try:
        try:
            res3 = await log_complaint(
                ctx, 
                complaint_type="damaged", 
                description="Shirt fabric torn", 
                severity="critical"
            )
        except TypeError:
            res3 = await log_complaint.func(
                ctx, 
                complaint_type="damaged", 
                description="Shirt fabric torn", 
                severity="critical"
            )
        print("Result:", res3)
        print("Outcome set in userdata:", getattr(ctx.userdata, 'outcome', None))
    except Exception as e:
        print("Error:", e)

    print("\nClosing Database Pool...")
    await close_pool()

if __name__ == "__main__":
    asyncio.run(test_complaint_tools())
