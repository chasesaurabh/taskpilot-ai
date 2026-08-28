"""Expected failures at the repository tool security boundary."""


class RepositoryToolError(RuntimeError):
    """Base class for safe, user-presentable tool errors."""


class RepositoryBoundaryError(RepositoryToolError):
    """A path or repository escaped the configured boundary."""


class CapabilityDeniedError(RepositoryToolError):
    """The requested capability is disabled by policy."""


class CommandDeniedError(RepositoryToolError):
    """A command did not match an allowed argument prefix."""


class FileLimitError(RepositoryToolError):
    """A read or write exceeded a configured size limit."""


class FileConflictError(RepositoryToolError):
    """A guarded write found an unexpected current file version."""
