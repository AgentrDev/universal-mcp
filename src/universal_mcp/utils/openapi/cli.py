import os
import re
from pathlib import Path

import litellm
import typer
from rich.console import Console
from rich.status import Status

console = Console()

app = typer.Typer(name="codegen")

def _model_callback(model: str) -> str:
    """
    Validates the model and checks if the required API key is set.
    This callback is now silent on success.
    """
    api_key_env_var = None
    if "claude" in model:
        api_key_env_var = "ANTHROPIC_API_KEY"
    elif "gpt" in model:
        api_key_env_var = "OPENAI_API_KEY"
    elif "gemini" in model:
        api_key_env_var = "GEMINI_API_KEY"
    elif "perplexity" in model:
        api_key_env_var = "PERPLEXITYAI_API_KEY"

    if api_key_env_var and not os.getenv(api_key_env_var):
        error_message = f"Environment variable '{api_key_env_var}' is not set. Please set it to use the '{model}' model."
        raise typer.BadParameter(error_message)
    elif not api_key_env_var:
        pass

    return model

@app.command()
def generate(
    schema_path: Path = typer.Option(..., "--schema", "-s"),
    output_path: Path = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path - should match the API name (e.g., 'twitter.py' for Twitter API)",
    ),
    class_name: str = typer.Option(
        None,
        "--class-name",
        "-c",
        help="Class name to use for the API client",
    ),
):
    """Generate API client from OpenAPI schema with optional docstring generation.

    The output filename should match the name of the API in the schema (e.g., 'twitter.py' for Twitter API).
    This name will be used for the folder in applications/.
    """
    # Import here to avoid circular imports
    from universal_mcp.utils.openapi.api_generator import generate_api_from_schema

    if not schema_path.exists():
        console.print(f"[red]Error: Schema file {schema_path} does not exist[/red]")
        raise typer.Exit(1)

    try:
        app_file_data = generate_api_from_schema(
            schema_path=schema_path,
            output_path=output_path,
            class_name=class_name,
        )
        if isinstance(app_file_data, dict) and "code" in app_file_data:
            console.print("[yellow]No output path specified, printing generated code to console:[/yellow]")
            console.print(app_file_data["code"])
        elif isinstance(app_file_data, Path):
            console.print("[green]API client successfully generated and installed.[/green]")
            console.print(f"[blue]Application file: {app_file_data}[/blue]")
        else:
            # Handle the error case from api_generator if validation fails
            if isinstance(app_file_data, dict) and "error" in app_file_data:
                console.print(f"[red]{app_file_data['error']}[/red]")
                raise typer.Exit(1)
            else:
                console.print("[red]Unexpected return value from API generator.[/red]")
                raise typer.Exit(1)

    except Exception as e:
        console.print(f"[red]Error generating API client: {e}[/red]")
        raise typer.Exit(1) from e


@app.command()
def readme(
    file_path: Path = typer.Argument(..., help="Path to the Python file to process"),
):
    """Generate a README.md file for the API client."""
    from universal_mcp.utils.openapi.readme import generate_readme

    readme_file = generate_readme(file_path)
    console.print(f"[green]README.md file generated at: {readme_file}[/green]")


@app.command()
def docgen(
    file_path: Path = typer.Argument(..., help="Path to the Python file to process"),
    model: str = typer.Option(
        "perplexity/sonar",
        "--model",
        "-m",
        help="Model to use for generating docstrings",
    ),
):
    """Generate docstrings for Python files using LLMs.

    This command uses litellm with structured output to generate high-quality
    Google-style docstrings for all functions in the specified Python file.
    """
    from universal_mcp.utils.openapi.docgen import process_file

    if not file_path.exists():
        console.print(f"[red]Error: File not found: {file_path}[/red]")
        raise typer.Exit(1)

    try:
        processed = process_file(str(file_path), model)
        console.print(f"[green]Successfully processed {processed} functions[/green]")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from e

@app.command()
def generate_from_llm(
    output_dir: Path = typer.Option(
        Path.cwd(),
        "--output-dir",
        "-o",
        help="Directory to save 'app.py'. Defaults to the current directory.",
        prompt="Enter the output directory",
        resolve_path=True,
    ),
    model: str = typer.Option(
        "perplexity/sonar",
        "--model",
        "-m",
        help="The LLM model to use for generation (via LiteLLM).",
        prompt="Enter the LLM model to use",
        callback=_model_callback,
    ),
    prompt: str = typer.Option(
        ...,
        "--prompt",
        "-p",
        help="A natural language description of the application and its tools.",
        prompt="Describe the application and its tools",
    ),
):
    """
    Generates an 'app.py' file from a natural language prompt using an LLM.
    """
    from universal_mcp.utils.prompts import APP_GENERATOR_SYSTEM_PROMPT

    console.print(f"[bold blue]🚀 Starting App Generation using model: '{model}'[/bold blue]")

    try:
        if not output_dir.exists():
             output_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        console.print(f"[red]❌ Failed to create output directory '{output_dir}': {e}[/red]")
        raise typer.Exit(code=1) from e

    output_file_path = output_dir / "app.py"
    console.print(f"[green]Will save generated file to:[/green] [cyan]{output_file_path}[/cyan]")

    messages = [
        {"role": "system", "content": APP_GENERATOR_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    response = None
    with Status("[bold green]Generating app code... (this may take a moment)[/bold green]", console=console) as status:
        try:
            response = litellm.completion(
                model=model,
                messages=messages,
                temperature=0.1,
                timeout=120,
            )
        except Exception as e:
            status.update("[bold red]❌ An error occurred during LLM API call.[/bold red]")
            console.print(f"[red]Error: {e}[/red]")
            raise typer.Exit(code=1) from e

    if not response or not response.choices:
        console.print("[bold red]❌ Failed to get a valid response from the LLM.[/bold red]")
        raise typer.Exit(code=1)

    generated_content = response.choices[0].message.content

    code_match = re.search(r"```python\n(.*?)\n```", generated_content, re.DOTALL)
    if code_match:
        final_code = code_match.group(1).strip()
    else:
        console.print("[yellow]Warning: LLM response did not contain a markdown code block. Using the raw response.[/yellow]")
        final_code = generated_content.strip()

    if not final_code:
        console.print("[bold red]❌ The LLM returned an empty code block. Aborting.[/bold red]")
        raise typer.Exit(code=1)

    try:
        output_file_path.write_text(final_code, encoding="utf-8")
        console.print("\n[bold green]✅ Success! Application code saved.[/bold green]")
    except Exception as e:
        console.print(f"\n[bold red]❌ Failed to write the generated code to file: {e}[/bold red]")
        raise typer.Exit(code=1) from e

@app.command()
def init(
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Output directory for the project (must exist)",
    ),
    app_name: str | None = typer.Option(
        None,
        "--app-name",
        "-a",
        help="App name (letters, numbers and hyphens only , underscores not allowed)",
    ),
    integration_type: str | None = typer.Option(
        None,
        "--integration-type",
        "-i",
        help="Integration type (api_key, oauth, agentr, none)",
        case_sensitive=False,
        show_choices=True,
    ),
):
    """Initialize a new MCP project using the cookiecutter template."""
    from cookiecutter.main import cookiecutter
    from typer import confirm, prompt

    from .cli import generate, generate_from_llm
    
    NAME_PATTERN = r"^[a-zA-Z0-9-]+$"
        
    def validate_app_name(value: str, field_name: str) -> None:
        if not re.match(NAME_PATTERN, value):
            console.print(
                f"[red]❌ Invalid {field_name}; only letters, numbers, hyphens allowed[/red]"
            )
            raise typer.Exit(code=1)

    if not app_name:
        app_name = typer.prompt(
            "Enter the app name",
            default="app_name",
            prompt_suffix=" (e.g., reddit, youtube): ",
        ).strip()
        
    validate_app_name(app_name, "app name")
    
    app_name = app_name.lower()
    if not output_dir:
        path_str = typer.prompt(
            "Enter the output directory for the project",
            default=str(Path.cwd()),
            prompt_suffix=": ",
        ).strip()
        output_dir = Path(path_str)

    if not output_dir.exists():
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            console.print(f"[green]✅ Created output directory at '{output_dir}'[/green]")
        except Exception as e:
            console.print(f"[red]❌ Failed to create output directory '{output_dir}': {e}[/red]")
            raise typer.Exit(code=1) from e
    elif not output_dir.is_dir():
        console.print(f"[red]❌ Output path '{output_dir}' exists but is not a directory.[/red]")
        raise typer.Exit(code=1)

    if not integration_type:
        integration_type = typer.prompt(
            "Choose the integration type",
            default="agentr",
            prompt_suffix=" (api_key, oauth, agentr, none): ",
        ).lower()
    if integration_type not in ("api_key", "oauth", "agentr", "none"):
        console.print("[red]❌ Integration type must be one of: api_key, oauth, agentr, none[/red]")
        raise typer.Exit(code=1)

    console.print("[blue]🚀 Generating project using cookiecutter...[/blue]")
    try:
        cookiecutter(
            "https://github.com/AgentrDev/universal-mcp-app-template.git",
            output_dir=str(output_dir),
            no_input=True,
            extra_context={
                "app_name": app_name,
                "integration_type": integration_type,
            },
        )
    except Exception as exc:
        console.print(f"❌ Project generation failed: {exc}")
        raise typer.Exit(code=1) from exc

    project_dir = output_dir / f"{app_name}"
    console.print(f"✅ Project created at {project_dir}")
    
    
    generate_client = confirm("Do you want to also generate api_client ?")

    if not generate_client:
        console.print("[yellow]Skipping API client generation.[/yellow]")
        return

    has_openapi_spec = confirm("Do you have openapi spec for the application just created ?")

    app_dir = app_name.lower().replace("-", "_")
    target_app_dir = project_dir / "src" / f"universal_mcp_{app_dir}"

    try:
         target_app_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
         console.print(f"[red]❌ Failed to create target app directory '{target_app_dir}': {e}[/red]")
         raise typer.Exit(code=1) from e


    if has_openapi_spec:
        schema_path_str = prompt("Enter the path to the OpenAPI schema file (JSON or YAML)")
        schema_path = Path(schema_path_str)

        if not schema_path.exists():
             console.print(f"[red]Error: Schema file {schema_path} does not exist[/red]")
             raise typer.Exit(1)
         
        class_name = "".join([part.title() for part in app_name.split('-')]) + "App"
        
        try:
            console.print("\n[bold blue]Calling 'codegen generate' with provided schema...[/bold blue]")
            generate(schema_path=schema_path, output_path=target_app_dir, class_name=class_name)

        except typer.Exit as e:
            console.print(f"[red]API client generation from schema failed. Exit code: {e.exit_code}[/red]")
            raise
        except Exception as e:
            console.print(f"[red]An unexpected error occurred during API client generation from schema: {e}[/red]")
            raise typer.Exit(code=1) from e

    else:
        try:
            llm_model = prompt("Enter the LLM model to use", default="perplexity/sonar")
            try:
                 _model_callback(llm_model)
            except typer.BadParameter as e:
                 console.print(f"[red]Validation Error: {e}[/red]")
                 raise typer.Exit(code=1) from e

            llm_prompt_text = prompt("Describe the application and its tools (natural language)")

            console.print("\n[bold blue]Calling 'codegen generate-from-llm'...[/bold blue]")
            generate_from_llm(output_dir=target_app_dir, model=llm_model, prompt=llm_prompt_text)

        except typer.Exit as e:
            console.print(f"[red]API client generation from LLM failed. Exit code: {e.exit_code}[/red]")
            raise
        except Exception as e:
            console.print(f"[red]An unexpected error occurred during API client generation from LLM: {e}[/red]")
            raise typer.Exit(code=1) from e

@app.command()
def preprocess(
    schema_path: Path = typer.Option(None, "--schema", "-s", help="Path to the OpenAPI schema file."),
    output_path: Path = typer.Option(None, "--output", "-o", help="Path to save the processed schema."),
):
    from universal_mcp.utils.openapi.preprocessor import run_preprocessing

    """Preprocess an OpenAPI schema using LLM to fill or enhance descriptions."""
    run_preprocessing(schema_path, output_path)


@app.command()
def split_api(
    input_app_file: Path = typer.Argument(..., help="Path to the generated app.py file to split"),
    output_dir: Path = typer.Option(..., "--output-dir", "-o", help="Directory to save the split files"),
    package_name: str = typer.Option(
        None, "--package-name", "-p", help="Package name for absolute imports (e.g., 'hubspot')"
    ),
):
    """Splits a single generated API client file into multiple files based on path groups."""
    from universal_mcp.utils.openapi.api_splitter import split_generated_app_file

    if not input_app_file.exists() or not input_app_file.is_file():
        console.print(f"[red]Error: Input file {input_app_file} does not exist or is not a file.[/red]")
        raise typer.Exit(1)

    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]Created output directory: {output_dir}[/green]")
    elif not output_dir.is_dir():
        console.print(f"[red]Error: Output path {output_dir} is not a directory.[/red]")
        raise typer.Exit(1)

    try:
        split_generated_app_file(input_app_file, output_dir, package_name)
        console.print(f"[green]Successfully split {input_app_file} into {output_dir}[/green]")
    except Exception as e:
        console.print(f"[red]Error splitting API client: {e}[/red]")

        raise typer.Exit(1) from e


if __name__ == "__main__":
    app()
