"""Gemini vision extraction. Same page, same prompt, same output contract.

Deliberately shares SYSTEM and PROMPT with the Anthropic extractor so the
benchmark compares models rather than prompts. Anything that differs between
the two runs is the model, not the instructions.

Gemini is here for three reasons: it has a free tier, so iterating on the
stitcher does not cost anything; it was the only model in the 21-parser table
benchmark that did not degrade on merged cells, which is every SoA; and two
independent readings of the same page give a real ambiguity signal -- where the
models disagree on a cell, a human should look.
"""

from __future__ import annotations

import json, pathlib, random, time

from .config import api_key
from .render import render
from .extract import SYSTEM, PROMPT, PageExtraction, _strip_fence, CACHE

# The 21-parser table benchmark rated "Gemini 3 Flash" highest on merged-cell
# tables. That exact id is not served; 3.7-flash is the current stable Flash on
# this account. Overridable with --model, and the id used is recorded in every
# output file so a result is always attributable to a specific model.
MODEL = "gemini-3.7-flash"

# Free-tier capacity is not guaranteed: a 503 "high demand" on the newest model
# is routine. Falling back down the family keeps a run from dying halfway, and
# the model that actually answered is recorded per page so the benchmark never
# attributes a result to the wrong model.
FALLBACKS = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
             "gemini-3-flash-preview", "gemini-2.5-flash"]
RETRIES = 4


def _cache_key(pdf_path: str, page_no: int, model: str) -> pathlib.Path:
    import hashlib
    h = hashlib.sha256()
    h.update(pathlib.Path(pdf_path).read_bytes()[:1_000_000])
    h.update(f"|{pathlib.Path(pdf_path).stat().st_size}|{page_no}|{model}|".encode())
    h.update((SYSTEM + PROMPT).encode())
    return CACHE / f"{pathlib.Path(pdf_path).stem}_p{page_no}_{h.hexdigest()[:16]}.json"


def extract_page(pdf_path: str, page_no: int, span: list[int] | None = None,
                 client=None, model: str = MODEL, use_cache: bool = True) -> PageExtraction:
    key = _cache_key(pdf_path, page_no, model)
    if use_cache and key.exists():
        c = json.loads(key.read_text())
        return PageExtraction(page=page_no, data=c["data"], raw=c["raw"],
                              usage={**c["usage"], "cached": True})

    from google import genai
    from google.genai import types

    client = client or genai.Client(api_key=api_key("GEMINI_API_KEY"))
    rp = render(pdf_path, page_no)
    span_note = (f", one of pages {span} that together hold a single "
                 f"Schedule of Activities") if span and len(span) > 1 else ""

    cfg = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        # JSON mode rather than prose-with-a-fence: the contract is a JSON
        # object and asking the API to enforce that removes a whole class of
        # parse failures.
        response_mime_type="application/json",
        max_output_tokens=32000,
        temperature=0,
        # Gemini 3 thinks by default and thinking tokens draw on the same
        # output budget. A page that returns zero output tokens has spent the
        # whole budget reasoning and emitted nothing -- which is how
        # protocol1 p53, half of that table, was silently lost. Cap thinking so
        # the budget goes to the answer.
        thinking_config=types.ThinkingConfig(thinking_budget=4096),
    )
    contents = [
        types.Part.from_bytes(data=rp.png, mime_type="image/png"),
        PROMPT.format(page=page_no, span_note=span_note),
    ]

    order = [model] + [m for m in FALLBACKS if m != model]
    resp = used = None
    last: Exception | str | None = None
    for candidate in order:
        for attempt in range(RETRIES):
            try:
                r = client.models.generate_content(
                    model=candidate, contents=contents, config=cfg)
            except Exception as e:                      # noqa: BLE001
                last = e
                code = getattr(e, "code", None) or getattr(e, "status_code", None)
                if code == 404:
                    break                               # wrong id, try next model
                if code not in (429, 500, 503, None):
                    raise
                time.sleep(min(2 ** attempt + random.random(), 20))
                continue

            # A 200 with no text is not success. It happens when the output
            # budget is exhausted or the response is filtered, and treating it
            # as an answer deletes a page of the table without a word.
            if (r.text or "").strip():
                resp, used = r, candidate
                break
            last = (f"empty response (finish_reason="
                    f"{getattr((r.candidates or [None])[0], 'finish_reason', '?')}, "
                    f"feedback={getattr(r, 'prompt_feedback', None)})")
            time.sleep(min(2 ** attempt + random.random(), 20))
        if resp is not None:
            break
    if resp is None:
        raise RuntimeError(
            f"Gemini produced no usable response for {pathlib.Path(pdf_path).name} "
            f"p{page_no} after trying {order}: {last}")

    text = resp.text or ""
    try:
        data = json.loads(_strip_fence(text))
    except json.JSONDecodeError as e:
        data = {"is_soa_page": None, "parse_error": str(e)}

    um = resp.usage_metadata
    data.setdefault("_model", used)
    ex = PageExtraction(page=page_no, data=data, raw=text, usage={
        "input": getattr(um, "prompt_token_count", 0) or 0,
        "output": getattr(um, "candidates_token_count", 0) or 0,
        "model": used,
    })
    # Never cache a failure: a cached parse error is indistinguishable from a
    # cached "this page has no table", and it would persist across every
    # future run.
    if data.get("is_soa_page") is not None:
        key.parent.mkdir(parents=True, exist_ok=True)
        key.write_text(json.dumps({"data": ex.data, "raw": ex.raw, "usage": ex.usage},
                                  ensure_ascii=False))
    return ex


def extract_span(pdf_path: str, pages: list[int], **kw) -> list[PageExtraction]:
    return [extract_page(pdf_path, p, span=pages, **kw) for p in pages]
