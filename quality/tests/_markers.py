"""TEST-HARNESS Wave 1 D3 + D6: suite-composition markers.

Registered from conftest.py ``pytest_plugins``; marker names are declared in
pytest.ini.

D3 -- ``@pytest.mark.quarantine("CARD-ID", reason="...", cls="...")``
    A known-failing test carried by a kanban card. The card id is REQUIRED
    (positional or ``card=``) and must look like a board id
    (``ABC-DEF-1``: upper-case words joined by ``-``). A missing/malformed id
    is a COLLECTION error, so nothing can be quarantined anonymously.
    Quarantined tests are SKIPPED in the default run and listed in a
    terminal summary section. Opt-ins:
      * ``URA_RUN_QUARANTINED=1`` -- run them normally (see if they now pass);
      * ``--quarantine-ledger``     -- print the ledger (card, reason, node id)
                                       and count even when nothing else asked.

D6 -- ``@pytest.mark.source_mutation``
    Tests that run a source-mutation drill (subprocess pytest against a
    mutated copy of production source). Slow (~5-10 s each) and, historically,
    the tree-corruption hazard. pytest.ini addopts deselects them by default
    (``-m "not source_mutation"``). Opt-ins:
      * ``-m source_mutation``      -- only the drills (a later ``-m`` wins);
      * ``-m ""``                   -- everything;
      * ``URA_SOURCE_MUTATION=1``   -- clears the default exclusion while
                                       leaving any explicit ``-m`` alone.
"""
from __future__ import annotations

import os
import re

import pytest

CARD_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
DEFAULT_EXCLUDE_EXPR = "not source_mutation"
ENV_RUN_QUARANTINED = "URA_RUN_QUARANTINED"
ENV_SOURCE_MUTATION = "URA_SOURCE_MUTATION"

_LEDGER_KEY = pytest.StashKey[list]()


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def pytest_addoption(parser):
    parser.addoption(
        "--quarantine-ledger",
        action="store_true",
        default=False,
        help="Print every quarantined test (card id, reason, node id) and the count.",
    )


def pytest_configure(config):
    config.stash[_LEDGER_KEY] = []
    if _truthy(ENV_SOURCE_MUTATION):
        # Only clear the ini default; an explicit `-m` the caller typed wins.
        if (config.option.markexpr or "").strip() == DEFAULT_EXCLUDE_EXPR:
            config.option.markexpr = ""


def parse_quarantine(mark) -> tuple[str, str, str]:
    """Return (card, reason, cls) or raise pytest.UsageError."""
    card = mark.kwargs.get("card")
    if card is None and mark.args:
        card = mark.args[0]
    if not isinstance(card, str) or not CARD_ID_RE.match(card):
        raise pytest.UsageError(
            f"quarantine marker needs a card id like 'ABC-DEF-1' "
            f"(positional or card=); got {card!r}"
        )
    reason = mark.kwargs.get("reason") or (mark.args[1] if len(mark.args) > 1 else "")
    return card, str(reason), str(mark.kwargs.get("cls", ""))


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(session, config, items):
    ledger = config.stash[_LEDGER_KEY]
    run_quarantined = _truthy(ENV_RUN_QUARANTINED)
    errors = []
    for item in items:
        mark = item.get_closest_marker("quarantine")
        if mark is None:
            continue
        try:
            card, reason, cls = parse_quarantine(mark)
        except pytest.UsageError as exc:
            errors.append(f"{item.nodeid}: {exc}")
            continue
        ledger.append((card, reason, cls, item.nodeid))
        if not run_quarantined:
            item.add_marker(pytest.mark.skip(reason=f"quarantined [{card}] {reason}".rstrip()))
    if errors:
        raise pytest.UsageError("invalid quarantine marker(s):\n  " + "\n  ".join(errors))


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    ledger = config.stash.get(_LEDGER_KEY, [])
    full = config.getoption("--quarantine-ledger")
    if not ledger and not full:
        return
    state = "RUN (URA_RUN_QUARANTINED)" if _truthy(ENV_RUN_QUARANTINED) else "skipped"
    terminalreporter.write_sep("-", "quarantine ledger")
    terminalreporter.write_line(
        f"quarantined: {len(ledger)} test(s), "
        f"{len({c for c, *_ in ledger})} card(s) -- {state}"
    )
    if full:
        for card, reason, cls, nodeid in sorted(ledger):
            extra = f" [{cls}]" if cls else ""
            terminalreporter.write_line(f"  {card}{extra}  {nodeid}  -- {reason}")
