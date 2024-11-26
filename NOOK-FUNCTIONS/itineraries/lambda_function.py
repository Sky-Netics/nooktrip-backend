import json
import os
import logging
import base64
from typing import Dict, Any, List
from random import randint
from urllib.parse import quote
import asyncio
import aiohttp
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.exceptions import ClientError
from openai import OpenAI
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize secrets at module level
secret_name = os.environ.get('SECRET_ID_NAME', 'nooktrip-secrets-dev')
session = boto3.session.Session()
secrets_client = session.client(
    service_name='secretsmanager',
    region_name="us-east-2"
)
try:
    secrets = json.loads(secrets_client.get_secret_value(SecretId=secret_name)['SecretString'])
except Exception as e:
    logger.error(f"Error loading secrets: {e}")
    raise

# Initialize global clients and resources
client = OpenAI(
    api_key=secrets.get('OPENAI_API_KEY'),
    timeout=60,
    max_retries=3
)
MAPBOX_TOKEN = secrets.get('MAPBOX_TOKEN')

# Global variables for parallel processing
_session = None
_executor = ThreadPoolExecutor(max_workers=20)

def parallel_base64_encode(image_data: bytes) -> str:
    """Encode image data to base64 in a separate thread"""
    return base64.b64encode(image_data).decode('utf-8')

async def get_aiohttp_session():
    """Get or create aiohttp session with connection pooling"""
    global _session
    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(limit=50, force_close=True)
        timeout = aiohttp.ClientTimeout(total=30)
        _session = aiohttp.ClientSession(connector=connector, timeout=timeout)
    return _session

async def fetch_with_retry(session, url, retries=3):
    """Fetch URL with retry logic"""
    for attempt in range(retries):
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.read()
                elif response.status != 429:  # If not rate limited, don't retry
                    break
        except Exception as e:
            if attempt == retries - 1:
                raise e
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
    return None

async def direction_path(start_coordinates, end_coordinates, mode, session):
    """Async version of direction path retrieval"""
    start = f'{start_coordinates[0]},{start_coordinates[1]}'
    end = f'{end_coordinates[0]},{end_coordinates[1]}'
    directions_url = f"https://api.mapbox.com/directions/v5/mapbox/{mode}/{start};{end}?alternatives=false&continue_straight=true&geometries=polyline&overview=full&steps=false&access_token={MAPBOX_TOKEN}"

    try:
        data = await fetch_with_retry(session, directions_url)
        if data:
            return json.loads(data)['routes'][0]['geometry']
    except Exception as e:
        logger.error(f"Error fetching direction path: {e}")
        raise

def encoding_points(coordinates):
    """Optimized point encoding with minimal string operations"""
    points = []
    for i, coordinate in enumerate(coordinates):
        if i == 0:
            pin_type, color = 'l', '26a269'
        elif i == len(coordinates) - 1:
            pin_type, color = 'l', 'ff0000'
        else:
            pin_type, color = 's', '555555'
        points.append(f"pin-{pin_type}-{i+1}+{color}({coordinate[0]},{coordinate[1]})")
    return ','.join(points)

def encoding_path(paths_coordinates, modes):
    """Optimized path encoding with lookup table"""
    COLOR_MAP = {'driving': '2bff00', 'walking': '0000ff', 'cycling': 'ff0000'}
    return ','.join(
        f"path-3+{COLOR_MAP.get(mode, '000000')}({path})"
        for path, mode in zip(paths_coordinates, modes)
    )

async def static_map_image(coordinates, modes, size):
    """Optimized static map image generation with parallel processing"""
    session = await get_aiohttp_session()
    
    # Generate all direction paths concurrently
    paths_tasks = [
        direction_path(coordinates[i], coordinates[i+1], modes[i], session)
        for i in range(len(coordinates)-1)
    ]
    paths_coordinates = await asyncio.gather(*paths_tasks)
    
    # Generate map URL
    encoded_points = encoding_points(coordinates)
    encoded_path = encoding_path(paths_coordinates, modes)
    encoded_path_url = quote(encoded_path)
    map_url = f"https://api.mapbox.com/styles/v1/mapbox/outdoors-v12/static/{encoded_path_url},{encoded_points}/auto/{size}@2x?access_token={MAPBOX_TOKEN}"
    
    # Fetch map image
    image_data = await fetch_with_retry(session, map_url)
    if not image_data:
        return None
    
    # Encode image in parallel thread
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, parallel_base64_encode, image_data)

class Stop(BaseModel):
    location_title: str
    location_address: str
    duration: str 
    cost: int
    currency: str
    google_map_coordinates: str

class Itinerary(BaseModel):
    stops: List[Stop]
    total_duration: str 
    total_cost: int
    location_currency: str
    summary: str
    package_name: str
    start: str
    end: str
    total_distance: str
    transport_mode: str

class Response(BaseModel):
    itineraries: List[Itinerary]

def validate_input(data: Dict[str, Any]) -> Dict[str, str]:
    """Validate the input data"""
    errors = {}
    if not data.get("city") or not isinstance(data.get("city"), str):
        errors["city"] = "Invalid city name"
    if not data.get("budget"):
        errors["budget"] = "Invalid budget"
    return errors

async def generate_itinerary(city: str, budget: int, is_single: bool) -> Dict[str, Any]:
    """Generate itinerary using OpenAI"""
    traveler_type = "I am a solo traveler" if is_single else "We are couple travelers"
    pronoun = "I" if is_single else "we"
    prompt = f"{traveler_type}, {pronoun} have the budget of {budget}. {pronoun.capitalize()} {'am' if is_single else 'are'} in {city} city."
    
    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            _executor,
            lambda: client.beta.chat.completions.parse(
                model="gpt-4o-2024-08-06",
                messages=[
                    {"role": "system", "content": """You're a trip advisor. Create 3 detailed itineraries for the user based on their input. Follow these guidelines:

1. Location: Ensure all stops are within the specified city only.
2. Budget: The total cost must be equal to or less than the user's budget.
3. Duration: Total duration should be between 2 to 8 hours.
4. Currency: Use the local currency of the specified city.
5. Transportation: For transport_mode field, use one of these values:
   - 'walking' for walking routes
   - 'cycling' for biking routes
   - 'driving' for car/taxi routes
   - 'ferry' for water transport
   Note: If ferry is used, the map will show the route as 'driving' between ports.
6. Food: Include meals and small snacks to make the trip more exciting.
7. Traveler Type: Adjust activities based on whether it's for a single traveler or a couple.
8. Stops: For each stop, provide:
   - Location Name (e.g., cafe name)
   - Location address 
   - Duration of the activity
   - Cost
   - ### Google Maps detailed coordinates (in latitude,longitude format) . 
9. Variety: Ensure a good mix of activities (e.g., sightseeing, cultural experiences, food, relaxation).
10. Time Management: Account for travel time between stops.
11. Local Insights: Include local tips or lesser-known attractions when possible."""},
                    {"role": "user", "content": prompt}
                ],
                response_format=Response,
                seed=randint(1000000000000000, 9223372036854775807)
            )
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating itinerary: {str(e)}")
        raise

def add_paths_to_itinerary(itinerary: Dict[str, Any]) -> Dict[str, Any]:
    """Add paths between stops"""
    stops = itinerary['stops']
    for i in range(len(stops) - 1):
        current_stop, next_stop = stops[i], stops[i + 1]
        current_stop['path_to_next'] = f"https://www.google.com/maps/dir/{current_stop['google_map_coordinates']}/{next_stop['google_map_coordinates']}"
    stops[-1]['path_to_next'] = None
    return itinerary

async def process_itinerary(itinerary: Dict[str, Any]) -> Dict[str, Any]:
    """Process single itinerary with optimized coordinate handling"""
    try:
        # Parse coordinates from google_map_coordinates (format: "lat,lon")
        coordinates = []
        for stop in itinerary['stops']:
            lat, lon = map(float, stop['google_map_coordinates'].strip().split(','))
            coordinates.append([lon, lat])  # Mapbox expects [longitude, latitude]
        
        # Handle transport mode
        mode = itinerary['transport_mode'].lower()
        mode = 'driving' if mode == 'ferry' else (mode if mode in ['walking', 'cycling', 'driving'] else 'walking')
        modes = [mode] * (len(coordinates) - 1)
        
        # Generate map
        base64_map = await static_map_image(coordinates, modes, size='500x400')
        if base64_map:
            itinerary['map_image'] = base64_map
            logger.info(f"Map generated for itinerary: {itinerary['package_name']}")
        else:
            logger.warning(f"Failed to generate map for itinerary: {itinerary['package_name']}")
    except Exception as e:
        logger.error(f"Error processing itinerary {itinerary.get('package_name', 'unknown')}: {str(e)}")
        
    return itinerary

async def lambda_handler_async(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Async lambda handler with optimized processing"""
    try:
        json_data = json.loads(event['body'])
        if errors := validate_input(json_data):
            return {"statusCode": 400, "body": json.dumps(errors)}
        
        city, budget, is_single = json_data["city"], json_data["budget"], json_data.get("is_single", False)
        
        # Generate itinerary
        itineraries = await generate_itinerary(city, budget, is_single)
        response_data = json.loads(itineraries)
        
        # Process itineraries concurrently
        processed_itineraries = await asyncio.gather(*[
            process_itinerary(add_paths_to_itinerary(itinerary))
            for itinerary in response_data['itineraries']
        ])
        
        response_data['itineraries'] = processed_itineraries
        return {"statusCode": 200, "body": json.dumps(response_data)}
        
    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}")
        return {"statusCode": 500, "body": json.dumps(str(e))}

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Main lambda handler"""
    return asyncio.run(lambda_handler_async(event, context))

if __name__ == '__main__':
    test_event = {'body': json.dumps({'city': 'Toronto Downtown', 'budget': 50, 'is_single': False})}
    print(json.dumps(lambda_handler(test_event, None), indent=2))
