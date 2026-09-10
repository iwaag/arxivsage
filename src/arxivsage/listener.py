"""Serve arXiv-sage questions from the published study knowledge tree.

Since `refactor` p3 ex1 the sage publishes **execution options**
(`ag.exec-options.v1`) like every other standardized agent: a public name for
a way of executing, mapped to a private `agents.toml` profile. The menu is
derived from the configuration, so a name whose profile is gone is never
advertised, and `stub` — the `fake` harness the suite runs on — is
deliberately not on it: a menu that offers a harness which answers nothing
is worse than a short menu.

An option chooses the harness and model that read the knowledge tree and
write the answer. It changes nothing else about the sage: it still never
edits the tree, still cites what it read, and still queues an honestly
unanswerable question for the study workflow.
"""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

from agag.agent import SWEEP_ACK, AgentSpec, exec_options_for, is_ack, listener_main, run_role
from agag.execopt import Option, Selection
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
ROLE = "front"
REDIRECT_REPLY = "Please ask in a topic named `entrance-…`."

#: What the sage is willing to be asked for: `(profile name, usage pool,
#: phrase)`. The profile name is the public name — one-to-one, the contract's
#: suggested start — and `exec_options` publishes one only if `agents.toml`
#: has it. `sonnet` stays private (it is how the sage is wired, not a choice
#: anybody outside makes) and `stub` stays off the menu entirely: it is the
#: `fake` harness the tests run on.
PUBLIC_PROFILES = (
    ("agy", "antigravity", "Antigravity CLI (`agy`), Gemini 3.8 Flash"),
)
#: The sage has one role, so an option covers the whole of it.
COVERS = "every answer I give, in any entrance topic"
#: What running under no selection costs. Published because a threshold like
#: "until the pool is 70 % used" cannot be judged against a default that
#: declines to name a pool.
DEFAULT_OPTION_DETAIL = ("anthropic", "my configured defaults — Claude Sonnet 5 through claude_code")
#: The sage's one role, and the role the published pool is **derived** from
#: (`agag.execpool`).
EXEC_ROLES = ("front",)


def configured_profiles(path: Path | None = None) -> frozenset[str]:
    """The profile names `agents.toml` declares.

    Read straight rather than through the validating loader: this runs at
    import time, and a schema complaint here would take the listener down
    while the only fact needed is which names exist.
    """
    try:
        data = tomllib.loads((path or (ROOT / "agents.toml")).read_text(encoding="utf-8"))
        return frozenset(data.get("profiles", {}))
    except (OSError, tomllib.TOMLDecodeError, AttributeError):
        return frozenset()


def exec_options(path: Path | None = None) -> tuple[Option, ...]:
    """The sage's menu, from the profiles it is actually configured with.

    Publishing nothing when the config cannot be read leaves a reader at
    *unknown*, which is the honest answer for an instance that cannot say —
    and better than advertising a name that would fail at execution time.
    """
    profiles = configured_profiles(path)
    if not profiles:
        return ()
    pool, summary = DEFAULT_OPTION_DETAIL
    return (
        Option("default", pool, COVERS, summary),
        *(
            Option(name, option_pool, COVERS, option_summary)
            for name, option_pool, option_summary in PUBLIC_PROFILES
            if name in profiles
        ),
    )


SPEC = AgentSpec("arxivsage", ROOT, plan_prefix="entrance-",
                 exec_options=exec_options(), exec_roles=EXEC_ROLES)


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
        # The answer runs under whatever this conversation was told to run
        # under, and the record carries the public name beside the harness's
        # own facts: what was asked for, beside what ran.
        selection=context.selection,
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
        exec_options=exec_options_for(SPEC, client),
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
        # The own-channel redirect obeys commands too: a selection posted at
        # the door is applied and answered rather than met with the
        # vocabulary lecture, which would leave the poster guessing whether
        # it landed.
        exec_options=exec_options_for(SPEC, client),
    )


def main() -> None:
    listener_main(SPEC, {"entrance-": handle_sage}, entrance=redirect)


if __name__ == "__main__":
    main()
