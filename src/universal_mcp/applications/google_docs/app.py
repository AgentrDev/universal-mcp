from typing import Any

from loguru import logger

from universal_mcp.applications.application import APIApplication
from universal_mcp.exceptions import NotAuthorizedError
from universal_mcp.integrations import Integration


class GoogleDocsApp(APIApplication):
    def __init__(self, integration: Integration) -> None:
        super().__init__(name="google-docs", integration=integration)
        self.base_api_url = "https://docs.googleapis.com/v1/documents"
    
    def _get_headers(self):
        if not self.integration:
            raise ValueError("Integration not configured for GoogleDocsApp")
        credentials = self.integration.get_credentials()
        if not credentials:
            logger.warning("No Google credentials found via integration.")
            action = self.integration.authorize()
            raise NotAuthorizedError(action)
        if "headers" in credentials:
            return credentials["headers"]
        return {
            "Authorization": f"Bearer {credentials['access_token']}",
            "Content-Type": "application/json",
        }
    
    def create_document(self, title: str) -> dict[str, Any]:
        """
        Creates a new blank Google Document with the specified title.
        
        Args:
            title: The title of the document to create
            
        Returns:
            The response from the Google Docs API
        """
        url = self.base_api_url
        document_data = {"title": title}
        response = self._post(url, data=document_data)
        response.raise_for_status()
        return response.json()
    
    def get_document(self, document_id: str) -> dict[str, Any]:
        """
        Gets the latest version of the specified document.
        
        Args:
            document_id: The ID of the document to retrieve
            
        Returns:
            The response from the Google Docs API containing the document data
        """
        url = f"{self.base_api_url}/{document_id}"
        response = self._get(url)
        return response.json()
    
    def add_content(self, document_id: str, content: str, index: int = 1) -> dict[str, Any]:
        """
        Adds text content to an existing Google Document.
        
        Args:
            document_id: The ID of the document to update
            content: The text content to insert
            index: The position at which to insert the text (default: 1, beginning of document)
            
        Returns:
            The response from the Google Docs API
        """
        url = f"{self.base_api_url}/{document_id}:batchUpdate"
        batch_update_data = {
            "requests": [
                {
                    "insertText": {
                        "location": {"index": index},
                        "text": content
                    }
                }
            ]
        }
        
        response = self._post(url, data=batch_update_data)
        response.raise_for_status()
        return response.json()
    
    def list_tools(self):
        return [
           self.create_document,
           self.get_document,
           self.add_content
        ]
