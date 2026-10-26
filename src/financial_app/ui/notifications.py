"""The header bell (issue #176): a list of what the app reminds the user of, the number of unread ones on the bell.

Opening the list marks what it shows as read; the number comes back when a reminder changes (a new Draft falls due, a
refresh fails again), because a reminder's key says its state. It replaced the header's "do zatwierdzenia" counters."""

from nicegui import ui
from sqlalchemy import Engine

from financial_app.domain.notifications import Notification, unread
from financial_app.sources.current_prices import LatestRates
from financial_app.sources.notifications import collect_notifications, load_read, save_read


class NotificationBell:
    """The bell button with its menu, redrawn by ``refresh`` when the state it reminds of may have changed."""

    def __init__(self, engine: Engine, rates: LatestRates) -> None:
        self.engine = engine
        self.rates = rates
        self.notifications: list[Notification] = []
        self.badge: ui.badge | None = None

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
        self.badge = None
        if fresh:
            with button:
                self.badge = (
                    ui.badge(str(len(fresh))).props("rounded floating color=negative").mark("notifications-count")
                )
        button.on_click(self.mark_read)
        with button, ui.menu().props("auto-close").classes("min-w-[24rem]").mark("notifications-menu"):
            if not self.notifications:
                ui.menu_item("Nic do przypomnienia.").props("disable").mark("notifications-empty")
            for notification in self.notifications:
                item = ui.menu_item(notification.text, on_click=lambda n=notification: ui.navigate.to(n.path))
                item.mark("notification-unread" if notification.key in fresh else "notification")
                if notification.key in fresh:
                    item.classes("font-bold")

    def mark_read(self) -> None:
        """Remember everything listed as read; the number goes, the list keeps its bold items until the next redraw."""
        save_read(self.engine, frozenset(n.key for n in self.notifications))
        if self.badge is not None:
            self.badge.delete()
            self.badge = None
