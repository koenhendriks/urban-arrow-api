class UrbanArrowError(Exception):
    pass


class UrbanArrowAuthError(UrbanArrowError):
    """Credentials are invalid or the refresh token was revoked; the user must log in again."""


class UrbanArrowConnectionError(UrbanArrowError):
    pass


class UrbanArrowApiError(UrbanArrowError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


class UrbanArrowCaptchaRequired(UrbanArrowAuthError):
    pass


class UrbanArrowMfaRequired(UrbanArrowAuthError):
    pass
