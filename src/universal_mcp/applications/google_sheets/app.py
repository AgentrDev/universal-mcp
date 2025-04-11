from typing import Any

from loguru import logger

from universal_mcp.applications.application import APIApplication
from universal_mcp.exceptions import NotAuthorizedError
from universal_mcp.integrations import Integration


class GoogleSheetsApp(APIApplication):
    """
    Application for interacting with Google Sheets API.
    Provides tools to create and manage Google Spreadsheets.
    """
    
    def __init__(self, integration: Integration | None = None) -> None:
        super().__init__(name="google-sheets", integration=integration)
        self.base_api_url = "https://sheets.googleapis.com/v4/spreadsheets"
    
    def _get_headers(self):
        if not self.integration:
            raise ValueError("Integration not configured for GoogleSheetsApp")
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
    
    def create_spreadsheet(self, title: str) -> dict[str, Any]:
        """
        Creates a new blank Google Spreadsheet with the specified title.
        
        Args:
            title: The title of the spreadsheet to create
            
        Returns:
            The response from the Google Sheets API
        """
        url = self.base_api_url
        spreadsheet_data = {
            "properties": {
                "title": title
            }
        }
        
        response = self._post(url, data=spreadsheet_data)
        return response.json()
    
    def get_spreadsheet(self, spreadsheet_id: str) -> dict[str, Any]:
        """
        Returns the spreadsheet details.
        
        Args:
            spreadsheet_id: The ID of the spreadsheet to retrieve
            
        Returns:
            The response from the Google Sheets API containing the spreadsheet data
        """
        url = f"{self.base_api_url}/{spreadsheet_id}"
        response = self._get(url)
        return response.json()
    
    def batch_get_values(self, spreadsheet_id: str, ranges: list[str] = None) -> dict[str, Any]:
        """
        Returns one or more ranges of values from a spreadsheet.
        
        Args:
            spreadsheet_id: The ID of the spreadsheet to retrieve values from
            ranges: Optional list of A1 notation or R1C1 notation ranges to retrieve values from
                   (e.g. ['Sheet1!A1:B2', 'Sheet2!C3:D4'])
            
        Returns:
            The response from the Google Sheets API containing the requested values
        """
        url = f"{self.base_api_url}/{spreadsheet_id}/values:batchGet"
        
        params = {}
        if ranges:
            params["ranges"] = ranges
            
        response = self._get(url, params=params)
        return response.json()
    
    def clear_values(self, spreadsheet_id: str, range: str) -> dict[str, Any]:
        """
        Clears values from a spreadsheet. Only values are cleared -- all other properties 
        of the cell (such as formatting, data validation, etc.) are kept.
        
        Args:
            spreadsheet_id: The ID of the spreadsheet to update
            range: The A1 notation or R1C1 notation of the values to clear
                  (e.g. 'Sheet1!A1:B2')
            
        Returns:
            The response from the Google Sheets API
        """
        url = f"{self.base_api_url}/{spreadsheet_id}/values/{range}:clear"
        
        response = self._post(url, data={})
        return response.json()
    
    def update_values(
        self, 
        spreadsheet_id: str, 
        range: str, 
        values: list[list[Any]], 
        value_input_option: str = "RAW"
    ) -> dict[str, Any]:
        """
        Sets values in a range of a spreadsheet. 
        
        Args:
            spreadsheet_id: The ID of the spreadsheet to update
            range: The A1 notation of the values to update (e.g. 'Sheet1!A1:B2')
            values: The data to write, as a list of lists (rows of values)
            value_input_option: How the input data should be interpreted. 
                                Accepted values are:
                                - "RAW": The values will be stored as-is
                                - "USER_ENTERED": The values will be parsed as if the user typed them into the UI
                
        Returns:
            The response from the Google Sheets API
        """
        url = f"{self.base_api_url}/{spreadsheet_id}/values/{range}"
        
        params = {
            "valueInputOption": value_input_option
        }
        
        data = {
            "range": range,
            "values": values
        }
        
        response = self._put(url, data=data, params=params)
        return response.json()
    
    def list_tools(self):
        """Returns a list of methods exposed as tools."""
        return [
           self.create_spreadsheet,
           self.get_spreadsheet,
           self.batch_get_values,
           self.clear_values,
           self.update_values
        ]
