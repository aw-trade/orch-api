from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from simulator_service import SimulatorService, SimulationStatus

app = FastAPI(title="Trading Simulator Orchestration API")
simulator = SimulatorService()

class StartSimulationRequest(BaseModel):
    duration_seconds: int

class StartSimulationResponse(BaseModel):
    success: bool
    message: str

class SimulationStatusResponse(BaseModel):
    status: str
    start_time: str = None
    duration: int = None
    elapsed: int = None
    remaining: int = None
    error_message: str = None

class StopSimulationResponse(BaseModel):
    success: bool
    message: str

@app.post("/simulate/start", response_model=StartSimulationResponse)
async def start_simulation(request: StartSimulationRequest):
    if request.duration_seconds <= 0:
        raise HTTPException(status_code=400, detail="Duration must be positive")
    
    success = simulator.start_simulation(request.duration_seconds)
    
    if success:
        return StartSimulationResponse(
            success=True,
            message=f"Simulation started for {request.duration_seconds} seconds"
        )
    else:
        current_status = simulator.get_status()
        if current_status["status"] == SimulationStatus.ERROR.value:
            raise HTTPException(status_code=500, detail="Failed to start simulation")
        else:
            raise HTTPException(status_code=409, detail="Simulation already running")

@app.get("/simulate/status", response_model=SimulationStatusResponse)
async def get_simulation_status():
    status = simulator.get_status()
    return SimulationStatusResponse(**status)

@app.post("/simulate/stop", response_model=StopSimulationResponse)
async def stop_simulation():
    success = simulator.stop_simulation()
    
    if success:
        return StopSimulationResponse(
            success=True,
            message="Simulation stopped successfully"
        )
    else:
        current_status = simulator.get_status()
        if current_status["status"] == SimulationStatus.IDLE.value:
            raise HTTPException(status_code=409, detail="No simulation running")
        else:
            raise HTTPException(status_code=500, detail="Failed to stop simulation")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)