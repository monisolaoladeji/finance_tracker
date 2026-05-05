
import sys
from pathlib import Path

# Add local libs to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.append(str(BASE_DIR / "libs"))

print("Testing imports...")
try:
    from flask import Flask
    print("✓ Flask imported successfully")
except Exception as e:
    print(f"✗ Flask import failed: {e}")

try:
    from flask_login import LoginManager
    print("✓ Flask-Login imported successfully")
except Exception as e:
    print(f"✗ Flask-Login import failed: {e}")

try:
    from werkzeug.security import generate_password_hash
    print("✓ Werkzeug imported successfully")
except Exception as e:
    print(f"✗ Werkzeug import failed: {e}")

print("\nAll tests completed!")
