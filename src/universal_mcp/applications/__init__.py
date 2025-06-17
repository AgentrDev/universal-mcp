from loguru import logger

from universal_mcp.applications.application import (
    APIApplication,
    BaseApplication,
    GraphQLApplication,
)
from universal_mcp.config import AppConfig
from universal_mcp.utils.common import (
    load_app_from_local_file,
    load_app_from_local_folder,
    load_app_from_package,
    load_app_from_remote_file,
    load_app_from_remote_zip,
)

app_cache: dict[str, type[BaseApplication]] = {}


def app_from_config(config: AppConfig) -> type[BaseApplication]:
    """
    Dynamically resolve and return the application class based on AppConfig.
    """
    if config.name in app_cache:
        return app_cache[config.name]

    app_class = None
    try:
        match config.source_type:
            case "package":
                app_class = load_app_from_package(config)
            case "local_folder":
                app_class = load_app_from_local_folder(config)
            case "remote_zip":
                app_class = load_app_from_remote_zip(config)
            case "remote_file":
                app_class = load_app_from_remote_file(config)
            case "local_file":
                app_class = load_app_from_local_file(config)
            case _:
                raise ValueError(f"Unsupported source_type: {config.source_type}")

    except Exception as e:
        logger.error(
            f"Failed to load application '{config.name}' from source '{config.source_type}': {e}",
            exc_info=True,
        )
        raise

    if not app_class:
        raise ImportError(f"Could not load application class for '{config.name}'")

    logger.debug(f"Loaded class '{app_class.__name__}' for app '{config.name}'")
    app_cache[config.name] = app_class
    return app_class


__all__ = [
    "app_from_config",
    "BaseApplication",
    "APIApplication",
    "GraphQLApplication",
]