"""Safe public diagnostics. Never log provider exception bodies or reasoning."""


class EnhancementError(RuntimeError):
    def __init__(self, message, record=None):
        super().__init__(message)
        self.record = record


class AuthenticationFailure(EnhancementError):
    pass


def safe_failure(error):
    if isinstance(error, EnhancementError):
        return error
    current, seen = error, set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "status_code", None) in (401, 403) or type(
            current
        ).__name__ in ("AuthenticationError", "PermissionDeniedError"):
            return AuthenticationFailure(
                "DeepSeek authentication/authorization failed (401/403); batch stopped."
            )
        current = current.__cause__ or current.__context__
    status = getattr(error, "status_code", None)
    if isinstance(status, int) and 100 <= status <= 599:
        return EnhancementError(f"AI request failed (HTTP {status}); batch stopped.")
    return EnhancementError(
        "Processing failed; publication blocked (private details suppressed)."
    )
