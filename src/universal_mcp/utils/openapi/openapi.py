import hashlib
import json
import re
import textwrap
from keyword import iskeyword
from pathlib import Path
from typing import Any, Literal

import yaml
from jsonref import replace_refs
from pydantic import BaseModel

from .filters import load_filter_config, should_process_operation

# Schema registry for tracking unique response schemas to avoid duplicates
_schema_registry: dict[str, str] = {}  # schema_hash -> model_class_name
_generated_models: dict[str, str] = {}  # model_class_name -> model_source_code


def _get_schema_hash(schema: dict[str, Any]) -> str:
    """Generate a hash for a schema to identify unique schemas."""
    try:
        schema_str = json.dumps(schema, sort_keys=True, default=str)
        return hashlib.md5(schema_str.encode()).hexdigest()[:8]
    except (TypeError, ValueError):
        # Fallback to string representation if JSON serialization fails
        schema_str = str(sorted(schema.items())) if isinstance(schema, dict) else str(schema)
        return hashlib.md5(schema_str.encode()).hexdigest()[:8]


def _generate_model_name(operation: dict[str, Any], path: str, method: str, schema: dict[str, Any]) -> str:
    """Generate a meaningful model name for a response schema."""
    if "title" in schema:
        name = schema["title"]
    else:
        # Generate name from operation info
        if "operationId" in operation:
            name = operation["operationId"] + "Response"
        else:
            # Generate from path and method
            path_parts = [part for part in path.strip("/").split("/") if not (part.startswith("{") and part.endswith("}"))]
            if path_parts:
                name = f"{method.capitalize()}{path_parts[-1].capitalize()}Response"
            else:
                name = f"{method.capitalize()}Response"
    
    name = "".join(word.capitalize() for word in re.split(r"[^a-zA-Z0-9]", name) if word)
    
    if name and name[0].isdigit():
        name = "Response" + name
    
    return name or "Response"


def _generate_response_model_class(schema: dict[str, Any], model_name: str) -> str:
    """Generate Pydantic model source code from OpenAPI response schema."""
    if not schema:
        return ""
    
    # Handle array responses
    if schema.get("type") == "array":
        items_schema = schema.get("items", {})
        if items_schema and (items_schema.get("properties") or items_schema.get("type") == "object"):
            # Generate model for array items if it's an object
            item_model_name = f"{model_name}Item"
            item_model_code = _generate_response_model_class(items_schema, item_model_name)
            
            # Create collection model
            collection_model = f"""
class {model_name}(BaseModel):
    value: List[{item_model_name}]
"""
            return item_model_code + collection_model
        else:
            # Fallback for arrays with simple items or no schema
            item_type = "Any"
            if items_schema:
                if items_schema.get("type") == "string":
                    item_type = "str"
                elif items_schema.get("type") == "integer":
                    item_type = "int"
                elif items_schema.get("type") == "number":
                    item_type = "float"
                elif items_schema.get("type") == "boolean":
                    item_type = "bool"
            
            return f"""
class {model_name}(BaseModel):
    value: List[{item_type}]
"""
    
    # Handle object responses
    if schema.get("type") == "object" or "properties" in schema:
        properties, required_fields = _extract_properties_from_schema(schema)
        
        if not properties:
            return f"""
class {model_name}(BaseModel):
    pass
"""
        
        field_definitions = []
        for prop_name, prop_schema in properties.items():
            field_name = _sanitize_identifier(prop_name)
            is_required = prop_name in required_fields
            
            # Handle arrays with object items specially
            if prop_schema.get("type") == "array" and prop_schema.get("items", {}).get("properties"):
                # Generate a model for the array items
                item_model_name = f"{model_name}{field_name.capitalize()}Item"
                items_schema = prop_schema.get("items", {})
                
                # Generate the item model and store it globally
                item_model_code = _generate_response_model_class(items_schema, item_model_name)
                if item_model_code and item_model_name not in _generated_models:
                    _generated_models[item_model_name] = item_model_code
                
                python_type = f"List[{item_model_name}]" if is_required else f"Optional[List[{item_model_name}]]"
            else:
                python_type = _openapi_type_to_python_type(prop_schema, required=is_required)
            
            # Handle field aliases for special characters like @odata.context
            if prop_name != field_name or prop_name.startswith('@'):
                if is_required:
                    field_definitions.append(f"    {field_name}: {python_type} = Field(alias='{prop_name}')")
                else:
                    field_definitions.append(f"    {field_name}: {python_type} = Field(None, alias='{prop_name}')")
            else:
                if is_required:
                    field_definitions.append(f"    {field_name}: {python_type}")
                else:
                    field_definitions.append(f"    {field_name}: {python_type} = None")
        
        model_code = f"""
class {model_name}(BaseModel):
{chr(10).join(field_definitions)}
"""
        return model_code
    
    # Fallback for other schema types
    return ""


def _get_or_create_response_model(operation: dict[str, Any], path: str, method: str, schema: dict[str, Any]) -> str | None:
    """Get or create a response model for a given schema, avoiding duplicates."""
    if not schema:
        return None
    
    try:
        # Generate hash for this schema
        schema_hash = _get_schema_hash(schema)
        
        # Check if we already have a model for this schema
        if schema_hash in _schema_registry:
            return _schema_registry[schema_hash]
        
        # Generate new model
        model_name = _generate_model_name(operation, path, method, schema)
        
        # Ensure unique model name
        base_name = model_name
        counter = 1
        while model_name in _generated_models:
            model_name = f"{base_name}{counter}"
            counter += 1
        
        # Generate model source code
        model_code = _generate_response_model_class(schema, model_name)
        
        if model_code:
            # Register the model
            _schema_registry[schema_hash] = model_name
            _generated_models[model_name] = model_code
            return model_name
    
    except Exception as e:
        # If model generation fails, log and continue with fallback
        print(f"Warning: Could not generate model for {method.upper()} {path}: {e}")
    
    return None


class Parameters(BaseModel):
    name: str
    identifier: str
    description: str = ""
    type: str = "string"
    where: Literal["path", "query", "header", "body"]
    required: bool
    example: str | None = None
    is_file: bool = False
    schema: dict = {}

    def __str__(self):
        return f"{self.name}: ({self.type})"


class Method(BaseModel):
    name: str
    summary: str
    tags: list[str]
    path: str
    method: str
    path_params: list[Parameters]
    query_params: list[Parameters]
    body_params: list[Parameters]
    return_type: str

    def deduplicate_params(self):
        """
        Deduplicate parameters by name.
        Sometimes the same parameter is defined in multiple places, we only want to include it once.
        """
        # TODO: Implement this
        pass

    def render(self, template_dir: str, template_name: str = "method.jinja2") -> str:
        """
        Render this Method instance into source code using a Jinja2 template.

        Args:
            template_dir (str): Directory where the Jinja2 templates are located.
            template_name (str): Filename of the method template.

        Returns:
            str: The rendered method source code.
        """
        from jinja2 import Environment, FileSystemLoader

        env = Environment(
            loader=FileSystemLoader(template_dir),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        template = env.get_template(template_name)
        return template.render(method=self)


def convert_to_snake_case(identifier: str) -> str:
    """
    Convert a string identifier to snake_case,
    replacing non-alphanumeric, non-underscore characters (including ., -, spaces, [], etc.) with underscores.
    Handles camelCase/PascalCase transitions.
    """
    if not identifier:
        return identifier
    result = re.sub(r"[^a-zA-Z0-9_]+", "_", identifier)
    result = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", result)
    result = re.sub(r"__+", "_", result)
    return result.strip("_").lower()


# Added new recursive type mapper
def _openapi_type_to_python_type(schema: dict, required: bool = True) -> str:
    """
    Recursively map OpenAPI schema to Python type hints.
    """
    openapi_type = schema.get("type")

    if "$ref" in schema and not openapi_type:
        py_type = "dict[str, Any]"
    elif openapi_type == "array":
        items_schema = schema.get("items", {})
        item_type = _openapi_type_to_python_type(items_schema, required=True)
        py_type = f"List[{item_type}]"
    elif openapi_type == "object":
        if schema.get("format") in ["binary", "byte"]:
            py_type = "bytes"
        else:
            if "additionalProperties" in schema and isinstance(schema["additionalProperties"], dict):
                additional_props_schema = schema["additionalProperties"]

                value_type = _openapi_type_to_python_type(additional_props_schema, required=True)
                py_type = f"dict[str, {value_type}]"
            elif (
                not schema.get("properties")
                and not schema.get("allOf")
                and not schema.get("oneOf")
                and not schema.get("anyOf")
            ):
                py_type = "dict[str, Any]"
            else:
                py_type = "dict[str, Any]"
    elif openapi_type == "integer":
        py_type = "int"
    elif openapi_type == "number":
        py_type = "float"
    elif openapi_type == "boolean":
        py_type = "bool"
    elif openapi_type == "string":
        if schema.get("format") in ["binary", "byte"]:
            py_type = "bytes"
        elif schema.get("format") == "date" or schema.get("format") == "date-time":
            py_type = "str"
        else:
            py_type = "str"
    else:
        py_type = "Any"

    if not required:
        if py_type.startswith("Optional[") and py_type.endswith("]"):
            return py_type
        return f"Optional[{py_type}]"
    return py_type


def _sanitize_identifier(name: str | None) -> str:
    """Cleans a string to be a valid Python identifier.

    Replaces hyphens, dots, and square brackets with underscores.
    Removes closing square brackets.
    Removes leading underscores (e.g., `_param` becomes `param`),
    unless the name consists only of underscores (e.g., `_` or `__` become `_`).
    Appends an underscore if the name is a Python keyword (e.g., `for` becomes `for_`).
    Converts `self` to `self_arg`.
    Returns empty string if input is None.
    """
    if name is None:
        return ""

    # Initial replacements for common non-alphanumeric characters
    sanitized = (
        name.replace("-", "_")
        .replace(".", "_")
        .replace("[", "_")
        .replace("]", "")
        .replace("$", "_")
        .replace("/", "_")
        .replace("@", "at")
    )

    # Remove leading underscores, but preserve a single underscore if the name (after initial replace)
    # consisted only of underscores.
    if sanitized.startswith("_"):
        stripped_name = sanitized.lstrip("_")
        sanitized = stripped_name if stripped_name else "_"

    # Append underscore if the sanitized name is a Python keyword
    if iskeyword(sanitized):
        sanitized += "_"

    # Special handling for "self" to avoid conflict with instance method's self argument
    if sanitized == "self":
        sanitized = "self_arg"

    return sanitized


def _extract_properties_from_schema(
    schema: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Extracts properties and required fields from a schema, handling 'allOf'."""
    properties = {}
    required_fields = []

    if "allOf" in schema:
        for sub_schema in schema["allOf"]:
            sub_props, sub_required = _extract_properties_from_schema(sub_schema)
            properties.update(sub_props)
            required_fields.extend(sub_required)

    if "oneOf" in schema:
        for sub_schema in schema["oneOf"]:
            sub_props, _ = _extract_properties_from_schema(sub_schema)
            properties.update(sub_props)

    if "anyOf" in schema:
        for sub_schema in schema["anyOf"]:
            sub_props, _ = _extract_properties_from_schema(sub_schema)
            properties.update(sub_props)

    # Combine with top-level properties and required fields, if any
    properties.update(schema.get("properties", {}))
    required_fields.extend(schema.get("required", []))

    # Deduplicate required fields
    required_fields = list(set(required_fields))

    return properties, required_fields


def _load_and_resolve_references(path: Path):
    # Load the schema
    type = "yaml" if path.suffix == ".yaml" else "json"
    with open(path) as f:
        schema = yaml.safe_load(f) if type == "yaml" else json.load(f)
    # Resolve references
    return replace_refs(schema)


def _determine_return_type(operation: dict[str, Any], path: str, method: str) -> str:
    """
    Determine the return type from the response schema.
    
    Now generates specific Pydantic model classes for response schemas where possible,
    falling back to generic types for complex or missing schemas.

    Args:
        operation (dict): The operation details from the schema.
        path (str): The API path (e.g., '/users/{user_id}').
        method (str): The HTTP method (e.g., 'get').

    Returns:
        str: The appropriate return type annotation (specific model class name or generic type)
    """
    responses = operation.get("responses", {})
    # Find successful response (2XX)
    success_response = None
    for code in responses:
        if code.startswith("2"):
            success_response = responses[code]
            break

    if not success_response:
        return "Any"  # Default to Any if no success response

    # Check if there's content with schema
    if "content" in success_response:
        for content_type, content_info in success_response["content"].items():
            if content_type.startswith("application/json") and "schema" in content_info:
                schema = content_info["schema"]
                
                # generate a specific model class for this schema
                model_name = _get_or_create_response_model(operation, path, method, schema)
                
                if model_name:
                    return model_name
                
                if schema.get("type") == "array":
                    return "list[Any]"
                elif schema.get("type") == "object" or "$ref" in schema:
                    return "dict[str, Any]"

    # Default to Any if unable to determine
    return "Any"


def _determine_function_name(operation: dict[str, Any], path: str, method: str) -> str:
    """
    Determine the function name from the operation.
    """
    # Determine function name
    if "operationId" in operation:
        raw_name = operation["operationId"]
        cleaned_name = raw_name.replace(".", "_").replace("-", "_")
        cleaned_name_no_numbers = re.sub(r"\d+", "", cleaned_name)
        func_name = convert_to_snake_case(cleaned_name_no_numbers)
    else:
        # Generate name from path and method
        path_parts = path.strip("/").split("/")
        name_parts = [method]
        for part in path_parts:
            if part.startswith("{") and part.endswith("}"):
                name_parts.append("by_" + part[1:-1])
            else:
                name_parts.append(part)
        func_name = "_".join(name_parts).replace("-", "_").lower()

    # Only fix isolated 'a' and 'an' as articles, not when they're part of words
    func_name = re.sub(r"_a([^_a-z])", r"_a_\1", func_name)  # Fix for patterns like retrieve_ablock -> retrieve_a_block
    func_name = re.sub(r"_a$", r"_a", func_name)  # Don't change if 'a' is at the end of the name
    func_name = re.sub(r"_an([^_a-z])", r"_an_\1", func_name)  # Fix for patterns like create_anitem -> create_an_item
    func_name = re.sub(r"_an$", r"_an", func_name)  # Don't change if 'an' is at the end of the name
    return func_name


def _generate_path_params(path: str) -> list[Parameters]:
    path_params_in_url = re.findall(r"{([^}]+)}", path)
    parameters = []
    for param_name in path_params_in_url:
        try:
            parameters.append(
                Parameters(
                    name=_sanitize_identifier(param_name),
                    identifier=param_name,
                    description=param_name,
                    type="string",
                    where="path",
                    required=True,
                    example=None,
                    schema={"type": "string"},
                )
            )
        except Exception as e:
            print(f"Error generating path parameters {param_name}: {e}")
            raise e
    return parameters


def _generate_url(path: str, path_params: list[Parameters]):
    formatted_path = path
    for param in path_params:
        formatted_path = formatted_path.replace(f"{{{param.identifier}}}", f"{{{param.name}}}")
    return formatted_path


def _generate_query_params(operation: dict[str, Any]) -> list[Parameters]:
    query_params = []
    for param in operation.get("parameters", []):
        name = param.get("name")
        if name is None:
            continue

        # Clean the parameter name for use as a Python identifier
        clean_name = _sanitize_identifier(name)

        description = param.get("description", "")

        # Extract type from schema if available
        param_schema = param.get("schema", {})
        type_value = param_schema.get("type") if param_schema else param.get("type")
        # Default to string if type is not available
        if type_value is None:
            type_value = "string"

        # Extract example
        example_value = param.get("example", param_schema.get("example"))

        where = param.get("in")
        required = param.get("required", False)
        if where == "query":
            parameter = Parameters(
                name=clean_name,
                identifier=name,
                description=description,
                type=type_value,
                where=where,
                required=required,
                example=str(example_value) if example_value is not None else None,
                schema=param_schema if param_schema else {"type": type_value},
            )
            query_params.append(parameter)
    return query_params


def _generate_body_params(schema_to_process: dict[str, Any] | None, overall_body_is_required: bool) -> list[Parameters]:
    body_params = []
    if not schema_to_process:
        return []

    properties, required_fields_in_schema = _extract_properties_from_schema(schema_to_process)

    for param_name, param_schema_details in properties.items():
        param_type = param_schema_details.get("type", "string")
        param_description = param_schema_details.get("description", param_name)
        param_required = overall_body_is_required and param_name in required_fields_in_schema
        param_example = param_schema_details.get("example")
        param_format = param_schema_details.get("format")

        current_is_file = False
        effective_param_type = param_type

        if param_type == "string" and param_format in ["binary", "byte"]:
            current_is_file = True
            effective_param_type = "file"  # Represent as 'file' for docstrings/type hints

        body_params.append(
            Parameters(
                name=_sanitize_identifier(param_name),
                identifier=param_name,
                description=param_description,
                type=effective_param_type,
                where="body",
                required=param_required,
                example=str(param_example) if param_example is not None else None,
                is_file=current_is_file,
                schema=param_schema_details,
            )
        )
    # print(f"[DEBUG] Final body_params list generated: {body_params}") # DEBUG
    return body_params


def _generate_method_code(path, method, operation):
    """
    Generate the code for a single API method.


    Args:
        path (str): The API path (e.g., '/users/{user_id}').
        method (str): The HTTP method (e.g., 'get').
        operation (dict): The operation details from the schema.
        full_schema (dict): The complete OpenAPI schema, used for reference resolution.
        tool_name (str, optional): The name of the tool/app to prefix the function name with.

    Returns:
        tuple: (method_code, func_name) - The Python code for the method and its name.
    """
    # print(f"--- Generating code for: {method.upper()} {path} ---")  # Log endpoint being processed

    # --- Determine Function Name and Basic Operation Details ---
    func_name = _determine_function_name(operation, path, method)
    method_lower = method.lower()  # Define method_lower earlier
    operation.get("summary", "")  # Ensure summary is accessed if needed elsewhere
    operation.get("tags", [])  # Ensure tags are accessed if needed elsewhere

    # --- Generate Path and Query Parameters (pre-aliasing) ---
    path_params = _generate_path_params(path)
    query_params = _generate_query_params(operation)

    # --- Determine Request Body Content Type and Schema ---
    # This section selects the primary content type and its schema to be used for the request body.
    has_body = "requestBody" in operation
    body_schema_to_use = None
    selected_content_type = None  # This will hold the chosen content type string

    if has_body:
        request_body_spec = operation["requestBody"]
        request_body_content_map = request_body_spec.get("content", {})

        preferred_content_types = [
            "multipart/form-data",
            "application/x-www-form-urlencoded",
            "application/json",
            "application/octet-stream",
            "text/plain",
        ]

        found_preferred = False
        for ct in preferred_content_types:
            if ct in request_body_content_map:
                selected_content_type = ct
                body_schema_to_use = request_body_content_map[ct].get("schema")
                found_preferred = True
                break

        if not found_preferred:  # Check for image/* if no direct match yet
            for ct_key in request_body_content_map:
                if ct_key.startswith("image/"):
                    selected_content_type = ct_key
                    body_schema_to_use = request_body_content_map[ct_key].get("schema")
                    found_preferred = True
                    break

        if not found_preferred and request_body_content_map:  # Fallback to first listed
            first_ct_key = next(iter(request_body_content_map))
            selected_content_type = first_ct_key
            body_schema_to_use = request_body_content_map[first_ct_key].get("schema")

    # --- Generate Body Parameters (based on selected schema, pre-aliasing) ---
    if body_schema_to_use:  # If a schema was actually found for the selected content type
        body_params = _generate_body_params(
            body_schema_to_use,  # Pass the specific schema
            operation.get("requestBody", {}).get("required", False),  # Pass the overall body requirement
        )
    else:
        body_params = []
    # --- End new logic for content type selection ---

    # --- Alias Duplicate Parameter Names ---
    # This section ensures that parameter names (path, query, body) are unique in the function signature, applying suffixes like '_query' or '_body' if needed.
    path_param_names = {p.name for p in path_params}

    # Define the string that "self" sanitizes to. This name will be treated as reserved
    # for query/body params to force suffixing.
    self_sanitized_marker = _sanitize_identifier("self")  # This will be "self_arg"

    # Base names that will force query/body parameters to be suffixed.
    # This includes actual path parameter names and the sanitized form of "self".
    path_param_base_conflict_names = path_param_names | {self_sanitized_marker}

    # Alias query parameters
    current_query_param_names = set()
    for q_param in query_params:
        original_q_name = q_param.name
        temp_q_name = original_q_name
        # Check against path params AND the sanitized "self" marker
        if temp_q_name in path_param_base_conflict_names:
            temp_q_name = f"{original_q_name}_query"
        # Ensure uniqueness among query params themselves after potential aliasing

        # This step is more about ensuring the final suffixed name is unique if multiple query params mapped to same path param name
        counter = 1
        final_q_name = temp_q_name
        while (
            final_q_name in path_param_base_conflict_names or final_q_name in current_query_param_names
        ):  # Check against path/\"self_arg\" and already processed query params
            if temp_q_name == original_q_name:  # first conflict was with path_param_base_conflict_names
                final_q_name = f"{original_q_name}_query"  # try simple suffix first
                if final_q_name in path_param_base_conflict_names or final_q_name in current_query_param_names:
                    final_q_name = f"{original_q_name}_query_{counter}"  # then add counter
            else:  # conflict was with another query param after initial suffixing
                final_q_name = f"{temp_q_name}_{counter}"
            counter += 1
        q_param.name = final_q_name
        current_query_param_names.add(q_param.name)

    # Alias body parameters
    # Names to check against: path param names (including "self_arg" marker) and (now aliased) query param names
    existing_param_names_for_body = path_param_base_conflict_names.union(current_query_param_names)
    current_body_param_names = set()

    for b_param in body_params:
        original_b_name = b_param.name
        temp_b_name = original_b_name
        # Check against path, "self_arg" marker, and query params
        if temp_b_name in existing_param_names_for_body:
            temp_b_name = f"{original_b_name}_body"

        # Ensure uniqueness among body params themselves or further conflicts
        counter = 1
        final_b_name = temp_b_name
        while final_b_name in existing_param_names_for_body or final_b_name in current_body_param_names:
            if temp_b_name == original_b_name:  # first conflict was with existing_param_names_for_body
                final_b_name = f"{original_b_name}_body"
                if final_b_name in existing_param_names_for_body or final_b_name in current_body_param_names:
                    final_b_name = f"{original_b_name}_body_{counter}"
            else:  # conflict was with another body param after initial suffixing
                final_b_name = f"{temp_b_name}_{counter}"

            counter += 1
        b_param.name = final_b_name
        current_body_param_names.add(b_param.name)
    # --- End Alias duplicate parameter names ---

    # --- Determine Return Type and Body Characteristics ---
    return_type = _determine_return_type(operation, path, method)

    body_required = has_body and operation["requestBody"].get("required", False)  # Remains useful

    is_array_body = False
    has_empty_body = False

    if has_body and body_schema_to_use:  # Use the determined body_schema_to_use
        if body_schema_to_use.get("type") == "array":
            is_array_body = True

        # Check for cases that might lead to an "empty" body parameter (for JSON) in the signature,
        # or indicate a raw body type where _generate_body_params wouldn't create named params.
        if (
            not body_params
            and not is_array_body
            and selected_content_type == "application/json"
            and (
                body_schema_to_use == {}
                or (
                    body_schema_to_use.get("type") == "object"
                    and not body_schema_to_use.get("properties")
                    and not body_schema_to_use.get("allOf")
                    and not body_schema_to_use.get("oneOf")
                    and not body_schema_to_use.get("anyOf")
                )
            )
        ):
            has_empty_body = True  # Indicates a generic 'request_body: dict = None' might be needed for empty JSON

    # --- Build Function Arguments for Signature ---
    # This section constructs the list of arguments (required and optional)
    # that will appear in the generated Python function's signature.
    required_args = []
    optional_args = []

    # Arguments for the function signature with type hints
    signature_required_args_typed = []
    signature_optional_args_typed = []

    #  Process Path Parameters (Highest Priority)
    for param in path_params:
        # Path param names are sanitized but not suffixed by aliasing.
        if param.name not in required_args:  # param.name is the sanitized name
            required_args.append(param.name)
            # For signature with types
            param_py_type = _openapi_type_to_python_type(param.schema, required=True)
            signature_required_args_typed.append(f"{param.name}: {param_py_type}")

    #  Process Query Parameters
    for param in query_params:  # param.name is the potentially aliased name (e.g., id_query)
        arg_name_for_sig = param.name
        current_arg_names_set = set(required_args) | {arg.split("=")[0] for arg in optional_args}

        # For signature with types
        param_py_type = _openapi_type_to_python_type(param.schema, required=param.required)

        if arg_name_for_sig not in current_arg_names_set:
            if param.required:
                required_args.append(arg_name_for_sig)
                signature_required_args_typed.append(f"{arg_name_for_sig}: {param_py_type}")
            else:
                optional_args.append(f"{arg_name_for_sig}=None")
                signature_optional_args_typed.append(f"{arg_name_for_sig}: {param_py_type} = None")

    #  Process Body Parameters / Request Body
    # This list tracks the *final* names of parameters in the signature that come from the request body,
    final_request_body_arg_names_for_signature = []
    final_empty_body_param_name = None  # For the specific case of has_empty_body (empty JSON object)
    raw_body_param_name = None  # For raw content like octet-stream, text/plain, image/*

    if has_body:
        current_arg_names_set = set(required_args) | {arg.split("=")[0] for arg in optional_args}
        if is_array_body:
            array_param_name_base = "items"  # Default base name
            if func_name.endswith("_list_input"):
                array_param_name_base = func_name.replace("_list_input", "")
            elif "List" in func_name:
                array_param_name_base = func_name.split("List")[0].lower() + "_list"

            final_array_param_name = array_param_name_base
            counter = 1
            is_first_suffix_attempt = True
            while final_array_param_name in current_arg_names_set:
                if is_first_suffix_attempt:
                    final_array_param_name = f"{array_param_name_base}_body"
                    is_first_suffix_attempt = False
                else:
                    final_array_param_name = f"{array_param_name_base}_body_{counter}"
                counter += 1

            # For signature with types
            # The schema for an array body is body_schema_to_use itself
            array_body_py_type = _openapi_type_to_python_type(body_schema_to_use, required=body_required)

            if body_required:
                required_args.append(final_array_param_name)
                signature_required_args_typed.append(f"{final_array_param_name}: {array_body_py_type}")
            else:
                optional_args.append(f"{final_array_param_name}=None")
                signature_optional_args_typed.append(f"{final_array_param_name}: {array_body_py_type} = None")
            final_request_body_arg_names_for_signature.append(final_array_param_name)

        # New: Handle raw body parameter (if body_params is empty but body is expected and not array/empty JSON)
        elif (
            not body_params
            and not is_array_body
            and selected_content_type
            and selected_content_type
            not in ["application/json", "application/x-www-form-urlencoded", "multipart/form-data"]
        ):
            # This branch is for raw content types like application/octet-stream, text/plain, image/*
            # where _generate_body_params returned an empty list because the schema isn't an object with properties.
            raw_body_param_name_base = "body_content"

            temp_raw_body_name = raw_body_param_name_base
            counter = 1
            is_first_suffix_attempt = True
            while temp_raw_body_name in current_arg_names_set:
                if is_first_suffix_attempt:
                    temp_raw_body_name = f"{raw_body_param_name_base}_body"
                    is_first_suffix_attempt = False
                else:
                    temp_raw_body_name = f"{raw_body_param_name_base}_body_{counter}"
                counter += 1
            raw_body_param_name = temp_raw_body_name

            # For signature with types
            # Determine type based on selected_content_type for raw body
            raw_body_schema_for_type = {"type": "string", "format": "binary"}  # Default to bytes
            if selected_content_type and "text" in selected_content_type:
                raw_body_schema_for_type = {"type": "string"}
            elif selected_content_type and selected_content_type.startswith("image/"):
                raw_body_schema_for_type = {"type": "string", "format": "binary"}  # image is bytes

            raw_body_py_type = _openapi_type_to_python_type(raw_body_schema_for_type, required=body_required)

            if body_required:  # If the raw body itself is required
                required_args.append(raw_body_param_name)
                signature_required_args_typed.append(f"{raw_body_param_name}: {raw_body_py_type}")
            else:
                optional_args.append(f"{raw_body_param_name}=None")
                signature_optional_args_typed.append(f"{raw_body_param_name}: {raw_body_py_type} = None")
            final_request_body_arg_names_for_signature.append(raw_body_param_name)

        elif body_params:  # Object body with discernible properties
            for param in body_params:  # Iterate ALIASED body_params
                arg_name_for_sig = param.name  # final aliased name (e.g., "id_body")

                # Defensive check against already added args
                current_arg_names_set_loop = set(required_args) | {arg.split("=")[0] for arg in optional_args}

                # For signature with types
                param_py_type = _openapi_type_to_python_type(param.schema, required=param.required)

                if arg_name_for_sig not in current_arg_names_set_loop:
                    if param.required:
                        required_args.append(arg_name_for_sig)
                        signature_required_args_typed.append(f"{arg_name_for_sig}: {param_py_type}")
                    else:
                        # Parameters model does not store schema 'default'. Optional params default to None.
                        optional_args.append(f"{arg_name_for_sig}=None")
                        signature_optional_args_typed.append(f"{arg_name_for_sig}: {param_py_type} = None")
                final_request_body_arg_names_for_signature.append(arg_name_for_sig)

    if (
        has_empty_body
        and selected_content_type == "application/json"
        and not body_params
        and not is_array_body
        and not raw_body_param_name
    ):
        empty_body_param_name_base = "request_body"  # For empty JSON object
        current_arg_names_set = set(required_args) | {arg.split("=")[0] for arg in optional_args}

        final_empty_body_param_name = empty_body_param_name_base
        counter = 1
        is_first_suffix_attempt = True
        while final_empty_body_param_name in current_arg_names_set:
            if is_first_suffix_attempt:
                final_empty_body_param_name = f"{empty_body_param_name_base}_body"
                is_first_suffix_attempt = False
            else:
                final_empty_body_param_name = f"{empty_body_param_name_base}_body_{counter}"
            counter += 1

        # For signature with types
        # Empty body usually implies an empty JSON object, so dict or Optional[dict]
        empty_body_py_type = _openapi_type_to_python_type({"type": "object"}, required=False)

        if final_empty_body_param_name not in (set(required_args) | {arg.split("=")[0] for arg in optional_args}):
            optional_args.append(f"{final_empty_body_param_name}=None")
            # Add to typed signature list
            signature_optional_args_typed.append(f"{final_empty_body_param_name}: {empty_body_py_type} = None")

        # Track for docstring, even if it's just 'request_body' or 'request_body_body'
        if final_empty_body_param_name not in final_request_body_arg_names_for_signature:
            final_request_body_arg_names_for_signature.append(final_empty_body_param_name)

    # Combine required and optional arguments FOR DOCSTRING (as before, without types)
    args = required_args + optional_args
    print(f"[DEBUG] Final combined args for DOCSTRING: {args}")  # DEBUG

    # Combine required and optional arguments FOR SIGNATURE (with types)
    signature_args_combined_typed = signature_required_args_typed + signature_optional_args_typed
    print(f"[DEBUG] Final combined args for SIGNATURE: {signature_args_combined_typed}")  # DEBUG

    # ----- Build Docstring -----
    # This section constructs the entire docstring for the generated method,
    # including summary, argument descriptions, return type, and tags.
    docstring_parts = []
    # NEW: Add OpenAPI path as the first line of the docstring
    # openapi_path_comment_for_docstring = f"# openapi_path: {path}"
    # docstring_parts.append(openapi_path_comment_for_docstring)

    return_type = _determine_return_type(operation, path, method)

    # Summary
    summary = operation.get("summary", "").strip()
    if not summary:
        summary = operation.get("description", f"Execute {method.upper()} {path}").strip()
        summary = summary.split("\n")[0]
    if summary:
        docstring_parts.append(summary)

    # Args
    args_doc_lines = []
    param_details = {}

    # Create a combined list of all parameter objects (path, query, body) to fetch details for docstring
    all_parameter_objects_for_docstring = path_params + query_params + body_params

    signature_arg_names = {a.split("=")[0] for a in args}

    for param_obj in all_parameter_objects_for_docstring:
        if param_obj.name in signature_arg_names and param_obj.name not in param_details:
            param_details[param_obj.name] = param_obj

    # Fetch request body example
    example_data = None  # Initialize example_data here for wider scope

    if has_body:
        try:
            json_content = operation["requestBody"]["content"]["application/json"]
            # From direct content definition
            if "example" in json_content:
                example_data = json_content["example"]
            elif "examples" in json_content and json_content["examples"]:
                first_example_key = list(json_content["examples"].keys())[0]
                example_data = json_content["examples"][first_example_key].get("value")
            # If not found directly, try from resolved body schema (for nested/referenced examples)
            if example_data is None and body_schema_to_use and "example" in body_schema_to_use:
                example_data = body_schema_to_use["example"]
        except KeyError:
            pass  # No example found or application/json content not present

    if signature_arg_names:
        args_doc_lines.append("Args:")
        for arg_signature_str in args:
            arg_name = arg_signature_str.split("=")[0]
            example_str = None  # Initialize example_str here for each argument
            detail = param_details.get(arg_name)
            if detail:
                desc = detail.description or "No description provided."
                type_hint = detail.type if detail.type else "Any"
                # Adjust type_hint for file parameters for the docstring
                if detail.is_file:
                    type_hint = "file (e.g., open('path/to/file', 'rb'))"

                arg_line = f"    {arg_name} ({type_hint}): {desc}"
                if detail.example and not detail.is_file:  # Don't show schema example for file inputs
                    example_str = repr(detail.example)
                    arg_line += f" Example: {example_str}."
                # Fallback for body parameters if no direct example was found
                elif (
                    not example_str
                    and detail.where == "body"
                    and example_data
                    and isinstance(example_data, dict)
                    and detail.identifier in example_data
                ):
                    current_body_param_example = example_data[detail.identifier]
                    if current_body_param_example is not None:  # Ensure the extracted part is not None
                        try:
                            arg_line += f" Example: {repr(current_body_param_example)}."
                        except Exception:  # Fallback if repr fails
                            arg_line += " Example: [Could not represent example]."

                args_doc_lines.append(arg_line)

            elif arg_name == final_empty_body_param_name and has_empty_body:
                args_doc_lines.append(
                    f"    {arg_name} (dict | None): Optional dictionary for an empty JSON request body (e.g., {{}})."
                )
            elif arg_name == raw_body_param_name:
                raw_body_type_hint = "bytes"
                raw_body_desc = "Raw binary content for the request body."
                if selected_content_type and "text" in selected_content_type:
                    raw_body_type_hint = "str"
                    raw_body_desc = "Raw text content for the request body."
                elif selected_content_type and selected_content_type.startswith("image/"):
                    raw_body_type_hint = "bytes (image data)"
                    raw_body_desc = f"Raw image content ({selected_content_type}) for the request body."
                args_doc_lines.append(f"    {arg_name} ({raw_body_type_hint} | None): {raw_body_desc}")

    if args_doc_lines:
        docstring_parts.append("\n".join(args_doc_lines))

    # Returns - Use the pre-calculated return_type variable
    success_desc = ""
    responses = operation.get("responses", {})
    for code, resp_info in responses.items():
        if code.startswith("2"):
            success_desc = resp_info.get("description", "").strip()
            break
    docstring_parts.append(f"Returns:\n    {return_type}: {success_desc or 'API response data.'}")

    raises_section_lines = [
        "Raises:",
        "    HTTPStatusError: Raised when the API request fails with detailed error information including status code and response body.",
    ]
    docstring_parts.append("\n".join(raises_section_lines))

    # Tags Section
    operation_tags = operation.get("tags", [])
    if operation_tags:
        tags_string = ", ".join(operation_tags)
        docstring_parts.append(f"Tags:\n    {tags_string}")

    # Combine and Format docstring
    docstring_content = "\n\n".join(docstring_parts)

    def_indent = "    "
    doc_indent = def_indent + "    "
    indented_docstring_content = textwrap.indent(docstring_content, doc_indent)

    # Wrap in triple quotes
    formatted_docstring = f'\n{doc_indent}"""\n{indented_docstring_content}\n{doc_indent}"""'
    # ----- End Build Docstring -----

    # --- Construct Method Signature String ---
    # Use signature_args_combined_typed for the signature
    if signature_args_combined_typed:
        signature = f"    def {func_name}(self, {', '.join(signature_args_combined_typed)}) -> {return_type}:"
    else:
        signature = f"    def {func_name}(self) -> {return_type}:"

    # --- Build Method Body ---
    # This section constructs the executable lines of code within the generated method.
    body_lines = []

    # --- Path Parameter Validation ---
    for param in path_params:
        body_lines.append(f"        if {param.name} is None:")
        body_lines.append(
            f"            raise ValueError(\"Missing required parameter '{param.identifier}'.\")"  # Use original name in error, ensure quotes are balanced
        )

    if method_lower not in ["get", "delete"]:
        body_lines.append("        request_body_data = None")

        # Initialize files_data only if it's POST or PUT and multipart/form-data,
        # as these are the primary cases where files_data is explicitly prepared and used.
        # The population logic (e.g., files_data = {}) will define it for other multipart cases if they arise.
        if method_lower in ["post", "put"] and selected_content_type == "multipart/form-data":
            body_lines.append("        files_data = None")

    # --- Build Request Payload (request_body_data and files_data) ---
    # This section prepares the data to be sent in the request body,
    # differentiating between files and other data for multipart forms,

    if has_body:
        # This block will now overwrite the initial None values if a body is present.
        if is_array_body:
            # For array request bodies, use the array parameter directly
            array_arg_name = (
                final_request_body_arg_names_for_signature[0]
                if final_request_body_arg_names_for_signature
                else "items_body"
            )  # Fallback
            body_lines.append(f"        # Using array parameter '{array_arg_name}' directly as request body")
            body_lines.append(f"        request_body_data = {array_arg_name}")  # Use a neutral temp name
            # files_data remains None

        elif selected_content_type == "multipart/form-data":
            body_lines.append("        request_body_data = {}")  # For non-file form fields
            body_lines.append("        files_data = {}")  # For file fields
            for b_param in body_params:  # Iterate through ALIASED body_params
                if b_param.is_file:
                    body_lines.append(f"        if {b_param.name} is not None:")  # Check if file param is provided
                    body_lines.append(f"            files_data['{b_param.identifier}'] = {b_param.name}")
                else:
                    body_lines.append(f"        if {b_param.name} is not None:")  # Check if form field is provided
                    body_lines.append(f"            request_body_data['{b_param.identifier}'] = {b_param.name}")
            body_lines.append("        files_data = {k: v for k, v in files_data.items() if v is not None}")
            # Ensure files_data is None if it's empty after filtering, as httpx expects None, not {}
            body_lines.append("        if not files_data: files_data = None")

        elif body_params:  # Object request bodies (JSON, x-www-form-urlencoded) with specific parameters
            body_lines.append("        request_body_data = {")
            for b_param in body_params:
                body_lines.append(f"            '{b_param.identifier}': {b_param.name},")
            body_lines.append("        }")
            body_lines.append(
                "        request_body_data = {k: v for k, v in request_body_data.items() if v is not None}"
            )

        elif raw_body_param_name:  # Raw content type (octet-stream, text, image)
            body_lines.append(f"        request_body_data = {raw_body_param_name}")

        elif has_empty_body and selected_content_type == "application/json":  # Empty JSON object {}
            body_lines.append(
                f"        request_body_data = {final_empty_body_param_name} if {final_empty_body_param_name} is not None else {{}}"
            )

    # --- Format URL and Query Parameters for Request ---
    url = _generate_url(path, path_params)
    url_line = f'        url = f"{{self.base_url}}{url}"'
    body_lines.append(url_line)

    if query_params:
        query_params_items = []
        for param in query_params:  # Iterate through original query_params list
            # Use the original param.identifier for the key, and the (potentially aliased) param.name for the value variable
            query_params_items.append(f"('{param.identifier}', {param.name})")
        body_lines.append(
            f"        query_params = {{k: v for k, v in [{', '.join(query_params_items)}] if v is not None}}"
        )
    else:
        body_lines.append("        query_params = {}")

    # --- Determine Final Content-Type for API Call (Obsolete Block, selected_content_type is used) ---
    # The following block for request_body_content_type is largely superseded by selected_content_type,

    # Use the selected_content_type determined by the new logic as the primary source of truth.
    final_content_type_for_api_call = selected_content_type if selected_content_type else "application/json"

    # --- Make HTTP Request ---
    # This section generates the actual HTTP call
    # using the prepared URL, query parameters, request body data, files, and content type.
    # Use convenience methods that automatically handle responses and errors

    # Determine the appropriate return statement based on return type
    if return_type in ["Any", "dict[str, Any]", "list[Any]"]:
        return_statement = "        return self._handle_response(response)"
    else:
        return_statement = f"        return {return_type}.model_validate(self._handle_response(response))"

    if method_lower == "get":
        body_lines.append("        response = self._get(url, params=query_params)")
        body_lines.append(return_statement)
    elif method_lower == "post":
        if selected_content_type == "multipart/form-data":
            body_lines.append(
                f"        response = self._post(url, data=request_body_data, files=files_data, params=query_params, content_type='{final_content_type_for_api_call}')"
            )
        else:
            body_lines.append(
                f"        response = self._post(url, data=request_body_data, params=query_params, content_type='{final_content_type_for_api_call}')"
            )
        body_lines.append(return_statement)
    elif method_lower == "put":
        if selected_content_type == "multipart/form-data":
            body_lines.append(
                f"        response = self._put(url, data=request_body_data, files=files_data, params=query_params, content_type='{final_content_type_for_api_call}')"
            )
        else:
            body_lines.append(
                f"        response = self._put(url, data=request_body_data, params=query_params, content_type='{final_content_type_for_api_call}')"
            )
        body_lines.append(return_statement)
    elif method_lower == "patch":
        body_lines.append("        response = self._patch(url, data=request_body_data, params=query_params)")
        body_lines.append(return_statement)
    elif method_lower == "delete":
        body_lines.append("        response = self._delete(url, params=query_params)")
        body_lines.append(return_statement)
    else:
        body_lines.append(f"        response = self._{method_lower}(url, data=request_body_data, params=query_params)")
        body_lines.append(return_statement)

    # --- Combine Signature, Docstring, and Body for Final Method Code ---
    method_code = signature + formatted_docstring + "\n" + "\n".join(body_lines)
    return method_code, func_name


def load_schema(path: Path):
    return _load_and_resolve_references(path)


def generate_api_client(schema, class_name: str | None = None, filter_config_path: str | None = None):
    """
    Generate a Python API client class from an OpenAPI schema.

    Args:
        schema (dict): The OpenAPI schema as a dictionary.
        class_name (str | None): Optional class name override.
        filter_config_path (str | None): Optional path to JSON filter configuration file.

    Returns:
        str: A string containing the Python code for the API client class.
    """
    global _schema_registry, _generated_models
    _schema_registry.clear()
    _generated_models.clear()
    
    # Load filter configuration if provided
    filter_config = None
    if filter_config_path:
        filter_config = load_filter_config(filter_config_path)
        print(f"Loaded filter configuration from {filter_config_path} with {len(filter_config)} path specifications")

    methods = []
    method_names = []
    processed_count = 0
    skipped_count = 0

    # Extract API info for naming and base URL
    info = schema.get("info", {})
    api_title = info.get("title", "API")

    # Get base URL from servers array if available
    base_url = ""
    servers = schema.get("servers", [])
    if servers and isinstance(servers, list) and "url" in servers[0]:
        base_url = servers[0]["url"].rstrip("/")

    # Create a clean class name from API title
    if api_title:
        # Convert API title to a clean class name
        if class_name:
            clean_name = class_name[:-3] if class_name.endswith("App") else class_name.capitalize()
        else:
            base_name = "".join(word.capitalize() for word in api_title.split())
            clean_name = "".join(c for c in base_name if c.isalnum())
        class_name = f"{clean_name}App"

        # Extract tool name - remove spaces and convert to lowercase
        tool_name = api_title.lower()

        # Remove version numbers (like 3.0, v1, etc.)
        tool_name = re.sub(r"\s*v?\d+(\.\d+)*", "", tool_name)

        # Remove common words that aren't needed
        common_words = ["api", "openapi", "open", "swagger", "spec", "specification"]
        for word in common_words:
            tool_name = tool_name.replace(word, "")

        # Remove spaces, hyphens, underscores
        tool_name = tool_name.replace(" ", "").replace("-", "").replace("_", "")

        # Remove any non-alphanumeric characters
        tool_name = "".join(c for c in tool_name if c.isalnum())

        # If empty (after cleaning), use generic name
        if not tool_name:
            tool_name = "api"
    else:
        class_name = "APIClient"
        tool_name = "api"

    # Iterate over paths and their operations
    for path, path_info in schema.get("paths", {}).items():
        for method in path_info:
            if method in ["get", "post", "put", "delete", "patch", "options", "head"]:
                # Apply filter configuration
                if not should_process_operation(path, method, filter_config):
                    print(f"Skipping method generation for '{method.upper()} {path}' due to filter configuration.")
                    skipped_count += 1
                    continue

                operation = path_info[method]
                print(f"Generating method for: {method.upper()} {path}")
                method_code, func_name = _generate_method_code(path, method, operation)
                methods.append(method_code)
                method_names.append(func_name)
                processed_count += 1

    if filter_config is not None:
        print(f"Selective generation complete: {processed_count} methods generated, {skipped_count} methods skipped.")

    # Generate list_tools method with all the function names
    tools_list = ",\n            ".join([f"self.{name}" for name in method_names])
    list_tools_method = f"""    def list_tools(self):
        return [
            {tools_list}
        ]"""

    # Generate class imports
    imports = [
        "from typing import Any, Optional, List",
        "from universal_mcp.applications import APIApplication",
        "from universal_mcp.integrations import Integration",
    ]
    
    # Add Pydantic imports 
    if _generated_models:
        imports.extend([
            "from pydantic import BaseModel, Field",
        ])

    # Generate the response model classes
    model_classes = []
    if _generated_models:
        print(f"Generated {len(_generated_models)} response model classes")
        model_classes = list(_generated_models.values())

    # Construct the class code
    imports_section = "\n".join(imports)
    models_section = "\n".join(model_classes) if model_classes else ""
    
    class_code_parts = [imports_section]
    
    if models_section:
        class_code_parts.extend(["", "# Generated Response Models", models_section])
    
    class_code_parts.extend([
        "",
        f"class {class_name}(APIApplication):",
        "    def __init__(self, integration: Integration = None, **kwargs) -> None:",
        f"        super().__init__(name='{class_name.lower()}', integration=integration, **kwargs)",
        f'        self.base_url = "{base_url}"',
        "",
        "\n\n".join(methods),
        "",
        list_tools_method,
        ""
    ])
    
    class_code = "\n".join(class_code_parts)
    return class_code


# Example usage
if __name__ == "__main__":
    # Sample OpenAPI schema
    schema = {
        "paths": {
            "/users": {
                "get": {
                    "summary": "Get a list of users",
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "A list of users",
                            "content": {"application/json": {"schema": {"type": "array"}}},
                        }
                    },
                },
                "post": {
                    "summary": "Create a user",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"name": {"type": "string"}},
                                }
                            }
                        },
                    },
                    "responses": {"201": {"description": "User created"}},
                },
            },
            "/users/{user_id}": {
                "get": {
                    "summary": "Get a user by ID",
                    "parameters": [
                        {
                            "name": "user_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"200": {"description": "User details"}},
                }
            },
        }
    }

    schema = load_schema("openapi.yaml")
    code = generate_api_client(schema)
    print(code)
