import re
import xml.etree.ElementTree as ET
from lxml import etree
import urllib.request
import sys


def validate_xml_with_xsd(xml_tree, xsd_url_or_path):
    try:
        if xsd_url_or_path.startswith('http'):
            req = urllib.request.Request(xsd_url_or_path, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as f:
                xmlschema_doc = etree.parse(f)
        else:
            xmlschema_doc = etree.parse(xsd_url_or_path)

        xmlschema = etree.XMLSchema(xmlschema_doc)
        if xmlschema.validate(xml_tree):
            return True, ""
        else:
            return False, xmlschema.error_log
    except Exception as e:
        return False, f"Validation script error: {str(e)}"


def process_amcr_xml(input_path, output_path, xpaths, translator, src_lang, tgt_lang, xsd_url=None, csv_writer=None,
                     identifier=None):
    try:
        tree = etree.parse(str(input_path))
        root = tree.getroot()

        # OAI-PMH FIX: Deep search for AMCR namespaces
        xpath_ns = {}
        for elem in root.iter():
            for prefix, uri in elem.nsmap.items():
                if uri and 'amcr' in uri:
                    xpath_ns['amcr'] = uri
                if uri and 'OAI-PMH' in uri:
                    xpath_ns['oai'] = uri  # Capture OAI envelope namespace
            if 'amcr' in xpath_ns and 'oai' in xpath_ns:
                break

        # Hard fallback if absolutely no namespace is explicitly found
        if 'amcr' not in xpath_ns:
            xpath_ns['amcr'] = "http://amcr.aiscr.cz/ns/amcr"

        for xpath in xpaths:
            try:
                elements = root.xpath(xpath, namespaces=xpath_ns)
                for elem in elements:
                    original_text = elem.text
                    if original_text and original_text.strip():
                        # Determine actual source language
                        actual_src_lang = src_lang
                        if src_lang == "auto" and identifier:
                            detected_lang, conf = identifier.detect(original_text)
                            actual_src_lang = detected_lang if conf > 0.2 else "cs"
                        elif src_lang == "auto":
                            actual_src_lang = "cs"  # Fallback if identifier fails/is missing

                        translated = translator.translate(original_text, actual_src_lang, tgt_lang)
                        elem.text = translated

                        if csv_writer:
                            doc_name = input_path.name.split('.')[0]
                            csv_writer.writerow([doc_name, "", xpath, original_text, translated])
            except etree.XPathEvalError as e:
                print(f"[WARN] Invalid XPath expression '{xpath}': {e}")

        if xsd_url:
            print(f"[INFO] Validating {output_path.name} against XSD...")
            is_valid, error_log = validate_xml_with_xsd(tree, xsd_url)
            if not is_valid:
                print(f"[WARN] XSD Validation failed for {output_path.name}:\n{error_log}")
            else:
                print(f"[SUCCESS] XSD Validation passed for {output_path.name}")

        tree.write(str(output_path), encoding='utf-8', xml_declaration=True, pretty_print=True)
        print(f"[SUCCESS] Saved AMCR translation to: {output_path}")

    except Exception as e:
        print(f"[ERROR] Failed to process AMCR XML {input_path}: {e}")


def process_alto_xml(input_path, output_path, translator, src_lang, tgt_lang, csv_writer=None, identifier=None):
    try:
        tree = etree.parse(str(input_path))
        root = tree.getroot()
        nsmap = root.nsmap
        ns = {'alto': nsmap[None]} if None in nsmap else nsmap
        pages = root.xpath('//alto:Page', namespaces=ns) if 'alto' in ns else root.xpath('//Page')

        for page_idx, page in enumerate(pages, 1):
            text_lines = page.xpath('.//alto:TextLine', namespaces=ns) if 'alto' in ns else page.xpath('.//TextLine')
            total_lines = len(text_lines)

            for line_idx, line in enumerate(text_lines, 1):
                sys.stdout.write(f"\r[INFO] Page {page_idx} | Processing text block: {line_idx}/{total_lines}")
                sys.stdout.flush()

                line_id = line.get('ID', str(line_idx))
                strings = line.xpath('.//alto:String', namespaces=ns) if 'alto' in ns else line.xpath('.//String')
                if not strings:
                    continue

                line_text = " ".join([s.get('CONTENT', '') for s in strings if s.get('CONTENT')]).strip()
                if not line_text:
                    continue

                # Language Identification
                actual_src_lang = src_lang
                if src_lang == "auto" and identifier:
                    detected_lang, _ = identifier.detect(line_text)
                    actual_src_lang = detected_lang

                translated_text = translator.translate(line_text, actual_src_lang, tgt_lang)

                if csv_writer:
                    doc_name = input_path.name.split('.')[0]
                    csv_writer.writerow([doc_name, page_idx, line_id, line_text, translated_text])

                trans_words = translated_text.split()
                num_strings = len(strings)
                words_per_string = len(trans_words) // num_strings
                remainder = len(trans_words) % num_strings

                word_idx = 0
                for i, string_elem in enumerate(strings):
                    count = words_per_string + (1 if i < remainder else 0)
                    assigned_words = trans_words[word_idx: word_idx + count]
                    word_idx += count
                    string_elem.set('CONTENT', " ".join(assigned_words))

            if total_lines > 0:
                print()

        tree.write(str(output_path), encoding='utf-8', xml_declaration=True)
        print(f"[SUCCESS] Saved ALTO translation to: {output_path}")

    except Exception as e:
        print(f"\n[ERROR] Failed to process ALTO XML {input_path}: {e}")