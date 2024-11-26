import requests
import os
import dotenv
import base64
from urllib.parse import quote 

dotenv.load_dotenv()
access_token = os.getenv('MAPBOX_TOKEN')

def direction_path(start_coordinates, end_coordinates, mode):
    start = f'{start_coordinates[0]},{start_coordinates[1]}'
    end = f'{end_coordinates[0]},{end_coordinates[1]}'

    directions_url = f"https://api.mapbox.com/directions/v5/mapbox/{mode}/{start};{end}?alternatives=false&continue_straight=true&geometries=polyline&overview=full&steps=false&access_token={access_token}"

    response = requests.get(directions_url)
    print("Response is: ", response)
    return response.json()['routes'][0]['geometry']

def encoding_points(coordinates):
    encoded_points = ''
    number_of_coordinates = len(coordinates)
    unicode = 97 # 'a'
    for i in range(number_of_coordinates):
        if i == 0:
            encoded_points += f"pin-l-{chr(unicode + i)}+26a269({coordinates[i][0]},{coordinates[i][1]}),"
        elif i == (number_of_coordinates - 1):
            encoded_points += f"pin-l-{chr(unicode + i)}+ff0000({coordinates[i][0]},{coordinates[i][1]})"
        else:
            encoded_points += f"pin-s-{chr(unicode + i)}+555555({coordinates[i][0]},{coordinates[i][1]}),"
    return encoded_points

def encoding_path(paths_coordinates,modes):
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

def static_map_image(coordinates, modes, size):
    """
    Generate a static map image and return it as base64 encoded string.
    
    Args:
    coordinates (List[List[float]]): List of [longitude, latitude] coordinates
    modes (List[str]): List of transport modes between coordinates
    size (str): Size of the image in format 'WxH'
    
    Returns:
    str: Base64 encoded PNG image
    """
    paths_coordinates = []

    for i in range(len(coordinates)-1):
        paths_coordinates.append(direction_path(coordinates[i], coordinates[i+1], modes[i]))

    encoded_points = encoding_points(coordinates)
    encoded_path = encoding_path(paths_coordinates,modes)
    encoded_path_url = quote(encoded_path)

    image_url = f"https://api.mapbox.com/styles/v1/mapbox/outdoors-v12/static/{encoded_path_url},{encoded_points}/auto/{size}@2x?access_token={access_token}"

    response = requests.get(image_url)
    if response.status_code == 200:
        # Convert image to base64
        base64_image = base64.b64encode(response.content).decode('utf-8')
        return base64_image
    else:
        print("Failed to download image")
        return None

if __name__=="__main__":
    coordinates = [
        [-123.1024, 49.2761],
        [-123.12284, 49.2868],
        [-123.1355, 49.28891],
        [-123.1486, 49.312]
    ]
    modes = ['walking', 'walking', 'cycling']
    SIZE = '500x400'
    base64_image = static_map_image(coordinates, modes, size=SIZE)
    print("Base64 image generated successfully" if base64_image else "Failed to generate image")
