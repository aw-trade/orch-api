
'''# Example cURL command to start a simulation

curl -X POST "http://localhost:8000/simulate/start" \
-H "Content-Type: application/json" \
-d '{"duration_seconds": 60, "algo_consts": {"IMBALANCE_THRESHOLD": 0.8, "MIN_VOLUME_THRESHOLD": 15.0, "LOOKBACK_PERIODS": 7, "SIGNAL_COOLDOWN_MS": 150}, "simulator_consts": 
{"INITIAL_CAPITAL": 50000.0, "POSITION_SIZE_PCT": 0.03, "TRADING_FEE_PCT": 0.002, "MIN_CONFIDENCE": 0.4, "ENABLE_SHORTING": false}}'
'''

'''
curl -X POST "http://localhost:8000/simulate/start" \
-H "Content-Type: application/json" \
-d '{"duration_seconds": 10, "algo_consts": {"IMBALANCE_THRESHOLD": 0.8, "MIN_VOLUME_THRESHOLD": 15.0, "LOOKBACK_PERIODS": 7,"SIGNAL_COOLDOWN_MS": 150}, "simulator_consts": {"INITIAL_CAPITAL": 50000.0, "POSITION_SIZE_PCT": 0.03, "TRADING_FEE_PCT": 0.002, "MIN_CONFIDENCE": 0.4, "ENABLE_SHORTING": false}}'
'''

"""
amiel@amiel-Prestige-14-A11MT:~/aw-trade/orch-api$ curl -X POST "http://localhost:8000/simulate/start" \
-H "Content-Type: application/json" \
-d '{"duration_seconds": 10, "algo_consts": {"IMBALANCE_THRESHOLD": 0.8, "MIN_VOLUME_THRESHOLD": 15.0, "LOOKBACK_PERIODS": 7,"SIGNAL_COOLDOWN_MS": 150}, "simulator_consts": {"INITIAL_CAPITAL": 50000.0, "POSITION_SIZE_PCT": 0.03, "TRADING_FEE_PCT": 0.002, "MIN_CONFIDENCE": 0.4, "ENABLE_SHORTING": false}}'
{"detail":"Failed to create simulation run record"}

"""


"""
 curl -X POST "http://localhost:8000/simulate/start" -H "Content-Type: application/json" -d '{"duration_seconds": 60, "algorithm": "rsi-algo"}'
"""

"""
 curl -X POST "http://localhost:8000/simulate/start" -H "Content-Type: application/json" -d '{"duration_seconds": 60, "algorithm": "order-book-algo"}'
"""