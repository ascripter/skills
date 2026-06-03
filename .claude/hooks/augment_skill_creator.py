import json
import sys
from pathlib import Path

SNIPPET = """Use my custom eval subagents explicitly when creating, running, and grading evals.

Subagents:
- eval-creator: use for designing eval cases, prompts, and atomic assertions from the skill's intended behavior and likely failure modes. Use this for eval creation only.
- eval-runner: use for executing one eval case faithfully against the skill or baseline and returning clean, gradable outputs. Use this for eval execution only.
- eval-grader-sonnet: use as the default first-pass grader for routine assertion-based grading. Use it for atomic, format, presence/absence, and other straightforward checks.
- eval-grader-opus: use only for tough grading tasks. Escalate to it when assertions are subjective or holistic, evidence spans multiple files/artifacts, the first-pass grader returns UNCLEAR on a must assertion, or a must-fail looks borderline or weakly supported.

Rules:
1. Use the named subagent that matches the task; do not substitute a generic agent when one of these applies.
2. Use eval-grader-sonnet first by default when grading.
3. Escalate to eval-grader-opus only when the case is genuinely ambiguous, holistic, cross-artifact, or borderline.
4. Keep the same eval IDs, assertion IDs, and grading schema across both graders.
5. Keep outputs concise, evidence-based, and machine-readable.
"""


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:
        event = {}

    command = event.get("command_name", "")

    project_dir = Path.cwd()
    try:
        log_path = project_dir / ".claude" / "hooks" / "augment_skill_creator.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            # Log the full event so you can see the real field values when testing.
            # Only activate for debug => "transcript_path" file contains hook output
            # f.write(f"{datetime.now().isoformat()} event={json.dumps(event)}\n")
            pass

    except Exception:
        pass

    # No command guard here: the matcher in settings.json already restricts
    # firing to skill-creator. (The real command_name is the plugin-namespaced
    # "skill-creator:skill-creator", so an exact == "skill-creator" check would
    # wrongly reject every real invocation.)

    # UserPromptExpansion requires additionalContext nested under
    # hookSpecificOutput. A top-level additionalContext is silently ignored.
    # Nothing else may be written to stdout, or the JSON becomes unparseable.
    out = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptExpansion",
            "additionalContext": SNIPPET,
        }
    }
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
