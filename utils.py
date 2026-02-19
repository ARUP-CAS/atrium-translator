import re
import xml.etree.ElementTree as ET
import numpy as np


def get_xml_elements_and_texts(xml_path, fields_path):
    """
    Parses an XML file and extracts elements matching tags in the fields file.
    Returns: (tree, root, namespace, elements_data)
    where elements_data is a list of tuples: (Element, 'CONTENT' or 'text', text_string)
    """
    try:
        with open(fields_path, 'r', encoding='utf-8') as f:
            fields = [line.strip() for line in f if line.strip()]
    except Exception as e:
        print(f"Error reading fields file: {e}")
        return None, None, None, []

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        namespace = ''

        # Determine and register namespace to preserve it during output write
        if '}' in root.tag:
            namespace_uri = root.tag.split('}')[0].strip('{')
            namespace = f"{{{namespace_uri}}}"
            ET.register_namespace('', namespace_uri)
    except Exception as e:
        print(f"Error parsing XML file: {e}")
        return None, None, None, []

    elements_data = []
    for field in fields:
        # Match with or without the detected namespace
        search_tag = f".//{namespace}{field}" if namespace else f".//{field}"
        elements = root.findall(search_tag)

        if not elements:
            elements = root.findall(f".//{field}")

        for elem in elements:
            # Prioritize ALTO's CONTENT attribute, fallback to inner text
            if 'CONTENT' in elem.attrib and elem.attrib['CONTENT'].strip():
                elements_data.append((elem, 'CONTENT', elem.attrib['CONTENT']))
            elif elem.text and elem.text.strip():
                elements_data.append((elem, 'text', elem.text))

    return tree, root, namespace, elements_data

def parse_alto_xml(xml_path):
    """
    Parses ALTO XML to extract words and bounding boxes.
    Ref: text_util.py from uploaded context.
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        print(f"XML Parse Error: {e}")
        return [], [], (0, 0)

    # Handle namespaces if present (e.g., alto:String)
    ns = {'alto': root.tag.split('}')[0].strip('{')} if '}' in root.tag else {}

    def find_all(node, tag):
        return node.findall(f'.//alto:{tag}', ns) if ns else node.findall(f'.//{tag}')

    page = root.find('.//alto:Page', ns) if ns else root.find('.//Page')
    if page is None:
        return [], [], (0, 0)

    try:
        page_w = int(float(page.attrib.get('WIDTH')))
        page_h = int(float(page.attrib.get('HEIGHT')))
    except (ValueError, TypeError):
        return [], [], (0, 0)

    words = []
    boxes = []

    # Iterate through all TextLines and Strings
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


def normalize_boxes(boxes, width, height):
    """Normalizes coordinates to 0-1000 scale required by LayoutLM."""
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