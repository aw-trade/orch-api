-- PostgreSQL initialization script for trading simulation results

-- Create the main simulation runs table
CREATE TABLE IF NOT EXISTS simulation_runs (
    run_id VARCHAR(50) PRIMARY KEY,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER NOT NULL,
    algorithm_version VARCHAR(20),
    status VARCHAR(20) NOT NULL CHECK (status IN ('pending', 'running', 'completed', 'failed', 'stopped')),
    
    -- Financial metrics
    initial_capital DECIMAL(15,2),
    final_capital DECIMAL(15,2),
    total_pnl DECIMAL(15,2),
    total_fees DECIMAL(15,2),
    net_pnl DECIMAL(15,2),
    return_pct DECIMAL(8,4),
    max_drawdown DECIMAL(8,4),
    
    -- Trading metrics
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,
    win_rate DECIMAL(5,4),
    signals_received INTEGER DEFAULT 0,
    signals_executed INTEGER DEFAULT 0,
    execution_rate DECIMAL(5,4),
    total_volume DECIMAL(15,2),
    
    -- Performance metrics
    sharpe_ratio DECIMAL(8,4),
    avg_win DECIMAL(15,2),
    avg_loss DECIMAL(15,2),
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create trades table for individual trade records
CREATE TABLE IF NOT EXISTS trades (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(50) NOT NULL REFERENCES simulation_runs(run_id) ON DELETE CASCADE,
    trade_id BIGINT NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
    quantity DECIMAL(15,8) NOT NULL,
    price DECIMAL(15,8) NOT NULL,
    timestamp_ms BIGINT NOT NULL,
    confidence DECIMAL(5,4),
    fees DECIMAL(15,8),
    source_algo VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create positions table for final positions per simulation
CREATE TABLE IF NOT EXISTS positions (
    id SERIAL PRIMARY KEY,
    run_id VARCHAR(50) NOT NULL REFERENCES simulation_runs(run_id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    quantity DECIMAL(15,8) NOT NULL,
    avg_price DECIMAL(15,8),
    unrealized_pnl DECIMAL(15,2),
    realized_pnl DECIMAL(15,2),
    last_price DECIMAL(15,8),
    last_update_ms BIGINT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(run_id, symbol)
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_trades_run_id ON trades(run_id);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp_ms);
CREATE INDEX IF NOT EXISTS idx_trades_side ON trades(side);

CREATE INDEX IF NOT EXISTS idx_positions_run_id ON positions(run_id);
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);

CREATE INDEX IF NOT EXISTS idx_simulation_runs_start_time ON simulation_runs(start_time);
CREATE INDEX IF NOT EXISTS idx_simulation_runs_status ON simulation_runs(status);
CREATE INDEX IF NOT EXISTS idx_simulation_runs_algorithm ON simulation_runs(algorithm_version);

-- Create a function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create trigger to automatically update updated_at
CREATE TRIGGER update_simulation_runs_updated_at 
    BEFORE UPDATE ON simulation_runs 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Insert some initial data for testing
INSERT INTO simulation_runs (
    run_id, 
    start_time, 
    duration_seconds, 
    algorithm_version, 
    status, 
    initial_capital
) VALUES (
    'test_run_001', 
    NOW(), 
    300, 
    'v1.0.0', 
    'pending', 
    100000.0
) ON CONFLICT (run_id) DO NOTHING;

-- Grant necessary permissions to the trading_user
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO trading_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO trading_user;