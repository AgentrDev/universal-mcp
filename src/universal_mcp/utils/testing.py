from loguru import logger

from universal_mcp.applications import BaseApplication
from universal_mcp.tools import Tool


def check_application_instance(app_instance: BaseApplication, app_name: str):
    """
    Performs a series of assertions to validate an application instance and its tools.

    This function checks for the following:
    - The application instance is not None.
    - The application instance's name matches the expected application name.
    - The application has at least one tool.
    - Each tool has a non-None name with a valid length (1-47 characters).
    - Each tool has a non-None description.
    - All tool names are unique within the application.
    - The application has at least one tool tagged as "important".

    Args:
        app_instance: The application instance to check. Must be an instance of BaseApplication.
        app_name: The expected name of the application.

    Raises:
        AssertionError: If any of the validation checks fail.
    """
    
    assert app_instance is not None, f"Application object is None for {app_name}"
    assert app_instance.name == app_name, (
        f"Application instance name '{app_instance.name}' does not match expected name '{app_name}'"
    )

    tools = app_instance.list_tools()
    logger.info(f"Tools for {app_name}: {len(tools)}")
    assert len(tools) > 0, f"No tools found for {app_name}"

    tools = [Tool.from_function(tool) for tool in tools]
    seen_names = set()
    important_tools = []

    for tool in tools:
        assert tool.name is not None, f"Tool name is None for a tool in {app_name}"
        assert 0 < len(tool.name) <= 48, (
            f"Tool name '{tool.name}' for {app_name} has invalid length (must be between 1 and 47 characters)"
        )
        assert tool.description is not None, f"Tool description is None for tool '{tool.name}' in {app_name}"
        # assert 0 < len(tool.description) <= 255, f"Tool description for '{tool.name}' in {app_name} has invalid length (must be between 1 and 255 characters)"
        assert tool.name not in seen_names, f"Duplicate tool name: '{tool.name}' found for {app_name}"
        seen_names.add(tool.name)
        if "important" in tool.tags:
            important_tools.append(tool.name)
    assert len(important_tools) > 0, f"No important tools found for {app_name}"
