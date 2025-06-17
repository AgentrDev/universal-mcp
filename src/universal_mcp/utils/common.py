import hashlib
import importlib
import importlib.util
import inspect
import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import httpx
from loguru import logger

from universal_mcp.applications.application import BaseApplication
from universal_mcp.config import AppConfig

# --- Global Constants and Setup ---

UNIVERSAL_MCP_HOME = Path.home() / ".universal-mcp" / "packages"
REMOTE_CACHE_DIR = UNIVERSAL_MCP_HOME / "remote_cache"

if not UNIVERSAL_MCP_HOME.exists():
    UNIVERSAL_MCP_HOME.mkdir(parents=True, exist_ok=True)
if not REMOTE_CACHE_DIR.exists():
    REMOTE_CACHE_DIR.mkdir(exist_ok=True)

# set python path to include the universal-mcp home directory
if str(UNIVERSAL_MCP_HOME) not in sys.path:
    sys.path.append(str(UNIVERSAL_MCP_HOME))


# --- Default Name Generators ---


def get_default_repository_path(slug: str) -> str:
    """
    Convert a repository slug to a repository URL.
    """
    slug = slug.strip().lower()
    return f"universal-mcp-{slug}"


def get_default_package_name(slug: str) -> str:
    """
    Convert a repository slug to a package name.
    """
    slug = slug.strip().lower()
    package_name = f"universal_mcp_{slug.replace('-', '_')}"
    return package_name


def get_default_module_path(slug: str) -> str:
    """
    Convert a repository slug to a module path.
    """
    package_name = get_default_package_name(slug)
    module_path = f"{package_name}.app"
    return module_path


def get_default_class_name(slug: str) -> str:
    """
    Convert a repository slug to a class name.
    """
    slug = slug.strip().lower()
    class_name = "".join(part.capitalize() for part in slug.split("-")) + "App"
    return class_name


# --- Installation and Loading Helpers ---


def install_or_upgrade_package(package_name: str, repository_path: str):
    """
    Helper to install a package via pip from the universal-mcp GitHub repository.
    """
    uv_path = os.getenv("UV_PATH")
    uv_executable = str(Path(uv_path) / "uv") if uv_path else "uv"
    logger.info(f"Using uv executable: {uv_executable}")
    cmd = [
        uv_executable,
        "pip",
        "install",
        "--upgrade",
        repository_path,
        "--target",
        str(UNIVERSAL_MCP_HOME),
    ]
    logger.debug(f"Installing package '{package_name}' with command: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if result.stdout:
            logger.info(f"Command stdout: {result.stdout}")
        if result.stderr:
            logger.warning(f"Command stderr: {result.stderr}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Installation failed for '{package_name}': {e}")
        logger.error(f"Command stdout:\n{e.stdout}")
        logger.error(f"Command stderr:\n{e.stderr}")
        raise ModuleNotFoundError(f"Installation failed for package '{package_name}'") from e
    else:
        logger.debug(f"Package {package_name} installed successfully")


def install_dependencies_from_path(project_root: Path, target_install_dir: Path):
    """
    Installs dependencies from pyproject.toml or requirements.txt found in project_root.
    """
    uv_path = os.getenv("UV_PATH")
    uv_executable = str(Path(uv_path) / "uv") if uv_path else "uv"
    cmd = []

    if (project_root / "pyproject.toml").exists():
        logger.info(f"Found pyproject.toml in {project_root}, installing dependencies.")
        cmd = [uv_executable, "pip", "install", ".", "--target", str(target_install_dir)]
    elif (project_root / "requirements.txt").exists():
        logger.info(f"Found requirements.txt in {project_root}, installing dependencies.")
        cmd = [
            uv_executable,
            "pip",
            "install",
            "-r",
            "requirements.txt",
            "--target",
            str(target_install_dir),
        ]
    else:
        logger.debug(f"No dependency file found in {project_root}. Skipping dependency installation.")
        return

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, cwd=project_root)
        if result.stdout:
            logger.info(f"Dependency installation stdout:\n{result.stdout}")
        if result.stderr:
            logger.warning(f"Dependency installation stderr:\n{result.stderr}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Dependency installation failed for project at '{project_root}': {e}")
        logger.error(f"Command stdout:\n{e.stdout}")
        logger.error(f"Command stderr:\n{e.stderr}")
        raise RuntimeError(f"Failed to install dependencies for {project_root}") from e


def _load_class_from_project_root(project_root: Path, config: AppConfig) -> type[BaseApplication]:
    """Internal helper to load an application class from a local project directory."""
    logger.debug(f"Attempting to load '{config.name}' from project root: {project_root}")
    src_path = project_root / "src"
    if not src_path.is_dir():
        raise FileNotFoundError(f"Required 'src' directory not found in project at {project_root}")

    install_dependencies_from_path(project_root, UNIVERSAL_MCP_HOME)

    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
        logger.debug(f"Added to sys.path: {src_path}")

    module_path_str = get_default_module_path(config.name)
    class_name_str = get_default_class_name(config.name)

    try:
        module = importlib.import_module(module_path_str)
        importlib.reload(module)  # Reload to pick up changes
        app_class = getattr(module, class_name_str)
        return app_class
    except (ModuleNotFoundError, AttributeError) as e:
        logger.error(f"Failed to load module/class '{module_path_str}.{class_name_str}': {e}")
        raise


# --- Application Loaders ---


def load_app_from_package(config: AppConfig) -> type[BaseApplication]:
    """Loads an application from a pip-installable package."""
    logger.debug(f"Loading '{config.name}' as a package.")
    slug = config.name
    repository_path = get_default_repository_path(slug)
    package_name = get_default_package_name(slug)
    install_or_upgrade_package(package_name, repository_path)

    module_path_str = get_default_module_path(slug)
    class_name_str = get_default_class_name(slug)
    module = importlib.import_module(module_path_str)
    return getattr(module, class_name_str)


def load_app_from_local_folder(config: AppConfig) -> type[BaseApplication]:
    """Loads an application from a local folder path."""
    project_path = Path(config.source_path).resolve()
    return _load_class_from_project_root(project_path, config)


def load_app_from_remote_zip(config: AppConfig) -> type[BaseApplication]:
    """Downloads, caches, and loads an application from a remote .zip file."""
    url_hash = hashlib.sha256(config.source_path.encode()).hexdigest()[:16]
    project_path = REMOTE_CACHE_DIR / f"{config.name}-{url_hash}"

    if not project_path.exists():
        logger.info(f"Downloading remote project for '{config.name}' from {config.source_path}")
        project_path.mkdir(parents=True, exist_ok=True)
        response = httpx.get(config.source_path, follow_redirects=True, timeout=120)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            z.extractall(project_path)
        logger.info(f"Extracted remote project to {project_path}")

    return _load_class_from_project_root(project_path, config)


def load_app_from_remote_file(config: AppConfig) -> type[BaseApplication]:
    """Downloads, caches, and loads an application from a remote Python file."""
    logger.debug(f"Loading '{config.name}' as a remote file from {config.source_path}")
    url_hash = hashlib.sha256(config.source_path.encode()).hexdigest()[:16]
    cached_file_path = REMOTE_CACHE_DIR / f"{config.name}-{url_hash}.py"

    if not cached_file_path.exists():
        logger.info(f"Downloading remote file for '{config.name}' from {config.source_path}")
        try:
            response = httpx.get(config.source_path, follow_redirects=True, timeout=60)
            response.raise_for_status()
            cached_file_path.write_text(response.text, encoding="utf-8")
            logger.info(f"Cached remote file to {cached_file_path}")
        except httpx.HTTPStatusError as e:
            logger.error(f"Failed to download remote file: {e.response.status_code} {e.response.reason_phrase}")
            raise
        except Exception as e:
            logger.error(f"An unexpected error occurred during download: {e}")
            raise

    if not cached_file_path.stat().st_size > 0:
        raise ImportError(f"Remote file at {cached_file_path} is empty.")

    module_name = f"remote_app_{config.name}_{url_hash}"
    spec = importlib.util.spec_from_file_location(module_name, cached_file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create module spec for {cached_file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    for name, obj in inspect.getmembers(module, inspect.isclass):
        if obj.__module__ == module_name and issubclass(obj, BaseApplication) and obj is not BaseApplication:
            logger.debug(f"Found application class '{name}' defined in remote file for '{config.name}'.")
            return obj

    raise ImportError(f"No class inheriting from BaseApplication found in remote file {config.source_path}")


def load_app_from_local_file(config: AppConfig) -> type[BaseApplication]:
    """Loads an application from a local Python file."""
    logger.debug(f"Loading '{config.name}' as a local file from {config.source_path}")
    local_file_path = Path(config.source_path).resolve()

    if not local_file_path.is_file():
        raise FileNotFoundError(f"Local file not found at: {local_file_path}")

    if not local_file_path.stat().st_size > 0:
        raise ImportError(f"Local file at {local_file_path} is empty.")

    path_hash = hashlib.sha256(str(local_file_path).encode()).hexdigest()[:16]
    module_name = f"local_app_{config.name}_{path_hash}"

    spec = importlib.util.spec_from_file_location(module_name, local_file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not create module spec for {local_file_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    for name, obj in inspect.getmembers(module, inspect.isclass):
        if obj.__module__ == module_name and issubclass(obj, BaseApplication) and obj is not BaseApplication:
            logger.debug(f"Found application class '{name}' in local file for '{config.name}'.")
            return obj

    raise ImportError(f"No class inheriting from BaseApplication found in local file {config.source_path}")