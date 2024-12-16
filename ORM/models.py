from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
import enum
# Test

Base = declarative_base()

class UserEmail(Base):
    __tablename__ = "user_emails"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)

class SelectedItinerary(Base):
    __tablename__ = "selected_itineraries"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True)
    itinerary_data = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<SelectedItinerary(id={self.id}, email={self.email})>"

class FeedbackType(enum.Enum):
    LIKE = "like"
    DISLIKE = "dislike"

class ItineraryFeedback(Base):
    __tablename__ = "itinerary_feedback"

    id = Column(Integer, primary_key=True, index=True)
    itinerary_id = Column(Integer, ForeignKey('selected_itineraries.id'), nullable=False)
    feedback = Column(Enum(FeedbackType), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<ItineraryFeedback(id={self.id}, itinerary_id={self.itinerary_id}, feedback={self.feedback})>"
