import inspect
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, Field, create_model

from universal_mcp.exceptions import NotAuthorizedError, ToolError
from universal_mcp.tools.docstring_parser import parse_docstring

from .func_metadata import FuncMetadata


def _get_return_type_schema(return_annotation: Any) -> dict[str, Any] | None:
    """Convert return type annotation to JSON schema using Pydantic."""
    if return_annotation == inspect.Signature.empty or return_annotation == Any:
        return None
    
    try:
        temp_model = create_model(
            "ReturnTypeModel",
            return_value=(return_annotation, ...)
        )
        
        full_schema = temp_model.model_json_schema()
        return_field_schema = full_schema.get("properties", {}).get("return_value")
        
        return return_field_schema
    except Exception:
        return None


class Tool(BaseModel):
    """Internal tool registration info."""

    fn: Callable[..., Any] = Field(exclude=True)
    name: str = Field(description="Name of the tool")
    description: str = Field(description="Summary line from the tool's docstring")
    args_description: dict[str, str] = Field(
        default_factory=dict, description="Descriptions of arguments from the docstring"
    )
    returns_description: str = Field(default="", description="Description of the return value from the docstring")
    raises_description: dict[str, str] = Field(
        default_factory=dict,
        description="Descriptions of exceptions raised from the docstring",
    )
    tags: list[str] = Field(default_factory=list, description="Tags for categorizing the tool")
    parameters: dict[str, Any] = Field(description="JSON schema for tool parameters")
    output_schema: dict[str, Any] | None = Field(default=None, description="JSON schema for tool output")
    fn_metadata: FuncMetadata = Field(
        description="Metadata about the function including a pydantic model for tool arguments"
    )
    is_async: bool = Field(description="Whether the tool is async")

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., Any],
        name: str | None = None,
    ) -> "Tool":
        """Create a Tool from a function."""

        func_name = name or fn.__name__

        if func_name == "<lambda>":
            raise ValueError("You must provide a name for lambda functions")

        raw_doc = inspect.getdoc(fn)
        parsed_doc = parse_docstring(raw_doc)

        is_async = inspect.iscoroutinefunction(fn)

        func_arg_metadata = FuncMetadata.func_metadata(fn, arg_description=parsed_doc["args"])
        parameters = func_arg_metadata.arg_model.model_json_schema()

        sig = inspect.signature(fn)
        output_schema = _get_return_type_schema(sig.return_annotation)

        simple_args_descriptions: dict[str, str] = {}
        if parsed_doc.get("args"):
            for arg_name, arg_details in parsed_doc["args"].items():
                if isinstance(arg_details, dict):
                    simple_args_descriptions[arg_name] = arg_details.get("description") or ""

        return cls(
            fn=fn,
            name=func_name,
            description=parsed_doc["summary"],
            args_description=simple_args_descriptions,
            returns_description=parsed_doc["returns"],
            raises_description=parsed_doc["raises"],
            tags=parsed_doc["tags"],
            parameters=parameters,
            output_schema=output_schema,
            fn_metadata=func_arg_metadata,
            is_async=is_async,
        )

    async def run(
        self,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> Any:
        """Run the tool with arguments."""
        try:
            return await self.fn_metadata.call_fn_with_arg_validation(
                self.fn, self.is_async, arguments, None, context=context
            )
        except NotAuthorizedError as e:
            message = f"Not authorized to call tool {self.name}: {e.message}"
            return message
        except httpx.HTTPStatusError as e:
            error_body = e.response.text or "<empty response>"
            message = f"HTTP Error, status code: {e.response.status_code}, error body: {error_body}"
            raise ToolError(message) from e
        except ValueError as e:
            message = f"Invalid arguments for tool {self.name}: {e}"
            raise ToolError(message) from e
        except Exception as e:
            raise ToolError(f"Error executing tool {self.name}: {e}") from e
