import os

base_dir = r"c:\Users\ashis\OneDrive\Documents\Important stuff of AG\Code2Create\ps2"

replacements = {
    # Interfaces and Scripts
    "src/interfaces/api.py": [("from main import run_simulation", "from src.interfaces.cli import run_simulation")],
    "src/interfaces/dashboard.py": [("from main import run_simulation", "from src.interfaces.cli import run_simulation")],
    "scripts/pareto_search.py": [("from main import run_simulation", "from src.interfaces.cli import run_simulation")],
    
    # Tests
    "tests/verify_phases.py": [
        ("from src.models import", "from src.models.datatypes import"),
        ("from src.graph import", "from src.utils.graph import"),
        ("from src.queue import", "from src.state.queue import"),
        ("from src.registry import", "from src.state.registry import"),
        ("from src.scorer import", "from src.core.scorer import"),
        ("from src.engine import", "from src.core.engine import"),
        ("from src.metrics import", "from src.metrics.collector import"),
    ],
    "tests/test_tiebreak.py": [
        ("from src.models import", "from src.models.datatypes import"),
        ("from src.scorer import", "from src.core.scorer import"),
        ("from src.graph import", "from src.utils.graph import"),
    ],
    
    # Core Engine
    "src/core/engine.py": [
        ("from .models import", "from src.models.datatypes import"),
        ("from .queue import", "from src.state.queue import"),
        ("from .registry import", "from src.state.registry import"),
        ("from .scorer import", "from src.core.scorer import"),
        ("from .metrics import", "from src.metrics.collector import"),
        ("from .graph import", "from src.utils.graph import"),
        ("from .adaptive import", "from src.core.adaptive import"),
        ("from .hungarian import", "from src.core.hungarian import"),
    ],
    "src/core/hungarian.py": [
        ("from .models import", "from src.models.datatypes import"),
        ("from .graph import", "from src.utils.graph import"),
        ("from .delay_buffer import", "from src.utils.delay_buffer import"),
    ],
    "src/core/scorer.py": [
        ("from .models import", "from src.models.datatypes import"),
        ("from .graph import", "from src.utils.graph import"),
        ("from .delay_buffer import", "from src.utils.delay_buffer import"),
    ],
    
    # State
    "src/state/queue.py": [
        ("from .models import", "from src.models.datatypes import"),
    ],
    "src/state/registry.py": [
        ("from .models import", "from src.models.datatypes import"),
    ],
    
    # Metrics
    "src/metrics/collector.py": [
        ("from .models import", "from src.models.datatypes import"),
    ],
    
    # Utils
    "src/utils/delay_buffer.py": [
        ("from .graph import", "from src.utils.graph import"),
    ]
}

for rel_path, reps in replacements.items():
    file_path = os.path.join(base_dir, rel_path)
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        for old, new in reps:
            content = content.replace(old, new)
            
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Updated {rel_path}")
    else:
        print(f"File not found: {rel_path}")
