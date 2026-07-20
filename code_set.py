# import os
# import asyncio
# from livekit import api
# from dotenv import load_dotenv
# load_dotenv()
# async def update_sip_trunk_codecs():
#     # 1. Initialize the LiveKit API client 
#     # It automatically picks up LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET from env variables
#     async with api.LiveKitAPI() as lkapi:
        
#         # 2. Define your strictly allowed codecs directly from api.SIPMediaConfig
#         # This completely strips out G.722 by leaving it out of the list
#         media_config = api.SIPMediaConfig(
#             codecs=[
#                 api.SIPCodec(name="PCMU"),
#                 api.SIPCodec(name="PCMA"),
#             ],
#             only_listed_codecs=True
#         )

#         # 3. Build the replacement trunk info
#         # NOTE: You MUST provide your actual Sip Trunk ID and your provider configuration.
#         # This mirrors a full update payload to avoid overwriting remaining credentials.
#         trunk_id = "ST_YjteHeGPYKxz"  # Replace with your actual Trunk ID
#         trunk_info = api.SIPInboundTrunkInfo(
#             name="Inbound Trunk without G722",
#             numbers=["+918035341648"],    # Replace with your trunk phone number
#             media=media_config           # Enforce codec constraints
#         )

#         try:
#             # 4. Use the correct API service endpoint
#             response = await lkapi.sip.update_inbound_trunk(trunk_id, trunk_info)
#             print(f"Trunk successfully updated! ID: {response.sip_trunk_id}")
            
#         except Exception as e:
#             print(f"Failed to update SIP Trunk configuration: {e}")

# # Run the async function
# if __name__ == "__main__":
#     asyncio.run(update_sip_trunk_codecs())

# import asyncio
# from livekit import api
# from dotenv import load_dotenv
# load_dotenv()

# async def update_sip_trunk_codecs():
#     # 1. Initialize the LiveKit API client using your env variables
#     async with api.LiveKitAPI() as lkapi:
        
#         # 2. Re-map the exact codecs you want to enforce
#         media_config = api.SIPMediaConfig(
#             codecs=[
#                 api.SIPCodec(name="PCMU"),
#                 api.SIPCodec(name="PCMA")
#             ],
#             only_listed_codecs=True
#         )

#         try:
#             # 3. Use update_inbound_trunk_fields to patch media safely 
#             # This avoids wiping out your Plivo username and password configuration!
#             response = await lkapi.sip.update_inbound_trunk_fields(
#                 trunk_id="ST_YjteHeGPYKxz",  # Your Trunk ID
#                 media=media_config           # Apply the codec constraints
#             )
#             print(f"Trunk fields successfully patched! ID: {response.sip_trunk_id}")
#             print(f"Current Config Name: {response.name}")
            
#         except Exception as e:
#             print(f"Failed to update fields: {e}")

# if __name__ == "__main__":
#     asyncio.run(update_sip_trunk_codecs())

import asyncio
from livekit import api
from dotenv import load_dotenv
load_dotenv()

async def check_trunk():
    async with api.LiveKitAPI() as lkapi:
        response = await lkapi.sip.list_inbound_trunk(
            api.ListSIPInboundTrunkRequest(trunk_ids=["ST_YjteHeGPYKxz"])
        )
        trunk = response.items[0]
        print("Name:", trunk.name)
        print("Media:", trunk.media)
        print("Codecs:", trunk.media.codecs if trunk.media else "NOT SET")
        print("Only listed:", trunk.media.only_listed_codecs if trunk.media else "NOT SET")

asyncio.run(check_trunk())