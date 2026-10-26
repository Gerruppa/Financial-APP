"""Dialogs the user can drag by their card, with no dimmed backdrop, so the screen behind them stays readable."""

from nicegui import context, ui

# A delegated listener, so it also covers dialogs opened after the page was built. Dragging starts on the card
# itself, not on a field or button, and the card keeps its offset when the dialog is shown again.
_DRAG_SCRIPT = """
<script>
(() => {
  let drag = null;
  const CONTROLS = 'input, textarea, select, button, a, .q-field, .q-select, .q-btn';
  document.addEventListener('mousedown', (e) => {
    const card = e.target.closest('.q-dialog .q-card');
    if (!card || e.button !== 0 || e.target.closest(CONTROLS)) return;
    drag = { card, x: e.clientX, y: e.clientY,
             dx: Number(card.dataset.dragX || 0), dy: Number(card.dataset.dragY || 0) };
  });
  document.addEventListener('mousemove', (e) => {
    if (!drag) return;
    let dx = drag.dx + e.clientX - drag.x;
    let dy = drag.dy + e.clientY - drag.y;
    // Keep at least half of the card inside the window: its untransformed box, shifted by the offset
    const rect = drag.card.getBoundingClientRect();
    const baseLeft = rect.left - Number(drag.card.dataset.dragX || 0);
    const baseTop = rect.top - Number(drag.card.dataset.dragY || 0);
    const w = rect.width;
    const h = rect.height;
    dx = Math.min(Math.max(dx, -baseLeft - w / 2), window.innerWidth - baseLeft - w / 2);
    dy = Math.min(Math.max(dy, -baseTop - h / 2), window.innerHeight - baseTop - h / 2);
    drag.card.style.transform = `translate(${dx}px, ${dy}px)`;
    drag.card.dataset.dragX = dx;
    drag.card.dataset.dragY = dy;
  });
  document.addEventListener('mouseup', () => { drag = null; });
  // Quasar ignores Esc on a seamless dialog; an open select menu or date popup takes the Esc first
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || e.defaultPrevented || document.querySelector('.q-menu, .q-popup-edit')) return;
    emitEvent('movable_dialog_escape');
  });
})();
</script>
"""


def close_topmost_dialog() -> None:
    """Close the newest open movable dialog; none when a regular dialog is open, which closes itself on Esc."""
    dialogs = [
        element for element in context.client.elements.values() if isinstance(element, ui.dialog) and element.value
    ]
    if dialogs and "seamless" in dialogs[-1]._props:  # noqa: SLF001
        dialogs[-1].close()


def install_movable_dialogs() -> None:
    """Add the drag and Esc behaviour to the page; call once when building the shell."""
    ui.add_head_html(_DRAG_SCRIPT)
    ui.on("movable_dialog_escape", close_topmost_dialog)


def movable_dialog() -> ui.dialog:
    """A dialog without the dimmed backdrop; its card can be dragged to any place on screen."""
    return ui.dialog().props("seamless")
