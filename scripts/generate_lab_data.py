"""Generate randomized, relational clinical laboratory test data.

Usage: python scripts/generate_lab_data.py [--records 150] [--seed 123]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path


SPECIALTIES = {
    "Clinical Chemistry": [
        ("GLU", "Glucose", "mg/dL", "2345-7", 70, 180, "mg/dL"),
        ("CREAT", "Creatinine", "mg/dL", "2160-0", 0.5, 3.5, "mg/dL"),
        ("ALT", "Alanine aminotransferase", "U/L", "1742-6", 5, 220, "U/L"),
        ("TSH", "Thyroid stimulating hormone", "mIU/L", "3016-3", 0.1, 15, "mIU/L"),
    ],
    "Hematology": [
        ("HGB", "Hemoglobin", "g/dL", "718-7", 7, 19, "g/dL"),
        ("WBC", "Leukocytes", "10*3/uL", "6690-2", 2, 28, "10*3/uL"),
        ("PLT", "Platelets", "10*3/uL", "777-3", 40, 600, "10*3/uL"),
        ("HCT", "Hematocrit", "%", "4544-3", 20, 62, "%"),
    ],
    "Molecular Diagnostics": [
        ("SARS2", "SARS-CoV-2 RNA", "copies/mL", "94500-6", 0, 1000000, "{copies}/mL"),
        ("HIVVL", "HIV-1 viral load", "copies/mL", "70241-5", 0, 500000, "{copies}/mL"),
        ("HBVDNA", "Hepatitis B DNA", "IU/mL", "29615-7", 0, 1000000, "[IU]/mL"),
    ],
    "Urinalysis": [
        ("UCREAT", "Urine creatinine", "mg/dL", "2161-8", 10, 450, "mg/dL"),
        ("UPROT", "Urine protein", "mg/dL", "2888-6", 0, 500, "mg/dL"),
        ("USG", "Urine specific gravity", "", "5811-5", 1.001, 1.040, "{SG}"),
        ("UPH", "Urine pH", "pH", "5803-2", 4.5, 9.5, "pH"),
    ],
    "Toxicology": [
        ("ETOH", "Ethanol", "mg/dL", "5643-2", 0, 350, "mg/dL"),
        ("THC", "Cannabinoid screen", "ng/mL", "18282-4", 0, 250, "ng/mL"),
        ("OPI", "Opiates screen", "ng/mL", "19295-5", 0, 2000, "ng/mL"),
    ],
}

STYLES = ("camel", "pascal", "snake", "abbr")
FIRST = ("Aarav", "Mia", "Noah", "Priya", "Liam", "Anika", "Ethan", "Sara", "Dev", "Olivia")
LAST = ("Sharma", "Patel", "Khan", "Chen", "Singh", "Garcia", "Brown", "Nair", "Wilson", "Das")
CLINICIANS = ("Dr. R. Mehta", "Dr. A. Wilson", "Dr. S. Chen", "Dr. P. Nair", "Dr. K. Khan")
ANALYZERS = ("CHEM-ADVIA-01", "HEMA-SYSMEX-02", "PCR-BIOFIRE-03", "UA-ATELLICA-04", "TOX-ABBOTT-05")


def key_name(key: str, style: str) -> str:
    words = key.split("_")
    if style == "snake": return key
    if style == "pascal": return "".join(w.title() for w in words)
    if style == "camel": return words[0] + "".join(w.title() for w in words[1:])
    return {"patient_id": "PID", "order_id": "ORD_NO", "item_id": "ITEM_GUID", "barcode_id": "BARCODE", "task_id": "TASK", "result_id": "RESULT"}.get(key, key.upper())


def timestamp(dt: datetime, rng: random.Random, edge: bool = False) -> str:
    if edge or rng.random() < 0.25:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    return dt.isoformat(timespec="seconds") if rng.random() < 0.5 else dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_csv(path: Path, rows: list[dict], rng: random.Random) -> None:
    keys = list(rows[0])
    style = rng.choice(STYLES)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=[key_name(k, style) for k in keys])
        writer.writeheader()
        for row in rows:
            writer.writerow({key_name(k, style): v for k, v in row.items()})


def rand_id(prefix: str, n: int, rng: random.Random) -> str:
    return prefix + "-" + str(n).zfill(5) + "-" + "".join(rng.choices(string.ascii_uppercase + string.digits, k=5))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=150)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    if args.records < 120:
        raise SystemExit("--records must be at least 120")
    rng = random.Random(args.seed)
    specialty = rng.choice(tuple(SPECIALTIES))
    tests = SPECIALTIES[specialty]
    out = Path(__file__).resolve().parents[1] / "new_data"
    out.mkdir(parents=True, exist_ok=True)
    base = datetime(2026, 1, 1, 8, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    patients, orders, items, barcodes, tasks, results = [], [], [], [], [], []
    hl7_messages, observations = [], []
    for i in range(1, args.records + 1):
        pid, oid = f"P{i:06d}", f"ORD-{i:08d}"
        iid, bid, tid, rid = rand_id("ITEM", i, rng), f"BC{i:09d}", rand_id("TASK", i, rng), rand_id("RES", i, rng)
        dt = base + timedelta(hours=i * 3, minutes=rng.randint(0, 59))
        first, last = rng.choice(FIRST), rng.choice(LAST)
        gender = rng.choice(("male", "female", "other", "unknown"))
        dob = datetime(1950, 1, 1) + timedelta(days=rng.randint(0, 25000))
        patients.append({"patient_id": pid, "full_name": f"{first} {last}", "gender": gender, "dob": dob.date().isoformat(), "phone": None if rng.random() < .07 else f"+91-98{rng.randint(10000000,99999999)}"})
        orders.append({"order_id": oid, "patient_id": pid, "ordering_clinician": rng.choice(CLINICIANS), "order_datetime": timestamp(dt, rng), "status": rng.choice(("FINAL", "IN_PROGRESS", "CANCELLED", "RELEASED"))})
        code, desc, unit, loinc, low, high, ucum = rng.choice(tests)
        items.append({"item_id": iid, "order_id": oid, "test_code": code if rng.random() > .06 else "CUSTOM-" + str(rng.randint(100,999)), "description": desc, "sample_type": rng.choice(("Serum", "Plasma", "Whole Blood", "Urine", "Swab"))})
        barcodes.append({"barcode_id": bid, "order_id": oid, "patient_id": pid, "collection_timestamp": timestamp(dt + timedelta(minutes=15), rng, rng.random() < .08), "rack_position": f"R{rng.randint(1,9)}-{rng.randint(1,48):02d}"})
        tasks.append({"task_id": tid, "barcode_id": bid, "analyzer_id": rng.choice(ANALYZERS), "assay_protocol": f"{specialty[:3].upper()}-{code}", "processing_status": rng.choice(("COMPLETED", "QUEUED", "REVIEW"))})
        value = round(rng.uniform(low, high), 3)
        flag = rng.choice(("NORMAL", "HIGH", "LOW", "ABNORMAL", "CRITICAL", "PANIC")) if rng.random() < .09 else "NORMAL"
        text_value = None if rng.random() < .08 else ("Detected" if specialty == "Molecular Diagnostics" and value > high * .5 else "")
        results.append({"result_id": rid, "task_id": tid, "parameter_code": code, "numeric_value": value, "text_value": text_value, "units": unit, "abnormality_flag": flag})

        msg_time = dt.strftime("%Y%m%d%H%M%S%z")
        msg_time = msg_time[:-2] if rng.random() < .05 else msg_time
        obx_value = text_value or str(value)
        hl7_messages.append("\r".join([
            f"MSH|^~\\&|SYNAPSE_LAB|LAB|EHR|HOSPITAL|{msg_time}||ORU^R01|MSG{i:08d}|P|2.5.1",
            f"PID|1||{pid}^^^SYNAPSE||{last}^{first}||{dob.strftime('%Y%m%d')}|{gender[0].upper()}|||",
            f"ORC|RE|{oid}|||||^^^{dt.strftime('%Y%m%d%H%M%S')}",
            f"OBR|1|{oid}|{iid}|{loinc}^{desc}^LN|||{dt.strftime('%Y%m%d%H%M%S')}",
            f"OBX|1|NM|{loinc}^{desc}^LN||{obx_value}|{unit}|{low}-{high}||||{flag}|{dt.strftime('%Y%m%d%H%M%S')}"
        ]))
        observations.append({"resourceType": "Observation", "id": rid, "status": "final" if flag == "NORMAL" else "amended", "code": {"coding": [{"system": "http://loinc.org", "code": loinc, "display": desc}]}, "subject": {"reference": f"Patient/{pid}"}, "effectiveDateTime": dt.isoformat(), "valueQuantity": {"value": value, "unit": unit, "system": "http://unitsofmeasure.org", "code": ucum}, "interpretation": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation", "code": "N" if flag == "NORMAL" else flag}]}]})

    write_csv(out / "lis_patients.csv", patients, rng)
    write_csv(out / "lis_orders.csv", orders, rng)
    write_csv(out / "lis_order_items.csv", items, rng)
    write_csv(out / "mw_barcodes.csv", barcodes, rng)
    write_csv(out / "mw_worklist.csv", tasks, rng)
    write_csv(out / "mw_results.csv", results, rng)
    (out / "hl7_v2_oru_r01.hl7").write_text("\n".join(hl7_messages) + "\n", encoding="utf-8")
    bundle = {"resourceType": "Bundle", "id": "synapse-lab-bundle", "type": "collection", "timestamp": datetime.now(timezone.utc).isoformat(), "entry": [{"fullUrl": f"urn:uuid:{o['id']}", "resource": o} for o in observations]}
    (out / "fhir_observations.json").write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    print(f"Generated {args.records} linked records for specialty: {specialty}")
    print(f"Output: {out}")


if __name__ == "__main__":
    main()
