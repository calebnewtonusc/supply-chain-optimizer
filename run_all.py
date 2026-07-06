"""
End-to-end pipeline runner (Python equivalent of run.sh).

Runs the six stages in order using the current interpreter:

    1. generate synthetic data
    2. load into SQLite
    3. analytics + charts
    4. supplier risk scorecard + savings model
    5. part-family risk segmentation
    6. executive dashboard
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

STAGES = [
    ("Generating synthetic procurement data", ["data/generate_data.py"]),
    ("Loading data into SQLite", ["src/load_db.py"]),
    ("Running SQL analytics and rendering charts", ["src/analyze.py"]),
    ("Computing supplier risk scorecard and savings model", ["src/supplier_scorecard.py"]),
    ("Building part-family risk segmentation", ["src/part_family.py"]),
    ("Rendering executive dashboard", ["src/build_dashboard.py"]),
]


def main():
    total = len(STAGES)
    for i, (label, args) in enumerate(STAGES, start=1):
        print(f"==> {i}/{total} {label}")
        subprocess.run([sys.executable, *args], cwd=ROOT, check=True)
        print()
    print("Pipeline complete. See output/ for the scorecard, savings breakdown,")
    print("part-family segmentation, charts, and dashboard.html.")


if __name__ == "__main__":
    main()
