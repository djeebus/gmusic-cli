import datetime
import functools
import time


SECONDS_IN_MINUTE = 60
MINUTES_IN_HOUR = 60
HOURS_IN_DAY = 24
SECONDS_IN_HOUR = MINUTES_IN_HOUR * SECONDS_IN_MINUTE
SECONDS_IN_DAY = HOURS_IN_DAY * SECONDS_IN_HOUR


def _format_delta(diff: datetime.timedelta):
    diff = int(diff.total_seconds())
    d, remainder = divmod(diff, SECONDS_IN_DAY)
    h, remainder = divmod(diff, SECONDS_IN_HOUR)
    m, s = divmod(remainder, SECONDS_IN_MINUTE)

    if d > 0:
        return f'{d}d {h}h {m}m {s}s'

    if h > 0:
        return f'{h}h {m}m {s}s'

    if m > 0:
        return f'{m}m {s}s'

    return str(s) + 's'


class ProgressTimer:
    INTERVAL = 10.0

    def __init__(self, total, report):
        self.report = report
        self.total = total
        self._completed = 0
        self._start = time.time()
        self._last_report = self._start

    def progress(self, completed):
        self._completed = completed
        now = time.time()
        if now - self._last_report < self.INTERVAL:
            return

        elapsed = time.time() - self._start
        elapsed_per = elapsed / self._completed
        total_time = elapsed_per * self.total
        remaining_time = total_time - elapsed

        total = datetime.timedelta(seconds=total_time)
        elapsed = datetime.timedelta(seconds=elapsed)
        remaining = datetime.timedelta(seconds=remaining_time)
        progress = map(_format_delta, (elapsed, remaining, total))
        progress = ' / '.join(progress)

        self.report(f'{self._completed}/{self.total} ({progress})')
        self._last_report = now


def to(cls):
    def to_wrapper(func):
        @functools.wraps(func)
        def to_inner(*args, **kwargs):
            results = func(*args, **kwargs)
            return cls(results)
        return to_inner
    return to_wrapper
