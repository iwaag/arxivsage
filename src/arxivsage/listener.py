"""Serve arXiv-sage questions from the published study knowledge tree."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agag.agent import SWEEP_ACK, AgentSpec, is_ack, listener_main, run_role
from agag.entrance import EMPTY_REPLY, ENTRANCE_TIMEOUT_SECONDS, EntranceError, NO_ANSWER, entrance_guide
from agag.topics import (
    TopicResult,
    chatlog_path,
    chatlog_placement,
    format_chatlog,
    generation_dir,
    next_generation,
    next_record_path,
    prompt_with_guide,
    serve_topic,
    topic_workspace,
)
from agag.zulip import ZulipClient, log

ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE = ROOT / "knowledge"
STUDY_QUEUE = ROOT / "tostudy"
SPEC = AgentSpec("arxivsage", ROOT, plan_prefix="entrance-")
ROLE = "front"
REDIRECT_REPLY = "Please ask in a topic named `entrance-…`."


def knowledge_revision() -> str:
    """Return the snapshot the run may read without making a missing clone fatal."""
    try:
        result = subprocess.run(
            ["git", "-C", str(KNOWLEDGE), "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"
    return result.stdout.strip() or "unavailable"


def sage_prompt(bot_name: str, revision: str) -> str:
    """Give the run its real placements while keeping the guide portable."""
    return prompt_with_guide(
        [
            chatlog_placement(bot_name),
            f"Your own channel is {SPEC.instance_name()!r}.",
            f"Your knowledge tree is {KNOWLEDGE} (read-only for you).",
            f"Your study queue is {STUDY_QUEUE}.",
            f"The knowledge tree git revision is {revision}.",
        ],
        entrance_guide(SPEC),
    )


def serve_sage(context) -> TopicResult:
    """Answer one entrance topic with an auditable, streaming front run."""
    workspace_root = topic_workspace(SPEC.topics_root, context.channel, context.topic)
    number = next_generation(workspace_root)
    workspace = generation_dir(SPEC.topics_root, context.channel, context.topic, number, ROLE)

    context.step = "chatlog placement"
    chatlog_path(workspace).write_text(
        format_chatlog(context.history, context.self_id, drop=is_ack), encoding="utf-8"
    )

    revision = knowledge_revision()
    context.step = ROLE
    output, _, exit_code = run_role(
        SPEC,
        ROLE,
        sage_prompt(context.bot_name, revision),
        cwd=workspace,
        timeout=ENTRANCE_TIMEOUT_SECONDS,
        record=next_record_path(SPEC.records_root / "entrance_front"),
        transcript=workspace / "transcript.jsonl",
        stream=True,
        home=(context.channel, context.topic),
        extra_meta={"knowledge_revision": revision},
    )
    if exit_code != 0:
        raise EntranceError(f"front run exited {exit_code}: {output.strip()[:500]}")
    return TopicResult([output.strip() or NO_ANSWER])


def handle_sage(client: ZulipClient, channel: str, topic: str) -> None:
    """Serve a correctly named sage entrance."""
    log(f"arxivsage entrance topic {channel!r}/{topic!r}")
    serve_topic(
        client,
        channel,
        topic,
        serve_sage,
        ack_text=SWEEP_ACK,
        empty_reply=EMPTY_REPLY,
    )


def redirect(client: ZulipClient, channel: str, topic: str) -> None:
    """Teach own-channel visitors the entrance vocabulary without a paid run."""
    serve_topic(
        client,
        channel,
        topic,
        lambda _context: TopicResult([REDIRECT_REPLY]),
        ack_text=SWEEP_ACK,
        empty_reply=REDIRECT_REPLY,
    )


def main() -> None:
    listener_main(SPEC, {"entrance-": handle_sage}, entrance=redirect)


if __name__ == "__main__":
    main()
