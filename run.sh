#!/usr/bin/env bash
#
# End-to-end pipeline runner.
#
#   1. generate synthetic procurement data (CSVs)
#   2. load it into a SQLite database
#   3. run SQL analytics and render charts
#   4. compute the supplier risk scorecard and savings model
#   5. build the part-family risk segmentation
#   6. render the executive dashboard
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

echo "==> 1/6 Generating synthetic procurement data"
"$PY" data/generate_data.py

echo
echo "==> 2/6 Loading data into SQLite"
"$PY" src/load_db.py

echo
echo "==> 3/6 Running SQL analytics and rendering charts"
"$PY" src/analyze.py

echo
echo "==> 4/6 Computing supplier risk scorecard and savings model"
"$PY" src/supplier_scorecard.py

echo
echo "==> 5/6 Building part-family risk segmentation"
"$PY" src/part_family.py

echo
echo "==> 6/6 Rendering executive dashboard"
"$PY" src/build_dashboard.py

echo
echo "Pipeline complete. See output/ for the scorecard, savings breakdown,"
echo "part-family segmentation, charts, and dashboard.html."
