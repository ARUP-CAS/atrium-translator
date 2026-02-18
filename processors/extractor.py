import torch
import pdfplumber
from transformers import LayoutLMv3ForTokenClassification
from utils import *

# FIX: Import these globally so they are available in _infer_order
try:
    from v3.helpers import prepare_inputs, boxes2inputs, parse_logits
except ImportError:
    print("WARNING: 'v3' module not found. LayoutReader inference will fail.")


    # Dummy fallbacks to prevent NameError if import fails
    def boxes2inputs(*args):
        raise ImportError("v3 missing")


    def prepare_inputs(*args):
        return {}


    def parse_logits(*args):
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
        # Imports handled globally now

        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Found device: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")

        print(f"Loading LayoutReader ({self.device})...")
        self.model = LayoutLMv3ForTokenClassification.from_pretrained(model_path)
        self.model.to(self.device).eval()

    def _infer_order(self, words, boxes):
        # ... (same as before, but now boxes2inputs will work) ...
        # Only showing relevant lines to confirm context:
        CHUNK_SIZE = 350
        full_ordered_words = []
        for i in range(0, len(words), CHUNK_SIZE):
            b_words = words[i:i + CHUNK_SIZE]
            b_boxes = boxes[i:i + CHUNK_SIZE]
            if not b_words: continue
            try:
                # Global function call
                inputs = boxes2inputs(b_boxes)
                inputs = prepare_inputs(inputs, self.model)

                # Move tensors to device
                for k, v in inputs.items():
                    if isinstance(v, torch.Tensor):
                        inputs[k] = v.to(self.device)

                # Inference
                with torch.no_grad():
                    logits = self.model(**inputs).logits.cpu().squeeze(0)

                # Decode order
                order_indices = parse_logits(logits, len(b_boxes))

                # Reorder this chunk
                ordered_chunk = [b_words[idx] for idx in order_indices]
                full_ordered_words.extend(ordered_chunk)

            except Exception as e:
                print(f"LayoutReader Error on chunk {i}: {e}")
                # Fallback: keep original order if inference fails
                full_ordered_words.extend(b_words)

        return " ".join(full_ordered_words)

    def process_alto(self, xml_path):
        """Extracts text from ALTO XML and reorders using LayoutReader."""
        words, boxes, (w, h) = parse_alto_xml(xml_path)

        if not words:
            return ""

        norm_boxes = normalize_boxes(boxes, w, h)
        return self._infer_order(words, norm_boxes)

    def process_pdf(self, pdf_path):
        """Extracts text from PDF and reorders using LayoutReader."""
        full_text = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                width, height = page.width, page.height
                words = page.extract_words()

                if not words: continue

                # pdfplumber returns x0, top, x1, bottom
                raw_boxes = [[w['x0'], w['top'], w['x1'], w['bottom']] for w in words]
                text_content = [w['text'] for w in words]

                norm_boxes = normalize_boxes(raw_boxes, width, height)

                # Reorder page content
                page_text = self._infer_order(text_content, norm_boxes)
                full_text.append(page_text)

        return "\n\n".join(full_text)

    def process_docx(self, docx_path):
        """Extracts text from DOCX files linearly."""
        try:
            doc = docx.Document(docx_path)
            # Join paragraphs with newlines
            return "\n".join([para.text for para in doc.paragraphs])
        except Exception as e:
            print(f"Error processing DOCX: {e}")
            return ""

    def process_html(self, html_path):
        """Extracts text from HTML files using BeautifulSoup."""
        try:
            with open(html_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'lxml')
                # get_text with separator ensures words don't merge across tags
                return soup.get_text(separator=' ')
        except Exception as e:
            print(f"Error processing HTML: {e}")
            return ""

    def extract(self, file_path):
        ext = file_path.lower().split('.')[-1]

        if ext == 'xml':
            return self.process_alto(file_path)
        elif ext == 'pdf':
            return self.process_pdf(file_path)
        elif ext == 'docx':
            return self.process_docx(file_path)
        elif ext in ['html', 'htm']:
            return self.process_html(file_path)
        elif ext == 'txt':
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            raise ValueError(f"Unsupported file format: .{ext}")