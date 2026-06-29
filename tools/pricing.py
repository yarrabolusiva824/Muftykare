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
    - "Cotton pants wash ki enta?"
    
    You do NOT need to pass the item name. This tool will return a comprehensive 
    list of all prices in JSON format. You must read through the returned list yourself 
    to find the price matching the customer's request.
    
    If the item they requested is not in the list, suggest checking the website
    at https://muftykare.com or contacting support at 7075232425.

    Returns:
        A JSON formatted string listing all available items, services, and their prices.
    """
    logger.info("tool:get_all_prices called")
    
    catalog = [
        {"item": "Apron - Normal", "service": "Dry Clean", "price": 50},
        {"item": "Bag - Backpack", "service": "Dry Clean", "price": 80},
        {"item": "Bathrobe - Normal", "service": "Dry Clean", "price": 50},
        {"item": "Bath Towel - Normal", "service": "Dry Clean", "price": 40},
        {"item": "Bed Sheet - Double", "service": "Dry Clean", "price": 60},
        {"item": "Bed Sheet - Single", "service": "Dry Clean", "price": 50},
        {"item": "Belt - Normal", "service": "Dry Clean", "price": 70},
        {"item": "Blanket - Normal", "service": "Dry Clean", "price": 250},
        {"item": "Blazer - Normal", "service": "Dry Clean", "price": 200},
        {"item": "Blouse - Normal", "service": "Dry Clean", "price": 25},
        {"item": "Boots - Long", "service": "Dry Clean", "price": 250},
        {"item": "Bottom - Normal", "service": "Dry Clean", "price": 50},
        {"item": "Burkha - Silk", "service": "Dry Clean", "price": 80},
        {"item": "Cap Hat - Normal", "service": "Dry Clean", "price": 60},
        {"item": "Curtain - Normal", "service": "Dry Clean", "price": 150},
        {"item": "Dhoti - Normal", "service": "Dry Clean", "price": 80},
        {"item": "Dog Bed - Large", "service": "Dry Clean", "price": 400},
        {"item": "Duet Cover - Normal", "service": "Dry Clean", "price": 40},
        {"item": "Dupatta - Normal", "service": "Dry Clean", "price": 30},
        {"item": "Hoodie - Full", "service": "Dry Clean", "price": 150},
        {"item": "Jacket - Normal", "service": "Dry Clean", "price": 200},
        {"item": "Jeans - Normal", "service": "Dry Clean", "price": 70},
        {"item": "Jump Suit - Normal", "service": "Dry Clean", "price": 250},
        {"item": "Kurta - Normal", "service": "Dry Clean", "price": 150},
        {"item": "Kurta - Normal", "service": "Steam Press", "price": 30},
        {"item": "Lab coat - Normal", "service": "Dry Clean", "price": 50},
        {"item": "Laundry By Weight - Any", "service": "Wash & Fold", "price": 90},
        {"item": "Lehenga - Cotton", "service": "Dry Clean", "price": 120},
        {"item": "Napkin - Normal", "service": "Dry Clean", "price": 15},
        {"item": "Overcoat - Leather", "service": "Dry Clean", "price": 450},
        {"item": "Pancha - Normal", "service": "Dry Clean", "price": 60},
        {"item": "Payjama - Normal", "service": "Dry Clean", "price": 50},
        {"item": "Petticoat - Normal", "service": "Dry Clean", "price": 80},
        {"item": "Pillow Cover - Large", "service": "Dry Clean", "price": 50},
        {"item": "Purse - Large", "service": "Dry Clean", "price": 450},
        {"item": "Quilt - Normal", "service": "Dry Clean", "price": 180},
        {"item": "Saree - Cotton", "service": "Dry Clean", "price": 100},
        {"item": "Shawl - Normal", "service": "Dry Clean", "price": 120},
        {"item": "Sherwani - Cotton", "service": "Dry Clean", "price": 250},
        {"item": "Shirt - Cotton", "service": "Dry Clean", "price": 40},
        {"item": "Shoes - Normal", "service": "Dry Clean", "price": 400},
        {"item": "Shorts - Normal", "service": "Dry Clean", "price": 40},
        {"item": "Skirt - Cotton", "service": "Dry Clean", "price": 150},
        {"item": "Socks - Normal", "service": "Dry Clean", "price": 30},
        {"item": "Sweater - Cotton", "service": "Dry Clean", "price": 120},
        {"item": "Table Cloth - Normal", "service": "Dry Clean", "price": 100},
        {"item": "Tie - Normal", "service": "Dry Clean", "price": 70},
        {"item": "Top - Cotton", "service": "Dry Clean", "price": 80},
        {"item": "Toy - Large", "service": "Dry Clean", "price": 400},
        {"item": "Trousers - Normal", "service": "Steam Press", "price": 25},
        {"item": "T-Shirt - Normal", "service": "Dry Clean", "price": 40},
        {"item": "Turband - Cotton", "service": "Dry Clean", "price": 80},
        {"item": "Undergarments - Men", "service": "Dry Clean", "price": 60},
        {"item": "Vest - Cotton", "service": "Dry Clean", "price": 50},
        {"item": "Waistcoat - Normal", "service": "Dry Clean", "price": 100},
        {"item": "Wedding Dress - Normal", "service": "Dry Clean", "price": 400}
    ]

    return json.dumps(catalog, indent=2)
