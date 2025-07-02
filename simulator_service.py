import docker
import threading
import subprocess
import os
from datetime import datetime
from enum import Enum
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class SimulationStatus(Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"

class SimulatorService:
    def __init__(self):
        self.client = None
        self.status = SimulationStatus.IDLE
        self.start_time: Optional[datetime] = None
        self.duration: Optional[int] = None
        self.stop_timer: Optional[threading.Timer] = None
        self.error_message: Optional[str] = None
        self.current_run_id: Optional[str] = None
    
    def _get_docker_client(self):
        if self.client is None:
            try:
                self.client = docker.from_env()
            except Exception as e:
                raise Exception(f"Failed to connect to Docker: {str(e)}")
        return self.client
        
    def start_simulation(self, run_id: str, duration_seconds: int, algo_consts=None, simulator_consts=None) -> bool:
        if self.status != SimulationStatus.IDLE:
            return False
            
        try:
            self.status = SimulationStatus.STARTING
            self.start_time = datetime.now()
            self.duration = duration_seconds
            self.current_run_id = run_id
            
            logger.info(f"Starting simulation {run_id} for {duration_seconds} seconds")
            
            # Set environment variables for configuration
            env = os.environ.copy()
            
            # Add run ID for tracking
            env["SIMULATION_RUN_ID"] = run_id
            
            # Add database connection info
            env["POSTGRES_HOST"] = "postgres"
            env["POSTGRES_PORT"] = "5432"
            env["POSTGRES_DB"] = "trading_results"
            env["POSTGRES_USER"] = "trading_user"
            env["POSTGRES_PASSWORD"] = "trading_pass"
            
            env["MONGODB_HOST"] = "mongodb"
            env["MONGODB_PORT"] = "27017"
            env["MONGODB_USERNAME"] = "admin"
            env["MONGODB_PASSWORD"] = "admin_pass"
            env["MONGODB_DATABASE"] = "trading_configs"
            
            # Add algorithm constants
            if algo_consts:
                for key, value in algo_consts.dict().items():
                    if value is not None:
                        env[key] = str(value)
                        logger.debug(f"Set algo config: {key}={value}")
            
            # Add simulator constants
            if simulator_consts:
                for key, value in simulator_consts.dict().items():
                    if value is not None:
                        env[key] = str(value)
                        logger.debug(f"Set simulator config: {key}={value}")
            
            # Start docker compose using subprocess (more reliable)
            result = subprocess.run(['docker', 'compose', 'up', '-d'], 
                                  capture_output=True, text=True, cwd='.', env=env)
            if result.returncode != 0:
                raise Exception(f"Docker compose failed: {result.stderr}")
            
            self.status = SimulationStatus.RUNNING
            
            # Set timer to stop simulation
            self.stop_timer = threading.Timer(duration_seconds, self._auto_stop)
            self.stop_timer.start()
            
            return True
            
        except Exception as e:
            self.status = SimulationStatus.ERROR
            self.error_message = str(e)
            return False
    
    def stop_simulation(self) -> bool:
        if self.status not in [SimulationStatus.RUNNING, SimulationStatus.STARTING]:
            return False
            
        try:
            self.status = SimulationStatus.STOPPING
            
            # Cancel timer if running
            if self.stop_timer:
                self.stop_timer.cancel()
                
            # Stop docker compose using subprocess
            result = subprocess.run(['docker', 'compose', 'down'], 
                                  capture_output=True, text=True, cwd='.')
            if result.returncode != 0:
                raise Exception(f"Docker compose down failed: {result.stderr}")
            
            self.status = SimulationStatus.IDLE
            self.start_time = None
            self.duration = None
            self.stop_timer = None
            self.current_run_id = None
            
            return True
            
        except Exception as e:
            self.status = SimulationStatus.ERROR
            return False
    
    def _auto_stop(self):
        self.stop_simulation()
    
    def get_current_run_id(self) -> Optional[str]:
        """Get the current running simulation ID"""
        return self.current_run_id
    
    def get_status(self) -> dict:
        elapsed = None
        remaining = None
        
        if self.start_time and self.duration:
            elapsed = int((datetime.now() - self.start_time).total_seconds())
            remaining = max(0, self.duration - elapsed)
            
        return {
            "status": self.status.value,
            "run_id": self.current_run_id,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "duration": self.duration,
            "elapsed": elapsed,
            "remaining": remaining,
            "error_message": self.error_message if self.status == SimulationStatus.ERROR else None
        }