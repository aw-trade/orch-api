#!/usr/bin/env python3
"""
Verification script to check if the refactored structure works
"""
import sys
import os

# Add the src directory to the Python path
project_root = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(project_root, 'src')
sys.path.insert(0, src_path)

def test_imports():
    """Test all critical imports"""
    try:
        print("Testing core imports...")
        from src.core.config import get_config
        print("✅ Core config import successful")
        
        print("Testing database imports...")
        from src.database import models
        print("✅ Database models import successful")
        
        print("Testing service imports...")
        from src.services.simulator_service import SimulatorService
        from src.services.resource_manager import ResourceManager
        print("✅ Services import successful")
        
        print("Testing endpoint imports...")
        from src.api.endpoints import simulation, results, analytics, resources
        print("✅ Endpoints import successful")
        
        print("Testing utils imports...")
        from src.utils.compose_generator import ComposeGenerator
        print("✅ Utils import successful")
        
        print("\n🎉 All imports successful! The refactored structure is working correctly.")
        return True
        
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False

def check_file_structure():
    """Check if all expected files exist"""
    expected_files = [
        'src/api/main.py',
        'src/api/endpoints/simulation.py',
        'src/api/endpoints/results.py',
        'src/api/endpoints/analytics.py',
        'src/api/endpoints/resources.py',
        'src/core/config.py',
        'src/database/models.py',
        'src/database/postgres_client.py',
        'src/database/mongodb_client.py',
        'src/services/simulator_service.py',
        'src/services/resource_manager.py',
        'src/utils/compose_generator.py',
        'tests/test_api_simple.py',
        'docker/docker-compose.yml',
        'docker/docker-compose.databases.yml',
        'docs/README.md',
        'requirements.txt'
    ]
    
    missing_files = []
    for file_path in expected_files:
        if not os.path.exists(file_path):
            missing_files.append(file_path)
    
    if missing_files:
        print("❌ Missing files:")
        for file_path in missing_files:
            print(f"   - {file_path}")
        return False
    else:
        print("✅ All expected files are present")
        return True

if __name__ == "__main__":
    print("🔍 Verifying refactored project structure...\n")
    
    structure_ok = check_file_structure()
    imports_ok = test_imports()
    
    if structure_ok and imports_ok:
        print("\n✅ Project refactoring completed successfully!")
        print("📝 Structure is organized and all imports are working")
        print("🚀 Ready to run the application with: python run.py")
    else:
        print("\n❌ Issues detected in the refactored structure")
        sys.exit(1)