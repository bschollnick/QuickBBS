#!/usr/bin/env bash
#
# run_hey.sh - Benchmark QuickBBS download endpoints with `hey` and emit a
#              runtime log suitable for comparing different QuickBBS versions.
#
# Each run (test1.bin, test2.bin, ...) is clearly delimited and its summary
# metrics (Total Time, Slowest, Fastest, Average, Requests/sec, Total Data,
# Size/request) are extracted and printed in a labelled, aligned block.
#
# Usage:
#   ./run_hey.sh                 # run all configured tests, log to benchmarks/logs/
#   LABEL=v4.1 ./run_hey.sh      # tag the log with a version label
#   N=200 C=100 ./run_hey.sh     # override request count / concurrency
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
N="${N:-200}"                       # total number of requests per run
C="${C:-100}"                       # concurrency
LABEL="${LABEL:-$(git rev-parse --short HEAD 2>/dev/null || echo unknown)}"
BASE="https://nerv.local:8888/download_file"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${LOG_DIR:-${SCRIPT_DIR}/logs}"
mkdir -p "${LOG_DIR}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="${LOG_DIR}/hey-${LABEL}-${TIMESTAMP}.log"

# Each entry: "name|url"
TESTS=(
  "test1.bin|${BASE}/test1.txt?usha=43b1c4c782707602f7fc7b14d744df100ae21d52b66424472123b4fadd8fa50c"
  "test2.bin|${BASE}/test2.txt?usha=e1ead9ecfa2b3386e5eae4694f74666adda8d1ef83bf08aebdf36d3e3a58b4c0"
  "test5.bin|${BASE}/test5.txt?usha=6f7ad3a8ed794ac92a07be27a33547893eb81c81257e1d026f853f77e23dabc6"
  "test10.bin|${BASE}/test10.txt?usha=fc393e16228bc3266e4c0457816d4ffa62f23b0b259810f6aed043e969cf0103"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# log: write to both stdout and the log file.
log() { printf '%s\n' "$*" | tee -a "${LOG_FILE}"; }

# extract: pull the value following a hey summary label from captured output.
#   $1 = raw hey output, $2 = label (e.g. "Slowest:")
extract() {
  awk -v key="$2" '$1 == key { print $2; exit }' <<<"$1"
}

# grab: pull a labelled field from the "Total data" / "Size/request" lines.
#   hey indents these lines and uses a tab after the colon, e.g.
#     "  Total data:\t20971520 bytes". Match the label after any leading
#     whitespace and return everything following the first colon.
grab_data() {
  awk -v key="$2" '
    { line = $0; sub(/^[[:space:]]+/, "", line) }
    index(line, key) == 1 {
      sub(/^[^:]*:[[:space:]]*/, "", line); print line; exit
    }' <<<"$1"
}

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
log "==============================================================="
log " QuickBBS Benchmark Log"
log " Label       : ${LABEL}"
log " Timestamp   : $(date '+%Y-%m-%d %H:%M:%S %Z')"
log " Requests    : ${N}   Concurrency: ${C}"
log " Host        : $(hostname)"
log "==============================================================="
log ""

# ---------------------------------------------------------------------------
# Run each test
# ---------------------------------------------------------------------------
for entry in "${TESTS[@]}"; do
  name="${entry%%|*}"
  url="${entry#*|}"

  log "---------------------------------------------------------------"
  log " RUN: ${name}"
  log " URL: ${url}"
  log "---------------------------------------------------------------"

  # Capture raw hey output (fall back gracefully if hey exits non-zero).
  raw="$(hey -n "${N}" -c "${C}" "${url}" 2>&1)" || true

  total=$(extract "$raw" "Total:")
  slowest=$(extract "$raw" "Slowest:")
  fastest=$(extract "$raw" "Fastest:")
  average=$(extract "$raw" "Average:")
  rps=$(extract "$raw" "Requests/sec:")
  total_data=$(grab_data "$raw" "Total data:")
  size_req=$(grab_data "$raw" "Size/request:")

  log "  Summary [${name}]"
  log "    Total Time      : ${total:-n/a} s"
  log "    Slowest         : ${slowest:-n/a} s"
  log "    Fastest         : ${fastest:-n/a} s"
  log "    Average         : ${average:-n/a} s"
  log "    Requests/sec    : ${rps:-n/a}"
  log "    Total Data      : ${total_data:-n/a}"
  log "    Size/request    : ${size_req:-n/a}"
  log ""
done

log "==============================================================="
log " Benchmark complete. Log written to:"
log "   ${LOG_FILE}"
log "==============================================================="
