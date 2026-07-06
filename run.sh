#!/usr/bin/env bash
#
# End-to-end pipeline runner.
#
#   1. generate synthetic procurement data (CSVs)
#   2. load it into a SQLite database
#   3. run SQL analytics and render charts
#   4. compute the supplier risk scorecard
#
# Usage: ./run.sh   (expects the .venv created in the README setup step)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
else
    PY="python3"
fi

echo "==> 1/4 Generating synthetic procurement data"
"$PY" data/generate_data.py

echo
echo "==> 2/4 Loading data into SQLite"
"$PY" src/load_db.py

echo
echo "==> 3/4 Running SQL analytics and rendering charts"
"$PY" src/analyze.py

echo
echo "==> 4/4 Computing supplier risk scorecard"
"$PY" src/supplier_scorecard.py

echo
echo "Pipeline complete. See output/ for the scorecard CSV and charts."
