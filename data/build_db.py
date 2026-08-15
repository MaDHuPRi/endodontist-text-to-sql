"""
Builds a synthetic SQLite database representing an endodontist practice's
records — as if exported from MS Access via DB Browser for SQLite.

All data below is fabricated for demo purposes only (no real patient data).
"""
import sqlite3
import random
from datetime import datetime, timedelta

DB_PATH = "clinic.db"
random.seed(42)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.executescript("""
DROP TABLE IF EXISTS patients;
DROP TABLE IF EXISTS dentists;
DROP TABLE IF EXISTS appointments;
DROP TABLE IF EXISTS treatments;
DROP TABLE IF EXISTS invoices;

CREATE TABLE dentists (
    dentist_id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    specialty TEXT,
    years_experience INTEGER
);

CREATE TABLE patients (
    patient_id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    date_of_birth TEXT,
    phone TEXT,
    insurance_provider TEXT,
    referred_by TEXT
);

CREATE TABLE appointments (
    appointment_id INTEGER PRIMARY KEY,
    patient_id INTEGER,
    dentist_id INTEGER,
    appointment_date TEXT,
    appointment_type TEXT,
    status TEXT,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    FOREIGN KEY (dentist_id) REFERENCES dentists(dentist_id)
);

CREATE TABLE treatments (
    treatment_id INTEGER PRIMARY KEY,
    appointment_id INTEGER,
    tooth_number INTEGER,
    procedure_name TEXT,
    procedure_code TEXT,
    cost REAL,
    notes TEXT,
    FOREIGN KEY (appointment_id) REFERENCES appointments(appointment_id)
);

CREATE TABLE invoices (
    invoice_id INTEGER PRIMARY KEY,
    patient_id INTEGER,
    appointment_id INTEGER,
    amount_due REAL,
    amount_paid REAL,
    invoice_date TEXT,
    payment_status TEXT,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id),
    FOREIGN KEY (appointment_id) REFERENCES appointments(appointment_id)
);
""")

# --- Dentists ---
dentists = [
    (1, "Dr. Sarah Chen", "Endodontics", 12),
    (2, "Dr. Michael Alvarez", "Endodontics", 8),
    (3, "Dr. Priya Nair", "Endodontics", 15),
]
cur.executemany("INSERT INTO dentists VALUES (?,?,?,?)", dentists)

# --- Patients ---
first_names = ["James","Maria","Robert","Linda","David","Susan","John","Karen",
               "William","Nancy","Thomas","Betty","Charles","Sandra","Daniel",
               "Emily","Michael","Patricia","Ahmed","Fatima","Wei","Sofia"]
last_names = ["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller",
              "Davis","Rodriguez","Martinez","Wilson","Anderson","Thomas","Lee",
              "Walker","Hall","Young","King","Wright","Patel"]
insurers = ["Delta Dental","Cigna","MetLife","Aetna","Guardian","Self-Pay","United Concordia"]
referrers = ["Dr. Kim (General Dentist)","Dr. Osei (General Dentist)","Walk-in",
             "Dr. Rossi (General Dentist)","Online Search","Dr. Kim (General Dentist)"]

patients = []
for i in range(1, 151):
    fn = random.choice(first_names)
    ln = random.choice(last_names)
    dob = datetime(1950 + random.randint(0,65), random.randint(1,12), random.randint(1,28))
    phone = f"({random.randint(200,999)}) {random.randint(200,999)}-{random.randint(1000,9999)}"
    patients.append((i, f"{fn} {ln}", dob.strftime("%Y-%m-%d"), phone,
                      random.choice(insurers), random.choice(referrers)))
cur.executemany("INSERT INTO patients VALUES (?,?,?,?,?,?)", patients)

# --- Appointments ---
appt_types = ["Root Canal - Initial","Root Canal - Follow-up","Emergency Pain Visit",
              "Consultation","Retreatment","Apicoectomy","Post-Op Check"]
statuses = ["Completed","Completed","Completed","No-Show","Cancelled","Scheduled"]

appointments = []
appt_id = 1
end_date = datetime(2026, 8, 15)          # "today" for this demo dataset
start = end_date - timedelta(days=730)     # 2 years of history
total_span_days = (end_date - start).days

for p in patients:
    n_appts = random.randint(3, 8)
    for _ in range(n_appts):
        day_offset = random.randint(0, total_span_days)
        appt_date = start + timedelta(days=day_offset)
        appointments.append((
            appt_id, p[0], random.choice(dentists)[0],
            appt_date.strftime("%Y-%m-%d"),
            random.choice(appt_types),
            random.choice(statuses)
        ))
        appt_id += 1

# --- Guarantee density in the most recent windows (last week / last month) ---
# Random sampling can leave short recent windows thin, and those are the
# ones demos and "how's this week looking" questions actually ask about.
recent_boost_days = 35   # covers "this week" + "last week" + "this/last month"
for p in patients:
    if random.random() < 0.6:   # not every patient — keep it realistic, not uniform
        n_recent = random.randint(1, 3)
        for _ in range(n_recent):
            day_offset = random.randint(0, recent_boost_days)
            appt_date = end_date - timedelta(days=day_offset)
            appointments.append((
                appt_id, p[0], random.choice(dentists)[0],
                appt_date.strftime("%Y-%m-%d"),
                random.choice(appt_types),
                random.choice(["Completed", "Completed", "Scheduled", "No-Show"])
            ))
            appt_id += 1
cur.executemany("INSERT INTO appointments VALUES (?,?,?,?,?,?)", appointments)

# --- Treatments (only for completed appointments) ---
procedures = [
    ("Root Canal Therapy - Molar", "D3330", (900, 1400)),
    ("Root Canal Therapy - Anterior", "D3310", (600, 900)),
    ("Root Canal Therapy - Premolar", "D3320", (750, 1100)),
    ("Retreatment", "D3346", (1000, 1600)),
    ("Apicoectomy", "D3410", (1100, 1700)),
    ("Pulp Cap - Direct", "D3110", (150, 300)),
    ("Post-Op Exam", "D0170", (0, 75)),
]

treatments = []
t_id = 1
for a in appointments:
    if a[5] == "Completed":
        proc = random.choice(procedures)
        cost = round(random.uniform(*proc[2]), 2)
        treatments.append((
            t_id, a[0], random.randint(1, 32), proc[0], proc[1], cost,
            random.choice(["Uneventful procedure.", "Patient tolerated well.",
                            "Mild sensitivity post-op, advised OTC pain relief.",
                            "Follow-up recommended in 2 weeks.", None])
        ))
        t_id += 1
cur.executemany("INSERT INTO treatments VALUES (?,?,?,?,?,?,?)", treatments)

# --- Invoices (one per treatment) ---
invoices = []
inv_id = 1
for t in treatments:
    appt = next(a for a in appointments if a[0] == t[1])
    amount_due = t[5]
    paid_fraction = random.choice([1.0, 1.0, 1.0, 0.5, 0.0])
    amount_paid = round(amount_due * paid_fraction, 2)
    status = "Paid" if amount_paid >= amount_due else ("Partial" if amount_paid > 0 else "Unpaid")
    inv_date = appt[3]
    invoices.append((inv_id, appt[1], appt[0], amount_due, amount_paid, inv_date, status))
    inv_id += 1
cur.executemany("INSERT INTO invoices VALUES (?,?,?,?,?,?,?)", invoices)

conn.commit()
conn.close()
print(f"Built {DB_PATH}: {len(patients)} patients, {len(appointments)} appointments, "
      f"{len(treatments)} treatments, {len(invoices)} invoices.")
