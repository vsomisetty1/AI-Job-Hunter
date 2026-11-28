# MVP validation (before browser automation)

Done on 2026-11-27 with the owner's real resume (DOCX) and 5,426 real postings discovered
from the public Greenhouse, Lever and Ashby boards in the company directory. Everything here
is anonymised: the full report (resume contents, letters, answers) is personal data and is
kept out of git (`validation-output/` is ignored).

## How to repeat it

```bash
./scripts/dev.sh                          # or start the backend on its own
python scripts/validate_mvp.py path/to/resume.docx --out validation-output/run1
python scripts/validate_mvp.py --reuse --jobs 10 --out validation-output/run2
```

`scripts/validate_mvp.py` drives the running backend over HTTP only: uploads the resume
(or reuses the stored one with `--reuse`), checks the parse against the document's own text
(lost lines, dates, roles), runs filtering and scoring, picks the top N scored jobs with
distinct companies and titles, generates (or regenerates) a package for each, and checks:
ATS text extraction from the PDF, keyword coverage, stock phrases, 4-gram overlap between
cover letters, and answers that need review. It writes `report.json` and `report.md`.

## 1. Resume parsing (real document)

| Problem found | Cause | Fix |
|---|---|---|
| 6 roles instead of 4; one role's bullets lost | Role headers laid out in 1-row tables (title cell, date cell) and bullets inside a table cell | DOCX extractor reads tables row by row, header lines first, then cell bullets, keeping list bullets; nested tables and merged cells handled |
| Dates attached to the wrong role | A dates-only line after a role's bullets started a new block | A dates-only line joins the previous role when that role has no dates |
| Locations missing | "Company — City, ST" split only on commas | Split on strong separators (`|`, em/en dash, ` - `, tab) and test the last piece |
| Degree missing | Degree regex lookahead rejected "B.S. Mathematics •" | Lookahead accepts bullets, dashes, digits |
| Certification issuer read as "Vendor (Issued" | Issue dates in parentheses | Parenthetical "(Issued …)" stripped, date kept |
| A title like "Platform Engineer (Contract)" used as a target role and in letters | Employment-arrangement qualifier treated as part of the role | `role_name()` strips (Contract), (Contingent), (Temporary)…; the resume itself keeps the title as written |
| GenAI, RAG, Helm, Oracle… not recognised | Taxonomy gaps; ambiguous names skipped in skills lists | ~20 taxonomy additions; items in a skills section are matched with ambiguous names allowed |
| Coursework lost | No place for "Relevant coursework" | Stored in education honours |

Result: parse confidence 1.0, 0 lost lines, 4 roles with correct dates and locations,
degree and 4 certifications; profile seniority "senior", 5.7 years, 52 skills.

## 2. Packages for the top 10 jobs (10 companies, 10 titles)

Reviewed as a hiring manager, a recruiter and an ATS. Problems found and fixed:

| Problem | Fix |
|---|---|
| Every job got the same "most relevant" bullets (few taxonomy skills per posting → ties) | `app/agents/relevance.py`: `JobTerms` weights the posting's own words (title ×3, requirements ×2, description ×1) on top of skills; used by Agents 6, 8 and 9 |
| Headline invented a title never held ("Senior Backend Engineer") and was added even when the summary already named the role | Headline = role as held; only added when the summary does not name it |
| Cover letters near-identical (mean 4-gram overlap 0.34, max 0.75) and generic ("strong match", "glad to bring") | Opening states years and latest real role; lead names only skills the bullets show; quotes a matching requirement; relevant certifications; no stock phrases; padding only with relevant evidence. Now mean 0.30, max 0.51 |
| Letter said "here is where I have used Java" and then quoted lines without Java | Best line for each named skill goes first |
| Letter and answers claimed use of a skill named only as a plan ("for future GenAI integration", "AI-ready") | Shared `strong_mentions()` rule: a mention after future/planned/exposure to/familiar with…, or followed by -ready/-oriented/concepts, is not use |
| Skill answers said "day-to-day" for skills mentioned once | "About N years: I have used X in …" only when every counted role shows use; otherwise "My resume mentions X in n role(s)… please confirm" (needs review) |
| "let us go" counted as the Go language | Lowercase spellings of ambiguous skills are ignored |
| Change log showed stems ("servic", "busines") | Shared terms shown as written |
| Resume rendered to 3 pages | Tighter ATS-safe styles: 2 pages |
| Scores inflated for sales, iOS and hardware roles; a 1-of-1 skill match scored 100 | Function mismatch penalty; skill coverage shrunk toward 50 % with few known skills; unknown skills neutral (`rules-3`) |

Final run: 10 packages, 0 harness issues, ATS text extraction clean, keyword coverage
0.5–1.0 (median 0.94; the gaps are skills the resume does not have), letters 150–220 words. Answers still flagged for review are the right ones:
salary, sponsorship and work authorisation (not set in Settings), "why this company"
(personal), and skills the resume does not show.

## 3. Data lifecycle

See [ADR-013](architecture/ADR-013.md). Measured: ~40 packages → 166 files (~4 MB), nothing
ever deleted. Added package delete, retention pruning, resume-file cleanup and an orphan
sweep, `GET /system/storage` and `POST /system/storage/cleanup`. Checked on the real data:
deleting a superseded package removed its 4 files; deleting an approved one returns 409.

## 4. Production readiness audit

| Area | Finding | Action |
|---|---|---|
| Scoring | 11 ms per job; 65 % in one regex per profile skill per text (≈5.4k jobs → 38–83 s per run) | One cached pattern per profile scans each text once: 3.8 ms per job, same results |
| Discovery | Two directory boards answered with 0 jobs and were reported "ok" (one company moved from Ashby to Greenhouse, one board went empty) | Directory updated; an empty board now carries a note in the run details |
| Approval | A package for a job that has since expired could still be approved (and later automated) | Approve returns 409 "This job is no longer posted" |
| Package generation | ~0.2 s per package; deterministic; no failures | — |
| Filtering | ~0.9 s for 5.4k jobs | — |
| Discovery | ~19 s for the directory boards | — |

Known and accepted for now: reparsing a resume does not rebuild the profile or rescore jobs
automatically (both are one click); the directory is static and will drift (the new
empty-board note makes drift visible).
