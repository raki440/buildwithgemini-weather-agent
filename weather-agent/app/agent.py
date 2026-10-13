# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import json
import os
import urllib.parse
import urllib.request
import uuid
from zoneinfo import ZoneInfo

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google import genai
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.cloud import firestore
from google.cloud import storage
from google.genai import types

from .a2ui_utils import a2ui_callback

PROJECT_ID = "qwiklabs-gcp-04-78ac92e9286e"
MEMORY_BANK_ID = "7806084231343374336"
COLLECTION_NAME = "cities"
BUCKET_NAME = "weather-agent-assets-qwiklabs-gcp-04-78ac92e9286e"
SANDBOX_RESOURCE_NAME = "projects/810848355362/locations/us-central1/reasoningEngines/7806084231343374336/sandboxEnvironments/4909074776682659840"

MODEL = "gemini-3.8-flash"


def _get_firestore_client() -> firestore.Client:
    """Returns a Firestore client initialized with hardcoded project ID."""
    return firestore.Client(project=PROJECT_ID)


def list_cities() -> list[dict]:
    """Retrieves all city destinations stored in the Firestore cities collection.

    Returns:
        A list of dictionaries representing each city's profile, including
        typical climate, seasonal temperatures, best travel season, and tags.
    """
    db = _get_firestore_client()
    docs = db.collection(COLLECTION_NAME).stream()
    results = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        results.append(data)
    return results


def get_city_details(city_id: str) -> dict:
    """Fetches details for a specific city from the Firestore cities collection.

    Args:
        city_id: The identifier or slug of the city (e.g. 'new-york', 'san-francisco', 'tokyo', 'paris').

    Returns:
        A dictionary containing the city's attributes, or an error message if not found.
    """
    db = _get_firestore_client()
    normalized_id = city_id.strip().lower().replace(" ", "-")
    doc = db.collection(COLLECTION_NAME).document(normalized_id).get()
    if doc.exists:
        data = doc.to_dict()
        data["id"] = doc.id
        return data
    return {"error": f"City '{city_id}' not found in database."}


def save_city_details(
    name: str,
    country: str,
    typical_climate: str,
    summer_temp_f: int,
    winter_temp_f: int,
    best_season: str,
    description: str,
    tags: str = "",
) -> dict:
    """Adds or updates a city destination record in Firestore.

    Args:
        name: Name of the city (e.g. 'London').
        country: Country the city is located in (e.g. 'United Kingdom').
        typical_climate: Climate classification (e.g. 'Temperate Oceanic').
        summer_temp_f: Average summer temperature in Fahrenheit (e.g. 73).
        winter_temp_f: Average winter temperature in Fahrenheit (e.g. 40).
        best_season: Recommended time of year to visit (e.g. 'Summer', 'Late Spring').
        description: Brief description or travel summary.
        tags: Comma-separated tags (e.g. 'history, museums, architecture').

    Returns:
        A confirmation dictionary with the saved document ID.
    """
    db = _get_firestore_client()
    doc_id = name.strip().lower().replace(" ", "-")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    record = {
        "name": name.strip(),
        "country": country.strip(),
        "typical_climate": typical_climate.strip(),
        "summer_temp_f": int(summer_temp_f),
        "winter_temp_f": int(winter_temp_f),
        "best_season": best_season.strip(),
        "description": description.strip(),
        "tags": tag_list,
    }
    db.collection(COLLECTION_NAME).document(doc_id).set(record)
    return {"status": "success", "message": f"Saved city '{name}' successfully.", "id": doc_id}


def get_weather(query: str) -> str:
    """Fetches real-time live weather conditions for a given city or location using Open-Meteo.

    Args:
        query: The city or location name (e.g., 'Paris', 'Tokyo', 'San Francisco', 'New York').

    Returns:
        A string summarizing real-time temperature, apparent temperature, humidity, wind speed, and precipitation.
    """
    try:
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(query)}&count=1&language=en&format=json"
        geo_req = urllib.request.Request(geo_url, headers={"User-Agent": "weather-agent/1.0"})
        with urllib.request.urlopen(geo_req, timeout=8) as resp:
            geo_data = json.loads(resp.read().decode("utf-8"))

        results = geo_data.get("results")
        if not results:
            return f"Could not find coordinates for location: {query}."

        place = results[0]
        lat, lon = place["latitude"], place["longitude"]
        place_name = place.get("name", query)
        country = place.get("country", "")

        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
            "&temperature_unit=fahrenheit&wind_speed_unit=mph"
        )
        weather_req = urllib.request.Request(weather_url, headers={"User-Agent": "weather-agent/1.0"})
        with urllib.request.urlopen(weather_req, timeout=8) as resp:
            w_data = json.loads(resp.read().decode("utf-8"))

        current = w_data.get("current", {})
        temp = current.get("temperature_2m")
        feels_like = current.get("apparent_temperature")
        humidity = current.get("relative_humidity_2m")
        wind = current.get("wind_speed_10m")
        precip = current.get("precipitation", 0.0)

        # Basic WMO weather code mapping
        wmo_code = current.get("weather_code", 0)
        condition = "Clear sky"
        if wmo_code in [1, 2, 3]:
            condition = "Mainly clear / Partly cloudy"
        elif wmo_code in [45, 48]:
            condition = "Foggy"
        elif wmo_code in [51, 53, 55, 61, 63, 65, 80, 81, 82]:
            condition = "Rainy"
        elif wmo_code in [71, 73, 75, 85, 86]:
            condition = "Snowy"
        elif wmo_code >= 95:
            condition = "Thunderstorm"

        return (
            f"Current live weather for {place_name}, {country}: {condition}. "
            f"Temperature: {temp}°F (feels like {feels_like}°F), Humidity: {humidity}%, "
            f"Wind: {wind} mph, Precipitation: {precip} in."
        )
    except Exception as e:
        return f"Failed to retrieve live weather for '{query}': {e}"


def get_current_time(query: str) -> str:
    """Simulates getting the current time for a city.

    Args:
        city: The name of the city to get the current time for.

    Returns:
        A string with the current time information.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        tz_identifier = "America/Los_Angeles"
    else:
        return f"Sorry, I don't have timezone information for query: {query}."

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"The current time for query {query} is {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


def search_city_attractions(city: str, limit: int = 5) -> list[dict]:
    """Finds real-world tourist attractions and notable places for a given city via OpenStreetMap Nominatim API.

    Args:
        city: The name of the city to discover attractions for (e.g. 'Paris', 'Tokyo', 'San Francisco').
        limit: Maximum number of points of interest to return (default: 5).

    Returns:
        A list of attraction dictionaries containing name, category, and address.
    """
    try:
        headers = {"User-Agent": "weather-city-guide-agent/1.0 (google-workshop-demo)"}
        query_str = f"attractions in {city}"
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query_str)}&format=json&limit={limit}&addressdetails=1"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        attractions = []
        for item in data:
            name = item.get("name") or item.get("display_name", "").split(",")[0]
            attractions.append({
                "name": name,
                "category": item.get("class", "attraction"),
                "type": item.get("type", "tourism"),
                "address": item.get("display_name"),
            })
        return attractions if attractions else [{"message": f"No specific attractions found for {city}."}]
    except Exception as e:
        return [{"error": f"Failed to fetch attractions for {city}: {e}"}]


def geocode_address(address: str) -> dict:
    """Converts a street address or location name into geographic latitude and longitude coordinates using Google Geocoding API.

    Args:
        address: The address or place to geocode (e.g. '1600 Amphitheatre Parkway, Mountain View, CA' or 'Empire State Building, NY').

    Returns:
        A dictionary containing the formatted address, location (latitude and longitude), and place ID.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key or api_key == "PASTE_KEY_HERE":
        return {"error": "GOOGLE_MAPS_API_KEY is not set or contains placeholder. Please set your key in .env."}

    try:
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={urllib.parse.quote(address)}&key={api_key}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if data.get("status") != "OK" or not data.get("results"):
            return {"error": f"Geocoding failed with status: {data.get('status')}", "message": data.get("error_message")}

        result = data["results"][0]
        location = result.get("geometry", {}).get("location", {})
        return {
            "formatted_address": result.get("formatted_address"),
            "latitude": location.get("lat"),
            "longitude": location.get("lng"),
            "place_id": result.get("place_id"),
        }
    except Exception as e:
        return {"error": f"Geocoding request failed: {e}"}


def search_nearby_places(latitude: float, longitude: float, place_type: str = "tourist_attraction", radius_meters: float = 2000.0, max_results: int = 5) -> list[dict]:
    """Finds nearby places of a given type around a coordinate using Google Places API (New) searchNearby.

    Args:
        latitude: Latitude coordinate of the center point.
        longitude: Longitude coordinate of the center point.
        place_type: Primary place type to search for (e.g. 'tourist_attraction', 'museum', 'restaurant', 'cafe', 'park').
        radius_meters: Search radius in meters (default 2000.0 meters).
        max_results: Maximum number of places to return (default 5, max 20).

    Returns:
        A list of place dictionaries with name, formatted address, and location coordinates.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key or api_key == "PASTE_KEY_HERE":
        return [{"error": "GOOGLE_MAPS_API_KEY is not set or contains placeholder. Please set your key in .env."}]

    try:
        url = "https://places.googleapis.com/v1/places:searchNearby"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location,places.primaryType",
        }
        payload = {
            "includedPrimaryTypes": [place_type],
            "maxResultCount": min(int(max_results), 20),
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": float(latitude),
                        "longitude": float(longitude),
                    },
                    "radius": float(radius_meters),
                }
            },
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        places = []
        for p in data.get("places", []):
            display_name = p.get("displayName", {}).get("text", "")
            loc = p.get("location", {})
            places.append({
                "name": display_name,
                "address": p.get("formattedAddress"),
                "primary_type": p.get("primaryType"),
                "latitude": loc.get("latitude"),
                "longitude": loc.get("longitude"),
            })
        return places if places else [{"message": f"No nearby places found of type '{place_type}'."}]
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        return [{"error": f"Places API HTTP error {e.code}: {error_body}"}]
    except Exception as e:
        return [{"error": f"Places API search failed: {e}"}]


def generate_destination_image(city_or_landmark: str, description: str, tool_context: ToolContext) -> dict:
    """Generates an image for a city, landmark, or scenic view using gemini-3.1-flash-lite-image in the global region.
    Saves the image as a session artifact and uploads it to Cloud Storage for public access.

    Args:
        city_or_landmark: Name of the city or landmark (e.g. 'Tokyo', 'Mount Fuji', 'Central Park, New York').
        description: Description of the scene to generate (e.g. 'cherry blossoms in spring with sunset', 'autumn foliage in the park').
        tool_context: ADK ToolContext used to save session artifacts.

    Returns:
        A dictionary containing the public Cloud Storage image URL, artifact filename, and status.
    """
    try:
        # 1. Generate image using gemini-3.1-flash-lite-image in global region
        client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")
        prompt = f"A vibrant, beautiful photograph of {city_or_landmark}: {description}"
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=[types.Modality.IMAGE],
            ),
        )

        image_bytes = None
        mime_type = "image/jpeg"
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                image_bytes = part.inline_data.data
                mime_type = part.inline_data.mime_type or "image/jpeg"
                break

        if not image_bytes:
            return {"error": f"No image was generated by gemini-3.1-flash-lite-image for {city_or_landmark}."}

        # Determine extension
        ext = "jpg" if "jpeg" in mime_type.lower() else "png"
        safe_name = city_or_landmark.strip().lower().replace(" ", "-").replace(",", "")
        filename = f"{safe_name}_{uuid.uuid4().hex[:8]}.{ext}"

        # 2. Save image as an artifact in ToolContext for Playground's Artifacts panel
        artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # 3. Upload image bytes directly to public Cloud Storage bucket
        storage_client = storage.Client(project=PROJECT_ID)
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"
        return {
            "status": "success",
            "city_or_landmark": city_or_landmark,
            "filename": filename,
            "public_url": public_url,
            "message": f"Image generated and uploaded successfully. Public URL: {public_url}",
        }
    except Exception as e:
        return {"error": f"Failed to generate destination image: {e}"}


async def generate_memories_callback(callback_context: CallbackContext):
    """WRITE: after each turn, send the session to Memory Bank for extraction."""
    await callback_context.add_session_to_memory()
    return None


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are a helpful travel and weather assistant. "
        "You remember the user's stated preferences, facts, and especially all user allergies, dietary restrictions, and sensitivities from previous conversations, and always use them to personalize your recommendations and keep dining/travel suggestions safe. "
        "You have access to a Firestore database of cities with climate data, seasonal temps, and travel tags. "
        "Use list_cities, get_city_details, and save_city_details to read and write city destination information, "
        "get_weather for real-time live weather, get_current_time for local time, "
        "search_city_attractions to fetch points of interest from OpenStreetMap, "
        "geocode_address to turn an address or landmark into exact geographic coordinates via Google Geocoding API, "
        "search_nearby_places to discover nearby sights, restaurants, or attractions using Google Places API (New), "
        "generate_destination_image to generate scenic illustrations and postcards for any destination or landmark, "
        "and you can execute Python code safely in your Agent Engine sandbox to perform calculations, data analysis, or conversions."
    ),
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        "{\"Image\": {\"url\": {\"literalString\": \"https://...\"}}}. Never point an "
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)

root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    code_executor=AgentEngineSandboxCodeExecutor(
        sandbox_resource_name=SANDBOX_RESOURCE_NAME,
    ),
    instruction=instruction,
    tools=[
        PreloadMemoryTool(),
        list_cities,
        get_city_details,
        save_city_details,
        get_weather,
        get_current_time,
        search_city_attractions,
        geocode_address,
        search_nearby_places,
        generate_destination_image,
    ],
    after_model_callback=a2ui_callback,
    after_agent_callback=generate_memories_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
