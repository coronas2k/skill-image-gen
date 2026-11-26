#!/usr/bin/env python3
"""Generate images with OpenRouter, OpenAI or Google Gemini.

Standard library only. API keys are read from the environment and never
printed, logged or written to disk.

    imagegen.py generate --prompt "..." --request "user's words" --name hero [options]
    imagegen.py options  --provider openrouter --model black-forest-labs/flux-3-image-klein
    imagegen.py keys

Run any command with --help for its flags. `generate --dry-run` prints the
exact request that would be sent (without the key) and spends nothing.
"""

from __future__ import annotations

import argparse
import base64
import datetime as _dt
import json
import math
import mimetypes
import os
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# --------------------------------------------------------------------------
# Providers, keys and defaults
# --------------------------------------------------------------------------

KEY_ENV = {
    "openrouter": "SKILL_IMAGE_GEN_OPENROUTER_KEY",
    "openai": "SKILL_IMAGE_GEN_OPENAI_KEY",
    "gemini": "SKILL_IMAGE_GEN_GEMINI_KEY",
}

DEFAULTS = {
    # provider: (model, resolution used when the caller gives none)
    "openrouter": ("black-forest-labs/flux-3-image-klein", "4K"),
    "openai": ("gpt-image-2", None),
    "gemini": ("gemini-nano-banana-2.1", None),
}

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENAI_BASE = "https://api.openai.com/v1"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

RESOLUTION_LONG_EDGE = {"512": 512, "768": 768, "1K": 1024, "1.5K": 1536, "2K": 2048, "4K": 3840}

USER_AGENT = "skill-image-gen/imagegen.py"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "skill-image-gen"
CACHE_TTL_SECONDS = 24 * 3600


class ImageGenError(Exception):
    """An error to show the user as-is (never contains secrets)."""


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def available_providers(env=None) -> list[str]:
    env = os.environ if env is None else env
    return [p for p, var in KEY_ENV.items() if env.get(var)]


def pick_provider(requested: str | None, env=None) -> str:
    have = available_providers(env)
    if requested:
        if requested not in KEY_ENV:
            raise ImageGenError(f"unknown provider {requested!r}; use one of {', '.join(KEY_ENV)}")
        if requested not in have:
            raise ImageGenError(f"{KEY_ENV[requested]} is not set, so {requested} can't be used")
        return requested
    if len(have) == 1:
        return have[0]
    if not have:
        raise ImageGenError("no API key is set; set one of " + ", ".join(KEY_ENV.values()))
    raise ImageGenError("several API keys are set (" + ", ".join(have) + "); pass --provider")


# --------------------------------------------------------------------------
# HTTP (key stays inside this process)
# --------------------------------------------------------------------------

def _request(method, url, headers=None, body: bytes | None = None, timeout=300):
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("User-Agent", USER_AGENT)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "") if e.headers else ""
    except TimeoutError:
        raise ImageGenError(
            f"request timed out after {timeout}s; 4K images can take 1-2 minutes, "
            "retry with a larger --timeout or a smaller --resolution"
        ) from None
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError):
            raise ImageGenError(f"request timed out after {timeout}s; retry with a larger --timeout") from None
        raise ImageGenError(f"network error: {e.reason}") from None


def _json_or_error(status, raw, provider):
    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        data = None
    if 200 <= status < 300 and isinstance(data, dict):
        return data
    raise ImageGenError(describe_error(provider, status, data, raw))


def describe_error(provider, status, data, raw=b"") -> str:
    """Turn a provider error response into one readable message."""
    err = (data or {}).get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        msg = err.get("message") or json.dumps(err)[:500]
    elif isinstance(err, str):
        msg = err
    else:
        msg = (raw or b"").decode("utf-8", "replace")[:500] or "no response body"
    out = f"{provider} returned HTTP {status}: {msg}"
    if provider == "openrouter" and isinstance(err, dict):
        reasons = (err.get("metadata") or {}).get("ineligibility_reasons") or []
        for r in reasons:
            if "guardrail" in str(r.get("reason", "")):
                out += (f"\nhint: a guardrail on the OpenRouter account blocks this model "
                        f"({r.get('reason')}); allow it at {r.get('configure_url', 'https://openrouter.ai/settings')}")
                break
    if status == 400 and provider in ("openai", "openrouter"):
        out += "\nhint: an option may not be supported by this model; run `imagegen.py options` to check"
    return out


# --------------------------------------------------------------------------
# Reference images
# --------------------------------------------------------------------------

def read_ref(path: str) -> tuple[bytes, str]:
    p = Path(path)
    if not p.is_file():
        raise ImageGenError(f"reference image not found: {path}")
    mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    if not mime.startswith("image/"):
        raise ImageGenError(f"reference is not an image: {path} ({mime})")
    return p.read_bytes(), mime


def data_url(raw: bytes, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")


# --------------------------------------------------------------------------
# Option parsing helpers
# --------------------------------------------------------------------------

def parse_params(pairs: list[str] | None, params_json: str | None) -> dict:
    """--param k=v (JSON-decoded when possible, dotted keys nest) and --params-json."""
    out: dict = {}
    if params_json:
        try:
            loaded = json.loads(params_json)
        except json.JSONDecodeError as e:
            raise ImageGenError(f"--params-json is not valid JSON: {e}") from None
        if not isinstance(loaded, dict):
            raise ImageGenError("--params-json must be a JSON object")
        out.update(loaded)
    for pair in pairs or []:
        if "=" not in pair:
            raise ImageGenError(f"--param needs key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = value
        node = out
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise ImageGenError(f"--param {key}: {part} is not an object")
        node[parts[-1]] = parsed
    return out


def parse_aspect(aspect: str) -> tuple[float, float]:
    try:
        a, b = aspect.split(":")
        a, b = float(a), float(b)
    except ValueError:
        raise ImageGenError(f"aspect ratio must look like 16:9, got {aspect!r}") from None
    if a <= 0 or b <= 0:
        raise ImageGenError(f"aspect ratio must be positive, got {aspect!r}")
    return a, b


# --------------------------------------------------------------------------
# OpenAI: size from aspect + resolution, and local checks
# --------------------------------------------------------------------------

OPENAI_MIN_PIXELS = 655_360
OPENAI_MAX_PIXELS = 8_294_400
OPENAI_MAX_EDGE = 3840


def _round16(x: float) -> int:
    return max(16, int(round(x / 16.0)) * 16)


def openai_size(aspect: str | None, resolution: str | None) -> str:
    """Pixel size for OpenAI from an aspect ratio and a resolution tier.

    Neither given -> "auto". Edges are multiples of 16, the ratio is kept
    between 1:3 and 3:1, and the pixel count is kept inside OpenAI's limits.
    """
    if not aspect and not resolution:
        return "auto"
    if resolution and resolution not in RESOLUTION_LONG_EDGE:
        raise ImageGenError(f"resolution must be one of {', '.join(RESOLUTION_LONG_EDGE)}, got {resolution!r}")
    long_edge = RESOLUTION_LONG_EDGE[resolution] if resolution else 1536
    a, b = parse_aspect(aspect) if aspect else (1.0, 1.0)
    ratio = a / b
    if ratio > 3 or ratio < 1 / 3:
        raise ImageGenError(f"OpenAI supports aspect ratios between 1:3 and 3:1, got {aspect}")
    if ratio >= 1:
        w, h = long_edge, long_edge / ratio
    else:
        w, h = long_edge * ratio, long_edge
    w, h = _round16(w), _round16(h)
    if w * h < OPENAI_MIN_PIXELS:
        scale = math.sqrt(OPENAI_MIN_PIXELS / (w * h))
        w, h = int(math.ceil(w * scale / 16)) * 16, int(math.ceil(h * scale / 16)) * 16
    while w * h > OPENAI_MAX_PIXELS or max(w, h) > OPENAI_MAX_EDGE:
        scale = min(math.sqrt(OPENAI_MAX_PIXELS / (w * h)), OPENAI_MAX_EDGE / max(w, h))
        w, h = int(math.floor(w * scale / 16)) * 16, int(math.floor(h * scale / 16)) * 16
    # Rounding to 16 can push an extreme ratio just past 3:1; widen the short edge.
    if w > 3 * h:
        h = int(math.ceil(w / 3 / 16)) * 16
    elif h > 3 * w:
        w = int(math.ceil(h / 3 / 16)) * 16
    return f"{w}x{h}"


def check_openai_size(size: str) -> None:
    if size in ("auto", "1024x1024", "1536x1024", "1024x1536"):
        return
    try:
        w, h = (int(v) for v in size.lower().split("x"))
    except ValueError:
        raise ImageGenError(f"size must be WIDTHxHEIGHT or auto, got {size!r}") from None
    problems = []
    if w % 16 or h % 16:
        problems.append("width and height must be multiples of 16")
    if not (1 / 3 <= w / h <= 3):
        problems.append("aspect ratio must be between 1:3 and 3:1")
    if max(w, h) > OPENAI_MAX_EDGE:
        problems.append(f"no edge may exceed {OPENAI_MAX_EDGE}px")
    if not (OPENAI_MIN_PIXELS <= w * h <= OPENAI_MAX_PIXELS):
        problems.append(f"total pixels must be {OPENAI_MIN_PIXELS:,}-{OPENAI_MAX_PIXELS:,}")
    if problems:
        raise ImageGenError(f"size {size}: " + "; ".join(problems))


def openai_warnings(model: str, body: dict) -> list[str]:
    """Checks where OpenAI's own docs disagree: warn, let the API decide."""
    out = []
    sunburst_flare = "sunburst" in model or "flare" in model
    if body.get("quality") in ("xhigh", "max") and not sunburst_flare:
        out.append(f"quality {body['quality']} is documented only for Sunburst and Flare models")
    if body.get("quality") in ("xhigh", "max") and "2.6" in model:
        out.append("OpenAI's API reference lists xhigh/max for 2.5 models only; the image guide includes 2.6")
    size = body.get("size", "auto")
    if size not in ("auto", "1024x1024", "1536x1024", "1024x1536"):
        w, h = (int(v) for v in size.split("x"))
        if w * h > 2560 * 1440:
            out.append(f"sizes above 2560x1440 are experimental ({size})")
    if "complexity" in body and not sunburst_flare:
        out.append("complexity is documented only for 2.6 Sunburst and Flare")
    return out


def openai_hard_checks(model: str, body: dict, has_refs: bool) -> None:
    fmt = body.get("output_format", "png")
    if body.get("background") == "transparent" and fmt not in ("png", "webp"):
        raise ImageGenError("transparent background needs output_format png or webp")
    if fmt == "svg":
        if body.get("n", 1) != 1:
            raise ImageGenError("SVG output needs n=1")
        if has_refs:
            raise ImageGenError("the edit endpoint can't produce SVG; drop --ref/--mask or choose another format")
        if "output_compression" in body:
            raise ImageGenError("SVG output doesn't support output_compression")
    if ("frame_count" in body or "frame_duration_ms" in body) and fmt != "gif":
        raise ImageGenError("frame_count/frame_duration_ms only apply to output_format gif")
    if fmt == "gif" and "output_compression" in body:
        raise ImageGenError("GIF output doesn't support output_compression")
    if "input_fidelity" in body and (model == "gpt-image-2" or model.startswith("gpt-image-2-")):
        raise ImageGenError("omit input_fidelity for gpt-image-2; the API doesn't allow changing it")
    check_openai_size(body.get("size", "auto"))


# --------------------------------------------------------------------------
# Gemini: built-in limits (no per-model options API)
# --------------------------------------------------------------------------

GEMINI_ASPECTS = {"1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"}
GEMINI_WIDE_ASPECT_MODELS = {"gemini-nano-banana-2.1", "gemini-3.1-flash-image"}
GEMINI_SIZE_MODELS = {"gemini-nano-banana-2.1", "gemini-3.1-flash-image", "gemini-3-pro-image"}
GEMINI_MAX_REFS = 14


def gemini_checks(model: str, aspect: str | None, resolution: str | None, n_refs: int) -> None:
    if aspect:
        allowed = set(GEMINI_ASPECTS)
        if model in GEMINI_WIDE_ASPECT_MODELS:
            allowed |= {"1:4", "4:1", "1:8", "8:1"}
        if aspect not in allowed:
            raise ImageGenError(f"{model} doesn't support aspect ratio {aspect}; use one of {', '.join(sorted(allowed))}")
    if resolution:
        if model not in GEMINI_SIZE_MODELS:
            raise ImageGenError(f"{model} doesn't take an image size; omit --resolution")
        allowed = {"1K", "2K", "4K"} | ({"512"} if model == "gemini-3.1-flash-image" else set())
        if resolution not in allowed:
            raise ImageGenError(f"{model} supports image sizes {', '.join(sorted(allowed))}, got {resolution}")
    if n_refs > GEMINI_MAX_REFS:
        raise ImageGenError(f"Gemini accepts at most {GEMINI_MAX_REFS} reference images, got {n_refs}")


# --------------------------------------------------------------------------
# OpenRouter: live options check from /endpoints (cached for a day)
# --------------------------------------------------------------------------

def openrouter_endpoints(model: str, key: str | None, timeout=60, use_cache=True) -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / ("openrouter-endpoints-" + model.replace("/", "__") + ".json")
    if use_cache and cache.is_file() and time.time() - cache.stat().st_mtime < CACHE_TTL_SECONDS:
        try:
            return json.loads(cache.read_text())
        except json.JSONDecodeError:
            pass
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    status, raw, _ = _request("GET", f"{OPENROUTER_BASE}/images/models/{model}/endpoints", headers, timeout=timeout)
    data = _json_or_error(status, raw, "openrouter")
    if "endpoints" not in data:
        raise ImageGenError(f"openrouter: unexpected /endpoints response for {model}")
    cache.write_text(json.dumps(data))
    return data


def _value_ok(spec: dict, value) -> bool:
    kind = spec.get("type")
    if kind == "enum":
        return str(value) in [str(v) for v in spec.get("values", [])]
    if kind == "range":
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        lo, hi = spec.get("min"), spec.get("max")
        return (lo is None or v >= lo) and (hi is None or v <= hi)
    return True  # boolean / unknown types: let the API decide


ALWAYS_OK = {"model", "prompt", "provider", "response_format"}


def openrouter_check(body: dict, endpoints: dict) -> list[str]:
    """Return problems; empty when at least one endpoint accepts every field."""
    eps = endpoints.get("endpoints") or []
    if not eps:
        return [f"no endpoints listed for {body.get('model')}"]
    best: list[str] | None = None
    for ep in eps:
        supported = ep.get("supported_parameters") or {}
        passthrough = set(ep.get("allowed_passthrough_parameters") or [])
        problems = []
        for field, value in body.items():
            if field in ALWAYS_OK:
                continue
            if field == "input_references":
                spec = supported.get(field)
                if spec is None:
                    problems.append("input_references (reference images) not supported")
                elif not _value_ok(spec, len(value)):
                    problems.append(f"input_references: {len(value)} images, allowed {spec.get('min')}-{spec.get('max')}")
                continue
            spec = supported.get(field)
            if spec is None:
                problems.append(f"{field} not supported")
            elif not _value_ok(spec, value):
                allowed = spec.get("values") or f"{spec.get('min')}-{spec.get('max')}"
                problems.append(f"{field}={value} not allowed; allowed: {allowed}")
        opts = (body.get("provider") or {}).get("options") or {}
        for _slug, keys in opts.items():
            for k in (keys or {}):
                if k not in passthrough:
                    problems.append(f"provider.options key {k} not allowed; allowed: {sorted(passthrough) or 'none'}")
        if not problems:
            return []
        if best is None or len(problems) < len(best):
            best = problems
    return best or []


def openrouter_price(endpoints: dict, resolution: str | None) -> str | None:
    for ep in endpoints.get("endpoints") or []:
        for p in ep.get("pricing") or []:
            if p.get("billable") != "output_image":
                continue
            variant = p.get("variant")
            if p.get("unit") == "image" and (variant is None or (resolution and variant.lower() == resolution.lower())):
                return f"{p['cost_usd']} USD per image"
            if p.get("unit") == "token":
                return f"{p['cost_usd'] * 1_000_000:g} USD per million output image tokens"
    return None


# --------------------------------------------------------------------------
# Request builders (pure: no network) -- easy to test and to dry-run
# --------------------------------------------------------------------------

def build_request(provider, model, prompt, *, aspect=None, resolution=None, n=1, fmt=None,
                  background=None, quality=None, refs=(), mask=None, extra=None, key="KEY"):
    """Return {method, url, headers, json|multipart, endpoint} for one call."""
    extra = dict(extra or {})
    refs = list(refs)
    if provider == "openrouter":
        body = {"model": model, "prompt": prompt}
        if n != 1:
            body["n"] = n
        if resolution:
            body["resolution"] = resolution
        if aspect:
            body["aspect_ratio"] = aspect
        if fmt:
            body["output_format"] = fmt
        if background:
            body["background"] = background
        if quality:
            body["quality"] = quality
        if refs:
            body["input_references"] = [
                {"type": "image_url", "image_url": {"url": data_url(raw, mime)}} for raw, mime, _p in refs
            ]
        if mask:
            raise ImageGenError("--mask is only supported with the openai provider")
        body.update(extra)
        return {"method": "POST", "url": f"{OPENROUTER_BASE}/images", "endpoint": "images",
                "headers": {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, "json": body}

    if provider == "openai":
        body = {"model": model, "prompt": prompt, "n": n, "size": openai_size(aspect, resolution)}
        if quality:
            body["quality"] = quality
        if fmt:
            body["output_format"] = fmt
        if background:
            body["background"] = background
        body.update(extra)
        openai_hard_checks(model, body, bool(refs or mask))
        if refs or mask:
            if not refs:
                raise ImageGenError("--mask needs at least one --ref image to edit")
            fields = [(k, json.dumps(v) if isinstance(v, (dict, list)) else str(v)) for k, v in body.items()]
            files = [("image[]", Path(p).name, mime, raw) for raw, mime, p in refs]
            if mask:
                raw, mime, p = mask
                files.append(("mask", Path(p).name, mime, raw))
            return {"method": "POST", "url": f"{OPENAI_BASE}/images/edits", "endpoint": "images/edits",
                    "headers": {"Authorization": f"Bearer {key}"}, "multipart": (fields, files), "json": body}
        return {"method": "POST", "url": f"{OPENAI_BASE}/images/generations", "endpoint": "images/generations",
                "headers": {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, "json": body}

    if provider == "gemini":
        if mask:
            raise ImageGenError("--mask is only supported with the openai provider")
        gemini_checks(model, aspect, resolution, len(refs))
        parts = [{"text": prompt}] + [
            {"inlineData": {"mimeType": mime, "data": base64.b64encode(raw).decode("ascii")}} for raw, mime, _p in refs
        ]
        gen = {"responseModalities": ["TEXT", "IMAGE"]}
        image_config = {}
        if aspect:
            image_config["aspectRatio"] = aspect
        if resolution:
            image_config["imageSize"] = resolution
        if image_config:
            gen["imageConfig"] = image_config
        body = {"contents": [{"parts": parts}], "generationConfig": gen}
        for k, v in extra.items():  # extra goes into generationConfig unless it is a top-level field
            (body if k in ("safetySettings", "tools", "systemInstruction") else gen)[k] = v
        return {"method": "POST", "url": f"{GEMINI_BASE}/models/{model}:generateContent", "endpoint": "generateContent",
                "headers": {"x-goog-api-key": key, "Content-Type": "application/json"}, "json": body}

    raise ImageGenError(f"unknown provider {provider}")


def redact_for_display(req: dict) -> dict:
    """Request as shown by --dry-run and stored in the record: no key, no image bytes."""
    def scrub(obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if k == "data" and isinstance(v, str) and len(v) > 200:
                    out[k] = f"<base64, {len(v)} chars>"
                elif k == "url" and isinstance(v, str) and v.startswith("data:"):
                    out[k] = f"<data URL, {len(v)} chars>"
                else:
                    out[k] = scrub(v)
            return out
        if isinstance(obj, list):
            return [scrub(v) for v in obj]
        return obj

    shown = {"method": req["method"], "url": req["url"], "body": scrub(req.get("json"))}
    if "multipart" in req:
        shown["files"] = [{"field": f, "filename": name, "type": mime, "bytes": len(raw)}
                          for f, name, mime, raw in req["multipart"][1]]
    return shown


def _multipart(fields, files):
    boundary = "----imagegen" + uuid.uuid4().hex
    out = bytearray()
    for name, value in fields:
        out += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
    for field, filename, mime, raw in files:
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {mime}\r\n\r\n").encode() + raw + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def send(req: dict, provider: str, timeout: int) -> dict:
    headers = dict(req["headers"])
    if "multipart" in req:
        body, ctype = _multipart(*req["multipart"])
        headers["Content-Type"] = ctype
    else:
        body = json.dumps(req["json"]).encode("utf-8")
    status, raw, _ = _request(req["method"], req["url"], headers, body, timeout=timeout)
    return _json_or_error(status, raw, provider)


# --------------------------------------------------------------------------
# Response parsing -> list of (bytes, mime)
# --------------------------------------------------------------------------

def _download(url, timeout):
    status, raw, ctype = _request("GET", url, timeout=timeout)
    if not 200 <= status < 300:
        raise ImageGenError(f"downloading the generated image failed with HTTP {status}")
    return raw, ctype.split(";")[0] or None


def parse_images(provider: str, data: dict, *, fmt=None, timeout=300, downloader=_download) -> list[tuple[bytes, str]]:
    images: list[tuple[bytes, str]] = []
    if provider in ("openrouter", "openai"):
        default_mime = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp",
                        "gif": "image/gif", "svg": "image/svg+xml"}.get(fmt or "png", "image/png")
        for item in data.get("data") or []:
            mime = item.get("media_type") or (default_mime if provider == "openai" else None)
            if item.get("b64_json"):
                raw = base64.b64decode(item["b64_json"])
            elif item.get("url"):
                raw, ctype = downloader(item["url"], timeout)
                mime = mime or ctype
            else:
                continue
            images.append((raw, mime or sniff_mime(raw) or "image/png"))
        return images

    if provider == "gemini":
        feedback = data.get("promptFeedback") or {}
        if feedback.get("blockReason"):
            raise ImageGenError(f"gemini blocked the prompt: {feedback['blockReason']}")
        for cand in data.get("candidates") or []:
            finish = cand.get("finishReason")
            for part in (cand.get("content") or {}).get("parts") or []:
                if part.get("thought"):
                    continue  # interim "thought" images are not the result
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    images.append((base64.b64decode(inline["data"]),
                                   inline.get("mimeType") or inline.get("mime_type") or "image/png"))
            if not images and finish and finish not in ("STOP", "MAX_TOKENS"):
                raise ImageGenError(f"gemini returned no image (finishReason {finish})")
        return images

    raise ImageGenError(f"unknown provider {provider}")


def sniff_mime(raw: bytes) -> str | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw.lstrip()[:5] in (b"<?xml", b"<svg ") or raw.lstrip()[:4] == b"<svg":
        return "image/svg+xml"
    return None


EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif", "image/svg+xml": "svg"}


def image_dimensions(raw: bytes) -> tuple[int, int] | None:
    """Width and height for PNG, JPEG, GIF and WebP; None if unknown."""
    try:
        if raw.startswith(b"\x89PNG\r\n\x1a\n"):
            return struct.unpack(">II", raw[16:24])
        if raw[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", raw[6:10])
        if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            chunk = raw[12:16]
            if chunk == b"VP8X":
                w = int.from_bytes(raw[24:27], "little") + 1
                h = int.from_bytes(raw[27:30], "little") + 1
                return w, h
            if chunk == b"VP8 ":
                w, h = struct.unpack("<HH", raw[26:30])
                return w & 0x3FFF, h & 0x3FFF
            if chunk == b"VP8L":
                bits = int.from_bytes(raw[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if raw.startswith(b"\xff\xd8"):
            i = 2
            while i + 9 < len(raw):
                if raw[i] != 0xFF:
                    i += 1
                    continue
                marker = raw[i + 1]
                if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                length = struct.unpack(">H", raw[i + 2:i + 4])[0]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", raw[i + 5:i + 9])
                    return w, h
                i += 2 + length
    except struct.error:
        return None
    return None


# --------------------------------------------------------------------------
# Saving
# --------------------------------------------------------------------------

def output_paths(out_dir: Path, name: str, count: int, exts: list[str]) -> list[Path]:
    if not name or "/" in name or name.startswith("."):
        raise ImageGenError(f"--name must be a plain file name without extension, got {name!r}")
    names = [name] if count == 1 else [f"{name}-{i}" for i in range(1, count + 1)]
    return [out_dir / f"{n}.{ext}" for n, ext in zip(names, exts)]


def check_free(paths: list[Path]) -> None:
    taken = [p if p.exists() else p.with_suffix(".json") for p in paths
             if p.exists() or p.with_suffix(".json").exists()]
    if taken:
        raise ImageGenError("won't overwrite existing files: " + ", ".join(str(p) for p in taken)
                            + "; choose a new --name (for example add -v2)")


def usage_and_cost(provider: str, data: dict) -> tuple[dict | None, float | None]:
    if provider in ("openrouter", "openai"):
        usage = data.get("usage")
        cost = usage.get("cost") if isinstance(usage, dict) else None
        return usage, cost
    return data.get("usageMetadata"), None


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_generate(args) -> int:
    provider = pick_provider(args.provider)
    model = args.model or DEFAULTS[provider][0]
    resolution = args.resolution
    default_model, default_resolution = DEFAULTS[provider]
    if resolution is None and model == default_model and default_resolution:
        resolution = default_resolution
    prompt = args.prompt
    if args.prompt_file:
        prompt = Path(args.prompt_file).read_text().strip()
    if not prompt:
        raise ImageGenError("a prompt is required (--prompt or --prompt-file)")
    if args.n < 1:
        raise ImageGenError("--n must be at least 1")

    refs = [(*read_ref(p), p) for p in args.ref or []]
    mask = (*read_ref(args.mask), args.mask) if args.mask else None
    extra = parse_params(args.param, args.params_json)
    key = os.environ.get(KEY_ENV[provider], "")

    calls = 1
    n_per_call = args.n
    if provider == "gemini" and args.n > 1:
        calls, n_per_call = args.n, 1  # one image per Gemini request
    req = build_request(provider, model, prompt, aspect=args.aspect, resolution=resolution, n=n_per_call,
                        fmt=args.format, background=args.background, quality=args.quality,
                        refs=refs, mask=mask, extra=extra, key=key)

    warnings = []
    price = None
    if provider == "openrouter" and not args.no_check:
        endpoints = openrouter_endpoints(model, key, use_cache=not args.refresh)
        problems = openrouter_check(req["json"], endpoints)
        if problems:
            raise ImageGenError(f"{model} won't accept this request:\n  - " + "\n  - ".join(problems)
                                + "\n(run `imagegen.py options --provider openrouter --model "
                                + model + "` to see what it accepts, or pass --no-check)")
        price = openrouter_price(endpoints, resolution)
    if provider == "openai":
        warnings = openai_warnings(model, req["json"])
    for w in warnings:
        warn(w)

    if args.dry_run:
        print(json.dumps({"dry_run": True, "provider": provider, "model": model, "calls": calls,
                          "price": price, "warnings": warnings, "request": redact_for_display(req)}, indent=2))
        return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Reserve names up front with a provisional extension so nothing is overwritten.
    check_free(output_paths(out_dir, args.name, args.n, ["png"] * args.n))

    started = time.time()
    images, usages, costs = [], [], []
    for _ in range(calls):
        data = send(req, provider, args.timeout)
        got = parse_images(provider, data, fmt=args.format, timeout=args.timeout)
        if not got:
            raise ImageGenError(f"{provider} returned no image")
        images.extend(got)
        usage, cost = usage_and_cost(provider, data)
        usages.append(usage)
        if cost is not None:
            costs.append(cost)
    elapsed = round(time.time() - started, 1)

    paths = output_paths(out_dir, args.name, len(images), [EXT.get(m, "png") for _, m in images])
    check_free(paths)
    shown = redact_for_display(req)
    created = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    results = []
    for (raw, mime), path in zip(images, paths):
        path.write_bytes(raw)
        dims = image_dimensions(raw)
        record = {
            "request": args.request or prompt,
            "prompt": prompt,
            "provider": provider,
            "model": model,
            "endpoint": req["endpoint"],
            "params": {k: v for k, v in (shown["body"] or {}).items() if k not in ("prompt", "model", "contents")},
            "references": [p for _r, _m, p in refs] + ([args.mask] if args.mask else []),
            "size": f"{dims[0]}x{dims[1]}" if dims else None,
            "media_type": mime,
            "created": created,
        }
        if provider == "gemini":
            record["params"] = {"generationConfig": shown["body"].get("generationConfig")}
        if costs:
            record["cost_usd"] = round(sum(costs) / len(images), 6)
        if any(usages):
            record["usage"] = usages[0] if len(usages) == 1 else usages
        path.with_suffix(".json").write_text(json.dumps(record, indent=2) + "\n")
        results.append({"image": str(path), "record": str(path.with_suffix(".json")),
                        "size": record["size"], "bytes": len(raw), "media_type": mime})

    print(json.dumps({"provider": provider, "model": model, "seconds": elapsed,
                      "cost_usd": round(sum(costs), 6) if costs else None,
                      "warnings": warnings, "images": results}, indent=2))
    return 0


def cmd_options(args) -> int:
    provider = args.provider or pick_provider(None)
    model = args.model or DEFAULTS[provider][0]
    if provider == "openrouter":
        key = os.environ.get(KEY_ENV["openrouter"], "")
        data = openrouter_endpoints(model, key, use_cache=not args.refresh)
        out = {"provider": provider, "model": model, "source": "live /endpoints listing", "endpoints": []}
        for ep in data.get("endpoints") or []:
            params = {}
            for name, spec in (ep.get("supported_parameters") or {}).items():
                if spec.get("type") == "enum":
                    params[name] = spec.get("values")
                elif spec.get("type") == "range":
                    params[name] = f"{spec.get('min')}-{spec.get('max')}"
                else:
                    params[name] = spec.get("type")
            out["endpoints"].append({"provider": ep.get("provider_name"), "parameters": params,
                                     "passthrough": ep.get("allowed_passthrough_parameters"),
                                     "pricing": ep.get("pricing")})
        print(json.dumps(out, indent=2))
        return 0
    if provider == "openai":
        print(json.dumps({
            "provider": "openai", "model": model, "source": "built-in notes from OpenAI's image guide (no options API)",
            "size": "auto, 1024x1024, 1536x1024, 1024x1536, or WIDTHxHEIGHT: multiples of 16, ratio 1:3-3:1, "
                    "edge <= 3840, 655,360-8,294,400 pixels (above 2560x1440 experimental)",
            "quality": "low, medium, high, auto; xhigh and max on Sunburst/Flare (docs disagree on 2.6)",
            "output_format": "png (default), jpeg, webp, gif (frame_count 2-16, frame_duration_ms 20-2000), "
                             "svg (n=1, generations only)",
            "background": "auto, opaque, transparent (png/webp only)",
            "complexity": "low, medium, high (default high) on 2.6 Sunburst/Flare",
            "other": "n, output_compression (jpeg/webp), moderation (auto/low), safety_identifier; "
                     "--ref uses /images/edits; --mask needs an alpha channel and applies to the first --ref",
            "pricing": "30 USD per million output image tokens; text input 5 USD, image input 8 USD per million",
        }, indent=2))
        return 0
    allowed_aspects = sorted(GEMINI_ASPECTS | ({"1:4", "4:1", "1:8", "8:1"} if model in GEMINI_WIDE_ASPECT_MODELS else set()))
    print(json.dumps({
        "provider": "gemini", "model": model, "source": "built-in notes from Google's docs (no options API)",
        "aspect_ratio": allowed_aspects,
        "image_size": (["1K", "2K", "4K"] + (["512"] if model == "gemini-3.1-flash-image" else []))
        if model in GEMINI_SIZE_MODELS else "not supported",
        "reference_images": f"up to {GEMINI_MAX_REFS}",
        "images_per_request": "1 (the script makes one call per image)",
        "notes": "thinking is always on; interim thought images are skipped; outputs carry a SynthID watermark",
        "pricing": "nano-banana-2.1: 30 USD per million image tokens (1K 1,120 / 2K 1,680 / 4K 3,780 tokens)",
    }, indent=2))
    return 0


def cmd_keys(_args) -> int:
    print(json.dumps({p: bool(os.environ.get(v)) for p, v in KEY_ENV.items()}, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="generate and save images")
    g.add_argument("--prompt", help="the exact prompt to send")
    g.add_argument("--prompt-file", help="read the prompt from a file")
    g.add_argument("--request", help="what the user asked for, in their words (stored in the record)")
    g.add_argument("--provider", choices=list(KEY_ENV), help="default: the only provider with a key set")
    g.add_argument("--model", help="default: " + ", ".join(f"{p} {m}" for p, (m, _r) in DEFAULTS.items()))
    g.add_argument("--aspect", help="aspect ratio such as 16:9")
    g.add_argument("--resolution", choices=list(RESOLUTION_LONG_EDGE),
                   help="size tier; the OpenRouter default model uses 4K unless set")
    g.add_argument("--n", type=int, default=1, help="number of images")
    g.add_argument("--format", choices=["png", "jpeg", "webp", "gif", "svg"], help="output format if the model supports it")
    g.add_argument("--background", choices=["auto", "opaque", "transparent"])
    g.add_argument("--quality", help="quality setting if the model supports it (e.g. OpenAI low/medium/high/xhigh/max)")
    g.add_argument("--ref", action="append", help="reference image (repeatable)")
    g.add_argument("--mask", help="OpenAI only: mask PNG with alpha for the first --ref")
    g.add_argument("--param", action="append", help="extra request field key=value (repeatable; dotted keys nest)")
    g.add_argument("--params-json", help="extra request fields as a JSON object")
    g.add_argument("--out-dir", default="images", help="directory for images and records (default: images)")
    g.add_argument("--name", required=True, help="file name without extension; several images get -1, -2")
    g.add_argument("--timeout", type=int, default=300, help="seconds to wait per request (default 300)")
    g.add_argument("--dry-run", action="store_true", help="print the request without sending it")
    g.add_argument("--no-check", action="store_true", help="skip the OpenRouter options check")
    g.add_argument("--refresh", action="store_true", help="ignore the cached OpenRouter options")
    g.set_defaults(func=cmd_generate)

    o = sub.add_parser("options", help="show what a model accepts")
    o.add_argument("--provider", choices=list(KEY_ENV))
    o.add_argument("--model")
    o.add_argument("--refresh", action="store_true", help="ignore the cached OpenRouter options")
    o.set_defaults(func=cmd_options)

    k = sub.add_parser("keys", help="show which provider keys are set (never their values)")
    k.set_defaults(func=cmd_keys)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except ImageGenError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
