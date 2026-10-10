# GSA SRMS

Student Records Management System for the Guyana School of Agriculture (Ministry of Agriculture).
One of three systems in the GSA ecosystem, built and deployed separately and joined by service APIs:

| System | Owns | Repository |
|---|---|---|
| HRMS | Staff, positions, campuses and organisational units | `HRMS/gsa-hrms` |
| **SRMS (this one)** | Programmes, courses, applicants, students, offerings, enrolments, results | `SRMS/gsa-srms` |
| LMS | Course sites, content, assignments, coursework marks | `LMS/gsa-lms` |

Same stack and licence policy as the HRMS: Django 5, Django REST Framework, PostgreSQL 16, React,
Caddy, Docker Compose. Every component is MIT, BSD, Apache 2.0, PostgreSQL or PSF licensed.

**Status:** scaffold with working API and web screens. Backend and web tests pass against PostgreSQL;
see the CI workflow for current counts.

## Modules

| Directory | What exists |
|---|---|
| `api/programmes` | Programmes, courses and curricula; a programme may set an intake capacity |
| `api/students` | Admissions workflow (submitted, under_review, interview, assessed, offered, waitlisted, accepted, declined, rejected, withdrawn) with document upload and a per-programme, per-intake waitlist; accepting an offer creates the student and the student number; students are campus-scoped, with an encrypted national ID and an audited reveal |
| `api/academics` | Academic years and terms, course offerings (coursework and examination weights must total 100), enrolments with capacity and campus checks, effective-dated grading scale, results workflow (lecturer submits, Head of Department approves, Registrar publishes), grade point averages and transcripts |
| `api/integration` | Scoped service keys; staff and campuses pulled from the HRMS; offerings, class lists and coursework marks exchanged with the LMS |
| `api/reports` | Enrolment by programme and campus, results summary with pass rates, admissions funnel |
| `api/core`, `api/audit`, `api/iam`, `api/notifications` | Shared skeleton: base models, field encryption, insert-only audit log, roles with campus and department scopes, session login with TOTP, account lockout, notifications |
| `web/` | Dashboard, student directory with file and transcript, admissions review file (workflow actions, scoring, document upload, waitlist), marks entry and results workflow, a student's own results |

## Setup

```bash
cp .env.example .env && sh scripts/gen-secret.sh      # paste the two lines into .env, set DB_PASSWORD
docker compose up -d --build
docker compose exec api python manage.py migrate
docker compose exec api python manage.py seed --year 2026
docker compose exec api python manage.py createsuperuser
```

Open https://srms.localhost:8444 (the HRMS uses 443, so each system has its own port in development).

| Command | Purpose |
|---|---|
| `docker compose run --rm api pytest -q` | Backend tests (PostgreSQL required) |
| `docker compose run --rm api ruff check .` | Lint |
| `cd web && npm run lint && npm run build` | Front-end checks |

## Joining the ecosystem

```bash
docker network create gsa-ecosystem                                   # once per host
# In the HRMS: issue a key for this system and put it in .env as HRMS_API_KEY
docker compose exec api python manage.py create_service_client --name srms --scopes staff:read org:read
# Here: issue a key for the LMS (it goes in the LMS .env as SRMS_API_KEY)
docker compose exec api python manage.py create_service_client --name lms --scopes academics:read marks:write
docker compose -f compose.yml -f compose.ecosystem.yml up -d
docker compose exec api python manage.py sync_hrms                     # also runs nightly at 01:30
```

Integration endpoints (header `Authorization: Api-Key <key>`):

| Endpoint | Scope | Used by |
|---|---|---|
| `GET /api/v1/integration/offerings/?current=1` | `academics:read` | LMS builds course sites |
| `GET /api/v1/integration/enrolments/?offering=<code>` | `academics:read` | LMS builds class lists |
| `POST /api/v1/integration/coursework-marks/` | `marks:write` | LMS returns coursework percentages; only draft results accept them |

No integration endpoint exposes a national ID, date of birth or address.

## Items for the Registrar to confirm

The seed data contains placeholders, all editable in the application: programme durations and campuses,
the grading scale (A from 80, B from 70, C from 60, D from 50), semester dates, the student number
format (`26MRP0001`), and the default 40 to 60 split between coursework and examination.

## Rules

- Personal data of students stays in Guyana; identifiers are encrypted and never logged in clear.
- Never commit secrets. `.env` is ignored; `.env.example` holds placeholders only.
- Every write to a student, application or result goes through an audited view or workflow.
- Branching: trunk-based, `feature/<area>-<name>` branches, pull request with green CI into `main`.

## Hosted staging (Railway)

A staging and demonstration copy runs on Railway in the project "GSA Ecosystem", beside the other two
systems, with fictional data only. How it is built and configured: [deploy/railway/README.md](deploy/railway/README.md).

## Demonstration data

`seed_demo` loads an invented dataset for staging and development: four courses, seven offerings, thirteen
students admitted through the admissions service, four applications still in progress, enrolments with
empty draft results for the current term, and six published results for the term before. Every person is
fictional, says so in the address line, and carries an identifier that starts with `DEMO-`.
**Never run it on a database that holds real records.**

```bash
docker compose exec api python manage.py sync_hrms                  # lecturers' names, from the HRMS
docker compose exec api python manage.py seed_demo --fictional
```

It is idempotent. Lecturers are the staff of the HRMS demonstration data, so load the systems in this
order: HRMS, SRMS, LMS.
