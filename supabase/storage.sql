-- Supabase Storage bucket for AI Job Hunter's files (run in the SQL editor; safe to
-- re-run: it updates the bucket's settings). Holds uploaded resumes, generated
-- PDF/DOCX resumes and cover letters, and application-form screenshots (PNG).
--
-- The backend uses the service-role key from the server only, so the bucket is
-- PRIVATE and has no public or anonymous access policies: the browser never
-- talks to Supabase Storage directly; downloads go through the API.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'job-hunter',
  'job-hunter',
  false,
  10485760,  -- 10 MB, matches MAX_UPLOAD_MB
  array[
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'image/png'  -- automation screenshots (Phase 8)
  ]
)
on conflict (id) do update
  set public = excluded.public,
      file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;
