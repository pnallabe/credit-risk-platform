# Decision API Benchmark

This directory contains the results of the k6 load testing benchmark for the `/v1/decisions` endpoint.

## Running the Benchmark

You can run the benchmark by executing the script from the project root:

```bash
./scripts/run_benchmark.sh
```

This will:
1. Ensure the `decision-api` server is running locally (starting it if necessary).
2. Run a k6 test script simulating an increasing load of virtual users (VUs), peaking at 50 VUs.
3. Output the raw k6 summary to `decision_api_benchmark.json` and `decision_api_benchmark_summary.json`.
4. Append the high-level metrics to `benchmark_history.csv`.

## Thresholds

The benchmark strictly enforces the following performance targets:
- `p(95)` response time < 500ms
- `p(99)` response time < 1000ms
- Failed requests < 1%

These thresholds correspond to the claims made in our investor pitch deck.

## Infrastructure Disclaimer

Local SQLite baseline: Measured p99 will likely differ from production. Production Cloud SQL target: <200ms p99.
Full production benchmark pending PostgreSQL migration.

Note: Benchmark results on a SQLite in-process DB will not accurately reflect production performance due to database lock contention and IO differences.
Do NOT interpret local results as production-grade guarantees.
