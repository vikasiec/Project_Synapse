You are tasked with implementing "Project Synapse", an end-to-end, enterprise-grade, multi-protocol clinical laboratory data engine built in Python. 

### Architecture & Requirements Overview:

1. Target Directory & Output Structure:
   - Create a module package named `synapse/` with submodules for `ingestion`, `decoders`, `normalization`, `models`, and `egress`.
   - All generated output datasets, logs, and sample exports must be saved into `./new_data/`.

2. Supported Input Protocols & Formats:
   Implement parsing decoders for the following 6 clinical laboratory formats:
   - ASTM E1394 / E1381 Pipe-Delimited text (e.g., Roche Cobas 8000).
   - HL7 v2.5.1 / v2.x ORU^R01 Pipe-and-Hat Delimited text (e.g., Siemens Atellica).
   - FHIR R4 JSON Resource Bundles (DiagnosticReport & Observation resources).
   - Sysmex IPU CSV Tabular File Formats (Hematology CBC + Diff).
   - Vendor REST JSON Streams (e.g., Abbott Alinity ci-series).
   - RS-232 Serial Framing Streams using [STX] / [ETX] delimiters (e.g., Beckman Coulter AU5800).

3. Schema Drift & Column Mapping Layer:
   - Implement a flexible `AliasMapper` class that dynamically maps heterogeneous field names across LIS (`PatientID`), Middleware (`patient_ref`), and Instrument outputs (`PtID`, `PID-3`, `subject.reference`) to a unified Canonical Patient & Observation Model.

4. Clinical Normalization Engine:
   - Map local assay codes (e.g., `GLUC3`, `ALIN-GLU`, `4001`) to standard LOINC codes (e.g., `2345-7` Glucose).
   - Normalize numeric values and evaluate values against reference ranges to output standardized flags: `NORMAL`, `HIGH`, `LOW`, `CRITICAL`, `PANIC`.

5. Egress & Serialization Layer:
   - Provide converters to transform any ingested payload into:
     a) Canonical CSV relational tables (`lis_patients.csv`, `lis_orders.csv`, `mw_results.csv`).
     b) Standard HL7 v2.5.1 ORU^R01 pipe-delimited text.
     c) Valid FHIR R4 JSON Bundle containing Observation resources.

6. Runnable CLI & Demonstration Script:
   - Include a main entry-point script (`main.py`) that executes a end-to-end data processing run:
     1) Ingests raw sample files across all 6 protocols.
     2) Passes payloads through decoders, schema drift mapper, and clinical normalization.
     3) Writes the normalized outputs (CSV, HL7, and FHIR) directly into the `./new_data/` folder.

Please write clean, modular, production-grade Python code complete with type hints, docstrings, and robust error handling for unparsed or malformed records.