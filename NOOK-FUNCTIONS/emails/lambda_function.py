import json
import os
import logging
from typing import Dict, Any, List, Optional
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import boto3
from botocore.exceptions import ClientError
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel, EmailStr

from models import SelectedItinerary

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

# Initialize database connection
db = sa.create_engine(secrets.get("DB_CONNECTION"))

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
    Send an email with the itinerary details using Gmail SMTP.
    
    Args:
    recipient (str): The recipient's email address.
    itinerary (Dict[str, Any]): The itinerary details.
    
    Returns:
    bool: True if the email was sent successfully, False otherwise.
    """
    SENDER = secrets.get("SENDER_EMAIL", "your-sender-email@gmail.com")
    SENDER_PASSWORD = secrets.get("SENDER_PASSWORD", "your-sender-password")
    SUBJECT = f"Your NookTrip Itinerary: {itinerary['package_name']}"

    # Read the HTML template
    try:
        with open('Standard version.html', 'r') as file:
            html_template = file.read()
    except FileNotFoundError:
        logger.error("HTML template file not found")
        return False

    # Replace placeholders in the template
    html_content = html_template.replace('[Destination]', itinerary['package_name'])
    html_content = html_content.replace('[Date]', f"{itinerary['start']} - {itinerary['end']}")
    html_content = html_content.replace('[Place A]', itinerary['stops'][0]['location_title'])
    html_content = html_content.replace('[Place B]', itinerary['stops'][-1]['location_title'])

    # Create activities and meals content
    activities_content = ""
    for i, stop in enumerate(itinerary['stops']):
        if i == 0:
            activities_content += f"<p style='margin: 10px 0;'><strong>Morning Activity:</strong> {stop['location_title']} - {stop['duration']}</p>"
        elif i == len(itinerary['stops']) - 1:
            activities_content += f"<p style='margin: 10px 0;'><strong>Afternoon Activity:</strong> {stop['location_title']} - {stop['duration']}</p>"
        else:
            activities_content += f"<p style='margin: 10px 0;'><strong>Stop {i+1}:</strong> {stop['location_title']} - {stop['duration']}, Cost: {stop['cost']} {stop['currency']}</p>"

    html_content = html_content.replace("<p style=\"margin: 10px 0;\"><strong>Morning Activity:</strong> [Activity 1]</p>", activities_content)
    html_content = html_content.replace("<p style=\"margin: 10px 0;\"><strong>Lunch Stop:</strong> [Restaurant] - $[Cost]</p>", "")
    html_content = html_content.replace("<p style=\"margin: 10px 0;\"><strong>Afternoon Activity:</strong> [Activity 2]</p>", "")
    html_content = html_content.replace("<p style=\"margin: 10px 0;\"><strong>Dinner Spot:</strong> [Restaurant] - $[Cost]</p>", "")

    # Add total cost and duration
    html_content += f"<p style='margin: 10px 0;'><strong>Total Cost:</strong> {itinerary['total_cost']} {itinerary['location_currency']}</p>"
    html_content += f"<p style='margin: 10px 0;'><strong>Total Duration:</strong> {itinerary['total_duration']}</p>"

    # Create the email message
    msg = MIMEMultipart()
    msg['From'] = SENDER
    msg['To'] = recipient
    msg['Subject'] = SUBJECT

    # Attach HTML content
    msg.attach(MIMEText(html_content, 'html'))

    # Connect to Gmail SMTP server and send the email
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(SENDER, SENDER_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        logger.error(f"Error sending email: {str(e)}")
        return False
    else:
        logger.info(f"Email sent successfully to: {recipient}")
        return True

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
                        'location_title': 'CN Tower',
                        'location_address': '790 Queen street',
                        'duration': '2h',
                        'cost': 50,
                        'currency': 'CAD',
                        'google_map_coordinates': '43.6425662,-79.3870568',
                        'path_to_next': 'https://www.google.com/maps/dir/43.6425662,-79.3870568/43.6488821,-79.3731843'
                    },
                    {
                         'location_title': 'CN Tower',
                        'location_address': '790 Queen street',
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