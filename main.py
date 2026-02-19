import argparse
from pathlib import Path

# Assuming these are available in your project directory
from extractor import LayoutExtractor
from identifier import LanguageIdentifier
from translator import LindatTranslator
from utils import get_xml_elements_and_texts


def parse_arguments():
    parser = argparse.ArgumentParser(description="ATRIUM - Lindat Translation Wrapper")

    parser.add_argument("input_file", type=Path, default="xlm-fields.txt",
                        help="Path to the source file (.pdf, .xml, .txt)")

    # NEW: Optional fields file for targeted XML translation
    parser.add_argument("--fields", type=Path, default=None,
                        help="Path to a .txt file containing XML tags to translate (one per line).")

    parser.add_argument("--output", type=Path, default=None,
                        help="Path to save the translated text. Defaults to '<input_name>_<target_lang>.<ext>'")
    parser.add_argument("--target_lang", type=str, default="en",
                        help="Target language code (e.g., 'en', 'cs', 'fr'). Default: 'en'")

    args = parser.parse_args()

    # ---------------------------------------------------------
    # AUTOMATIC OUTPUT NAMING LOGIC
    # ---------------------------------------------------------
    if args.output is None:
        base_name = args.input_file.stem
        # Preserve .xml extension if running in targeted XML mode
        ext = args.input_file.suffix if (args.fields and args.input_file.suffix.lower() == '.xml') else '.txt'

        new_filename = f"{base_name}_{args.target_lang}{ext}"
        args.output = args.input_file.with_name(new_filename)

    return args


def process_standard_file(args):
    """Original logic: Extracts all text and outputs to a flat .txt file."""
    print("Initializing LayoutReader and extracting text...")
    extractor = LayoutExtractor()
    raw_text = extractor.extract(str(args.input_file))

    if not raw_text.strip():
        print("No text extracted.")
        return

    print("Identifying source language...")
    identifier = LanguageIdentifier()
    src_lang, lang_score = identifier.detect(raw_text)

    if lang_score < 0.4:
        print(f"Warning: Language detection confidence low ({round(lang_score, 3)} < 0.4). Defaulting to 'cs'.")
        src_lang = 'cs'
    else:
        print(f"Detected Language: {src_lang} - Confidence: {round(lang_score * 100, 3)}%")

    if src_lang == args.target_lang:
        print("Source matches target. Skipping translation.")
        final_text = raw_text
    else:
        print(f"Translating from {src_lang} to {args.target_lang}...")
        translator = LindatTranslator()
        final_text = translator.translate(raw_text, src_lang, args.target_lang)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(final_text)

    print(f"Done! Translation saved to {args.output}")


def process_xml_in_place(args):
    """New logic: Translates specific XML elements and preserves tree structure."""
    print(f"XML Mode: Extracting selected fields from {args.fields}...")
    tree, root, namespace, elements_data = get_xml_elements_and_texts(args.input_file, args.fields)

    if not tree:
        return

    if not elements_data:
        print("No matching text found in specified fields. Saving exact copy.")
        tree.write(args.output, encoding='utf-8', xml_declaration=True)
        return

    # Sample text for language detection
    sample_text = " ".join([data[2] for data in elements_data[:50]])
    print("Identifying source language from XML elements...")
    identifier = LanguageIdentifier()
    src_lang, lang_score = identifier.detect(sample_text)

    if lang_score < 0.4:
        print(f"Warning: Language detection confidence low ({round(lang_score, 3)} < 0.4). Defaulting to 'cs'.")
        src_lang = 'cs'
    else:
        print(f"Detected Language: {src_lang} - Confidence: {round(lang_score * 100, 3)}%")

    if src_lang == args.target_lang:
        print("Source matches target. Saving exact copy.")
        tree.write(args.output, encoding='utf-8', xml_declaration=True)
        return

    unique_strings = set(d[2] for d in elements_data)
    print(f"Translating {len(unique_strings)} unique strings from {src_lang} to {args.target_lang}...")

    translator = LindatTranslator()
    translation_cache = {}

    # Translate uniquely to minimize redundant API calls
    for i, original_text in enumerate(unique_strings, 1):
        translation_cache[original_text] = translator.translate(original_text, src_lang, args.target_lang)

    # Apply translations back to the elements
    print("Reconstructing XML with translated fields...")
    for elem, text_type, original_text in elements_data:
        if text_type == 'CONTENT':
            elem.attrib['CONTENT'] = translation_cache[original_text]
        else:
            elem.text = translation_cache[original_text]

    tree.write(args.output, encoding='utf-8', xml_declaration=True)
    print(f"Done! Translated XML saved to {args.output}")


def main():
    args = parse_arguments()

    print(f"Processing: {args.input_file}")
    print(f"Target Language: {args.target_lang}")
    print(f"Output will be saved to: {args.output}")

    # Route logic based on provided arguments
    if args.fields and args.input_file.suffix.lower() == '.xml':
        process_xml_in_place(args)
    else:
        process_standard_file(args)


if __name__ == "__main__":
    main()