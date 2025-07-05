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
            logger.info(f"📊 Processing live stats for run_id: {run_id}")
            
            # Log run_id format analysis for debugging
            if run_id.startswith('sim_'):
                logger.info(f"🔍 Detected Rust simulator run_id format: {run_id}")
                logger.info(f"🔍 This indicates the update is coming from the trade-simulator (Rust)")
            elif run_id.startswith('run_'):
                logger.info(f"🔍 Detected Python API run_id format: {run_id}")
                logger.info(f"🔍 This indicates the update is coming from the orchestration API")
            else:
                logger.warning(f"🔍 Unknown run_id format: {run_id}")
            
            # Convert Redis stream data to database format
            update_data = self._convert_stats_to_db_format(stats_data)
            logger.info(f"📊 Update data ({len(update_data)} fields): {list(update_data.keys())}")
            
            if not update_data:
                logger.warning(f"⚠️ No valid update data found for run_id: {run_id}")
                return
            
            # Update simulation run record
            logger.info(f"📊 Updating PostgreSQL for run_id: {run_id}")
            success = await self.postgres_client.update_simulation_run(run_id, update_data)
            
            if success:
                logger.info(f"✅ Successfully updated live stats for run_id: {run_id}")
            else:
                logger.error(f"❌ Failed to update live stats for run_id: {run_id} - see warnings above")
            
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
        logger.info(f"📊 Raw stats data received: {stats_data}")
        logger.info(f"📊 Available fields: {list(stats_data.keys())}")
        db_data = {}
        
        # Create field mapping for flexible conversion including nested paths
        field_mapping = {
            # Financial metrics - check multiple possible field names including nested paths
            'final_capital': ['final_capital', 'capital', 'final_balance', 'balance', 'financials.current_capital', 'financials.final_capital'],
            'total_pnl': ['total_pnl', 'pnl', 'total_profit_loss', 'profit_loss', 'financials.total_pnl', 'financials.net_pnl'],
            'total_fees': ['total_fees', 'fees', 'total_commission', 'commission', 'financials.total_fees'],
            'net_pnl': ['net_pnl', 'net_profit_loss', 'net_profit', 'net_loss', 'financials.net_pnl'],
            'return_pct': ['return_pct', 'return_percentage', 'return', 'percentage_return', 'financials.return_pct'],
            'max_drawdown': ['max_drawdown', 'maximum_drawdown', 'drawdown', 'financials.max_drawdown'],
            
            # Trading metrics - prioritize nested paths first to avoid matching parent objects
            'total_trades': ['trades.total', 'total_trades', 'trade_count', 'num_trades'],
            'winning_trades': ['trades.winning', 'winning_trades', 'wins', 'profitable_trades'],
            'losing_trades': ['trades.losing', 'losing_trades', 'losses', 'unprofitable_trades'],
            'win_rate': ['trades.win_rate', 'win_rate', 'win_ratio', 'success_rate'],
            'signals_received': ['signals.received', 'signals_received', 'total_signals'],
            'signals_executed': ['signals.executed', 'signals_executed', 'executed_signals', 'trades_executed'],
            'total_volume': ['total_volume', 'volume', 'total_traded_volume'],
            
            # Performance metrics
            'sharpe_ratio': ['sharpe_ratio', 'sharpe'],
            'avg_win': ['avg_win', 'average_win', 'mean_win'],
            'avg_loss': ['avg_loss', 'average_loss', 'mean_loss']
        }
        
        # Map fields using the flexible mapping including nested field support
        for db_field, possible_names in field_mapping.items():
            for field_name in possible_names:
                value = self._get_nested_value(stats_data, field_name)
                if value is not None:
                    db_data[db_field] = value
                    logger.debug(f"📊 Mapped {field_name} -> {db_field}: {value} (type: {type(value)})")
                    break
        
        # Calculate execution rate if both signals_received and signals_executed are present
        if 'signals_received' in db_data and 'signals_executed' in db_data:
            signals_received = db_data['signals_received']
            signals_executed = db_data['signals_executed']
            
            # Ensure both values are numeric
            if isinstance(signals_received, (int, float)) and isinstance(signals_executed, (int, float)):
                if signals_received > 0:
                    db_data['execution_rate'] = signals_executed / signals_received
            else:
                logger.warning(f"⚠️ Invalid data types for execution rate calculation: signals_received={type(signals_received)}, signals_executed={type(signals_executed)}")
        
        return db_data
    
    def _get_nested_value(self, data: Dict[str, Any], field_path: str) -> Any:
        """Get value from nested dictionary using dot notation path"""
        if '.' not in field_path:
            # Simple field access
            return data.get(field_path)
        
        # Handle nested field access
        parts = field_path.split('.')
        current = data
        
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        
        return current
    
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