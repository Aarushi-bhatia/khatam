"""Shared fixtures for the honesty suites.

COLLOQUIAL lives here so test_vocabulary_gap.py (which measures the problem)
and test_alias_generation.py (which measures the fix) are scored against
exactly the same words.
"""

# What a shopkeeper actually says, paired with the SKU it means. Every one of
# these words is chosen because it shares no letters with the product's brand
# or name — phonetic matching cannot reach them, only vocabulary can.
COLLOQUIAL = [
    ("doodh", "AMU-TAZ"), ("sabun", "LIF-BAR"), ("maachis", "MAT-BOX"),
    ("anda", "EGG-TRY"), ("namak", "TAT-SLT"), ("cheeni", "SUG-1K"),
    ("atta", "AAS-ATA"), ("chawal", "DAW-BAS"), ("tel", "FOR-OIL"),
    ("chai patti", "RED-250"), ("makhan", "AMU-BUT"), ("dahi", "AMU-DAH"),
    ("haldi", "EVR-HAL"), ("mirchi", "EVR-MIR"), ("nariyal tel", "PAR-HAI"),
    ("mombatti", "CAN-DLE"), ("kaapi", "BRU-50"), ("double roti", "BRD-400"),
    ("bhujia", "HAL-BHU"), ("pani", "BIS-750"),
]
