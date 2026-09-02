"""OpenAI vision extraction. Same page, same prompt, same output contract.

The third engine exists so the benchmark can say "we ran three and here is
where each broke" rather than "we ran two and read about a third". It shares
SYSTEM and PROMPT with the other engines verbatim, so any difference in the
results is the model and not the instructions.

It also settles two defects the other engines left open, both of which are
per-page model variance rather than pipeline bugs: protocol12's cell values
came back lowercased where the page prints `Xa`, and protocol15's RANDOMIZATION
divider was returned as an explained column while protocol12's identical device
was dropped. A third independent reading tells us whether those are properties
of the page or of the model.
"""

from __future__ import annotations

import hashlib, json, pathlib, random, time

from .config import api_key
from .render import render
from .extract import SYSTEM, PROMPT, PageExtraction, _strip_fence, CACHE

MODEL = "gpt-5"
FALLBACKS = ["gpt-5", "gpt-5-mini", "gpt-4.1"]
RETRIES = 3


def _cache_key(pdf_path: str, page_no: int, model: str) -> pathlib.Path:
    h = hashlib.sha256()
    h.update(pathlib.Path(pdf_path).read_bytes()[:1_000_000])
    h.update(f"|{pathlib.Path(pdf_path).stat().st_size}|{page_no}|{model}|".encode())
    h.update((SYSTEM + PROMPT).encode())
    return CACHE / f"p{page_no}_{h.hexdigest()[:20]}.json"


def extract_page(pdf_path: str, page_no: int, span: list[int] | None = None,
                 client=None, model: str = MODEL, use_cache: bool = True) -> PageExtraction:
    key = _cache_key(pdf_path, page_no, model)
    if use_cache and key.exists():
        c = json.loads(key.read_text())
        return PageExtraction(page=page_no, data=c["data"], raw=c["raw"],
                              usage={**c["usage"], "cached": True})

    from openai import OpenAI

    client = client or OpenAI(api_key=api_key("OPENAI_API_KEY"))
    rp = render(pdf_path, page_no)
    span_note = (f", one of pages {span} that together hold a single "
                 f"Schedule of Activities") if span and len(span) > 1 else ""

    content = [
        {"type": "input_image",
         "image_url": f"data:image/png;base64,{rp.b64}", "detail": "high"},
        {"type": "input_text", "text": PROMPT.format(page=page_no, span_note=span_note)},
    ]

    order = [model] + [m for m in FALLBACKS if m != model]
    resp = used = None
    last: Exception | str | None = None
    for candidate in order:
        for attempt in range(RETRIES):
            try:
                r = client.responses.create(
                    model=candidate,
                    instructions=SYSTEM,
                    input=[{"role": "user", "content": content}],
                    max_output_tokens=32000,
                    text={"format": {"type": "json_object"}},
                )
            except Exception as e:                              # noqa: BLE001
                last = e
                code = getattr(e, "status_code", None)
                if code in (404, 400):
                    break                                       # model not available
                if code not in (429, 500, 502, 503, None):
                    raise
                time.sleep(min(2 ** attempt + random.random(), 20))
                continue

            # Same rule as the other engines: a 200 whose body is empty or will
            # not parse is a failed attempt, not an answer. Accepting one
            # deletes a page of the table without a word.
            body = (getattr(r, "output_text", "") or "").strip()
            if not body:
                last = f"empty response from {candidate}"
                time.sleep(min(2 ** attempt + random.random(), 20))
                continue
            try:
                json.loads(_strip_fence(body))
            except json.JSONDecodeError as e:
                last = f"unparseable response from {candidate} ({len(body)} chars): {e}"
                time.sleep(min(2 ** attempt + random.random(), 20))
                continue
            resp, used = r, candidate
            break
        if resp is not None:
            break
    if resp is None:
        raise RuntimeError(
            f"OpenAI produced no usable response for {pathlib.Path(pdf_path).name} "
            f"p{page_no} after trying {order}. Last error: {last}")

    text = resp.output_text or ""
    try:
        data = json.loads(_strip_fence(text))
    except json.JSONDecodeError as e:
        data = {"is_soa_page": None, "parse_error": str(e)}

    u = getattr(resp, "usage", None)
    data.setdefault("_model", used)
    ex = PageExtraction(page=page_no, data=data, raw=text, usage={
        "input": getattr(u, "input_tokens", 0) or 0,
        "output": getattr(u, "output_tokens", 0) or 0,
        "model": used,
    })
    if data.get("is_soa_page") is not None:
        key.parent.mkdir(parents=True, exist_ok=True)
        key.write_text(json.dumps({"data": ex.data, "raw": ex.raw, "usage": ex.usage},
                                  ensure_ascii=False))
    return ex


def extract_span(pdf_path: str, pages: list[int], **kw) -> list[PageExtraction]:
    return [extract_page(pdf_path, p, span=pages, **kw) for p in pages]
