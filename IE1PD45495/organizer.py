import os
import shutil
from pathlib import Path

def organize_tibetan_rtfs():
    # 1. Configuration of paths
    source_base = Path("/Users/tenzinmonlam/Documents/dharmaduta/file_convert_1/taranatha-gsung-qbum/sources")
    
    # Define the target structure hierarchy
    root_folder_name = "IE1PD45495"
    collection_name = "taranatha-gsung-qbum"
    
    # Current working directory will be the base for the new structure
    target_base = Path.cwd() / root_folder_name / "sources"

    print(f"🚀 Starting organization from: {source_base}")
    print(f"📂 Target base: {target_base}")

    if not source_base.exists():
        print(f"❌ Error: Source path {source_base} does not exist.")
        return

    # 2. Iterate through volume folders in the source
    # Expecting folders like 'volume_001', 'volume_002', etc.
    count = 0
    volume_dirs = sorted([d for d in source_base.iterdir() if d.is_dir() and d.name.startswith('volume_')])
    
    if not volume_dirs:
        print(f"❌ No volume folders found in {source_base}")
        return
    
    print(f"📚 Found {len(volume_dirs)} volume folders\n")
    
    for volume_dir in volume_dirs:
        # Extract volume number from 'volume_001' -> '001'
        volume_num = volume_dir.name.split('_')[1]
        
        # Create project code for this volume: VE1PD45495_001, VE1PD45495_002, etc.
        project_code = f"VE1PD45495_{volume_num}"
        
        # Create the target path: IE1PD45495/sources/VE1PD45495_001/taranatha-gsung-qbum/volume_001
        target_vol_path = target_base / project_code / collection_name / volume_dir.name
        target_vol_path.mkdir(parents=True, exist_ok=True)
        
        # 3. Copy RTF and DOC files
        rtf_files = list(volume_dir.glob("*.rtf"))
        doc_files = list(volume_dir.glob("*.doc"))
        all_files = rtf_files + doc_files
        
        if all_files:
            print(f"  📖 {project_code}: copying {len(rtf_files)} RTF and {len(doc_files)} DOC files from {volume_dir.name}...")
            for file in all_files:
                try:
                    shutil.copy2(file, target_vol_path / file.name)
                    count += 1
                except Exception as e:
                    print(f"    ⚠️ Failed to copy {file.name}: {e}")
        else:
            print(f"  ⚠️ {project_code}: no RTF or DOC files found in {volume_dir.name}")

    print(f"\n✅ Success!")
    print(f"Total files organized: {count}")
    print(f"Final structure created at: {Path.cwd() / root_folder_name}")

if __name__ == "__main__":
    organize_tibetan_rtfs()