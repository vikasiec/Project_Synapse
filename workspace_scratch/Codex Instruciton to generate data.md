Write and execute a Python script to generate a set of randomized, realistic clinical laboratory datasets for testing a data ingestion engine. 
### Requirements & Specifications:

1. Target Directory:
   - Ensure the directory "./new_data_"Iterator" is created automatically if it doesn't exist.Iterator is a number incremented for every iteration. All below files will go in there.

2. Dynamic Scenario Variation (Every run should generate varied lab contexts):
   - Choose randomly among different Clinical Lab Specialties for each run (e.g., Clinical Chemistry, Hematology, Molecular Diagnostics, Urinalysis, or Toxicology).
   - Randomly vary field naming conventions across layers (e.g., camelCase, PascalCase, snake_case, or shortened abbreviations) while maintaining relational logical keys across systems.
   - Inject realistic edge cases across a small percentage (~5-10%) of records:
     - Null/missing optional fields.
     - Critical diagnostic flags ('CRITICAL', 'PANIC', 'HIGH', 'LOW', 'ABNORMAL').
     - Unmapped/Custom parameters (e.g., novel assay codes).
     - Slight timestamp variations (e.g., ISO8601 with/without offset, 'YYYY-MM-DD HH:MM:SS').

3. Minimum File Requirements (At least 120 records per table/file):

   a) LIS Layer (CSV Files):
      - `lis_patients.csv`: Demographic master list (Patient IDs, Full Names, Gender, DOB, Phone/Contact).
      - `lis_orders.csv`: Master laboratory orders (Order Tracking Numbers, Patient Foreign Key, Ordering Clinician, Order Datetime, Status).
      - `lis_order_items.csv`: Test line items (Item GUID, Order Tracking FK, Test/Assay Code, Description, Sample Type).
	  

   b) Middleware Layer (CSV Files):
      - `mw_barcodes.csv`: Specimen tracking (Barcode ID, LIS Order FK, Patient FK, Collection Timestamp, Rack/Position ID).
      - `mw_worklist.csv`: Instrument job queue (Task ID, Barcode FK, Analyzer Device ID, Assay Protocol, Processing Status).
      - `mw_results.csv`: Raw analyzer metrics (Result ID, Task FK, Parameter Code, Numeric Value, Text Value, Units, Abnormality Flag).

   c) Messaging & Interoperability Layer:
      - `hl7_v2_oru_r01.hl7` (or `.txt`): At least 120 standard HL7 v2.5.1 ORU^R01 (Unsolicited Observation Result) pipe-delimited messages using MSH, PID, ORC, OBR, and OBX segments.
      - `fhir_observations.json`: A single valid FHIR R4 Bundle (type: 'collection') containing at least 120 `Observation` resources mapped with LOINC codes, UCUM units, patient references, and status codes.

4. Execution:
   - Make the script self-contained and run it immediately using Python so that the directory "new_data/" is populated with ready-to-use synthetic files.