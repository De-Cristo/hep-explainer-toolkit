"""Local, dependency-free human review UI for scientific claim interpretation.

The server is intentionally conservative:
- loopback binding by default;
- private registries may never bind to a non-loopback address;
- no external scripts, styles, fonts, or network requests;
- no-store response headers and a restrictive CSP;
- CSRF token on every mutating request;
- review files are reloaded and atomically written for each decision.
"""

from __future__ import annotations

import argparse
import html
import ipaddress
import secrets
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from checks.claims import ClaimRegistry, ClaimRegistryError, load_registry
from checks.review import (
    ReviewError,
    decide,
    load_reviews,
    make_review_file,
    review_status,
    save_reviews,
)
from checks.yamlsubset import YamlError, load as load_yaml


class ReviewUIError(ValueError):
    """The local reviewer UI cannot safely start or apply a decision."""


def ensure_reviews(
    registry: ClaimRegistry,
    reviews_path: Path,
) -> dict[str, object]:
    reviews_path = Path(reviews_path)
    if reviews_path.exists():
        return load_reviews(reviews_path)
    reviews = make_review_file(registry)
    save_reviews(reviews_path, reviews)
    return reviews


def review_model(
    registry_path: Path,
    reviews_path: Path,
    scene_paths: tuple[Path, ...] = (),
) -> dict[str, object]:
    registry = load_registry(registry_path)
    reviews = ensure_reviews(registry, reviews_path)
    statuses = review_status(registry, reviews)
    audience = _audience_wording(scene_paths)
    raw_reviews = reviews.get("claims") or {}
    assert isinstance(raw_reviews, dict)

    claims: list[dict[str, object]] = []
    for claim_id, claim in registry.claims.items():
        excerpt = load_yaml(claim.excerpt.read_text(encoding="utf-8"))
        quote = ""
        if isinstance(excerpt, dict):
            quote = str(excerpt.get("quote") or "")
        entry = raw_reviews.get(claim_id)
        if not isinstance(entry, dict):
            entry = {}
        claims.append({
            "id": claim.id,
            "kind": claim.kind,
            "origin": claim.origin,
            "status": statuses[claim.id],
            "statement": claim.statement,
            "citation": _citation_text(claim.citation),
            "quote": quote,
            "context": dict(claim.context),
            "effective_assumptions": list(
                registry.effective_assumptions(claim.id)
            ),
            "caveats": list(claim.caveats),
            "depends_on": list(claim.depends_on),
            "audience_wording": audience.get(claim.id, []),
            "reviewer": str(entry.get("reviewer") or ""),
            "reviewed_at": str(entry.get("reviewed_at") or ""),
            "note": str(entry.get("note") or ""),
        })

    comparisons = [
        {
            "id": item.id,
            "left": item.left,
            "right": item.right,
            "same_when": list(item.same_when),
            "differs_when": list(item.differs_when),
        }
        for item in registry.comparisons
    ]
    counts: dict[str, int] = {}
    for status in statuses.values():
        counts[status] = counts.get(status, 0) + 1
    return {
        "registry": str(registry.path),
        "visibility": registry.visibility,
        "reviews": str(Path(reviews_path).resolve()),
        "claims": claims,
        "comparisons": comparisons,
        "counts": counts,
    }


def apply_decision(
    registry_path: Path,
    reviews_path: Path,
    *,
    claim_id: str,
    decision: str,
    reviewer: str,
    note: str,
) -> str:
    registry = load_registry(registry_path)
    reviews = ensure_reviews(registry, reviews_path)
    decide(
        registry,
        reviews,
        claim_id,
        reviewer,
        note,
        decision,
    )
    save_reviews(reviews_path, reviews)
    return review_status(registry, reviews)[claim_id]


def render_html(
    model: dict[str, object],
    csrf_token: str,
    *,
    default_reviewer: str = "",
    message: str = "",
) -> str:
    visibility = str(model["visibility"])
    claims = model["claims"]
    assert isinstance(claims, list)
    comparisons = model["comparisons"]
    assert isinstance(comparisons, list)
    counts = model["counts"]
    assert isinstance(counts, dict)

    summary = " · ".join(
        f"{html.escape(str(key))}: {value}"
        for key, value in sorted(counts.items())
    ) or "no claims"

    cards = []
    for raw in claims:
        assert isinstance(raw, dict)
        claim_id = str(raw["id"])
        status = str(raw["status"])
        reviewer = str(raw.get("reviewer") or default_reviewer)
        note = str(raw.get("note") or "")
        wordings = raw.get("audience_wording") or []
        assumptions = raw.get("effective_assumptions") or []
        caveats = raw.get("caveats") or []
        dependencies = raw.get("depends_on") or []
        context = raw.get("context") or {}

        wording_html = _list_html(
            [
                f"{item['scene']}: {item['text']}"
                for item in wordings
                if isinstance(item, dict)
            ],
            empty="No audience-specific wording linked from the selected scene files.",
        )
        assumption_html = _list_html(
            [str(item) for item in assumptions],
            empty="No explicit or inherited assumptions.",
        )
        caveat_html = _list_html(
            [str(item) for item in caveats],
            empty="No registered caveats.",
        )
        dependency_html = _list_html(
            [str(item) for item in dependencies],
            empty="No upstream claim dependencies.",
        )
        context_html = _list_html(
            [f"{key} = {value}" for key, value in context.items()],
            empty="No structured context.",
        )
        cards.append(
            f"""
<section class="claim" id="{html.escape(claim_id)}">
  <header>
    <div>
      <h2>{html.escape(claim_id)}</h2>
      <p class="meta">{html.escape(str(raw['kind']))} · {html.escape(str(raw['origin']))}</p>
    </div>
    <span class="status status-{html.escape(status)}">{html.escape(status)}</span>
  </header>

  <h3>Canonical scientific statement</h3>
  <p class="canonical">{html.escape(str(raw['statement']))}</p>

  <h3>Evidence</h3>
  <p><b>Citation:</b> {html.escape(str(raw['citation']))}</p>
  <blockquote>{html.escape(str(raw['quote']))}</blockquote>

  <details open>
    <summary>Assumptions, caveats, dependencies, and context</summary>
    <div class="cols">
      <div><h4>Effective assumptions</h4>{assumption_html}</div>
      <div><h4>Caveats</h4>{caveat_html}</div>
      <div><h4>Dependencies</h4>{dependency_html}</div>
      <div><h4>Context</h4>{context_html}</div>
    </div>
  </details>

  <details open>
    <summary>Audience wording</summary>
    {wording_html}
  </details>

  <form method="post" action="/decision">
    <input type="hidden" name="csrf" value="{html.escape(csrf_token)}">
    <input type="hidden" name="claim_id" value="{html.escape(claim_id)}">
    <label>Reviewer
      <input name="reviewer" required value="{html.escape(reviewer)}">
    </label>
    <label>Review note
      <textarea name="note" rows="3">{html.escape(note)}</textarea>
    </label>
    <div class="actions">
      <button class="approve" type="submit" name="decision" value="approved">Approve interpretation</button>
      <button class="reject" type="submit" name="decision" value="rejected">Reject / revise</button>
    </div>
  </form>
  <p class="previous">Last reviewer: {html.escape(str(raw.get('reviewer') or '—'))}
  · {html.escape(str(raw.get('reviewed_at') or 'not reviewed'))}</p>
</section>
"""
        )

    comparison_html = []
    for item in comparisons:
        assert isinstance(item, dict)
        comparison_html.append(
            f"""
<section class="comparison">
  <h2>{html.escape(str(item['id']))}</h2>
  <p><b>Left:</b> {html.escape(str(item['left']))}</p>
  <p><b>Right:</b> {html.escape(str(item['right']))}</p>
  <p><b>Same when supported by:</b> {html.escape(', '.join(str(x) for x in item['same_when']))}</p>
  <p><b>Differ when supported by:</b> {html.escape(', '.join(str(x) for x in item['differs_when']))}</p>
</section>
"""
        )

    private_warning = ""
    if visibility == "private":
        private_warning = (
            "<p class='private-warning'><b>Private evidence:</b> this page is "
            "served only on loopback. Do not proxy or screen-share it without "
            "checking the material first.</p>"
        )
    flash = (
        f"<p class='flash'>{html.escape(message)}</p>"
        if message
        else ""
    )

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>HEP scientific review</title>
<style>
:root {{ color-scheme: light dark; }}
body {{ font-family: system-ui,sans-serif; max-width: 1180px; margin: 28px auto; padding: 0 20px 60px; line-height: 1.5; }}
header.page {{ position: sticky; top: 0; z-index: 2; padding: 12px 0; backdrop-filter: blur(10px); }}
.claim,.comparison {{ border: 1px solid #8886; border-radius: 12px; padding: 18px 20px; margin: 18px 0; }}
.claim > header {{ display:flex; justify-content:space-between; gap:16px; align-items:flex-start; }}
h1,h2,h3,h4 {{ line-height:1.2; }}
.meta,.previous {{ opacity:.72; }}
.status {{ border:1px solid currentColor; border-radius:999px; padding:4px 9px; font-weight:700; white-space:nowrap; }}
.status-approved,.status-embedded_reviewed {{ color:#187238; }}
.status-rejected,.status-stale,.status-invalid {{ color:#a22; }}
.status-pending,.status-missing {{ color:#9a6500; }}
.canonical {{ font-size:1.08rem; font-weight:650; }}
blockquote {{ border-left:4px solid #8888; margin-left:0; padding:10px 16px; background:#8881; white-space:pre-wrap; }}
.cols {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:12px; }}
form {{ border-top:1px solid #8885; margin-top:16px; padding-top:16px; }}
label {{ display:block; font-weight:650; margin:10px 0; }}
input,textarea {{ display:block; width:100%; box-sizing:border-box; font:inherit; padding:8px; margin-top:4px; }}
.actions {{ display:flex; gap:10px; flex-wrap:wrap; }}
button {{ padding:9px 14px; font:inherit; font-weight:750; cursor:pointer; }}
.approve {{ border:1px solid #187238; }}
.reject {{ border:1px solid #a22; }}
.private-warning {{ border:1px solid #a66; padding:10px 12px; border-radius:8px; }}
.flash {{ border:1px solid #478; padding:10px 12px; border-radius:8px; }}
ul {{ padding-left:22px; }}
</style>
</head>
<body>
<header class="page">
  <h1>HEP scientific interpretation review</h1>
  <p><b>Registry:</b> {html.escape(str(model['registry']))}<br>
  <b>Visibility:</b> {html.escape(visibility)}<br>
  <b>Status:</b> {summary}</p>
  {private_warning}
  {flash}
</header>

<h1>Claims</h1>
{''.join(cards)}

<h1>Definition comparisons</h1>
{''.join(comparison_html) or '<p>No registered comparisons.</p>'}
</body>
</html>
"""


def host_allowed(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_bind(
    host: str,
    *,
    visibility: str,
    unsafe_remote: bool,
) -> None:
    loopback = host_allowed(host)
    if visibility == "private" and not loopback:
        raise ReviewUIError(
            "private registries may only be served on loopback"
        )
    if not loopback and not unsafe_remote:
        raise ReviewUIError(
            "non-loopback bind refused; pass --unsafe-remote only for public registries"
        )


def _audience_wording(
    scene_paths: tuple[Path, ...],
) -> dict[str, list[dict[str, str]]]:
    found: dict[str, list[dict[str, str]]] = {}
    for raw_path in scene_paths:
        path = Path(raw_path).resolve()
        try:
            document = load_yaml(path.read_text(encoding="utf-8"))
        except (OSError, YamlError) as exc:
            raise ReviewUIError(f"cannot read scene {path}: {exc}") from exc
        if not isinstance(document, dict):
            raise ReviewUIError(f"{path}: scene file must be a mapping")
        for scene in document.get("scenes") or []:
            if not isinstance(scene, dict):
                continue
            scene_id = str(scene.get("id") or "?")
            for item in scene.get("claims") or []:
                if not isinstance(item, dict):
                    continue
                ref = str(item.get("claim_ref") or "").strip()
                text = str(item.get("text") or item.get("tex") or "").strip()
                if not ref or not text:
                    continue
                found.setdefault(ref, []).append({
                    "scene": scene_id,
                    "text": text,
                })
    return found


def _citation_text(citation: dict[str, object]) -> str:
    parts = []
    if citation.get("arxiv"):
        parts.append("arXiv:" + str(citation["arxiv"]))
    if citation.get("doi"):
        parts.append("doi:" + str(citation["doi"]))
    if citation.get("local"):
        parts.append("local:" + str(citation["local"]))
    parts.append(str(citation.get("locator") or ""))
    return ", ".join(parts)


def _list_html(items: list[str], *, empty: str) -> str:
    if not items:
        return f"<p>{html.escape(empty)}</p>"
    return "<ul>" + "".join(
        f"<li>{html.escape(item)}</li>" for item in items
    ) + "</ul>"


def _handler_factory(
    registry_path: Path,
    reviews_path: Path,
    scene_paths: tuple[Path, ...],
    csrf_token: str,
    default_reviewer: str,
):
    class Handler(BaseHTTPRequestHandler):
        server_version = "HEPReview/0.4"

        def _headers(
            self,
            status: HTTPStatus,
            content_type: str = "text/html; charset=utf-8",
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; "
                "form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
            )
            self.end_headers()

        def do_GET(self) -> None:
            if self.path not in {"/", ""} and not self.path.startswith("/#"):
                self._headers(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")
                self.wfile.write(b"not found\n")
                return
            try:
                model = review_model(
                    registry_path,
                    reviews_path,
                    scene_paths,
                )
                body = render_html(
                    model,
                    csrf_token,
                    default_reviewer=default_reviewer,
                ).encode("utf-8")
            except Exception as exc:
                self._headers(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "text/plain; charset=utf-8",
                )
                self.wfile.write(("review UI error: " + str(exc) + "\n").encode("utf-8"))
                return
            self._headers(HTTPStatus.OK)
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path != "/decision":
                self._headers(HTTPStatus.NOT_FOUND, "text/plain; charset=utf-8")
                self.wfile.write(b"not found\n")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0 or length > 65536:
                self._headers(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    "text/plain; charset=utf-8",
                )
                self.wfile.write(b"invalid request size\n")
                return
            fields = parse_qs(
                self.rfile.read(length).decode("utf-8"),
                keep_blank_values=True,
            )
            token = (fields.get("csrf") or [""])[0]
            if not secrets.compare_digest(token, csrf_token):
                self._headers(
                    HTTPStatus.FORBIDDEN,
                    "text/plain; charset=utf-8",
                )
                self.wfile.write(b"csrf rejected\n")
                return
            claim_id = (fields.get("claim_id") or [""])[0]
            decision = (fields.get("decision") or [""])[0]
            reviewer = (fields.get("reviewer") or [""])[0]
            note = (fields.get("note") or [""])[0]
            try:
                status = apply_decision(
                    registry_path,
                    reviews_path,
                    claim_id=claim_id,
                    decision=decision,
                    reviewer=reviewer,
                    note=note,
                )
                model = review_model(
                    registry_path,
                    reviews_path,
                    scene_paths,
                )
                body = render_html(
                    model,
                    csrf_token,
                    default_reviewer=reviewer or default_reviewer,
                    message=f"{claim_id}: {status}",
                ).encode("utf-8")
            except (
                ClaimRegistryError,
                ReviewError,
                ReviewUIError,
                OSError,
                YamlError,
            ) as exc:
                self._headers(
                    HTTPStatus.BAD_REQUEST,
                    "text/plain; charset=utf-8",
                )
                self.wfile.write(("decision rejected: " + str(exc) + "\n").encode("utf-8"))
                return
            self._headers(HTTPStatus.OK)
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:
            return

    return Handler


def serve(
    registry_path: Path,
    reviews_path: Path,
    scene_paths: tuple[Path, ...],
    *,
    host: str,
    port: int,
    unsafe_remote: bool,
    default_reviewer: str,
) -> None:
    registry = load_registry(registry_path)
    validate_bind(
        host,
        visibility=registry.visibility,
        unsafe_remote=unsafe_remote,
    )
    ensure_reviews(registry, reviews_path)
    csrf_token = secrets.token_urlsafe(32)
    handler = _handler_factory(
        Path(registry_path).resolve(),
        Path(reviews_path).resolve(),
        tuple(Path(path).resolve() for path in scene_paths),
        csrf_token,
        default_reviewer,
    )
    server = ThreadingHTTPServer((host, port), handler)
    bound_host, bound_port = server.server_address[:2]
    display_host = "127.0.0.1" if bound_host in {"0.0.0.0", "::"} else bound_host
    print(
        f"HEP review UI: http://{display_host}:{bound_port}/ "
        f"({registry.visibility}, no external assets)"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nreview UI stopped")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m checks.review_ui")
    parser.add_argument("registry", type=Path)
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--scene", action="append", type=Path, default=[])
    parser.add_argument("--reviewer", default="")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument(
        "--unsafe-remote",
        action="store_true",
        help="allow non-loopback bind for public registries only",
    )
    args = parser.parse_args(argv)
    try:
        serve(
            args.registry,
            args.reviews,
            tuple(args.scene),
            host=args.host,
            port=args.port,
            unsafe_remote=args.unsafe_remote,
            default_reviewer=args.reviewer,
        )
        return 0
    except (
        ClaimRegistryError,
        ReviewError,
        ReviewUIError,
        OSError,
        YamlError,
    ) as exc:
        print(f"review UI: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
