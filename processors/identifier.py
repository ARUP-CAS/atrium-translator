import logging

import fasttext
from huggingface_hub import hf_hub_download

# (12-factor XI) Library module: getLogger only, never basicConfig. The root
# logger is configured in service/api.py's __main__ block. (issue #61)
logger = logging.getLogger(__name__)


class LanguageIdentifier:
    # Map ISO 639-3 (FastText) to ISO 639-1 (Lindat)
    CODE_MAP = {
        "ces": "cs",
        "eng": "en",
        "fra": "fr",
        "deu": "de",
        "rus": "ru",
        "pol": "pl",
        "ukr": "uk",
        "slk": "sk",
        "bul": "bg",
        "hrv": "hr",
        "slv": "sl",
        "lav": "lv",
        "lit": "lt",
        "est": "et",
        "hun": "hu",
        "ron": "ro",
        "spa": "es",
        "ita": "it",
        "nld": "nl",
        "hin": "hi",
    }

    def __init__(self):
        """
        Initializes the LanguageIdentifier by downloading and loading
        the FastText language identification model from Hugging Face Hub.
        """
        # `load_error` is the declared half of a degraded start. Without it the
        # failure below was swallowed: self.model became None, detect() then
        # answered ("en", 0.0) for EVERY document, and nothing upstream could
        # tell that apart from a genuine English detection. In an egress-
        # restricted cluster hf_hub_download is exactly what fails, so the
        # service came up "healthy" and quietly mislabelled every source
        # language it was given. service/api.py's _deep_health() reads this.
        self.load_error: str | None = None
        self._warned_unavailable = False
        try:
            model_path = hf_hub_download(repo_id="facebook/fasttext-language-identification", filename="model.bin")
            self.model = fasttext.load_model(model_path)
        except Exception as e:
            self.load_error = f"{type(e).__name__}: {e}"
            logger.error(
                "Failed to load the FastText language-identification model (%s). "
                "Language detection is unavailable; every document will be reported as 'en' "
                "with confidence 0.0 until this is fixed.",
                self.load_error,
            )
            self.model = None

    def detect(self, text):
        """
        Detects the language of the provided text. Normalizes text structure,
        queries the FastText model, and maps the ISO 639-3 result to ISO 639-1.
        Returns a tuple: (language_code, confidence_score).
        """
        if not self.model:
            # Once per process, not once per line: this path fires for every
            # chunk of every document, and a log line repeated thousands of times
            # buries the one at startup that says why.
            if not self._warned_unavailable:
                self._warned_unavailable = True
                logger.warning(
                    "Language identification model is not loaded (%s); defaulting to 'en'.",
                    self.load_error or "reason unrecorded",
                )
            return "en", 0.0

        if not text or not text.strip():
            return "en", 0.0

        # Lowercase for better detection
        clean_text = text.replace("\n", " ").lower()[:2000]

        try:
            labels, scores = self.model.predict(clean_text)

            raw_label = labels[0].replace("__label__", "")
            iso3_code = raw_label.split("_")[0]
            lang_code = self.CODE_MAP.get(iso3_code, iso3_code)

            score = scores[0]
            return lang_code, score
        except Exception as e:
            print(f"[ERROR] Language detection prediction failed: {type(e).__name__} - {e}")
            return "en", 0.0
