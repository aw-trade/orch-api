import asyncpg
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime
import os
import logging
import json
from pathlib import Path
import time
from .models import SimulationRun, Trade, Position, SimulationStatus
from ..core.config import get_config

logger = logging.getLogger(__name__)

class PostgresClient:
    def __init__(self):
        self.connection_pool = None
        self.host = os.getenv("POSTGRES_HOST", "localhost")
        self.port = int(os.getenv("POSTGRES_PORT", "5432"))
        self.database = os.getenv("POSTGRES_DB", "trading_results")
        self.user = os.getenv("POSTGRES_USER", "trading_user")
        self.password = os.getenv("POSTGRES_PASSWORD", "trading_pass")
        
        # Backup configuration
        self.backup_enabled = os.getenv("ENABLE_BACKUP", "false").lower() == "true"
        self.backup_dir = Path(os.getenv("BACKUP_DIR", "./backup"))
        if self.backup_enabled:
            self.backup_dir.mkdir(exist_ok=True)
        
        # Retry configuration
        self.max_retries = int(os.getenv("DB_MAX_RETRIES", "3"))
        self.retry_delay = float(os.getenv("DB_RETRY_DELAY", "1.0"))
        self.circuit_breaker_threshold = int(os.getenv("DB_CIRCUIT_BREAKER_THRESHOLD", "5"))
        self.circuit_breaker_reset_timeout = int(os.getenv("DB_CIRCUIT_BREAKER_RESET", "60"))
        
        # Circuit breaker state
        self.failure_count = 0
        self.last_failure_time = 0
        self.circuit_open = False

    def _check_circuit_breaker(self):
        """Check if circuit breaker should be opened or reset"""
        current_time = time.time()
        
        # Reset circuit breaker if timeout period has passed
        if self.circuit_open and (current_time - self.last_failure_time) > self.circuit_breaker_reset_timeout:
            logger.info("Circuit breaker reset - attempting to restore connection")
            self.circuit_open = False
            self.failure_count = 0
        
        return not self.circuit_open

    def _record_failure(self):
        """Record a database operation failure"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.circuit_breaker_threshold:
            logger.error(f"Circuit breaker opened after {self.failure_count} failures")
            self.circuit_open = True
    
    def _log_query(self, query: str, params: tuple = None, execution_time: float = None, error: Exception = None):
        """Log database query with timing and error information"""
        config = get_config()
        
        if not config.database.postgres_log_queries:
            return
            
        # Create structured log entry
        log_data = {
            "query": query.strip(),
            "params_count": len(params) if params else 0,
            "execution_time_ms": round(execution_time * 1000, 2) if execution_time else None,
            "error": str(error) if error else None
        }
        
        # Log level based on success/failure and timing
        if error:
            logger.error(f"🔴 PostgreSQL Query Failed: {log_data}")
        elif execution_time and execution_time > config.database.postgres_slow_query_threshold:
            logger.warning(f"🟡 PostgreSQL Slow Query: {log_data}")
        else:
            logger.info(f"🟢 PostgreSQL Query: {log_data}")
    
    async def _execute_with_logging(self, conn, query: str, *params):
        """Execute query with logging and timing"""
        start_time = time.time()
        error = None
        
        try:
            result = await conn.execute(query, *params)
            return result
        except Exception as e:
            error = e
            raise
        finally:
            execution_time = time.time() - start_time
            self._log_query(query, params, execution_time, error)
    
    async def _fetch_with_logging(self, conn, query: str, *params):
        """Fetch query results with logging and timing"""
        start_time = time.time()
        error = None
        
        try:
            result = await conn.fetch(query, *params)
            return result
        except Exception as e:
            error = e
            raise
        finally:
            execution_time = time.time() - start_time
            self._log_query(query, params, execution_time, error)
    
    async def _fetchrow_with_logging(self, conn, query: str, *params):
        """Fetch single row with logging and timing"""
        start_time = time.time()
        error = None
        
        try:
            result = await conn.fetchrow(query, *params)
            return result
        except Exception as e:
            error = e
            raise
        finally:
            execution_time = time.time() - start_time
            self._log_query(query, params, execution_time, error)

    def _record_success(self):
        """Record a successful database operation"""
        if self.failure_count > 0:
            logger.info("Database operation successful - resetting failure count")
        self.failure_count = 0

    async def _execute_with_retry(self, operation, *args, **kwargs):
        """Execute database operation with retry logic and circuit breaker"""
        if not self._check_circuit_breaker():
            raise Exception("Circuit breaker is open - database operations suspended")
        
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                result = await operation(*args, **kwargs)
                self._record_success()
                return result
                
            except Exception as e:
                last_exception = e
                logger.warning(f"Database operation failed (attempt {attempt + 1}/{self.max_retries + 1}): {e}")
                
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))  # Exponential backoff
                else:
                    self._record_failure()
        
        # All retries failed
        raise last_exception

    def _backup_to_file(self, operation_type: str, data: Dict):
        """Backup operation data to JSON file when database is unavailable"""
        if not self.backup_enabled:
            logger.debug(f"Backup disabled - skipping backup for {operation_type}")
            return False
            
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{operation_type}_{timestamp}_{data.get('run_id', 'unknown')}.json"
            filepath = self.backup_dir / filename
            
            backup_data = {
                "timestamp": timestamp,
                "operation": operation_type,
                "data": data
            }
            
            with open(filepath, 'w') as f:
                json.dump(backup_data, f, indent=2, default=str)
            
            logger.info(f"Data backed up to file: {filepath}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to backup data to file: {e}")
            return False

    async def process_backup_files(self):
        """Process backup files when database comes back online"""
        if not self.backup_enabled:
            logger.debug("Backup disabled - skipping backup file processing")
            return
            
        try:
            backup_files = list(self.backup_dir.glob("*.json"))
            if not backup_files:
                return
            
            logger.info(f"Found {len(backup_files)} backup files to process")
            
            for backup_file in backup_files:
                try:
                    with open(backup_file, 'r') as f:
                        backup_data = json.load(f)
                    
                    operation = backup_data.get("operation")
                    data = backup_data.get("data")
                    
                    if operation == "create_simulation_run":
                        simulation = SimulationRun(**data)
                        success = await self.create_simulation_run(simulation)
                    elif operation == "update_simulation_run":
                        run_id = data.get("run_id")
                        updates = data.get("updates")
                        success = await self.update_simulation_run(run_id, updates)
                    else:
                        logger.warning(f"Unknown backup operation: {operation}")
                        continue
                    
                    if success:
                        backup_file.unlink()  # Delete processed backup file
                        logger.info(f"Processed and deleted backup file: {backup_file}")
                    else:
                        logger.warning(f"Failed to process backup file: {backup_file}")
                        
                except Exception as e:
                    logger.error(f"Error processing backup file {backup_file}: {e}")
                    
        except Exception as e:
            logger.error(f"Error processing backup files: {e}")

    async def connect(self):
        """Initialize connection pool"""
        try:
            self.connection_pool = await asyncpg.create_pool(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password,
                min_size=2,
                max_size=10,
                command_timeout=60
            )
            logger.info(f"Connected to PostgreSQL at {self.host}:{self.port}")
            
            # Reset circuit breaker on successful connection
            self.circuit_open = False
            self.failure_count = 0
            
            # Process any backup files that accumulated during downtime
            await self.process_backup_files()
            
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise

    async def disconnect(self):
        """Close connection pool"""
        if self.connection_pool:
            await self.connection_pool.close()
            logger.info("Disconnected from PostgreSQL")

    async def create_simulation_run(self, simulation: SimulationRun) -> bool:
        """Create a new simulation run record with retry logic and backup"""
        async def _create_operation():
            async with self.connection_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO simulation_runs (
                        run_id, start_time, end_time, duration_seconds, algorithm_version, 
                        status, initial_capital, final_capital, total_pnl, total_fees, 
                        net_pnl, return_pct, max_drawdown, total_trades, winning_trades, 
                        losing_trades, win_rate, signals_received, signals_executed, 
                        execution_rate, total_volume, sharpe_ratio, avg_win, avg_loss,
                        created_at, updated_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, 
                             $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26)
                """, 
                    simulation.run_id, simulation.start_time, simulation.end_time,
                    simulation.duration_seconds, simulation.algorithm_version,
                    simulation.status.value, simulation.initial_capital, 
                    simulation.final_capital, simulation.total_pnl, simulation.total_fees,
                    simulation.net_pnl, simulation.return_pct, simulation.max_drawdown,
                    simulation.total_trades, simulation.winning_trades, simulation.losing_trades,
                    simulation.win_rate, simulation.signals_received, simulation.signals_executed,
                    simulation.execution_rate, simulation.total_volume, simulation.sharpe_ratio,
                    simulation.avg_win, simulation.avg_loss, simulation.created_at, simulation.updated_at
                )
        
        try:
            await self._execute_with_retry(_create_operation)
            logger.info(f"✅ PostgreSQL: Created simulation run {simulation.run_id} with status {simulation.status.value}")
            return True
        except Exception as e:
            logger.error(f"❌ PostgreSQL: Failed to create simulation run {simulation.run_id}: {e}")
            
            # Backup to file as fallback
            backup_data = simulation.dict()
            if self._backup_to_file("create_simulation_run", backup_data):
                logger.info(f"Simulation run {simulation.run_id} backed up to file")
            
            return False

    async def update_simulation_run(self, run_id: str, updates: Dict[str, Any]) -> bool:
        """Update simulation run with new data, retry logic and backup"""
        if not updates:
            return True
            
        async def _update_operation():
            # Remove updated_at from updates since it's handled by the database trigger
            filtered_updates = {k: v for k, v in updates.items() if k != 'updated_at'}
            
            # Check if there are any fields to update after filtering
            if not filtered_updates:
                logger.debug(f"📊 No fields to update for run_id {run_id} after filtering (only updated_at was provided)")
                return
            
            # Build dynamic update query
            set_clauses = []
            values = []
            param_count = 1
            
            for key, value in filtered_updates.items():
                set_clauses.append(f"{key} = ${param_count}")
                values.append(value)
                param_count += 1
            
            # Add run_id to values for WHERE clause
            values.append(run_id)
            
            query = f"""
                UPDATE simulation_runs 
                SET {', '.join(set_clauses)}
                WHERE run_id = ${param_count}
            """
            
            async with self.connection_pool.acquire() as conn:
                await self._execute_with_logging(conn, query, *values)
        
        try:
            await self._execute_with_retry(_update_operation)
            filtered_count = len([k for k in updates.keys() if k != 'updated_at'])
            if filtered_count > 0:
                logger.info(f"✅ PostgreSQL: Updated simulation run {run_id} with {filtered_count} fields: {[k for k in updates.keys() if k != 'updated_at']}")
            else:
                logger.debug(f"📊 PostgreSQL: No database update needed for {run_id} (only updated_at was provided)")
            return True
        except Exception as e:
            logger.error(f"❌ PostgreSQL: Failed to update simulation run {run_id}: {e}")
            
            # Backup to file as fallback
            backup_data = {"run_id": run_id, "updates": updates}
            if self._backup_to_file("update_simulation_run", backup_data):
                logger.info(f"Simulation run update {run_id} backed up to file")
            
            return False

    async def get_simulation_run(self, run_id: str) -> Optional[SimulationRun]:
        """Get simulation run by ID"""
        try:
            async with self.connection_pool.acquire() as conn:
                row = await self._fetchrow_with_logging(
                    conn, "SELECT * FROM simulation_runs WHERE run_id = $1", run_id
                )
                if row:
                    return SimulationRun(**dict(row))
                return None
        except Exception as e:
            logger.error(f"Failed to get simulation run {run_id}: {e}")
            return None

    async def list_simulation_runs(self, 
                                 limit: int = 100, 
                                 offset: int = 0,
                                 status: Optional[SimulationStatus] = None,
                                 algorithm_version: Optional[str] = None) -> List[SimulationRun]:
        """List simulation runs with filtering"""
        try:
            query = "SELECT * FROM simulation_runs"
            conditions = []
            values = []
            param_count = 1

            if status:
                conditions.append(f"status = ${param_count}")
                values.append(status.value)
                param_count += 1

            if algorithm_version:
                conditions.append(f"algorithm_version = ${param_count}")
                values.append(algorithm_version)
                param_count += 1

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += f" ORDER BY start_time DESC LIMIT ${param_count} OFFSET ${param_count + 1}"
            values.extend([limit, offset])

            async with self.connection_pool.acquire() as conn:
                rows = await conn.fetch(query, *values)
                return [SimulationRun(**dict(row)) for row in rows]
        except Exception as e:
            logger.error(f"Failed to list simulation runs: {e}")
            return []

    async def add_trade(self, trade: Trade) -> bool:
        """Add a trade record"""
        try:
            async with self.connection_pool.acquire() as conn:
                await self._execute_with_logging(conn, """
                    INSERT INTO trades (
                        run_id, trade_id, symbol, side, quantity, price, 
                        timestamp_ms, confidence, fees, source_algo
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """, 
                    trade.run_id, trade.trade_id, trade.symbol, trade.side.value,
                    trade.quantity, trade.price, trade.timestamp_ms, trade.confidence,
                    trade.fees, trade.source_algo
                )
            logger.info(f"✅ PostgreSQL: Added trade {trade.symbol} {trade.side.value} {trade.quantity}@{trade.price} for run {trade.run_id}")
            return True
        except Exception as e:
            logger.error(f"❌ PostgreSQL: Failed to add trade for run {trade.run_id}: {e}")
            return False

    async def get_trades(self, run_id: str) -> List[Trade]:
        """Get all trades for a simulation run"""
        try:
            async with self.connection_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM trades WHERE run_id = $1 ORDER BY timestamp_ms", 
                    run_id
                )
                return [Trade(**dict(row)) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get trades for run {run_id}: {e}")
            return []

    async def upsert_position(self, position: Position) -> bool:
        """Insert or update a position record"""
        try:
            async with self.connection_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO positions (
                        run_id, symbol, quantity, avg_price, unrealized_pnl, 
                        realized_pnl, last_price, last_update_ms
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (run_id, symbol) 
                    DO UPDATE SET 
                        quantity = EXCLUDED.quantity,
                        avg_price = EXCLUDED.avg_price,
                        unrealized_pnl = EXCLUDED.unrealized_pnl,
                        realized_pnl = EXCLUDED.realized_pnl,
                        last_price = EXCLUDED.last_price,
                        last_update_ms = EXCLUDED.last_update_ms
                """, 
                    position.run_id, position.symbol, position.quantity, 
                    position.avg_price, position.unrealized_pnl, position.realized_pnl,
                    position.last_price, position.last_update_ms
                )
            logger.info(f"✅ PostgreSQL: Upserted position {position.symbol} qty={position.quantity} for run {position.run_id}")
            return True
        except Exception as e:
            logger.error(f"❌ PostgreSQL: Failed to upsert position for run {position.run_id}: {e}")
            return False

    async def get_positions(self, run_id: str) -> List[Position]:
        """Get all positions for a simulation run"""
        try:
            async with self.connection_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM positions WHERE run_id = $1 ORDER BY symbol", 
                    run_id
                )
                return [Position(**dict(row)) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get positions for run {run_id}: {e}")
            return []

    async def get_performance_summary(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get performance summary for a simulation run"""
        try:
            async with self.connection_pool.acquire() as conn:
                # Get basic stats
                sim_row = await conn.fetchrow("""
                    SELECT net_pnl, return_pct, total_trades, win_rate, 
                           max_drawdown, sharpe_ratio, signals_received, signals_executed
                    FROM simulation_runs WHERE run_id = $1
                """, run_id)
                
                if not sim_row:
                    return None
                
                # Get trade count by side
                trade_stats = await conn.fetchrow("""
                    SELECT 
                        COUNT(CASE WHEN side = 'BUY' THEN 1 END) as buy_trades,
                        COUNT(CASE WHEN side = 'SELL' THEN 1 END) as sell_trades,
                        AVG(confidence) as avg_confidence,
                        SUM(fees) as total_fees
                    FROM trades WHERE run_id = $1
                """, run_id)
                
                # Get position stats
                position_stats = await conn.fetchrow("""
                    SELECT 
                        COUNT(*) as total_positions,
                        SUM(realized_pnl) as total_realized_pnl,
                        SUM(unrealized_pnl) as total_unrealized_pnl
                    FROM positions WHERE run_id = $1 AND quantity != 0
                """, run_id)
                
                return {
                    "simulation": dict(sim_row) if sim_row else {},
                    "trades": dict(trade_stats) if trade_stats else {},
                    "positions": dict(position_stats) if position_stats else {}
                }
        except Exception as e:
            logger.error(f"Failed to get performance summary for run {run_id}: {e}")
            return None

# Global client instance
postgres_client = PostgresClient()