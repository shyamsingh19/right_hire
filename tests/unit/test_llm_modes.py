from __future__ import annotations

import instructor

from app.llm._openai_compatible import OpenAICompatibleProvider
from app.llm.cerebras import CerebrasProvider
from app.llm.groq import GroqProvider


def test_instructor_modes_resolve():
    """Every provider's instructor_mode must name a real instructor.Mode member —
    _complete_json_once resolves it with getattr, so a typo or an instructor upgrade
    that renames a mode would only surface as an AttributeError on a live LLM call."""
    for provider in (OpenAICompatibleProvider, CerebrasProvider, GroqProvider):
        mode = provider.instructor_mode
        assert hasattr(instructor.Mode, mode), f"{provider.__name__}.instructor_mode={mode!r}"


if __name__ == "__main__":
    test_instructor_modes_resolve()
    print("ok")
