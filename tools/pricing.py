"""
tools/pricing.py — Pricing inquiry tools for MuftyKare voice agent.

Used by: GreeterAgent and BookingAgent (for pre-booking price queries)
"""
from __future__ import annotations
from typing import Annotated
from pydantic import Field
from livekit.agents import RunContext, ToolError
from livekit.agents.llm import function_tool
from userdata import MuftyKareUserData
from logger import get_logger
import json

logger = get_logger(__name__)
RunCtx = RunContext[MuftyKareUserData]

@function_tool
async def get_all_prices(
    context: RunCtx,
) -> str:
    """
    Retrieve the full catalog of items and their prices.

    Call when the customer asks about pricing BEFORE booking:
    - "Silk saree dry cleaning ki enta?" (How much for silk saree dry cleaning?)
    - "Shirt steam iron ki price enti?"
     pants wash ki enta?"
    
    You do NOT need to pass the item name. This tool will return a comprehensive 
    list of all prices in JSON format. You must read through the returned list yourself 
    to find the price matching the customer's request.
    
    If the item they requested is not in the list, suggest checking the website
    at https://muftykare.com or contacting support at 7075232425.

    Returns:
        A JSON formatted string listing all available items and their prices.
    """
    logger.info("tool:get_all_prices called")
    
    catalog = [
        {"item": "Apron", "price": 50},
        {"item": "Bag - Backpack", "price": 80},
        {"item": "Bathrobe", "price": 50},
        {"item": "Bath Towel", "price": 40},
        {"item": "Bed Sheet", "price": 60},
        {"item": "Belt", "price": 70},
        {"item": "Blanket", "price": 250},
        {"item": "Blazer", "price": 200},
        {"item": "Blouse", "price": 25},
        {"item": "Boots - Long", "price": 250},
        {"item": "Bottom", "price": 50},
        {"item": "Burkha - Silk", "price": 80},
        {"item": "Cap Hat", "price": 60},
        {"item": "Curtain", "price": 150},
        {"item": "Dhoti", "price": 80},
        {"item": "Dog Bed", "price": 400},
        {"item": "Duet Cover", "price": 40},
        {"item": "Dupatta", "price": 30},
        {"item": "Hoodie - Full", "price": 150},
        {"item": "Jacket", "price": 200},
        {"item": "Jeans", "price": 70},
        {"item": "Jump Suit", "price": 250},
        {"item": "Kurta (Dry Clean)", "price": 150},
        {"item": "Kurta (Steam Press)", "price": 30},
        {"item": "Lab coat", "price": 50},
        {"item": "Laundry By Weight - Any", "price": 90},
        {"item": "Lehenga", "price": 120},
        {"item": "Napkin", "price": 15},
        {"item": "Overcoat", "price": 450},
        {"item": "Pancha", "price": 60},
        {"item": "Payjama", "price": 50},
        {"item": "Petticoat", "price": 80},
        {"item": "Pillow Cover", "price": 50},
        {"item": "Purse", "price": 450},
        {"item": "Quilt", "price": 180},
        {"item": "Saree", "price": 100},
        {"item": "Shawl", "price": 120},
        {"item": "Sherwani", "price": 250},
        {"item": "Shirt", "price": 40},
        {"item": "Shoes", "price": 400},
        {"item": "Shorts", "price": 40},
        {"item": "Skirt", "price": 150},
        {"item": "Socks", "price": 30},
        {"item": "Sweater", "price": 120},
        {"item": "Table Cloth", "price": 100},
        {"item": "Tie", "price": 70},
        {"item": "Top", "price": 80},
        {"item": "Toy", "price": 400},
        {"item": "Trousers", "price": 25},
        {"item": "T-Shirt", "price": 40},
        {"item": "Turband", "price": 80},
        {"item": "Undergarments", "price": 60},
        {"item": "Vest", "price": 50},
        {"item": "Waistcoat", "price": 100},
        {"item": "Wedding Dress", "price": 400}
    ]

    return json.dumps(catalog, indent=2)
