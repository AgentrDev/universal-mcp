import csv
from pathlib import Path

from universal_mcp.applications import app_from_slug


def discover_available_app_slugs():
    apps_dir = Path(__file__).resolve().parent.parent / "applications"
    app_slugs = []
    
    for item in apps_dir.iterdir():
        if not item.is_dir() or item.name.startswith('_'):
            continue
        
        if (item / "app.py").exists():
            slug = item.name.replace("_", "-")
            app_slugs.append(slug)
    
    return app_slugs

def extract_app_tools(app_slugs):
    all_apps_tools = []
    
    for slug in app_slugs:
        try:
            print(f"Loading app: {slug}")
            app_class = app_from_slug(slug)
            
            app_instance = app_class(integration=None)
            
            tools = app_instance.list_tools()
            
            for tool in tools:
                tool_name = tool.__name__
                description = tool.__doc__.strip().split('\n')[0] if tool.__doc__ else "No description"
                
                all_apps_tools.append({
                    "app_name": slug,
                    "tool_name": tool_name,
                    "description": description
                })
                
        except Exception as e:
            print(f"Error loading app {slug}: {e}")
    
    return all_apps_tools

def write_to_csv(app_tools, output_file="app_tools.csv"):
    fieldnames = ["app_name", "tool_name", "description"]
    
    with open(output_file, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(app_tools)
    
    print(f"CSV file created: {output_file}")

def main():
    app_slugs = discover_available_app_slugs()
    print(f"Found {len(app_slugs)} app slugs: {', '.join(app_slugs)}")
    
    app_tools = extract_app_tools(app_slugs)
    print(f"Extracted {len(app_tools)} tools from all apps")
    
    write_to_csv(app_tools)

if __name__ == "__main__":
    main()