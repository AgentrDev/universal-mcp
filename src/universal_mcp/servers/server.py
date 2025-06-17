from collections.abc import Callable
from typing import Any

from loguru import logger
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from universal_mcp.applications import BaseApplication, app_from_config
from universal_mcp.config import AppConfig, ServerConfig
from universal_mcp.exceptions import ConfigurationError, ToolError
from universal_mcp.integrations import AgentRIntegration, integration_from_config
from universal_mcp.stores import store_from_config
from universal_mcp.tools import ToolManager
from universal_mcp.tools.adapters import ToolFormat, format_to_mcp_result
from universal_mcp.utils.agentr import AgentrClient

# --- Loader Implementations ---


def load_from_local_config(config: ServerConfig, tool_manager: ToolManager) -> None:
    """Load apps and store from local config, register their tools."""
    # Setup store if present
    if config.store:
        try:
            store = store_from_config(config.store)
            tool_manager.add_tool(store.set)
            tool_manager.add_tool(store.delete)
            logger.info(f"Store loaded: {config.store.type}")
        except Exception as e:
            logger.error(f"Failed to setup store: {e}", exc_info=True)
            raise ConfigurationError(f"Store setup failed: {str(e)}") from e

    # Load apps
    if not config.apps:
        logger.warning("No applications configured in local config")
        return

    for app_config in config.apps:
        try:
            integration = None
            if app_config.integration:
                try:
                    integration = integration_from_config(app_config.integration, store=store if config.store else None)
                except Exception as e:
                    logger.error(f"Failed to setup integration for {app_config.name}: {e}", exc_info=True)
            app = app_from_config(app_config)(integration=integration)
            tool_manager.register_tools_from_app(app, app_config.actions)
            logger.info(f"Loaded app: {app_config.name}")
        except Exception as e:
            logger.error(f"Failed to load app {app_config.name}: {e}", exc_info=True)


def load_from_agentr_server(client: AgentrClient, tool_manager: ToolManager) -> None:
    """Load apps from AgentR server and register their tools."""
    try:
        apps = client.fetch_apps()
        for app in apps:
            try:
                app_config = AppConfig.model_validate(app)
                integration = (
                    AgentRIntegration(name=app_config.integration.name, client=client)  # type: ignore
                    if app_config.integration
                    else None
                )
                app_instance = app_from_config(app_config)(integration=integration)
                tool_manager.register_tools_from_app(app_instance, app_config.actions)
                logger.info(f"Loaded app from AgentR: {app_config.name}")
            except Exception as e:
                logger.error(f"Failed to load app from AgentR: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Failed to fetch apps from AgentR: {e}", exc_info=True)
        raise


def load_from_application(app_instance: BaseApplication, tool_manager: ToolManager) -> None:
    """Register all tools from a single application instance."""
    tool_manager.register_tools_from_app(app_instance, tags=["all"])
    logger.info(f"Loaded tools from application: {app_instance.name}")


# --- Server Implementations ---


class BaseServer(FastMCP):
    """Base server for Universal MCP, manages ToolManager and tool invocation."""

    def __init__(self, config: ServerConfig, tool_manager: ToolManager | None = None, **kwargs):
        try:
            super().__init__(config.name, config.description, port=config.port, **kwargs)  # type: ignore
            self.config = config
            self._tool_manager = tool_manager
            ServerConfig.model_validate(config)
        except Exception as e:
            logger.error(f"Failed to initialize server: {e}", exc_info=True)
            raise ConfigurationError(f"Server initialization failed: {str(e)}") from e

    @property
    def tool_manager(self) -> ToolManager:
        if self._tool_manager is None:
            self._tool_manager = ToolManager(warn_on_duplicate_tools=True)
        return self._tool_manager

    def add_tool(self, fn: Callable, name: str | None = None, description: str | None = None) -> None:
        self.tool_manager.add_tool(fn, name)

    async def list_tools(self) -> list:  # type: ignore
        return self.tool_manager.list_tools(format=ToolFormat.MCP)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if not name:
            raise ValueError("Tool name is required")
        if not isinstance(arguments, dict):
            raise ValueError("Arguments must be a dictionary")
        try:
            result = await self.tool_manager.call_tool(name, arguments)
            return format_to_mcp_result(result)
        except Exception as e:
            logger.error(f"Tool '{name}' failed: {e}", exc_info=True)
            raise ToolError(f"Tool execution failed: {str(e)}") from e


class LocalServer(BaseServer):
    """Server that loads apps and store from local config."""

    def __init__(self, config: ServerConfig, **kwargs):
        super().__init__(config, **kwargs)
        self._tools_loaded = False

    @property
    def tool_manager(self) -> ToolManager:
        if self._tool_manager is None:
            self._tool_manager = ToolManager(warn_on_duplicate_tools=True)
        if not getattr(self, "_tools_loaded", False):
            load_from_local_config(self.config, self._tool_manager)
            self._tools_loaded = True
        return self._tool_manager


class AgentRServer(BaseServer):
    """Server that loads apps from AgentR server."""

    def __init__(self, config: ServerConfig, **kwargs):
        super().__init__(config, **kwargs)
        self._tools_loaded = False
        self.api_key = config.api_key.get_secret_value() if config.api_key else None
        self.base_url = config.base_url
        self.client = AgentrClient(api_key=self.api_key, base_url=self.base_url)

    @property
    def tool_manager(self) -> ToolManager:
        if self._tool_manager is None:
            self._tool_manager = ToolManager(warn_on_duplicate_tools=True)
        if not self._tools_loaded:
            load_from_agentr_server(self.client, self._tool_manager)
            self._tools_loaded = True
        return self._tool_manager


class SingleMCPServer(BaseServer):
    """Server for a single, pre-configured application."""

    def __init__(
        self,
        app_instance: BaseApplication,
        config: ServerConfig | None = None,
        **kwargs,
    ):
        config = config or ServerConfig(
            type="local",
            name=f"{app_instance.name.title()} MCP Server for Local Development",
            description=f"Minimal MCP server for the local {app_instance.name} application.",
        )
        super().__init__(config, **kwargs)
        self.app_instance = app_instance
        self._tools_loaded = False

    @property
    def tool_manager(self) -> ToolManager:
        if self._tool_manager is None:
            self._tool_manager = ToolManager(warn_on_duplicate_tools=True)
        if not self._tools_loaded:
            load_from_application(self.app_instance, self._tool_manager)
            self._tools_loaded = True
        return self._tool_manager
