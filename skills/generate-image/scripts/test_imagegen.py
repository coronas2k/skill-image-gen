"""Offline tests for imagegen.py: python3 -m unittest discover -s scripts"""

import base64
import contextlib
import http.server
import io
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import imagegen as ig  # noqa: E402

# Trimmed copy of OpenRouter's /endpoints listing for flux-3-image-klein (2026-11-26).
FLUX_ENDPOINTS = {
    "id": "black-forest-labs/flux-3-image-klein",
    "endpoints": [{
        "provider_name": "Black Forest Labs",
        "supported_parameters": {
            "resolution": {"type": "enum", "values": ["768", "1K", "1.5K", "2K", "4K"]},
            "aspect_ratio": {"type": "enum", "values": ["21:9", "2:1", "16:9", "3:2", "7:5", "4:3", "5:4", "1:1",
                                                         "4:5", "3:4", "5:7", "2:3", "9:16", "1:2", "9:21", "auto"]},
            "output_format": {"type": "enum", "values": ["jpeg", "png"]},
            "n": {"type": "range", "min": 1, "max": 1},
            "input_references": {"type": "range", "min": 0, "max": 10},
            "seed": {"type": "boolean"},
        },
        "allowed_passthrough_parameters": ["safety_tolerance", "steps"],
        "pricing": [
            {"billable": "output_image", "unit": "image", "cost_usd": 0.014, "variant": "2k"},
            {"billable": "output_image", "unit": "image", "cost_usd": 0.036, "variant": "4k"},
        ],
    }],
}

PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAwS2OUAAAAABJRU5ErkJggg==")


def fake_png(w, h):
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"


def fake_jpeg(w, h):
    return (b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
            + b"\xff\xc0" + struct.pack(">HBHH", 17, 8, h, w) + b"\x03" + b"\x00" * 9 + b"\xff\xd9")


class OpenAISize(unittest.TestCase):
    def test_4k_landscape(self):
        self.assertEqual(ig.openai_size("16:9", "4K"), "3840x2160")

    def test_small_size_is_raised_to_minimum_pixels(self):
        w, h = (int(v) for v in ig.openai_size("16:9", "1K").split("x"))
        self.assertEqual((w % 16, h % 16), (0, 0))
        self.assertGreaterEqual(w * h, ig.OPENAI_MIN_PIXELS)

    def test_auto_and_defaults(self):
        self.assertEqual(ig.openai_size(None, None), "auto")
        self.assertEqual(ig.openai_size("9:16", None), "864x1536")
        self.assertEqual(ig.openai_size(None, "2K"), "2048x2048")

    def test_every_result_passes_the_documented_limits(self):
        for aspect in ["1:1", "16:9", "9:16", "3:2", "2:3", "21:9", "3:1", "1:3"]:
            for res in ig.RESOLUTION_LONG_EDGE:
                size = ig.openai_size(aspect, res)
                ig.check_openai_size(size)  # raises if outside the limits

    def test_ratio_outside_limits(self):
        with self.assertRaises(ig.ImageGenError):
            ig.openai_size("4:1", "2K")

    def test_check_rejects_bad_sizes(self):
        for bad in ["1000x1000", "4096x2304", "800x600", "3840x1024"]:
            with self.assertRaises(ig.ImageGenError, msg=bad):
                ig.check_openai_size(bad)


class OpenAIChecks(unittest.TestCase):
    def test_transparent_needs_png_or_webp(self):
        with self.assertRaises(ig.ImageGenError):
            ig.build_request("openai", "gpt-image-2", "x", fmt="jpeg", background="transparent")
        ig.build_request("openai", "gpt-image-2", "x", fmt="webp", background="transparent")

    def test_svg_rules(self):
        with self.assertRaises(ig.ImageGenError):
            ig.build_request("openai", "gpt-image-2.6-sunburst", "x", fmt="svg", n=2)
        with self.assertRaises(ig.ImageGenError):
            ig.build_request("openai", "gpt-image-2.6-sunburst", "x", fmt="svg",
                             refs=[(PNG_1x1, "image/png", "a.png")])

    def test_gif_fields_need_gif(self):
        with self.assertRaises(ig.ImageGenError):
            ig.build_request("openai", "gpt-image-2.6-sunburst", "x", extra={"frame_count": 4})
        req = ig.build_request("openai", "gpt-image-2.6-sunburst", "x", fmt="gif", extra={"frame_count": 4})
        self.assertEqual(req["endpoint"], "images/generations")

    def test_input_fidelity(self):
        with self.assertRaises(ig.ImageGenError):
            ig.build_request("openai", "gpt-image-2", "x", extra={"input_fidelity": "high"})
        ig.build_request("openai", "gpt-image-1.5", "x", extra={"input_fidelity": "high"})

    def test_refs_and_mask_use_edits(self):
        req = ig.build_request("openai", "gpt-image-2.5-sunburst", "x", refs=[(PNG_1x1, "image/png", "a.png")],
                               mask=(PNG_1x1, "image/png", "m.png"))
        self.assertEqual(req["endpoint"], "images/edits")
        self.assertEqual([f[0] for f in req["multipart"][1]], ["image[]", "mask"])
        with self.assertRaises(ig.ImageGenError):
            ig.build_request("openai", "gpt-image-2", "x", mask=(PNG_1x1, "image/png", "m.png"))

    def test_warnings_for_disputed_settings(self):
        body = {"quality": "max", "size": "3840x2160"}
        warnings = ig.openai_warnings("gpt-image-2.6-sunburst", body)
        self.assertTrue(any("2.5 models only" in w for w in warnings))
        self.assertTrue(any("experimental" in w for w in warnings))
        self.assertTrue(any("Sunburst and Flare" in w for w in ig.openai_warnings("gpt-image-2", {"quality": "xhigh"})))


class OpenRouterChecks(unittest.TestCase):
    def body(self, **kw):
        return ig.build_request("openrouter", "black-forest-labs/flux-3-image-klein", "p", **kw)["json"]

    def test_accepts_supported_request(self):
        self.assertEqual(ig.openrouter_check(self.body(aspect="16:9", resolution="4K"), FLUX_ENDPOINTS), [])
        ok = self.body(extra={"seed": 7, "provider": {"options": {"black-forest-labs": {"steps": 30}}}})
        self.assertEqual(ig.openrouter_check(ok, FLUX_ENDPOINTS), [])

    def test_rejects_unsupported_fields_and_values(self):
        problems = ig.openrouter_check(self.body(resolution="512", background="transparent", n=2), FLUX_ENDPOINTS)
        text = " ".join(problems)
        self.assertIn("resolution=512 not allowed", text)
        self.assertIn("background not supported", text)
        self.assertIn("n=2 not allowed", text)

    def test_rejects_unknown_passthrough_and_too_many_refs(self):
        bad = self.body(extra={"provider": {"options": {"black-forest-labs": {"guidance": 3}}}})
        self.assertIn("guidance", " ".join(ig.openrouter_check(bad, FLUX_ENDPOINTS)))
        refs = [(PNG_1x1, "image/png", f"{i}.png") for i in range(11)]
        self.assertIn("input_references", " ".join(ig.openrouter_check(self.body(refs=refs), FLUX_ENDPOINTS)))

    def test_price_by_resolution(self):
        self.assertEqual(ig.openrouter_price(FLUX_ENDPOINTS, "4K"), "0.036 USD per image")
        token_priced = {"endpoints": [{"pricing": [{"billable": "output_image", "unit": "token", "cost_usd": 3e-05}]}]}
        self.assertEqual(ig.openrouter_price(token_priced, "4K"), "30 USD per million output image tokens")

    def test_refs_become_data_urls_and_are_hidden_when_shown(self):
        req = ig.build_request("openrouter", "m", "p", refs=[(PNG_1x1 * 20, "image/png", "a.png")])
        url = req["json"]["input_references"][0]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/png;base64,"))
        shown = json.dumps(ig.redact_for_display(req))
        self.assertNotIn("base64,iVBOR", shown)
        self.assertNotIn("KEY", shown)

    def test_guardrail_hint(self):
        err = {"error": {"message": "0 endpoints...", "metadata": {"ineligibility_reasons": [
            {"reason": "model-ignored-by-guardrail", "configure_url": "https://openrouter.ai/workspaces/default/guardrails"}]}}}
        msg = ig.describe_error("openrouter", 404, err)
        self.assertIn("guardrail", msg)
        self.assertIn("workspaces/default/guardrails", msg)


class Gemini(unittest.TestCase):
    def test_size_and_aspect_rules(self):
        ig.build_request("gemini", "gemini-nano-banana-2.1", "p", aspect="1:8", resolution="4K")
        for model, aspect, res in [("gemini-nano-banana-2.1", None, "512"),
                                   ("gemini-2.5-flash-image", None, "2K"),
                                   ("gemini-3-pro-image", "1:8", None)]:
            with self.assertRaises(ig.ImageGenError, msg=(model, aspect, res)):
                ig.build_request("gemini", model, "p", aspect=aspect, resolution=res)
        ig.build_request("gemini", "gemini-3.1-flash-image", "p", resolution="512")

    def test_body_shape(self):
        req = ig.build_request("gemini", "gemini-nano-banana-2.1", "p", aspect="16:9", resolution="2K",
                               refs=[(PNG_1x1, "image/png", "a.png")], extra={"thinkingConfig": {"thinkingLevel": "High"}})
        gen = req["json"]["generationConfig"]
        self.assertEqual(gen["imageConfig"], {"aspectRatio": "16:9", "imageSize": "2K"})
        self.assertEqual(gen["thinkingConfig"], {"thinkingLevel": "High"})
        self.assertEqual(req["json"]["contents"][0]["parts"][1]["inlineData"]["mimeType"], "image/png")
        self.assertTrue(req["url"].endswith("/models/gemini-nano-banana-2.1:generateContent"))

    def test_parse_skips_thought_images(self):
        thought = base64.b64encode(b"draft").decode()
        final = base64.b64encode(PNG_1x1).decode()
        data = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": "thinking", "thought": True},
            {"inlineData": {"mimeType": "image/png", "data": thought}, "thought": True},
            {"text": "Here you go"},
            {"inlineData": {"mimeType": "image/png", "data": final}},
        ]}}]}
        self.assertEqual(ig.parse_images("gemini", data), [(PNG_1x1, "image/png")])

    def test_blocked_and_filtered(self):
        with self.assertRaises(ig.ImageGenError):
            ig.parse_images("gemini", {"promptFeedback": {"blockReason": "SAFETY"}})
        with self.assertRaises(ig.ImageGenError):
            ig.parse_images("gemini", {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]})


class Parsing(unittest.TestCase):
    def test_openrouter_b64_and_url(self):
        b64 = {"data": [{"b64_json": base64.b64encode(PNG_1x1).decode(), "media_type": "image/png"}]}
        self.assertEqual(ig.parse_images("openrouter", b64), [(PNG_1x1, "image/png")])
        url = {"data": [{"url": "https://example.invalid/a", "media_type": "image/jpeg"}]}
        got = ig.parse_images("openrouter", url, downloader=lambda u, t: (b"\xff\xd8jpeg", "image/jpeg"))
        self.assertEqual(got, [(b"\xff\xd8jpeg", "image/jpeg")])

    def test_openai_mime_from_format(self):
        data = {"data": [{"b64_json": base64.b64encode(b"GIF89a....").decode()}]}
        self.assertEqual(ig.parse_images("openai", data, fmt="gif")[0][1], "image/gif")

    def test_dimensions(self):
        self.assertEqual(ig.image_dimensions(PNG_1x1), (1, 1))
        self.assertEqual(ig.image_dimensions(fake_png(5456, 3072)), (5456, 3072))
        self.assertEqual(ig.image_dimensions(fake_jpeg(2048, 1152)), (2048, 1152))
        self.assertEqual(ig.image_dimensions(b"GIF89a" + struct.pack("<HH", 320, 200)), (320, 200))
        self.assertIsNone(ig.image_dimensions(b"nope"))

    def test_params(self):
        got = ig.parse_params(["seed=7", "provider.options.bfl.steps=30", "moderation=low"], '{"quality": "high"}')
        self.assertEqual(got, {"quality": "high", "seed": 7, "moderation": "low",
                               "provider": {"options": {"bfl": {"steps": 30}}}})
        with self.assertRaises(ig.ImageGenError):
            ig.parse_params(["novalue"], None)


class ProvidersAndFiles(unittest.TestCase):
    def test_pick_provider(self):
        env = {"SKILL_IMAGE_GEN_OPENROUTER_KEY": "x"}
        self.assertEqual(ig.pick_provider(None, env), "openrouter")
        with self.assertRaises(ig.ImageGenError):
            ig.pick_provider("openai", env)
        with self.assertRaises(ig.ImageGenError):
            ig.pick_provider(None, {**env, "SKILL_IMAGE_GEN_GEMINI_KEY": "y"})
        with self.assertRaises(ig.ImageGenError):
            ig.pick_provider(None, {})

    def test_names_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            self.assertEqual([ig.stem_for("hero", i, 2) for i in (1, 2)], ["hero-1", "hero-2"])
            self.assertEqual(ig.stem_for("hero", 1, 1), "hero")
            (out / "hero.json").write_text("{}")
            with self.assertRaises(ig.ImageGenError):
                ig.check_free(out, "hero", 1)
            ig.check_free(out, "hero", 2)  # hero-1 / hero-2 are free
            with self.assertRaises(ig.ImageGenError):
                ig.check_name("../escape")

    def test_precheck_covers_every_extension(self):
        # Regression: a clash on another extension (cat.jpg) used to be found only after paying.
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "cat.jpg").write_bytes(b"old")
            with self.assertRaises(ig.ImageGenError):
                ig.check_free(Path(d), "cat", 1)

    def test_exclusive_create_and_dangling_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            (out / "a.png").write_bytes(b"old")
            with self.assertRaises(ig.ImageGenError):
                ig._write_new(out / "a.png", b"new")
            self.assertEqual((out / "a.png").read_bytes(), b"old")
            # A dangling symlink counts as taken and is never followed.
            target = out / "outside-target"
            os.symlink(target, out / "b.png")
            with self.assertRaises(ig.ImageGenError):
                ig.check_free(out, "b", 1)
            with self.assertRaises(ig.ImageGenError):
                ig._write_new(out / "b.png", b"x")
            path, renamed = ig.save_image(out, "b", b"img", "png")
            self.assertEqual((path.name, renamed), ("b-v2.png", True))
            self.assertFalse(os.path.lexists(target))


class GenerateCommand(unittest.TestCase):
    def run_main(self, argv, env):
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(out):
            code = ig.main(argv)
        return code, out.getvalue()

    def test_dry_run_uses_default_model_at_4k_and_hides_key(self):
        env = {"SKILL_IMAGE_GEN_OPENROUTER_KEY": "sk-or-SECRET", "HOME": tempfile.gettempdir()}
        with mock.patch.object(ig, "openrouter_endpoints", return_value=FLUX_ENDPOINTS):
            code, out = self.run_main(["generate", "--prompt", "a cat", "--name", "cat", "--aspect", "16:9", "--dry-run"], env)
        self.assertEqual(code, 0)
        shown = json.loads(out)
        self.assertEqual(shown["model"], "black-forest-labs/flux-3-image-klein")
        self.assertEqual(shown["request"]["body"]["resolution"], "4K")
        self.assertEqual(shown["price"], "0.036 USD per image")
        self.assertNotIn("SECRET", out)

    def test_generate_saves_image_and_record(self):
        env = {"SKILL_IMAGE_GEN_OPENROUTER_KEY": "sk-or-SECRET"}
        response = {"data": [{"b64_json": base64.b64encode(fake_png(64, 36)).decode(), "media_type": "image/png"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 10, "cost": 0.036}}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(ig, "openrouter_endpoints", return_value=FLUX_ENDPOINTS), \
                mock.patch.object(ig, "send", return_value=response):
            code, out = self.run_main(["generate", "--prompt", "a cat", "--request", "cat pls", "--name", "cat",
                                       "--out-dir", d], env)
            self.assertEqual(code, 0)
            record = json.loads((Path(d) / "cat.json").read_text())
            self.assertTrue((Path(d) / "cat.png").is_file())
        self.assertEqual(record["request"], "cat pls")
        self.assertEqual(record["size"], "64x36")
        self.assertEqual(record["cost_usd"], 0.036)
        self.assertEqual(record["params"]["resolution"], "4K")
        self.assertNotIn("SECRET", json.dumps(record) + out)

    def test_rejected_option_stops_before_sending(self):
        env = {"SKILL_IMAGE_GEN_OPENROUTER_KEY": "k"}
        err = io.StringIO()
        with mock.patch.object(ig, "openrouter_endpoints", return_value=FLUX_ENDPOINTS), \
                mock.patch.object(ig, "send") as sent, contextlib.redirect_stderr(err):
            code, _ = self.run_main(["generate", "--prompt", "icon", "--name", "icon", "--background", "transparent"], env)
        self.assertEqual(code, 1)
        sent.assert_not_called()
        self.assertIn("background not supported", err.getvalue())

    def run_main_err(self, argv, env):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, out = self.run_main(argv, env)
        return code, out, err.getvalue()

    def test_clash_on_other_extension_stops_before_sending(self):
        env = {"SKILL_IMAGE_GEN_OPENROUTER_KEY": "k"}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(ig, "openrouter_endpoints", return_value=FLUX_ENDPOINTS), \
                mock.patch.object(ig, "send") as sent:
            (Path(d) / "cat.jpg").write_bytes(b"old")
            code, _, err = self.run_main_err(["generate", "--prompt", "p", "--name", "cat", "--out-dir", d,
                                              "--format", "jpeg"], env)
            self.assertEqual((Path(d) / "cat.jpg").read_bytes(), b"old")
        self.assertEqual(code, 1)
        sent.assert_not_called()
        self.assertIn("won't overwrite", err)

    def test_clash_after_paying_saves_under_fallback_name(self):
        env = {"SKILL_IMAGE_GEN_OPENROUTER_KEY": "k"}
        response = {"data": [{"b64_json": base64.b64encode(fake_png(4, 4)).decode(), "media_type": "image/png"}]}
        with tempfile.TemporaryDirectory() as d:
            def send(req, provider, timeout):  # another process takes the name while we wait
                (Path(d) / "cat.png").write_bytes(b"theirs")
                return response
            with mock.patch.object(ig, "openrouter_endpoints", return_value=FLUX_ENDPOINTS), \
                    mock.patch.object(ig, "send", side_effect=send):
                code, out, _ = self.run_main_err(["generate", "--prompt", "p", "--name", "cat", "--out-dir", d], env)
            self.assertEqual(code, 0)
            self.assertEqual((Path(d) / "cat.png").read_bytes(), b"theirs")
            self.assertEqual((Path(d) / "cat-v2.png").read_bytes(), fake_png(4, 4))
            self.assertTrue((Path(d) / "cat-v2.json").is_file())
        self.assertIn("saved as cat-v2.png", " ".join(json.loads(out)["warnings"]))

    def test_gemini_later_failure_keeps_saved_images(self):
        env = {"SKILL_IMAGE_GEN_GEMINI_KEY": "k"}
        ok = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(fake_png(8, 8)).decode()}}]}}]}
        replies = [ok, ok, ig.ImageGenError("gemini returned HTTP 503: overloaded")]

        def send(req, provider, timeout):
            r = replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ig, "send", side_effect=send):
            code, out, err = self.run_main_err(["generate", "--prompt", "p", "--name", "g", "--out-dir", d,
                                                "--n", "3"], env)
            files = sorted(os.listdir(d))
        self.assertEqual(code, 1)
        self.assertEqual(files, ["g-1.json", "g-1.png", "g-2.json", "g-2.png"])
        self.assertEqual(len(json.loads(out)["images"]), 2)
        self.assertIn("503", err)

    def test_dry_run_validates_name_and_out_dir(self):
        env = {"SKILL_IMAGE_GEN_OPENROUTER_KEY": "k"}
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(ig, "openrouter_endpoints", return_value=FLUX_ENDPOINTS):
            code, _, err = self.run_main_err(["generate", "--prompt", "p", "--name", "../x", "--dry-run"], env)
            self.assertEqual(code, 1)
            self.assertIn("--name", err)
            a_file = Path(d) / "file"
            a_file.write_text("")
            code, _, err = self.run_main_err(["generate", "--prompt", "p", "--name", "x", "--out-dir", str(a_file),
                                              "--dry-run"], env)
            self.assertEqual(code, 1)
            self.assertIn("not a directory", err)

    def test_missing_prompt_file_is_a_clear_error(self):
        code, _, err = self.run_main_err(["generate", "--prompt-file", "/nonexistent/prompt.txt", "--name", "x",
                                          "--dry-run"], {"SKILL_IMAGE_GEN_OPENROUTER_KEY": "k"})
        self.assertEqual(code, 1)
        self.assertIn("can't read --prompt-file", err)


class Secrets(unittest.TestCase):
    def test_key_is_stripped_and_bad_key_refused_without_echo(self):
        self.assertEqual(ig.read_key("openrouter", {"SKILL_IMAGE_GEN_OPENROUTER_KEY": " sk-DUMMY\r\n"}), "sk-DUMMY")
        with self.assertRaises(ig.ImageGenError) as cm:
            ig.read_key("openrouter", {"SKILL_IMAGE_GEN_OPENROUTER_KEY": "sk-DUM\nMY"})
        self.assertNotIn("DUM", str(cm.exception))
        self.assertEqual(ig.available_providers({"SKILL_IMAGE_GEN_GEMINI_KEY": "  "}), [])

    def test_unexpected_error_hides_its_text(self):
        err = io.StringIO()
        with mock.patch.object(ig, "cmd_keys", side_effect=ValueError("Invalid header value b'Bearer sk-DUMMY'")), \
                contextlib.redirect_stderr(err):
            code = ig.main(["keys"])
        self.assertEqual(code, 1)
        self.assertIn("ValueError", err.getvalue())
        self.assertNotIn("DUMMY", err.getvalue())


def serve(handler):
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


class Quiet(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass


class Network(unittest.TestCase):
    def test_key_headers_do_not_follow_redirects(self):
        seen = {}

        class Target(Quiet):
            def do_GET(self):
                seen.update(self.headers.items())
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")
        target = serve(Target)

        class Redirect(Quiet):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self.send_response(302)
                self.send_header("Location", f"http://localhost:{target.server_port}/elsewhere")
                self.end_headers()
        redirect = serve(Redirect)
        try:
            status, _, _ = ig._request("POST", f"http://127.0.0.1:{redirect.server_port}/api",
                                       {"Authorization": "Bearer DUMMY", "x-goog-api-key": "DUMMY"}, b"{}", timeout=5)
        finally:
            for srv in (target, redirect):
                srv.shutdown()
                srv.server_close()
        self.assertEqual(status, 200)
        self.assertTrue(seen, "redirect target was not reached")
        self.assertNotIn("DUMMY", json.dumps(seen))

    def test_https_redirect_may_not_downgrade(self):
        req = urllib.request.Request("https://example.invalid/a")
        with self.assertRaises(ig.ImageGenError):
            ig._NoDowngradeRedirects().redirect_request(req, None, 302, "Found", {}, "http://example.invalid/b")

    def test_read_timeout_is_friendly_on_every_python(self):
        # Regression: on Python 3.8/3.9 socket.timeout is not TimeoutError and escaped as a traceback.
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        try:
            with self.assertRaises(ig.ImageGenError) as cm:
                ig._request("GET", f"http://127.0.0.1:{srv.getsockname()[1]}/", timeout=0.5)
        finally:
            srv.close()
        self.assertIn("timed out", str(cm.exception))

    def test_dropped_connection_is_friendly(self):
        class Drop(Quiet):
            def handle_one_request(self):
                self.raw_requestline = self.rfile.readline()
                self.close_connection = True  # close without any reply
        srv = serve(Drop)
        try:
            with self.assertRaises(ig.ImageGenError) as cm:
                ig._request("GET", f"http://127.0.0.1:{srv.server_port}/", timeout=5)
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertIn("network error", str(cm.exception))

    def test_download_refuses_non_https_non_images_and_oversize(self):
        for url in ["http://example.invalid/a.png", "file:///etc/hosts", "data:image/png;base64,AAAA"]:
            with self.assertRaises(ig.ImageGenError, msg=url):
                ig._download(url, 5)
        with mock.patch.object(ig, "_request", return_value=(200, b"<html>hi</html>", "image/png")):
            with self.assertRaises(ig.ImageGenError):
                ig._download("https://example.invalid/a.png", 5)
        with mock.patch.object(ig, "_request", return_value=(200, fake_png(2, 2) + b"\0" * 64, "image/png")), \
                mock.patch.object(ig, "MAX_DOWNLOAD_BYTES", 32):
            with self.assertRaises(ig.ImageGenError):
                ig._download("https://example.invalid/a.png", 5)
        with mock.patch.object(ig, "_request", return_value=(200, fake_png(2, 2), "application/octet-stream")):
            self.assertEqual(ig._download("https://example.invalid/a.png", 5), (fake_png(2, 2), "image/png"))


class BadInput(unittest.TestCase):
    def test_non_string_size(self):
        with self.assertRaises(ig.ImageGenError):
            ig.build_request("openai", "gpt-image-2", "p", extra={"size": 1536})

    def test_provider_field_must_be_object(self):
        for bad in ["x", {"options": "x"}, {"options": {"bfl": "x"}}]:
            with self.assertRaises(ig.ImageGenError, msg=bad):
                ig.build_request("openrouter", "m", "p", extra={"provider": bad})

    def test_gemini_text_only_answer_is_shown(self):
        data = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": "I can't draw that, but here is a description instead."}]}}]}
        with self.assertRaises(ig.ImageGenError) as cm:
            ig.parse_images("gemini", data)
        self.assertIn("I can't draw that", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
