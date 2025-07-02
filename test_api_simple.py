#!/usr/bin/env python3
"""
Simple test script for the trading simulation API
"""
import requests
import json
import time

# Test configuration
BASE_URL = "http://localhost:8001"

def test_health():
    """Test health endpoint"""
    print("Testing health endpoint...")
    try:
        response = requests.get(f"{BASE_URL}/health")
        if response.status_code == 200:
            print("✅ Health check passed")
            print(f"Response: {response.json()}")
        else:
            print(f"❌ Health check failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Health check error: {e}")

def test_simulation_basic():
    """Test basic simulation start/stop"""
    print("\nTesting basic simulation...")
    
    # Test start
    request_data = {
        "duration_seconds": 30
    }
    
    try:
        response = requests.post(f"{BASE_URL}/simulate/start", json=request_data)
        print(f"Start response: {response.status_code}")
        if response.status_code in [200, 409]:
            print("✅ Start request handled correctly")
            if response.status_code == 200:
                print(f"Response: {response.json()}")
        else:
            print(f"❌ Start failed: {response.json()}")
    except Exception as e:
        print(f"❌ Start error: {e}")
    
    # Check status
    time.sleep(1)
    try:
        response = requests.get(f"{BASE_URL}/simulate/status")
        if response.status_code == 200:
            print("✅ Status check passed")
            print(f"Status: {response.json()}")
        else:
            print(f"❌ Status check failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Status error: {e}")
    
    # Test stop
    try:
        response = requests.post(f"{BASE_URL}/simulate/stop")
        print(f"Stop response: {response.status_code}")
        if response.status_code in [200, 409]:
            print("✅ Stop request handled correctly")
            if response.status_code == 200:
                print(f"Response: {response.json()}")
        else:
            print(f"❌ Stop failed: {response.json()}")
    except Exception as e:
        print(f"❌ Stop error: {e}")

def test_simulation_with_config():
    """Test simulation with configuration parameters"""
    print("\nTesting simulation with custom configuration...")
    
    request_data = {
        "duration_seconds": 15,
        "algo_consts": {
            "IMBALANCE_THRESHOLD": 0.8,
            "MIN_VOLUME_THRESHOLD": 15.0,
            "LOOKBACK_PERIODS": 7,
            "SIGNAL_COOLDOWN_MS": 150
        },
        "simulator_consts": {
            "INITIAL_CAPITAL": 50000.0,
            "POSITION_SIZE_PCT": 0.03,
            "TRADING_FEE_PCT": 0.002,
            "MIN_CONFIDENCE": 0.4,
            "ENABLE_SHORTING": False,
            "STATS_INTERVAL_SECS": 20,
            "AUTO_REGISTER": True
        }
    }
    
    try:
        response = requests.post(f"{BASE_URL}/simulate/start", json=request_data)
        print(f"Config test response: {response.status_code}")
        if response.status_code in [200, 409]:
            print("✅ Configuration test passed")
            if response.status_code == 200:
                print(f"Response: {response.json()}")
        else:
            print(f"❌ Configuration test failed: {response.json()}")
    except Exception as e:
        print(f"❌ Configuration test error: {e}")
    
    # Stop the simulation
    try:
        requests.post(f"{BASE_URL}/simulate/stop")
    except:
        pass

def test_validation():
    """Test input validation"""
    print("\nTesting input validation...")
    
    # Test invalid duration
    request_data = {
        "duration_seconds": -10
    }
    
    try:
        response = requests.post(f"{BASE_URL}/simulate/start", json=request_data)
        if response.status_code == 400:
            print("✅ Validation test passed - negative duration rejected")
            print(f"Error: {response.json()}")
        else:
            print(f"❌ Validation test failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Validation test error: {e}")

def test_partial_config():
    """Test partial configuration"""
    print("\nTesting partial configuration...")
    
    request_data = {
        "duration_seconds": 10,
        "algo_consts": {
            "IMBALANCE_THRESHOLD": 0.9
            # Other values should use defaults
        },
        "simulator_consts": {
            "INITIAL_CAPITAL": 25000.0,
            "ENABLE_SHORTING": False
            # Other values should use defaults
        }
    }
    
    try:
        response = requests.post(f"{BASE_URL}/simulate/start", json=request_data)
        print(f"Partial config response: {response.status_code}")
        if response.status_code in [200, 409]:
            print("✅ Partial configuration test passed")
            if response.status_code == 200:
                print(f"Response: {response.json()}")
        else:
            print(f"❌ Partial configuration test failed: {response.json()}")
    except Exception as e:
        print(f"❌ Partial configuration test error: {e}")
    
    # Stop the simulation
    try:
        requests.post(f"{BASE_URL}/simulate/stop")
    except:
        pass

def main():
    """Run all tests"""
    print("🧪 Starting API Tests")
    print("=" * 50)
    
    test_health()
    test_simulation_basic()
    test_simulation_with_config()
    test_validation()
    test_partial_config()
    
    print("\n" + "=" * 50)
    print("🏁 Tests completed")
    print("\nTo run these tests:")
    print("1. Start the API server: python3 main.py")
    print("2. Run this test script: python3 test_api_simple.py")

if __name__ == "__main__":
    main()


'''# Example cURL command to start a simulation

curl -X POST "http://localhost:8001/simulate/start" \
-H "Content-Type: application/json" \
-d '{"duration_seconds": 60, "algo_consts": {"IMBALANCE_THRESHOLD": 0.8, "MIN_VOLUME_THRESHOLD": 15.0, "LOOKBACK_PERIODS": 7, "SIGNAL_COOLDOWN_MS": 150}, "simulator_consts": 
{"INITIAL_CAPITAL": 50000.0, "POSITION_SIZE_PCT": 0.03, "TRADING_FEE_PCT": 0.002, "MIN_CONFIDENCE": 0.4, "ENABLE_SHORTING": false}}'
'''

'''
curl -X POST "http://localhost:8001/simulate/start" \
-H "Content-Type: application/json" \
-d '{"duration_seconds": 10, "algo_consts": {"IMBALANCE_THRESHOLD": 0.8, "MIN_VOLUME_THRESHOLD": 15.0, "LOOKBACK_PERIODS": 7,"SIGNAL_COOLDOWN_MS": 150}, "simulator_consts": {"INITIAL_CAPITAL": 50000.0, "POSITION_SIZE_PCT": 0.03, "TRADING_FEE_PCT": 0.002, "MIN_CONFIDENCE": 0.4, "ENABLE_SHORTING": false}}'
'''