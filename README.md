# Clinic Records — Natural Language Query Tool

A local desktop-style app built for a small endodontist practice, letting
front-desk staff and doctors ask plain-English questions about patients,
appointments, treatments, and billing — without writing SQL.

> **Note on this repo:** this is a rebuilt version of a project originally
> delivered for a neighborhood endodontist office. The original codebase was
> lost to a storage cleanup; this version reconstructs the same architecture
> and functionality with synthetic sample data (no real patient information).

## How it works

1. **Data layer** — Practice records were originally structured and entered
   in **MS Access**, then exported to **SQLite** and managed with
   **DB Browser for SQLite**. `data/build_db.py` regenerates an equivalent
   schema (patients, dentists, appointments, treatments, invoices) with
   synthetic data for demo purposes.
2. **Query translation** — A **LangChain SQL Agent** (`app/main.py`) takes
   a plain-English question, inspects the database schema, generates the
   appropriate SQL, executes it against SQLite, and returns a natural-
   language answer.
3. **Interface** — A lightweight **Flask** app serves a simple local web UI
   (`templates/index.html`) that staff use like a desktop tool — type a
   question, get an answer, no SQL knowledge required.
4. **Deployment** — Packaged with **Docker** so the same environment could
   be replicated on other machines in the office without manual setup.

## Running locally

Requires [Ollama](https://ollama.com) running locally with a model pulled:

```bash
ollama pull llama3.1
ollama serve          # if not already running

pip install -r requirements.txt
python data/build_db.py        # generates data/clinic.db
python app/main.py
```

Visit `http://localhost:5000`.

## Running with Docker

`docker-compose.yml` runs both the app and an Ollama container:

```bash
docker compose up --build
docker compose exec ollama ollama pull llama3.1   # first run only
```

Override the model with `OLLAMA_MODEL=<name>` if you used a different one.

## Example questions

- "How many root canals were completed last month?"
- "Which patients have an unpaid balance over $500?"
- "List appointments for Dr. Chen this week"
- "What's our no-show rate this year?"

## Schema

- `dentists` — practitioner roster
- `patients` — patient records, insurance, referral source
- `appointments` — scheduling, linked to patient + dentist
- `treatments` — procedures performed per appointment (CDT codes, cost)
- `invoices` — billing status per appointment

## Stack

Python · Flask · LangChain (SQL Agent) · Llama (via Ollama, local inference) · SQLite · Docker · MS Access (source data entry) · DB Browser for SQLite
