"""Realistic noisy transcriptions -> the SKU the shopkeeper meant.

`expect` is the SKU we must land on. Cases marked `hard` are the ones we
expect to fall through to the model rather than auto-accept.
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

from khatam.matcher import Catalogue
from khatam.parse import parse_utterance

CAT = Catalogue.load(pathlib.Path(__file__).resolve().parents[1] / "data" / "catalog.json")

CASES = [
    # (what ASR produced, expected sku, expected direction, expected qty)
    ("maggi khatam",                          "MAG-70",  "out", 1),
    ("magi khatam ho gaya",                   "MAG-70",  "out", 1),
    ("meggi khatm",                           "MAG-70",  "out", 1),
    ("do parle-g wala bada packet gaya",      "PAR-G250","out", 2),
    ("pale gee wala bada packet gaya",        "PAR-G250","out", 1),
    ("parle ji khatam",                       "PAR-G50", "out", 1),
    ("teen red lebel gaya",                   "RED-250", "out", 3),
    ("chai patti khatam ho gayi",             "RED-250", "out", 1),
    ("paanch lays gaye",                      "LAY-MAG", "out", 5),
    ("layes khatam",                          "LAY-MAG", "out", 1),
    ("kurkuray khatam ho gaya",               "KUR-MAS", "out", 1),
    ("colget khatam",                         "COL-100", "out", 1),
    ("kolgate paste nahi hai",                "COL-100", "out", 1),
    ("do sarf excel gaya",                    "SUR-1K",  "out", 2),
    ("surf ka packet khatam",                 "SUR-1K",  "out", 1),
    ("parashoot tel khatam",                  "PAR-HAI", "out", 1),
    ("nariyal tel khatam ho gaya",            "PAR-HAI", "out", 1),
    ("das anda gaya",                         "EGG-TRY", "out", 10),
    ("ande khatam",                           "EGG-TRY", "out", 1),
    ("bisleri ki bottle khatam",              "BIS-750", "out", 1),
    ("char thumbs up gaye",                   "THU-750", "out", 4),
    ("dairymilk khatam ho gaya",              "DAI-MLK", "out", 1),
    ("faiv star khatam",                      "FIV-STR", "out", 1),
    ("gudnight refill khatam",                "GOO-KNT", "out", 1),
    ("maachis khatam",                        "MAT-BOX", "out", 1),
    ("do mombatti gaya",                      "CAN-DLE", "out", 2),
    ("wiskas khatam ho gaya",                 "WHI-CAT", "out", 1),
    ("pedigri khatam",                        "PED-1K",  "out", 1),
    ("serelac khatam ho gaya",                "CER-400", "out", 1),
    ("clinik plus shampoo khatam",            "CLI-SHM", "out", 1),
    ("shampoo ki patti khatam",               "SHM-SAC", "out", 1),
    # restock direction
    ("das maggi aa gaya",                     "MAG-70",  "in",  10),
    ("bees parle g aaye",                     "PAR-G50", "in",  20),
    ("surf excel stock aaya",                 "SUR-1K",  "in",  1),
    ("do peti bisleri aayi",                  "BIS-750", "in",  2),
    ("tata namak mil gaya",                   "TAT-SLT", "in",  1),
]

def run():
    ok = fell_through = wrong = 0
    print(f"catalogue: {len(CAT)} SKUs\n")
    print(f"{'transcription':38s} {'->':2s} {'matched':34s} {'conf':>5s}  {'dec':6s} {'qty':>4s} {'dir':4s}")
    print("-" * 104)
    for text, want_sku, want_dir, want_qty in CASES:
        u = parse_utterance(text)
        m = CAT.match(u.product_phrase)
        got = m.top.sku_id if m.top else "-"
        hit = got == want_sku
        dir_ok = u.direction == want_dir
        qty_ok = abs(u.quantity - want_qty) < 1e-6
        flag = "OK " if (hit and dir_ok and qty_ok) else "FAIL"
        if not hit:
            wrong += 1
        elif m.decision == "auto":
            ok += 1
        else:
            fell_through += 1
        label = m.top.label if m.top else "-"
        print(f"{text:38.38s} {flag:2s} {label:34.34s} {m.top.score if m.top else 0:5.2f}"
              f"  {m.decision:6s} {u.quantity:4.4g} {u.direction:4s}"
              + ("" if (hit and dir_ok and qty_ok) else f"   << want {want_sku}/{want_dir}/{want_qty}"))
    total = len(CASES)
    print("-" * 104)
    print(f"correct SKU: {ok + fell_through}/{total}   "
          f"auto-accepted: {ok}   escalated to model: {fell_through}   wrong: {wrong}")
    return wrong

if __name__ == "__main__":
    raise SystemExit(1 if run() else 0)
