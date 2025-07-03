from enum import Enum

from loguru import logger
from mcp.types import TextContent

from universal_mcp.tools.tools import Tool


class ToolFormat(str, Enum):
    """Supported tool formats."""

    MCP = "mcp"
    LANGCHAIN = "langchain"
    OPENAI = "openai"


def convert_tool_to_mcp_tool(
    tool: Tool,
):
    from mcp.server.fastmcp.server import MCPTool

    logger.debug(f"Converting tool '{tool.name}' to MCP format")
    mcp_tool = MCPTool(
        name=tool.name[:63],
        description=tool.description or "",
        inputSchema=tool.parameters,
        outputSchema=tool.output_schema,
    )
    logger.debug(f"Successfully converted tool '{tool.name}' to MCP format")
    return mcp_tool


def format_to_mcp_result(result: any) -> list[TextContent]:
    """Format tool result into TextContent list.

    Args:
        result: Raw tool result

    Returns:
        List of TextContent objects
    """
    logger.debug(f"Formatting result to MCP format, type: {type(result)}")
    if isinstance(result, str):
        logger.debug("Result is string, wrapping in TextContent")
        return [TextContent(type="text", text=result)]
    elif isinstance(result, list) and all(isinstance(item, TextContent) for item in result):
        logger.debug("Result is already list of TextContent objects")
        return result
    else:
        logger.warning(f"Tool returned unexpected type: {type(result)}. Wrapping in TextContent.")
        return [TextContent(type="text", text=str(result))]


def convert_tool_to_langchain_tool(
    tool: Tool,
):
    from langchain_core.tools import StructuredTool

    """Convert an tool to a LangChain tool.

    NOTE: this tool can be executed only in a context of an active MCP client session.

    Args:
        tool: Tool to convert

    Returns:
        a LangChain tool
    """

    logger.debug(f"Converting tool '{tool.name}' to LangChain format")

    async def call_tool(
        **arguments: dict[str, any],
    ):
        logger.debug(f"Executing LangChain tool '{tool.name}' with arguments: {arguments}")
        call_tool_result = await tool.run(arguments)
        logger.debug(f"Tool '{tool.name}' execution completed")
        return call_tool_result

    langchain_tool = StructuredTool(
        name=tool.name,
        description=tool.description or "",
        coroutine=call_tool,
        response_format="content",
        args_schema=tool.parameters,
    )
    logger.debug(f"Successfully converted tool '{tool.name}' to LangChain format")
    return langchain_tool


def convert_tool_to_openai_tool(
    tool: Tool,
):
    """Convert a Tool object to an OpenAI function."""
    logger.debug(f"Converting tool '{tool.name}' to OpenAI format")
    openai_tool = {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
    logger.debug(f"Successfully converted tool '{tool.name}' to OpenAI format")
    return openai_tool


def transform_mcp_tool_to_openai_tool(mcp_tool: Tool):
    """Convert an MCP tool to an OpenAI tool."""
    from openai.types import FunctionDefinition
    from openai.types.chat import ChatCompletionToolParam

    return ChatCompletionToolParam(
        type="function",
        function=FunctionDefinition(
            name=mcp_tool.name,
            description=mcp_tool.description or "",
            parameters=mcp_tool.inputSchema,
            strict=False,
        ),
    )
