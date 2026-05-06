import sys
import logging
from streamlit.web import cli as stcli

if __name__ == "__main__":
    try:
        sys.argv = ["streamlit", "run", "src/interfaces/dashboard.py"]
        sys.exit(stcli.main())
    except Exception as e:
        logging.error(f"Failed to start dashboard: {e}")
        sys.exit(1)
