import docker
import threading
import subprocess
import os
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List
import logging
from compose_generator import ComposeGenerator

logger = logging.getLogger(__name__)

class SimulationStatus(Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"

class SimulationRun:
    def __init__(self, run_id: str, duration_seconds: int):
        self.run_id = run_id
        self.status = SimulationStatus.STARTING
        self.start_time = datetime.now()
        self.duration = duration_seconds
        self.stop_timer: Optional[threading.Timer] = None
        self.error_message: Optional[str] = None
        self.compose_file_path: Optional[str] = None

class SimulatorService:
    def __init__(self):
        self.client = None
        self.active_runs: Dict[str, SimulationRun] = {}
        self.compose_generator = ComposeGenerator()
        self._cleanup_orphaned_resources()
    
    def _get_docker_client(self):
        if self.client is None:
            try:
                self.client = docker.from_env()
            except Exception as e:
                raise Exception(f"Failed to connect to Docker: {str(e)}")
        return self.client
    
    def _validate_docker_environment(self):
        """Validate Docker daemon and required environment"""
        try:
            # Test Docker daemon connection
            result = subprocess.run(['docker', 'version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                raise Exception("Docker daemon not available")
            
            # Test Docker Compose availability
            result = subprocess.run(['docker', 'compose', 'version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                raise Exception("Docker Compose not available")
                
            logger.info("Docker environment validated successfully")
            
        except subprocess.TimeoutExpired:
            raise Exception("Docker command timed out - daemon may be unresponsive")
        except Exception as e:
            raise Exception(f"Docker environment validation failed: {str(e)}")
        
    def start_simulation(self, run_id: str, duration_seconds: int, algo_consts=None, simulator_consts=None) -> bool:
        # Check if this run_id is already active
        if run_id in self.active_runs:
            logger.warning(f"Simulation {run_id} is already running")
            return False
            
        try:
            # Validate Docker environment before starting
            self._validate_docker_environment()
            
            # Create simulation run tracker
            simulation_run = SimulationRun(run_id, duration_seconds)
            self.active_runs[run_id] = simulation_run
            
            logger.info(f"Starting simulation {run_id} for {duration_seconds} seconds")
            
            # Generate unique compose file for this simulation
            compose_file_path = self.compose_generator.generate_compose_file(
                run_id, algo_consts, simulator_consts
            )
            simulation_run.compose_file_path = compose_file_path
            
            # Start docker compose using the generated file
            result = subprocess.run([
                'docker', 'compose', '-f', compose_file_path, 'up', '-d'
            ], capture_output=True, text=True, cwd='.')
            
            if result.returncode != 0:
                raise Exception(f"Docker compose failed: {result.stderr}")
                
            simulation_run.status = SimulationStatus.RUNNING
            
            # Set timer to auto-stop simulation
            simulation_run.stop_timer = threading.Timer(
                duration_seconds, 
                lambda: self._auto_stop(run_id)
            )
            simulation_run.stop_timer.start()
            
            logger.info(f"Simulation {run_id} started successfully")
            return True
            
        except Exception as e:
            # Clean up on failure
            if run_id in self.active_runs:
                self.active_runs[run_id].status = SimulationStatus.ERROR
                self.active_runs[run_id].error_message = str(e)
            logger.error(f"Failed to start simulation {run_id}: {e}")
            return False
        
    
    def stop_simulation(self, run_id: str) -> bool:
        if run_id not in self.active_runs:
            logger.warning(f"Simulation {run_id} not found in active runs")
            return False
            
        simulation_run = self.active_runs[run_id]
        
        if simulation_run.status not in [SimulationStatus.RUNNING, SimulationStatus.STARTING]:
            logger.warning(f"Simulation {run_id} is not running (status: {simulation_run.status})")
            return False
            
        try:
            simulation_run.status = SimulationStatus.STOPPING
            
            # Cancel timer if running
            if simulation_run.stop_timer:
                simulation_run.stop_timer.cancel()
                
            # Stop docker compose using the specific compose file
            if simulation_run.compose_file_path:
                result = subprocess.run([
                    'docker', 'compose', '-f', simulation_run.compose_file_path, 'down'
                ], capture_output=True, text=True, cwd='.')
                
                if result.returncode != 0:
                    raise Exception(f"Docker compose down failed: {result.stderr}")
                
                # Clean up compose file
                self.compose_generator.cleanup_compose_file(run_id)
            
            # Remove from active runs
            del self.active_runs[run_id]
            
            logger.info(f"Simulation {run_id} stopped successfully")
            return True
            
        except Exception as e:
            simulation_run.status = SimulationStatus.ERROR
            simulation_run.error_message = str(e)
            logger.error(f"Failed to stop simulation {run_id}: {e}")
            return False
    
    def _auto_stop(self, run_id: str):
        logger.info(f"Auto-stopping simulation {run_id} due to timeout")
        self.stop_simulation(run_id)
    
    def get_active_run_ids(self) -> List[str]:
        """Get all active simulation run IDs"""
        return list(self.active_runs.keys())
    
    def get_running_simulations(self) -> List[str]:
        """Get simulation IDs that are currently running"""
        return [
            run_id for run_id, run in self.active_runs.items() 
            if run.status == SimulationStatus.RUNNING
        ]
    
    def _cleanup_orphaned_resources(self):
        """Clean up any orphaned Docker resources and compose files on startup"""
        try:
            # Clean up orphaned compose files
            active_compose_files = self.compose_generator.list_active_compose_files()
            for run_id in active_compose_files:
                # Check if containers are actually running
                compose_file_path = self.compose_generator.get_compose_file_path(run_id)
                result = subprocess.run([
                    'docker', 'compose', '-f', compose_file_path, 'ps', '-q'
                ], capture_output=True, text=True, cwd='.')
                
                # If no containers running, clean up the compose file
                if result.returncode == 0 and not result.stdout.strip():
                    logger.info(f"Cleaning up orphaned compose file for {run_id}")
                    self.compose_generator.cleanup_compose_file(run_id)
                    
        except Exception as e:
            logger.warning(f"Failed to cleanup orphaned resources: {e}")
    
    def _sync_status_with_docker(self, run_id: str):
        """Sync internal status with actual Docker container state for a specific run"""
        if run_id not in self.active_runs:
            return
            
        simulation_run = self.active_runs[run_id]
        
        try:
            if simulation_run.compose_file_path:
                # Check if containers for this specific run are running
                result = subprocess.run([
                    'docker', 'compose', '-f', simulation_run.compose_file_path, 'ps', '-q'
                ], capture_output=True, text=True, cwd='.')
                
                # If no containers and we think we're running, mark as completed or error
                if result.returncode == 0 and not result.stdout.strip():
                    if simulation_run.status in [SimulationStatus.RUNNING, SimulationStatus.STARTING]:
                        logger.info(f"No Docker containers found for {run_id}, marking as completed")
                        simulation_run.status = SimulationStatus.IDLE
                        if simulation_run.stop_timer:
                            simulation_run.stop_timer.cancel()
                            
        except Exception as e:
            logger.warning(f"Failed to sync Docker status for {run_id}: {e}")
    
    def get_status(self, run_id: Optional[str] = None) -> dict:
        """Get status for a specific run or all runs"""
        if run_id:
            return self._get_single_run_status(run_id)
        else:
            return self._get_all_runs_status()
    
    def _get_single_run_status(self, run_id: str) -> dict:
        """Get status for a specific simulation run"""
        if run_id not in self.active_runs:
            return {
                "status": "not_found",
                "run_id": run_id,
                "error_message": "Simulation run not found"
            }
        
        # Sync with Docker state
        self._sync_status_with_docker(run_id)
        
        simulation_run = self.active_runs[run_id]
        
        elapsed = None
        remaining = None
        
        if simulation_run.start_time and simulation_run.duration:
            elapsed = int((datetime.now() - simulation_run.start_time).total_seconds())
            remaining = max(0, simulation_run.duration - elapsed)
            
        return {
            "status": simulation_run.status.value,
            "run_id": run_id,
            "start_time": simulation_run.start_time.isoformat() if simulation_run.start_time else None,
            "duration": simulation_run.duration,
            "elapsed": elapsed,
            "remaining": remaining,
            "error_message": simulation_run.error_message if simulation_run.status == SimulationStatus.ERROR else None
        }
    
    def _get_all_runs_status(self) -> dict:
        """Get status for all active simulation runs"""
        runs_status = {}
        
        for run_id in list(self.active_runs.keys()):
            runs_status[run_id] = self._get_single_run_status(run_id)
        
        return {
            "total_active_runs": len(self.active_runs),
            "running_count": len(self.get_running_simulations()),
            "runs": runs_status
        }
    
    def stop_all_simulations(self) -> Dict[str, bool]:
        """Stop all active simulations"""
        results = {}
        for run_id in list(self.active_runs.keys()):
            results[run_id] = self.stop_simulation(run_id)
        return results
    
    def get_current_run_id(self) -> Optional[str]:
        """Get the first running simulation ID (for backward compatibility)"""
        running_sims = self.get_running_simulations()
        return running_sims[0] if running_sims else None