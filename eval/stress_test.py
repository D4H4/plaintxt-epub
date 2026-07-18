import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
from converter import TextProcessor
path = os.path.join(_HERE, "samples", "hamlet.txt")
raw = open(path, encoding="utf-8", errors="replace").read()
text = TextProcessor.clean_text(raw)
ch = TextProcessor.detect_chapters(text)
print("Kapitel detekterade:", len(ch))
titles = [t for t, _ in ch]
print("Forsta 25:", titles[:25])
