"""
Main entry point — run the Streamlit dashboard.
Usage: streamlit run main.py
Or:    streamlit run dashboard.py
"""

import subprocess
import sys


def main():
    subprocess.run([sys.executable, "-m", "streamlit", "run", "dashboard.py", "--server.headless=true"])


if __name__ == "__main__":
    main()
