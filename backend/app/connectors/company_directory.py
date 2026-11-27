"""Suggested company boards for quick setup.

Every entry was checked against the live job-board APIs on 2026-11-27.
Companies move between platforms; a suggestion that stops working shows up
as a "not found" crawl status and can simply be removed.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DirectoryEntry:
    source: str
    slug: str
    name: str


DIRECTORY: tuple[DirectoryEntry, ...] = (
    DirectoryEntry("greenhouse", "stripe", "Stripe"),
    DirectoryEntry("greenhouse", "airbnb", "Airbnb"),
    DirectoryEntry("greenhouse", "figma", "Figma"),
    DirectoryEntry("greenhouse", "discord", "Discord"),
    DirectoryEntry("greenhouse", "gitlab", "GitLab"),
    DirectoryEntry("greenhouse", "dropbox", "Dropbox"),
    DirectoryEntry("greenhouse", "databricks", "Databricks"),
    DirectoryEntry("greenhouse", "cloudflare", "Cloudflare"),
    DirectoryEntry("greenhouse", "robinhood", "Robinhood"),
    DirectoryEntry("greenhouse", "reddit", "Reddit"),
    DirectoryEntry("greenhouse", "instacart", "Instacart"),
    DirectoryEntry("greenhouse", "coinbase", "Coinbase"),
    DirectoryEntry("greenhouse", "asana", "Asana"),
    DirectoryEntry("greenhouse", "duolingo", "Duolingo"),
    DirectoryEntry("lever", "spotify", "Spotify"),
    DirectoryEntry("lever", "palantir", "Palantir"),
    DirectoryEntry("lever", "binance", "Binance"),
    DirectoryEntry("ashby", "ramp", "Ramp"),
    DirectoryEntry("ashby", "openai", "OpenAI"),
    DirectoryEntry("ashby", "notion", "Notion"),
    DirectoryEntry("ashby", "linear", "Linear"),
    DirectoryEntry("ashby", "vercel", "Vercel"),
    DirectoryEntry("ashby", "supabase", "Supabase"),
    DirectoryEntry("ashby", "deel", "Deel"),
    DirectoryEntry("ashby", "posthog", "PostHog"),
)
