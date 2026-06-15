#!/usr/bin/env bash
set -e

# Change to the root directory
cd "$(dirname "$0")/.."

mkdir -p reports/benchmarks



# Check if decision-api is running
if ! curl -s http://127.0.0.1:8000/v1/health &> /dev/null; then
    echo "Starting decision-api..."
    # Start the API in the background
    RATE_LIMIT_DECISIONS=100000 JWT_SECRET="test-secret-key-12345" PYTHONPATH=decision-api/src:. .venv/bin/uvicorn decision-api.src.main:app --host 127.0.0.1 --port 8000 &
    API_PID=$!
    # Wait for the API to start
    sleep 5
else
    echo "decision-api is already running."
fi

echo "Running k6 benchmark..."
set +e
docker run --rm -i \
  -v "$PWD/scripts:/scripts" \
  -v "$PWD/data:/data" \
  -v "$PWD/reports:/reports" \
  --network host \
  grafana/k6 run --out json=/reports/benchmarks/decision_api_benchmark.json \
  --summary-export=/reports/benchmarks/decision_api_benchmark_summary.json \
  /scripts/benchmark_decision_api.js
K6_EXIT_CODE=$?
set -e

echo "Extracting metrics..."
if [ -f reports/benchmarks/decision_api_benchmark_summary.json ]; then
    P50=$(cat reports/benchmarks/decision_api_benchmark_summary.json | python3 -c "import sys, json; print(json.load(sys.stdin)['metrics']['http_req_duration']['med'])")
    P95=$(cat reports/benchmarks/decision_api_benchmark_summary.json | python3 -c "import sys, json; print(json.load(sys.stdin)['metrics']['http_req_duration']['p(95)'])")
    P99=$(cat reports/benchmarks/decision_api_benchmark_summary.json | python3 -c "import sys, json; print(json.load(sys.stdin)['metrics']['http_req_duration']['p(99)'])")
    VUS_PEAK=50
    TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    if [ ! -f reports/benchmarks/benchmark_history.csv ]; then
        echo "timestamp,p50,p95,p99,vus_peak" > reports/benchmarks/benchmark_history.csv
    fi

    echo "$TIMESTAMP,$P50,$P95,$P99,$VUS_PEAK" >> reports/benchmarks/benchmark_history.csv

    echo "Metrics: p50=${P50}ms, p95=${P95}ms, p99=${P99}ms"

    if (( $(echo "$P99 < 200" | bc -l) )); then
        echo "Verdict: PASS (p99 is <200ms)"
    else
        echo "Verdict: FAIL (p99 is >=200ms target)"
    fi
fi

if [ -n "$API_PID" ]; then
    echo "Stopping decision-api (PID $API_PID)..."
    kill $API_PID
fi
