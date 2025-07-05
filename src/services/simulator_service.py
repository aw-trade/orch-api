import docker
import threading
import subprocess
import os
import requests
import time
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List
import logging
from src.utils.compose_generator import ComposeGenerator
from src.core.config import get_config

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
        self.results: Optional[Dict] = None

class SimulatorService:
    def __init__(self):
        self.client = None
        self.active_runs: Dict[str, SimulationRun] = {}
        self.compose_generator = ComposeGenerator()
        self.config = get_config()
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
            
            # Ensure simulator config exists
            if simulator_consts is None:
                from src.database.models import SimulatorConfig
                simulator_consts = SimulatorConfig()
            
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
            
            # Note: Timer is now handled by Rust simulator after algorithm connection
            # No FastAPI-level timer needed
            
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
            
            # Collect results before stopping
            if not simulation_run.results:  # Only collect if not already collected
                results = self.collect_simulation_results(run_id)
                if results:
                    simulation_run.results = results
                
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
        # Collect results before stopping
        results = self.collect_simulation_results(run_id)
        if results:
            logger.info(f"Successfully collected results for {run_id}")
            # Store results for later database persistence
            if run_id in self.active_runs:
                self.active_runs[run_id].results = results
        self.stop_simulation(run_id)
    
    def collect_simulation_results(self, run_id: str) -> Optional[Dict]:
        """Collect simulation results from the simulator's API before stopping"""
        try:
            # Get the results API port for this simulation
            results_port = self.compose_generator.get_results_api_port(run_id)
            
            # Try to fetch results from the simulator
            url = f"http://localhost:{results_port}/results"
            logger.info(f"Collecting results from {url}")
            
            # Retry logic in case the simulator is still finalizing
            max_retries = self.config.simulator.max_result_retries
            timeout = self.config.simulator.default_results_timeout
            
            for attempt in range(max_retries):
                try:
                    response = requests.get(url, timeout=timeout)
                    if response.status_code == 200:
                        results = response.json()
                        logger.info(f"Successfully collected results for {run_id}")
                        return results
                    elif response.status_code == 404:
                        logger.info(f"Results not yet available for {run_id}, waiting...")
                        time.sleep(2)
                        continue
                    else:
                        logger.warning(f"Unexpected status code {response.status_code} from results API")
                        time.sleep(1)
                        continue
                except requests.exceptions.RequestException as e:
                    logger.warning(f"Attempt {attempt + 1} failed to collect results: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(2)
                    continue
            
            logger.error(f"Failed to collect results for {run_id} after {max_retries} attempts")
            return None
            
        except Exception as e:
            logger.error(f"Error collecting results for {run_id}: {e}")
            return None

    def collect_live_stats(self, run_id: str) -> Optional[Dict]:
        """Collect live statistics from the simulator's /stats endpoint during execution"""
        try:
            # Get the results API port for this simulation
            results_port = self.compose_generator.get_results_api_port(run_id)
            
            # Try to fetch live stats from the simulator
            url = f"http://localhost:{results_port}/stats"
            logger.debug(f"Collecting live stats from {url}")
            
            timeout = self.config.stats_collection.collection_timeout_seconds
            response = requests.get(url, timeout=timeout)
            if response.status_code == 200:
                stats = response.json()
                logger.debug(f"Successfully collected live stats for {run_id}")
                return stats
            elif response.status_code == 404:
                logger.debug(f"Live stats not available for {run_id}")
                return None
            else:
                logger.warning(f"Unexpected status code {response.status_code} from stats API")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.debug(f"Failed to collect live stats for {run_id}: {e}")
            return None
        except Exception as e:
            logger.warning(f"Error collecting live stats for {run_id}: {e}")
            return None
    
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
    
    def get_simulation_results(self, run_id: str) -> Optional[Dict]:
        """Get the collected results for a specific simulation"""
        if run_id in self.active_runs:
            return self.active_runs[run_id].results
        return None