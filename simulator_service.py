import asyncio
import docker
import threading
import subprocess
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

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
    
    def _get_docker_client(self):
        if self.client is None:
            try:
                self.client = docker.from_env()
            except Exception as e:
                raise Exception(f"Failed to connect to Docker: {str(e)}")
        return self.client
        
    def start_simulation(self, duration_seconds: int) -> bool:
        if self.status != SimulationStatus.IDLE:
            return False
            
        try:
            self.status = SimulationStatus.STARTING
            self.start_time = datetime.now()
            self.duration = duration_seconds
            
            # Start docker compose using subprocess (more reliable)
            result = subprocess.run(['docker', 'compose', 'up', '-d'], 
                                  capture_output=True, text=True, cwd='.')
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
            
            return True
            
        except Exception as e:
            self.status = SimulationStatus.ERROR
            return False
    
    def _auto_stop(self):
        self.stop_simulation()
    
    def get_status(self) -> dict:
        elapsed = None
        remaining = None
        
        if self.start_time and self.duration:
            elapsed = int((datetime.now() - self.start_time).total_seconds())
            remaining = max(0, self.duration - elapsed)
            
        return {
            "status": self.status.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "duration": self.duration,
            "elapsed": elapsed,
            "remaining": remaining,
            "error_message": self.error_message if self.status == SimulationStatus.ERROR else None
        }