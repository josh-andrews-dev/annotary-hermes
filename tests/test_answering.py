"""Agents answer the comments they act on: the skill, the tool descriptions and the wake-up all
say the same (as Annotary's own skill does since its S39-01)."""

import importlib.util
import sys

from conftest import ROOT

from annotary_hermes import rules, watcher

RULES = (
    "**After pushing, answer each Thread you acted on**",
    "what changed, in which Version",
    "Done in v3: ",
    "or why not",
    "A question gets an answer, no edit.",
    "Unclear? Ask in that Thread",
    "don't guess",
    "`resolve: true` only on what you fully addressed",
)


def _plugin():
    spec = importlib.util.spec_from_file_location("annotary_plugin_schemas", ROOT / "__init__.py",
                                                  submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_skill_says_to_answer_each_thread_like_a_colleague():
    skill = (ROOT / "skills" / "annotary" / "SKILL.md").read_text()
    for rule in RULES:
        assert rule in skill, f"SKILL.md lost the answering rule {rule!r}"
    assert "with `resolve: true`." not in skill  # the old step resolved every Thread it replied to


def test_the_tool_descriptions_say_it_too():
    schemas = _plugin().SCHEMAS
    reply = schemas["annotary_reply"]["description"]
    for words in ("like a colleague", "what changed and in which Version", "Done in v3", "or why not",
                  "a question back when the comment is unclear", "only when the Thread is fully addressed"):
        assert words in reply, words
    assert "answer each Thread you acted on" in schemas["annotary_push_version"]["description"]
    assert "Answer each one you act on" in schemas["annotary_threads"]["description"]


def wake(reason, action=""):
    return rules.Wake(profile="coder", reason=reason, action=action, doc="d1", name="Plan", by="josh",
                      thread="t2", excerpt="survey or interviews?")


def test_the_wake_up_says_push_once_then_answer_each_thread():
    sent_back = watcher.message_for(wake("review", "send-back"), me="coder", digest="Open Threads: …")
    for words in ("push one new Version", "then answer each Thread you acted on", "Done in v3",
                  "or why not", "A question gets an answer, no edit", "don't guess",
                  "resolve=true only on a Thread you fully addressed"):
        assert words in sent_back, words
    assert sent_back.index("push one new Version") < sent_back.index("answer each Thread")
    approved = watcher.message_for(wake("review", "approve"), me="coder", digest="")
    assert "Do not push" in approved and "Answer every open Thread that is waiting for you" in approved
    mention = watcher.message_for(wake("mention"), me="coder", digest="")
    assert "a question back if it is unclear" in mention and "Do not push" in mention
