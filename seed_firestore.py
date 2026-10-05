# Seed script for Firestore collection 'destinations'
from google.cloud import firestore

# IMPORTANT: Hardcoded Project ID string as required for Agent Platform compatibility
FIRESTORE_PROJECT_ID = "qwiklabs-gcp-03-fc83cd0fca08"

def seed():
    db = firestore.Client(project=FIRESTORE_PROJECT_ID)
    destinations_ref = db.collection("destinations")

    sample_destinations = [
        {
            "id": "kyoto",
            "city": "Kyoto",
            "country": "Japan",
            "category": "Cultural",
            "best_season": "Spring",
            "average_daily_cost_usd": 180,
            "description": "Historic city famous for classical Buddhist temples, gardens, imperial palaces, and bamboo groves.",
            "highlights": ["Fushimi Inari Shrine", "Arashiyama Bamboo Grove", "Kinkaku-ji (Golden Pavilion)"]
        },
        {
            "id": "paris",
            "city": "Paris",
            "country": "France",
            "category": "Romantic & Culinary",
            "best_season": "Autumn",
            "average_daily_cost_usd": 250,
            "description": "Global center for art, fashion, gastronomy, and culture with iconic landmarks and world-class cuisine.",
            "highlights": ["Eiffel Tower", "Louvre Museum", "Montmartre & Sacré-Cœur"]
        },
        {
            "id": "santorini",
            "city": "Santorini",
            "country": "Greece",
            "category": "Beach & Scenic",
            "best_season": "Summer",
            "average_daily_cost_usd": 220,
            "description": "Stunning Cyclades island in the Aegean Sea known for whitewashed cliffside villages and sunsets.",
            "highlights": ["Oia Sunset Viewpoint", "Red Beach", "Akrotiri Archaeological Site"]
        },
        {
            "id": "reykjavik",
            "city": "Reykjavik",
            "country": "Iceland",
            "category": "Nature & Adventure",
            "best_season": "Winter",
            "average_daily_cost_usd": 210,
            "description": "Coastal capital of Iceland, gateway to geothermal lagoons, Northern Lights, and glaciers.",
            "highlights": ["Blue Lagoon", "Golden Circle", "Hallgrímskirkja"]
        }
    ]

    print(f"Seeding Firestore collection 'destinations' in project '{FIRESTORE_PROJECT_ID}'...")
    for dest in sample_destinations:
        doc_id = dest["id"]
        destinations_ref.document(doc_id).set(dest)
        print(f"  ✓ Added destination: {dest['city']} ({doc_id})")

    print("Firestore seeding completed successfully!")

if __name__ == "__main__":
    seed()
