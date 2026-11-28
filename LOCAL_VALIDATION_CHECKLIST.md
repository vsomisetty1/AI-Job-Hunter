# Local validation checklist

A walk through the whole app with your own resume, ending with your first real
application. Do it once after [LOCAL_SETUP.md](LOCAL_SETUP.md). Each step says what to
click, what you should see, and how to check it from a terminal. Button and field names are
quoted exactly as the app shows them.

Steps 1–7 were run end to end on version 0.10.0 with a synthetic resume and live job boards
(GitLab on Greenhouse, Spotify on Lever). Step 7 was checked up to the "Fill application
form" button, and the review flow by the automated browser tests. Step 8 has never been
done on a live site: it is the first real submission (Phase 11). Record what happens
(section 9).

**Before you start**
- [ ] The app is running (`./scripts/dev.sh`) and LOCAL_SETUP.md section 10 passes.
- [ ] Settings are filled in: http://localhost:3000/settings → "Preferred locations",
      "Workplace", "Minimum (yearly)", "Target (yearly)", "Work authorization",
      "I need visa sponsorship", "Willing to relocate" → **"Save preferences"**. Expect
      "Saved. Jobs are being filtered and scored again."
- [ ] A backup exists: `./scripts/backup.sh` (BACKUP_AND_RECOVERY.md).

Your resume stays on your machine: no step sends it anywhere except Claude (only if you set
`ANTHROPIC_API_KEY`, and without your name, contact details or links) and, in steps 7–8, the
company you apply to.

## 1. Upload your resume

1. Open **Resumes** (http://localhost:3000/resumes).
2. Tick **"Use as my primary resume (rebuilds the profile)"**.
3. Click **"Choose file"** (or drop the file on "Drop your resume here"): PDF or DOCX, up to
   10 MB.
4. Expect: "Uploaded `<file>`. Processing finished." and the file under "Your resumes" with
   status **parsed** and the label **Primary**.
5. Click **"Review the parsed data"** and check every section against your document:
   contact details, each role (title, company, location, dates, all bullets), education,
   certifications, skills. Correct anything wrong there: an edit is saved as a new version.

- [ ] Status is `parsed`; no role, date or bullet is missing or wrong.

Terminal check:

```bash
curl -s http://127.0.0.1:8000/api/v1/resumes
```

It lists your resume with `"parse_status": "parsed"` and `"is_primary": true`.

A file is refused if it contains active content (macros, PDF JavaScript, embedded files) or
is encrypted: save a clean copy (for example "Save as PDF" again) and upload that.

## 2. Generate your profile

The primary resume builds the profile automatically.

1. Open **Profile** (http://localhost:3000/profile).
2. Check: your name and headline, **Seniority**, **Experience** (years), **Target roles**,
   **Skills**, **Career history**, **Education**, **Certifications**. "Source" says
   "Rule-based" (or Claude when an API key is set); "Transferable roles" and the career
   analysis need Claude.
3. Fix anything with **"Edit"**. Edited fields are kept when the profile is rebuilt.
4. **"Regenerate"** rebuilds it from the resume; untick "Keep my edits when regenerating"
   only if you want to drop your edits.

- [ ] Seniority, years and skills are right. They drive every score.

Terminal check:

```bash
curl -s http://127.0.0.1:8000/api/v1/profile
```

It shows `"inference_status": "complete"`.

## 3. Run discovery

1. Open **Discovery** (http://localhost:3000/discovery).
2. Pick companies whose jobs you want:
   - under **Suggested companies**, tick some and click **"Add N selected"**, or
   - under **Tracked companies**, choose a **Platform** (Greenhouse, Lever, Ashby), type the
     **Board name** (the last part of the careers URL, for example `stripe` in
     `job-boards.greenhouse.io/stripe`) and click **"Add"**. The board is checked live
     before it is saved.
3. Click **"Discover jobs now"**. A couple of boards take a few seconds; the button shows
   "Discovering…" while it runs.
4. Expect a new entry in **Run history** with its status and "Found / new / updated /
   skipped" counts. Open it for per-company results.
5. Optional: **Connector health** → **"Check live"** probes each platform.

- [ ] The run succeeded and every company shows `ok` (an `error` or `not_found` row names
      the reason, for example a board that moved).

Terminal check (status, jobs found, jobs new):

```bash
curl -s "http://127.0.0.1:8000/api/v1/discovery/runs?limit=1"
```

Discovery then repeats on its own every `DISCOVERY_INTERVAL_MINUTES` (6 hours), only for
companies that are due.

## 4. View discovered jobs

1. Click **"View discovered jobs →"** or open **Jobs** (http://localhost:3000/jobs).
2. The header says how many jobs match your filters, how many were filtered out and scored.
3. Use **Search** ("Title, company or location"), **Show** (matches / filtered out / not
   filtered yet / all), **Min score**, **Source**, **Workplace**, **Sort** ("Best score" by
   default) and "Include expired".
4. Open a job: requirements, description, salary, **"View posting ↗"** (the original),
   **Rule-based score** with each component, **Skills** ("You have" / "Missing"),
   **Filters kept** (each rule's decision) and the raw board data.

- [ ] The top matches look like jobs you would apply to. If not, adjust **Settings**
      (locations, workplace, salary, excluded companies and keywords) and your profile's
      skills and target roles.

## 5. Run scoring

Scoring already ran after discovery (Discovery → Deduplication → Filtering → Scoring), and
saving Settings or editing the profile re-scores in the background.

1. On **Jobs**, click **"Re-score"** to run filtering and scoring again ("Scoring…").
2. Check that scores and the "filtered out" count change as you expect after a settings change.
3. Optional, with `ANTHROPIC_API_KEY` set: **Settings → "Also score my best matches with
   Claude"** and "Only jobs with a rule score of at least" (default 60). Claude scores only
   that shortlist, capped per run and per day (`.env.example`).

- [ ] A job's score breakdown makes sense to you (skills, title, seniority, location, salary).

Terminal check (`jobs_passed`, `jobs_scored`, `last_run_status`):

```bash
curl -s http://127.0.0.1:8000/api/v1/scoring/summary
```

## 6. Generate a package

Pick a real job you want, near the top of the list.

1. On the job's page, under **Application package**: keep **"Include a cover letter"**
   ticked; tick **"Reword with Claude"** only with an API key. Click **"Generate package"**.
2. The package page opens ("Generating the package… this page updates by itself.") and
   shows, within seconds:
   - **Tailored resume**: "Resume (PDF)" / "Resume (DOCX)"; **"See N changes"** lists every
     change with its reason.
   - **Cover letter**: "Letter (PDF)" / "Letter (DOCX)" and "Read it".
   - **Application answers**: **"Review answers"**.
3. Open **Answers**. Every answer marked **needs your input** could not be answered from
   your facts (salary, sponsorship, "why this company", skills your resume does not show).
   Click **"Edit"**, write your answer, **"Save answer"**. Check the others too.
4. Download the tailored resume and the letter and read them as a recruiter would. Nothing
   may claim a skill, employer, date or number you do not have.
5. When it is right: **"Approve"** → optional notes → **"Confirm approval"**. The package
   shows "approved", and the job appears under **Applications → Ready to fill**. (Or
   **"Reject"** with a reason, or **"Regenerate"** for a new version.)

- [ ] No answer still says "needs your input". The resume and letter are true and you
      would send them.

## 7. Run automation in review mode

Review mode fills the real form and **stops**: nothing is sent until you confirm in step 8.

> **Attaching is uploading.** On Greenhouse and Ashby, attaching your resume uploads it to the
> company's system right away, even if you cancel afterwards. Only open the form for a job
> you really intend to apply to.

**Optional dry run first, with a synthetic applicant** (no personal data; it still uploads
the synthetic documents to the companies' systems, and never submits). From the repository
root:

```bash
source backend/.venv/bin/activate
```

```bash
python scripts/validate_automation.py --platform greenhouse --jobs 1 --headed --out validation-output/automation
```

It writes `report.md` and screenshots to `validation-output/automation/` (git-ignored).
`--headed` shows the browser.

**With your package:**
1. Recommended for the first runs: in `.env` set `AUTOMATION_HEADLESS=false`, then restart
   (Ctrl+C, `./scripts/dev.sh`). A Chromium window will show the form being filled.
2. Open **Applications** (http://localhost:3000/applications). Under **Ready to fill**, click
   **"Fill application form"** next to your job (also on the approved package's page).
3. Follow the progress: "Open the form", "Upload documents", "Fill in answers", "Check the
   form", "Wait for your review".
4. In **Review before submitting**, check:
   - Resume and Cover letter: attached.
   - **Missing fields**: required fields the app could not answer. Answer them right there;
     the open form changes.
   - **Validation problems**: the form's own error messages.
   - **Answers inserted**: each value and where it came from (**"Edit"** to change one).
   - **Left for you**: consent boxes, self-identification and anything it will not guess.
   - **Screenshots** of the filled form.
5. For this validation step, stop here: click **"Cancel"**. Expect "Cancelled. Nothing was
   submitted." (Or keep it open and go on to step 8; an untouched form closes after 30
   minutes, and **"Retry (reopen and refill)"** reopens it.)

- [ ] Every field you can see in the form is filled correctly or listed for you; nothing was
      sent.

Logs: **Applications → Automation logs**, and **Submission history** for every run.

## 8. Your first real application

Do this with time to watch it, on a job you want.

1. Back up: `./scripts/backup.sh`.
2. Make sure `AUTOMATION_HEADLESS=false` (step 7.1), so you can see the form and solve a
   CAPTCHA if one appears.
3. **Applications** → **"Fill application form"** (or **"Retry (reopen and refill)"** on the
   run you cancelled).
4. Wait for **Review before submitting**. Fix every **Missing field** and **Validation
   problem** in the review screen. Fill anything **Left for you** (consent, voluntary
   questions) **in the Chromium window** yourself.
5. Compare the Chromium window with the review screen once more, field by field.
6. Click **"Submit application…"**, tick **"I reviewed the filled form and want to submit
   this application to `<company>` now."** and click **"Submit to `<company>`"**. ("Not yet"
   goes back.) The app checks the form again first and refuses if anything is missing.
7. Expect "Submitting the application you confirmed…", then the run shows **submitted** with
   the site's confirmation. The package and the application become submitted and the job
   `applied`.

If it does not end as submitted:
- **CAPTCHA**: solve it in the Chromium window, then submit again from the review screen.
- **"Not confirmed"** (unconfirmed): the click happened but the site's confirmation was not
  recognised. **Do not submit again.** Check your email and the company's portal first. The
  app never retries a submission by itself.
- **Failed with a reason** (job closed, form changed, upload refused): follow the hint in
  **"What went wrong"**; **"Retry (reopen and refill)"** when it makes sense.
- **Applied by hand instead**: on the package page, **"I applied with this package"** records it.

After submitting:
- [ ] **Applications → Submission history** shows the run as submitted.
- [ ] You received the company's confirmation email.
- [ ] **Interviews** (http://localhost:3000/insights/pipeline) lists the application. From now
      on, use **"Record what happened"** for every reply, screen, interview, offer, rejection
      or withdrawal: the dashboard and recommendations are only as good as what you record.
- [ ] Back up again: `./scripts/backup.sh`.

## 9. Record the result

This first real submission is the open item that matters most for 1.0 (RELEASE_READINESS.md,
section 4). For each of your first applications, note:

| Job and platform | Fields filled / left for you | Fixes you made in review | CAPTCHA? | Result (submitted / not confirmed / failed + reason) | Confirmation email? |
|---|---|---|---|---|---|
| | | | | | |

The run's details are also in **Applications → Automation logs** and the screenshots. Do not
commit anything with personal data: `validation-output/` and `backups/` are git-ignored.
