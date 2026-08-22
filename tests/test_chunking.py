from __future__ import annotations

import pytest
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.utils import globals_helper

from google_drive_rag_mcp.chunking import LlamaIndexChunker, _split_sentences


def test_sentence_tokenizer_supports_english_and_vietnamese_punctuation() -> None:
    text = (
        "First sentence. Second question? Third answer! "
        "Xin chào Việt Nam. Bạn khỏe không? Tôi khỏe! Đúng vậy… "
        "Không cần khoảng trắng。Câu cuối？"
    )

    assert _split_sentences(text) == [
        "First sentence.",
        " Second question?",
        " Third answer!",
        " Xin chào Việt Nam.",
        " Bạn khỏe không?",
        " Tôi khỏe!",
        " Đúng vậy…",
        " Không cần khoảng trắng。",
        "Câu cuối？",
    ]


def test_chunking_does_not_initialize_nltk_data(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_nltk_data() -> None:
        raise PermissionError(
            "Security Violation [pathsec.open]: refusing multiply-linked stopwords file"
        )

    monkeypatch.setattr(globals_helper, "_stopwords", None)
    monkeypatch.setattr(globals_helper, "_punkt_tokenizer", None)
    monkeypatch.setattr(globals_helper, "wait_for_nltk_check", reject_nltk_data)

    text = "Xin chào Việt Nam. This remains available!"
    with pytest.raises(PermissionError, match="multiply-linked stopwords"):
        SentenceSplitter(chunk_size=12, chunk_overlap=4).split_text(text)

    chunks = LlamaIndexChunker(chunk_size=12, chunk_overlap=4).split(text)

    assert chunks == ["Xin chào Việt Nam.", "This remains available!"]
    assert globals_helper._stopwords is None
    assert globals_helper._punkt_tokenizer is None


def test_long_text_preserves_chunk_size_and_overlap_behavior() -> None:
    text = (
        "One two three. Four five six. Seven eight nine. "
        "Ten eleven twelve. Thirteen fourteen fifteen."
    )
    chunker = LlamaIndexChunker(chunk_size=12, chunk_overlap=4)

    chunks = chunker.split(text)

    assert chunks == [
        "One two three. Four five six. Seven eight nine.",
        "Seven eight nine. Ten eleven twelve.",
        "Ten eleven twelve. Thirteen fourteen fifteen.",
    ]
    assert "Seven eight nine." in chunks[0] and "Seven eight nine." in chunks[1]
    assert "Ten eleven twelve." in chunks[1] and "Ten eleven twelve." in chunks[2]

    long_chunks = chunker.split(" ".join([text] * 20))
    assert len(long_chunks) > 20
    assert all(len(chunker.splitter._tokenizer(chunk)) <= 12 for chunk in long_chunks)


def test_chunking_empty_input_and_output_are_deterministic() -> None:
    chunker = LlamaIndexChunker(chunk_size=12, chunk_overlap=4)
    text = "Một hai ba. Four five six? Bảy tám chín!"

    assert chunker.split("") == []
    assert chunker.split("   \n\n") == []
    assert chunker.split(text) == chunker.split(text)
