#!/usr/bin/env python3
"""End-to-end MVP validation against a RUNNING backend.

    resume -> parse -> profile -> scoring -> top jobs -> packages -> quality report

Usage (backend running, jobs already discovered; run with the backend's venv):

    python scripts/validate_mvp.py path/to/resume.docx --out validation-output
    python scripts/validate_mvp.py --reuse            # keep the uploaded resume
    python scripts/validate_mvp.py --jobs 10 --use-llm

The report contains your resume data: it is written to --out (git-ignored by
default), never anywhere else. Checks are mechanical (what a parser, an ATS and
a careful reader would notice); read the packages yourself as well.
"""

import argparse
import io
import itertools
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import HTTPError

API = "http://127.0.0.1:8000/api/v1"
GENERIC_PHRASES = (
    "strong match for the work i do best", "i would be glad to bring", "lines up with the work",
    "team player", "passionate", "dynamic", "synergy", "fast-paced", "go-getter",
    "think outside the box", "hit the ground running", "detail-oriented", "results-driven",
    "i am writing to express", "to whom it may concern",
)  # fmt: skip


# ------------------------------------------------------------------ http
def call(method: str, path: str, body: Any = None, raw: bool = False) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = request.Request(API + path, data=data, method=method)
    if data is not None:
        req.add_header("content-type", "application/json")
    try:
        with request.urlopen(req, timeout=120) as r:  # noqa: S310 - local API
            payload = r.read()
    except HTTPError as e:
        raise SystemExit(f"{method} {path} -> {e.code}: {e.read()[:300]!r}") from e
    return payload if raw else json.loads(payload or b"null")


def upload(path: Path) -> dict[str, Any]:
    boundary = "----mvp-validation"
    mime = ("application/pdf" if path.suffix.lower() == ".pdf" else
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")  # fmt: skip
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
            f"filename=\"{path.name}\"\r\nContent-Type: {mime}\r\n\r\n").encode()  # fmt: skip
    body += path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = request.Request(API + "/resumes", data=body, method="POST")
    req.add_header("content-type", f"multipart/form-data; boundary={boundary}")
    try:
        with request.urlopen(req, timeout=120) as r:  # noqa: S310
            return json.loads(r.read())
    except HTTPError as e:
        if e.code == 409:
            return {"duplicate": True}
        raise


def wait_task(task_id: str, timeout: float = 180) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = call("GET", f"/system/tasks/{task_id}")["status"]
        if status == "succeeded":
            return
        if status in ("failed", "cancelled"):
            raise SystemExit(f"task {task_id} {status}")
        time.sleep(0.5)
    raise SystemExit(f"task {task_id} timed out")


# ------------------------------------------------------------- resume checks
def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]
    return []


def resume_checks(detail: dict[str, Any], profile: dict[str, Any], raw_text: str) -> dict[str, Any]:
    parsed = detail["parsed"]
    issues: list[str] = []
    roles = parsed["experience"]
    for i, r in enumerate(roles, 1):
        missing = [f for f in ("title", "company", "start_date") if not r.get(f)]
        if missing:
            issues.append(f"role {i} ({r.get('title')} / {r.get('company')}) lacks {', '.join(missing)}")
        if not r["bullets"]:
            issues.append(f"role {i} ({r.get('title')}) has no bullets")
        if r.get("title") and len(r["title"].split()) > 8:
            issues.append(f"role {i} title looks like a sentence: {r['title'][:60]}")
    for e in parsed["education"]:
        if not e.get("degree"):
            issues.append(f"education at {e.get('institution')} has no degree")
    for c in parsed["certifications"]:
        if c.get("issuer") and "(" in c["issuer"]:
            issues.append(f"certification issuer looks broken: {c['issuer']}")
    # Text lost by the parser: lines whose words mostly appear nowhere in the
    # parsed data (month names are skipped: parsed dates read "2023-08").
    parsed_words = set(norm(" ".join(strings(parsed))).replace("-", " ").split())
    months = {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct",
              "nov", "dec", "january", "february", "march", "april", "june", "july", "august",
              "september", "october", "november", "december", "present", "current", "issued"}

    def is_lost(line: str) -> bool:
        words = [w for w in norm(line).split() if len(w) > 2 and w not in months]
        if len(words) < 3 or re.fullmatch(r"[A-Z &/]+", line.strip()):
            return False
        return sum(w in parsed_words for w in words) / len(words) < 0.7

    lost = [line for line in raw_text.splitlines() if is_lost(line)]
    for line in lost:
        issues.append(f"text not in parsed data: {line[:90]}")
    for role in profile.get("inferred_roles", []):
        if len(role.split()) > 6 or "(" in role:
            issues.append(f"odd inferred role: {role}")
    return {
        "roles": [{k: r.get(k) for k in ("title", "company", "location", "start_date", "end_date",
                                         "is_current")} | {"bullets": len(r["bullets"])}
                  for r in roles],  # fmt: skip
        "education": parsed["education"],
        "certifications": parsed["certifications"],
        "skills": parsed["skills"],
        "skill_groups": [(g["name"], g["skills"]) for g in parsed["skill_groups"]],
        "confidence": parsed["meta"]["confidence"],
        "profile": {k: profile.get(k) for k in (
            "headline", "seniority", "experience_level", "years_of_experience", "inferred_roles",
            "transferable_roles", "industries", "education_summary", "certification_summary",
            "inference_source")},  # fmt: skip
        "profile_skills": profile.get("skills"),
        "lost_lines": lost,
        "issues": issues,
    }


# ------------------------------------------------------------- job selection
def pick_jobs(n: int) -> list[dict[str, Any]]:
    """Best-scored kept jobs, at most one per company and per normalized title."""
    chosen: list[dict[str, Any]] = []
    companies: set[str] = set()
    titles: set[str] = set()
    for offset in range(0, 1000, 200):
        page = call("GET", f"/jobs?sort=score&filter_state=passed&limit=200&offset={offset}")
        for job in page["items"]:
            t = re.sub(r"\b(senior|sr|staff|lead|principal|ii|iii|i)\b", "", norm(job["title"])).strip()
            if job["score"] is None or job["company_id"] in companies or t in titles:
                continue
            chosen.append(job)
            companies.add(job["company_id"])
            titles.add(t)
            if len(chosen) == n:
                return chosen
        if len(page["items"]) < 200:
            break
    return chosen


# ------------------------------------------------------------ package checks
def shingles(text: str, k: int = 4) -> set[tuple[str, ...]]:
    words = norm(text).split()
    return {tuple(words[i : i + k]) for i in range(max(0, len(words) - k + 1))}


def jaccard(a: set[Any], b: set[Any]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def pdf_text(data: bytes) -> tuple[str, int]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages), len(pdf.pages)


def package_checks(pkg: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    tr = pkg["tailored_resume"] or {}
    tailoring = tr.get("tailoring", {})
    matched, missing = tailoring.get("matched_skills", []), tailoring.get("missing_skills", [])
    pdf = call("GET", f"/packages/{pkg['id']}/files/resume.pdf", raw=True)
    text, pages = pdf_text(pdf)
    lowered = text.lower()
    absent = [s for s in matched if s.lower() not in lowered]
    if absent:
        issues.append(f"ATS: matched skills missing from the PDF text: {absent}")
    if "(cid:" in text:
        issues.append("ATS: unreadable glyphs in the PDF")
    for section in ("EXPERIENCE", "SKILLS", "EDUCATION"):
        if section not in text:
            issues.append(f"ATS: no {section} heading")
    coverage = len(matched) / (len(matched) + len(missing)) if matched or missing else None
    changes = tr.get("changes", [])
    if not changes:
        issues.append("tailoring: no changes at all")
    letter = (pkg.get("cover_letter") or {}).get("content", "")
    lw = letter.lower()
    generic = [p for p in GENERIC_PHRASES if p in lw]
    if letter and job["company_name"].lower() not in lw:
        issues.append("letter: company not named")
    answers = pkg["answers"]
    flagged = [a["question_key"] for a in answers if a["needs_review"]]
    return {
        "job": f"{job['title']} @ {job['company_name']}",
        "score": job["score"],
        "package": pkg["id"],
        "status": pkg["status"],
        "keyword_coverage": round(coverage, 2) if coverage is not None else None,
        "matched": matched,
        "missing": missing,
        "changes": [f"{c['section']}/{c['field']}: {c['reason']}" for c in changes],
        "summary": tr.get("content", {}).get("summary"),
        "pdf_pages": pages,
        "letter_words": (pkg.get("cover_letter") or {}).get("word_count"),
        "letter": letter,
        "generic_phrases": generic,
        "answers": {a["question_key"]: {"answer": a["answer"], "needs_review": a["needs_review"]}
                    for a in answers},  # fmt: skip
        "answers_flagged": flagged,
        "issues": issues,
    }


# ----------------------------------------------------------------- report
def markdown(report: dict[str, Any]) -> str:
    r, out = report["resume"], []
    out.append("# MVP validation report\n")
    out.append(f"Generated {time.strftime('%Y-%m-%d %H:%M')}. Contains personal data: keep private.\n")
    out.append("## 1. Resume and profile\n")
    out.append(f"- Parse confidence: {r['confidence']}")
    for role in r["roles"]:
        out.append(f"- Role: {role['title']} | {role['company']} | {role['location']} | "
                   f"{role['start_date']} - {role['end_date'] or ('present' if role['is_current'] else '?')}"
                   f" | {role['bullets']} bullets")  # fmt: skip
    out.append(f"- Education: {r['education']}")
    out.append(f"- Certifications: {[(c['name'], c['issuer'], c['date']) for c in r['certifications']]}")
    out.append(f"- Skills ({len(r['skills'])}): {', '.join(r['skills'])}")
    for k, v in r["profile"].items():
        out.append(f"- Profile {k}: {v}")
    out.append(f"\n**Resume issues ({len(r['issues'])})**\n")
    out += [f"- {i}" for i in r["issues"]] or ["- none"]
    out.append("\n## 2. Packages\n")
    sims = report["letter_similarity"]
    out.append(f"- Jobs: {len(report['packages'])}; cover-letter 4-gram overlap: mean "
               f"{sims['mean']}, max {sims['max']}")  # fmt: skip
    for p in report["packages"]:
        out.append(f"\n### {p['job']} (score {p['score']})\n")
        out.append(f"- Keyword coverage {p['keyword_coverage']}; matched {p['matched']}; missing {p['missing']}")
        out.append(f"- Summary: {p['summary']}")
        out += [f"- Change: {c}" for c in p["changes"]]
        out.append(f"- Letter: {p['letter_words']} words; generic phrases {p['generic_phrases']}")
        out.append(f"- Answers needing review: {p['answers_flagged']}")
        out += [f"- ISSUE: {i}" for i in p["issues"]]
        out.append("\n<details><summary>Cover letter</summary>\n\n" + p["letter"] + "\n\n</details>")
        out.append("\n<details><summary>Answers</summary>\n")
        out += [f"- **{k}**: {v['answer']}" for k, v in p["answers"].items()]
        out.append("\n</details>")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("resume", nargs="?", type=Path)
    ap.add_argument("--reuse", action="store_true", help="use the resume already uploaded")
    ap.add_argument("--jobs", type=int, default=10)
    ap.add_argument("--use-llm", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("validation-output"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    if args.resume and not args.reuse:
        up = upload(args.resume)
        if up.get("task_id"):
            wait_task(up["task_id"])
    resumes = call("GET", "/resumes")
    if not resumes:
        raise SystemExit("no resume uploaded")
    rid = next((r["id"] for r in resumes if r["is_primary"]), resumes[0]["id"])
    detail = call("GET", f"/resumes/{rid}")
    profile = call("GET", "/profile")
    raw_text = "\n".join(strings(detail["parsed"]))
    if args.resume and args.resume.suffix.lower() == ".docx":
        import docx

        d = docx.Document(str(args.resume))
        body = [p.text for p in d.paragraphs]
        body += [p.text for t in d.tables for row in t.rows for c in row.cells for p in c.paragraphs]
        raw_text = "\n".join(t.strip() for t in body if t.strip())
    resume = resume_checks(detail, profile, raw_text)

    started = call("POST", "/scoring/runs")
    wait_task(started["task_id"], timeout=600)
    jobs = pick_jobs(args.jobs)
    packages = []
    for job in jobs:
        existing = call("GET", f"/packages?job_id={job['id']}")["items"]
        live = [p for p in existing if p["status"] not in ("superseded", "rejected", "failed")]
        if live:
            started = call("POST", f"/packages/{live[0]['id']}/regenerate", {"use_llm": args.use_llm})
        else:
            started = call("POST", "/packages", {"job_id": job["id"], "use_llm": args.use_llm})
        wait_task(started["task_id"])
        pkg = call("GET", f"/packages/{started['package_id']}")
        packages.append(package_checks(pkg, job))
    letters = [shingles(p["letter"]) for p in packages if p["letter"]]
    pairs = [jaccard(a, b) for a, b in itertools.combinations(letters, 2)]
    report = {
        "resume": resume,
        "packages": packages,
        "letter_similarity": {
            "mean": round(sum(pairs) / len(pairs), 3) if pairs else None,
            "max": round(max(pairs), 3) if pairs else None,
        },
    }
    (args.out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    (args.out / "report.md").write_text(markdown(report))
    n_issues = len(resume["issues"]) + sum(len(p["issues"]) for p in packages)
    print(f"report: {args.out / 'report.md'} ({len(packages)} packages, {n_issues} issues)")


if __name__ == "__main__":
    sys.exit(main())
