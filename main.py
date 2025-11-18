import os
from datetime import datetime, timezone, date
from typing import List, Optional, Dict, Any

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents

app = FastAPI(title="FitTrack API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class FoodItem(BaseModel):
    food_name: str
    calories: float
    protein_g: float = 0
    carbohydrates_total_g: float = 0
    fat_total_g: float = 0
    serving_qty: Optional[float] = 1
    serving_unit: Optional[str] = None


class DiaryFoodCreate(BaseModel):
    food_name: str
    calories: float
    protein_g: float = 0
    carbohydrates_total_g: float = 0
    fat_total_g: float = 0
    consumed_at: Optional[str] = None  # ISO date (YYYY-MM-DD)


class WorkoutItem(BaseModel):
    name: str
    duration: Optional[int] = 30
    calories: Optional[int] = 0
    performed_at: Optional[str] = None  # ISO date


@app.get("/")
def read_root():
    return {"message": "FitTrack backend running"}


@app.get("/api/food/search")
def search_food(q: str = Query(..., min_length=1)):
    """Search foods via Nutritionix if keys are set, otherwise return sample data."""
    app_id = os.getenv("NUTRITIONIX_APP_ID")
    app_key = os.getenv("NUTRITIONIX_API_KEY")

    # If keys provided, use natural language endpoint to quickly get macros
    if app_id and app_key:
        try:
            url = "https://trackapi.nutritionix.com/v2/natural/nutrients"
            headers = {
                "x-app-id": app_id,
                "x-app-key": app_key,
                "Content-Type": "application/json",
            }
            payload = {"query": q}
            r = requests.post(url, json=payload, headers=headers, timeout=12)
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Nutritionix error: {r.text[:120]}")
            data = r.json()
            items: List[Dict[str, Any]] = []
            for f in data.get("foods", []):
                items.append(
                    {
                        "food_name": f.get("food_name"),
                        "calories": f.get("nf_calories", 0),
                        "protein_g": f.get("nf_protein", 0),
                        "carbohydrates_total_g": f.get("nf_total_carbohydrate", 0),
                        "fat_total_g": f.get("nf_total_fat", 0),
                        "serving_qty": f.get("serving_qty"),
                        "serving_unit": f.get("serving_unit"),
                    }
                )
            return {"items": items}
        except requests.RequestException as e:
            # Fallback to sample data
            pass

    # Fallback sample items (no keys)
    sample = [
        {
            "food_name": "Petto di pollo",
            "calories": 165,
            "protein_g": 31,
            "carbohydrates_total_g": 0,
            "fat_total_g": 3.6,
        },
        {
            "food_name": "Riso basmati (100g)",
            "calories": 130,
            "protein_g": 2.7,
            "carbohydrates_total_g": 28,
            "fat_total_g": 0.3,
        },
        {
            "food_name": "Avocado (1/2)",
            "calories": 120,
            "protein_g": 1.5,
            "carbohydrates_total_g": 6,
            "fat_total_g": 10,
        },
    ]
    # Filter by query locally
    filtered = [s for s in sample if q.lower() in s["food_name"].lower()]
    return {"items": filtered or sample}


@app.post("/api/diary/food")
def add_food_to_diary(item: DiaryFoodCreate):
    """Add a food entry to diary collection and return day summary."""
    day = item.consumed_at or date.today().isoformat()
    doc = {
        "food_name": item.food_name,
        "calories": item.calories,
        "protein_g": item.protein_g,
        "carbohydrates_total_g": item.carbohydrates_total_g,
        "fat_total_g": item.fat_total_g,
        "day": day,
    }
    inserted_id = create_document("foodentry", doc)
    summary = get_day_summary(day)
    return {"inserted_id": inserted_id, "summary": summary}


@app.get("/api/diary/summary")
def diary_summary(day: Optional[str] = None):
    d = day or date.today().isoformat()
    return get_day_summary(d)


@app.get("/api/exercises/search")
def search_exercises(q: str = Query("")):
    """Search exercises via ExerciseDB (RapidAPI) if key is set, else return sample list."""
    rapid_key = os.getenv("RAPIDAPI_KEY")
    if rapid_key and q:
        try:
            url = f"https://exercisedb.p.rapidapi.com/exercises/name/{q}"
            headers = {
                "X-RapidAPI-Key": rapid_key,
                "X-RapidAPI-Host": "exercisedb.p.rapidapi.com",
            }
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code != 200:
                raise HTTPException(status_code=502, detail=f"ExerciseDB error: {r.text[:120]}")
            data = r.json()
            items = [
                {
                    "name": it.get("name"),
                    "target": it.get("target"),
                    "equipment": it.get("equipment"),
                    "bodyPart": it.get("bodyPart"),
                    "gifUrl": it.get("gifUrl"),
                }
                for it in data
            ]
            return {"items": items}
        except requests.RequestException:
            pass

    # Fallback sample exercises
    sample = [
        {"name": "Push-up", "target": "petto", "equipment": "body weight", "bodyPart": "torace"},
        {"name": "Squat", "target": "gambe", "equipment": "body weight", "bodyPart": "gambe"},
        {"name": "Plank", "target": "core", "equipment": "tappetino", "bodyPart": "addome"},
    ]
    filtered = [s for s in sample if q.lower() in s["name"].lower()] if q else sample
    return {"items": filtered}


def get_day_summary(d: str):
    # Fetch entries for specific day
    entries = get_documents("foodentry", {"day": d}, limit=None)
    total_cal = sum(e.get("calories", 0) for e in entries)
    total_p = sum(e.get("protein_g", 0) for e in entries)
    total_c = sum(e.get("carbohydrates_total_g", 0) for e in entries)
    total_f = sum(e.get("fat_total_g", 0) for e in entries)
    # Convert ObjectId to str if present
    for e in entries:
        if e.get("_id"):
            e["_id"] = str(e["_id"]) 
    return {
        "day": d,
        "totals": {
            "calories": round(total_cal, 1),
            "protein_g": round(total_p, 1),
            "carbohydrates_total_g": round(total_c, 1),
            "fat_total_g": round(total_f, 1),
        },
        "entries": entries,
    }


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, "name") else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
