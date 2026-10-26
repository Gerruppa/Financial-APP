"""The header bell (issue #176): a list of what the app reminds the user of, a dot on the bell while any is unread.

Opening the list marks what it shows as read; the dot comes back when a reminder changes (a new Draft falls due, a
refresh fails again), because a reminder's key says its state. The header's counters stay beside it."""

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.notifications import Notification, unread
from financial_app.sources.current_prices import LatestRates
from financial_app.sources.notifications import collect_notifications, load_read, save_read


class NotificationBell:
    """The bell button with its menu, redrawn by ``refresh`` when the state it reminds of may have changed."""

    def __init__(self, engine: Engine, rates: LatestRates, count_badge: bool = False) -> None:
        self.count_badge = count_badge
        self.engine = engine
        self.rates = rates
        self.notifications: list[Notification] = []
        self.dot: ui.badge | None = None

    def build(self) -> None:
        self.content()

    @ui.refreshable_method
    def content(self) -> None:
        self.notifications = collect_notifications(self.engine, self.rates)
        read = load_read(self.engine)
        fresh = {n.key for n in unread(self.notifications, read)}
        button = ui.button(icon="notifications").props('flat round color=ink aria-label="Powiadomienia"')
        button.mark("notifications-bell")
        button.tooltip("Powiadomienia")
        self.dot = None
        if fresh:
            with button:
                self.dot = (
                    ui.badge(str(len(fresh)) if self.count_badge else "")
                    .props("rounded floating color=negative")
                    .mark("notifications-dot")
                )
        button.on_click(self.mark_read)
        with button, ui.menu().props("auto-close").mark("notifications-menu"):
            if not self.notifications:
                ui.menu_item("Nic do przypomnienia.").props("disable").mark("notifications-empty")
            for notification in self.notifications:
                item = ui.menu_item(notification.text, on_click=lambda n=notification: ui.navigate.to(n.path))
                item.mark("notification-unread" if notification.key in fresh else "notification")
                if notification.key in fresh:
                    item.classes("font-bold")

    def mark_read(self) -> None:
        """Remember everything listed as read; the dot goes, the list keeps its bold items until the next redraw."""
        save_read(self.engine, frozenset(n.key for n in self.notifications))
        if self.dot is not None:
            self.dot.delete()
            self.dot = None
