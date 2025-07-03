from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid
import logging

from src.database.models import (
    StartSimulationRequest, StartSimulationResponse, SimulationStatusResponse,
    SimulationSummary, AlgoConfig, SimulatorConfig, SimulationConfigDocument,
    SimulationRun, SimulationStatus
)
from src.database.postgres_client import postgres_client
from src.database.mongodb_client import mongodb_client
from src.services.simulator_service import SimulatorService
from src.services.resource_manager import ResourceManager

router = APIRouter(prefix="/simulate", tags=["simulation"])

class StopSimulationResponse(BaseModel):
    success: bool
    message: str
    run_id: Optional[str] = None

async def get_simulator_service():
    return SimulatorService()

async def get_resource_manager():
    return ResourceManager(await get_simulator_service())

async def persist_simulation_results(run_id: str, results: dict):
    """Persist collected simulation results to PostgreSQL"""
    try:
        end_time = datetime.now()
        
        updates = {
            "status": SimulationStatus.COMPLETED.value,
            "end_time": end_time,
            "final_capital": results.get("final_capital", 0.0),
            "total_pnl": results.get("total_pnl", 0.0),
            "total_fees": results.get("total_fees", 0.0),
            "net_pnl": results.get("net_pnl", 0.0),
            "return_pct": results.get("return_pct", 0.0),
            "max_drawdown": results.get("max_drawdown", 0.0),
            "total_trades": results.get("total_trades", 0),
            "winning_trades": results.get("winning_trades", 0),
            "losing_trades": results.get("losing_trades", 0),
            "win_rate": results.get("win_rate", 0.0),
            "signals_received": results.get("signals_received", 0),
            "signals_executed": results.get("signals_executed", 0),
            "execution_rate": results.get("signals_executed", 0) / max(results.get("signals_received", 1), 1) * 100.0,
            "total_volume": results.get("total_volume", 0.0),
            "sharpe_ratio": results.get("sharpe_ratio", 0.0),
            "avg_win": results.get("avg_win", 0.0),
            "avg_loss": results.get("avg_loss", 0.0)
        }
        
        await postgres_client.update_simulation_run(run_id, updates)
        await mongodb_client.update_simulation_config(run_id, {"status": SimulationStatus.COMPLETED.value})
        
        logging.info(f"Successfully persisted results for simulation {run_id}")
        
    except Exception as e:
        logging.error(f"Failed to persist results for {run_id}: {e}")

@router.post("/start", response_model=StartSimulationResponse)
async def start_simulation(
    request: StartSimulationRequest,
    simulator: SimulatorService = Depends(get_simulator_service)
):
    if request.duration_seconds <= 0:
        raise HTTPException(status_code=400, detail="Duration must be positive")
    
    run_id = f"run_{datetime.now().strftime('%Y_%m_%d_%H%M%S')}_{str(uuid.uuid4())[:8]}"
    
    algo_config = request.algo_consts or AlgoConfig()
    simulator_config = request.simulator_consts or SimulatorConfig()
    
    config_doc = SimulationConfigDocument(
        run_id=run_id,
        created_at=datetime.now(),
        status=SimulationStatus.PENDING,
        duration_seconds=request.duration_seconds,
        algorithm_version=request.algorithm_version,
        algo_config=algo_config,
        simulator_config=simulator_config,
        metadata=request.metadata
    )
    
    config_saved = await mongodb_client.save_simulation_config(config_doc)
    if not config_saved:
        raise HTTPException(status_code=500, detail="Failed to save simulation configuration")
    
    simulation_run = SimulationRun(
        run_id=run_id,
        start_time=datetime.now(),
        duration_seconds=request.duration_seconds,
        algorithm_version=request.algorithm_version,
        status=SimulationStatus.PENDING,
        initial_capital=simulator_config.INITIAL_CAPITAL
    )
    run_saved = await postgres_client.create_simulation_run(simulation_run)
    if not run_saved:
        raise HTTPException(status_code=500, detail="Failed to create simulation run record")
    
    success = simulator.start_simulation(
        run_id,
        request.duration_seconds,
        algo_config,
        simulator_config
    )
    
    if success:
        await mongodb_client.update_simulation_config(run_id, {"status": SimulationStatus.RUNNING.value})
        await postgres_client.update_simulation_run(run_id, {"status": SimulationStatus.RUNNING.value})
        
        return StartSimulationResponse(
            success=True,
            message=f"Simulation started for {request.duration_seconds} seconds",
            run_id=run_id
        )
    else:
        await mongodb_client.update_simulation_config(run_id, {"status": SimulationStatus.FAILED.value})
        await postgres_client.update_simulation_run(run_id, {"status": SimulationStatus.FAILED.value})
        
        current_status = simulator.get_status()
        if current_status["status"] == "error":
            raise HTTPException(status_code=500, detail="Failed to start simulation")
        else:
            raise HTTPException(status_code=500, detail="Failed to start simulation")

@router.get("/status")
async def get_simulation_status(simulator: SimulatorService = Depends(get_simulator_service)):
    """Get status of all running simulations"""
    status = simulator.get_status()
    return status

@router.get("/status/{run_id}")
async def get_specific_simulation_status(
    run_id: str,
    simulator: SimulatorService = Depends(get_simulator_service)
):
    """Get status of a specific simulation"""
    status = simulator.get_status(run_id)
    return status

@router.get("/runs", response_model=List[SimulationSummary])
async def list_simulation_runs(
    limit: int = 100,
    offset: int = 0,
    status: Optional[SimulationStatus] = None,
    algorithm_version: Optional[str] = None
):
    """List all simulation runs with filtering"""
    runs = await postgres_client.list_simulation_runs(limit, offset, status, algorithm_version)
    return [
        SimulationSummary(
            run_id=run.run_id,
            start_time=run.start_time,
            end_time=run.end_time,
            duration_seconds=run.duration_seconds,
            status=run.status,
            algorithm_version=run.algorithm_version or "unknown",
            net_pnl=run.net_pnl,
            return_pct=run.return_pct,
            total_trades=run.total_trades,
            win_rate=run.win_rate
        )
        for run in runs
    ]

@router.get("/runs/{run_id}", response_model=SimulationStatusResponse)
async def get_simulation_run_status(run_id: str):
    """Get status of a specific simulation run"""
    simulation = await postgres_client.get_simulation_run(run_id)
    if not simulation:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    
    elapsed_seconds = None
    remaining_seconds = None
    
    if simulation.start_time:
        elapsed = datetime.now() - simulation.start_time
        elapsed_seconds = int(elapsed.total_seconds())
        
        if simulation.status == SimulationStatus.RUNNING:
            remaining_seconds = max(0, simulation.duration_seconds - elapsed_seconds)
    
    return SimulationStatusResponse(
        run_id=simulation.run_id,
        status=simulation.status,
        start_time=simulation.start_time.isoformat() if simulation.start_time else None,
        end_time=simulation.end_time.isoformat() if simulation.end_time else None,
        duration_seconds=simulation.duration_seconds,
        elapsed_seconds=elapsed_seconds,
        remaining_seconds=remaining_seconds
    )

@router.post("/stop", response_model=StopSimulationResponse)
async def stop_all_simulations(simulator: SimulatorService = Depends(get_simulator_service)):
    """Stop all currently running simulations"""
    results = simulator.stop_all_simulations()
    
    if not results:
        raise HTTPException(status_code=409, detail="No simulations running")
    
    stopped_runs = []
    failed_runs = []
    
    for run_id, success in results.items():
        if success:
            collected_results = simulator.get_simulation_results(run_id)
            if collected_results:
                await persist_simulation_results(run_id, collected_results)
            else:
                await mongodb_client.update_simulation_config(run_id, {"status": SimulationStatus.STOPPED.value})
                await postgres_client.update_simulation_run(run_id, {
                    "status": SimulationStatus.STOPPED.value,
                    "end_time": datetime.now()
                })
            stopped_runs.append(run_id)
        else:
            failed_runs.append(run_id)
    
    if failed_runs:
        return StopSimulationResponse(
            success=False,
            message=f"Stopped {len(stopped_runs)} simulations, failed to stop {len(failed_runs)}: {', '.join(failed_runs)}"
        )
    else:
        return StopSimulationResponse(
            success=True,
            message=f"Successfully stopped {len(stopped_runs)} simulations: {', '.join(stopped_runs)}"
        )

@router.post("/stop/{run_id}", response_model=StopSimulationResponse)
async def stop_specific_simulation(
    run_id: str,
    simulator: SimulatorService = Depends(get_simulator_service)
):
    """Stop a specific simulation run"""
    simulation = await postgres_client.get_simulation_run(run_id)
    if not simulation:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    
    success = simulator.stop_simulation(run_id)
    
    if success:
        collected_results = simulator.get_simulation_results(run_id)
        if collected_results:
            await persist_simulation_results(run_id, collected_results)
        else:
            await mongodb_client.update_simulation_config(run_id, {"status": SimulationStatus.STOPPED.value})
            await postgres_client.update_simulation_run(run_id, {
                "status": SimulationStatus.STOPPED.value,
                "end_time": datetime.now()
            })
        
        return StopSimulationResponse(
            success=True,
            message=f"Simulation {run_id} stopped successfully",
            run_id=run_id
        )
    else:
        sim_status = simulator.get_status(run_id)
        if sim_status.get("status") == "not_found":
            raise HTTPException(status_code=404, detail="Simulation not currently active")
        else:
            raise HTTPException(status_code=500, detail="Failed to stop simulation")

@router.post("/force-stop/{run_id}")
async def force_stop_simulation(
    run_id: str,
    resource_manager: ResourceManager = Depends(get_resource_manager)
):
    """Force stop a simulation (emergency stop)"""
    success = resource_manager.force_stop_simulation(run_id)
    
    if success:
        simulator = await get_simulator_service()
        collected_results = simulator.get_simulation_results(run_id)
        if collected_results:
            await persist_simulation_results(run_id, collected_results)
        else:
            await mongodb_client.update_simulation_config(run_id, {"status": SimulationStatus.STOPPED.value})
            await postgres_client.update_simulation_run(run_id, {
                "status": SimulationStatus.STOPPED.value,
                "end_time": datetime.now()
            })
        
        return {"success": True, "message": f"Simulation {run_id} force stopped"}
    else:
        raise HTTPException(status_code=500, detail="Failed to force stop simulation")