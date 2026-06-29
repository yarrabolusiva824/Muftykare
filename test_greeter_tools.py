import asyncio
import sys

# Force UTF-8 encoding for Windows consoles to support the ₹ symbol
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

from db.connection import get_pool, close_pool
from userdata import MuftyKareUserData

# Import the tools we want to test
from tools.customer import lookup_caller, lookup_customer_by_number, save_new_customer
from tools.pricing import get_all_prices
from tools.call_log import log_call_start_tool

class MockContext:
    """A simple mock context to mimic LiveKit's RunContext."""
    def __init__(self, userdata):
        self.userdata = userdata

async def test_tools():
    print("Initializing Database Pool...")
    pool = await get_pool()
    
    # 1. Setup UserData with the requested phone number
    phone_to_test = "9381891509"
    import uuid
    call_id_test = f"test_call_{uuid.uuid4().hex[:8]}"
    userdata = MuftyKareUserData(
        db_pool=pool,
        call_id=call_id_test,
        call_direction="inbound",
        caller_phone=phone_to_test,
        language="te-IN"
    )
    
    ctx = MockContext(userdata)
    
    print(f"\n--- Testing lookup_caller (using caller_phone: {phone_to_test}) ---")
    try:
        # Note: LiveKit's @function_tool decorator might require us to call the underlying .func 
        # depending on the version. If direct call fails, we'll try .func
        try:
            res1 = await lookup_caller(ctx)
        except TypeError:
            res1 = await lookup_caller.func(ctx)
        print("Result:", res1)
    except Exception as e:
        print("Error:", e)
        
    print(f"\n--- Testing lookup_customer_by_number (passing phone verbally: {phone_to_test}) ---")
    try:
        try:
            res2 = await lookup_customer_by_number(ctx, phone=phone_to_test)
        except TypeError:
            res2 = await lookup_customer_by_number.func(ctx, phone=phone_to_test)
        print("Result:", res2)
    except Exception as e:
        print("Error:", e)
        
    print(f"\n--- Testing save_new_customer (Creating Test User for {phone_to_test}) ---")
    try:
        try:
            res3 = await save_new_customer(ctx, name="Test User", phone=phone_to_test, address="Hyderabad Test Address")
        except TypeError:
            res3 = await save_new_customer.func(ctx, name="Test User", phone=phone_to_test, address="Hyderabad Test Address")
        print("Result:", res3)
    except Exception as e:
        print("Error:", e)
        
    print("\n--- Testing get_all_prices ---")
    try:
        try:
            res4 = await get_all_prices(ctx)
        except TypeError:
            res4 = await get_all_prices.func(ctx)
        print("Result:", res4)
    except Exception as e:
        print("Error:", e)
        
    print("\n--- Testing log_call_start_tool ---")
    try:
        try:
            res5 = await log_call_start_tool(ctx)
        except TypeError:
            res5 = await log_call_start_tool.func(ctx)
        print("Result:", res5)
    except Exception as e:
        print("Error:", e)
        
    print("\nClosing Database Pool...")
    await close_pool()

if __name__ == "__main__":
    asyncio.run(test_tools())
