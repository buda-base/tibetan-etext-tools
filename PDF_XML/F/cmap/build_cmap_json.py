import glob
import json
import re

def build_json_map():
    cid_map = {}
    
    # Matches the hex pairs, e.g., <016C> <0FA20F7C>
    pattern = re.compile(r'<([0-9A-Fa-f]+)>\s+<([0-9A-Fa-f]+)>')

    # Grab all extracted CMap text files in the current directory
    cmap_files = glob.glob("qomolangma_cmap_*.txt")
    
    if not cmap_files:
        print("No CMap text files found in the current directory.")
        return

    for file in cmap_files:
        with open(file, 'r', encoding='utf-8') as f:
            content = f.read()
            
            # Find all mapping pairs in the file
            for match in pattern.finditer(content):
                cid_hex, uni_hex = match.groups()
                
                # Convert the CID from hex to a decimal string (for pytiblegenc matching)
                cid_dec = str(int(cid_hex, 16))
                
                # Convert the Unicode hex to actual characters
                # Chunked by 4 because some are ligatures (e.g., 0F620F920FB1)
                unicode_str = ""
                for i in range(0, len(uni_hex), 4):
                    code_point = int(uni_hex[i:i+4], 16)
                    unicode_str += chr(code_point)
                    
                cid_map[cid_dec] = unicode_str
                
    # Output the final dictionary to JSON
    output_filename = "qomolangma_cid_map.json"
    with open(output_filename, "w", encoding="utf-8") as out:
        json.dump(cid_map, out, ensure_ascii=False, indent=2)
        
    print(f"Success! Generated {output_filename} with {len(cid_map)} mapped CIDs.")

if __name__ == "__main__":
    build_json_map()