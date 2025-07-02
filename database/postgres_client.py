import asyncpg
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime
import os
import logging
from .models import SimulationRun, Trade, Position, SimulationStatus

logger = logging.getLogger(__name__)

class PostgresClient:
    def __init__(self):
        self.connection_pool = None
        self.host = os.getenv("POSTGRES_HOST", "localhost")
        self.port = int(os.getenv("POSTGRES_PORT", "5432"))
        self.database = os.getenv("POSTGRES_DB", "trading_results")
        self.user = os.getenv("POSTGRES_USER", "trading_user")
        self.password = os.getenv("POSTGRES_PASSWORD", "trading_pass")

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
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL: {e}")
            raise

    async def disconnect(self):
        """Close connection pool"""
        if self.connection_pool:
            await self.connection_pool.close()
            logger.info("Disconnected from PostgreSQL")

    async def create_simulation_run(self, simulation: SimulationRun) -> bool:
        """Create a new simulation run record"""
        try:
            async with self.connection_pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO simulation_runs (
                        run_id, start_time, end_time, duration_seconds, algorithm_version, 
                        status, initial_capital, final_capital, total_pnl, total_fees, 
                        net_pnl, return_pct, max_drawdown, total_trades, winning_trades, 
                        losing_trades, win_rate, signals_received, signals_executed, 
                        execution_rate, total_volume, sharpe_ratio, avg_win, avg_loss
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, 
                             $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24)
                """, 
                    simulation.run_id, simulation.start_time, simulation.end_time,
                    simulation.duration_seconds, simulation.algorithm_version,
                    simulation.status.value, simulation.initial_capital, 
                    simulation.final_capital, simulation.total_pnl, simulation.total_fees,
                    simulation.net_pnl, simulation.return_pct, simulation.max_drawdown,
                    simulation.total_trades, simulation.winning_trades, simulation.losing_trades,
                    simulation.win_rate, simulation.signals_received, simulation.signals_executed,
                    simulation.execution_rate, simulation.total_volume, simulation.sharpe_ratio,
                    simulation.avg_win, simulation.avg_loss
                )
            logger.info(f"Created simulation run: {simulation.run_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to create simulation run {simulation.run_id}: {e}")
            return False

    async def update_simulation_run(self, run_id: str, updates: Dict[str, Any]) -> bool:
        """Update simulation run with new data"""
        try:
            if not updates:
                return True
                
            # Build dynamic update query
            set_clauses = []
            values = []
            param_count = 1
            
            for key, value in updates.items():
                set_clauses.append(f"{key} = ${param_count}")
                values.append(value)
                param_count += 1
            
            # Add run_id to values for WHERE clause
            values.append(run_id)
            
            query = f"""
                UPDATE simulation_runs 
                SET {', '.join(set_clauses)}, updated_at = NOW()
                WHERE run_id = ${param_count}
            """
            
            async with self.connection_pool.acquire() as conn:
                await conn.execute(query, *values)
            
            logger.info(f"Updated simulation run: {run_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to update simulation run {run_id}: {e}")
            return False

    async def get_simulation_run(self, run_id: str) -> Optional[SimulationRun]:
        """Get simulation run by ID"""
        try:
            async with self.connection_pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM simulation_runs WHERE run_id = $1", run_id
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
                await conn.execute("""
                    INSERT INTO trades (
                        run_id, trade_id, symbol, side, quantity, price, 
                        timestamp_ms, confidence, fees, source_algo
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """, 
                    trade.run_id, trade.trade_id, trade.symbol, trade.side.value,
                    trade.quantity, trade.price, trade.timestamp_ms, trade.confidence,
                    trade.fees, trade.source_algo
                )
            return True
        except Exception as e:
            logger.error(f"Failed to add trade for run {trade.run_id}: {e}")
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
            return True
        except Exception as e:
            logger.error(f"Failed to upsert position for run {position.run_id}: {e}")
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