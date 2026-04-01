#!/usr/bin/env python3
import json
from pathlib import Path
from collections import Counter

try:
    import pymupdf as fitz
except Exception:
    import fitz


# --- CONFIG ---
PDF_PATH = Path("/Users/tenzinmonlam/Documents/dharmaduta/pdf_convert_5/1-11/Done/IE2KG209991/sources/VE1ER1017/TI992-01-001.pdf")
OUT_DIR = Path("/Users/tenzinmonlam/Documents/dharmaduta/tibetan-etext-tools/PDF_XML/T1/IE2KG209991")
TARGET_FONTS = {
    "monlamuniouchan2": "monlamuniouchan2_cid_map.json",
    "kailasa": "kailasa_cid_map.json",
}
MIN_COUNT = 1  # raise to 2/3 to reduce noise


def collect_font_chars(pdf_path: Path):
    counters = {k: Counter() for k in TARGET_FONTS.keys()}
    doc = fitz.open(str(pdf_path))
    for page in doc:
        d = page.get_text("rawdict")
        for block in d.get("blocks", []):
            if block.get("type", 1) != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    font_name = (span.get("font") or "").lower()
                    for font_key in TARGET_FONTS.keys():
                        if font_key in font_name:
                            for ch_obj in span.get("chars", []):
                                ch = ch_obj.get("c", "")
                                # Keep only single-codepoint items for ord-based mapping
                                if len(ch) == 1:
                                    counters[font_key][ch] += 1
    doc.close()
    return counters


def load_existing(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main():
    counters = collect_font_chars(PDF_PATH)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for font_key, filename in TARGET_FONTS.items():
        out_path = OUT_DIR / filename
        existing = load_existing(out_path)

        # Bootstrap unknown entries with empty string so you can fill manually
        generated = dict(existing)
        for ch, count in counters[font_key].items():
            if count < MIN_COUNT:
                continue
            cid_key = str(ord(ch))
            generated.setdefault(cid_key, "")

        # Sort numerically by CID key for readability
        sorted_generated = dict(sorted(generated.items(), key=lambda kv: int(kv[0])))

        out_path.write_text(
            json.dumps(sorted_generated, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        print(f"\nWrote: {out_path}")
        print(f"Total entries: {len(sorted_generated)}")
        print("Top observed chars:")
        for ch, n in counters[font_key].most_common(20):
            print(f"  ord={ord(ch):>5}  char={repr(ch):<8}  count={n}")


if __name__ == "__main__":
    main()