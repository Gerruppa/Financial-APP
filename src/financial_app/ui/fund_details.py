"""A fund's TER, Distribution Policy and domicile as short texts, shared by the Instrument list and the Portfolio."""

from financial_app.domain.formatting import format_exact_percent
from financial_app.domain.instruments import InstrumentDraft


def fund_details(instrument: InstrumentDraft) -> list[str]:
    """The fund details the user entered, e.g. ["TER 0,07 %", "Akumulacja", "Siedziba: Irlandia"]; none when empty."""
    details = []
    if instrument.ter_percent is not None:
        details.append(f"TER {format_exact_percent(instrument.ter_percent)}")
    if instrument.distribution_policy is not None:
        details.append(instrument.distribution_policy.label)
    if instrument.domicile:
        details.append(f"Siedziba: {instrument.domicile}")
    return details
