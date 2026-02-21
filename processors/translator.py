import requests
import sys

# Graceful fallback for tqdm inside the translator for large text chunks
try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, *args, **kwargs):
        """
        Fallback generator if tqdm is not installed.
        Yields items from the iterable without displaying a progress bar.
        """
        for item in iterable:
            yield item


class LindatTranslator:
    BASE_URL = "https://lindat.mff.cuni.cz/services/translation/api/v2"

    def __init__(self):
        """
        Initializes the LindatTranslator by dynamically fetching the
        supported translation models from the API.
        """
        self.supported_models = self._fetch_models()

    def _fetch_models(self):
        """
        Dynamically fetches supported language pairs from the Lindat API.
        Returns a list of supported model strings (e.g., 'cs-en').
        """
        try:
            resp = requests.get(f"{self.BASE_URL}/models")
            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, dict) and '_embedded' in data:
                return [item['model'] for item in data['_embedded'].get('item', [])]
            elif isinstance(data, list):
                return data
            else:
                return []
        except requests.exceptions.RequestException as e:
            print(f"[WARN] Network error fetching models from API ({type(e).__name__}: {e}). Using default list.")
            return ["fr-en", "cs-en", "de-en", "uk-en", "ru-en", "pl-en"]
        except ValueError as e:
            print(f"[WARN] Invalid JSON response when fetching models ({type(e).__name__}: {e}). Using default list.")
            return ["fr-en", "cs-en", "de-en", "uk-en", "ru-en", "pl-en"]

    def translate(self, text, src_lang, tgt_lang="en"):
        """
        Translates text from src_lang to tgt_lang using the Lindat API.
        Chunks text automatically to respect API limits.
        """
        # Prevents unnecessary network calls for blanks
        if not text or not text.strip() or src_lang == tgt_lang:
            return text

        model_name = f"{src_lang}-{tgt_lang}"

        if self.supported_models:
            if model_name not in self.supported_models:
                print(f"[ERROR] Model '{model_name}' not found. Available models: {', '.join(self.supported_models)}")
                return f"[ERROR: Model {model_name} not supported]"
        else:
            print(f"[WARN] Proceeding with '{model_name}' (model validation unavailable).")

        # Chunk text to avoid 100KB limit
        chunks = self._chunk_text(text)
        translated_chunks = []

        # Only show a progress bar here if we actually have multiple chunks
        chunk_iter = tqdm(chunks, desc="Translating long text chunks", leave=False) if len(chunks) > 1 else chunks

        for i, chunk in enumerate(chunk_iter):
            data = {"input_text": chunk}

            try:
                response = requests.post(
                    f"{self.BASE_URL}/models/{model_name}?src={src_lang}&tgt={tgt_lang}",
                    data=data
                )

                if response.status_code == 200:
                    translated_chunks.append(response.text.strip())
                else:
                    error_msg = f"[Translation Failed on chunk {i}: HTTP {response.status_code} - {response.reason}]"
                    print(error_msg)
                    translated_chunks.append(error_msg)
            except requests.exceptions.RequestException as e:
                error_msg = f"[Network Error on chunk {i}: {type(e).__name__} - {e}]"
                print(error_msg)
                translated_chunks.append(error_msg)

        return "\n".join(translated_chunks)

    def _chunk_text(self, text, chunk_size=5000):
        """
        Splits text into smaller chunks of maximum 'chunk_size' characters
        to ensure compatibility with API payload limits.
        """
        return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]