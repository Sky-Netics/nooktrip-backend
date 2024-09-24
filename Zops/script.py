# In[1]


from openai import OpenAI
from pydantic import BaseModel
from random import randint



# In[2]
#Models


class Stop(BaseModel):
    start: str
    duration: str 
    cost: int
    currency: str

class Itenary(BaseModel):
    stops: list[Stop]
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
    itenaries: list[Itenary]



# In[3]

client = OpenAI(api_key="sk-proj-qDKXbmUZmP908aW90ABnT3BlbkFJiWj4y2k50f71nIqifoNY", timeout=60, max_retries=3)



#In[4]
#inputs
city = "Toronto"
budget = 50
email = "example@gmail.com"
is_single = False




#In[5]

stream = client.beta.chat.completions.parse(
            model="gpt-4o-2024-08-06",
            messages=[ {"role": "system", 
                        # "content": "You're a trip planner user will give you {Location} and {Travel Composite} which is being a single or couple travelers and their {Budget} you should suggest a day of trip in their desired location with different types of activities with different stops. have in mind different ways of travel {walking and bicycle/Ferry/Tourist Bus} and different types of food to include in the itenaries {breakfast/launch/dinner/snack/ice cream} based on the budget. give 2-3 diverse itenaries"
                            "content": """
                Respond only in Json: As a trip planner provide three options for a day trip itinerary for {Location} , for {Travel Composite} , with {Cost} , and mode of transport for first option should {walking} and the second option can be combination of {walking and bicycle/Ferry/Tourist Bus}, suggest breakfast/launch/dinner/snack/ice cream based on the budget. 
                Return the stops as an array with detailed properties for each stop in each Itinerary
                the plans should structured and includes: 

[Detailed Day Trip Itinerary]

Itinerary 1:

Start: [Start Time] at [Starting Location]

Duration: [Duration at Start Location]

Cost: [Cost at Start Location]
activity type: [walking in the city/art gallery/Beaches/Shopping Malls/sightseen/historical/landmarks]
Activity explanation: [Activity at Following Spot]
[Next Stop]

Duration: [Duration at Next Stop]
Cost: [Cost at Next Stop]
[Following Stop]

Duration: [Duration at Following Stop]
Cost: [Cost at Following Stop]
[Further Stop]

Duration: [Duration at Further Stop]
Cost: [Cost at Further Stop]
End: [End Time] at [Ending Location]

Duration: [Duration at Ending Location]
Summary:

Package Name: [Package Name]
Travel Composite: Solo Traveler or Couple Traveler
Start: [Start Time] at [Starting Location]
End: [End Time] at [Ending Location]
Total Duration: [Total Duration]
Total Distance: [Total Distance]
Mode of Transport: [Mode of Transport]
Total Cost: [Total Cost] (or within the $[Budget] budget)
                """
        },
            {"role": "user", "content":  "Solo {Travel Composite}" if is_single else "Couple {Travel Composite}" + f"{budget} {{Cost}} {city} {{Location}}" }],
        response_format=Response,
        seed=randint(1000000000000000, 9223372036854775807)
    )

content = stream.choices[0].message.content



#In[99]

import json


json.loads('')