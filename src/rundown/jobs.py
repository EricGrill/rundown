"""In-session research jobs; saved research remains in the catalog."""
from dataclasses import dataclass, field
from threading import Event
from time import monotonic


@dataclass
class ResearchJob:
    id: int
    full_name: str
    action: str = "research"
    state: str = "queued"
    created: float = field(default_factory=monotonic)
    started: float | None = None
    finished: float | None = None
    message: str = "Waiting to start."
    cancel_event: Event = field(default_factory=Event)

    @property
    def elapsed(self) -> str:
        seconds = int((self.finished or monotonic()) - (self.started or self.created))
        return f"{seconds // 60}:{seconds % 60:02d}"

    @property
    def terminal(self) -> bool:
        return self.state in {"completed", "failed", "cancelled"}
