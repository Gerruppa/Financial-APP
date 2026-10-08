"""PROTOTYPE - throwaway, do not build on this.

Question: what should the app shell look like in NiceGUI (navigation between
the spreadsheet's tabs, Portfolio view, transaction entry form)?

Three structurally different variants on one page, switchable via ?variant=A|B|C
and the floating bar at the bottom (or the left/right arrow keys).
All data is invented and lives in memory; nothing is saved.

Run:  .venv/Scripts/python.exe prototypes/ui_shell_prototype.py
"""
from nicegui import ui

VARIANTS = {'A': 'Zakładki jak w arkuszu', 'B': 'Menu boczne i karty', 'C': 'Gęsty arkusz'}
TABS = ['Dashboard', 'Wyniki', 'Portfolio', 'Transakcje', 'Strategie inwestycyjne', 'Obligacje', 'Benchmarki', 'Ustawienia']

# --- fake data (invented) -----------------------------------------------------
ACCOUNTS = {
    'IKE (XTB)': {'cash': ['PLN'], 'fx_fee': 0.5, 'broker': 'XTB'},
    'IKZE (XTB)': {'cash': ['PLN'], 'fx_fee': 0.5, 'broker': 'XTB'},
    'Konto zwykłe (mBank)': {'cash': ['PLN', 'USD'], 'fx_fee': 0.0, 'broker': 'mBank'},
    'Obligacje (PKO)': {'cash': ['PLN'], 'fx_fee': 0.0, 'broker': 'PKO'},
}
POSITIONS = [
    {'konto': 'IKE (XTB)', 'instrument': 'Vanguard FTSE All-World (VWCE)', 'klasa': 'Akcje zagraniczne',
     'waluta': 'EUR', 'liczba': 42, 'koszt': 22150.00, 'wartosc': 24980.40},
    {'konto': 'IKE (XTB)', 'instrument': 'iShares Core S&P 500 (CSPX)', 'klasa': 'Akcje zagraniczne',
     'waluta': 'USD', 'liczba': 9, 'koszt': 21890.10, 'wartosc': 23120.75},
    {'konto': 'IKE (XTB)', 'instrument': 'Gotówka', 'klasa': 'Gotówka',
     'waluta': 'PLN', 'liczba': None, 'koszt': 312.55, 'wartosc': 312.55},
    {'konto': 'IKZE (XTB)', 'instrument': 'Beta ETF WIG20TR', 'klasa': 'Akcje polskie',
     'waluta': 'PLN', 'liczba': 60, 'koszt': 6020.00, 'wartosc': 5840.40},
    {'konto': 'Konto zwykłe (mBank)', 'instrument': 'Złoto (moneta 1 oz)', 'klasa': 'Metale i surowce',
     'waluta': 'USD', 'liczba': 2, 'koszt': 19800.00, 'wartosc': 21430.00},
    {'konto': 'Obligacje (PKO)', 'instrument': 'EDO0735', 'klasa': 'Obligacje skarbowe polskie',
     'waluta': 'PLN', 'liczba': 150, 'koszt': 15000.00, 'wartosc': 15912.30},
]
for p in POSITIONS:
    p['zysk'] = round(p['wartosc'] - p['koszt'], 2)
    p['zysk_pct'] = round(100 * p['zysk'] / p['koszt'], 2)

TRANSACTIONS = [
    {'data': '2026-04-17', 'konto': 'IKE (XTB)', 'typ': 'Wpłata', 'instrument': 'Gotówka', 'liczba': 1, 'cena': 25000, 'kwota': 25000.00},
    {'data': '2026-04-18', 'konto': 'IKE (XTB)', 'typ': 'Zakup', 'waluta': 'EUR', 'instrument': 'VWCE', 'liczba': 42, 'cena': 122.40, 'kwota': 22150.00},
    {'data': '2026-05-02', 'konto': 'IKE (XTB)', 'typ': 'Zakup', 'waluta': 'USD', 'instrument': 'CSPX', 'liczba': 9, 'cena': 618.20, 'kwota': 21890.10},
    {'data': '2026-05-20', 'konto': 'Obligacje (PKO)', 'typ': 'Zakup', 'instrument': 'EDO0735', 'liczba': 150, 'cena': 100, 'kwota': 15000.00},
    {'data': '2026-06-11', 'konto': 'IKZE (XTB)', 'typ': 'Zakup', 'instrument': 'ETFBW20TR', 'liczba': 60, 'cena': 100.33, 'kwota': 6020.00},
    {'data': '2026-08-11', 'konto': 'Konto zwykłe (mBank)', 'typ': 'Zakup', 'waluta': 'USD', 'instrument': 'Złoto 1 oz', 'liczba': 2, 'cena': 2530, 'kwota': 19800.00},
]
HISTORY_DATES = ['05-01', '05-15', '06-01', '06-15', '07-01', '07-15', '08-01', '08-15', '09-01', '09-15', '10-01']
HISTORY_VALUE = [25000, 47300, 47900, 63500, 64800, 70100, 70900, 91200, 92800, 90400, 91596]
HISTORY_DEPOSITS = [25000, 47000, 47000, 62000, 62000, 68000, 68000, 88000, 88000, 88000, 88000]

PLAN = {'deposit': 2000.0}


def split_deposit(values: dict[str, float], targets: dict[str, float], amount: float) -> dict[str, float]:
    """Split a planned deposit across classes without selling: fill the most under-target classes first,
    so that afterwards every bought class sits at the same fraction of its target ("water-filling")."""
    t = {c: targets[c] / 100 for c in targets if targets[c] > 0}
    if amount <= 0 or not t:
        return {}
    lo, hi = 0.0, max(values.get(c, 0) / t[c] for c in t) + amount / min(t.values())
    for _ in range(100):  # find level k with sum(max(0, k*t_c - v_c)) == amount
        k = (lo + hi) / 2
        if sum(max(0.0, k * t[c] - values.get(c, 0)) for c in t) > amount:
            hi = k
        else:
            lo = k
    return {c: round(max(0.0, lo * t[c] - values.get(c, 0)), 2) for c in t}


# Allocation Targets per Asset Class (editable on the Dashboard)
TARGETS = {'Obligacje skarbowe polskie': 50.0, 'Akcje zagraniczne': 35.0, 'Akcje polskie': 5.0,
           'Metale i surowce': 10.0, 'Gotówka': 0.0}

# Targets inside an Asset Class, per Instrument (% of the class). May name instruments not held yet.
SUBTARGETS: dict[str, dict[str, float]] = {
    'Akcje zagraniczne': {'iShares Core S&P 500 (CSPX)': 50.0, 'iShares MSCI ACWI (SSAC)': 50.0,
                          'Vanguard FTSE All-World (VWCE)': 0.0},
}
CATALOG = {  # instruments available to add to a class strategy (invented)
    'Akcje zagraniczne': ['iShares MSCI ACWI (SSAC)', 'Vanguard S&P 500 (VUAA)', 'iShares Core MSCI EM IMI (EMIM)'],
    'Akcje polskie': ['Beta ETF WIG20TR', 'Beta ETF mWIG40TR', 'Beta ETF sWIG80TR'],
    'Obligacje skarbowe polskie': ['EDO0735', 'COI1029', 'ROD1038'],
    'Metale i surowce': ['Złoto (moneta 1 oz)', 'Srebro (moneta 1 oz)'],
}
OPEN: set[str] = set()  # expanded classes on the strategy page

TOTAL = sum(p['wartosc'] for p in POSITIONS)
COST = sum(p['koszt'] for p in POSITIONS)


def pln(x: float) -> str:
    # non-breaking spaces so an amount never wraps between digits and "zł"
    return f'{x:,.2f} zł'.replace(',', ' ').replace('.', ',')


def pct(x: float, signed: bool = False, unit: str = '%') -> str:
    return (f'{x:+.1f}' if signed else f'{x:.1f}').replace('.', ',') + ' ' + unit


def allocation() -> dict[str, float]:
    out: dict[str, float] = {}
    for p in POSITIONS:
        out[p['klasa']] = out.get(p['klasa'], 0) + p['wartosc']
    return out


# --- shared bits (charts, form) -----------------------------------------------
def value_chart(height: str = '260px') -> None:
    ui.echart({
        'tooltip': {'trigger': 'axis'},
        'legend': {'data': ['Wartość konta', 'Wpłaty netto']},
        'xAxis': {'type': 'category', 'data': HISTORY_DATES},
        'yAxis': {'type': 'value'},
        'series': [
            {'name': 'Wartość konta', 'type': 'line', 'data': HISTORY_VALUE, 'smooth': True, 'areaStyle': {}},
            {'name': 'Wpłaty netto', 'type': 'line', 'data': HISTORY_DEPOSITS, 'step': 'end'},
        ],
    }).style(f'height: {height}')


def allocation_chart(height: str = '260px') -> None:
    ui.echart({
        'tooltip': {'trigger': 'item'},
        'series': [{'type': 'pie', 'radius': ['45%', '70%'],
                    'data': [{'name': k, 'value': round(v, 2)} for k, v in allocation().items()]}],
    }).style(f'height: {height}')


def transaction_form(on_done=None, initial: dict | None = None, on_delete=None) -> None:
    """Fields change with the transaction type and with FX conversion (spec 3.3).
    With `initial` the form edits an existing Transaction and offers deletion."""
    initial = initial or {}
    state = {'typ': initial.get('typ', 'Zakup'), 'konto': initial.get('konto', 'IKE (XTB)'),
             'waluta': initial.get('waluta', 'PLN' if initial else 'USD'), 'xtb_fee': False}

    @ui.refreshable
    def fields() -> None:
        typ, konto, waluta = state['typ'], state['konto'], state['waluta']
        # PLN-only account buying/selling in a foreign currency: the only case where conversion happens.
        foreign_on_pln_account = waluta not in ACCOUNTS[konto]['cash'] and typ in ('Zakup', 'Sprzedaż', 'Dywidenda')
        if typ in ('Zakup', 'Sprzedaż'):
            ui.input('Instrument', placeholder='np. CSPX', value=initial.get('instrument', '')).classes('w-full')
            with ui.row().classes('w-full no-wrap'):
                ui.number('Liczba', value=initial.get('liczba', 1)).classes('grow')
                ui.number(f'Cena ({waluta})', value=initial.get('cena', 100)).classes('grow')
            ui.number(f'Prowizja ({waluta})', value=0).classes('w-full')
        elif typ in ('Wpłata', 'Wypłata', 'Koszty'):
            ui.number(f'Kwota ({waluta})', value=initial.get('kwota', 1000)).classes('w-full')
        elif typ == 'Dywidenda':
            ui.input('Instrument').classes('w-full')
            with ui.row().classes('w-full no-wrap'):
                ui.number(f'Brutto ({waluta})').classes('grow')
                ui.number(f'Podatek u źródła ({waluta})').classes('grow')
        fee = ACCOUNTS[konto]['fx_fee']
        if foreign_on_pln_account:
            if fee:  # checkbox only on Accounts with an FX Conversion Fee configured (Q56b)
                def toggle_fee(e):
                    state['xtb_fee'] = e.value
                    fields.refresh()
                ui.checkbox(f"Prowizja {ACCOUNTS[konto]['broker']} (przewalutowanie {fee:g}%)".replace('.', ','),
                            value=state['xtb_fee'], on_change=toggle_fee)
            if fee and state['xtb_fee']:
                with ui.card().classes('w-full bg-amber-50'):
                    ui.label(f'Przewalutowanie {waluta}→PLN z opłatą {fee:g}%'.replace('.', ',')).classes('font-medium')
                    ui.number(f"Kwota PLN pobrana przez {ACCOUNTS[konto]['broker']} *").classes('w-full')
                    ui.label('Kurs efektywny i opłata zostaną wyliczone z tej kwoty.').classes('text-xs text-gray-600')
            else:
                ui.number(f'Kurs {waluta}/PLN', placeholder='puste = kurs NBP z dnia przed transakcją').classes('w-full')
        elif waluta != 'PLN' and len(ACCOUNTS[konto]['cash']) > 1:
            ui.select(['z gotówki ' + waluta, 'z PLN (przewalutowanie)'], label='Płatność',
                      value='z gotówki ' + waluta).classes('w-full')

    def set_(key):
        def handler(e):
            state[key] = e.value
            fields.refresh()
        return handler

    ui.toggle(['Zakup', 'Sprzedaż', 'Wpłata', 'Wypłata', 'Dywidenda', 'Koszty'], value=state['typ'],
              on_change=set_('typ')).props('dense no-caps')
    with ui.row().classes('w-full no-wrap'):
        ui.select(list(ACCOUNTS), label='Konto', value=state['konto'], on_change=set_('konto')).classes('grow')
        ui.select(['PLN', 'USD', 'EUR', 'GBP'], label='Waluta', value=state['waluta'],
                  on_change=set_('waluta')).classes('w-28')
    ui.input('Data', value=initial.get('data', '2026-10-08')).classes('w-full')
    fields()
    ui.input('Komentarz').classes('w-full')

    def save():
        ui.notify('PROTOTYP: nic nie zapisano', type='info')
        if on_done:
            on_done()

    with ui.row().classes('w-full no-wrap'):
        if on_delete:
            ui.button('Usuń', icon='delete', on_click=on_delete).props('flat color=red')
        ui.button('Zapisz zmiany' if initial else 'Zapisz transakcję', on_click=save).classes('grow')


# --- Variant A: top tabs like the spreadsheet, side panel form ----------------------
def variant_a() -> None:
    with ui.header().classes('bg-slate-800 items-center'):
        ui.label('Moje inwestycje').classes('text-lg font-bold')
        ui.space()
        ui.label(f'Wartość: {pln(TOTAL)}').classes('text-sm')
        ui.button(icon='refresh', on_click=lambda: ui.notify('Odświeżanie wycen…')).props('flat color=white')
    form_drawer = ui.right_drawer(value=False).classes('bg-gray-50').props('width=380 bordered')
    with form_drawer:
        ui.label('Nowa transakcja').classes('text-lg font-bold')
        transaction_form(on_done=form_drawer.hide)

    with ui.tabs().classes('w-full bg-slate-100') as tabs:
        for t in TABS:
            ui.tab(t)
    with ui.tab_panels(tabs, value='Portfolio').classes('w-full'):
        with ui.tab_panel('Dashboard'):
            with ui.row().classes('w-full'):
                for label, val in [('Wartość konta', pln(TOTAL)), ('Wpłaty netto', pln(88000)),
                                   ('Zysk/strata', pln(TOTAL - COST)), ('XIRR', '6,4 %')]:
                    with ui.column().classes('gap-0 pr-8'):
                        ui.label(label).classes('text-xs text-gray-500')
                        ui.label(val).classes('text-xl font-semibold')
            with ui.row().classes('w-full no-wrap'):
                with ui.column().classes('w-2/3'):
                    value_chart()
                with ui.column().classes('w-1/3'):
                    allocation_chart()
        with ui.tab_panel('Portfolio'):
            with ui.row().classes('w-full items-center'):
                ui.label('Pozycje').classes('text-lg font-bold')
                ui.space()
                ui.button('Dodaj transakcję', icon='add', on_click=form_drawer.show)
            ui.table(
                columns=[
                    {'name': 'konto', 'label': 'Konto', 'field': 'konto', 'align': 'left', 'sortable': True},
                    {'name': 'instrument', 'label': 'Instrument', 'field': 'instrument', 'align': 'left'},
                    {'name': 'klasa', 'label': 'Klasa', 'field': 'klasa', 'align': 'left'},
                    {'name': 'waluta', 'label': 'Waluta', 'field': 'waluta'},
                    {'name': 'liczba', 'label': 'Liczba', 'field': 'liczba'},
                    {'name': 'koszt', 'label': 'Koszt PLN', 'field': 'koszt', 'sortable': True},
                    {'name': 'wartosc', 'label': 'Wartość PLN', 'field': 'wartosc', 'sortable': True},
                    {'name': 'zysk_pct', 'label': 'Zysk %', 'field': 'zysk_pct', 'sortable': True},
                ],
                rows=POSITIONS, row_key='instrument',
            ).classes('w-full').props('dense flat bordered')
        with ui.tab_panel('Transakcje'):
            with ui.row().classes('w-full items-center'):
                ui.input(placeholder='Szukaj…').props('dense outlined clearable')
                ui.space()
                ui.button('Dodaj transakcję', icon='add', on_click=form_drawer.show)
            ui.table(columns=[{'name': k, 'label': k.capitalize(), 'field': k, 'align': 'left'}
                              for k in TRANSACTIONS[0]], rows=TRANSACTIONS).classes('w-full').props('dense flat')
        for t in ['Wyniki', 'Obligacje', 'Benchmarki', 'Ustawienia']:
            with ui.tab_panel(t):
                ui.label(f'{t} – poza zakresem prototypu').classes('text-gray-400')


# --- Variant B: left navigation menu, cards per account, dialog with steps -----------------
def variant_b(start_page: str = 'Dashboard') -> None:
    current = {'page': start_page if start_page in TABS else 'Dashboard'}

    with ui.dialog() as dialog, ui.card().classes('w-[460px]'):
        ui.label('Nowa transakcja').classes('text-lg font-bold')
        transaction_form(on_done=dialog.close)

    with ui.left_drawer(value=True).classes('bg-indigo-950 text-white').props('width=220'):
        ui.label('Moje inwestycje').classes('text-lg font-bold mb-4')
        icons = {'Dashboard': 'dashboard', 'Wyniki': 'insights', 'Portfolio': 'account_balance_wallet',
                 'Transakcje': 'receipt_long', 'Strategie inwestycyjne': 'flag', 'Obligacje': 'savings', 'Benchmarki': 'compare_arrows',
                 'Ustawienia': 'settings'}
        for t in TABS:
            ui.button(t, icon=icons[t], on_click=lambda t=t: (current.update(page=t), content.refresh())) \
                .props('flat align=left no-caps color=white').classes('w-full')
        ui.space()
        ui.label(f'Wartość portfela\n{pln(TOTAL)}').classes('whitespace-pre-line text-sm mt-6 opacity-80')

    def open_edit(t: dict) -> None:
        def delete() -> None:
            with ui.dialog() as confirm, ui.card():
                ui.label(f"Usunąć transakcję {t['typ']} {t['instrument']} z {t['data']}?")
                ui.label('Partie i salda zostaną przeliczone. Jeśli późniejsza sprzedaż straci pokrycie, '
                         'usunięcie zostanie zablokowane.').classes('text-xs text-gray-500')
                with ui.row():
                    ui.button('Anuluj', on_click=confirm.close).props('flat')
                    def really():
                        TRANSACTIONS.remove(t)
                        confirm.close()
                        edit.close()
                        content.refresh()
                        ui.notify('PROTOTYP: usunięto tylko z pamięci')
                    ui.button('Usuń', on_click=really).props('color=red')
            confirm.open()

        with ui.dialog() as edit, ui.card().classes('w-[460px]'):
            ui.label('Edycja transakcji').classes('text-lg font-bold')
            transaction_form(on_done=edit.close, initial=t, on_delete=delete)
        edit.open()

    @ui.refreshable
    def rebalancing() -> None:
        alloc = allocation()
        total = sum(alloc.values())
        classes = sorted(set(alloc) | set(TARGETS), key=lambda c: -TARGETS.get(c, 0))
        target_sum = sum(TARGETS.get(c, 0) for c in classes)
        # Smallest deposit that brings every class to its target without selling anything.
        needed = [alloc.get(c, 0) / (TARGETS[c] / 100) for c in classes if TARGETS.get(c, 0) > 0]
        deposit = max(0.0, max(needed, default=total) - total) if abs(target_sum - 100) < 0.01 else None

        with ui.row().classes('w-full items-center'):
            ui.label('Strategia inwestycyjna').classes('text-lg font-bold')
            ui.button('Szczegóły', icon='arrow_forward',
                      on_click=lambda: (current.update(page='Strategie inwestycyjne'), content.refresh())) \
                .props('flat dense no-caps')
            ui.space()
            ui.label(f'Suma celów: {target_sum:g}%').classes(
                'text-sm ' + ('text-green-700' if abs(target_sum - 100) < 0.01 else 'text-red-600 font-bold'))
        plan = split_deposit(alloc, TARGETS, PLAN['deposit']) if abs(target_sum - 100) < 0.01 else {}

        def set_plan(e):
            PLAN['deposit'] = float(e.value or 0)
            rebalancing.refresh()
        with ui.row().classes('items-center'):
            ui.number('Planuję wpłacić', value=PLAN['deposit'], min=0, step=100, suffix='zł', on_change=set_plan)                 .props('dense outlined debounce=600').classes('w-48')
            ui.label('→ kolumna „Kup za” pokazuje, jak ją rozdzielić bez sprzedaży.').classes('text-xs text-gray-500')
        with ui.grid(columns='1.8fr 0.7fr 1.1fr 1fr 0.8fr 1.5fr 1.2fr')                 .classes('w-full items-center gap-x-3 gap-y-1 text-sm whitespace-nowrap'):
            for h in ['Klasa aktywów', 'Udział', 'Wartość', 'Cel %', 'Różnica', 'Przesunięcie do celu',
                      'Kup za (z wpłaty)']:
                ui.label(h).classes('text-xs text-gray-500')
            for c in classes:
                value = alloc.get(c, 0)
                share = 100 * value / total
                target = TARGETS.get(c, 0)
                shift = target / 100 * total - value
                ui.label(c)
                ui.label(pct(share))
                ui.label(pln(value))

                def set_target(e, c=c):
                    TARGETS[c] = float(e.value or 0)
                    rebalancing.refresh()
                ui.number(value=target, min=0, max=100, step=1, suffix='%', on_change=set_target)                     .props('dense outlined debounce=600').classes('w-24')
                ui.label(pct(share - target, signed=True, unit='pp')).classes(
                    'text-red-600' if share < target else 'text-green-700')
                ui.label(('dokup ' if shift > 0 else 'nadwyżka ') + pln(abs(shift)))
                buy = plan.get(c, 0)
                ui.label(pln(buy) if buy > 0 else '–').classes('font-semibold' if buy > 0 else 'text-gray-400')
        if deposit is None:
            ui.label('Cele muszą sumować się do 100%, aby policzyć dopłatę.').classes('text-red-600 text-sm')
        else:
            ui.label(f'Pełne wyrównanie portfela samymi wpłatami (bez sprzedaży) wymaga wpłaty {pln(deposit)}.')                 .classes('text-sm text-gray-600 mt-2')

    @ui.refreshable
    def strategy_page() -> None:
        alloc = allocation()
        total = sum(alloc.values())
        target_sum = sum(TARGETS.values())
        class_plan = split_deposit(alloc, TARGETS, PLAN['deposit']) if abs(target_sum - 100) < 0.01 else {}

        def set_plan(e):
            PLAN['deposit'] = float(e.value or 0)
            strategy_page.refresh()
        with ui.row().classes('w-full items-center'):
            ui.number('Planuję wpłacić', value=PLAN['deposit'], min=0, step=100, suffix='zł', on_change=set_plan) \
                .props('dense outlined debounce=600').classes('w-48')
            ui.label('Wpłata dzielona jest najpierw między klasy, potem wewnątrz klasy między instrumenty.') \
                .classes('text-xs text-gray-500')
            ui.space()
            ui.label(f'Suma celów klas: {target_sum:g}%').classes(
                'text-sm ' + ('text-green-700' if abs(target_sum - 100) < 0.01 else 'text-red-600 font-bold'))

        cols = '2.2fr 0.8fr 1.2fr 1fr 0.9fr 1.5fr 1.2fr'
        for c in sorted(set(alloc) | set(TARGETS), key=lambda c: -TARGETS.get(c, 0)):
            value = alloc.get(c, 0)
            share = 100 * value / total
            target = TARGETS.get(c, 0)
            class_buy = class_plan.get(c, 0)
            held = {p['instrument']: p['wartosc'] for p in POSITIONS
                    if p['klasa'] == c and p['instrument'] != 'Gotówka'}
            subs = SUBTARGETS.setdefault(c, {})
            for name in held:
                subs.setdefault(name, 0.0)

            def on_open(e, c=c):
                (OPEN.add if e.value else OPEN.discard)(c)
            with ui.expansion(value=c in OPEN, on_value_change=on_open) \
                    .classes('w-full bg-white shadow rounded').props('dense') as exp:
                with exp.add_slot('header'):
                    with ui.grid(columns=cols).classes('w-full items-center gap-x-3 text-sm whitespace-nowrap'):
                        ui.label(c).classes('font-bold')
                        ui.label(pct(share))
                        ui.label(pln(value))

                        def set_target(e, c=c):
                            TARGETS[c] = float(e.value or 0)
                            strategy_page.refresh()
                        ui.number(value=target, min=0, max=100, step=1, suffix='%', on_change=set_target) \
                            .props('dense outlined debounce=600').classes('w-24').on('click.stop', lambda: None)
                        ui.label(pct(share - target, signed=True, unit='pp')).classes(
                            'text-red-600' if share < target else 'text-green-700')
                        shift = target / 100 * total - value
                        ui.label(('dokup ' if shift > 0 else 'nadwyżka ') + pln(abs(shift)))
                        ui.label(pln(class_buy) if class_buy > 0 else '–') \
                            .classes('font-semibold' if class_buy > 0 else 'text-gray-400')

                if c == 'Gotówka':
                    ui.label('Gotówka nie ma podziału na instrumenty.').classes('text-xs text-gray-500 p-2')
                    continue
                sub_sum = sum(subs.values())
                sub_ok = abs(sub_sum - 100) < 0.01
                values_in = {n: held.get(n, 0.0) for n in subs}
                no_strategy = sub_sum == 0
                if no_strategy:  # no inner strategy: split proportionally to current values
                    held_total = sum(held.values())
                    inner_plan = {n: class_buy * v / held_total for n, v in held.items()} if held_total else {}
                else:
                    inner_plan = split_deposit(values_in, subs, class_buy) if sub_ok else {}
                class_target_value = target / 100 * (total + PLAN['deposit'])
                with ui.column().classes('w-full pl-6 pr-2 pb-2 gap-1'):
                    with ui.grid(columns=cols).classes('w-full items-center gap-x-3 text-sm whitespace-nowrap'):
                        for h in ['Instrument', 'Udział w klasie', 'Wartość', 'Cel w klasie', 'Różnica',
                                  'Przesunięcie do celu', 'Kup za (z wpłaty)']:
                            ui.label(h).classes('text-xs text-gray-500')
                        for name, sub_target in sorted(subs.items(), key=lambda kv: -kv[1]):
                            v = held.get(name, 0.0)
                            in_share = 100 * v / value if value else 0.0
                            ui.label(name + ('' if name in held else ' · nieposiadany')) \
                                .classes('' if name in held else 'text-gray-500 italic')
                            ui.label(pct(in_share))
                            ui.label(pln(v))

                            def set_sub(e, c=c, name=name):
                                SUBTARGETS[c][name] = float(e.value or 0)
                                strategy_page.refresh()
                            ui.number(value=sub_target, min=0, max=100, step=5, suffix='%', on_change=set_sub) \
                                .props('dense outlined debounce=600').classes('w-24')
                            ui.label(pct(in_share - sub_target, signed=True, unit='pp')).classes(
                                'text-red-600' if in_share < sub_target else 'text-green-700')
                            ishift = sub_target / 100 * class_target_value - v
                            ui.label(('dokup ' if ishift > 0 else 'nadwyżka ') + pln(abs(ishift)))
                            buy = inner_plan.get(name, 0)
                            ui.label(pln(buy) if buy > 0 else '–') \
                                .classes('font-semibold' if buy > 0 else 'text-gray-400')
                    with ui.row().classes('w-full items-center'):
                        options = [n for n in CATALOG.get(c, []) if n not in subs]

                        def add(e, c=c):
                            if e.value:
                                SUBTARGETS[c][e.value] = 0.0
                                strategy_page.refresh()
                        if options:
                            ui.select(options, label='Dodaj instrument do strategii', on_change=add) \
                                .props('dense outlined').classes('w-80')
                        ui.space()
                        if no_strategy:
                            ui.label('Brak strategii w klasie – kwota dzielona proporcjonalnie do obecnych wartości')                                 .classes('text-xs text-gray-500')
                        else:
                            ui.label(f'Suma celów w klasie: {sub_sum:g}%').classes(
                                'text-xs ' + ('text-green-700' if sub_ok else 'text-red-600 font-bold'))
                    if not sub_ok and not no_strategy and class_buy > 0:
                        ui.label('Cele w klasie muszą sumować się do 100%, aby rozdzielić kwotę na instrumenty.') \
                            .classes('text-xs text-red-600')

    with ui.page_sticky(position='bottom-right', x_offset=24, y_offset=80):
        ui.button(icon='add', on_click=dialog.open).props('fab color=indigo')

    @ui.refreshable
    def content() -> None:
        page = current['page']
        ui.label(page).classes('text-2xl font-bold')
        if page == 'Dashboard':
            with ui.grid(columns=4).classes('w-full'):
                for label, val, icon in [('Wartość konta', pln(TOTAL), 'account_balance'),
                                         ('Wpłaty netto', pln(88000), 'south_west'),
                                         ('Zysk/strata', pln(TOTAL - COST), 'trending_up'),
                                         ('XIRR', '6,4 %', 'percent')]:
                    with ui.card():
                        ui.icon(icon).classes('text-indigo-500 text-2xl')
                        ui.label(label).classes('text-xs text-gray-500')
                        ui.label(val).classes('text-xl font-semibold')
            with ui.grid(columns=2).classes('w-full'):
                with ui.card():
                    value_chart()
                with ui.card():
                    allocation_chart()
            with ui.card().classes('w-full'):
                rebalancing()
        elif page == 'Portfolio':
            for konto in ACCOUNTS:
                rows = [p for p in POSITIONS if p['konto'] == konto]
                if not rows:
                    continue
                total = sum(r['wartosc'] for r in rows)
                zysk = sum(r['zysk'] for r in rows)
                with ui.expansion(value=True).classes('w-full bg-white shadow rounded') as exp:
                    with exp.add_slot('header'):
                        with ui.row().classes('w-full items-center'):
                            ui.label(konto).classes('font-bold')
                            ui.space()
                            ui.label(pln(total)).classes('font-semibold')
                            ui.badge(f'{zysk:+,.0f} zł', color='green' if zysk >= 0 else 'red')
                    for r in rows:
                        with ui.row().classes('w-full items-center border-t py-2'):
                            with ui.column().classes('gap-0 grow'):
                                ui.label(r['instrument']).classes('font-medium')
                                ui.label(f"{r['klasa']} · {r['liczba'] or ''} {r['waluta']}").classes('text-xs text-gray-500')
                            with ui.column().classes('gap-0 items-end'):
                                ui.label(pln(r['wartosc']))
                                ui.label(f"{r['zysk_pct']:+.2f} %").classes(
                                    'text-xs ' + ('text-green-600' if r['zysk'] >= 0 else 'text-red-600'))
        elif page == 'Strategie inwestycyjne':
            strategy_page()
        elif page == 'Transakcje':
            ui.label('Kliknij transakcję, aby ją edytować lub usunąć. Portfolio jest tylko do odczytu.')                 .classes('text-xs text-gray-500')
            for t in reversed(TRANSACTIONS):
                with ui.card().classes('w-full cursor-pointer hover:bg-indigo-50')                         .on('click', lambda t=t: open_edit(t)):
                    with ui.row().classes('w-full items-center'):
                        ui.badge(t['typ'], color='indigo')
                        ui.label(f"{t['instrument']} · {t['konto']}").classes('font-medium')
                        ui.space()
                        ui.label(t['data']).classes('text-xs text-gray-500')
                        ui.label(pln(t['kwota'])).classes('font-semibold')
                        ui.icon('edit').classes('text-gray-400')
        else:
            ui.label('Poza zakresem prototypu').classes('text-gray-400')

    with ui.column().classes('w-full max-w-5xl mx-auto p-4'):
        content()


# --- Variant C: dense spreadsheet, sheet tabs at the bottom, inline entry -----------------
def variant_c() -> None:
    current = {'sheet': 'Transakcje'}

    @ui.refreshable
    def sheet() -> None:
        name = current['sheet']
        if name == 'Transakcje':
            with ui.row().classes('w-full items-center gap-2'):
                ui.button('+ wiersz', on_click=lambda: (TRANSACTIONS.append(
                    {'data': '2026-10-08', 'konto': 'IKE (XTB)', 'typ': 'Zakup', 'instrument': '',
                     'liczba': 0, 'cena': 0, 'kwota': 0}), sheet.refresh())).props('dense outline')
                ui.label('Edytuj komórki bezpośrednio (dwuklik). Walidacja przy zatwierdzeniu wiersza.') \
                    .classes('text-xs text-gray-500')
            ui.aggrid({
                'columnDefs': [
                    {'field': 'data', 'editable': True, 'width': 110},
                    {'field': 'konto', 'editable': True, 'cellEditor': 'agSelectCellEditor',
                     'cellEditorParams': {'values': list(ACCOUNTS)}},
                    {'field': 'typ', 'editable': True, 'cellEditor': 'agSelectCellEditor', 'width': 110,
                     'cellEditorParams': {'values': ['Zakup', 'Sprzedaż', 'Wpłata', 'Wypłata', 'Dywidenda', 'Koszty']}},
                    {'field': 'instrument', 'editable': True},
                    {'field': 'liczba', 'editable': True, 'width': 90, 'type': 'numericColumn'},
                    {'field': 'cena', 'editable': True, 'width': 100, 'type': 'numericColumn'},
                    {'headerName': 'Kwota PLN', 'field': 'kwota', 'editable': True, 'type': 'numericColumn'},
                ],
                'rowData': TRANSACTIONS,
                'defaultColDef': {'filter': True, 'floatingFilter': True, 'resizable': True},
                'rowHeight': 28,
            }).classes('w-full').style('height: calc(100vh - 170px)')
        elif name == 'Portfolio':
            ui.aggrid({
                'columnDefs': [{'field': k} for k in
                               ['konto', 'instrument', 'klasa', 'waluta', 'liczba', 'koszt', 'wartosc', 'zysk', 'zysk_pct']],
                'rowData': POSITIONS,
                'defaultColDef': {'filter': True, 'resizable': True, 'sortable': True},
                'rowHeight': 28,
            }).classes('w-full').style('height: calc(100vh - 140px)')
        elif name == 'Dashboard':
            with ui.row().classes('w-full no-wrap'):
                with ui.column().classes('w-1/2'):
                    value_chart('300px')
                with ui.column().classes('w-1/2'):
                    allocation_chart('300px')
        else:
            ui.label('Poza zakresem prototypu').classes('text-gray-400')

    with ui.row().classes('w-full no-wrap gap-0'):
        with ui.column().classes('grow p-2'):
            sheet()
        with ui.column().classes('w-56 p-3 bg-gray-50 border-l text-sm gap-1').style('min-height: calc(100vh - 60px)'):
            ui.label('Podsumowanie').classes('font-bold')
            for label, val in [('Wartość', pln(TOTAL)), ('Koszt', pln(COST)), ('Zysk', pln(TOTAL - COST)), ('XIRR', '6,4 %')]:
                with ui.row().classes('w-full justify-between'):
                    ui.label(label).classes('text-gray-500')
                    ui.label(val).classes('font-mono')

    with ui.footer().classes('bg-gray-200 p-0 gap-0'):
        for t in TABS:
            ui.button(t, on_click=lambda t=t: (current.update(sheet=t), sheet.refresh())) \
                .props('flat no-caps square dense color=black').classes('px-4 border-r border-gray-300')


# --- page + floating switcher -------------------------------------------------------------
@ui.page('/')
def index(variant: str = 'A', page: str = 'Dashboard') -> None:
    variant = variant.upper() if variant.upper() in VARIANTS else 'A'
    keys = list(VARIANTS)
    variant_b(page) if variant == 'B' else {'A': variant_a, 'C': variant_c}[variant]()

    def go(step: int) -> None:
        ui.navigate.to(f'/?variant={keys[(keys.index(variant) + step) % len(keys)]}')

    with ui.element('div').style(
            'position:fixed; bottom:56px; left:50%; transform:translateX(-50%); z-index:10000; '
            'background:#111; color:#fff; border-radius:999px; padding:4px 10px; '
            'box-shadow:0 4px 14px rgba(0,0,0,.35); display:flex; align-items:center; gap:8px;'):
        ui.button(icon='chevron_left', on_click=lambda: go(-1)).props('flat round dense color=white')
        ui.label(f'PROTOTYP {variant} ({VARIANTS[variant]})').classes('text-sm')
        ui.button(icon='chevron_right', on_click=lambda: go(1)).props('flat round dense color=white')

    def on_key(e) -> None:  # default `ignore` skips keys typed into inputs/selects/textareas
        if e.action.keydown and e.key.arrow_left:
            go(-1)
        elif e.action.keydown and e.key.arrow_right:
            go(1)

    ui.keyboard(on_key=on_key)


ui.run(title='PROTOTYP – Moje inwestycje', port=8090, reload=False, show=True)
