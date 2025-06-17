import pytest

from universal_mcp.applications import app_from_config
from universal_mcp.config import AppConfig  # <-- Import the AppConfig model
from universal_mcp.exceptions import NotAuthorizedError
from universal_mcp.integrations import ApiKeyIntegration
from universal_mcp.stores import MemoryStore


def test_perplexity_api_no_key():
    store = MemoryStore()

    integration = ApiKeyIntegration("PERPLEXITY", store=store)
    perplexity_app_config = AppConfig(name="perplexity")
    PerplexityApp = app_from_config(perplexity_app_config)

    app = PerplexityApp(integration=integration)

    with pytest.raises(NotAuthorizedError) as exc_info:
        app.chat("Hello, how are you?")

    assert "Please ask the user for api key" in str(exc_info.value)
    assert "PERPLEXITY_API_KEY" in str(exc_info.value)