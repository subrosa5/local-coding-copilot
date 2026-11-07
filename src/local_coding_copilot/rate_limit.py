import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable


class RateLimitExceeded(PermissionError):
    pass


class RateLimiter:
    def __init__(
        self,
        requests_per_window: int = 60,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = requests_per_window
        self._window = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, user_id: str) -> None:
        now = self._clock()
        with self._lock:
            events = self._events[user_id]
            while events and events[0] <= now - self._window:
                events.popleft()
            if len(events) >= self._limit:
                raise RateLimitExceeded("Request rate limit exceeded")
            events.append(now)
