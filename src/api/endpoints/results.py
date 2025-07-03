from fastapi import APIRouter, HTTPException
from typing import Dict, Any

from src.database.models import SimulationResultsResponse
from src.database.postgres_client import postgres_client
from src.database.mongodb_client import mongodb_client

router = APIRouter(prefix="/results", tags=["results"])

@router.get("/{run_id}", response_model=SimulationResultsResponse)
async def get_simulation_results(run_id: str):
    """Get complete results for a simulation run"""
    simulation = await postgres_client.get_simulation_run(run_id)
    if not simulation:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    
    config = await mongodb_client.get_simulation_config(run_id)
    if not config:
        raise HTTPException(status_code=404, detail="Simulation configuration not found")
    
    trades = await postgres_client.get_trades(run_id)
    positions = await postgres_client.get_positions(run_id)
    
    return SimulationResultsResponse(
        run_id=run_id,
        simulation=simulation,
        trades=trades,
        positions=positions,
        config=config
    )

@router.get("/{run_id}/trades")
async def get_simulation_trades(run_id: str):
    """Get trade history for a simulation run"""
    simulation = await postgres_client.get_simulation_run(run_id)
    if not simulation:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    
    trades = await postgres_client.get_trades(run_id)
    return {"run_id": run_id, "trades": trades}

@router.get("/{run_id}/positions")
async def get_simulation_positions(run_id: str):
    """Get final positions for a simulation run"""
    simulation = await postgres_client.get_simulation_run(run_id)
    if not simulation:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    
    positions = await postgres_client.get_positions(run_id)
    return {"run_id": run_id, "positions": positions}