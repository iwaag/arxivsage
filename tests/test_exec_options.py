"""The sage's execution options (`ag.exec-options.v1`, `refactor` p3 ex1).

What is the sage's own is the menu it derives from `agents.toml` and the fact
that both of its serving routes carry it. The serving discipline behind the
menu — freezing at a serving's start, a configuration-only post costing no
run, a refusal naming what is published — is `agag.topics.serve_topic`'s and
is tested there.
"""

from agag import execopt
from agag.execopt import Selection

from arxivsage import listener


def command(option, bot="arXiv sage"):
    return f"@**{bot}** {execopt.VERB} {option}"


def write_config(path, *profiles):
    body = ['schema = "ag.agent-config.v2"', '[models."antigravity/g"]']
    for name in profiles:
        body.append(f'[profiles.{name}]\nharness = "agy"\nmodel = "antigravity/g"')
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


def test_the_sage_publishes_only_profiles_it_actually_has(tmp_path):
    config = write_config(tmp_path / "agents.toml", "agy")
    assert [option.name for option in listener.exec_options(config)] == ["default", "agy"]


def test_a_profile_that_is_not_published_is_not_offered(tmp_path):
    config = write_config(tmp_path / "agents.toml", "sonnet")
    # `sonnet` is configured but private: it is how the sage is wired, not a
    # choice anybody outside makes.
    assert [option.name for option in listener.exec_options(config)] == ["default"]


def test_an_unreadable_config_publishes_nothing_rather_than_a_wrong_menu(tmp_path):
    assert listener.exec_options(tmp_path / "nothing.toml") == ()


def test_the_committed_menu_is_real_and_keeps_the_test_harness_off_it():
    names = [option.name for option in listener.SPEC.exec_options]
    assert names == ["default", "agy"]
    assert "stub" not in names


def test_every_option_names_the_pool_it_consumes():
    published = listener.SPEC.published_options("arXiv sage")
    assert published.get("default").pool == "anthropic"
    assert published.get("agy").pool == "antigravity"
    assert all(option.covers for option in published.options)


def test_the_published_block_survives_a_round_trip():
    published = listener.SPEC.published_options("arXiv sage")
    back = execopt.parse_options(published.block())
    assert back.supported and back.bot == "arXiv sage"
    assert back.names == published.names


def test_both_serving_routes_carry_the_menu(monkeypatch):
    """The entrance and the own-channel redirect alike.

    The redirect is the one that would be easy to forget, and forgetting it
    means a selection posted at the door is answered with a lecture about
    topic names while the setting silently does not land.
    """
    seen = {}
    monkeypatch.setattr(
        listener, "serve_topic",
        lambda client, channel, topic, handler, **kw: seen.setdefault(topic, kw),
    )

    class Client:
        def whoami(self):
            return {"user_id": 13, "full_name": "arXiv sage"}

    listener.handle_sage(Client(), "arxivsage-agstudio1", "entrance-x")
    listener.redirect(Client(), "arxivsage-agstudio1", "hello")
    for topic in ("entrance-x", "hello"):
        published = seen[topic]["exec_options"]
        assert published is not None and "agy" in published.names


def test_a_selection_reaches_the_answering_run(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(listener, "knowledge_revision", lambda: "abc1234")
    monkeypatch.setattr(
        listener, "run_role",
        lambda spec, role, prompt, **kw: seen.update(kw) or ("answered", {}, 0),
    )

    class Context:
        channel, topic = "arxivsage-agstudio1", "entrance-x"
        history, self_id, bot_name = [], 13, "arXiv sage"
        selection = Selection("agy", "topic", 7)
        step = ""

    monkeypatch.setattr(listener.SPEC.__class__, "topics_root", property(lambda self: tmp_path))
    monkeypatch.setattr(listener.SPEC.__class__, "records_root", property(lambda self: tmp_path))
    listener.serve_sage(Context())
    assert seen["selection"].option == "agy"


def test_a_refused_name_never_becomes_the_setting():
    """The contract's rule, read back through the sage's own menu.

    A directive naming something unpublished is skipped by `resolve`, so the
    topic keeps running on whatever it was running on — a typo must not
    quietly stop a conversation running on `agy`.
    """
    known = listener.SPEC.published_options("arXiv sage").names
    history = [
        {"id": 5, "content": command("agy")},
        {"id": 6, "content": command("opus")},
    ]
    assert execopt.resolve(history, "arXiv sage", known=known).option == "agy"


def test_a_reset_returns_to_the_configured_defaults():
    known = listener.SPEC.published_options("arXiv sage").names
    history = [
        {"id": 5, "content": command("agy")},
        {"id": 6, "content": command("default")},
    ]
    assert execopt.resolve(history, "arXiv sage", known=known) == Selection(
        None, "topic", 6
    )


def test_a_command_posted_during_a_run_lands_on_the_next_serving():
    known = listener.SPEC.published_options("arXiv sage").names
    history = [
        {"id": 5, "content": command("agy")},
        {"id": 9, "content": command("default")},
    ]
    # The serving froze at 6: the later command is not this run's.
    assert execopt.resolve(history, "arXiv sage", up_to=6, known=known).option == "agy"
    assert execopt.resolve(history, "arXiv sage", up_to=9, known=known).option is None
