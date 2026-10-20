"""Shared test setup."""

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from nicegui.testing import User
from nicegui.testing.user_download import UserDownload


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark the tests of every module that drives the UI through user_simulation, so ``-m "not ui"`` skips them."""
    for item in items:
        module = getattr(item, "module", None)
        if module is not None and hasattr(module, "user_simulation"):
            item.add_marker(pytest.mark.ui)


# NiceGUI's should_see waits 0.3 s and should_not_see 0.15 s, too short on a slow CI runner for what a background task
# (a refresh, a search) shows; give both 5 s. A passing check still returns as soon as the page matches.
_SEE_RETRIES = 50  # 0.1 s each
_NOT_SEE_RETRIES = 100  # 0.05 s each
# user.download.next() waits 1 s for an export's file, which a busy machine misses; give it 5 s as well
_DOWNLOAD_TIMEOUT = 5.0
# A failed check prints the whole page tree, hundreds of lines with the Dashboard's charts; the first ones tell enough
_FAILURE_LINES = 40


def _shortened(message: str) -> str:
    lines = message.splitlines()
    if len(lines) <= _FAILURE_LINES:
        return message
    return "\n".join([*lines[:_FAILURE_LINES], f"... {len(lines) - _FAILURE_LINES} more lines of the page tree"])


@pytest.fixture(autouse=True)
def patient_user(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    should_see, should_not_see = User.should_see, User.should_not_see

    async def see(self: User, *args: Any, retries: int = _SEE_RETRIES, **kwargs: Any) -> None:
        try:
            await should_see(self, *args, retries=retries, **kwargs)
        except AssertionError as error:
            raise AssertionError(_shortened(str(error))) from None

    async def not_see(self: User, *args: Any, retries: int = _NOT_SEE_RETRIES, **kwargs: Any) -> None:
        try:
            await should_not_see(self, *args, retries=retries, **kwargs)
        except AssertionError as error:
            raise AssertionError(_shortened(str(error))) from None

    monkeypatch.setattr(User, "should_see", see)
    monkeypatch.setattr(User, "should_not_see", not_see)

    next_download = UserDownload.next

    async def download(self: UserDownload, *, timeout: float = _DOWNLOAD_TIMEOUT) -> httpx.Response:
        return await next_download(self, timeout=timeout)

    monkeypatch.setattr(UserDownload, "next", download)
    yield
