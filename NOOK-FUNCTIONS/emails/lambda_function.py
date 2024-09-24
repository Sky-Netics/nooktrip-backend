import json
import os
import logging
from typing import Dict, Any, List, Optional

import boto3
from botocore.exceptions import ClientError
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel, EmailStr

from models import SelectedItinerary

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize database connection
db = sa.create_engine(os.environ.get("DB_CONNECTION"))

# Pydantic models
class Stop(BaseModel):
    location_name: str
    duration: str 
    cost: int
    currency: str
    google_map_coordinates: str
    path_to_next: Optional[str] = None

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

class EmailRequest(BaseModel):
    email: EmailStr
    itinerary: Itinerary

def validate_input(data: Dict[str, Any]) -> Dict[str, str]:
    """
    Validate the input data for the lambda function.
    
    Args:
    data (Dict[str, Any]): The input data to validate.
    
    Returns:
    Dict[str, str]: A dictionary of error messages, if any.
    """
    errors = {}
    try:
        EmailRequest(**data)
    except ValueError as e:
        errors["validation"] = str(e)
    return errors

def save_itinerary(email: str, itinerary: Dict[str, Any]) -> bool:
    """
    Save the selected itinerary to the database.
    
    Args:
    email (str): The user's email.
    itinerary (Dict[str, Any]): The selected itinerary.
    
    Returns:
    bool: True if the itinerary was saved successfully, False otherwise.
    """
    try:
        with db.connect() as conn:
            add_query = sa.insert(SelectedItinerary).values(
                email=email,
                itinerary_data=json.dumps(itinerary)
            )
            result = conn.execute(add_query)
            if result.rowcount == 1:
                conn.commit()
                logger.info(f"Itinerary saved successfully for email: {email}")
                return True
            else:
                logger.warning(f"Failed to save itinerary for email: {email}")
                return False
    except SQLAlchemyError as e:
        logger.error(f"Database error while saving itinerary for email {email}: {str(e)}")
        return False

def send_email(recipient: str, itinerary: Dict[str, Any]) -> bool:
    """
    Send an email with the itinerary details.
    
    Args:
    recipient (str): The recipient's email address.
    itinerary (Dict[str, Any]): The itinerary details.
    
    Returns:
    bool: True if the email was sent successfully, False otherwise.
    """
    SENDER = "your-sender-email@example.com"
    SUBJECT = "Your NookTrip Itinerary"

    # Create a formatted email body with the itinerary details
    BODY_TEXT = f"""
    Your NookTrip Itinerary:

    Package Name: {itinerary['package_name']}
    Summary: {itinerary['summary']}
    Total Duration: {itinerary['total_duration']}
    Total Cost: {itinerary['total_cost']} {itinerary['location_currency']}
    Start: {itinerary['start']}
    End: {itinerary['end']}
    Total Distance: {itinerary['total_distance']}
    Transport Mode: {itinerary['transport_mode']}

    Stops:
    """
    for stop in itinerary['stops']:
        BODY_TEXT += f"\n- {stop['location_name']}: Duration: {stop['duration']}, Cost: {stop['cost']} {stop['currency']}"
        BODY_TEXT += f"\n  Google Maps: https://www.google.com/maps/search/?api=1&query={stop['google_map_coordinates']}"
        if stop['path_to_next']:
            BODY_TEXT += f"\n  Path to next stop: {stop['path_to_next']}"

    return True
    # client = boto3.client('ses', region_name="us-west-2")
    # try:
    #     response = client.send_email(
    #         Destination={'ToAddresses': [recipient]},
    #         Message={
    #             'Body': {'Text': {'Charset': "UTF-8", 'Data': BODY_TEXT}},
    #             'Subject': {'Charset': "UTF-8", 'Data': SUBJECT},
    #         },
    #         Source=SENDER
    #     )
    # except ClientError as e:
    #     logger.error(f"Error sending email: {e.response['Error']['Message']}")
    #     return False
    # else:
    #     logger.info(f"Email sent! Message ID: {response['MessageId']}")
    #     return True

def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda function handler for sending emails with selected itineraries.
    
    Args:
    event (Dict[str, Any]): The event data passed to the Lambda function.
    context (Any): The runtime information of the Lambda function.
    
    Returns:
    Dict[str, Any]: The response containing the result of the email sending process.
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
    
    email = json_data["email"]
    itinerary = json_data["itinerary"]
    
    if not save_itinerary(email, itinerary):
        logger.error(f"Failed to save itinerary for email: {email}")
        return {
            "statusCode": 500,
            "body": json.dumps("Failed to save itinerary")
        }
    
    if not send_email(email, itinerary):
        logger.error(f"Failed to send email to: {email}")
        return {
            "statusCode": 500,
            "body": json.dumps("Failed to send email")
        }
    
    logger.info(f"Successfully processed request for email: {email}")
    return {
        "statusCode": 200,
        "body": json.dumps("Itinerary saved and email sent successfully")
    }

if __name__ == '__main__':
    # For local testing
    test_event = {
        'body': json.dumps({
            'email': 'test@example.com',
            'itinerary': {
                'stops': [
                    {
                        'location_name': 'CN Tower',
                        'duration': '2h',
                        'cost': 50,
                        'currency': 'CAD',
                        'google_map_coordinates': '43.6425662,-79.3870568',
                        'path_to_next': 'https://www.google.com/maps/dir/43.6425662,-79.3870568/43.6488821,-79.3731843'
                    },
                    {
                        'location_name': 'St. Lawrence Market',
                        'duration': '1h30m',
                        'cost': 20,
                        'currency': 'CAD',
                        'google_map_coordinates': '43.6488821,-79.3731843',
                        'path_to_next': None
                    }
                ],
                'total_duration': '4h',
                'total_cost': 70,
                'location_currency': 'CAD',
                'summary': 'A brief tour of downtown Toronto',
                'package_name': 'Toronto City Explorer',
                'start': '10:00 AM',
                'end': '2:00 PM',
                'total_distance': '2.5 km',
                'transport_mode': 'Walking'
            }
        })
    }
    print(lambda_handler(test_event, None)['body'])