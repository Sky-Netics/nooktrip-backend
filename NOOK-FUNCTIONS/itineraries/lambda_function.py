import json
import os
import logging
from typing import Dict, Any, List
from random import randint

import boto3
from botocore.exceptions import ClientError
from openai import OpenAI
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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
    location_name: str
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
5. Transportation: Include a mix of walking, biking, and public transport (including ferries if applicable).
6. Food: Include meals and small snacks to make the trip more exciting.
7. Traveler Type: Adjust activities based on whether it's for a single traveler or a couple.
8. Stops: For each stop, provide:
   - Location Name and brief description
   - Duration of the activity
   - Cost
   - ### Google Maps detailed coordinates (in latitude,longitude format) . 
   Variety: Ensure a good mix of activities (e.g., sightseeing, cultural experiences, food, relaxation).
10. Time Management: Account for travel time between stops.
11. Local Insights: Include local tips or lesser-known attractions when possible.

Provide a comprehensive and engaging itinerary that maximizes the traveler's experience within their constraints."""},
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
        
        # Add paths to each itinerary
        for itinerary in response_data['itineraries']:
            add_paths_to_itinerary(itinerary)
        
        logger.info("Itineraries generated and paths added successfully")
        return {
            "statusCode": 200,
            "body": json.dumps(response_data)
        }
    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps("An error occurred while processing your request")
        }

if __name__ == '__main__':
    # For local testing
    test_event = {'body': json.dumps({'city': 'Toronto Downtown', 'budget': 50, 'is_single': False})}
    print(lambda_handler(test_event, None)['body'])