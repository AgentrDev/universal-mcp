from loguru import logger

from universal_mcp.applications import BaseApplication
from universal_mcp.tools import ToolManager


def check_application_instance(app_instance: BaseApplication, app_name: str):
    """
    Validates a BaseApplication instance and its tools by simulating
    the registration process with a ToolManager. This version is designed
    to work with parametrized tests.

    Args:
        app_instance: An instantiated object of a class that inherits from BaseApplication.
        app_name: The expected name of the application, used for assertions.
    """
    assert app_instance is not None, f"Application object is None for {app_name}"
    assert app_instance.name == app_name, (
        f"Application instance name '{app_instance.name}' does not match expected name '{app_name}' from test."
    )

    tool_manager = ToolManager(warn_on_duplicate_tools=False)
    tool_manager.register_tools_from_app(app_instance, tags=["all"])
    tools = tool_manager.get_tools_by_app(app_name)
    
    logger.info(f"Found {len(tools)} tools for app '{app_name}' after processing.")
    assert len(tools) > 0, f"No tools were registered for app '{app_name}'."
    
    seen_names = set()
    important_tools = []

    for tool in tools:
        assert tool.name is not None, f"Tool name is None for a tool in {app_name}"        
        assert 0 < len(tool.name) <= 128, (
            f"Tool name '{tool.name}' for {app_name} has an invalid length."
        )
        
        assert tool.description, f"Tool description is empty for tool '{tool.name}' in {app_name}"
        assert tool.name not in seen_names, f"Duplicate tool name '{tool.name}' found for {app_name} in the manager."
        seen_names.add(tool.name)

        if "important" in tool.tags:
            important_tools.append(tool.name)

    assert len(important_tools) > 0, f"No tools tagged as 'important' were found for app '{app_name}'."
    logger.success(f"Successfully validated application '{app_name}' and its {len(tools)} tools.")