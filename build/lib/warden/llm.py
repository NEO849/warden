"""
Local-LLM hook (Ollama) — free, no API key, no card. Makes reflection insights REAL synthesis
instead of the deterministic stub. Falls back to the stub if Ollama errors, so the pipeline never breaks.

Env: OLLAMA_URL (default http://localhost:11434/api/generate), OLLAMA_MODEL.
"""
import json
import os
import urllib.request

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mannix/llama3.1-8b-abliterated:q4_k_m")


def ollama_json(prompt: str, system: str, temperature: float = 0.0, timeout: int = 300) -> dict:
    # num_predict caps output tokens → bounds CPU inference time (no GPU on this box, ~36s/short call).
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "system": system, "stream": False,
               "format": "json", "options": {"temperature": temperature, "num_predict": 400}}
    req = urllib.request.Request(OLLAMA_URL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(json.loads(r.read())["response"])


REFLECT_SYSTEM = (
    "You are a data-governance reflection engine over a data-lineage graph. You synthesize INSIGHTS that "
    "live on NO single asset, each grounded in the given per-asset memories. Rules: (1) cite >=2 of the "
    "provided asset URNs VERBATIM in evidence_urns; (2) NEVER invent a URN not in the list; (3) mark "
    "supported=false if the memories indicate an upstream change/drift/contradiction, true if they "
    "corroborate. Output STRICT JSON only."
)


def make_reflection_llm():
    """Return an llm(memories, event) -> insights callable for warden.reflection.reflect."""
    from warden.reflection import _stub_synthesis

    def _llm(memories, event):
        lines = [f'{i+1}. urn={m["urn"]} hops={m["hops"]} confidence={m["confidence"]:.2f} '
                 f'summary={m.get("summary")}' for i, m in enumerate(memories)]
        prompt = (
            f"FIRING EVENT: {event}\n\nPER-ASSET MEMORIES (upstream of one ML model):\n"
            + "\n".join(lines)
            + '\n\nTASK: 1) up to 3 focal questions; 2) up to 3 insights, each '
              '{"statement": str, "evidence_urns": [>=2 urns copied from above], "supported": bool}. '
              'Output JSON: {"focal_questions": [...], "insights": [...]}'
        )
        try:
            data = ollama_json(prompt, REFLECT_SYSTEM)
            insights = data.get("insights") or []
            by_urn = {m["urn"]: m for m in memories}
            cleaned = []
            for ins in insights:
                urns = [u for u in ins.get("evidence_urns", []) if u in by_urn]
                if len(set(urns)) < 2:
                    continue
                supported = bool(ins.get("supported", True))
                ins["cited"] = [{**by_urn[u], "supported": supported} for u in dict.fromkeys(urns)]
                ins["generated_from_events"] = [str(event)] if event else []
                cleaned.append(ins)
            return cleaned or _stub_synthesis(memories, event)  # fallback if LLM gave nothing usable
        except Exception as e:
            print(f"   [llm] Ollama fallback → stub ({type(e).__name__}: {str(e)[:80]})")
            return _stub_synthesis(memories, event)

    return _llm
