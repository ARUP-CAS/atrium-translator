import re
import xml.etree.ElementTree as ET
import numpy as np


def get_alto_textblocks(xml_path):
    """
    Parses an ALTO XML file and extracts text strictly at the TextBlock level
    for contextual coherence. Preserves namespace for accurate write-back.
    Returns: (tree, root, namespace, blocks_data)
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        namespace = ''

        if '}' in root.tag:
            namespace_uri = root.tag.split('}')[0].strip('{')
            namespace = f"{{{namespace_uri}}}"
            ET.register_namespace('', namespace_uri)
    except Exception as e:
        print(f"[ERROR] Failed to parse ALTO XML file {xml_path}: {type(e).__name__} - {e}")
        return None, None, None, []

    blocks_data = []

    try:
        search_tag = f".//{namespace}TextBlock" if namespace else ".//TextBlock"
        text_blocks = root.findall(search_tag)

        for block in text_blocks:
            block_text_parts = []
            lines_data = []

            line_search_tag = f".//{namespace}TextLine" if namespace else ".//TextLine"
            string_search_tag = f".//{namespace}String" if namespace else ".//String"

            for line in block.findall(line_search_tag):
                line_text_parts = []
                for string_elem in line.findall(string_search_tag):
                    content = string_elem.attrib.get('CONTENT', '').strip()
                    if content:
                        line_text_parts.append(content)

                line_text = " ".join(line_text_parts)
                if line_text:
                    lines_data.append(line)
                    block_text_parts.append(line_text)

            block_text = " ".join(block_text_parts)
            if block_text.strip() and lines_data:
                blocks_data.append((block, block_text, lines_data))

        return tree, root, namespace, blocks_data
    except Exception as e:
        print(f"[ERROR] Element extraction failed during ALTO block parsing: {type(e).__name__} - {e}")
        return tree, root, namespace, []


def get_xml_elements_and_texts(xml_path, fields_path):
    """
    Parses a general XML file, reads tags of interest from a provided text file,
    and yields elements matching those specific tags with their textual content.
    Returns: (tree, root, namespace, elements_data)
    """
    try:
        with open(fields_path, 'r', encoding='utf-8') as f:
            fields = [line.strip() for line in f if line.strip()]
    except Exception as e:
        print(f"[ERROR] Reading fields configuration file failed ({fields_path}): {type(e).__name__} - {e}")
        return None, None, None, []

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        namespace = ''

        if '}' in root.tag:
            namespace_uri = root.tag.split('}')[0].strip('{')
            namespace = f"{{{namespace_uri}}}"
            ET.register_namespace('', namespace_uri)
    except Exception as e:
        print(f"[ERROR] Parsing generic XML file failed ({xml_path}): {type(e).__name__} - {e}")
        return None, None, None, []

    elements_data = []
    try:
        for field in fields:
            search_tag = f".//{namespace}{field}" if namespace else f".//{field}"
            elements = root.findall(search_tag)

            if not elements:
                elements = root.findall(f".//{field}")

            for elem in elements:
                if 'CONTENT' in elem.attrib and elem.attrib['CONTENT'].strip():
                    elements_data.append((elem, 'CONTENT', elem.attrib['CONTENT']))
                elif elem.text and elem.text.strip():
                    elements_data.append((elem, 'text', elem.text))

        return tree, root, namespace, elements_data
    except Exception as e:
        print(f"[ERROR] Generic XML element parsing loop failed: {type(e).__name__} - {e}")
        return tree, root, namespace, []


def parse_alto_xml(xml_path):
    """
    Parses ALTO XML primarily to extract bounding boxes (x, y, w, h) and
    their corresponding string contents for downstream LayoutLM processing.
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        print(f"[ERROR] Extracting ALTO boxes failed during XML Parse ({xml_path}): {type(e).__name__} - {e}")
        return [], [], (0, 0)

    try:
        ns = {'alto': root.tag.split('}')[0].strip('{')} if '}' in root.tag else {}

        def find_all(node, tag):
            return node.findall(f'.//alto:{tag}', ns) if ns else node.findall(f'.//{tag}')

        page = root.find('.//alto:Page', ns) if ns else root.find('.//Page')
        if page is None:
            return [], [], (0, 0)

        page_w = int(float(page.attrib.get('WIDTH', 0)))
        page_h = int(float(page.attrib.get('HEIGHT', 0)))

        words = []
        boxes = []

        text_lines = find_all(root, 'TextLine')
        for line in text_lines:
            children = list(line)
            for i, child in enumerate(children):
                tag_name = child.tag.split('}')[-1]
                if tag_name == 'String':
                    content = child.attrib.get('CONTENT')
                    if not content: continue

                    try:
                        x = int(float(child.attrib.get('HPOS')))
                        y = int(float(child.attrib.get('VPOS')))
                        w = int(float(child.attrib.get('WIDTH')))
                        h = int(float(child.attrib.get('HEIGHT')))
                    except (ValueError, TypeError):
                        continue

                    words.append(content)
                    boxes.append([x, y, x + w, y + h])

        return words, boxes, (page_w, page_h)
    except Exception as e:
        print(f"[ERROR] ALTO box and word string extraction logic failed: {type(e).__name__} - {e}")
        return [], [], (0, 0)


def normalize_boxes(boxes, width, height):
    """
    Normalizes coordinates bounds dynamically generated from extraction tools
    (e.g., pdfplumber) to a 0-1000 scale expected inherently by the LayoutLM model.
    """
    try:
        if width == 0 or height == 0:
            return [[0, 0, 0, 0] for _ in boxes]

        x_scale = 1000.0 / width
        y_scale = 1000.0 / height

        norm_boxes = []
        for (x1, y1, x2, y2) in boxes:
            nx1 = max(0, min(1000, int(round(x1 * x_scale))))
            ny1 = max(0, min(1000, int(round(y1 * y_scale))))
            nx2 = max(0, min(1000, int(round(x2 * x_scale))))
            ny2 = max(0, min(1000, int(round(y2 * y_scale))))
            norm_boxes.append([nx1, ny1, nx2, ny2])
        return norm_boxes
    except Exception as e:
        print(f"[ERROR] Failed normalizing bounding boxes: {type(e).__name__} - {e}")
        return [[0, 0, 0, 0] for _ in boxes]