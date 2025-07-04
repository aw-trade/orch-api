#!/bin/bash

# Redis Stream Setup Script
# This script initializes Redis streams and consumer groups for the trading API

set -e

echo "🚀 Setting up Redis streams and consumer groups..."

# Check if Redis is available
echo "📡 Checking Redis connection..."
if ! redis-cli ping > /dev/null 2>&1; then
    echo "❌ Redis is not available. Please ensure Redis is running."
    exit 1
fi

echo "✅ Redis is available"

# Configuration
STREAM_NAME="${REDIS_STREAM_NAME:-trading-stats}"
CONSUMER_GROUP="${REDIS_CONSUMER_GROUP:-trading-api-group}"
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"

echo "📊 Stream name: $STREAM_NAME"
echo "👥 Consumer group: $CONSUMER_GROUP"
echo "🔌 Redis: $REDIS_HOST:$REDIS_PORT"

# Function to run Redis command
run_redis_cmd() {
    redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" "$@"
}

# Check if stream exists
echo "🔍 Checking if stream exists..."
if run_redis_cmd EXISTS "$STREAM_NAME" | grep -q "1"; then
    echo "📊 Stream '$STREAM_NAME' already exists"
    STREAM_LENGTH=$(run_redis_cmd XLEN "$STREAM_NAME")
    echo "📈 Stream length: $STREAM_LENGTH messages"
else
    echo "📊 Stream '$STREAM_NAME' does not exist"
fi

# Create consumer group (this will create the stream if it doesn't exist)
echo "👥 Creating consumer group..."
if run_redis_cmd XGROUP CREATE "$STREAM_NAME" "$CONSUMER_GROUP" 0 MKSTREAM 2>/dev/null; then
    echo "✅ Consumer group '$CONSUMER_GROUP' created successfully"
else
    # Check if it's because the group already exists
    if run_redis_cmd XINFO GROUPS "$STREAM_NAME" 2>/dev/null | grep -q "$CONSUMER_GROUP"; then
        echo "📊 Consumer group '$CONSUMER_GROUP' already exists"
    else
        echo "❌ Failed to create consumer group"
        exit 1
    fi
fi

# Verify setup
echo "🔍 Verifying setup..."

# Get stream info
echo "📊 Stream information:"
run_redis_cmd XINFO STREAM "$STREAM_NAME" | grep -E "(length|groups|first-entry|last-entry)" || true

# Get consumer group info
echo "👥 Consumer group information:"
run_redis_cmd XINFO GROUPS "$STREAM_NAME" || true

# Add a test message to verify stream functionality
echo "🧪 Adding test message..."
TEST_MSG_ID=$(run_redis_cmd XADD "$STREAM_NAME" "*" \
    "type" "test" \
    "run_id" "setup-test" \
    "data" '{"message": "Redis stream setup completed successfully"}' \
    "timestamp" "$(date -u +%Y-%m-%dT%H:%M:%SZ)")

echo "✅ Test message added with ID: $TEST_MSG_ID"

# Show final stream status
echo "📈 Final stream status:"
echo "   Stream: $STREAM_NAME"
echo "   Length: $(run_redis_cmd XLEN "$STREAM_NAME")"
echo "   Consumer groups: $(run_redis_cmd XINFO GROUPS "$STREAM_NAME" | grep -c "name" || echo "0")"

echo "🎉 Redis stream setup completed successfully!"
echo ""
echo "💡 You can now start the Redis consumer to process messages from the '$STREAM_NAME' stream"
echo "   using consumer group '$CONSUMER_GROUP'"