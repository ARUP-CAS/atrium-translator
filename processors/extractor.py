import torch
import pdfplumber
from transformers import LayoutLMv3ForTokenClassification
from utils import *

try:
    from v3.helpers import prepare_inputs, boxes2inputs, parse_logits
except ImportError:
    print("WARNING: 'v3' module not found. LayoutReader inference will fail.")

    def boxes2inputs(*args):
        """Dummy fallback if v3 module is missing to prevent NameError."""
        raise ImportError("v3 missing. Cannot convert boxes to inputs.")

    def prepare_inputs(*args):
        """Dummy fallback if v3 module is missing to prevent NameError."""
        return {}

    def parse_logits(*args):
        """Dummy fallback if v3 module is missing to prevent NameError."""
        return []

try:
    import docx
except ImportError:
    pass
try:
    from bs4 import BeautifulSoup
except ImportError:
    pass


class LayoutExtractor:
    def __init__(self, model_path="hantian/layoutreader"):
        """
        Initializes the layout extractor, loads the LayoutLMv3 model into
        memory, and moves it to the appropriate device (CUDA/CPU).
        """
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Found device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")

        print(f"Loading LayoutReader ({self.device})...")
        try:
            self.model = LayoutLMv3ForTokenClassification.from_pretrained(model_path)
            self.model.to(self.device).eval()
        except Exception as e:
            print(f"[ERROR] Failed to load LayoutReader model from {model_path}: {type(e).__name__} - {e}")

    def _infer_order(self, words, boxes):
        """
        Infers the reading order of text blocks using the LayoutReader model
        by passing word bounding boxes through layout evaluation.
        """
        CHUNK_SIZE = 350
        full_ordered_words = []
        for i in range(0, len(words), CHUNK_SIZE):
            b_words = words[i:i + CHUNK_SIZE]
            b_boxes = boxes[i:i + CHUNK_SIZE]
            if not b_words: continue
            try:
                inputs = boxes2inputs(b_boxes)
                inputs = prepare_inputs(inputs, self.model)

                for k, v in inputs.items():
                    if isinstance(v, torch.Tensor):
                        inputs[k] = v.to(self.device)

                with torch.no_grad():
                    logits = self.model(**inputs).logits.cpu().squeeze(0)

                order_indices = parse_logits(logits, len(b_boxes))

                ordered_chunk = [b_words[idx] for idx in order_indices]
                full_ordered_words.extend(ordered_chunk)

            except Exception as e:
                print(f"[ERROR] LayoutReader inference failed on chunk index {i}: {type(e).__name__} - {e}")
                # Fallback: keep original order if inference fails
                full_ordered_words.extend(b_words)

        return " ".join(full_ordered_words)

    def process_alto(self, xml_path):
        """
        Extracts text from ALTO XML, normalizes the bounding boxes, and
        reorders the text logically using LayoutReader.
        """
        try:
            words, boxes, (w, h) = parse_alto_xml(xml_path)

            if not words:
                return ""

            norm_boxes = normalize_boxes(boxes, w, h)
            return self._infer_order(words, norm_boxes)
        except Exception as e:
            print(f"[ERROR] Failed to process ALTO XML file {xml_path}: {type(e).__name__} - {e}")
            return ""

    def process_pdf(self, pdf_path):
        """
        Iterates over a PDF file page-by-page, extracts text and layout,
        and reorders it logically using LayoutReader.
        """
        full_text = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    width, height = page.width, page.height
                    words = page.extract_words()

                    if not words: continue

                    raw_boxes = [[w['x0'], w['top'], w['x1'], w['bottom']] for w in words]
                    text_content = [w['text'] for w in words]

                    norm_boxes = normalize_boxes(raw_boxes, width, height)
                    page_text = self._infer_order(text_content, norm_boxes)
                    full_text.append(page_text)

            return "\n\n".join(full_text)
        except Exception as e:
            print(f"[ERROR] Failed to process PDF file {pdf_path}: {type(e).__name__} - {e}")
            return ""

    def process_docx(self, docx_path):
        """
        Extracts paragraphs linearly from a DOCX document.
        """
        try:
            doc = docx.Document(docx_path)
            return "\n".join([para.text for para in doc.paragraphs])
        except Exception as e:
            print(f"[ERROR] Failed to process DOCX file {docx_path}: {type(e).__name__} - {e}")
            return ""

    def process_html(self, html_path):
        """
        Extracts raw text from an HTML file, stripping all tags and separating
        text nodes safely to prevent merging.
        """
        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'lxml')
                return soup.get_text(separator=' ')
        except Exception as e:
            print(f"[ERROR] Failed to process HTML file {html_path}: {type(e).__name__} - {e}")
            return ""

    def process_csv(self, csv_path):
        """
        Extracts text from CSV files specifically by looking for a 'text'
        column and concatenating its cells.
        """
        try:
            import pandas as pd
            df = pd.read_csv(csv_path)
            text_col = None
            for col in df.columns:
                if 'text' in col.lower():
                    text_col = col
                    break
            if text_col:
                return "\n".join(df[text_col].dropna().astype(str).tolist())
            else:
                print(f"[WARN] No column containing 'text' found in CSV: {csv_path}")
                return ""
        except Exception as e:
            print(f"[ERROR] Failed to process CSV file {csv_path}: {type(e).__name__} - {e}")
            return ""

    def process_json(self, json_path):
        """
        Recursively explores a JSON file to find keys containing 'text'
        and extracts their string values into a consolidated block.
        """
        try:
            import json
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            def extract_text(obj):
                """Helper function to traverse dictionary trees."""
                if isinstance(obj, dict):
                    text_values = []
                    for k, v in obj.items():
                        if 'text' in k.lower() and isinstance(v, str):
                            text_values.append(v)
                        else:
                            text_values.extend(extract_text(v))
                    return text_values
                elif isinstance(obj, list):
                    text_values = []
                    for item in obj:
                        text_values.extend(extract_text(item))
                    return text_values
                else:
                    return []

            all_texts = extract_text(data)
            return "\n".join(all_texts)

        except Exception as e:
            print(f"[ERROR] Failed to process JSON file {json_path}: {type(e).__name__} - {e}")
            return ""

    def extract(self, file_path):
        """
        Master router for extraction. Delegates to the correct format
        processor based on file extension.
        """
        ext = str(file_path).lower().split('.')[-1]

        try:
            if ext == 'xml':
                return self.process_alto(file_path)
            elif ext == 'pdf':
                return self.process_pdf(file_path)
            elif ext == 'docx':
                return self.process_docx(file_path)
            elif ext in ['html', 'htm']:
                return self.process_html(file_path)
            elif ext == 'csv':
                return self.process_csv(file_path)
            elif ext == 'json':
                return self.process_json(file_path)
            elif ext == 'txt':
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            else:
                raise ValueError(f"Unsupported file format: .{ext}")
        except Exception as e:
            print(f"[ERROR] Extraction pipeline failed for {file_path}: {type(e).__name__} - {e}")
            return ""