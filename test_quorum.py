"""
Unit tests for NewsConsensusFeed's code-enforced quorum rule (_apply_quorum).

Why this test exists / how to read it:
_apply_quorum is written as a small @staticmethod with no access to contract storage and no
GenLayer runtime calls -- its only job is turning (supports_count, contradicts_count, quorum,
prior_status) into a new status string. That is the one piece of "consensus logic" in this
contract that is NOT delegated to the model, so it is the piece most worth pinning down with
plain, fast, deterministic tests that need no Docker/Studio and no LLM.

Because the contract module does `from genlayer import *` at import time, and the `genlayer`
package is only available inside a GenLayer project/Studio environment, this file installs a
minimal stand-in module into sys.modules first, just enough for NewsConsensusFeed to import
cleanly. The stand-in never intercepts real fetch/LLM/consensus behaviour -- it only needs to
exist so the *pure* quorum function can be reached and exercised directly. Full behavioural
coverage of create_query / check_query / add_source (including the actual web fetch and
gl.eq_principle.prompt_comparative round) belongs in gltest-based direct/integration tests
against a real GenLayer Studio instance, per docs.genlayer.com/developers/decentralized-
applications/testing -- this file intentionally does not attempt to fake that part.

Run with: pytest tests/test_quorum.py -v
"""

import sys
import types
import importlib.util
from pathlib import Path


def _install_genlayer_stub() -> None:
    if "genlayer" in sys.modules:
        return
    mod = types.ModuleType("genlayer")

    class _Write:
        def __call__(self, fn):
            return fn

        @staticmethod
        def payable(fn):
            return fn

    class _View:
        def __call__(self, fn):
            return fn

    class _Public:
        write = _Write()
        view = _View()

    class _EqPrinciple:
        @staticmethod
        def prompt_comparative(fn, principle):
            return fn()

    class _WebNS:
        @staticmethod
        def render(url, mode="text"):
            return ""

    class _Nondet:
        web = _WebNS()

        @staticmethod
        def exec_prompt(prompt, response_format=None):
            return {}

    class _Message:
        sender_address = None
        value = 0

    class _UserError(Exception):
        pass

    class _Vm:
        UserError = _UserError

    class _EvmNS:
        @staticmethod
        def contract_interface(cls):
            return cls

    class _Gl:
        class Contract:
            pass

        public = _Public()
        eq_principle = _EqPrinciple()
        nondet = _Nondet()
        message = _Message()
        message_raw: dict = {}
        vm = _Vm()
        evm = _EvmNS()

    class Address(str):
        pass

    class DynArray(list):
        pass

    class TreeMap(dict):
        pass

    def allow_storage(cls):
        return cls

    def u256(v=0):
        return int(v)

    mod.gl = _Gl()
    mod.Address = Address
    mod.DynArray = DynArray
    mod.TreeMap = TreeMap
    mod.allow_storage = allow_storage
    mod.u256 = u256
    mod.__all__ = ["gl", "Address", "DynArray", "TreeMap", "allow_storage", "u256"]
    sys.modules["genlayer"] = mod


_install_genlayer_stub()

_CONTRACT_PATH = Path(__file__).resolve().parent.parent / "NewsConsensusFeed.py"
_spec = importlib.util.spec_from_file_location("news_consensus_feed", _CONTRACT_PATH)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

NewsConsensusFeed = _module.NewsConsensusFeed
STATUS_OPEN = _module.STATUS_OPEN
STATUS_RESOLVED_TRUE = _module.STATUS_RESOLVED_TRUE
STATUS_RESOLVED_FALSE = _module.STATUS_RESOLVED_FALSE
STATUS_DISPUTED = _module.STATUS_DISPUTED

# _apply_quorum is a regular instance method (not @staticmethod, per GenVM lint rule E022) that
# happens not to touch any contract state -- so a bare, un-initialized instance (built with
# __new__, skipping __init__) is enough to call it as a bound method in isolation.
_bare_instance = NewsConsensusFeed.__new__(NewsConsensusFeed)
apply_quorum = _bare_instance._apply_quorum


def test_clean_support_majority_resolves_true():
    assert apply_quorum(supports=3, contradicts=0, quorum=2, prior_status=STATUS_OPEN) == STATUS_RESOLVED_TRUE


def test_clean_contradiction_majority_resolves_false():
    assert apply_quorum(supports=0, contradicts=2, quorum=2, prior_status=STATUS_OPEN) == STATUS_RESOLVED_FALSE


def test_mixed_signal_is_disputed_even_if_supports_meets_quorum():
    # supports alone reaches quorum, but a contradicting source exists too -- must NOT resolve
    # TRUE just because supports>=quorum; disagreement itself is the reportable signal.
    assert apply_quorum(supports=2, contradicts=1, quorum=2, prior_status=STATUS_OPEN) == STATUS_DISPUTED


def test_single_contradiction_alone_does_not_resolve_false():
    # contradicts < quorum, and supports+contradicts < quorum too -> insufficient evidence,
    # status must not move off OPEN.
    assert apply_quorum(supports=0, contradicts=1, quorum=2, prior_status=STATUS_OPEN) == STATUS_OPEN


def test_insufficient_evidence_never_resolves_from_open():
    assert apply_quorum(supports=1, contradicts=0, quorum=2, prior_status=STATUS_OPEN) == STATUS_OPEN


def test_insufficient_evidence_preserves_prior_resolved_true():
    # This mirrors check_query's own evidence_sufficient gate: when supports+contradicts fails
    # to reach quorum, check_query never even calls _apply_quorum with prior_status's real value
    # for that round -- but _apply_quorum itself must still be safe if called, returning the
    # prior status unchanged rather than resetting it.
    assert apply_quorum(supports=0, contradicts=0, quorum=2, prior_status=STATUS_RESOLVED_TRUE) == STATUS_RESOLVED_TRUE


def test_insufficient_evidence_preserves_prior_disputed():
    assert apply_quorum(supports=1, contradicts=0, quorum=3, prior_status=STATUS_DISPUTED) == STATUS_DISPUTED


def test_quorum_exactly_met_by_supports_resolves_true():
    assert apply_quorum(supports=2, contradicts=0, quorum=2, prior_status=STATUS_OPEN) == STATUS_RESOLVED_TRUE


def test_large_disagreement_is_disputed_not_averaged():
    assert apply_quorum(supports=4, contradicts=3, quorum=2, prior_status=STATUS_OPEN) == STATUS_DISPUTED


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
