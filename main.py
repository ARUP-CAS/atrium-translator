import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Graceful fallback for tqdm so the script works out-of-the-box
try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, *args, **kwargs):
        """Fallback progress bar if tqdm is not installed."""
        total = kwargs.get('total', len(iterable) if hasattr(iterable, '__len__') else None)
        desc = kwargs.get('desc', 'Processing')
        for i, item in enumerate(iterable, 1):
            if total:
                sys.stdout.write(f"\r[INFO] {desc}: {i}/{total} ({(i / total) * 100:.1f}%)")
            else:
                sys.stdout.write(f"\r[INFO] {desc}: {i} items")
            sys.stdout.flush()
            yield item
        print()

from processors.extractor import LayoutExtractor
from processors.identifier import LanguageIdentifier
from processors.translator import LindatTranslator
from utils import get_alto_textblocks


def parse_arguments():
    """
    Parses console arguments and optional configuration file parameters.
    Automatically looks for 'config.txt' in the current directory.
    Console arguments take precedence over config file parameters.
    """
    parser = argparse.ArgumentParser(description="ATRIUM - Lindat Translation Batch Wrapper")
    parser.add_argument("input_path", type=Path, nargs='?', default=None,
                        help="Path to a single source file or a directory containing files.")
    parser.add_argument("--config", type=Path, default=Path("config.txt"),
                        help="Path to a config file. Defaults to 'config.txt' automatically.")
    parser.add_argument("--fields", type=Path, default=Path("xml-fields.txt"),
                        help="Path to a .txt file containing XML tags to translate.")
    parser.add_argument("--output", "-o",  type=Path, default=None,
                        help="Output file path (for single) or output directory (for batch mode).")
    parser.add_argument("--source_lang", "-src", type=str, default="auto",
                        help="Source language code (e.g., 'cs', 'fr'). Use 'auto' to auto-detect. Default: 'auto'")
    parser.add_argument("--target_lang", "-tgt", type=str, default="en",
                        help="Target language code (e.g., 'en', 'cs', 'fr'). Default: 'en'")
    parser.add_argument("--formats", "-f", type=str, default="xml,txt,pdf",
                        help="Comma-separated list of formats to process in batch mode (e.g., 'xml,pdf').")

    args = parser.parse_args()

    # Mapping config keys to their CLI flags to correctly detect overrides
    cli_flag_map = {
        'output': ['--output', '-o'],
        'source_lang': ['--source_lang', '-src'],
        'target_lang': ['--target_lang', '-tgt'],
        'formats': ['--formats', '-f'],
        'fields': ['--fields'],
        'config': ['--config']
    }

    # Process config file automatically if it exists
    if args.config and args.config.exists():
        print(f"[INFO] Loaded configuration from: {args.config.name}")
        try:
            with open(args.config, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue

                    key, val = [x.strip() for x in line.split('=', 1)]

                    # Check if the user passed this argument via CLI (sys.argv)
                    flags_for_key = cli_flag_map.get(key, [f'--{key}'])
                    cli_provided = any(
                        arg == flag or arg.startswith(flag + '=')
                        for arg in sys.argv
                        for flag in flags_for_key
                    )

                    # Handle positional input path override
                    if key == 'input_path' and len([a for a in sys.argv if not a.startswith('-')]) <= 1:
                        setattr(args, key, Path(val))
                    elif not cli_provided and hasattr(args, key):
                        if key in ['output', 'fields', 'input_path', 'config']:
                            setattr(args, key, Path(val))
                        else:
                            setattr(args, key, val)
        except Exception as e:
            print(f"[ERROR] Failed to parse config file '{args.config}': {type(e).__name__} - {e}")
    elif str(args.config) != "config.txt":
        # Only warn if they manually specified a config that doesn't exist
        print(f"[WARN] Config file '{args.config}' not found. Using CLI arguments and defaults.")

    return args


def process_standard_file(input_file, output_file, args):
    """
    Extracts text from a standard file (PDF, TXT, CSV, etc.), identifies or uses
    the provided source language, translates if necessary, and writes output.
    """
    print(f"[INFO] Initializing LayoutReader and extracting text for {input_file.name}...")
    try:
        extractor = LayoutExtractor()
        raw_text = extractor.extract(str(input_file))
    except Exception as e:
        print(f"[ERROR] Layout extraction failed for {input_file.name}: {e}")
        return

    if not raw_text.strip():
        print(f"[WARN] No text extracted from {input_file.name}. Skipping.")
        return

    # Evaluate Source Language
    if args.source_lang.lower() == "auto":
        print("[INFO] Identifying source language automatically...")
        identifier = LanguageIdentifier()
        src_lang, lang_score = identifier.detect(raw_text)

        if lang_score < 0.4:
            print(f"[WARN] Language detection confidence low ({round(lang_score, 3)} < 0.4). Defaulting to 'cs'.")
            src_lang = 'cs'
        else:
            print(f"[INFO] Detected Language: {src_lang.upper()} (Confidence: {round(lang_score * 100, 1)}%)")
    else:
        src_lang = args.source_lang.lower()
        print(f"[INFO] Using explicit Source Language: {src_lang.upper()}")

    if src_lang == args.target_lang:
        print(f"[INFO] Source language ({src_lang}) matches target. Skipping file creation.")
        return

    print(f"[INFO] Translating from {src_lang.upper()} to {args.target_lang.upper()}...")
    try:
        translator = LindatTranslator()
        final_text = translator.translate(raw_text, src_lang, args.target_lang)

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(final_text)

        print(f"[SUCCESS] Translation saved to: {output_file}")
    except Exception as e:
        print(f"[ERROR] Translation process failed for {input_file.name}: {e}")


def process_xml_in_place(input_file, output_file, args):
    """
    Extracts text specifically from ALTO XML, preserving tree structure,
    translates text block by block, and reconstructs the XML inline.
    """
    print(f"[INFO] ALTO XML Mode: Extracting TextBlocks for {input_file.name}...")
    tree, root, namespace, blocks_data = get_alto_textblocks(input_file)

    if not tree:
        print(f"[ERROR] Failed to parse XML: {input_file.name}")
        return

    if not blocks_data:
        print(f"[WARN] No matching TextBlocks found in {input_file.name}. Skipping file creation.")
        return

    # Evaluate Source Language
    if args.source_lang.lower() == "auto":
        sample_text = " ".join([data[1] for data in blocks_data[:20]])
        print("[INFO] Identifying source language from XML elements...")
        identifier = LanguageIdentifier()
        src_lang, lang_score = identifier.detect(sample_text)

        if lang_score < 0.4:
            print(f"[WARN] Language detection confidence low ({round(lang_score, 3)} < 0.4). Defaulting to 'cs'.")
            src_lang = 'cs'
        else:
            print(f"[INFO] Detected Language: {src_lang.upper()} (Confidence: {round(lang_score * 100, 1)}%)")
    else:
        src_lang = args.source_lang.lower()
        print(f"[INFO] Using explicit Source Language: {src_lang.upper()}")

    if src_lang == args.target_lang:
        print(f"[INFO] Source language ({src_lang}) matches target. Skipping file creation.")
        return

    unique_blocks = list(set(d[1] for d in blocks_data))
    print(f"[INFO] Prepared {len(unique_blocks)} unique text blocks for translation.")

    translator = LindatTranslator()
    translation_cache = {}

    try:
        for original_text in tqdm(unique_blocks, desc=f"Translating {input_file.name}", unit="block"):
            translation_cache[original_text] = translator.translate(original_text, src_lang, args.target_lang)
    except Exception as e:
        print(f"[ERROR] Translation block processing failed: {e}")
        return

    print("[INFO] Reconstructing XML TextLines with translated content...")
    try:
        for block_elem, original_text, lines in tqdm(blocks_data, desc="Rebuilding XML", unit="block"):
            translated_text = translation_cache[original_text]
            words = translated_text.split()
            num_lines = len(lines)

            if num_lines == 0:
                continue

            words_per_line = len(words) // num_lines
            remainder = len(words) % num_lines

            word_idx = 0
            for i, line_elem in enumerate(lines):
                count = words_per_line + (1 if i < remainder else 0)
                line_words = words[word_idx: word_idx + count]
                word_idx += count

                line_str = " ".join(line_words)

                for child in list(line_elem):
                    line_elem.remove(child)

                if not line_str:
                    continue

                string_tag = f"{namespace}String" if namespace else "String"
                new_string = ET.Element(string_tag)

                new_string.attrib['HPOS'] = line_elem.attrib.get('HPOS', '0')
                new_string.attrib['VPOS'] = line_elem.attrib.get('VPOS', '0')
                new_string.attrib['WIDTH'] = line_elem.attrib.get('WIDTH', '0')
                new_string.attrib['HEIGHT'] = line_elem.attrib.get('HEIGHT', '0')
                new_string.attrib['CONTENT'] = line_str

                line_elem.append(new_string)

        tree.write(output_file, encoding='utf-8', xml_declaration=True)
        print(f"[SUCCESS] Translated XML saved to: {output_file}")
    except Exception as e:
        print(f"[ERROR] XML Reconstruction failed for {input_file.name}: {e}")


def generate_output_path(input_file, base_output, args, is_batch=False):
    """
    Constructs the target path for the translated output file dynamically,
    accounting for custom output directories and batch processing context.
    """
    ext = input_file.suffix if (args.fields and input_file.suffix.lower() == '.xml') else '.txt'
    new_filename = f"{input_file.stem}_{args.target_lang}{ext}"

    if is_batch:
        return base_output / new_filename

    if base_output:
        if base_output.is_dir():
            return base_output / new_filename
        return base_output

    return input_file.with_name(new_filename)


def process_single_file(input_file, output_file, args):
    """
    Determines routing: uses XML specific structural translation for ALTO XML
    or flat text pipeline for all other formats.
    """
    try:
        if args.fields and input_file.suffix.lower() == '.xml':
            process_xml_in_place(input_file, output_file, args)
        else:
            process_standard_file(input_file, output_file, args)
    except Exception as e:
        print(f"[ERROR] Unhandled failure while processing {input_file.name}: {type(e).__name__} - {e}")


def main():
    """
    Main entry point. Initializes configurations, handles batch-folder
    traversals or single file passes based on CLI inputs.
    """
    args = parse_arguments()

    print(f"\n{'=' * 60}")
    print(f" ATRIUM LINDAT TRANSLATOR ".center(60, "="))
    print(f"{'=' * 60}")

    input_path = args.input_path

    if not input_path or not input_path.exists():
        print(f"[ERROR] Input path does not exist or was not provided.")
        print("Please provide a valid input_path in your config.txt or via the command line.")
        return

    valid_exts = {f".{ext.strip().lower()}" for ext in args.formats.split(',')}

    # --- BATCH DIRECTORY PROCESSING ---
    if input_path.is_dir():
        files_to_process = [f for f in input_path.rglob('*') if f.is_file() and f.suffix.lower() in valid_exts]

        if not files_to_process:
            print(f"[WARN] No valid files ({', '.join(valid_exts)}) found in {input_path}")
            return

        out_dir = args.output if args.output else input_path / f"translated_{args.target_lang}"

        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"[ERROR] Failed to create output directory {out_dir}: {e}")
            return

        print(f"[INFO] Batch Mode: Found {len(files_to_process)} files in '{input_path.name}'.")
        print(f"[INFO] Source Language: {args.source_lang.upper()}")
        print(f"[INFO] Target Language: {args.target_lang.upper()}")
        print(f"[INFO] Target Formats: {args.formats}")
        print(f"[INFO] Output Directory: {out_dir}")
        print("-" * 60)

        for i, file_path in enumerate(files_to_process, 1):
            print(f"\n[FILE {i}/{len(files_to_process)}] Processing: {file_path.name}")
            output_file = generate_output_path(file_path, out_dir, args, is_batch=True)
            process_single_file(file_path, output_file, args)

    # --- SINGLE FILE PROCESSING ---
    else:
        output_file = generate_output_path(input_path, args.output, args)
        print(f"[INFO] Single File Mode: {input_path.name}")
        print(f"[INFO] Source Language: {args.source_lang.upper()}")
        print(f"[INFO] Target Language: {args.target_lang.upper()}")
        print(f"[INFO] Output will be saved to: {output_file}")
        print("-" * 60)

        process_single_file(input_path, output_file, args)

    print(f"\n{'=' * 60}")
    print(f" PROCESSING COMPLETE ".center(60, "="))
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()