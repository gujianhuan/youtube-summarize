# -*- coding: utf-8 -*-
"""Generate a minimal git patch for the Render remote-worker fix."""

from __future__ import annotations

from pathlib import Path
import difflib
import re


ROOT = Path(__file__).resolve().parent


def read_text_auto(path: Path) -> str:
    """Read text from files that may be stored as UTF-8 or UTF-16."""
    for encoding in ("utf-8", "utf-8-sig", "utf-16"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeError:
            continue
    raise RuntimeError(f"Unsupported encoding: {path}")


def replace_once(text: str, old: str, new: str) -> str:
    if old not in text:
        raise RuntimeError(f"Snippet not found:\n{old[:200]}")
    return text.replace(old, new, 1)


def main() -> int:
    app_head_path = ROOT / "tmp_git_head_app.py"
    core_head_path = ROOT / "tmp_git_head_core_logic.py"
    patch_path = ROOT / "tmp_minimal_render_fix.patch"

    app_head = read_text_auto(app_head_path)
    core_head = read_text_auto(core_head_path)

    app_target, app_sub_count = re.subn(
        r"    status_col1, status_col2 = st\.columns\(\[5, 1\]\)\r?\n"
        r"[\s\S]*?"
        r"(?=    url = st\.text_input)",
        "",
        app_head,
        count=1,
    )
    if app_sub_count != 1:
        raise RuntimeError("Failed to locate remote status panel in tmp_head_app.py")

    core_target = core_head
    core_target, sub_count = re.subn(
        r'(def get_remote_worker_status\(timeout_seconds: float = 4\.0\) -> dict:\n\s+""".*?"""\n)',
        r'\1'
        '    remote_enabled = str(\n'
        '        os.environ.get("REMOTE_TRANSCRIBE_ENABLED", "0") or "0"\n'
        '    ).strip().lower() in {"1", "true", "yes"}\n',
        core_target,
        count=1,
        flags=re.DOTALL,
    )
    if sub_count != 1:
        raise RuntimeError("Failed to update get_remote_worker_status header")
    core_target = replace_once(
        core_target,
        '    status = {\n        "configured": bool(worker_url),\n        "remote_mode": remote_mode or "disabled",\n',
        '    status = {\n        "configured": remote_enabled and bool(worker_url),\n        "remote_enabled": remote_enabled,\n        "remote_mode": remote_mode if remote_enabled else "disabled",\n',
    )
    core_target = replace_once(
        core_target,
        '    }\n\n    if not worker_url:\n',
        '    }\n\n    if not remote_enabled:\n        status["health_error"] = "REMOTE_TRANSCRIBE_ENABLED=0"\n        return status\n\n    if not worker_url:\n',
    )
    core_target, sub_count = re.subn(
        r'(\s+""".*?"""\n)(\s+worker_url = str\(os\.environ\.get\("REMOTE_TRANSCRIBE_URL", ""\) or ""\)\.strip\(\)\n)',
        r'\1'
        '    remote_enabled = str(\n'
        '        os.environ.get("REMOTE_TRANSCRIBE_ENABLED", "0") or "0"\n'
        '    ).strip().lower() in {"1", "true", "yes"}\n'
        '    if not remote_enabled:\n'
        '        raise RuntimeError("远程抓取节点已禁用（REMOTE_TRANSCRIBE_ENABLED=0）")\n\n'
        r'\2',
        core_target,
        count=1,
        flags=re.DOTALL,
    )
    if sub_count != 1:
        raise RuntimeError("Failed to update try_fetch_transcript_via_remote_worker header")
    core_target = replace_once(
        core_target,
        '        remote_worker_mode = str(os.environ.get("REMOTE_TRANSCRIBE_MODE", "") or "").strip().lower()\n        prefer_remote_first = remote_worker_mode in {"prefer_remote", "remote_first", "force_remote"}\n',
        '        remote_worker_mode = str(os.environ.get("REMOTE_TRANSCRIBE_MODE", "") or "").strip().lower()\n'
        '        remote_worker_enabled = str(\n'
        '            os.environ.get("REMOTE_TRANSCRIBE_ENABLED", "0") or "0"\n'
        '        ).strip().lower() in {"1", "true", "yes"}\n'
        '        prefer_remote_first = remote_worker_enabled and remote_worker_mode in {"prefer_remote", "remote_first", "force_remote"}\n',
    )
    core_target = replace_once(
        core_target,
        '    remote_worker_mode = str(os.environ.get("REMOTE_TRANSCRIBE_MODE", "") or "").strip().lower()\n    prefer_remote_first = remote_worker_mode in {"prefer_remote", "remote_first", "force_remote"}\n',
        '    remote_worker_mode = str(os.environ.get("REMOTE_TRANSCRIBE_MODE", "") or "").strip().lower()\n'
        '    remote_worker_enabled = str(\n'
        '        os.environ.get("REMOTE_TRANSCRIBE_ENABLED", "0") or "0"\n'
        '    ).strip().lower() in {"1", "true", "yes"}\n'
        '    prefer_remote_first = remote_worker_enabled and remote_worker_mode in {"prefer_remote", "remote_first", "force_remote"}\n',
    )

    diff_lines = []
    diff_lines.extend(
        difflib.unified_diff(
            app_head.splitlines(True),
            app_target.splitlines(True),
            fromfile="a/app.py",
            tofile="b/app.py",
            n=3,
        )
    )
    diff_lines.extend(
        difflib.unified_diff(
            core_head.splitlines(True),
            core_target.splitlines(True),
            fromfile="a/core_logic.py",
            tofile="b/core_logic.py",
            n=3,
        )
    )

    patch_path.write_text("".join(diff_lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
