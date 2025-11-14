# Download Endpoint Benchmarking with Locust

This directory contains Locust-based benchmarking tools for testing QuickBBS download endpoints, designed to replicate Apache Benchmark (ab) functionality with better reporting and historical comparison.

## Quick Start

### 1. Run a Benchmark

```bash
# Make sure the QuickBBS server is running
python manage.py runserver 0.0.0.0:8888

# In another terminal, run the benchmark (from quickbbs/ directory)
cd quickbbs
python run_download_benchmark.py
```

This will test the three download endpoints:
- **1MB file**: `/download_file/test1.txt`
- **5MB file**: `/download_file/test5.txt`
- **10MB file**: `/download_file/test10.txt`

**Default settings**: 50 concurrent users, 30 second run time

**Note**: Unlike Apache Benchmark which makes exactly N requests, Locust runs for a fixed 30 second time period. The actual number of requests will vary based on your server's response time and network speed. The `--requests` parameter is no longer used to calculate run time, but is kept for compatibility with the comparison scripts.

### 2. View Results

The benchmark generates several output files in `benchmark_results/`:

- **`benchmark_YYYYMMDD_HHMMSS.html`** - Interactive HTML report
- **`benchmark_YYYYMMDD_HHMMSS.json`** - JSON data for comparison
- **`benchmark_YYYYMMDD_HHMMSS_*.csv`** - Raw CSV data

The terminal output shows an Apache Benchmark-style summary with:
- Requests per second
- Transfer rates
- Latency percentiles (50th, 90th, 95th, 99th)
- Per-endpoint statistics

### 3. Compare Results Over Time

**Option A: Interactive Web Dashboard (Recommended)**

Open the HTML dashboard in your browser:
```bash
open benchmark_dashboard.html
```

Then select up to 5 JSON files from `benchmark_results/` directory. Features:
- Interactive charts comparing RPS, latency, transfer rates
- Server configuration comparison (highlights HTTP/2 vs HTTP/1.1)
- Per-endpoint breakdowns with visualizations
- Side-by-side metrics tables
- Color-coded performance indicators

**Option B: Command-Line Comparison**

```bash
# Compare latest 2 runs
python compare_benchmark_results.py

# Compare latest 5 runs
python compare_benchmark_results.py --last 5

# Compare specific runs
python compare_benchmark_results.py \
    benchmark_results/benchmark_20250124_120000.json \
    benchmark_results/benchmark_20250124_130000.json

# List all available results
python compare_benchmark_results.py --list
```

## Advanced Usage

### SSL Certificate Verification

If you're testing against an HTTPS server with a self-signed certificate, use the `--insecure` flag to disable SSL certificate verification:

```bash
# Test HTTPS server with self-signed cert
python run_download_benchmark.py \
    --host https://localhost:8443 \
    --insecure
```

You can also set the environment variable directly:

```bash
# Using environment variable
export LOCUST_INSECURE=1
python run_download_benchmark.py --host https://localhost:8443
```

### Custom Parameters

```bash
# More users and requests
python run_download_benchmark.py --users 100 --requests 500

# Different server
python run_download_benchmark.py --host http://localhost:8000

# Custom spawn rate
python run_download_benchmark.py --users 50 --spawn-rate 10

# HTTPS with self-signed certificate
python run_download_benchmark.py \
    --host https://localhost:8443 \
    --insecure

# All options
python run_download_benchmark.py \
    --host https://localhost:8443 \
    --users 50 \
    --requests 200 \
    --spawn-rate 50 \
    --output-dir my_results \
    --insecure
```

### Running Locust Directly (with UI)

If you want to use Locust's web UI for interactive testing:

```bash
# HTTP
locust -f locustfile_downloads.py --host http://localhost:8888

# HTTPS with self-signed cert
export LOCUST_INSECURE=1
locust -f locustfile_downloads.py --host https://localhost:8443
```

Then open http://localhost:8089 in your browser.

## Files

- **`locustfile_downloads.py`** - Locust test definition with httpx HTTP/2 client (tasks and user behavior)
- **`run_download_benchmark.py`** - Wrapper script that runs Locust headlessly with Apache Benchmark-style output
- **`compare_benchmark_results.py`** - Command-line tool to compare multiple benchmark runs
- **`benchmark_dashboard.html`** - Interactive web dashboard for visual comparison (up to 5 runs)
- **`benchmark_results/`** - Output directory (created automatically)

## HTTP/2 Support

This benchmark uses **httpx** instead of the standard `requests` library to support HTTP/2 protocol testing. The `requests` library only supports HTTP/1.1, so we use `httpx` with HTTP/2 enabled.

**Requirements:**
- `httpx[http2]` - Installed via `poetry add "httpx[http2]" --group dev`
- `h2` library - Provides HTTP/2 protocol support (already installed)

When the server supports HTTP/2 (via HTTPS with ALPN negotiation), the benchmark will automatically use it and report "HTTP/2" in the server configuration output.

## Understanding the Output

### Terminal Output

The benchmark prints results similar to Apache Benchmark:

```
==============================================================================
BENCHMARK SUMMARY (Apache Benchmark Style)
==============================================================================
Server:              http://localhost:8888
Concurrency Level:   50
Complete requests:   200
Failed requests:     0
Requests per second: 45.23 [#/sec] (mean)
Transfer rate:       150.45 MB/sec

Connection Times (ms)
              min    mean   median   p90    p95    p99    max
Total:        150    220    210      280    310    350    450

Per-Endpoint Statistics:

1MB Download:
  Requests:      67
  Failures:      0
  Avg size:      1.00 MB
  Transfer rate: 50.12 MB/sec
  RPS:           15.08
  Latency:
    Median:      180 ms
    90th %ile:   250 ms
    95th %ile:   280 ms
    99th %ile:   320 ms
...
```

### Comparison Output

The comparison script shows changes between runs:

```
Overall Performance Comparison:
-------------------------------------------------------------------------------------
Metric                    | Run  1           | Run  2           | Change
-------------------------------------------------------------------------------------
Requests                  |              200 |              200 | 0.0%
Failures                  |                0 |                0 | 0.0%
Requests/sec              |            45.23 |            48.50 | +7.2% ✓
Avg Latency (ms)          |            220.1 |            205.8 | -6.5% ✓
P95 Latency (ms)          |            310.2 |            298.5 | -3.8% ✓
Transfer rate             |      150.45 MB/sec |      161.20 MB/sec | +7.1% ✓
```

- **✓** = Improvement
- **✗** = Regression
- **+%** = Increase
- **-%** = Decrease

### Server Configuration Detection

The benchmark automatically detects and records server configuration information on the first request. This information appears in both the summary output and comparison reports:

**In Summary Output:**
```
==============================================================================
BENCHMARK SUMMARY (Apache Benchmark Style)
==============================================================================
Server:              http://localhost:8888
Server Software:     uvicorn
HTTP Protocol:       HTTP/2
Concurrency Level:   50
...
```

**In Comparison Output:**
```
Server Configuration:
----------------------------------------------------------------------------------------------------
Setting                   | Run  1           | Run  2
----------------------------------------------------------------------------------------------------
Server Software           |          uvicorn |      gunicorn
HTTP Protocol             |          HTTP/2  |       HTTP/1.1   ⚠️  CHANGED
Connection Type           |       keep-alive |       keep-alive
Alt-Svc Header            |              N/A |              N/A
----------------------------------------------------------------------------------------------------
```

**Detected Information:**
- **Server Software**: Web server type (uvicorn, gunicorn, daphne, Django dev server)
- **HTTP Protocol**: Protocol version (HTTP/1.0, HTTP/1.1, HTTP/2, HTTP/3)
- **Connection Type**: Connection header value (keep-alive, close)
- **Alt-Svc Header**: Alternative services advertised (HTTP/2, HTTP/3 hints)

**Configuration Changes:**
When comparing benchmarks, any server configuration changes are marked with ⚠️ **CHANGED**. This helps identify when performance differences are due to server configuration changes (e.g., upgrading from HTTP/1.1 to HTTP/2).

**Implementation Notes:**
- Server info is captured once at the start of each benchmark run
- Information is saved to `benchmark_results/server_info.json`
- The wrapper script (`run_download_benchmark.py`) reads this file and includes it in the JSON results
- Comparison script displays configuration side-by-side and highlights changes

## Comparison to Apache Benchmark

### What's Better in Locust

1. **Historical comparison** - JSON results can be compared over time
2. **Per-endpoint metrics** - See individual stats for each download size
3. **HTML reports** - Interactive charts and graphs
4. **More flexible** - Easy to add new endpoints or change behavior
5. **Better statistics** - More percentiles, better reporting

### Apache Benchmark Equivalent

The old command:
```bash
ab -n 200 -c 50 http://localhost:8888/download_file/test1.txt?usha=...
```

Is now:
```bash
python run_download_benchmark.py --users 50 --requests 200
```

**Key differences:**
- Locust tests **all three endpoints** in one run (1MB, 5MB, 10MB)
- Runs for fixed 30 seconds instead of counting requests
  - Request count will vary based on server performance
  - Focus on requests/sec metric for comparisons
- Results are saved for later comparison
- More detailed latency statistics
- 1-2 second wait time between requests per user (more realistic load pattern)

## Troubleshooting

### Server Not Running

```
Error: Connection refused
```

**Solution**: Start the QuickBBS server first:
```bash
cd quickbbs && python manage.py runserver 0.0.0.0:8888
```

### Request Count Varies

The actual request count will vary because the benchmark runs for a fixed 30 seconds. The number of requests depends on:
- Server response speed
- Network latency
- File download speed
- The 1-2 second wait time between requests per user

**For consistent comparisons:**
- Run the benchmark multiple times and average the results
- Compare runs with similar server load conditions
- The comparison script (`compare_benchmark_results.py`) helps track trends over time
- Focus on requests/sec and latency percentiles rather than total request count

### Locust Not Installed

```
locust: command not found
```

**Solution**: Install via Poetry:
```bash
poetry add locust --group dev
```

## Next Steps

To add more endpoints to benchmark:

1. Edit `locustfile_downloads.py`
2. Add new `@task` methods to `DownloadTaskSet`
3. Run the benchmark again

Example:
```python
@task(1)
def download_20mb(self) -> None:
    """Download 20MB test file."""
    self.client.get(
        "/downloads/test20.txt",
        params={"usha": "..."},
        name="20MB Download",
    )
```
