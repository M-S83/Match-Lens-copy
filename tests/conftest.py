"""Shared test setup for the Match Lens suite.

WHY THE STUBS BELOW EXIST
-------------------------
Several pipeline modules import heavy third-party packages at module scope
(``cv2``, ``anthropic``, ``PIL``, ``numpy``), and ``batch_runner.py:33``
instantiates ``anthropic.Anthropic()`` at *import* time — so importing
``pipeline_runner_v2`` requires API credentials to be present even when the
test never makes a call.

That is a testability defect in its own right (recorded in AUDIT-2026-08.md).
Until those imports are made lazy, this conftest inserts minimal stand-ins into
``sys.modules`` before the modules under test are imported, so the suite runs in
a bare checkout with nothing installed and no API key.

WHAT THIS MEANS FOR COVERAGE
----------------------------
These tests cover **pure logic**: key resolution, merge behaviour, ordering,
gating, and metric arithmetic. They do NOT cover anything that actually touches
a video file, an image, or the Claude API — those paths are stubbed out, not
exercised. Do not read a green suite as evidence that frame extraction or an
API call works.
"""
import os
import sys
import types

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _stub(name, **attrs):
    """Register a stand-in module only if the real package is absent."""
    try:
        __import__(name)
        return                      # real package installed — prefer it
    except ImportError:
        pass
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


class _StubAnthropic:
    """Enough shape for `anthropic.Anthropic()` at import time.

    Any attempt to actually call the API raises, so a test that accidentally
    reaches the network fails loudly instead of appearing to pass.
    """

    def __init__(self, *args, **kwargs):
        self.messages = self
        self.batches = self

    def __getattr__(self, item):
        raise AssertionError(
            f"test tried to use the Anthropic API (.{item}); "
            "these tests must not make network calls")


def _api_error(name):
    return type(name, (Exception,), {})


_stub("cv2")
# python-docx: md_to_docx imports Document plus several submodules at module
# scope. Stub the package and each submodule it reaches for.
if "docx" not in sys.modules:
    try:
        __import__("docx")
    except ImportError:
        _docx = types.ModuleType("docx")
        _callable = lambda *a, **k: None
        _docx.Document = _callable
        for sub, attrs in (
            ("docx.shared",    {"Pt": _callable, "RGBColor": _callable,
                                "Inches": _callable, "Cm": _callable}),
            ("docx.enum.text", {"WD_ALIGN_PARAGRAPH": types.SimpleNamespace(
                                    CENTER=1, LEFT=0, RIGHT=2, JUSTIFY=3)}),
            ("docx.enum.table",{"WD_TABLE_ALIGNMENT": types.SimpleNamespace(CENTER=1)}),
            ("docx.oxml.ns",   {"qn": lambda x: x}),
            ("docx.oxml",      {"OxmlElement": _callable}),
            ("docx.enum",      {}),
        ):
            m = types.ModuleType(sub)
            for k, v in attrs.items():
                setattr(m, k, v)
            sys.modules[sub] = m
        sys.modules["docx"] = _docx
_stub("numpy")
_stub("easyocr")
_stub("PIL", Image=types.SimpleNamespace(
    open=None, fromarray=None, LANCZOS=1, Image=object))
_stub("dotenv", load_dotenv=lambda *a, **k: None)
_stub("anthropic",
      Anthropic=_StubAnthropic,
      APIConnectionError=_api_error("APIConnectionError"),
      APIStatusError=_api_error("APIStatusError"),
      APITimeoutError=_api_error("APITimeoutError"),
      RateLimitError=_api_error("RateLimitError"),
      AuthenticationError=_api_error("AuthenticationError"),
      BadRequestError=_api_error("BadRequestError"))
