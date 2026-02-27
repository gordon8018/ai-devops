from __future__ import annotations

import re
from types import TracebackType
from typing import Type


class RaisesContext:
    def __init__(self, expected_exception: Type[BaseException], match: str | None = None) -> None:
        self.expected_exception = expected_exception
        self.match = match

    def __enter__(self) -> "RaisesContext":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if exc_type is None:
            raise AssertionError(f"Did not raise {self.expected_exception.__name__}")
        if not issubclass(exc_type, self.expected_exception):
            return False
        if self.match and exc is not None and re.search(self.match, str(exc)) is None:
            raise AssertionError(
                f"Exception message did not match {self.match!r}: {exc}"
            )
        return True


def raises(expected_exception: Type[BaseException], match: str | None = None) -> RaisesContext:
    return RaisesContext(expected_exception, match=match)
