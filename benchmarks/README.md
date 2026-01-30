# Benchmarks & Manual Tests

These tests are excluded from CI as they take a long time to run.

## Running Benchmarks

```bash
# Run all benchmarks
pytest benchmarks/ -v

# Run specific benchmark
pytest benchmarks/test_stress.py -v
pytest benchmarks/test_limit.py -v

# Run integration tests
pytest benchmarks/test_integration_complex.py -v
```

## Test Descriptions

- **test_stress.py** - Measures SDK throughput (transactions per second)
- **test_limit.py** - Finds concurrency limits and burst capacity
- **test_integration_complex.py** - End-to-end workflow tests with mocks
