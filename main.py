#!/usr/bin/env python3
"""
Main entry point for the Trading Simulator Orchestration API
"""
import sys
import os

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.api.main import app

if __name__ == "__main__":
    import uvicorn
    import logging
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="0.0.0.0", port=8000)