# RTF to TEI XML Converter

Python script to convert Tibetan RTF documents into TEI XML format.

## Directory Structure
### Input Path: 
```   
    {IE_ID}/sources/{VE_ID}/{collection_name}/rtfs/{VOL_ID}/*.rtf
```
### Output Path:
For nested: 
```
{IE_ID}_output/archive/{VE_ID}/{collection_name}/xml/volume_{VOL_ID}/UT{suffix}_{index}.xml
```
For direct: 
```
{IE_ID}_output/archive/{VE_ID}/UT{suffix}_{index}.xml
```

### Supported Input Structures

#### Nested Structure (New):

```
IE1PD105893/
└── sources/
    └── VE1PD105893/
        └── collection_name/
            └── rtfs/
                └── volume_001/
                    ├── 01.rtf
                    └── 02.rtf
```

#### Direct Structure:
```
IE1PD105893/
└── sources/
    └── VE1PD105893/
        ├── 01.rtf
        └── 02.rtf
```
#### Legacy Structure:
```
IE1PD105893/
└── toprocess/
    └── IE1PD105893-VE1PD105893/
        ├── 01.rtf
        └── ...
```


### Output Structure
```
IE1PD105893_output/
├── archive/
│   └── VE1PD105893/
│       └── [collection_name]/
│           └── xml/
│               └── volume_001/
│                   ├── UT1PD105893_0001.xml
│                   └── UT1PD105893_0002.xml
└── sources/
    └── VE1PD105893/
        └── [collection_name]/
            └── rtfs/
                └── volume_001/
                    ├── 01.rtf
                    └── ...
```


## Usage
```
python convert.py
```
#### Process a Specific Collection :
```
python convert.py --ie-id IE1PD45495
```
#### Adjust Performance :

Change the number of parallel worker processes (default is CPU count - 1):
```
python convert.py --workers 4
```

## Technical Details

### ID Generation

- VE ID: Extracted from the source folder name.

- UT ID: Generated sequentially based on the file index within the volume.

  - Format: UT{VE_Suffix}_{Index:04d}

  - Example: File 1 in VE3KG253 becomes UT3KG253_0001.



  

   


