from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
from decimal import Decimal

class SimulationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"

class TradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class Algorithm(str, Enum):
    ORDER_BOOK_ALGO = "order-book-algo"
    RSI_ALGO = "rsi-algo"

# MongoDB Models (Configuration Storage)
class AlgoConfig(BaseModel):
    IMBALANCE_THRESHOLD: Optional[float] = 0.6
    MIN_VOLUME_THRESHOLD: Optional[float] = 10.0
    LOOKBACK_PERIODS: Optional[int] = 5
    SIGNAL_COOLDOWN_MS: Optional[int] = 100

class SimulatorConfig(BaseModel):
    INITIAL_CAPITAL: Optional[float] = 100000.0
    POSITION_SIZE_PCT: Optional[float] = 0.05
    MAX_POSITION_SIZE: Optional[float] = 10000.0
    TRADING_FEE_PCT: Optional[float] = 0.001
    MIN_CONFIDENCE: Optional[float] = 0.3
    ENABLE_SHORTING: Optional[bool] = True
    STATS_INTERVAL_SECS: Optional[int] = 30
    AUTO_REGISTER: Optional[bool] = True
    MAX_RUNTIME_SECS: Optional[int] = None

class SimulationConfigDocument(BaseModel):
    run_id: str
    created_at: datetime
    status: SimulationStatus
    duration_seconds: int
    algorithm: Algorithm = Algorithm.ORDER_BOOK_ALGO
    algorithm_version: str = "v1.0.0"
    algo_config: AlgoConfig
    simulator_config: SimulatorConfig
    metadata: Optional[Dict[str, Any]] = {}

class AlgorithmVersionDocument(BaseModel):
    version: str
    created_at: datetime
    description: str
    default_config: AlgoConfig
    config_schema: Optional[Dict[str, Any]] = {}

# PostgreSQL Models (Results Storage)
class SimulationRun(BaseModel):
    run_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_seconds: int
    algorithm: Optional[Algorithm] = None
    algorithm_version: Optional[str] = None
    status: SimulationStatus
    
    # Financial metrics
    initial_capital: Optional[float] = None
    final_capital: Optional[float] = None
    total_pnl: Optional[float] = None
    total_fees: Optional[float] = None
    net_pnl: Optional[float] = None
    return_pct: Optional[float] = None
    max_drawdown: Optional[float] = None
    
    # Trading metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: Optional[float] = None
    signals_received: int = 0
    signals_executed: int = 0
    execution_rate: Optional[float] = None
    total_volume: Optional[float] = None
    
    # Performance metrics
    sharpe_ratio: Optional[float] = None
    avg_win: Optional[float] = None
    avg_loss: Optional[float] = None
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

class Trade(BaseModel):
    id: Optional[int] = None
    run_id: str
    trade_id: int
    symbol: str
    side: TradeSide
    quantity: float
    price: float
    timestamp_ms: int
    confidence: Optional[float] = None
    fees: Optional[float] = None
    source_algo: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)

class Position(BaseModel):
    id: Optional[int] = None
    run_id: str
    symbol: str
    quantity: float
    avg_price: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    realized_pnl: Optional[float] = None
    last_price: Optional[float] = None
    last_update_ms: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.now)

# API Request/Response Models
class StartSimulationRequest(BaseModel):
    duration_seconds: int
    algorithm: Algorithm = Algorithm.ORDER_BOOK_ALGO
    algo_consts: Optional[AlgoConfig] = None
    simulator_consts: Optional[SimulatorConfig] = None
    algorithm_version: str = "v1.0.0"
    metadata: Optional[Dict[str, Any]] = {}

class StartSimulationResponse(BaseModel):
    success: bool
    message: str
    run_id: Optional[str] = None

class SimulationStatusResponse(BaseModel):
    run_id: str
    status: SimulationStatus
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: Optional[int] = None
    elapsed_seconds: Optional[int] = None
    remaining_seconds: Optional[int] = None
    error_message: Optional[str] = None

class SimulationResultsResponse(BaseModel):
    run_id: str
    simulation: SimulationRun
    trades: List[Trade]
    positions: List[Position]
    config: SimulationConfigDocument

class SimulationSummary(BaseModel):
    run_id: str
    start_time: datetime
    end_time: Optional[datetime]
    duration_seconds: int
    status: SimulationStatus
    algorithm_version: str
    net_pnl: Optional[float]
    return_pct: Optional[float]
    total_trades: int
    win_rate: Optional[float]