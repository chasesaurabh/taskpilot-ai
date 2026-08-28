"""Model configuration and invocation failures."""


class ModelError(RuntimeError):
    """Base error for safe presentation at the graph boundary."""


class ModelConfigurationError(ModelError):
    """Provider or routing configuration cannot satisfy a request."""


class ModelResponseError(ModelError):
    """A provider did not return the requested structured response."""
