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
2. **Query translation** — `app/main.py` reads the live database schema and
   foreign-key relationships directly from SQLite, builds a prompt with that
   schema plus pre-computed date ranges ("this week," "last month," etc.)
   and real sample values for status/category columns, and asks a locally
   running **Llama model (via Ollama)** to output *only* the SQL for the
   question. That exact SQL is then executed in Python against the real
   database — the model never has a chance to fabricate results. If the
   generated SQL errors against the schema, the app feeds the real error
   back to the model for one self-correction attempt before giving up.
3. **Interface** — A lightweight **Flask** app serves a simple local web UI
   (`templates/index.html`): a question box, a panel showing the generated
   SQL, and a results table — no chat-style narration, just the query and
   its real output.
4. **Deployment** — Packaged with **Docker** (app + an Ollama container) so
   the same environment could be replicated on other machines in the office
   without manual setup.

## Running locally

Requires [Ollama](https://ollama.com) running locally with a model pulled:

```bash
ollama pull llama3.1
ollama serve          # if not already running

pip install -r requirements.txt
python data/build_db.py        # regenerates data/clinic.db (already included)
python app/main.py
```

Visit `http://localhost:5001`.

(Port 5001 is used by default since macOS's AirPlay Receiver often occupies
port 5000. Override with `PORT=5000 python app/main.py` if you'd rather free
up 5000 instead — System Settings → General → AirDrop & Handoff → AirPlay
Receiver.)

Set `OLLAMA_MODEL` to use a different local model, e.g.:

```bash
OLLAMA_MODEL=llama3.2:latest python app/main.py
```

## Running with Docker

`docker-compose.yml` runs both the app and an Ollama container:

```bash
docker compose up --build
docker compose exec ollama ollama pull llama3.1   # first run only
```

Override the model with `OLLAMA_MODEL=<name>` in your environment or a
`.env` file.

## Example questions

- "Which patients have an unpaid balance over $500?"
- "List appointments for Dr. Chen this week"
- "How many root canals were completed last month?"
- "What's our no-show rate this year?"

## Schema

- `dentists` — practitioner roster
- `patients` — patient records, insurance, referral source
- `appointments` — scheduling, linked to patient + dentist
- `treatments` — procedures performed per appointment (CDT codes, cost)
- `invoices` — billing status per appointment

## Stack

Python · Flask · Llama (via Ollama, local inference) · SQLite · Docker · MS Access (source data entry) · DB Browser for SQLite

## Notes on reliability

Small local models can still misinterpret ambiguous questions (e.g. an
unnecessary JOIN silently excluding rows) even with schema and foreign-key
context in the prompt. The app validates and retries on hard SQL errors,
but logic-level mistakes are a known limitation of running fully local,
smaller open-weight models rather than a larger hosted LLM.
