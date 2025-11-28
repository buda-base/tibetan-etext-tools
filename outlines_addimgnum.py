import csv
import os
from collections import defaultdict
from natsort import natsorted

def calculate_text_pages(row):
    """Calculate total text pages for a PDF file, accounting for blank spaces"""
    pdf_pages = int(row[1])
    blank_spaces = int(row[2])
    pages_per_pdf = int(row[3])
    return pdf_pages - blank_spaces

def get_volume_number(subfolder):
    """Extract volume number from subfolder name"""
    return int(subfolder[-3:])-691

def get_img_num(volume_data, pg_num):
    for i, pg_range in enumerate(volume_data['pdf_pg_ranges']):
        if pg_num < pg_range[0]:
            continue
        img_range = volume_data['pdf_img_ranges'][i+1] # +1 because the first pdf (the karchak) is not in pdf_pg_ranges
        img_in_pdf = pg_num - pg_range[0]
        return img_range[0] + img_in_pdf
    return -1

def process_files(blank_pages_file, output_file):

    # Process data by volume
    volumes_data = defaultdict(dict)

    # Read input files
    with open(blank_pages_file, 'r') as f:
        reader = csv.reader(f)
    
        # Group blank_pages data by volume
        for row in reader:
            # we suppose that rows are in order in the file
            subfolder = row[0].split('/')[0]
            filename = row[0].split('/')[1]
            if subfolder not in volumes_data:
                volumes_data[subfolder]['pdfs'] = []
                volumes_data[subfolder]['pdf_img_ranges'] = []
                volumes_data[subfolder]['pdf_pg_ranges'] = []
                volumes_data[subfolder]['total_imgs'] = 3
                volumes_data[subfolder]['last_pgnum'] = 0

            volumes_data[subfolder]['pdfs'].append(row[0])
            
            nb_pages_pdf = calculate_text_pages(row)
            volumes_data[subfolder]['pdf_img_ranges'].append([volumes_data[subfolder]['total_imgs']+1, volumes_data[subfolder]['total_imgs']+nb_pages_pdf])
            volumes_data[subfolder]['total_imgs'] += nb_pages_pdf
            if not row[0].endswith('-0.pdf'):  # Exclude table of contents
                volumes_data[subfolder]['pdf_pg_ranges'].append([volumes_data[subfolder]['last_pgnum']+1, volumes_data[subfolder]['last_pgnum']+nb_pages_pdf])
                volumes_data[subfolder]['last_pgnum'] += nb_pages_pdf

    output_rows = []
    with open(output_file, 'r') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames + ['volnum_start', 'volnum_end', 'imgnum_start', 'imgnum_end']
        output_rows = list(reader)
    
    # Process each row
    result_rows = []
    
    # Calculate image numbers
    for subfolder in volumes_data:
        subfolder_rows = [row for row in output_rows if row['Folder'] == subfolder]
        volnum = get_volume_number(subfolder)
        nb_content_pdfs = len(volumes_data[subfolder]['pdfs']) - 1
        nb_texts = len(subfolder_rows)

        # add karchak at beginning
        karchak_range = volumes_data[subfolder]['pdf_img_ranges'][0]
        result_rows.append({
            "Folder": subfolder,
            "number in outline": 0,
            "Title": "དཀར་ཆག",
            "page number": 0,
            'volnum_start': volnum,
            'volnum_end': volnum,
            'imgnum_start': karchak_range[0],
            'imgnum_end': karchak_range[1]
            })
        
        if nb_content_pdfs == nb_texts:
            for i, img_range in enumerate(volumes_data[subfolder]['pdf_img_ranges'][1:]): # skip karchak
                new_row = subfolder_rows[i].copy()
                new_row['volnum_start'] = volnum
                new_row['volnum_end'] = volnum
                new_row['imgnum_start'] = img_range[0]
                new_row['imgnum_end'] = img_range[1]
                result_rows.append(new_row)
        else:
            print("complex case for %d %s " % (volnum, subfolder))
            #print(volumes_data[subfolder])
            # Complex case: use page numbers
            for i, row in enumerate(subfolder_rows):
                new_row = row.copy()
                img_start = -1
                try:
                    img_start = get_img_num(volumes_data[subfolder], int(row['page number']))
                except:
                    pass
                new_row = subfolder_rows[i].copy()
                new_row['volnum_start'] = volnum
                new_row['volnum_end'] = volnum
                new_row['imgnum_start'] = img_start
                new_row['imgnum_end'] = volumes_data[subfolder]['total_imgs']
                if i < len(subfolder_rows) -1:
                    imgnum_end = -1
                    try:
                        next_page_num = int(subfolder_rows[i+1]['page number'])
                        imgnum_end = get_img_num(volumes_data[subfolder], next_page_num) - 1
                    except:
                        pass
                    new_row['imgnum_end'] = imgnum_end
                result_rows.append(new_row)
    
    # Write results
    with open('outline_imgnums.csv', 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(result_rows)

if __name__ == "__main__":
    process_files('blank_pages.csv', 'output.csv')
