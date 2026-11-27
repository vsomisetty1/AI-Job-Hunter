# Application automation: real-world validation (review mode)

Run on 2026-11-27 against live Greenhouse, Lever and Ashby application forms. **Nothing
was submitted**: the script never calls the submit step, and a browser guard aborts any
form-submitting navigation (none was attempted). The applicant was a synthetic test
persona with synthetic PDF documents, never a real resume.

## How to repeat it

```bash
cd backend && source .venv/bin/activate && cd ..
python scripts/validate_automation.py --jobs 2 --out validation-output/automation
python scripts/validate_automation.py --platform lever --jobs 1 --headed   # watch it
```

It discovers jobs with the app's own connectors (engineering roles, one per company), opens
each application form with Agent 10, uploads, fills, validates, screenshots, and closes the
form. Output: `report.md`, `report.json` and screenshots in the (git-ignored) `--out` folder.

## Results (6 live forms)

| Platform | Company | Fields | Filled | Uploaded | Left for you | Consent | Failed | Time |
|---|---|---|---|---|---|---|---|---|
| Ashby | Ramp | 15 | 6 | resume + cover letter | 4 | 2 | 0 | 4.5 s |
| Ashby | Notion | 16 | 6 | resume (no letter asked) | 1 | 0 | 0 | 4.4 s |
| Greenhouse | Duolingo (new-grad form) | 39 | 18 | resume + cover letter | 14 | 0 | 2 | 32 s |
| Greenhouse | GitLab | 19 | 12 | resume + cover letter | 3 | 0 | 0 | 9 s |
| Lever | Palantir | 25 | 12 | resume; letter pasted | 7 | 2 | 1 | 16 s |
| Lever | Spotify | 15 | 6 | resume (no letter asked) | 1 | 1 | 1 | 16 s |

Every upload succeeded. No CAPTCHA challenge was visible while filling; the pages do load
invisible CAPTCHA scripts (reCAPTCHA, hCaptcha), whose hosts this sandbox could not reach,
so whether a challenge appears on submit was not tested. No submission was attempted or
blocked.

**Verified:** discovery (connectors) → application URL per platform → field detection
(labels, ARIA, legends, nearby text, React-select comboboxes, Ashby Yes/No buttons, Lever
custom questions and EEO selects) → uploads (file chips, Lever's resume parse) → answers
(contact, links, country, work authorization and sponsorship Yes/No, "how did you hear",
education, years, EEO decline) → validation → review report and screenshot.

**Left for the person, correctly:** questions about a specific team, office days, a
company's own product, previous employment there, security clearance, GPA, name
pronunciation, technology-specific experience without a reviewed answer, an anti-bot
puzzle (Ramp), AI-notetaker and SMS consent.

**The 4 "failed" fields** (each reported with its reason in the review screen):
- Greenhouse "Location (City)" and Lever "Current location": the platforms' location
  lookups are third-party services this sandbox cannot reach ("Our location service is
  temporarily unavailable"); on a normal connection they return suggestions. Left for the
  user either way.
- Greenhouse "School": the synthetic school is not in Greenhouse's list; a real school
  name is matched against the list.

## Problems found and fixed during validation

| Found on | Problem | Fix |
|---|---|---|
| Greenhouse | Company boards redirect to the company's own site | Use the embeddable form URL, which serves every board |
| Greenhouse | The file input is replaced by a "chip" once a file is attached | Upload check anchors on the field's group container, falls back to the file name |
| Greenhouse | A disabled field (location service down) aborted the run | Per-field errors become a "failed" outcome; only browser crashes abort |
| Greenhouse | A red field label was reported as an error message | Labels are filtered out of page errors |
| Lever | Lever reads the uploaded resume and overwrites name and email | Uploads first, then wait for "Analyzing resume" to finish, then fill |
| Lever | The location box clears on blur unless a suggestion is picked | Lever adapter types without blur and picks the matching suggestion |
| Lever | Required marker inside a wrapping label ("Resume/CV ✱ ATTACH …") | Label cut at the marker, field marked required |
| Lever, Ashby | Declines worded "I do not want to answer" | Decline pattern widened |
| Ashby | Required shown only by a CSS asterisk | Labels styled as required count |
| Ashby | "At least 7 years?" as Yes/No buttons | Total years answer it; a named technology needs that skill's reviewed years |
| Ashby | Location picker: "San Francisco, CA" vs "San Francisco, California, United States" | State abbreviations expanded; city typed, full place picked |
| Greenhouse | Education questions unanswered | Education facts from the resume; "B.S." = "Bachelor's Degree" |
| Lever | Years asked as ranges | The range holding the profile's years is picked |
| GitLab | "…restrictions with your employer?" got the company name | Short facts never answer long or yes/no questions |
| Greenhouse | "Alternative Email" got the same email | Left blank |

## Notes for real use

- **Attaching is uploading.** Greenhouse and Ashby upload an attached file to their
  storage immediately (the validation saw the POSTs to their S3 buckets), before submit.
  Starting a run therefore shares your documents with that company's ATS even if you
  cancel.
- **CAPTCHAs** may appear when submitting; the run detects a visible challenge and returns
  to review. Run with `AUTOMATION_HEADLESS=false` to solve it in the browser window, then
  press Submit again.
