import sys
import os
import importlib.util
from pathlib import Path

def check_installation():
    print(f"Python executable: {sys.executable}")
    
    # Check if package is importable
    try:
        import pytiblegenc
        print(f"pytiblegenc location: {os.path.dirname(pytiblegenc.__file__)}")
    except ImportError:
        print("Error: pytiblegenc not installed or not found in python path.")
        return

    # Check for the new function (confirms code is up to date)
    try:
        from pytiblegenc.font_utils import build_glyph_lookup_tables
        print("SUCCESS: build_glyph_lookup_tables function found (code is up to date).")
    except ImportError:
        print("FAILURE: build_glyph_lookup_tables function NOT found. You are running an older version.")
        return

    # Check for the database file (confirms data is present)
    try:
        from pytiblegenc.font_utils import get_glyph_db_path
        db_path = get_glyph_db_path()
        print(f"Glyph DB path: {db_path}")
        if os.path.exists(db_path):
            print(f"SUCCESS: glyph_db.csv found (size: {os.path.getsize(db_path)} bytes).")
        else:
            print("FAILURE: glyph_db.csv NOT found at the expected location.")
    except ImportError:
        print("FAILURE: Could not import get_glyph_db_path.")

if __name__ == "__main__":
    check_installation()