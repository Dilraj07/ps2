import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

if __name__ == "__main__":
    try:
        from src.interfaces.cli import run_cli
        run_cli()
    except Exception as e:
        logging.error(f"Failed to start simulation: {e}")
        sys.exit(1)
