# Thumbnail Backend Benchmarks

This directory contains benchmarking tools for comparing thumbnail generation backend performance.

## Overview

The benchmark suite tests:
- **Image backends**: PIL/Pillow vs Core Image (macOS)
- **Video backends**: FFmpeg vs AVFoundation (macOS)
- **PDF backends**: PyMuPDF vs PDFKit (macOS)

## Quick Start

### 1. Prepare Test Files

Place test files in this directory:
- `test.png` - Required for image benchmarks
- `test.mp4` - Optional for video benchmarks
- `test.pdf` - Optional for PDF benchmarks

### 2. Run Benchmarks

```bash
cd thumbnails/benchmarks
python thumbnail_benchmarks.py
```

## Configuration

Edit `thumbnail_benchmarks.py` to adjust:

```python
# Number of iterations per backend
ITERATIONS = 1000

# Test files
TEST_IMAGE = "test.png"
TEST_VIDEO = "test.mp4"
TEST_PDF = "test.pdf"

# Thumbnail sizes
IMAGE_SIZES = {
    "large": (1024, 1024),
    "medium": (740, 740),
    "small": (200, 200)
}

# JPEG quality (1-100)
JPEG_QUALITY = 85

# Save output files (disable for pure speed test)
SAVE_OUTPUT = True
```

## Output

The benchmark provides:
- **Individual iteration times** - Precise timing for each conversion
- **Total execution time** - Overall benchmark duration
- **Statistics**:
  - Average time per iteration
  - Median time per iteration
  - Min/Max times
  - Standard deviation
  - Throughput (images/sec)
- **Comparison** - Speedup factor between backends

### Example Output

```
======================================================================
Thumbnail Generation Backend Benchmarks
======================================================================
Iterations per backend: 1,000
Thumbnail sizes: {'large': (1024, 1024), 'medium': (740, 740), 'small': (200, 200)}
JPEG quality: 85

Backend Availability:
  Core Image:     True
  AVFoundation:   True
  PDFKit:         True

======================================================================
PIL/Pillow Backend
======================================================================
Benchmarking PIL/Pillow...
  Backend:     image
  Test file:   test.png
  Iterations:  1,000

======================================================================
PIL/Pillow Results
======================================================================
Total iterations:     1,000
Total time:           12.345s
Average per iter:     12.3ms
Median per iter:      12.1ms
Min per iter:         10.5ms
Max per iter:         25.8ms
Std deviation:        1.2ms
Throughput:           81.0 images/sec

======================================================================
Core Image Backend (macOS)
======================================================================
Benchmarking Core Image...

======================================================================
Core Image Results
======================================================================
Total iterations:     1,000
Total time:           4.567s
Average per iter:     4.6ms
Median per iter:      4.5ms
Min per iter:         4.2ms
Max per iter:         8.1ms
Std deviation:        0.3ms
Throughput:           219.0 images/sec

======================================================================
Comparison: Core Image vs PIL
======================================================================
Core Image total time:  4.567s
PIL total time:         12.345s
Speedup:                2.70x

Core Image avg/iter:    4.6ms
PIL avg/iter:           12.3ms
Avg speedup:            2.67x
```

## Output Files

When `SAVE_OUTPUT = True`, the benchmark saves:
- First iteration thumbnails (verification)
- Last iteration thumbnails (verification)

Files are named: `{backend}_iter{number}_{size}.jpg`

Examples:
- `image_iter0000_small.jpg`
- `coreimage_iter0999_large.jpg`

## Performance Tips

### For Quick Tests
```python
ITERATIONS = 100
SAVE_OUTPUT = False
```

### For Detailed Analysis
```python
ITERATIONS = 1000
SAVE_OUTPUT = True
```

### For Production Benchmarks
```python
ITERATIONS = 10000
SAVE_OUTPUT = False
```

## Platform-Specific Features

### macOS (Apple Silicon)
- Core Image: GPU-accelerated image processing
- AVFoundation: Hardware video decoding
- PDFKit: Native PDF rendering

### All Platforms
- PIL/Pillow: Cross-platform image processing
- FFmpeg: Cross-platform video processing
- PyMuPDF: Cross-platform PDF processing

## Interpreting Results

### Speedup Factors
- **1.0x - 1.5x**: Marginal improvement
- **1.5x - 2.5x**: Significant improvement
- **2.5x+**: Major improvement (use this backend!)

### Throughput
- **<50 images/sec**: Slow (consider optimization)
- **50-100 images/sec**: Acceptable
- **100-200 images/sec**: Good
- **200+ images/sec**: Excellent

### Standard Deviation
- **Low (<10% of mean)**: Consistent performance
- **High (>20% of mean)**: Variable performance (I/O bottleneck?)

## Troubleshooting

### Import Errors
Ensure you're running from the benchmarks directory:
```bash
cd thumbnails/benchmarks
python thumbnail_benchmarks.py
```

### Missing Test Files
Place `test.png` in the benchmarks directory. The script will skip video/PDF tests if those files are missing.

### Backend Not Available
Some backends are platform-specific:
- Core Image: macOS only
- AVFoundation: macOS only
- PDFKit: macOS only (requires Apple Silicon for best performance)

## Integration with QuickBBS

These benchmarks test the same thumbnail generation code used by QuickBBS. Performance improvements in backends directly translate to faster thumbnail generation in production.

To apply benchmark findings:
1. Identify fastest backend for your platform
2. Update `quickbbs_settings.py` quality settings if needed
3. Monitor production performance with similar workloads
