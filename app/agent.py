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

import os
from dotenv import load_dotenv

# Ensure environment variables are loaded and set for Vertex AI prior to other imports
load_dotenv()
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
os.environ["GOOGLE_CLOUD_PROJECT"] = "qwiklabs-gcp-03-fc83cd0fca08"
os.environ["GOOGLE_CLOUD_LOCATION"] = "us-east1"

import datetime
import json
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo
from google.cloud import firestore, storage
from google import genai

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager

from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.genai import types

from app.a2ui_utils import a2ui_callback

# IMPORTANT: Hardcode project ID and Cloud Storage bucket string
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-03-fc83cd0fca08"
GCS_BUCKET_NAME = "wanderlust-concierge-media-qwiklabs-gcp-03-fc83cd0fca08"

# Resolve Agent Engine resource name from deployment_metadata.json
DEPLOYMENT_METADATA_PATH = os.path.join(os.path.dirname(__file__), "..", "deployment_metadata.json")
agent_engine_resource_name = "projects/452488777414/locations/us-east1/reasoningEngines/8880413469430513664"

if os.path.exists(DEPLOYMENT_METADATA_PATH):
    try:
        with open(DEPLOYMENT_METADATA_PATH, "r") as f:
            metadata = json.load(f)
            agent_engine_resource_name = metadata.get("remote_agent_runtime_id", agent_engine_resource_name)
    except Exception:
        pass

code_executor = AgentEngineSandboxCodeExecutor(
    agent_engine_resource_name=agent_engine_resource_name
)


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are Wanderlust Concierge, a specialized travel assistant. "
        "You remember all user search queries, location searches, travel preferences, and facts from previous conversations and use them to personalize your responses. "
        "Whenever the user searches for a destination, attraction, or location, explicitly acknowledge and log their search terms and preferences so they are permanently remembered across sessions. "
        "Use your travel tools (`generate_destination_illustration`, `geocode_address`, `find_nearby_places`, "
        "`fetch_destination_wiki_summary`, `search_destinations`, `get_destination_details`, `save_destination`, `generate_travel_poster`) "
        "and sandboxed Python code execution to safely run Python calculations (like budget math and itineraries), "
        "look up locations, find nearby attractions with Google Maps, fetch destination facts from Wikipedia, "
        "search internal travel records, save new locations, and generate custom travel illustrations and posters."
    ),
    workflow_description="Analyze the user request, run tools or sandboxed Python calculations when appropriate, and return structured A2UI visual cards when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        '{"Image": {"url": {"literalString": "https://..."}}}. Never point an '
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


async def generate_memories_callback(callback_context: CallbackContext):
    """Callback triggered after each turn to save all user searches, preferences, and session events into Vertex AI Memory Bank."""
    await callback_context.add_session_to_memory()
    return None


def get_firestore_client() -> firestore.Client:
    """Returns a Firestore client initialized with the hardcoded GCP project ID."""
    return firestore.Client(project=FIRESTORE_PROJECT_ID)


def generate_destination_illustration(
    destination_name: str,
    tool_context: ToolContext,
    style_description: str = "vibrant travel illustration"
) -> str:
    """Generate a travel illustration for a destination using gemini-3.1-flash-lite-image in the global region.

    Saves the image as a Playground artifact and uploads it to public Cloud Storage, returning the public HTTPS URL.

    Args:
        destination_name: Name of the travel destination or attraction (e.g. 'Kyoto', 'Paris', 'Santorini').
        tool_context: ADK ToolContext injected automatically by the framework.
        style_description: Optional visual artistic style description (default: 'vibrant travel illustration').

    Returns:
        The public HTTPS image URL from Cloud Storage (https://storage.googleapis.com/<bucket>/<object>).
    """
    try:
        genai_client = genai.Client(vertexai=True, project=FIRESTORE_PROJECT_ID, location="global")
        prompt = f"Generate a {style_description} of {destination_name} highlighting its landmark architecture and scenery."

        response = genai_client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE"])
        )

        for part in response.candidates[0].content.parts:
            if part.inline_data:
                image_bytes = part.inline_data.data
                mime_type = part.inline_data.mime_type or "image/jpeg"
                ext = "png" if "png" in mime_type else "jpg"
                clean_name = destination_name.lower().replace(" ", "-")
                filename = f"{clean_name}-illustration.{ext}"

                # 1. Save as ADK artifact for Playground Artifacts panel
                artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
                tool_context.save_artifact(filename=filename, artifact=artifact_part)

                # 2. Upload to public Cloud Storage bucket
                storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
                bucket = storage_client.bucket(GCS_BUCKET_NAME)
                blob = bucket.blob(f"illustrations/{filename}")
                blob.upload_from_string(image_bytes, content_type=mime_type)

                public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/illustrations/{filename}"
                return public_url

        return f"Could not generate image data for {destination_name}."
    except Exception as e:
        return f"Error generating destination illustration for {destination_name}: {str(e)}"


def geocode_address(address: str) -> dict:
    """Convert an address or city name into geographic coordinates (latitude and longitude) using Google Geocoding API.

    Args:
        address: The address, place name, or city to geocode (e.g. 'Kyoto Station', 'Eiffel Tower', 'Santorini').

    Returns:
        A dictionary containing formatted address, location coordinates (latitude, longitude), and place ID.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return {"error": "GOOGLE_MAPS_API_KEY environment variable is missing."}

    try:
        encoded_address = urllib.parse.quote(address.strip())
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded_address}&key={api_key}"

        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            if data.get("status") == "OK" and data.get("results"):
                first_result = data["results"][0]
                loc = first_result["geometry"]["location"]
                return {
                    "address": first_result.get("formatted_address"),
                    "location": {"latitude": loc["lat"], "longitude": loc["lng"]},
                    "place_id": first_result.get("place_id")
                }
            return {"error": f"Geocoding failed for '{address}': {data.get('status')}"}
    except Exception as e:
        return {"error": f"Error calling Geocoding API for '{address}': {str(e)}"}


def find_nearby_places(latitude: float, longitude: float, place_type: str = "tourist_attraction", radius_meters: float = 5000.0) -> list[dict]:
    """Find nearby points of interest or places around given coordinates using Google Places API (New).

    Args:
        latitude: Latitude of the center location.
        longitude: Longitude of the center location.
        place_type: Type of place to search for (e.g. 'tourist_attraction', 'restaurant', 'museum', 'lodging', 'park').
        radius_meters: Search radius in meters (default 5000.0).

    Returns:
        List of matching nearby places with name, formatted address, location coordinates, rating, and types.
    """
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        return [{"error": "GOOGLE_MAPS_API_KEY environment variable is missing."}]

    try:
        url = "https://places.googleapis.com/v1/places:searchNearby"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location,places.rating,places.types"
        }

        payload = {
            "includedTypes": [place_type],
            "maxResultCount": 5,
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": latitude,
                        "longitude": longitude
                    },
                    "radius": radius_meters
                }
            }
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            places = data.get("places", [])
            results = []
            for p in places:
                results.append({
                    "name": p.get("displayName", {}).get("text"),
                    "address": p.get("formattedAddress"),
                    "location": p.get("location"),
                    "rating": p.get("rating"),
                    "types": p.get("types")
                })
            return results
    except Exception as e:
        return [{"error": f"Error calling Places API (New): {str(e)}"}]


def fetch_destination_wiki_summary(destination_name: str) -> dict:
    """Fetch real-time destination summary, facts, and image info from Wikipedia REST API.

    Args:
        destination_name: Name of the travel destination or city (e.g. 'Kyoto', 'Paris', 'Santorini', 'Reykjavik').

    Returns:
        A dictionary containing destination summary extract, page title, Wikipedia URL, and thumbnail image URL.
    """
    try:
        user_agent = os.getenv("WIKIPEDIA_USER_AGENT", "WanderlustConcierge/1.0 (contact: info@wanderlust.example.com)")
        api_key = os.getenv("WIKIPEDIA_API_KEY")  # Read optional API key from env var if provided

        encoded_name = urllib.parse.quote(destination_name.strip())
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded_name}"

        headers = {"User-Agent": user_agent}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            return {
                "destination": destination_name,
                "title": data.get("title"),
                "extract": data.get("extract"),
                "wikipedia_url": data.get("content_urls", {}).get("desktop", {}).get("page"),
                "thumbnail_url": data.get("thumbnail", {}).get("source")
            }
    except Exception as e:
        return {"error": f"Failed to fetch Wikipedia summary for '{destination_name}': {str(e)}"}


def generate_travel_poster(destination_name: str, style_description: str = "vintage retro travel poster") -> str:
    """Generate a stylized travel poster for a destination and upload it to public Cloud Storage.

    Args:
        destination_name: Name of the destination city or location (e.g. 'Kyoto', 'Paris', 'Santorini').
        style_description: Visual artistic style description (default: 'vintage retro travel poster').

    Returns:
        The public HTTPS image URL of the generated travel poster.
    """
    try:
        genai_client = genai.Client(vertexai=True, project=FIRESTORE_PROJECT_ID, location="us-central1")
        prompt = f"Generate a {style_description} for {destination_name} with landmark art, vibrant harmonious colors, and bold title typography."

        response = genai_client.models.generate_content(
            model="gemini-2.5-flash-image",
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE"])
        )

        for part in response.candidates[0].content.parts:
            if part.inline_data:
                image_bytes = part.inline_data.data
                mime_type = part.inline_data.mime_type or "image/png"
                ext = "png" if "png" in mime_type else "jpg"
                filename = f"{destination_name.lower().replace(' ', '-')}.{ext}"

                storage_client = storage.Client(project=FIRESTORE_PROJECT_ID)
                bucket = storage_client.bucket(GCS_BUCKET_NAME)
                blob = bucket.blob(f"posters/{filename}")
                blob.upload_from_string(image_bytes, content_type=mime_type)

                public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/posters/{filename}"
                return f"Successfully generated travel poster for {destination_name}: {public_url}"

        return f"Could not generate poster image for {destination_name}."
    except Exception as e:
        return f"Error generating travel poster for {destination_name}: {str(e)}"


def search_destinations(category: str = None) -> list[dict]:
    """Search travel destinations stored in the Firestore database.

    Args:
        category: Optional category filter (e.g. 'Cultural', 'Beach', 'Romantic & Culinary', 'Nature & Adventure').

    Returns:
        List of matching destination records with city, country, category, cost, and description.
    """
    db = get_firestore_client()
    docs = db.collection("destinations").stream()
    results = []

    for doc in docs:
        data = doc.to_dict()
        if category:
            if category.lower() in data.get("category", "").lower():
                results.append(data)
        else:
            results.append(data)

    return results


def get_destination_details(city_or_id: str) -> dict:
    """Get detailed travel information for a specific destination from Firestore.

    Args:
        city_or_id: The name or ID of the city/destination (e.g. 'Kyoto', 'Paris', 'Santorini', 'Reykjavik').

    Returns:
        A dictionary containing destination details including highlights, costs, best season, and description.
    """
    db = get_firestore_client()
    query = city_or_id.lower().strip()

    # Direct document lookup
    doc = db.collection("destinations").document(query).get()
    if doc.exists:
        return doc.to_dict()

    # Search by city name
    docs = db.collection("destinations").stream()
    for d in docs:
        data = d.to_dict()
        if data.get("city", "").lower() == query or query in data.get("city", "").lower():
            return data

    return {"error": f"No destination details found for '{city_or_id}'."}


def save_destination(
    city: str,
    country: str,
    description: str,
    category: str = "General",
    best_season: str = "Spring",
    average_daily_cost_usd: int = 200,
    highlights: list[str] = None
) -> str:
    """Save or update a travel destination in the Firestore database.

    Args:
        city: City name (e.g., 'Tokyo').
        country: Country name (e.g., 'Japan').
        description: A brief summary of the destination.
        category: Category or travel style (e.g., 'Cultural', 'Modern & Tech', 'Beach').
        best_season: Best season to visit.
        average_daily_cost_usd: Estimated average daily cost in USD.
        highlights: List of key attractions or top things to do.

    Returns:
        A success message with the saved destination ID.
    """
    db = get_firestore_client()
    doc_id = city.lower().replace(" ", "-")

    destination_data = {
        "id": doc_id,
        "city": city,
        "country": country,
        "description": description,
        "category": category,
        "best_season": best_season,
        "average_daily_cost_usd": average_daily_cost_usd,
        "highlights": highlights or []
    }

    db.collection("destinations").document(doc_id).set(destination_data)
    return f"Successfully saved destination '{city}' ({doc_id}) to Firestore."


def get_weather(query: str) -> str:
    """Simulates getting weather information for a location.

    Args:
        query: A string containing the location to get weather information for.

    Returns:
        A string with the simulated weather information for the queried location.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        return "It's 60 degrees and foggy."
    return "It's 90 degrees and sunny."


def get_current_time(query: str) -> str:
    """Simulates getting the current time for a city.

    Args:
        query: The name of the city to get the current time for.

    Returns:
        A string with the current time information.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        tz_identifier = "America/Los_Angeles"
    elif "tokyo" in query.lower():
        tz_identifier = "Asia/Tokyo"
    elif "paris" in query.lower():
        tz_identifier = "Europe/Paris"
    else:
        return f"Sorry, I don't have timezone information for query: {query}."

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"The current time for query {query} is {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-2.5-flash",
        client_kwargs={
            "vertexai": True,
            "project": FIRESTORE_PROJECT_ID,
            "location": "us-east1",
        },
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=instruction,
    code_executor=code_executor,
    tools=[
        PreloadMemoryTool(),
        generate_destination_illustration,
        geocode_address,
        find_nearby_places,
        fetch_destination_wiki_summary,
        generate_travel_poster,
        search_destinations,
        get_destination_details,
        save_destination,
        get_weather,
        get_current_time
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
