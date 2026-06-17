#!/usr/bin/env python3
"""
Blotato CLI for ACME agent.
Wraps the Blotato MCP API (JSON-RPC over HTTP) for both content generation
and social media publishing/scheduling.

Usage:
  blotato.py accounts         [--platform PLATFORM]
  blotato.py templates        [--search TERM]
  blotato.py generate         TEMPLATE_ID PROMPT [--title TEXT] [--timeout N] [--raw]
  blotato.py visual-status    VISUAL_ID           [--raw]
  blotato.py source           URL_OR_TEXT [--type TYPE] [--instructions TEXT] [--timeout N] [--raw]
  blotato.py upload           FILE                [--raw]
  blotato.py publish          TEXT --account-id ID --platform P [--media-url URL ...]
                               [--also TEXT ...] [--schedule DATETIME] [--title T]
                               [--privacy-level LEVEL] [--dry-run] [--raw]
  blotato.py post-status      POST_ID             [--raw]
  blotato.py schedules
  blotato.py user

generate:       Create image, carousel, slideshow, or AI video from a template.
                Polls until the visual is rendered and returns the final URL.
source:         Extract content/transcript from a URL (YouTube, TikTok, article, etc.)
                for use as generation input. Polls until complete.
upload:         Upload a LOCAL image/video to Blotato and print its public URL
                (presigned PUT). Required bridge: produce.py/post.py write local
                files, but publish needs public mediaUrls.
publish:        Post to Instagram/TikTok/X/etc. immediately or at a scheduled time.
                mediaUrls must be public URLs (use `upload` for local files). Pass
                multiple --media-url for a carousel; --also for thread posts.
                --dry-run prints the payload without posting.
"""

import argparse
import json
import mimetypes
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


SCRIPT_DIR = Path(__file__).parent
MCP_URL = "https://mcp.blotato.com/mcp"
DEFAULT_GEN_TIMEOUT = 300   # visuals can take 2–4 min
DEFAULT_SRC_TIMEOUT = 120


def load_api_key():
    env_file = SCRIPT_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("BLOTATO_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    key = os.environ.get("BLOTATO_API_KEY")
    if key:
        return key
    sys.exit("ERROR: BLOTATO_API_KEY not found in .env or environment")


def mcp_call(tool_name, arguments, api_key):
    payload = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": 1,
        "params": {"name": tool_name, "arguments": arguments},
    }
    req = urllib.request.Request(
        MCP_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "blotato-api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": "acme-blotato/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.exit(f"ERROR: Blotato MCP {e.code} on {tool_name}: {body[:400]}")
    except urllib.error.URLError as e:
        sys.exit(f"ERROR: network failure: {e}")

    if "error" in body:
        sys.exit(f"ERROR: {tool_name} failed: {body['error']}")

    result = body.get("result", {})
    # MCP returns content as array of {type,text} blocks
    content = result.get("content", [])
    if content and isinstance(content, list):
        text_blocks = [c.get("text", "") for c in content if c.get("type") == "text"]
        combined = "\n".join(text_blocks)
        try:
            return json.loads(combined)
        except json.JSONDecodeError:
            return combined
    return result


# ── Command implementations ────────────────────────────────────────────────────

def cmd_accounts(platform, raw, api_key):
    args = {}
    if platform:
        args["platform"] = platform
    result = mcp_call("blotato_list_accounts", args, api_key)
    if raw:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    accounts = result if isinstance(result, list) else (result.get("accounts") or result.get("items") or [result])
    out = []
    for a in (accounts if isinstance(accounts, list) else [accounts]):
        entry = {
            "id": a.get("id"),
            "platform": a.get("platform"),
            "name": a.get("displayName") or a.get("name"),
            "username": a.get("username"),
        }
        subs = a.get("subaccounts") or []
        if subs:
            entry["subaccounts"] = [{"id": s.get("id"), "name": s.get("name"), "type": s.get("type")} for s in subs]
        out.append(entry)
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_user(raw, api_key):
    result = mcp_call("blotato_get_user", {}, api_key)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_templates(search, raw, api_key):
    args = {}
    if search:
        args["search"] = search
    result = mcp_call("blotato_list_visual_templates", args, api_key)
    if raw:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    templates = result if isinstance(result, list) else (result.get("templates") or result.get("items") or [result])
    out = []
    for t in (templates if isinstance(templates, list) else [templates]):
        out.append({
            "id": t.get("id"),
            "title": t.get("title") or t.get("name"),
            "category": t.get("category"),
            "description": (t.get("description") or "")[:120],
            "type": t.get("type") or t.get("visualType"),
        })
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_generate(template_id, prompt, title, timeout, raw, api_key):
    args = {
        "templateId": template_id,
        "prompt": prompt,
        "render": True,
    }
    if title:
        args["title"] = title

    print(f"[acme-blotato] generating visual from template={template_id}...", file=sys.stderr)
    result = mcp_call("blotato_create_visual", args, api_key)

    # Extract the visual ID from the response
    visual_id = None
    if isinstance(result, dict):
        visual_id = result.get("id") or result.get("visualId")
    elif isinstance(result, str):
        # Sometimes MCP returns a string with the ID
        try:
            parsed = json.loads(result)
            visual_id = parsed.get("id") or parsed.get("visualId")
        except Exception:
            pass

    if not visual_id:
        if raw:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"error": "no visual_id in response", "raw": result}, ensure_ascii=False, indent=2))
        return

    print(f"[acme-blotato] visual_id={visual_id}, polling for render...", file=sys.stderr)
    _poll_visual(visual_id, timeout, raw, api_key)


def cmd_visual_status(visual_id, raw, api_key):
    result = mcp_call("blotato_get_visual_status", {"id": visual_id}, api_key)
    if raw:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    _format_visual(result, visual_id)


def _poll_visual(visual_id, timeout, raw, api_key):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = mcp_call("blotato_get_visual_status", {"id": visual_id}, api_key)
        status = _extract_visual_status(result)
        print(f"[acme-blotato] visual status={status}", file=sys.stderr)
        if status in ("completed", "done", "rendered", "ready", "COMPLETED", "DONE"):
            if raw:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                _format_visual(result, visual_id)
            return
        if status in ("failed", "error", "FAILED", "ERROR"):
            sys.exit(f"ERROR: Visual {visual_id} failed: {result}")
        time.sleep(8)
    sys.exit(f"ERROR: Visual {visual_id} timed out after {timeout}s")


def _extract_visual_status(result):
    if isinstance(result, dict):
        return result.get("status") or result.get("state") or ""
    return str(result)


def _format_visual(result, visual_id):
    if not isinstance(result, dict):
        print(json.dumps({"id": visual_id, "raw": result}, ensure_ascii=False, indent=2))
        return
    out = {
        "id": visual_id,
        "status": result.get("status") or result.get("state"),
        "url": result.get("url") or result.get("exportUrl") or result.get("mediaUrl") or result.get("outputUrl"),
        "thumbnail": result.get("thumbnail") or result.get("thumbnailUrl"),
        "type": result.get("type") or result.get("visualType"),
        "title": result.get("title"),
    }
    # Remove None values
    out = {k: v for k, v in out.items() if v is not None}
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_source(url_or_text, source_type, instructions, timeout, raw, api_key):
    # Auto-detect type if not specified
    if not source_type:
        lower = (url_or_text or "").lower()
        if "youtube.com" in lower or "youtu.be" in lower:
            source_type = "youtube"
        elif "tiktok.com" in lower:
            source_type = "tiktok"
        elif lower.startswith("http"):
            source_type = "article"
        else:
            source_type = "text"

    args = {"sourceType": source_type}
    if source_type == "text":
        args["text"] = url_or_text
    else:
        args["url"] = url_or_text
    if instructions:
        args["customInstructions"] = instructions

    print(f"[acme-blotato] extracting source type={source_type}...", file=sys.stderr)
    result = mcp_call("blotato_create_source", args, api_key)

    source_id = None
    if isinstance(result, dict):
        source_id = result.get("id") or result.get("sourceId")

    if not source_id:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"[acme-blotato] source_id={source_id}, polling...", file=sys.stderr)
    deadline = time.time() + timeout
    while time.time() < deadline:
        status_result = mcp_call("blotato_get_source_status", {"id": source_id}, api_key)
        status = status_result.get("status", "") if isinstance(status_result, dict) else ""
        print(f"[acme-blotato] source status={status}", file=sys.stderr)
        if status in ("completed", "done", "ready", "COMPLETED"):
            if raw:
                print(json.dumps(status_result, ensure_ascii=False, indent=2))
            else:
                out = {
                    "id": source_id,
                    "type": source_type,
                    "summary": status_result.get("summary") or status_result.get("content", "")[:3000],
                    "transcript": (status_result.get("transcript") or "")[:3000],
                    "title": status_result.get("title"),
                    "url": url_or_text if source_type != "text" else None,
                }
                print(json.dumps({k: v for k, v in out.items() if v}, ensure_ascii=False, indent=2))
            return
        if status in ("failed", "error", "FAILED"):
            sys.exit(f"ERROR: Source {source_id} failed: {status_result}")
        time.sleep(6)
    sys.exit(f"ERROR: Source {source_id} timed out after {timeout}s")


def cmd_upload(file_path, raw, api_key):
    """Upload a LOCAL file to Blotato and print its public URL.

    blotato_create_post needs publicly accessible mediaUrls; our rendered assets
    are local files. Flow: create_presigned_upload_url -> PUT raw bytes -> publicUrl.
    This is the bridge from a job-folder PNG/mp4 to a postable URL.
    """
    p = Path(file_path)
    if not p.exists():
        sys.exit(f"ERROR: file not found: {file_path}")

    presign = mcp_call("blotato_create_presigned_upload_url", {"filename": p.name}, api_key)
    if not isinstance(presign, dict):
        sys.exit(f"ERROR: unexpected presign response: {presign}")
    presigned_url = presign.get("presignedUrl") or presign.get("uploadUrl")
    public_url = presign.get("publicUrl") or presign.get("url")
    if not presigned_url or not public_url:
        sys.exit(f"ERROR: no presignedUrl/publicUrl in response: {presign}")

    content_type = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    print(f"[acme-blotato] uploading {p.name} ({content_type})...", file=sys.stderr)
    req = urllib.request.Request(
        presigned_url, data=p.read_bytes(), method="PUT",
        headers={"Content-Type": content_type},
    )
    try:
        with urllib.request.urlopen(req, timeout=180, context=_ssl_context()) as resp:
            status = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        sys.exit(f"ERROR: upload PUT failed {e.code}: {body[:300]}")
    except urllib.error.URLError as e:
        sys.exit(f"ERROR: upload network failure: {e}")

    if raw:
        print(json.dumps({"publicUrl": public_url, "httpStatus": status}, indent=2))
    else:
        print(public_url)


# TikTok requires these fields on every post (per blotato_list_accounts). Sensible
# brand defaults; AI-generated is true because our visuals are produced by the engine.
TIKTOK_DEFAULTS = {
    "privacyLevel": "PUBLIC_TO_EVERYONE",
    "disabledComments": False,
    "disabledDuet": False,
    "disabledStitch": False,
    "isBrandedContent": False,
    "isYourBrand": True,
    "isAiGenerated": True,
}


def cmd_publish(text, account_id, platform, media_urls, schedule, also, title,
                privacy_level, dry_run, raw, api_key):
    if not account_id:
        sys.exit("ERROR: --account-id required. Run `acme-blotato accounts` to get your account IDs.")
    if not platform:
        sys.exit("ERROR: --platform required (e.g. instagram, tiktok, linkedin, twitter).")

    args = {
        "accountId": account_id,
        "platform": platform,
        "text": text,
        "mediaUrls": media_urls or [],
    }
    if schedule:
        args["scheduledTime"] = schedule           # was "scheduleTime" — wrong key, scheduling silently no-op'd
    if also:                                        # thread (Twitter/Bluesky/Threads): each extra post
        args["additionalPosts"] = [{"text": t} for t in also]
    if platform == "tiktok":
        for k, v in TIKTOK_DEFAULTS.items():
            args.setdefault(k, v)
        if privacy_level:
            args["privacyLevel"] = privacy_level
    if platform == "youtube" and title:
        args["title"] = title

    if dry_run:                                     # show the exact payload, post NOTHING
        print(json.dumps(args, ensure_ascii=False, indent=2))
        return

    print(f"[acme-blotato] publishing to {platform} account={account_id}"
          f"{' (scheduled ' + schedule + ')' if schedule else ''}...", file=sys.stderr)
    result = mcp_call("blotato_create_post", args, api_key)
    if raw:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    out = {
        "id": (result.get("id") or result.get("postId") or result.get("postSubmissionId")) if isinstance(result, dict) else None,
        "status": result.get("status") if isinstance(result, dict) else None,
        "platform": platform,
        "scheduled_for": schedule,
        "raw": result if not isinstance(result, dict) else None,
    }
    print(json.dumps({k: v for k, v in out.items() if v is not None}, ensure_ascii=False, indent=2))


def cmd_post_status(post_id, raw, api_key):
    result = mcp_call("blotato_get_post_status", {"postSubmissionId": post_id}, api_key)
    if raw:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if isinstance(result, dict):
        out = {
            "id": post_id,
            "status": result.get("status"),
            "platform": result.get("platform"),
            "published_at": result.get("publishedAt") or result.get("publishedDate"),
            "url": result.get("url") or result.get("postUrl"),
            "error": result.get("error"),
        }
        print(json.dumps({k: v for k, v in out.items() if v is not None}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_schedules(raw, api_key):
    result = mcp_call("blotato_list_schedules", {}, api_key)
    if raw:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    items = result if isinstance(result, list) else (result.get("items") or result.get("schedules") or [])
    out = []
    for s in items:
        out.append({
            "id": s.get("id"),
            "platform": s.get("platform"),
            "scheduled_for": s.get("scheduleTime") or s.get("scheduledAt"),
            "text_preview": (s.get("text") or "")[:100],
            "status": s.get("status"),
        })
    print(json.dumps(out, ensure_ascii=False, indent=2))


# ── CLI entry point ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(prog="blotato", description="Blotato social media CLI for acme")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # user
    sub.add_parser("user", help="Show authenticated user profile and subscription status")

    # accounts
    p = sub.add_parser("accounts", help="List connected social media accounts")
    p.add_argument("--platform", help="Filter: instagram, tiktok, linkedin, twitter, facebook, youtube, threads, bluesky, pinterest")
    p.add_argument("--raw", action="store_true")

    # templates
    p = sub.add_parser("templates", help="List visual generation templates (carousels, images, AI video)")
    p.add_argument("--search", help="Filter regex (e.g. carousel, quote, slideshow, video, infographic)")
    p.add_argument("--raw", action="store_true")

    # generate
    p = sub.add_parser("generate", help="Generate image/carousel/slideshow/AI video from a template")
    p.add_argument("template_id", help="Template ID from `templates` command")
    p.add_argument("prompt", help="Natural language description of what to generate")
    p.add_argument("--title", help="Human-readable title for the visual")
    p.add_argument("--timeout", type=int, default=DEFAULT_GEN_TIMEOUT, help=f"Max seconds to wait (default {DEFAULT_GEN_TIMEOUT})")
    p.add_argument("--raw", action="store_true")

    # visual-status
    p = sub.add_parser("visual-status", help="Check visual generation status by ID")
    p.add_argument("visual_id")
    p.add_argument("--raw", action="store_true")

    # source
    p = sub.add_parser("source", help="Extract transcript/summary from a YouTube, TikTok, or article URL")
    p.add_argument("url_or_text", help="URL or raw text to extract from")
    p.add_argument("--type", dest="source_type", choices=["text","article","youtube","twitter","tiktok","perplexity-query","audio","pdf"], help="Source type (auto-detected if omitted)")
    p.add_argument("--instructions", help="Custom extraction instructions (e.g. 'focus on key takeaways')")
    p.add_argument("--timeout", type=int, default=DEFAULT_SRC_TIMEOUT)
    p.add_argument("--raw", action="store_true")

    # upload
    p = sub.add_parser("upload", help="Upload a LOCAL file to Blotato; prints its public URL for use as --media-url")
    p.add_argument("file", help="Local path to an image or video")
    p.add_argument("--raw", action="store_true")

    # publish
    p = sub.add_parser("publish", help="Publish or schedule a post to a connected social account")
    p.add_argument("text", help="Post caption/body text")
    p.add_argument("--account-id", required=True, help="Account ID from `accounts` command")
    p.add_argument("--platform", required=True, help="Platform: instagram, tiktok, linkedin, twitter, facebook, youtube, etc.")
    p.add_argument("--media-url", action="append", dest="media_urls", default=[], help="Public media URL (repeatable for multiple images / carousel)")
    p.add_argument("--also", action="append", default=[], help="Additional thread post text (repeatable; Twitter/Bluesky/Threads)")
    p.add_argument("--schedule", help="Schedule time in ISO 8601 format (e.g. 2026-06-01T09:00:00Z). Omit to post immediately.")
    p.add_argument("--title", help="Title (required for YouTube; optional elsewhere)")
    p.add_argument("--privacy-level", dest="privacy_level",
                   choices=["SELF_ONLY", "PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR"],
                   help="TikTok privacy level (default PUBLIC_TO_EVERYONE)")
    p.add_argument("--dry-run", action="store_true", help="Print the exact post payload and exit — posts NOTHING")
    p.add_argument("--raw", action="store_true")

    # post-status
    p = sub.add_parser("post-status", help="Check publishing status of a post by ID")
    p.add_argument("post_id")
    p.add_argument("--raw", action="store_true")

    # schedules
    p = sub.add_parser("schedules", help="List all currently scheduled posts")
    p.add_argument("--raw", action="store_true")

    args = parser.parse_args()
    key = load_api_key()

    if args.cmd == "user":
        cmd_user(False, key)
    elif args.cmd == "accounts":
        cmd_accounts(args.platform, args.raw, key)
    elif args.cmd == "templates":
        cmd_templates(args.search, args.raw, key)
    elif args.cmd == "generate":
        cmd_generate(args.template_id, args.prompt, args.title, args.timeout, args.raw, key)
    elif args.cmd == "visual-status":
        cmd_visual_status(args.visual_id, args.raw, key)
    elif args.cmd == "source":
        cmd_source(args.url_or_text, args.source_type, args.instructions, args.timeout, args.raw, key)
    elif args.cmd == "upload":
        cmd_upload(args.file, args.raw, key)
    elif args.cmd == "publish":
        cmd_publish(args.text, args.account_id, args.platform, args.media_urls, args.schedule,
                    args.also, args.title, args.privacy_level, args.dry_run, args.raw, key)
    elif args.cmd == "post-status":
        cmd_post_status(args.post_id, args.raw, key)
    elif args.cmd == "schedules":
        cmd_schedules(args.raw, key)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
