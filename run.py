#!/usr/bin/env python3
"""
Alternative entry point that works with the new project structure
"""
import sys
import os

# Add the src directory to the Python path
project_root = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(project_root, 'src')
sys.path.insert(0, src_path)

try:
    from src.api.main import app
    print("✅ Application imported successfully")
    
    if __name__ == "__main__":
        import uvicorn
        import logging
        logging.basicConfig(level=logging.INFO)
        print("🚀 Starting Trading Simulator Orchestration API...")
        uvicorn.run(app, host="0.0.0.0", port=8000)
        
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Make sure all dependencies are installed: pip install -r requirements.txt")
    sys.exit(1)