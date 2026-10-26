"""Discreet mode: the header's eye button blurs every amount on the page, for working with someone looking on.

Amounts are plain text in tables, cards and labels, so a small script marks the element holding any text that looks
like one of ``domain/formatting.py``'s amounts (``MONEY_PATTERN``) with ``k-money``, and ``body.k-discreet`` blurs those
and the charts; hovering an amount shows it. The script only adds a class, never replaces a node, so NiceGUI's own
redraws keep working; a ``MutationObserver`` marks what a redraw brings. Switching needs no reload: the button toggles
the body's class.
"""

from nicegui import ui
from sqlalchemy import Engine

from financial_app.persistence.settings import UI_DISCREET, load_setting, save_setting

# A formatted amount or rate: digits grouped by (non-breaking) spaces, a decimal comma, then "zł" or a currency code
MONEY_PATTERN = r"\d[\d\s]*,\d{2,}\s(?:zł|[A-Z]{3})"

_CSS = """
body.k-discreet .k-money, body.k-discreet .nicegui-echart { filter:blur(7px); transition:filter .15s; }
body.k-discreet .k-money:hover, body.k-discreet .nicegui-echart:hover { filter:none; }
"""

_SCRIPT = """
(() => {
  if (window.kDiscreet) return;
  const money = new RegExp("PATTERN");
  const mark = (root) => {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const parent = node.parentElement;
      if (parent && !parent.classList.contains('k-money') && money.test(node.nodeValue)
          && !['SCRIPT', 'STYLE', 'TEXTAREA'].includes(parent.tagName)) parent.classList.add('k-money');
    }
  };
  window.kDiscreet = new MutationObserver((changes) => {
    for (const change of changes) {
      const target = change.target.nodeType === Node.TEXT_NODE ? change.target.parentElement : change.target;
      if (target) mark(target);
    }
  });
  window.kDiscreet.observe(document.body, {childList: true, subtree: true, characterData: true});
  mark(document.body);
})();
""".replace("PATTERN", MONEY_PATTERN.replace("\\", "\\\\"))


class DiscreetChoice:
    """Whether the amounts are blurred, remembered in ``app_settings``."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.on = load_setting(engine, UI_DISCREET) == "1"

    def toggle(self) -> None:
        self.on = not self.on
        save_setting(self.engine, UI_DISCREET, "1" if self.on else "0")


def apply_discreet(choice: DiscreetChoice) -> None:
    """Make the page being built able to blur its amounts, in the remembered state."""
    ui.add_css(_CSS)
    ui.query("body").classes("k-discreet" if choice.on else "")
    ui.add_body_html(f"<script>{_SCRIPT}</script>")


def build_discreet_button(choice: DiscreetChoice) -> None:
    """The eye button in the header, marked ``discreet-toggle``: closed eye while the amounts are blurred."""
    button = ui.button(icon="visibility_off" if choice.on else "visibility")
    button.props('flat round color=ink aria-label="Tryb dyskrecji"').mark("discreet-toggle")
    button.tooltip("Tryb dyskrecji: ukryj kwoty")

    def toggle() -> None:
        choice.toggle()
        ui.run_javascript(f"document.body.classList.toggle('k-discreet', {str(choice.on).lower()})")
        button.props(f"icon={'visibility_off' if choice.on else 'visibility'}")

    button.on_click(toggle)
