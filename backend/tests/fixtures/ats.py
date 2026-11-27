"""Mock Greenhouse, Lever and Ashby application forms for browser tests.

The pages copy the structure of the live forms (checked on 2026-11-27): how
labels, ARIA, required markers, React-select comboboxes, Yes/No buttons, file
"chips" and Lever's resume parsing behave. They are served to a real Chromium
through Playwright request routing at the real hosts, so adapters and URLs are
exercised unchanged; nothing leaves the machine.

`MockATS.posts` records every submission the pages send; a test can prove
nothing was submitted before the user confirmed. `MockATS.scenario` switches a
platform's behaviour: "ok", "reject", "captcha", "silent", "closed",
"changed", "upload_error", "reload".
"""

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

GH_HOST, LEVER_HOST, ASHBY_HOST = "job-boards.greenhouse.io", "jobs.lever.co", "jobs.ashbyhq.com"
MOCK_HOSTS = (GH_HOST, LEVER_HOST, ASHBY_HOST)

COMMON_JS = r"""
<script>
const SCENARIO = '__SCENARIO__';
const PLATFORM = '__PLATFORM__';
function data() {
  const out = {};
  for (const el of document.querySelectorAll('input,select,textarea')) {
    if (el.type === 'file') { out[el.name || el.id] = [...(el.files || [])].map(f => f.name); continue; }
    if ((el.type === 'radio' || el.type === 'checkbox') && !el.checked) continue;
    const k = el.name || el.id; if (!k) continue;
    out[k] = el.value;
  }
  for (const v of document.querySelectorAll('[data-value-for]')) out[v.dataset.valueFor] = v.textContent;
  for (const c of document.querySelectorAll('[data-file-for]')) out[c.dataset.fileFor] = [c.textContent];
  for (const b of document.querySelectorAll('button[aria-pressed=true]')) out[b.dataset.q] = b.textContent;
  return out;
}
function showError(msg) {
  let box = document.getElementById('form-error');
  if (!box) { box = document.createElement('div'); box.id = 'form-error'; box.setAttribute('role', 'alert');
    box.className = 'error'; document.body.prepend(box); }
  box.textContent = msg;
}
async function submitApp(required) {
  const d = data();
  const empty = required.filter(k => !d[k] || (Array.isArray(d[k]) && !d[k].length));
  if (empty.length) { showError('Please fill in all required fields: ' + empty.join(', ')); return; }
  if (SCENARIO === 'captcha') {
    const f = document.createElement('iframe');
    f.src = 'https://www.google.com/recaptcha/api2/bframe?k=test';
    f.style = 'width:400px;height:500px;display:block;border:1px solid #ccc';
    document.body.appendChild(f); return;
  }
  if (SCENARIO === 'silent') return;
  if (SCENARIO === 'reject') { showError('There was a problem with your submission. Please check your answers.'); return; }
  await fetch('/__submit', {method: 'POST', body: JSON.stringify({platform: PLATFORM, data: d})});
  if (PLATFORM === 'lever') { location.href = location.pathname.replace('/apply', '/thanks'); return; }
  if (PLATFORM === 'greenhouse') { location.href = '/embed/job_app/confirmation'; return; }
  document.querySelector('.ashby-application-form-container').innerHTML =
    '<h2>Application submitted</h2><p>Thank you for applying to Acme.</p>';
}
// React-select style combobox: options appear in a listbox while typing.
function combobox(input, options) {
  const box = input.closest('.select-shell');
  const shown = box.querySelector('[data-value-for]');
  let list = null;
  const close = () => { if (list) { list.remove(); list = null; } input.setAttribute('aria-expanded', 'false'); };
  const open = () => {
    close();
    const q = input.value.toLowerCase();
    const hits = options.filter(o => !q || o.toLowerCase().includes(q));
    list = document.createElement('div'); list.setAttribute('role', 'listbox'); list.className = 'menu';
    for (const o of hits) {
      const opt = document.createElement('div'); opt.setAttribute('role', 'option'); opt.textContent = o;
      opt.className = 'option';
      opt.addEventListener('mousedown', e => { e.preventDefault(); shown.textContent = o; input.value = '';
        const helper = box.querySelector('.req-helper'); if (helper) helper.value = o; close(); });
      list.appendChild(opt);
    }
    box.appendChild(list); input.setAttribute('aria-expanded', 'true');
  };
  input.addEventListener('input', open);
  input.addEventListener('keydown', e => { if (e.key === 'ArrowDown') open(); if (e.key === 'Escape') close(); });
  input.addEventListener('blur', () => setTimeout(close, 150));
}
// File input that turns into a "chip" with the file name (Greenhouse/Ashby).
function fileChip(input, key) {
  input.addEventListener('change', () => {
    const f = input.files[0]; if (!f) return;
    const holder = input.closest('[data-upload]');
    if (SCENARIO === 'upload_error') {
      const err = document.createElement('p'); err.className = 'error'; err.setAttribute('role', 'alert');
      err.textContent = 'Upload failed: please try again.'; holder.appendChild(err); return;
    }
    setTimeout(() => {
      holder.querySelector('.wrapper').outerHTML =
        '<div class="chip"><p data-file-for="' + key + '">' + f.name + '</p><button type="button" aria-label="Remove file">x</button></div>';
    }, 120);
  });
}
</script>
"""

GREENHOUSE = r"""<!doctype html><html><head><title>Senior Engineer - Acme</title>
<style>.visually-hidden{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.req-helper{opacity:0;width:1px;height:1px;position:absolute} .menu{border:1px solid #999}</style></head>
<body>__COMMON__
<h1>Senior Software Engineer</h1>
<form id="application-form" onsubmit="event.preventDefault(); submitApp(['first_name','last_name','email','country','resume','question_2','question_4','question_5'])">
 <div class="field"><label for="first_name">First Name<span class="required">*</span></label><input id="first_name" type="text" aria-required="true"></div>
 <div class="field"><label for="last_name">Last Name<span class="required">*</span></label><input id="last_name" type="text" aria-required="true"></div>
 <div class="field"><label for="email">Email<span class="required">*</span></label><input id="email" type="text" aria-required="true"></div>
 <div class="field"><label id="country-label" for="country">Country<span class="required">*</span></label>
   <div class="select-shell"><div class="control"><div class="select__single-value" data-value-for="country"></div><input id="country" role="combobox" aria-autocomplete="list" aria-labelledby="country-label" aria-required="true"></div><input class="req-helper" tabindex="-1" required></div></div>
 <div class="field"><label for="phone">Phone</label><input id="phone" type="tel"></div>
 <div role="group" aria-labelledby="upload-label-resume" class="file-upload" data-upload>
   <div id="upload-label-resume" class="label upload-label">Resume/CV<span class="required">*</span></div>
   <div class="wrapper"><button type="button">Attach</button><label class="visually-hidden" for="resume">Attach</label><input id="resume" class="visually-hidden" type="file" accept=".pdf,.doc,.docx"><button type="button">Enter manually</button></div>
 </div>
 <div role="group" aria-labelledby="upload-label-cover" class="file-upload" data-upload>
   <div id="upload-label-cover" class="label upload-label">Cover Letter</div>
   <div class="wrapper"><button type="button">Attach</button><label class="visually-hidden" for="cover_letter">Attach</label><input id="cover_letter" class="visually-hidden" type="file" accept=".pdf,.doc,.docx"></div>
 </div>
 <div class="field"><label for="question_1">LinkedIn Profile</label><input id="question_1" type="text"></div>
 <div class="field"><label for="question_2">Which team are you most interested in?<span class="required">*</span></label><input id="question_2" type="text" aria-required="true"></div>
 <fieldset><legend>Which offices could you work from? (select all that apply)</legend>
   <label><input type="checkbox" name="question_3[]" value="ny"> New York, NY</label>
   <label><input type="checkbox" name="question_3[]" value="sf"> San Francisco, CA</label></fieldset>
 <div class="field"><label id="q4-label" for="question_4">Are you authorized to work lawfully in the United States?<span class="required">*</span></label>
   <div class="select-shell"><div class="control"><div class="select__single-value" data-value-for="question_4"></div><input id="question_4" role="combobox" aria-autocomplete="list" aria-labelledby="q4-label" aria-required="true" placeholder="Select..."></div></div></div>
 <div class="field"><label id="q5-label" for="question_5">Will you now, or in the future, require sponsorship (e.g. H-1B visa)?<span class="required">*</span></label>
   <div class="select-shell"><div class="control"><div class="select__single-value" data-value-for="question_5"></div><input id="question_5" role="combobox" aria-autocomplete="list" aria-labelledby="q5-label" aria-required="true" placeholder="Select..."></div></div></div>
 <div class="field"><label id="q6-label" for="question_6">Where did you hear about this job?</label>
   <div class="select-shell"><div class="control"><div class="select__single-value" data-value-for="question_6"></div><input id="question_6" role="combobox" aria-autocomplete="list" aria-labelledby="q6-label" placeholder="Select..."></div></div></div>
 <div class="field"><label id="g-label" for="gender">How would you describe your gender identity?</label>
   <div class="select-shell"><div class="control"><div class="select__single-value" data-value-for="gender"></div><input id="gender" role="combobox" aria-autocomplete="list" aria-labelledby="g-label" placeholder="Select..."></div></div></div>
 <button type="submit">Submit application</button>
</form>
<script>
combobox(document.getElementById('country'), ['United States +1', 'United Kingdom +44', 'Canada +1']);
combobox(document.getElementById('question_4'), ['Yes', 'No']);
combobox(document.getElementById('question_5'), ['Yes', 'No']);
combobox(document.getElementById('question_6'), ['LinkedIn', 'Acme Careers Page', 'Referral', 'Other']);
combobox(document.getElementById('gender'), ['Man', 'Woman', 'Non-binary', "I don't wish to answer"]);
fileChip(document.getElementById('resume'), 'resume');
fileChip(document.getElementById('cover_letter'), 'cover_letter');
if (SCENARIO === 'reload' && !sessionStorage.getItem('reloaded')) {
  sessionStorage.setItem('reloaded', '1');
  document.getElementById('question_1').addEventListener('input', () => location.reload(), {once: true});
}
</script></body></html>"""

GREENHOUSE_CONFIRMATION = """<!doctype html><html><body><h1>Thank you for applying.</h1>
<p>Your application has been received.</p></body></html>"""

LEVER = r"""<!doctype html><html><head><title>Acme - Senior Engineer</title>
<style>.hidden{display:none} .dropdown-location{padding:4px;cursor:pointer}</style></head><body>__COMMON__
<form id="application-form" class="application-form" onsubmit="event.preventDefault(); submitApp(['resume','name','email','location','cards[a][field0]','cards[c][field0]'])">
 <h4>Submit your application</h4><ul>
 <li class="application-question resume"><label><div class="application-label">Resume/CV <span class="required">&#10033;</span></div>
   <div class="application-field"><a class="postings-btn">ATTACH RESUME/CV</a><input type="file" name="resume" id="resume-upload-input" style="opacity:0;position:absolute;width:1px"></div>
   <span class="filename" data-upload></span><span class="resume-analyzing hidden">Analyzing resume...</span><span class="hidden">Couldn't auto-read resume.</span></label></li>
 <li class="application-question"><label><div class="application-label">Full name <span class="required">&#10033;</span></div><div class="application-field"><input type="text" name="name" required></div></label></li>
 <li class="application-question"><label><div class="application-label">Email <span class="required">&#10033;</span></div><div class="application-field"><input type="email" name="email" required></div></label></li>
 <li class="application-question"><label><div class="application-label">Phone</div><div class="application-field"><input type="text" name="phone"></div></label></li>
 <li class="application-question"><label><div class="application-label">Current location <span class="required">&#10033;</span></div><div class="application-field"><input type="text" name="location" id="location-input" autocomplete="off" required>
   <div class="dropdown-results"></div><div class="dropdown-no-results hidden">No location found. Try entering a different location</div></div></label></li>
 <li class="application-question"><label><div class="application-label">Current company</div><div class="application-field"><input type="text" name="org"></div></label></li>
 <li class="application-question"><label><div class="application-label">LinkedIn URL</div><div class="application-field"><input type="text" name="urls[LinkedIn]"></div></label></li>
 </ul>
 <div class="application-question custom-question"><div class="application-label">Are you legally authorized to work in the country for which you are applying? <span class="required">&#10033;</span></div>
   <ul><li><label><input type="radio" name="cards[a][field0]" value="Yes" required> Yes</label></li><li><label><input type="radio" name="cards[a][field0]" value="No"> No</label></li></ul></div>
 <div class="application-question custom-question"><div class="application-label">Please tell us how you heard about this opportunity.</div>
   <select name="cards[b][field0]"><option value="">Select ...</option><option>Job Board (Indeed, Monster, etc.)</option><option>Acme Website</option><option>Referral</option></select></div>
 <div class="application-question custom-question"><div class="application-label">Why do you want to work at Acme?</div><textarea name="cards[d][field0]"></textarea></div>
 <div class="application-question custom-question"><div class="application-label">We may use AI notetakers in interviews. <span class="required">&#10033;</span></div>
   <ul><li><label><input type="radio" name="cards[c][field0]" value="Yes" required> Yes, I consent</label></li><li><label><input type="radio" name="cards[c][field0]" value="No"> No, I do not consent</label></li></ul></div>
 <div class="application-question"><div class="application-label">Additional information</div><textarea name="comments" placeholder="Add a cover letter or anything else you want to share."></textarea></div>
 <div class="application-question"><div class="application-label">Veteran status</div><select name="eeo[veteran]"><option value="">Select ...</option><option>I am a veteran</option><option>I am not a veteran</option><option>I don't wish to answer</option></select></div>
 <button type="submit" id="btn-submit">Submit application</button>
</form>
<script>
const resume = document.getElementById('resume-upload-input');
resume.addEventListener('change', () => {
  const f = resume.files[0]; if (!f) return;
  if (SCENARIO === 'upload_error') { const e = document.createElement('div'); e.className = 'error-message';
    e.setAttribute('role', 'alert'); e.textContent = 'Upload failed: file is too large.';
    resume.closest('li').appendChild(e); return; }
  document.querySelector('.filename').textContent = f.name;
  const busy = document.querySelector('.resume-analyzing'); busy.classList.remove('hidden');
  // Lever reads the resume and fills fields from it; later values must win.
  setTimeout(() => { document.querySelector('[name=name]').value = 'Parsed From Resume';
    document.querySelector('[name=email]').value = 'parsed@example.com'; busy.classList.add('hidden'); }, 700);
});
const loc = document.getElementById('location-input');
const results = document.querySelector('.dropdown-results');
let picked = false;
loc.addEventListener('input', () => {
  picked = false; results.innerHTML = '';
  if (loc.value.length >= 3) {
    const typed = loc.value.split(',')[0];
    const hits = typed.toLowerCase() === 'nowhere' ? [] : [loc.value + ', United States', typed + ', Cordoba, Argentina'];
    for (const t of hits) {
      const d = document.createElement('div'); d.className = 'dropdown-location'; d.textContent = t;
      d.addEventListener('mousedown', e => { e.preventDefault(); loc.value = t; picked = true; results.innerHTML = ''; });
      results.appendChild(d);
    }
  }
});
loc.addEventListener('blur', () => setTimeout(() => { if (!picked) loc.value = ''; }, 100));
</script></body></html>"""

LEVER_THANKS = """<!doctype html><html><body><h2>Application submitted!</h2>
<p>Thanks for applying to Acme.</p></body></html>"""

ASHBY = r"""<!doctype html><html><head><title>Acme Jobs</title>
<style>._required::after{content:'*';color:red} .selected{background:#333;color:#fff}</style></head><body>__COMMON__
<div class="ashby-application-form-container">
 <div class="_autofill"><p>Autofill from resume</p><p>Upload your resume here to autofill key application fields.</p><input type="file"></div>
 <div class="_fieldEntry"><label for="_systemfield_name" class="_label _required">Name</label><input id="_systemfield_name" name="_systemfield_name" placeholder="Type here..."></div>
 <div class="_fieldEntry"><label for="_systemfield_email" class="_label _required">Email</label><input id="_systemfield_email" name="_systemfield_email" type="email" placeholder="hello@example.com..."></div>
 <div class="_fieldEntry"><label for="phone-1" class="_label">Phone</label><input id="phone-1" name="phone-1" type="tel"></div>
 <div class="_fieldEntry" data-upload><label for="_systemfield_resume" class="_label _required">Resume</label>
   <div class="wrapper"><button type="button">Upload File</button><input id="_systemfield_resume" type="file" style="display:none"><p>or drag and drop here</p></div></div>
 <div class="_fieldEntry" data-upload><label for="cover-1" class="_label">Cover Letter</label>
   <div class="wrapper"><button type="button">Upload File</button><input id="cover-1" type="file" style="display:none"></div></div>
 <div class="_fieldEntry"><label class="_label _required">Do you have at least 5 years of experience building software?</label>
   <div class="_container _yesno"><div><button type="button" data-q="yn1">Yes</button><button type="button" data-q="yn1">No</button></div><input type="checkbox" name="yn1" style="display:none"></div></div>
 <div class="_fieldEntry"><label class="_label">Do you have at least 5 years of experience with Kubernetes?</label>
   <div class="_container _yesno"><div><button type="button" data-q="yn2">Yes</button><button type="button" data-q="yn2">No</button></div><input type="checkbox" name="yn2" style="display:none"></div></div>
 <div class="_fieldEntry"><label class="_label">Where do you plan on working from?</label>
   <div class="select-shell"><div class="select__single-value" data-value-for="workplace"></div><input role="combobox" aria-autocomplete="list" placeholder="Start typing..."></div></div>
 <div class="_fieldEntry"><label for="q-aws" class="_label _required">Please elaborate on your experience building software in AWS</label><textarea id="q-aws" name="q-aws" placeholder="Type here..."></textarea></div>
 <button type="button" class="submit" onclick="submitApp(['_systemfield_name','_systemfield_email','_systemfield_resume','yn1','q-aws'])">Submit Application</button>
</div>
<script>
for (const btn of document.querySelectorAll('._yesno button')) {
  btn.addEventListener('click', () => {
    for (const b of btn.parentElement.querySelectorAll('button')) { b.setAttribute('aria-pressed', 'false'); b.classList.remove('selected'); }
    btn.setAttribute('aria-pressed', 'true'); btn.classList.add('selected');
  });
}
combobox(document.querySelector('.select-shell input'), ['San Francisco, CA, United States', 'New York, NY, United States', 'Remote (US)']);
fileChip(document.getElementById('_systemfield_resume'), '_systemfield_resume');
fileChip(document.getElementById('cover-1'), 'cover-1');
</script></body></html>"""

CLOSED = """<!doctype html><html><body><h1>Senior Engineer</h1>
<p>Sorry, this job is no longer accepting applications.</p></body></html>"""
CHANGED = (
    """<!doctype html><html><body><h1>Apply</h1><div id="app">Loading...</div></body></html>"""
)


@dataclass
class MockATS:
    scenario: dict[str, str] = field(default_factory=dict)
    posts: list[dict[str, Any]] = field(default_factory=list)
    pages_served: list[str] = field(default_factory=list)
    fail_next: int = 0  # abort this many page loads (a flaky network)

    def set(self, platform: str, scenario: str) -> None:
        self.scenario[platform] = scenario

    def page(self, platform: str, url: str) -> tuple[int, str]:
        path = urlparse(url).path
        scenario = self.scenario.get(platform, "ok")
        if scenario == "closed":
            return 200, CLOSED
        if scenario == "changed":
            return 200, CHANGED
        if platform == "greenhouse":
            body = GREENHOUSE_CONFIRMATION if path.endswith("/confirmation") else GREENHOUSE
        elif platform == "lever":
            body = LEVER_THANKS if path.endswith("/thanks") else LEVER
        else:
            body = ASHBY
        common = COMMON_JS.replace("__SCENARIO__", scenario).replace("__PLATFORM__", platform)
        return 200, body.replace("__COMMON__", common)

    async def hook(self, context: Any) -> None:
        """BrowserManager context hook: serve the mock hosts, block the rest."""
        platforms = {GH_HOST: "greenhouse", LEVER_HOST: "lever", ASHBY_HOST: "ashby"}

        async def handle(route: Any) -> None:
            request = route.request
            host = urlparse(request.url).hostname or ""
            if host not in platforms:
                await route.abort()  # e.g. the CAPTCHA frame: never reach the internet
                return
            if request.method == "POST" and urlparse(request.url).path == "/__submit":
                self.posts.append(json.loads(request.post_data or "{}"))
                await route.fulfill(status=200, content_type="application/json", body="{}")
                return
            if self.fail_next > 0 and request.resource_type == "document":
                self.fail_next -= 1
                await route.abort("connectionreset")
                return
            self.pages_served.append(request.url)
            status, body = self.page(platforms[host], request.url)
            await route.fulfill(status=status, content_type="text/html", body=body)

        await context.route("**/*", handle)


GH_URL = "https://job-boards.greenhouse.io/embed/job_app?for=acme&token=4001"
LEVER_URL = "https://jobs.lever.co/acme/aaaa-1111/apply"
ASHBY_URL = "https://jobs.ashbyhq.com/acme/bbbb-2222/application"
