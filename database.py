import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# Charger les variables du fichier .env
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DBNAME = os.getenv("MONGO_DBNAME")

client = AsyncIOMotorClient(MONGO_URI)
db = client[MONGO_DBNAME]
