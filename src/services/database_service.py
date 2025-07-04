"""Database service for handling Redis stream data"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from ..database.postgres_client import PostgresClient
from ..database.mongodb_client import MongoDBClient
from ..database.models import SimulationRun, Trade, Position, SimulationStatus

logger = logging.getLogger(__name__)

class DatabaseService:
    """Service for handling database operations from Redis stream data"""
    
    def __init__(self):
        self.postgres_client = PostgresClient()
        self.mongodb_client = MongoDBClient()
    
    async def connect(self):
        """Initialize database connections"""
        try:
            logger.info("🔌 Connecting to PostgreSQL...")
            await self.postgres_client.connect()
            logger.info("✅ PostgreSQL connected")
            
            logger.info("🔌 Connecting to MongoDB...")
            await self.mongodb_client.connect()
            logger.info("✅ MongoDB connected")
            
        except Exception as e:
            logger.error(f"❌ Database connection failed: {e}")
            raise
    
    async def disconnect(self):
        """Close database connections"""
        try:
            logger.info("🔌 Disconnecting from databases...")
            await self.postgres_client.disconnect()
            await self.mongodb_client.disconnect()
            logger.info("✅ Database connections closed")
        except Exception as e:
            logger.error(f"❌ Database disconnection error: {e}")
    
    async def is_connected(self) -> bool:
        """Check if database connections are healthy"""
        try:
            postgres_healthy = self.postgres_client.connection_pool is not None
            mongodb_healthy = self.mongodb_client.client is not None
            return postgres_healthy and mongodb_healthy
        except Exception:
            return False
    
    async def update_simulation_live_stats(self, run_id: str, stats_data: Dict[str, Any]):
        """Update simulation run with live statistics from Redis stream"""
        # Check database connection first
        if not await self.is_connected():
            logger.error(f"❌ Database not connected - cannot update live stats for {run_id}")
            raise ConnectionError("Database not connected")
        
        try:
            logger.debug(f"📊 Converting stats data for run_id: {run_id}")
            # Convert Redis stream data to database format
            update_data = self._convert_stats_to_db_format(stats_data)
            logger.debug(f"📊 Update data: {update_data}")
            
            # Update simulation run record
            logger.debug(f"📊 Updating PostgreSQL for run_id: {run_id}")
            await self.postgres_client.update_simulation_run(run_id, update_data)
            logger.info(f"✅ Successfully updated live stats for run_id: {run_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to update live stats for {run_id}: {e}")
            logger.error(f"📋 Stats data: {stats_data}")
            raise
    
    async def update_simulation_final_results(self, run_id: str, results_data: Dict[str, Any]):
        """Update simulation run with final results from Redis stream"""
        # Check database connection first
        if not await self.is_connected():
            logger.error(f"❌ Database not connected - cannot update final results for {run_id}")
            raise ConnectionError("Database not connected")
        
        try:
            logger.info(f"🏁 Processing final results for run_id: {run_id}")
            
            # Convert Redis stream data to database format
            final_data = self._convert_stats_to_db_format(results_data)
            final_data.update({
                'status': SimulationStatus.COMPLETED,
                'end_time': datetime.now()
            })
            logger.debug(f"🏁 Final data: {final_data}")
            
            # Update simulation run record
            logger.debug(f"🏁 Updating simulation run in PostgreSQL")
            await self.postgres_client.update_simulation_run(run_id, final_data)
            
            # Store trades if present
            if 'trades' in results_data:
                logger.info(f"🏁 Storing {len(results_data['trades'])} trades for run_id: {run_id}")
                await self._store_trades(run_id, results_data['trades'])
            
            # Store positions if present
            if 'positions_by_symbol' in results_data:
                logger.info(f"🏁 Storing {len(results_data['positions_by_symbol'])} positions for run_id: {run_id}")
                await self._store_positions(run_id, results_data['positions_by_symbol'])
            
            logger.info(f"✅ Successfully updated final results for run_id: {run_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to update final results for {run_id}: {e}")
            logger.error(f"📋 Results data: {results_data}")
            raise
    
    async def store_trade_event(self, run_id: str, trade_data: Dict[str, Any]):
        """Store individual trade event from Redis stream"""
        # Check database connection first
        if not await self.is_connected():
            logger.error(f"❌ Database not connected - cannot store trade event for {run_id}")
            raise ConnectionError("Database not connected")
        
        try:
            logger.debug(f"💱 Creating trade object for run_id: {run_id}")
            trade = Trade(
                run_id=run_id,
                trade_id=trade_data.get('id', 0),
                symbol=trade_data.get('symbol', ''),
                side=trade_data.get('side', 'BUY'),
                quantity=trade_data.get('quantity', 0.0),
                price=trade_data.get('price', 0.0),
                timestamp_ms=trade_data.get('timestamp', 0),
                confidence=trade_data.get('confidence'),
                fees=trade_data.get('fees'),
                source_algo=trade_data.get('source_algo')
            )
            
            logger.debug(f"💱 Adding trade to PostgreSQL: {trade.symbol} {trade.side} {trade.quantity}@{trade.price}")
            await self.postgres_client.add_trade(trade)
            logger.info(f"✅ Successfully stored trade event for run_id: {run_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to store trade event for {run_id}: {e}")
            logger.error(f"📋 Trade data: {trade_data}")
            raise
    
    def _convert_stats_to_db_format(self, stats_data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Redis stream stats data to database format"""
        db_data = {}
        
        # Financial metrics
        if 'final_capital' in stats_data:
            db_data['final_capital'] = stats_data['final_capital']
        if 'total_pnl' in stats_data:
            db_data['total_pnl'] = stats_data['total_pnl']
        if 'total_fees' in stats_data:
            db_data['total_fees'] = stats_data['total_fees']
        if 'net_pnl' in stats_data:
            db_data['net_pnl'] = stats_data['net_pnl']
        if 'return_pct' in stats_data:
            db_data['return_pct'] = stats_data['return_pct']
        if 'max_drawdown' in stats_data:
            db_data['max_drawdown'] = stats_data['max_drawdown']
        
        # Trading metrics
        if 'total_trades' in stats_data:
            db_data['total_trades'] = stats_data['total_trades']
        if 'winning_trades' in stats_data:
            db_data['winning_trades'] = stats_data['winning_trades']
        if 'losing_trades' in stats_data:
            db_data['losing_trades'] = stats_data['losing_trades']
        if 'win_rate' in stats_data:
            db_data['win_rate'] = stats_data['win_rate']
        if 'signals_received' in stats_data:
            db_data['signals_received'] = stats_data['signals_received']
        if 'signals_executed' in stats_data:
            db_data['signals_executed'] = stats_data['signals_executed']
        if 'total_volume' in stats_data:
            db_data['total_volume'] = stats_data['total_volume']
        
        # Performance metrics
        if 'sharpe_ratio' in stats_data:
            db_data['sharpe_ratio'] = stats_data['sharpe_ratio']
        if 'avg_win' in stats_data:
            db_data['avg_win'] = stats_data['avg_win']
        if 'avg_loss' in stats_data:
            db_data['avg_loss'] = stats_data['avg_loss']
        
        # Calculate execution rate if both signals_received and signals_executed are present
        if 'signals_received' in stats_data and 'signals_executed' in stats_data:
            signals_received = stats_data['signals_received']
            if signals_received > 0:
                db_data['execution_rate'] = stats_data['signals_executed'] / signals_received
        
        return db_data
    
    async def _store_trades(self, run_id: str, trades_data: list):
        """Store multiple trades from final results"""
        for trade_data in trades_data:
            trade = Trade(
                run_id=run_id,
                trade_id=trade_data.get('id', 0),
                symbol=trade_data.get('symbol', ''),
                side=trade_data.get('side', 'BUY'),
                quantity=trade_data.get('quantity', 0.0),
                price=trade_data.get('price', 0.0),
                timestamp_ms=trade_data.get('timestamp', 0),
                confidence=trade_data.get('confidence'),
                fees=trade_data.get('fees'),
                source_algo=trade_data.get('source_algo')
            )
            await self.postgres_client.add_trade(trade)
    
    async def _store_positions(self, run_id: str, positions_data: Dict[str, Any]):
        """Store positions from final results"""
        for symbol, position_data in positions_data.items():
            position = Position(
                run_id=run_id,
                symbol=symbol,
                quantity=position_data.get('quantity', 0.0),
                avg_price=position_data.get('avg_price'),
                unrealized_pnl=position_data.get('unrealized_pnl'),
                realized_pnl=position_data.get('realized_pnl'),
                last_price=position_data.get('last_price'),
                last_update_ms=position_data.get('last_update')
            )
            await self.postgres_client.upsert_position(position)