import os
import shutil
import sys


def remove_pdf_folders(root_dir):
    """Recursively remove all folders named 'PDF' under root_dir."""
    removed = []
    errors = []

    for dirpath, dirnames, _ in os.walk(root_dir, topdown=True):
        # Find 'PDF' folders at this level (case-sensitive)
        pdf_dirs = [d for d in dirnames if d == "PDF"]

        for pdf_dir in pdf_dirs:
            full_path = os.path.join(dirpath, pdf_dir)
            try:
                shutil.rmtree(full_path)
                removed.append(full_path)
                print(f"Removed: {full_path}")
            except Exception as e:
                errors.append((full_path, str(e)))
                print(f"Error removing {full_path}: {e}")

        # Don't descend into 'PDF' folders (they're already deleted)
        dirnames[:] = [d for d in dirnames if d != "PDF"]

    print(f"\nDone. Removed {len(removed)} folder(s).")
    if errors:
        print(f"Failed to remove {len(errors)} folder(s):")
        for path, err in errors:
            print(f"  {path}: {err}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python remove_pdf_folders.py <root_folder>")
        sys.exit(1)

    root = sys.argv[1]

    if not os.path.isdir(root):
        print(f"Error: '{root}' is not a valid directory.")
        sys.exit(1)

    print(f"Scanning: {root}\n")
    remove_pdf_folders(root)
