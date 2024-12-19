import os
import csv
import re

def convert_tibetan_to_arabic_numeral(tibetan_num):
    # Tibetan to Arabic numeral mapping
    tibetan_to_arabic = {
        '༠': '0', '༡': '1', '༢': '2', '༣': '3', '༤': '4',
        '༥': '5', '༦': '6', '༧': '7', '༨': '8', '༩': '9'
    }
    
    # Convert each Tibetan digit to Arabic
    arabic_num = ''.join(tibetan_to_arabic.get(digit, digit) for digit in tibetan_num)
    return arabic_num

def process_directory(root_dir, output_csv):
    # Open CSV file for writing
    with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
        # Two different CSV writers for different purposes
        toc_writer = csv.writer(csvfile, delimiter=',')
        
        # Write headers
        toc_writer.writerow(['Folder', 'number in outline', 'Title', 'page number'])

        # Walk through all subdirectories in the root directory
        for subdir in sorted(os.listdir(root_dir)):
            full_subdir_path = os.path.join(root_dir, subdir)
            
            # Check if it's a directory
            if os.path.isdir(full_subdir_path):
                # Find all .txt files, excluding the "-0.txt" file
                pdf_files = [f for f in os.listdir(os.path.join("W3KG218/", subdir)) if f.endswith('.pdf') and not f.endswith('-0.pdf')]
                #txt_files = [f for f in os.listdir(full_subdir_path) if f.endswith('.txt') and not f.endswith('-0.txt')]
                num_files = len(pdf_files)
                
                # Find the table of contents file
                toc_files = [f for f in os.listdir(full_subdir_path) if f.endswith('-0.txt')]
                
                if toc_files:
                    toc_path = os.path.join(full_subdir_path, toc_files[0])
                    
                    # Read and process table of contents
                    with open(toc_path, 'r', encoding='utf-8') as toc_file:
                        toc_lines = toc_file.readlines()
                    
                    # Process and write cleaned table of contents
                    processed_toc_lines = []
                    for line in toc_lines:
                        # Remove lines not starting with Tibetan digit
                        if re.match(r'^[༠-༩]', line.strip()):
                            # Split at "་་"
                            parts = re.split(r'་་+', line.strip())
                            pg_begin = ""
                            if len(parts) == 1:
                                print(line)
                            else:
                                pg_begin = parts[1]
                                pg_begin = re.sub(r'\[\[F\d(\d)\]\]', r'\1', pg_begin)
                                pg_begin = pg_begin.replace("[[F5-]]", "-")
                                pg_begin = convert_tibetan_to_arabic_numeral(pg_begin)
                            
                            # Extract Tibetan number and convert to Arabic
                            tibetan_num = re.match(r'^[༠-༩]+', parts[0]).group(0)
                            arabic_num = convert_tibetan_to_arabic_numeral(tibetan_num)
                            
                            # Remove the Tibetan number from the line 
                            title = parts[0][len(tibetan_num):].replace("[[F5 ]]", "").replace("[[F1)]]", "").replace("[[F1 ]]", "").replace("[[F11(]]", "༼").strip("༽ ")
                            title = re.sub(r"\s+", " ", title)
                            title = title.replace("[[F12#]]", "རྱ")
                            title = title.replace("[[Ededris-vowa,62,ཧཱུྃ or ྃཧཱུ]]", "ཧཱུྃ")
                            title = title.replace("[[Ededris-vowa,116,ཨྠིྀ or ཨྠྀི]]", "ཨྠྀི")
                            title = title.replace("[[F12j]]", "ནྡྲ")
                            title = title.replace("[[F12K]]", "དྷཱུ")
                            
                            
                            processed_toc_lines.append([full_subdir_path, arabic_num, title, pg_begin])
                    
                    # Write processed table of contents
                    toc_writer.writerows(processed_toc_lines)
                    
                    # Warning if number of files doesn't match processed TOC lines
                    if num_files != len(processed_toc_lines):
                        print(f"Warning: Mismatch in {full_subdir_path}")
                        print(f"Number of files: {num_files}")
                        print(f"Number of TOC entries: {len(processed_toc_lines)}")

# Use the function
process_directory('W3KG218-etext/', 'output.csv')