#!/bin/bash

# Source the setup script from the project root
source ../setup.sh

# Add the project root to PYTHONPATH
export PYTHONPATH=$PYTHONPATH:$(dirname $(dirname $(realpath $0)))

# Array to store PIDs
declare -a pids

# Function to cleanup processes
cleanup() {
    echo "Cleaning up calculator services..."
    # Kill all child processes
    for pid in "${pids[@]}"; do
        if ps -p $pid > /dev/null; then
            kill $pid 2>/dev/null
        fi
    done
    exit 0
}

# Set up trap for cleanup on script termination
trap cleanup SIGINT SIGTERM EXIT

# Start calculator services
NUM_SERVICES=5  # Reduced from 20 to 5 for testing
echo "Starting $NUM_SERVICES calculator services..."
for i in $(seq 1 $NUM_SERVICES); do
    python ../test_functions/calculator_service.py > /dev/null 2>&1 &
    pids+=($!)
    echo "Started calculator service $i with PID ${pids[-1]}"
    # Increased delay between starts to prevent overwhelming the system
    sleep 0.5
done

# Wait for services to start
echo "Waiting for services to start..."
sleep 3

# Run a test client that makes requests to the services
echo "Running test client..."
python -c "
import sys
import time
from genesis_lib.rpc_client import RPCClient

# Create a client
client = RPCClient('CalculatorService')

# Wait for service to be available
time.sleep(1)

# Make multiple requests
for i in range(10):
    # Test the add function
    result = client.call_function('add', {'a': i, 'b': i*2})
    print(f'{i} + {i*2} = {result}')
    
    # Test the multiply function
    result = client.call_function('multiply', {'a': i, 'b': i+1})
    print(f'{i} * {i+1} = {result}')
    
    time.sleep(0.1)

print('Tests completed successfully')
"

echo "Tests completed. Shutting down services..." 
