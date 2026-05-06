import os
import shutil

base_dir = r"c:\Users\ashis\OneDrive\Documents\Important stuff of AG\Code2Create\ps2"

# 1. Create directories
dirs = [
    "src/config", "src/data_access", "src/core", "src/state", 
    "src/models", "src/metrics", "src/utils", "src/interfaces",
    "tests", "scripts", "docs", "data/results"
]

for d in dirs:
    os.makedirs(os.path.join(base_dir, d), exist_ok=True)

# 2. Create __init__.py files
init_dirs = [
    "src", "src/config", "src/data_access", "src/core", "src/state",
    "src/models", "src/metrics", "src/utils", "src/interfaces"
]
for d in init_dirs:
    with open(os.path.join(base_dir, d, "__init__.py"), "w") as f:
        pass

# 3. Move files
moves = [
    ("api.py", "src/interfaces/api.py"),
    ("dashboard.py", "src/interfaces/dashboard.py"),
    ("verify_phases.py", "tests/verify_phases.py"),
    ("test_tiebreak.py", "tests/test_tiebreak.py"),
    ("pareto_search.py", "scripts/pareto_search.py"),
    ("ISSUES.md", "docs/ISSUES.md"),
    
    ("src/models.py", "src/models/datatypes.py"),
    ("src/metrics.py", "src/metrics/collector.py"),
    ("src/engine.py", "src/core/engine.py"),
    ("src/hungarian.py", "src/core/hungarian.py"),
    ("src/adaptive.py", "src/core/adaptive.py"),
    ("src/scorer.py", "src/core/scorer.py"),
    ("src/queue.py", "src/state/queue.py"),
    ("src/registry.py", "src/state/registry.py"),
    ("src/graph.py", "src/utils/graph.py"),
    ("src/delay_buffer.py", "src/utils/delay_buffer.py"),
]

for src, dst in moves:
    src_path = os.path.join(base_dir, src)
    dst_path = os.path.join(base_dir, dst)
    if os.path.exists(src_path):
        shutil.move(src_path, dst_path)
        print(f"Moved {src} -> {dst}")
    else:
        print(f"File not found: {src}")

# Handle output -> data/results
output_dir = os.path.join(base_dir, "output")
data_results_dir = os.path.join(base_dir, "data/results")
if os.path.exists(output_dir):
    for f in os.listdir(output_dir):
        shutil.move(os.path.join(output_dir, f), os.path.join(data_results_dir, f))
    os.rmdir(output_dir)
    print("Moved output contents to data/results")
