class ServiceNowError(Exception):
    def __init__(self, message: str, code: str = "UNKNOWN_ERROR"):
        super().__init__(message)
        self.code = code


class ErrorHandler:
    def handle_error(self, error):
        # Basic error handling implementation
        print(f"Handling error: {error}")
