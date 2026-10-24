"""The Pomoc tab (issue #156): the FAQ shipped with the app, its search and the "Przejdź do …" buttons."""

from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from nicegui.testing import User, user_simulation
from sqlalchemy import Engine

from financial_app.domain.accounts import AccountDraft, AccountType
from financial_app.domain.transactions import TransactionDraft, TransactionType
from financial_app.domain.ui_visibility import visibility_setting
from financial_app.persistence.accounts import add_account
from financial_app.persistence.db import init_db
from financial_app.persistence.settings import UI_HIDDEN, save_setting
from financial_app.persistence.transactions import add_transactions
from financial_app.ui.help import HELP_PATH, load_faq
from financial_app.ui.shell import TABS, build_shell


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    return init_db(tmp_path / "app.sqlite3")


@pytest.fixture
async def user(engine: Engine) -> AsyncIterator[User]:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open(HELP_PATH)
        yield user


def test_the_shipped_faq_covers_the_agreed_topics_and_links_only_to_tabs() -> None:
    faq = load_faq()

    titles = [section.title for section in faq]
    assert titles[:4] == ["Pierwsze kroki", "Transakcje", "Import danych", "Ceny i dane"]
    questions = [question for section in faq for question in section.questions]
    assert all(question.title and question.answer for question in questions)
    paths = {tab.path for tab in TABS}
    assert {question.goto for question in questions} - {None} <= paths
    assert {"kryptowaluty", "obligacje", "import-xtb", "import-arkusza", "stooq"} <= {q.slug for q in questions}


async def test_pomoc_is_the_last_tab_and_has_no_plus_button(user: User) -> None:
    assert TABS[-1].path == HELP_PATH
    with user.scope(marker="nav-menu"):
        await user.should_see("Pomoc")
    await user.should_see(marker="help")
    await user.should_see("Pierwsze kroki")
    await user.should_not_see(marker="add-transaction")


async def test_searching_bitcoin_leaves_the_crypto_question(user: User) -> None:
    await user.should_see(marker="faq-wplata")

    user.find(marker="faq-search").type("bitcoin")

    await user.should_see(marker="faq-kryptowaluty")
    await user.should_not_see(marker="faq-wplata")
    await user.should_not_see("Import danych")  # a section left without questions

    user.find(marker="faq-search").clear().type("nic takiego nie ma")
    await user.should_see(marker="faq-no-match")
    await user.should_not_see(marker="faq-kryptowaluty")


async def test_przejdz_do_opens_the_tab_the_answer_is_about(user: User) -> None:
    user.find(marker="faq-stooq-go").click()

    await user.should_see(marker="stooq-api-key")
    await user.should_not_see(marker="help")


async def test_przejdz_do_opens_a_tab_hidden_in_wyglad_i_widocznosc(engine: Engine) -> None:
    save_setting(engine, UI_HIDDEN, visibility_setting(frozenset({"tab-obligacje"})))
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open(HELP_PATH)

        user.find(marker="faq-obligacje-go").click()

        await user.should_not_see(marker="help")
        with user.scope(marker="page-content"):
            await user.should_see("Obligacje")


async def test_an_empty_dashboard_leads_to_the_first_steps(engine: Engine) -> None:
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")

        await user.should_see(marker="first-steps")
        user.find(marker="first-steps-help").click()

        await user.should_see(marker="help")


async def test_the_dashboard_has_no_first_steps_banner_once_a_transaction_is_saved(engine: Engine) -> None:
    account = add_account(engine, AccountDraft("IKE", "XTB", AccountType.IKE, ("PLN",))).id
    add_transactions(engine, [TransactionDraft(account, date(2026, 8, 3), TransactionType.DEPOSIT, Decimal(1000))])
    async with user_simulation(lambda: build_shell(engine)) as user:
        await user.open("/")

        await user.should_see(marker="dashboard")
        await user.should_not_see(marker="first-steps")


def test_faq_questions_are_dark_in_golden() -> None:
    from financial_app.ui.theme import CSS

    assert "body.theme-golden .k-faq { background:#171717; }" in CSS
