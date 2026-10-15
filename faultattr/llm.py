"""
OpenRouter client. Set OPENROUTER_API_KEY in the environment -- never in code.

Every request pins ONE provider with fallback disabled, so a run is served by
a known endpoint (model weights, quantization and sampling differ across
providers). The pinned provider is checked against the model's endpoint list
at startup; if it does not serve the model, construction fails loudly.

  FA_MODEL     agent model     (default qwen/qwen3-235b-a22b-2507)
  FA_PROVIDER  agent provider  (default alibaba -- Qwen's first-party endpoint)

Mock mode (FA_MOCK=1) runs the whole pipeline without network, using a
deterministic scripted solver. Use it to verify contract evaluation and
verdict logic before spending API calls.
"""
from __future__ import annotations
import json
import os
import random
import threading
import time
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = os.environ.get("FA_MODEL", "qwen/qwen3-235b-a22b-2507")
DEFAULT_PROVIDER = os.environ.get("FA_PROVIDER", "alibaba")


@dataclass
class LLMReply:
    text: str
    ok: bool
    error: Optional[str] = None
    latency: float = 0.0
    retries: int = 0
    # "stop" | "length" | ... as reported by the API. "length" means the
    # reply was cut off at max_tokens: it is neither an agent's answer nor
    # a projection error, and callers should treat it separately.
    finish_reason: Optional[str] = None
    served_by: Optional[str] = None     # provider OpenRouter actually used
    prompt_tokens: int = 0              # for cost accounting
    completion_tokens: int = 0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _backoff(attempt: int, retry_after: Optional[str] = None) -> float:
    """Seconds to wait: the server's Retry-After if given, else jittered
    exponential. Jitter keeps concurrent workers from retrying in lockstep."""
    if retry_after:
        try:
            return min(60.0, float(retry_after))
        except ValueError:
            pass
    return min(60.0, 2.0 ** attempt) * (0.5 + random.random())


# ------------------------------------------------------- provider checking

_verified: Dict[tuple, dict] = {}
_verify_lock = threading.Lock()


def _matches(endpoint: dict, provider: str) -> bool:
    p = provider.lower()
    tag = (endpoint.get("tag") or "").lower()
    return (tag == p or tag.split("/")[0] == p
            or (endpoint.get("provider_name") or "").lower() == p)


def verify_provider(model: str, provider: str) -> dict:
    """
    Print every provider serving `model` with prices, mark the pinned one,
    and return its endpoint record. SystemExit if the pinned provider does
    not serve the model. Checked once per (model, provider) per process.
    """
    with _verify_lock:
        if (model, provider) in _verified:
            return _verified[(model, provider)]
        url = f"https://openrouter.ai/api/v1/models/{model}/endpoints"
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                eps = json.load(r)["data"]["endpoints"]
        except urllib.error.HTTPError as e:
            raise SystemExit(f"model {model!r} not found on OpenRouter "
                             f"(HTTP {e.code})") from None
        print(f"  providers serving {model}:")
        pinned = None
        for e in sorted(eps, key=lambda e: float(e["pricing"]["prompt"])):
            hit = _matches(e, provider)
            pinned = pinned or (e if hit else None)
            p = e["pricing"]
            print(f"    {'->' if hit else '  '} {e['provider_name']:<15} "
                  f"{e.get('tag') or '':<26} "
                  f"in ${float(p['prompt']) * 1e6:.3f}/M  "
                  f"out ${float(p['completion']) * 1e6:.3f}/M  "
                  f"max_out {e.get('max_completion_tokens')}  "
                  f"status {e.get('status')}")
        if pinned is None:
            raise SystemExit(f"pinned provider {provider!r} does not serve "
                             f"{model!r}. Set it to one of the above.")
        if (pinned.get("status") or 0) < 0:
            print(f"  WARNING: pinned endpoint {pinned.get('tag')} reports "
                  f"degraded status {pinned.get('status')}")
        print(f"  pinned: {provider} (allow_fallbacks=false)")
        _verified[(model, provider)] = pinned
        return pinned


class LLM:
    def __init__(self, model: str = DEFAULT_MODEL, temperature: float = 0.7,
                 max_tokens: int = 900, mock: Optional[bool] = None,
                 max_attempts: int = 6, provider: Optional[str] = None,
                 extra_body: Optional[dict] = None):
        self.model = model
        self.provider = provider or DEFAULT_PROVIDER
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_attempts = max_attempts
        self.extra_body = extra_body or {}  # e.g. {"reasoning": {...}}
        self.mock = (os.environ.get("FA_MOCK") == "1") if mock is None else mock
        self.key = os.environ.get("OPENROUTER_API_KEY")
        if not self.mock and not self.key:
            raise RuntimeError(
                "OPENROUTER_API_KEY not set. Export it, or run with FA_MOCK=1."
            )
        if not self.mock:
            verify_provider(self.model, self.provider)
        self.calls = 0
        self.prompt_tokens = 0              # running totals, for cost caps
        self.completion_tokens = 0
        self._lock = threading.Lock()       # chat() is called from threads

    def describe(self) -> Dict[str, str]:
        """What to record in every results file."""
        if self.mock:
            return {"model": "mock", "provider": "mock"}
        return {"model": self.model, "provider": self.provider}

    def chat(self, system: str, user: str,
             temperature: Optional[float] = None) -> LLMReply:
        if self.mock:
            from .mockagents import mock_reply
            return LLMReply(text=mock_reply(system, user), ok=True,
                            finish_reason="stop", served_by="mock")

        body = json.dumps({
            "model": self.model,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "provider": {"order": [self.provider], "allow_fallbacks": False},
            **self.extra_body,
        }).encode()

        last_err = None
        for attempt in range(self.max_attempts):
            t0 = time.time()
            req = urllib.request.Request(
                API_URL, data=body,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {self.key}"})
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    data = json.loads(r.read().decode())
                with self._lock:
                    self.calls += 1
                choice = data["choices"][0]
                use = data.get("usage") or {}
                with self._lock:
                    self.prompt_tokens += use.get("prompt_tokens", 0) or 0
                    self.completion_tokens += (use.get("completion_tokens", 0)
                                               or 0)
                return LLMReply(text=choice["message"]["content"] or "",
                                ok=True, latency=time.time() - t0,
                                retries=attempt,
                                finish_reason=choice.get("finish_reason"),
                                served_by=data.get("provider"),
                                prompt_tokens=use.get("prompt_tokens", 0) or 0,
                                completion_tokens=(use.get("completion_tokens",
                                                           0) or 0))
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}: {e.read()[:200]!r}"
                if e.code in (429, 500, 502, 503, 529):
                    if attempt + 1 < self.max_attempts:
                        time.sleep(_backoff(attempt,
                                            e.headers.get("Retry-After")))
                    continue
                break
            except Exception as e:            # noqa: BLE001
                last_err = repr(e)
                if attempt + 1 < self.max_attempts:
                    time.sleep(_backoff(attempt))

        return LLMReply(text="", ok=False, error=last_err,
                        retries=self.max_attempts)

    def sample(self, system: str, user: str, k: int) -> List[LLMReply]:
        return [self.chat(system, user) for _ in range(k)]
