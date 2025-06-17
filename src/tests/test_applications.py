import pytest

from universal_mcp.applications import app_from_config
from universal_mcp.config import AppConfig  # <-- Import AppConfig
from universal_mcp.utils.testing import check_application_instance

ALL_APPS = [
    "ahrefs",
    "airtable",
    "aws-s3",
    "apollo",
    "asana",
    "box",
    "braze",
    "cal-com-v2",
    "confluence",
    "calendly",
    "canva",
    # "clickup",
    "coda",
    "crustdata",
    "e2b",
    "elevenlabs",
    "exa",
    "falai",
    "figma",
    "firecrawl",
    "github",
    "gong",
    "google-calendar",
    "google-docs",
    "google-drive",
    "google-gemini",
    "google-mail",
    "google-sheet",
    "hashnode",
    "heygen",
    "hubspot",
    "jira",
    "klaviyo",
    "mailchimp",
    "markitdown",
    "miro",
    "ms-teams",
    "neon",
    "notion",
    "perplexity",
    "pipedrive",
    "posthog",
    "reddit",
    "replicate",
    "resend",
    "retell",
    "rocketlane",
    "serpapi",
    "sharepoint",
    "shopify",
    "shortcut",
    "spotify",
    "supabase",
    "tavily",
    "trello",
    "unipile",
    "whatsapp-business",
    "wrike",
    "youtube",
    "zenquotes",
]


@pytest.mark.parametrize("app_name", ALL_APPS)
def test_application(app_name):
    app_config = AppConfig(name=app_name, source_type="package")
    app_class = app_from_config(app_config)
    app_instance = app_class(integration=None)
    check_application_instance(app_instance, app_name)
