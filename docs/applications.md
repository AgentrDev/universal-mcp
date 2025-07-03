# Universal MCP Applications Module

This module provides the core functionality for managing and integrating applications within the Universal MCP system. It offers a flexible framework for creating, managing, and interacting with various types of applications through a unified interface.

## Overview

The applications module provides three main base classes for building application integrations:

1. `BaseApplication`: The abstract base class that defines the common interface for all applications
2. `APIApplication`: A concrete implementation for applications that communicate via HTTP APIs
3. `GraphQLApplication`: A specialized implementation for applications that use GraphQL APIs

## Key Features

- **Dynamic Application Loading**: Applications can be loaded dynamically from external packages
- **Unified Credential Management**: Centralized handling of application credentials
- **HTTP API Support**: Built-in support for RESTful API interactions
- **GraphQL Support**: Specialized support for GraphQL-based applications
- **Automatic Package Installation**: Automatic installation of application packages from GitHub

## Base Classes

### BaseApplication

The foundation class for all applications, providing:
- Basic initialization
- Credential management
- Tool listing interface

### APIApplication

Extends BaseApplication to provide:
- HTTP client management
- Authentication handling
- Common HTTP methods (GET, POST, PUT, DELETE, PATCH)
- Request/response handling

### GraphQLApplication

Specialized for GraphQL-based applications, offering:
- GraphQL client management
- Query and mutation execution
- Authentication handling

## Usage

### Creating a New Application

1. Create a new package following the naming convention: `universal_mcp_<app_name>`
2. Implement your application class inheriting from one of the base classes
3. Name your class following the convention: `<AppName>App`

Example:
```python
from universal_mcp.applications import APIApplication

class MyApp(APIApplication):
    def __init__(self, name: str, integration=None, **kwargs):
        super().__init__(name, integration, **kwargs)
        self.base_url = "https://api.example.com"

    def list_tools(self):
        return [self.my_tool]

    def my_tool(self):
        # Implementation here
        pass
```

### Loading an Application

```python
from universal_mcp.applications import app_from_config
from universal_mcp.config import AppConfig

app_config_pkg = AppConfig(name="my-app")
MyAppFromPackage = app_from_config(app_config_pkg)
app_pkg_instance = MyAppFromPackage()

```

## Authentication

The module supports various authentication methods:
- API Keys
- Access Tokens
- Custom Headers
- Bearer Tokens

Credentials are managed through the integration system and can be accessed via the `credentials` property.

## Error Handling

The module includes comprehensive error handling for:
- Package installation failures
- Import errors
- API request failures
- Authentication issues

## Logging

All operations are logged using the `loguru` logger, providing detailed information about:
- Application initialization
- API requests
- Authentication attempts
- Package installation
- Error conditions

## Requirements

- Python 3.8+
- httpx
- gql
- loguru
- uv (for package installation)

## Contributing

To contribute a new application:
1. Create a new package following the naming conventions
2. Implement the application class
3. Add proper error handling and logging
4. Include comprehensive documentation
5. Submit a pull request to the Universal MCP repository
