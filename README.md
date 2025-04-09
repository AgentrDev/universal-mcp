# Universal MCP
Universal MCP acts as a middleware layer for your API applications, enabling seamless integration with various services through the Model Context Protocol (MCP). It simplifies credential management, authorization, and dynamic app enablement.

## 🌟 Features

-   **MCP (Model Context Protocol) Integration**: Built upon the `mcp.server.fastmcp` framework for robust server architecture.
-   **Simplified API Integration**: Easily connect to services like GitHub, Google Calendar, Gmail, Reddit, Notion, Firecrawl, E2B, and more via standardized application classes.
-   **Managed Authentication**: Built-in support for API keys (`ApiKeyIntegration`), OAuth (`OAuthIntegration`), and AgentR-managed credentials (`AgentRIntegration`).
-   **Extensible Architecture**: Add new application integrations easily by subclassing `Application` or `APIApplication` and leveraging the dynamic `app_from_slug` loader.
-   **Credential Management**: Flexible storage options for API credentials using in-memory (`MemoryStore`), environment variables (`EnvironmentStore`), or system keyring (`KeyringStore`).

## 🔧 Installation

Install Universal MCP using pip:

```bash
pip install universal-mcp
```

## 🚀 Quick Start

**Important Prerequisite: AgentR API Key (If Using AgentR Integration)**

If you plan to use integrations with `type: "agentr"` (for services like GitHub, Gmail, Notion via the AgentR platform), or if you run the server with `type: "agentr"`, you first need an AgentR API key:

1.  Visit [https://agentr.dev](https://agentr.dev) to create an account and generate an API key from your dashboard.
2.  Set it as an environment variable *before* running the MCP server:
    ```bash
    export AGENTR_API_KEY="your_api_key_here"
    ```

**1. Create a Configuration File (e.g., `config.json`)**

This file defines the server settings, credential stores, and the applications to load with their respective integrations.

```python
{
  "name": "My Local MCP Server",
  "description": "A server for testing applications locally",
  "type": "local",                  # Or "agentr" to load apps dynamically from AgentR
  "transport": "sse",
  "port": 8005,
  "store": {
    "name": "my_mcp_store",
    "type": "keyring"
  },
  "apps": [
    {
      "name": "zenquotes",          # App slug
      "integration": null           # No authentication needed
    },
    {
      "name": "tavily",
      "integration": {
        "name": "TAVILY_API_KEY",   # Unique name for this credential
        "type": "api_key",
        "store": {
          "type": "environment"
        }
      }
    },
    {
      "name": "github",
      "integration": {
        "name": "github",          # Matches the service name in AgentR
        "type": "agentr"           # Uses AgentR platform for auth/creds
      }
    }
  ]
}
```

*Notes:*
*   `type: "local"` runs applications defined directly in the config's `apps` list.
*   `type: "agentr"` connects to the AgentR platform to dynamically load user-enabled apps (ignores the `apps` list in the config) and handle credentials (requires `AGENTR_API_KEY` env var).
*   `store`: Defines credential storage. `environment` looks for `<INTEGRATION_NAME_UPPERCASE>` env var (e.g., `TAVILY_API_KEY`). `keyring` uses the system's secure storage. `memory` is transient.
*   `integration`: Configures authentication for each app when using `type: "local"`. `type: "agentr"` uses the AgentR platform for OAuth/credential management. `type: "api_key"` uses the specified `store`.

**2. Run the Server via CLI**

Make sure any required environment variables (like `TAVILY_API_KEY` for the example above, or `AGENTR_API_KEY` if using `"agentr"` type server/integrations) are set.

```bash
universal_mcp run -c config.json
```

The server will start, load the configured applications (or connect to AgentR if `type: "agentr"`), and listen for connections based on the `transport` type (`sse`, `stdio`, or `http`).

## 🛠️ Using Playground

The `playground` directory provides a runnable example with a FastAPI backend and a Streamlit frontend for interacting with the MCP server.

**Prerequisites:**

*   Ensure `local_config.json` exists in the project root directory. See `src/playground/README.md` for its format. This configures the *local* MCP server that the playground backend connects to.
*   Install playground dependencies if needed (e.g., `fastapi`, `streamlit`, `uvicorn`, `langchain`, etc.).

**Running the Playground:**

The easiest way is to use the automated startup script from the **project root directory**:

```bash
python src/playground
```
Refer to `src/playground/README.md` for more detailed setup and usage instructions.

## 🧩 Available Applications

Universal MCP comes with several pre-built applications:

| Application Slug | Description                              | Authentication Type                       |
| :--------------- | :--------------------------------------- | :---------------------------------------- |
| `e2b`            | Execute Python code in secure sandboxes  | API Key (via Integration)                 |
| `firecrawl`      | Scrape/crawl web pages, search           | API Key (via Integration)                 |
| `github`         | Interact with GitHub repos, issues, PRs  | OAuth (AgentR)                            |
| `google-calendar`| Manage Google Calendar events            | OAuth (AgentR)                            |
| `google-mail`    | Read and send Gmail emails               | OAuth (AgentR)                            |
| `markitdown`     | Convert web pages/files to Markdown      | None                                      |
| `notion`         | Interact with Notion pages/databases     | OAuth (AgentR)                            |
| `reddit`         | Interact with Reddit posts/comments      | OAuth (AgentR)                            |
| `resend`         | Send emails via Resend API               | API Key (via Integration)                 |
| `serp`           | Perform web searches via SerpApi         | API Key (via Integration)                 |
| `tavily`         | Advanced web search & research API       | API Key (via Integration)                 |
| `zenquotes`      | Get inspirational quotes                 | None                                      |

*Authentication Type notes:*
*   *OAuth (AgentR)*: Typically requires configuring the integration with `type: "agentr"` in your `ServerConfig`. Requires the `AGENTR_API_KEY`.
*   *API Key (via Integration)*: Requires configuring `type: "api_key"` and a `store` (like `environment` or `keyring`) in your `ServerConfig`.

## 🔐 Integration Types

Universal MCP supports different ways to handle authentication for applications:

### 1. API Key Integration

For services that authenticate via simple API keys. Configure using `IntegrationConfig` with `type: "api_key"`.

```python
{
  "name": "tavily",
  "integration": {
    "name": "TAVILY_API_KEY",
    "type": "api_key",
    "store": {
      "name": "universal_mcp",
      "type": "environment"   # Or "keyring", "memory"
       }
    } 
}
```

### 2. AgentR Integration

For services integrated with the AgentR platform, typically handling OAuth flows or centrally managed credentials. Configure using `IntegrationConfig` with `type: "agentr"`. Requires the `AGENTR_API_KEY` environment variable to be set for the MCP server process.

```python
{
  "name": "github",
  "integration": {
    "name": "github", # Matches the service name configured in AgentR
    "type": "agentr"
  }
}
```
When an action requiring authorization is called, the `AgentRIntegration` will prompt the user (via the MCP client) to visit a URL to complete the OAuth flow managed by AgentR. This is also the default integration type when using `type: "agentr"` for the main server config.

### 3. OAuth Integration (Direct - Less Common)

While `AgentRIntegration` is preferred for OAuth, a direct `OAuthIntegration` class exists but requires manual configuration of client IDs, secrets, and handling callbacks, which is generally more complex to set up outside the AgentR platform.

## 🤖 CLI Usage

Universal MCP includes a command-line interface:

```bash
# Run the MCP server using a configuration file
universal_mcp run -c config.json

# Generate API client code and application structure from an OpenAPI schema
# Output file name (e.g., 'twitter.py') determines app name ('twitter')
universal_mcp generate --schema <path_to_schema.json/yaml> --output <path/to/output_app_name.py> [--no-docstrings]

# Generate Google-style docstrings for functions in a Python file using an LLM
universal_mcp docgen <path/to/file.py> [--model <model_name>] [--api-key <llm_api_key>]

# Install MCP configuration for supported desktop apps (Claude, Cursor)
# Requires AgentR API key for configuration.
universal_mcp install claude
universal_mcp install cursor

# Check installed version (standard typer command)
universal_mcp --version
```

## 📋 Requirements

-   Python 3.11+
-   Dependencies (installed automatically via pip):
    -   `mcp-server`
    -   `loguru`
    -   `typer`
    -   `httpx`
    -   `pydantic`
    -   `pyyaml`
    -   `keyring` (optional, for `KeyringStore`)
    -   `litellm` (optional, for `docgen` command)
    -   ... and others specific to certain applications.

## 📝 License

This project is licensed under the MIT License.