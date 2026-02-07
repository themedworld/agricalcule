from pydantic import BaseModel
from typing import Optional, Dict

class Terrain(BaseModel):
    terrainId: int
    clientId: int
    latitude: float
    longitude: float
    surface: float
    description: Optional[str] = None
    culture: Optional[str] = None
    indicators: Optional[Dict] = {}
