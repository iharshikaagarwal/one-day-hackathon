class UserFacingError(Exception):
    """Error safe to show in the Streamlit UI."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
