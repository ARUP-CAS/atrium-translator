"""
tests/test_ct2_translator.py – regression coverage for the CTranslate2 backend.

No model files, network access, GPU, CTranslate2 runtime, or Transformers
installation are required: the heavy modules are replaced with small fakes.
"""

import sys
from types import SimpleNamespace

import pytest

from processors.ct2_translator import CT2Translator


class _FakeTokenizer:
    eos_token = "<|im_end|>"

    def __init__(self):
        self.chat_template_calls = []
        self.tokenizer_calls = []
        self.decode_calls = []

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        self.chat_template_calls.append((messages, tokenize, add_generation_prompt))
        assert tokenize is False
        assert add_generation_prompt is True
        return "<|im_start|>user<|im_end|><|im_start|>assistant"

    def __call__(self, prompt, *, add_special_tokens):
        self.tokenizer_calls.append((prompt, add_special_tokens))
        assert add_special_tokens is False
        return {"input_ids": [101, 102, 103]}

    def convert_ids_to_tokens(self, ids):
        return [f"tok-{i}" for i in ids]

    def convert_tokens_to_ids(self, tokens):
        return list(range(200, 200 + len(tokens)))

    def decode(self, ids, *, skip_special_tokens, clean_up_tokenization_spaces):
        self.decode_calls.append((ids, skip_special_tokens, clean_up_tokenization_spaces))
        return "Archaeological research took place in Prague's historic centre."


class _FakeGenerator:
    def __init__(self, model_dir, *, device, compute_type):
        self.model_dir = model_dir
        self.device = device
        self.compute_type = compute_type
        self.calls = []

    def generate_batch(self, sequences, **kwargs):
        self.calls.append((sequences, kwargs))
        return [SimpleNamespace(sequences=[["out-1", "out-2"]])]


def _install_fake_modules(monkeypatch, tokenizer):
    fake_engine = _FakeGenerator
    fake_ct2 = SimpleNamespace(
        Generator=fake_engine,
        Translator=object,
        get_supported_compute_types=lambda device: {"int8"},
    )
    fake_transformers = SimpleNamespace(AutoTokenizer=SimpleNamespace(from_pretrained=lambda path, **kwargs: tokenizer))
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    return fake_engine


def test_eurollm_uses_hf_chat_template_and_ct2_tokens(monkeypatch):
    tokenizer = _FakeTokenizer()
    engine_cls = _install_fake_modules(monkeypatch, tokenizer)

    backend = CT2Translator(
        model_dir="/models/eurollm-ct2",
        family="eurollm",
        device="cuda",
        compute_type="int8",
        languages=["cs", "en"],
    )

    output = backend.translate(
        "Archeologický výzkum proběhl v centru Prahy.",
        "cs",
        "en",
    )

    assert output == "Archaeological research took place in Prague's historic centre."
    assert tokenizer.chat_template_calls[0][1:] == (False, True)
    assert tokenizer.tokenizer_calls == [
        (
            "<|im_start|>user<|im_end|><|im_start|>assistant",
            False,
        )
    ]
    assert tokenizer.decode_calls[0][1:] == (True, True)

    # The CTranslate2 engine receives token strings, never the characters of the
    # prompt. The generated end token is the model's actual EOS token.
    engine = backend._engine
    assert isinstance(engine, engine_cls)
    assert engine.calls[0][0] == [["tok-101", "tok-102", "tok-103"]]
    assert engine.calls[0][1]["end_token"] == "<|im_end|>"
    assert engine.calls[0][1]["include_prompt_in_result"] is False


def test_eurollm_does_not_load_sentencepiece_even_when_ct2_sp_model_is_set(
    monkeypatch,
):
    tokenizer = _FakeTokenizer()
    _install_fake_modules(monkeypatch, tokenizer)

    fake_sp = SimpleNamespace(
        SentencePieceProcessor=lambda **kwargs: pytest.fail("SentencePiece must not be loaded for EuroLLM")
    )
    monkeypatch.setitem(sys.modules, "sentencepiece", fake_sp)

    backend = CT2Translator(
        model_dir="/models/eurollm-ct2",
        family="eurollm",
        sp_model="/some/sentencepiece.model",
        device="cuda",
        compute_type="int8",
    )
    backend.translate("Archeologický výzkum proběhl v Praze.", "cs", "en")
