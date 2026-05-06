"""Routly FastAPI Backend."""
import json, os
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from main import run_simulation

app = FastAPI(title="Routly Dispatch API", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class SimReq(BaseModel):
    mode: str = "hungarian"
    weights: Optional[dict[str, float]] = None

@app.get("/health")
def health():
    return {"status": "ok", "project": "Routly", "team": "Greater N0ida"}

@app.post("/run-simulation")
def simulate(req: SimReq):
    if req.mode not in ("hungarian", "greedy"):
        raise HTTPException(400, "Mode must be 'hungarian' or 'greedy'")
    try:
        return run_simulation(mode=req.mode, custom_weights=req.weights)
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/pareto-data")
def pareto_data():
    path = os.path.join(BASE_DIR, "output", "pareto_results.json")
    if not os.path.exists(path):
        raise HTTPException(404, "Run pareto_search.py first")
    with open(path, "r") as f:
        return json.load(f)

@app.post("/compare")
def compare(req: SimReq):
    h = run_simulation(mode="hungarian", custom_weights=req.weights)
    g = run_simulation(mode="greedy", custom_weights=req.weights)
    return {
        "hungarian": {"summary": h["summary"], "performance": h["performance"]},
        "greedy": {"summary": g["summary"], "performance": g["performance"]},
        "comparison": {
            "sla_diff": h["summary"]["sla_compliance_rate_percent"] - g["summary"]["sla_compliance_rate_percent"],
            "fairness_diff": g["summary"]["fairness_std_dev"] - h["summary"]["fairness_std_dev"],
            "time_diff": g["summary"]["average_delivery_time"] - h["summary"]["average_delivery_time"],
        },
    }
