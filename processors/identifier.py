import fasttext
from huggingface_hub import hf_hub_download


class LanguageIdentifier:
    # Map ISO 639-3 (FastText) to ISO 639-1 (Lindat)
    CODE_MAP = {
        'ces': 'cs', 'eng': 'en', 'fra': 'fr', 'deu': 'de',
        'rus': 'ru', 'pol': 'pl', 'ukr': 'uk', 'slk': 'sk',
        'bul': 'bg', 'hrv': 'hr', 'slv': 'sl', 'lav': 'lv',
        'lit': 'lt', 'est': 'et', 'hun': 'hu', 'ron': 'ro',
        'spa': 'es', 'ita': 'it', 'nld': 'nl', 'hin': 'hi'
    }

    def __init__(self):
        model_path = hf_hub_download(repo_id="facebook/fasttext-language-identification", filename="model.bin")
        self.model = fasttext.load_model(model_path)

    def detect(self, text):
        # Lowercase for better detection
        clean_text = text.replace('\n', ' ').lower()[:2000]
        labels, scores = self.model.predict(clean_text)

        # Label format is usually __label__ces_Latn
        raw_label = labels[0].replace("__label__", "")

        # Split 'ces_Latn' -> 'ces'
        iso3_code = raw_label.split('_')[0]

        # Map 'ces' -> 'cs'. Return original if not found (fallback)
        lang_code = self.CODE_MAP.get(iso3_code, iso3_code)

        score = scores[0]
        return lang_code, score