"""The shared step-by-step window (``ui/wizard.py``), without a browser."""

from collections.abc import AsyncIterator

import pytest
from nicegui import ui
from nicegui.testing import User, user_simulation

from financial_app.ui.wizard import Wizard, WizardStep


def page() -> None:
    """A wizard whose second step lets "Dalej" through only after its checkbox is ticked."""
    ready = {"value": False}

    def first() -> bool:
        ui.label("Treść pierwszego kroku")
        return True

    def second() -> bool:
        ui.checkbox("Gotowe", value=ready["value"], on_change=lambda e: tick(e.value)).mark("demo-ready")
        return ready["value"]

    def third() -> bool:
        ui.label("Treść ostatniego kroku")
        return True

    def tick(value: bool) -> None:
        ready["value"] = value
        wizard.render()

    with ui.card():
        steps = (WizardStep("Początek", first), WizardStep("Wybór", second), WizardStep("Koniec", third))
        wizard = Wizard("demo", steps)
        ui.button("Otwórz", on_click=wizard.open).mark("demo-open")


@pytest.fixture
async def user() -> AsyncIterator[User]:
    async with user_simulation(page) as user:
        await user.open("/")
        yield user


async def test_wizard_steps_forward_and_back_with_the_header(user: User) -> None:
    user.find(marker="demo-open").click()
    await user.should_see("Krok 1 z 3: Początek")
    await user.should_see("Treść pierwszego kroku")
    await user.should_not_see(marker="demo-back")
    user.find(marker="demo-next").click()
    await user.should_see("Krok 2 z 3: Wybór")
    user.find(marker="demo-back").click()
    await user.should_see(marker="demo-step-1")


async def test_wizard_holds_dalej_until_the_step_is_ready(user: User) -> None:
    user.find(marker="demo-open").click()
    user.find(marker="demo-next").click()
    await user.should_see(marker="demo-step-2")
    assert not user.find(marker="demo-next", kind=ui.button).elements.pop().enabled
    user.find(marker="demo-ready").click()
    assert user.find(marker="demo-next", kind=ui.button).elements.pop().enabled
    user.find(marker="demo-next").click()
    await user.should_see(marker="demo-step-3")
    await user.should_not_see(marker="demo-next")
    await user.should_see(marker="demo-close")


async def test_wizard_opens_again_on_its_first_step(user: User) -> None:
    user.find(marker="demo-open").click()
    user.find(marker="demo-next").click()
    await user.should_see(marker="demo-step-2")
    user.find(marker="demo-close").click()
    user.find(marker="demo-open").click()
    await user.should_see(marker="demo-step-1")
