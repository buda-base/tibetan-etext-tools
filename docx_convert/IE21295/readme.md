# Files are stored in wrong folder (not structured properly)
In toprocess all the files that need to be converted are stored in same folder structure as source folder and folder with IE_ID-VE_ID are empty
WHen converting the file take input structure as /Users/tenzinmonlam/Documents/dharmaduta/file_convert_4/IE21295/toprocess/1v-30v/{number}/*.docx
and 
for Output structure:
    Archive (flat): {IE_ID}_output/archive/{VE_ID}/UT{suffix}_{FILE_NUM}.xml
    Sources (nested): {IE_ID}_output/sources/{IE_ID-VE_ID}/*.docx