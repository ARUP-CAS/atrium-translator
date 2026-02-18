import argparse
import os

from processors.extractor import *
from processors.translator import *
from processors.identifier import *


def main():
    parser = argparse.ArgumentParser(description="Lindat Translation Wrapper (PDF/XML/TXT)")
    parser.add_argument("input_file", help="Path to input file (.pdf, .xml (ALTO), .txt)")
    parser.add_argument("--output", help="Path to save translated text", default="output.txt")
    parser.add_argument("--target_lang", help="Target language code (default: en)", default="en")
    args = parser.parse_args()

    if not os.path.exists(args.input_file):
        print(f"Error: File '{args.input_file}' not found.")
        return

    print(f"--- Processing {args.input_file} ---")

    # 1. Extract Text (Layout Analysis)
    print("Initializing LayoutReader and extracting text...")
    extractor = LayoutExtractor()
    raw_text = extractor.extract(args.input_file)

    if not raw_text.strip():
        print("No text extracted.")
        return

    # 2. Identify Language
    print("Identifying source language...")
    identifier = LanguageIdentifier()
    src_lang, lang_score = identifier.detect(raw_text)

    # UPDATED: Check confidence score
    # If confidence is low (< 0.4), assume data is inadequate for detection and default to Czech
    if lang_score < 0.4:
        print(f"Warning: Language detection confidence low ({round(lang_score, 3)} < 0.4).")
        print("Defaulting source language to 'cs' (Czech).")
        src_lang = 'cs'
    else:
        print(f"Detected Language: {src_lang} - Confidence: {round(lang_score * 100, 3)}%")

    # 3. Translate
    if src_lang == args.target_lang:
        print("Source matches target. Skipping translation.")
        final_text = raw_text
    else:
        print(f"Translating from {src_lang} to {args.target_lang}...")
        translator = LindatTranslator()
        final_text = translator.translate(raw_text, src_lang, args.target_lang)

    # 4. Output
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(final_text)

    print(f"Done! Translation saved to {args.output}")


if __name__ == "__main__":
    main()