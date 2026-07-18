"""Ensure BlogAgent runs from its own project virtual environment."""
import os
import subprocess
import sys
import venv


PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(PROJECT_DIR, ".venv")
VENV_PYTHON = os.path.join(VENV_DIR, "bin", "python")
REQUIREMENTS_PATH = os.path.join(PROJECT_DIR, "requirements.txt")


def ensure_project_runtime(script_path: str):
    """Create the local venv if needed, install dependencies, then re-run here."""
    if os.path.abspath(sys.executable) == os.path.abspath(VENV_PYTHON):
        return

    if not os.path.exists(VENV_PYTHON):
        print("Creating BlogAgent's local Python environment...")
        venv.EnvBuilder(with_pip=True).create(VENV_DIR)

    dependency_check = subprocess.run(
        [VENV_PYTHON, "-c", "import requests"], capture_output=True, check=False,
    )
    if dependency_check.returncode != 0:
        print("Installing BlogAgent's required packages into .venv...")
        subprocess.run([VENV_PYTHON, "-m", "pip", "install", "-r", REQUIREMENTS_PATH], check=True)

    os.execv(VENV_PYTHON, [VENV_PYTHON, os.path.abspath(script_path), *sys.argv[1:]])
