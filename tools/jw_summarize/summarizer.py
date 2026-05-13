from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from .config import Settings
from .exceptions import ProcessingError
from .llm import Profile, Provider, get_llm


SYSTEM_PROMPT = """You summarize JW talk transcripts into clean Markdown notes.

Requirements:
- Write the output in Japanese.
- Use Markdown headings and flat bullet lists only.
- Keep the content concise and structured for Obsidian.
- Preserve explicit scripture references when they appear.
- Do not quote long transcript passages verbatim.
- Focus on the speaker's main claims, supporting points, and practical application.
"""


def summarize_text(
    text: str,
    settings: Settings,
    provider: Provider | None = None,
    profile: Profile | None = None,
) -> str:
    llm = get_llm(settings=settings, provider=provider, profile=profile)
    response = llm.invoke(
        [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    "次の文字起こしを要約し、Obsidian向け Markdown ノートとして出力してください。\n\n"
                    f"{text}"
                )
            ),
        ]
    )
    summary = _extract_response_text(response).strip()
    if not summary:
        raise ProcessingError("The LLM returned an empty summary.")
    return summary


def _extract_response_text(response: object) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()
    return str(content)
