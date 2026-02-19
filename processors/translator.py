import requests


class LindatTranslator:
    BASE_URL = "https://lindat.mff.cuni.cz/services/translation/api/v2"

    def __init__(self):
        self.supported_models = self._fetch_models()
        # print(f"DEBUG: Loaded models: {self.supported_models}") # Uncomment to debug

    def _fetch_models(self):
        """Dynamically fetch supported language pairs."""
        try:
            resp = requests.get(f"{self.BASE_URL}/models")
            resp.raise_for_status()
            data = resp.json()

            # Fix: Handle Lindat's HAL JSON structure
            # Models are typically in data['_embedded']['item']
            if isinstance(data, dict) and '_embedded' in data:
                return [item['model'] for item in data['_embedded'].get('item', [])]
            elif isinstance(data, list):
                return data
            else:
                return []
        except Exception as e:
            print(f"Warning: Could not fetch models from API ({e}). Using default list.")
            return ["fr-en", "cs-en", "de-en", "uk-en", "ru-en", "pl-en"]

    def translate(self, text, src_lang, tgt_lang="en"):
        # NEW GUARD: Prevents unnecessary network calls for blanks
        if not text or not text.strip() or src_lang == tgt_lang:
            return text

        model_name = f"{src_lang}-{tgt_lang}"

        # Relaxed check: if model list is empty (API fail), try anyway
        if self.supported_models and model_name not in self.supported_models:
            # Try reversing if generic? No, strict for now.
            print(f"Warning: Direct model {model_name} not found in supported list.")
            # If we defaulted to 'cs' earlier, we might want to try anyway if list was empty

        model_name = f"{src_lang}-{tgt_lang}"

        # Check if model exists (e.g., 'fr-en')
        if model_name not in self.supported_models:
            # Try to see if there is a generic model or handle error
            print(f"Warning: Direct model {model_name} not found. Available: {self.supported_models}")
            # Depending on API, might fallback to transformer logic or fail
            # For this draft, we proceed hoping the API handles it or we return original
            if model_name not in self.supported_models:
                return f"[ERROR: Model {model_name} not supported]"

        # Chunk text to avoid 100KB limit
        chunks = self._chunk_text(text)
        translated_chunks = []

        for chunk in chunks:
            # formData parameters: input_text, src, tgt (optional if model in URL)
            data = {"input_text": chunk}

            # print(f"Requesting translation for chunk (length {len(chunk)} chars) using model {model_name}...")
            # print(f"DEBUG: Request data: {data}")  # Debugging line to check request payload
            # print(f"DEBUG: Request URL: {self.BASE_URL}/models/{model_name}?src={src_lang}&tgt={tgt_lang}")  # Debugging line to check URL
            # The URL pattern is /models/{model_name}/translate
            response = requests.post(
                f"{self.BASE_URL}/models/{model_name}?src={src_lang}&tgt={tgt_lang}",
                data=data
            )

            if response.status_code == 200:
                # Lindat returns the translated string directly usually
                translated_chunks.append(response.text.strip())
            else:
                # Log the error for debugging
                translated_chunks.append(f"[Translation Failed: {response.status_code} - {response.reason}]")

        return "\n".join(translated_chunks)

    def _chunk_text(self, text, chunk_size=5000):
        return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]