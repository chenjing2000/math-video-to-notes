class VideoToNotesError(Exception):
    """Base exception for video_to_notes."""


class ConfigError(VideoToNotesError):
    """Raised when configuration is invalid."""


class WorkspaceError(VideoToNotesError):
    """Raised when a workspace cannot be created or resolved."""


class StateError(VideoToNotesError):
    """Raised when pipeline state is invalid."""


class StageError(VideoToNotesError):
    """Raised when a pipeline stage fails."""
