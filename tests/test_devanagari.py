"""Chrome's speech API returns Devanagari for hi-IN, not romanised Hinglish.

This suite exists because the app was built and tested entirely on typed
romanised input, and the first real microphone test returned "मैगी खत्म" —
which matched nothing at all.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

from khatam.matcher import Catalogue
from khatam.parse import parse_utterance

CAT = Catalogue.load(pathlib.Path(__file__).resolve().parents[1] / "data" / "catalog.json")

CASES = [
    ("मैगी खत्म",                    "MAG-70",   "out", 1),
    ("मैगी खत्म हो गया",              "MAG-70",   "out", 1),
    ("दो पारले जी बड़ा पैकेट गया",     "PAR-G250", "out", 2),
    ("चाय पत्ती खत्म हो गयी",          "RED-250",  "out", 1),
    ("दस मैगी आ गया",                 "MAG-70",   "in",  10),
    ("कोलगेट खत्म",                   "COL-100",  "out", 1),
    ("साबुन खत्म",                    "LIF-BAR",  "out", 1),
    ("अंडा खत्म",                     "EGG-TRY",  "out", 1),
    ("सर्फ एक्सेल खत्म",              "SUR-1K",   "out", 1),
    ("पाँच लेज़ गया",                  "LAY-MAG",  "out", 5),
    ("शैम्पू की पत्ती खत्म",           "SHM-SAC",  "out", 1),
    ("बिसलेरी खत्म",                  "BIS-750",  "out", 1),
    ("तीन डेयरी मिल्क गया",            "DAI-MLK",  "out", 3),
    ("नमक खत्म",                      "TAT-SLT",  "out", 1),
    ("बीस पारले जी आ गया",            "PAR-G50",  "in",  20),
]

def run():
    bad = 0
    print(f"{'spoken (Devanagari)':32s} {'matched':34s} {'qty':>4s} {'dir':4s}")
    print("-" * 82)
    for text, want, want_dir, want_qty in CASES:
        u = parse_utterance(text)
        m = CAT.match(u.product_phrase)
        got = m.top.sku_id if m.top else "-"
        ok = got == want and u.direction == want_dir and abs(u.quantity - want_qty) < 1e-6
        if not ok:
            bad += 1
        label = m.top.label if m.top else "-"
        print(f"{text:32s} {label:34.34s} {u.quantity:4.4g} {u.direction:4s}"
              + ("" if ok else f"  << want {want}/{want_dir}/{want_qty}"))
    print("-" * 82)
    print(f"{len(CASES) - bad}/{len(CASES)} correct")
    return bad

if __name__ == "__main__":
    raise SystemExit(1 if run() else 0)
