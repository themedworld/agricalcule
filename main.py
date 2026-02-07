import asyncio
import os
import httpx
from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from datetime import datetime
from jose import jwt, JWTError
from database import db
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware

# ================== APP ==================
app = FastAPI()

origins = [
    "http://localhost:3000",
    "http://192.168.56.1:3000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

load_dotenv()

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"

security = HTTPBearer()

# ================== AUTH ==================
def verify_token(credentials: HTTPAuthorizationCredentials):
    try:
        payload = jwt.decode(
            credentials.credentials,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            options={"verify_sub": False},
        )

        return {
            "id": int(payload["sub"]),
            "email": payload["email"],
            "role": payload["role"],
        }

    except Exception:
        raise HTTPException(status_code=401, detail="Token invalide ou expiré")

# ================== WEATHER ==================
async def fetch_hourly_weather(lat: float, lon: float):
    url = (
        f"https://api.openweathermap.org/data/2.5/forecast"
        f"?lat={lat}&lon={lon}&appid={OPENWEATHER_API_KEY}&units=metric"
    )

    async with httpx.AsyncClient() as client:
        res = await client.get(url)

    if res.status_code != 200:
        raise HTTPException(status_code=500, detail="Erreur API météo")

    data = res.json()
    hourly = []

    for item in data["list"][:48]:  # 48 x 3h ≈ 6 jours
        precipitation = item.get("rain", {}).get("3h", 0)

        hourly.append({
            "time": item["dt_txt"],
            "temp": item["main"]["temp"],
            "humidity": item["main"]["humidity"],
            "precipitation": precipitation,
            "is_wet": item["main"]["humidity"] >= 90 or precipitation > 0
        })

    return hourly

# ================== SCORING LOGIC ==================
def clamp(score):
    return max(0, min(100, score))

def score_rouille_brune(hours):
    score = 0
    consecutive = 0

    for h in hours[:24]:
        if 15 <= h["temp"] <= 25 and h["humidity"] >= 85:
            consecutive += 1
            score += 5
            if h["is_wet"]:
                score += 3
        else:
            consecutive = 0

        if consecutive >= 6:
            score += 20

    return clamp(score)

def score_rouille_noire(hours):
    score = 0
    consecutive = 0

    for h in hours[:24]:
        if 18 <= h["temp"] <= 30 and h["humidity"] >= 90:
            consecutive += 1
            score += 6
        else:
            consecutive = 0

        if consecutive >= 8:
            score += 25

    return clamp(score)

def score_rouille_jaune(hours):
    score = 0
    consecutive = 0

    for h in hours[:24]:
        if 7 <= h["temp"] <= 18 and h["humidity"] >= 87:
            consecutive += 1
            score += 5
            if h["is_wet"]:
                score += 4
        else:
            consecutive = 0

        if consecutive >= 5:
            score += 20

    return clamp(score)

def score_septoriose(hours):
    score = 0
    wet_hours = 0

    for h in hours[:48]:
        if 15 <= h["temp"] <= 20 and h["is_wet"]:
            wet_hours += 1
            score += 4
        else:
            wet_hours = 0

        if wet_hours >= 20:
            score += 30

    return clamp(score)

def predict_future_risk(hourly):
    return {
        "rouille_brune": score_rouille_brune(hourly),
        "rouille_noire": score_rouille_noire(hourly),
        "rouille_jaune": score_rouille_jaune(hourly),
        "septoriose": score_septoriose(hourly),
    }

# ================== MONGO UPDATE ==================
async def update_terrain_with_weather(terrain):
    lat, lon = terrain.get("latitude"), terrain.get("longitude")
    if not lat or not lon:
        return

    hourly_weather = await fetch_hourly_weather(lat, lon)
    risks = predict_future_risk(hourly_weather)

    await db["terrainmongos"].update_one(
        {"_id": terrain["_id"]},
        {"$set": {
            "indicators": {
                "weather_forecast": hourly_weather,
                "risks": risks,
                "lastUpdate": datetime.utcnow().isoformat()
            }
        }}
    )

    print(f"✅ Terrain {terrain['terrainId']} mis à jour")

# ================== BACKGROUND TASKS ==================
async def update_all_terrainmongos_once():
    async for terrain in db["terrainmongos"].find({}):
        await update_terrain_with_weather(terrain)

async def update_all_terrainmongos_periodically():
    while True:
        async for terrain in db["terrainmongos"].find({}):
            await update_terrain_with_weather(terrain)
        await asyncio.sleep(3600)

@app.on_event("startup")
async def startup():
    asyncio.create_task(update_all_terrainmongos_once())
    asyncio.create_task(update_all_terrainmongos_periodically())

# ================== API ==================
@app.get("/")
async def root():
    return {"message": "Service météo & maladies actif"}

@app.get("/terrainmongos/{terrain_id}")
async def get_terrain(
    terrain_id: int,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    user = verify_token(credentials)

    terrain = await db["terrainmongos"].find_one({"terrainId": terrain_id})
    if not terrain:
        raise HTTPException(status_code=404, detail="Terrain introuvable")

    if int(terrain.get("clientId", 0)) != user["id"]:
        raise HTTPException(status_code=403, detail="Accès interdit")

    terrain["_id"] = str(terrain["_id"])
    return terrain
