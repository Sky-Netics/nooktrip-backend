import json
import os
import logging
import base64
from typing import Dict, Any, List
from random import randint
from urllib.parse import quote

import boto3
import requests
from botocore.exceptions import ClientError
from openai import OpenAI
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Static Map Functions
def direction_path(start_coordinates, end_coordinates, mode, access_token):
    start = f'{start_coordinates[0]},{start_coordinates[1]}'
    end = f'{end_coordinates[0]},{end_coordinates[1]}'

    directions_url = f"https://api.mapbox.com/directions/v5/mapbox/{mode}/{start};{end}?alternatives=false&continue_straight=true&geometries=polyline&overview=full&steps=false&access_token={access_token}"

    response = requests.get(directions_url)
    logger.info(f"Direction API response status: {response.status_code}")
    return response.json()['routes'][0]['geometry']

def encoding_points(coordinates):
    encoded_points = ''
    number_of_coordinates = len(coordinates)
    for i in range(number_of_coordinates):
        if i == 0:
            encoded_points += f"pin-l-{i+1}+26a269({coordinates[i][0]},{coordinates[i][1]}),"
        elif i == (number_of_coordinates - 1):
            encoded_points += f"pin-l-{i+1}+ff0000({coordinates[i][0]},{coordinates[i][1]})"
        else:
            encoded_points += f"pin-s-{i+1}+555555({coordinates[i][0]},{coordinates[i][1]}),"
    return encoded_points

def encoding_path(paths_coordinates, modes):
    DRIVING_COLOR = '2bff00'
    WALKING_COLOR = '0000ff'
    CYCLING_COLOR = 'ff0000'
    STROKE_WIDTH = 3
    
    encoded_path = ''
    number_of_paths = len(paths_coordinates)
    for i in range(number_of_paths):
        if modes[i] == 'driving':
            encoded_path += f"path-{STROKE_WIDTH}+{DRIVING_COLOR}({paths_coordinates[i]}),"
        elif modes[i] == 'walking':
            encoded_path += f"path-{STROKE_WIDTH}+{WALKING_COLOR}({paths_coordinates[i]}),"
        elif modes[i] == 'cycling':
            encoded_path += f"path-{STROKE_WIDTH}+{CYCLING_COLOR}({paths_coordinates[i]}),"
        else:
            encoded_path += f"path-{STROKE_WIDTH}({paths_coordinates[i]}),"

    return encoded_path[:-1]

def static_map_image(coordinates, modes, size, access_token):
    """
    Generate a static map image and return it as base64 encoded string.
    
    Args:
    coordinates (List[List[float]]): List of [longitude, latitude] coordinates
    modes (List[str]): List of transport modes between coordinates
    size (str): Size of the image in format 'WxH'
    access_token (str): Mapbox access token
    
    Returns:
    str: Base64 encoded PNG image
    """
    paths_coordinates = []

    for i in range(len(coordinates)-1):
        paths_coordinates.append(direction_path(coordinates[i], coordinates[i+1], modes[i], access_token))

    encoded_points = encoding_points(coordinates)
    encoded_path = encoding_path(paths_coordinates, modes)
    encoded_path_url = quote(encoded_path)

    image_url = f"https://api.mapbox.com/styles/v1/mapbox/outdoors-v12/static/{encoded_path_url},{encoded_points}/auto/{size}@2x?access_token={access_token}"

    response = requests.get(image_url)
    if response.status_code == 200:
        base64_image = base64.b64encode(response.content).decode('utf-8')
        return base64_image
    else:
        logger.error(f"Failed to download map image. Status code: {response.status_code}")
        return None

# Retrieve secrets from AWS Secrets Manager
def get_secret():
    secret_name = os.environ.get('SECRET_ID_NAME', 'nooktrip-secrets-dev')
    region_name = "us-east-2"  # Replace with your AWS region

    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except ClientError as e:
        logger.error(f"Error retrieving secret: {e}")
        raise e
    else:
        if 'SecretString' in get_secret_value_response:
            return json.loads(get_secret_value_response['SecretString'])
        else:
            logger.error("Secret value is not a string")
            raise ValueError("Secret value is not a string")

# Retrieve secrets
secrets = get_secret()

# Pydantic models
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

# Initialize OpenAI client
client = OpenAI(
    api_key=secrets.get('OPENAI_API_KEY'),
    timeout=60,
    max_retries=3
)

def validate_input(data: Dict[str, Any]) -> Dict[str, str]:
    """
    Validate the input data for the lambda function.
    
    Args:
    data (Dict[str, Any]): The input data to validate.
    
    Returns:
    Dict[str, str]: A dictionary of error messages, if any.
    """
    errors = {}
    if not data.get("city") or not isinstance(data.get("city"), str):
        errors["city"] = "Invalid city name"
    if not data.get("budget"):
        errors["budget"] = "Invalid budget"
    return errors

def generate_itinerary(city: str, budget: int, is_single: bool) -> Dict[str, Any]:
    """
    Generate an itinerary using OpenAI's API.
    
    Args:
    city (str): The city for the itinerary.
    budget (int): The budget for the itinerary.
    is_single (bool): Whether the traveler is single or a couple.
    
    Returns:
    Dict[str, Any]: The generated itinerary.
    """
    traveler_type = "I am a solo traveler" if is_single else "We are couple travelers"
    pronoun = "I" if is_single else "we"
    prompt = f"{traveler_type}, {pronoun} have the budget of {budget}. {pronoun.capitalize()} {'am' if is_single else 'are'} in {city} city."
    
    logger.info(f"Generating itinerary with prompt: {prompt}")
    
    try:
        stream = client.beta.chat.completions.parse(
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
11. Local Insights: Include local tips or lesser-known attractions when possible.

IMPORTANT: When ferry transport is used, the map will display the route as a driving path between ports, but the itinerary description will accurately reflect ferry transport."""},
                {"role": "user", "content": prompt}
            ],
            response_format=Response,
            seed=randint(1000000000000000, 9223372036854775807)
        )
        return stream.choices[0].message.content
    except Exception as e:
        logger.error(f"Error generating itinerary: {str(e)}")
        raise

def add_paths_to_itinerary(itinerary: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add paths between stops in an itinerary.
    
    Args:
    itinerary (Dict[str, Any]): The itinerary to process.
    
    Returns:
    Dict[str, Any]: The updated itinerary with paths between stops.
    """
    stops = itinerary['stops']
    for i in range(len(stops) - 1):
        current_stop = stops[i]
        next_stop = stops[i + 1]
        current_stop['path_to_next'] = f"https://www.google.com/maps/dir/{current_stop['google_map_coordinates']}/{next_stop['google_map_coordinates']}"
    
    # The last stop doesn't have a next stop, so we set its path_to_next to None
    stops[-1]['path_to_next'] = None
    
    return itinerary

def generate_route_map(itinerary: Dict[str, Any], mapbox_token: str) -> str:
    """
    Generate a static map image for the itinerary route.
    
    Args:
    itinerary (Dict[str, Any]): The itinerary to generate a map for.
    mapbox_token (str): Mapbox access token
    
    Returns:
    str: Base64 encoded map image.
    """
    coordinates = []
    modes = []
    
    # Extract coordinates from stops
    for stop in itinerary['stops']:
        lat, lon = map(float, stop['google_map_coordinates'].split(','))
        coordinates.append([lon, lat])  # Mapbox expects [longitude, latitude]
    
    # Get transport mode - if ferry, use driving for map display
    mode = itinerary['transport_mode'].lower()
    if mode == 'ferry':
        mode = 'driving'
    elif mode not in ['walking', 'cycling', 'driving']:
        logger.warning(f"Invalid transport mode '{mode}', defaulting to 'walking'")
        mode = 'walking'
    
    # Add mode for each path between stops
    for _ in range(len(coordinates) - 1):
        modes.append(mode)
    
    # Generate and return the base64 encoded map image
    return static_map_image(coordinates, modes, size='500x400', access_token=mapbox_token)

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda function handler for generating itineraries.
    
    Args:
    event (Dict[str, Any]): The event data passed to the Lambda function.
    context (Any): The runtime information of the Lambda function.
    
    Returns:
    Dict[str, Any]: The response containing the generated itinerary or error message.
    """
    logger.info(f"Received event: {event}")
    
    try:
        json_data = json.loads(event['body'])
    except json.JSONDecodeError:
        logger.error("Invalid JSON in event body")
        return {"statusCode": 400, "body": json.dumps("Invalid JSON in request body")}
    
    errors = validate_input(json_data)
    if errors:
        logger.warning(f"Input validation failed: {errors}")
        return {"statusCode": 400, "body": json.dumps(errors)}
    
    city = json_data["city"]
    budget = json_data["budget"]
    is_single = json_data.get("is_single", False)
    
    try:
        itineraries = generate_itinerary(city, budget, is_single)
        
        # Parse the generated itineraries
        response_data = json.loads(itineraries)
        
        # Get Mapbox token from secrets
        mapbox_token = secrets.get('MAPBOX_TOKEN')
        if not mapbox_token:
            logger.error("Mapbox token not found in secrets")
            return {
                "statusCode": 500,
                "body": json.dumps("Missing Mapbox configuration")
            }
        
        # Add paths and generate maps for each itinerary
        for itinerary in response_data['itineraries']:
            add_paths_to_itinerary(itinerary)
            base64_map = generate_route_map(itinerary, mapbox_token)
            if base64_map:
                itinerary['map_image'] = base64_map
                logger.info(f"Successfully generated map for itinerary: {itinerary['package_name']}")
            else:
                logger.warning(f"Failed to generate map for itinerary: {itinerary['package_name']}")
        
        logger.info("Itineraries generated with maps and paths added successfully")
        return {
            "statusCode": 200,
            "body": json.dumps(response_data)
        }
    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps(f"An error occurred while processing your request: {str(e)}")
        }

if __name__ == '__main__':
    # For local testing
    test_event = {'body': json.dumps({'city': 'Toronto Downtown', 'budget': 50, 'is_single': False})}
    result = lambda_handler(test_event, None)
    print(f"Status Code: {result['statusCode']}")
    if result['statusCode'] == 200:
        response_data = json.loads(result['body'])
        # Print first few characters of map_image to verify it's base64
        for itinerary in response_data['itineraries']:
            if 'map_image' in itinerary:
                print(f"Map generated for {itinerary['package_name']}")
                print(f"Base64 image preview: {itinerary['map_image'][:50]}...")
            else:
                print(f"No map generated for {itinerary['package_name']}")
    else:
        print(f"Error: {result['body']}")
