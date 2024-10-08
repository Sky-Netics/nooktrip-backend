import json
import os
import boto3
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import Base, ItineraryFeedback, FeedbackType

# Get the database connection string from environment variables
DB_CONNECTION_STRING = os.environ['DB_CONNECTION_STRING']

# Create SQLAlchemy engine and session
engine = create_engine(DB_CONNECTION_STRING)
Session = sessionmaker(bind=engine)

def lambda_handler(event, context):
    # Parse query string parameters
    params = event.get('queryStringParameters', {})
    itinerary_id = params.get('itinerary_id')
    feedback = params.get('feedback')

    # Validate input
    if not itinerary_id or not feedback:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Missing required parameters'})
        }

    try:
        # Convert feedback string to FeedbackType enum
        feedback_type = FeedbackType[feedback.upper()]
    except KeyError:
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Invalid feedback type'})
        }

    # Create database session
    session = Session()

    try:
        # Create new ItineraryFeedback record
        new_feedback = ItineraryFeedback(
            itinerary_id=int(itinerary_id),
            feedback=feedback_type
        )
        session.add(new_feedback)
        session.commit()

        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Feedback recorded successfully'})
        }
    except Exception as e:
        session.rollback()
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
    finally:
        session.close()