"""Seed Firestore with cities catalog for weather-agent."""
from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-04-78ac92e9286e"
COLLECTION_NAME = "cities"

SEEDED_CITIES = [
    {
        "id": "new-york",
        "name": "New York",
        "country": "United States",
        "typical_climate": "Continental",
        "summer_temp_f": 85,
        "winter_temp_f": 32,
        "best_season": "Autumn",
        "tags": ["culture", "skyline", "walkable", "museums"],
        "description": "Vibrant metropolis with distinct four seasons and world-class cultural institutions."
    },
    {
        "id": "san-francisco",
        "name": "San Francisco",
        "country": "United States",
        "typical_climate": "Mediterranean / Coastal Fog",
        "summer_temp_f": 68,
        "winter_temp_f": 52,
        "best_season": "Fall",
        "tags": ["fog", "ocean", "tech", "hills"],
        "description": "Breezy coastal city famous for microclimates, cable cars, and the Golden Gate."
    },
    {
        "id": "tokyo",
        "name": "Tokyo",
        "country": "Japan",
        "typical_climate": "Humid Subtropical",
        "summer_temp_f": 88,
        "winter_temp_f": 42,
        "best_season": "Spring",
        "tags": ["food", "gardens", "transit", "cherry-blossoms"],
        "description": "Dynamic mega-city blending ultramodern technology with tranquil historic temples."
    },
    {
        "id": "paris",
        "name": "Paris",
        "country": "France",
        "typical_climate": "Oceanic",
        "summer_temp_f": 78,
        "winter_temp_f": 38,
        "best_season": "Spring",
        "tags": ["cafes", "architecture", "art", "romance"],
        "description": "The City of Light, offering scenic river strolls, historic bistros, and iconic monuments."
    }
]

def seed():
    print(f"Connecting to Firestore with hardcoded project ID: {PROJECT_ID}...")
    db = firestore.Client(project=PROJECT_ID)
    collection = db.collection(COLLECTION_NAME)

    for item in SEEDED_CITIES:
        doc_id = item["id"]
        data = {k: v for k, v in item.items() if k != "id"}
        collection.document(doc_id).set(data)
        print(f"✓ Seeded city: {item['name']} (ID: {doc_id})")

    print(f"\nAll {len(SEEDED_CITIES)} items successfully seeded into collection '{COLLECTION_NAME}'!")

if __name__ == "__main__":
    seed()
