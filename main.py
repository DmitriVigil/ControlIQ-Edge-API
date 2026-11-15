import sqlite3
import asyncio
import random
from datetime import datetime
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# --- Database Setup (SQLite) ---
def init_db():
    conn = sqlite3.connect('telemetry.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS maintenance_logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, zone_id TEXT, note TEXT)''')
    conn.commit()
    conn.close()

def log_event(zone_id: str, note: str):
    conn = sqlite3.connect('telemetry.db')
    c = conn.cursor()
    c.execute("INSERT INTO maintenance_logs (timestamp, zone_id, note) VALUES (?, ?, ?)",
              (datetime.now().strftime("%Y-%m-%d %I:%M:%S %p"), zone_id, note))
    conn.commit()
    conn.close()

# --- In-Memory Edge Telemetry State ---
zones = {
    "BAC-101": {"id": "BAC-101", "name": "Main Lobby & Atrium", "temp": 71.2, "setpoint": 71.0, "valve": 35, "kw": 4.8, "override": False},
    "BAC-204": {"id": "BAC-204", "name": "Central Chiller", "temp": 69.8, "setpoint": 70.0, "valve": 42, "kw": 6.2, "override": False},
    "BAC-302": {"id": "BAC-302", "name": "Server IDF", "temp": 67.9, "setpoint": 65.0, "valve": 88, "kw": 9.4, "override": False},
    "BAC-310": {"id": "BAC-310", "name": "East Wing Suites", "temp": 72.1, "setpoint": 72.0, "valve": 28, "kw": 3.5, "override": False},
    "BAC-401": {"id": "BAC-401", "name": "Executive Penthouse", "temp": 75.4, "setpoint": 72.0, "valve": 95, "kw": 11.1, "override": False}
}

# --- Background Telemetry Simulation Task ---
async def simulate_telemetry():
    while True:
        for z_id, z in zones.items():
            if z["override"]:
                # Field override forces max load
                z["valve"] = 100
                z["kw"] = round(12.5 + random.uniform(0.0, 1.2), 2)
                z["temp"] = round(z["temp"] - 0.15, 1)
            else:
                # Seek setpoint dynamically
                delta = z["setpoint"] - z["temp"]
                step = max(min(delta * 0.12, 0.35), -0.35) + random.uniform(-0.1, 0.1)
                z["temp"] = round(z["temp"] + step, 1)
                
                target_valve = max(min(int(abs(z["setpoint"] - z["temp"]) * 28 + 18), 100), 10)
                z["valve"] = target_valve
                z["kw"] = round((target_valve / 100.0) * 11.5 + random.uniform(0.0, 0.4), 2)
        await asyncio.sleep(2.5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(simulate_telemetry())
    yield
    task.cancel()

app = FastAPI(lifespan=lifespan)

# --- REST API Endpoints ---
class SetpointUpdate(BaseModel):
    delta: float

class NoteUpdate(BaseModel):
    note: str

@app.get("/api/zones")
def get_zones():
    return list(zones.values())

@app.post("/api/zones/{zone_id}/setpoint")
def update_setpoint(zone_id: str, payload: SetpointUpdate):
    if zone_id in zones:
        zones[zone_id]["setpoint"] = round(zones[zone_id]["setpoint"] + payload.delta, 1)
        return zones[zone_id]
    raise HTTPException(status_code=404, detail="Zone not found")

@app.post("/api/zones/{zone_id}/override")
def toggle_override(zone_id: str):
    if zone_id in zones:
        zones[zone_id]["override"] = not zones[zone_id]["override"]
        status = "enabled (100% test)" if zones[zone_id]["override"] else "disabled"
        log_event(zone_id, f"Field override {status}.")
        return zones[zone_id]
    raise HTTPException(status_code=404, detail="Zone not found")

@app.post("/api/zones/{zone_id}/log")
def add_log(zone_id: str, payload: NoteUpdate):
    log_event(zone_id, payload.note)
    return {"status": "success"}

@app.get("/api/logs")
def get_logs():
    conn = sqlite3.connect('telemetry.db')
    c = conn.cursor()
    c.execute("SELECT timestamp, zone_id, note FROM maintenance_logs ORDER BY id DESC LIMIT 10")
    logs = [{"timestamp": row[0], "zone_id": row[1], "note": row[2]} for row in c.fetchall()]
    conn.close()
    return logs

# Mount the static directory to serve the frontend
app.mount("/", StaticFiles(directory="static", html=True), name="static")