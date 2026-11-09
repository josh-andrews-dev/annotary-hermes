"""Whether each profile has the plugin (enablement.py) and that its skill reaches the prompt."""

import importlib.util
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest
from conftest import ROOT, make_profile

from annotary_hermes import accounts, cli, enablement, paths, skillmeta, tools

CONFIG = """model:
  default: test
plugins:
  # Deadline for each Git clone. Default: 300
  clone_timeout_seconds: 300

  enabled:
    - annotary
    # a comment between items
    - homeassistant  # trailing comment
  disabled:
    - annotary-spike
  entries:
    annotary:
      enabled: true
webapp:
  enabled: true
"""


@pytest.fixture(params=["pyyaml", "fallback"])
def yaml_path(request, monkeypatch):
    """Run a test through PyYAML (what Hermes has) and through the parser used without it."""
    if request.param == "pyyaml":
        import yaml
        assert yaml.safe_load("a: 1") == {"a": 1}
    else:
        monkeypatch.setitem(sys.modules, "yaml", None)  # `import yaml` raises ImportError
    return request.param


def test_reads_enabled_and_disabled_plugin_lists_without_pyyaml():
    assert enablement.parse_plugin_lists(CONFIG) == {
        "enabled": ["annotary", "homeassistant"], "disabled": ["annotary-spike"]}
    assert enablement.parse_plugin_lists("plugins:\n  enabled: [annotary, 'x']\n") == {
        "enabled": ["annotary", "x"], "disabled": []}
    assert enablement.parse_plugin_lists("plugins:\n    enabled:\n      - annotary\n")["enabled"] == ["annotary"]
    assert enablement.parse_plugin_lists("webapp:\n  enabled:\n    - annotary\n")["enabled"] == []


def test_plugin_lists_read_the_same_either_way(tmp_path, yaml_path):
    (tmp_path / "config.yaml").write_text(CONFIG)
    assert enablement.plugin_lists(tmp_path) == {
        "enabled": ["annotary", "homeassistant"], "disabled": ["annotary-spike"]}


@pytest.mark.parametrize("config", [
    "- a list\n", "plugins: [annotary]\n", "plugins: annotary\n", "plugins:\n  enabled: annotary\n",
    "plugins:\n  enabled:\n    annotary: true\n", "plugins:\n  enabled: 3\n  disabled: {a: 1}\n", "plugins: null\n",
    "plugins: [unclosed\n"])
def test_a_config_of_the_wrong_shape_lists_nothing(tmp_path, config):
    import yaml
    assert yaml  # this path needs PyYAML
    (tmp_path / "config.yaml").write_text(config)
    assert enablement.plugin_lists(tmp_path) == {"enabled": [], "disabled": []}


def test_frontmatter_reads_the_same_either_way(tmp_path, yaml_path):
    f = tmp_path / "SKILL.md"
    f.write_text("---\nname: annotary\ndescription: 'Reviews here.'\n---\nBody\n")
    assert skillmeta.frontmatter(f) == {"name": "annotary", "description": "Reviews here."}
    f.write_text("no frontmatter\n")
    assert skillmeta.frontmatter(f) == {}


def test_frontmatter_that_pyyaml_rejects_or_is_not_a_mapping_is_empty(tmp_path):
    import yaml
    assert yaml  # this path needs PyYAML
    f = tmp_path / "SKILL.md"
    f.write_text("---\n- a\n- b\n---\n")
    assert skillmeta.frontmatter(f) == {}
    f.write_text("---\nname: [unclosed\n---\n")
    assert skillmeta.frontmatter(f) == {}


def test_plugin_state_per_profile(tmp_path, yaml_path):
    root = tmp_path / "hermes"
    make_profile(root, "default")
    installed = root / "plugins" / "annotary"
    assert installed.is_dir() and not installed.is_symlink()  # as after `hermes plugins install`
    assert enablement.plugin_state("default", root) == enablement.ON
    make_profile(root, "linked")
    assert enablement.plugin_state("linked", root) == enablement.ON
    make_profile(root, "fresh", annotary=False)  # `hermes profile create` after install
    assert enablement.plugin_state("fresh", root) == enablement.OFF
    home = make_profile(root, "listed-only", annotary=False)  # enabled in config, no plugin folder
    (home / "config.yaml").write_text("plugins:\n  enabled:\n    - annotary\n")
    assert enablement.plugin_state("listed-only", root) == enablement.OFF
    home = make_profile(root, "switched-off")  # `hermes -p X plugins disable annotary`
    (home / "config.yaml").write_text("plugins:\n  enabled: []\n  disabled:\n    - annotary\n")
    assert enablement.plugin_state("switched-off", root) == enablement.DECLINED
    home = make_profile(root, "both-lists")  # plugins.disabled wins, as in Hermes
    (home / "config.yaml").write_text("plugins:\n  enabled: [annotary]\n  disabled: [annotary]\n")
    assert enablement.plugin_state("both-lists", root) == enablement.DECLINED
    home = make_profile(root, "unlisted")  # linked, then taken off the enabled list by hand
    (home / "config.yaml").write_text("model: test\n")
    assert enablement.plugin_state("unlisted", root) == enablement.DECLINED
    home = make_profile(root, "linked-parent", annotary=False)  # all of plugins/ is a link
    (home / "plugins").symlink_to(root / "plugins", target_is_directory=True)
    (home / "config.yaml").write_text("plugins:\n  enabled: [annotary]\n")
    assert enablement.plugin_state("linked-parent", root) == enablement.ON
    clone = _clone_of_default(root, "bot")
    assert enablement.plugin_state("bot", root) == enablement.COPY
    assert clone.is_dir() and not clone.is_symlink()


def _clone_of_default(root: Path, name: str) -> Path:
    """What `hermes profile create NAME --clone` (and Desktop's Bot Mode) leaves: the config with
    the plugin enabled and a physical copy of the installed plugin folder."""
    home = make_profile(root, name, annotary=False)
    (home / "config.yaml").write_text("plugins:\n  enabled:\n    - annotary\n")
    copy = home / "plugins" / "annotary"
    (copy / "annotary_hermes").mkdir(parents=True)
    (copy / ".git").mkdir()  # installed from git, and `--clone` keeps that
    (copy / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (copy / "plugin.yaml").write_text((ROOT / "plugin.yaml").read_text())
    (copy / "__init__.py").write_text("# an old copy\n")
    return copy


def test_link_plugin_links_a_new_profile_and_replaces_a_cloned_copy(tmp_path):
    root = tmp_path / "hermes"
    make_profile(root, "default")
    installed = (root / "plugins" / "annotary").resolve()
    make_profile(root, "fresh", annotary=False)
    assert enablement.link_plugin("fresh", root) == "linked"
    assert (root / "profiles" / "fresh" / "plugins" / "annotary").resolve() == installed
    assert enablement.link_plugin("fresh", root) == "linked"  # idempotent
    copy = _clone_of_default(root, "bot")
    assert enablement.link_plugin("bot", root) == "replaced its own copy with a link"
    assert copy.is_symlink() and copy.resolve() == installed
    assert enablement.plugin_state("bot", root) == enablement.ON
    assert not list((root / "profiles" / "bot" / "plugin-data" / "annotary").glob(".replaced-*"))
    other = make_profile(root, "mine", annotary=False) / "plugins" / "annotary"
    other.mkdir(parents=True)
    (other / "plugin.yaml").write_text("name: something-else\n")
    assert enablement.link_plugin("mine", root) == "left as is: not this plugin"
    assert not other.is_symlink()
    assert enablement.link_plugin("default", root) == "the installed plugin"


def _installed(root):
    make_profile(root, "default")
    return root / "plugins" / "annotary"


def test_link_plugin_keeps_a_plugin_that_is_the_installed_one_by_another_path(tmp_path):
    root = tmp_path / "hermes"
    installed = _installed(root)
    home = make_profile(root, "shared", annotary=False)
    (home / "plugins").symlink_to(root / "plugins", target_is_directory=True)
    assert enablement.link_plugin("shared", root) == "left as is: this is the installed plugin"
    assert installed.is_dir() and not installed.is_symlink() and (installed / "plugin.yaml").is_file()


def test_link_plugin_keeps_the_running_package_when_nothing_is_installed(tmp_path, monkeypatch):
    root = tmp_path / "hermes"
    make_profile(root, "default", annotary=False)
    copy = _clone_of_default(root, "bot")
    monkeypatch.setattr(paths, "package_dir", lambda: copy)
    assert enablement.link_plugin("bot", root) == "left as is: this is the installed plugin"
    assert copy.is_dir() and not copy.is_symlink() and (copy / "plugin.yaml").is_file()


def test_link_plugin_needs_a_real_target(tmp_path, monkeypatch):
    root = tmp_path / "hermes"
    make_profile(root, "default", annotary=False)
    copy = _clone_of_default(root, "bot")
    make_profile(root, "fresh", annotary=False)
    monkeypatch.setattr(paths, "package_dir", lambda: tmp_path / "gone")
    for pid in ("bot", "fresh"):
        assert enablement.link_plugin(pid, root) == "left as is: the installed plugin is missing"
    assert copy.is_dir() and not copy.is_symlink() and not (root / "profiles" / "fresh" / "plugins").exists()


def test_link_plugin_leaves_another_plugin_that_shares_the_name(tmp_path):
    root = tmp_path / "hermes"
    _installed(root)
    theirs = make_profile(root, "mine", annotary=False) / "plugins" / "annotary"
    theirs.mkdir(parents=True)
    (theirs / "plugin.yaml").write_text("name: annotary\n")
    assert enablement.link_plugin("mine", root) == "left as is: not this plugin"
    assert theirs.is_dir() and not theirs.is_symlink() and (theirs / "plugin.yaml").is_file()


def _failing_symlink(error):
    def fail(self, *a, **kw):
        raise error
    return fail


def test_a_failed_link_puts_the_copy_back(tmp_path, monkeypatch):
    root = tmp_path / "hermes"
    _installed(root)
    copy = _clone_of_default(root, "bot")
    monkeypatch.setattr(Path, "symlink_to", _failing_symlink(OSError("no room")))
    assert enablement.link_plugin("bot", root) == "left as is: could not link it (no room)"
    assert copy.is_dir() and not copy.is_symlink() and (copy / ".git" / "HEAD").is_file()
    assert not list((root / "profiles" / "bot" / "plugin-data" / "annotary").glob(".replaced-*"))


def test_an_interrupted_link_puts_the_copy_back(tmp_path, monkeypatch):
    root = tmp_path / "hermes"
    _installed(root)
    copy = _clone_of_default(root, "bot")
    monkeypatch.setattr(Path, "symlink_to", _failing_symlink(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        enablement.link_plugin("bot", root)
    assert copy.is_dir() and not copy.is_symlink() and (copy / ".git" / "HEAD").is_file()


def test_a_run_killed_after_moving_the_copy_aside_is_finished_next_time(tmp_path):
    root = tmp_path / "hermes"
    installed = _installed(root)
    copy = _clone_of_default(root, "bot")
    data = root / "profiles" / "bot" / "plugin-data" / "annotary"
    data.mkdir(parents=True)
    copy.rename(data / ".replaced-abcd")
    assert not copy.exists()
    assert enablement.link_plugin("bot", root) == "replaced its own copy with a link"
    assert copy.is_symlink() and copy.resolve() == installed.resolve()
    assert not list(data.glob(".replaced-*"))


def test_leftovers_go_and_never_replace_what_is_there(tmp_path):
    root = tmp_path / "hermes"
    installed = _installed(root)
    make_profile(root, "linked", annotary=False)
    assert enablement.link_plugin("linked", root) == "linked"
    data = root / "profiles" / "linked" / "plugin-data" / "annotary"
    (data / ".replaced-beef").mkdir(parents=True)
    assert enablement.link_plugin("linked", root) == "linked"
    assert not list(data.glob(".replaced-*"))
    assert (root / "profiles" / "linked" / "plugins" / "annotary").resolve() == installed.resolve()


class FakeHermes:
    """`hermes -p X plugins enable|disable annotary`, doing to the config what Hermes does (its
    plugins_cmd.py): enable adds to enabled and removes from disabled, and fails with no folder."""

    def __init__(self, root, fail=()):
        self.root, self.fail, self.enabled = root, set(fail), []

    def home(self, pid):
        return self.root if pid == "default" else self.root / "profiles" / pid

    def write(self, pid, enabled, disabled):
        (self.home(pid) / "config.yaml").write_text(
            f"plugins:\n  enabled: {enabled}\n  disabled: {disabled}\n")

    def disable(self, pid):
        self.write(pid, [], ["annotary"])

    def __call__(self, args):
        if args[2:4] == ["plugins", "enable"]:
            pid = args[1]
            if pid in self.fail or not (self.home(pid) / "plugins" / "annotary").exists():
                return subprocess.CompletedProcess(args, 1, "", "No plugin named 'annotary'")
            self.write(pid, ["annotary"], [])
            self.enabled.append(pid)
        return subprocess.CompletedProcess(args, 0, "", "")


@pytest.fixture()
def fake_hermes(hermes, monkeypatch):
    fake = FakeHermes(hermes)
    monkeypatch.setattr(cli, "_run_hermes", fake)
    return fake


def test_enable_all_leaves_a_declined_profile_off(hermes, fake_hermes, capsys):
    fake_hermes.disable("bencha")
    before = (hermes / "profiles" / "bencha" / "config.yaml").read_text()
    assert cli.enable(Namespace(all=True, profile=None)) == 0
    assert "bencha" not in fake_hermes.enabled and "coder" in fake_hermes.enabled
    assert (hermes / "profiles" / "bencha" / "config.yaml").read_text() == before
    assert enablement.plugin_state("bencha") == enablement.DECLINED
    assert "bencha: left off, as you chose (to turn it on: hermes annotary enable bencha)" in capsys.readouterr().out


def test_enable_all_still_sets_up_a_fresh_profile_and_a_clone(hermes, fake_hermes):
    make_profile(hermes, "fresh", annotary=False)
    copy = _clone_of_default(hermes, "bot")
    assert cli.enable(Namespace(all=True, profile=None)) == 0
    assert enablement.plugin_state("fresh") == enablement.ON and enablement.plugin_state("bot") == enablement.ON
    assert copy.is_symlink()


def test_enable_a_profile_opts_a_declined_one_back_in(hermes, fake_hermes):
    fake_hermes.disable("bencha")
    assert cli.enable(Namespace(all=False, profile="bencha")) == 0
    assert fake_hermes.enabled == ["bencha"]
    assert enablement.plugin_state("bencha") == enablement.ON


def test_enable_a_profile_sets_up_a_fresh_one_and_links_a_clone(hermes, fake_hermes):
    make_profile(hermes, "fresh", annotary=False)
    copy = _clone_of_default(hermes, "bot")
    assert cli.enable(Namespace(all=False, profile="fresh")) == 0
    assert cli.enable(Namespace(all=False, profile="bot")) == 0
    assert enablement.plugin_state("fresh") == enablement.ON
    assert enablement.plugin_state("bot") == enablement.ON and copy.is_symlink()


@pytest.mark.parametrize("args", [Namespace(all=False, profile=None), Namespace(all=True, profile="coder")])
def test_enable_needs_all_or_one_profile(fake_hermes, args, capsys):
    assert cli.enable(args) == 1
    assert "usage" in capsys.readouterr().err and fake_hermes.enabled == []


def test_enable_refuses_a_profile_that_does_not_exist(fake_hermes, capsys):
    assert cli.enable(Namespace(all=False, profile="nope")) == 1
    assert "no profile named nope" in capsys.readouterr().err and fake_hermes.enabled == []


def test_a_failed_enable_does_not_read_as_declined(hermes, fake_hermes):
    make_profile(hermes, "fresh", annotary=False)
    fake_hermes.fail.add("fresh")
    assert cli.enable(Namespace(all=True, profile=None)) == 1
    assert enablement.plugin_state("fresh") == enablement.OFF
    assert not (hermes / "profiles" / "fresh" / "plugins" / "annotary").is_symlink()
    fake_hermes.fail.clear()
    assert cli.enable(Namespace(all=True, profile=None)) == 0
    assert enablement.plugin_state("fresh") == enablement.ON


def test_a_failed_enable_keeps_a_profile_that_already_had_it(hermes, fake_hermes):
    home = make_profile(hermes, "had", annotary=False)
    assert enablement.link_plugin("had") == "linked"
    (home / "config.yaml").write_text("plugins:\n  enabled: [annotary]\n")
    fake_hermes.fail.add("had")
    assert cli.enable(Namespace(all=False, profile="had")) == 1
    assert (home / "plugins" / "annotary").is_symlink()
    assert enablement.plugin_state("had") == enablement.ON


def test_doctor_and_members_accept_a_declined_profile_without_nagging(hermes, fake_hermes, capsys):
    accounts.reconcile()
    fake_hermes.disable("bencha")
    assert accounts.reconcile() == {}  # no note, this pass or later
    assert cli.doctor() == 0
    out = capsys.readouterr().out
    assert "Annotary is off in profile bencha, as you chose" in out and "FAIL" not in out
    assert cli.members() == 0
    out = capsys.readouterr().out
    assert "Annotary off (your choice)" in out and "run `hermes annotary enable --all`" not in out


def test_doctor_still_fails_a_fresh_profile_and_a_clone(hermes, fake_hermes, capsys):
    make_profile(hermes, "fresh", annotary=False)
    assert cli.doctor() == 1
    assert "FAIL Annotary is off in profile fresh" in capsys.readouterr().out
    cli.enable(Namespace(all=True, profile=None))
    _clone_of_default(hermes, "bot")
    assert cli.doctor() == 1
    assert "FAIL profile bot runs its own copy" in capsys.readouterr().out


def test_reconcile_says_when_a_declined_profile_comes_back(hermes, fake_hermes):
    accounts.reconcile()
    fake_hermes.disable("bencha")
    assert accounts.reconcile() == {}
    fake_hermes("-p bencha plugins enable annotary".split())
    assert accounts.reconcile() == {"bencha": "Annotary is on in this profile"}


def _dashboard():
    spec = importlib.util.spec_from_file_location("annotary_dashboard_under_test", ROOT / "dashboard" / "plugin_api.py")
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    return api


def test_the_page_offers_only_bots_that_can_edit(hermes, fake_hermes):
    make_profile(hermes, "fresh", annotary=False)
    _clone_of_default(hermes, "bot")
    fake_hermes.disable("bencha")
    accounts.reconcile()
    bots = _dashboard()._status()["bots"]
    assert "@coder" in bots and "@bot" in bots
    assert "@fresh" not in bots and "@bencha" not in bots


def test_a_declined_profile_cannot_be_made_editor(hermes, fake_hermes):
    from annotary_hermes import docs as docs_mod
    accounts.reconcile()
    made = tools.share(tools.Caller(profile="coder", session_key="s", surface="cli", cwd=""), markdown="# P\n", name="P")
    fake_hermes.disable("bencha")
    with pytest.raises(tools.ToolError, match="hermes annotary enable bencha"):
        tools.handoff(tools.Caller(profile="coder", session_key="s", surface="cli", cwd=""), doc=made["id"], to="@bencha")
    with pytest.raises(ValueError, match="hermes annotary enable bencha"):
        docs_mod.set_editor_for_handle(made["id"], "@bencha")


class FakeCtx:
    profile_name = "coder"

    def __init__(self):
        self.skills, self.tools = [], []

    def register_tool(self, **kw):
        self.tools.append(kw["name"])

    def register_skill(self, name, path, description="", frontmatter=None):
        self.skills.append({"name": name, "path": path, "description": description, "frontmatter": frontmatter})

    def register_cli_command(self, **kw):
        pass


def test_the_skill_is_registered_with_its_description():
    spec = importlib.util.spec_from_file_location("annotary_plugin_under_test", ROOT / "__init__.py",
                                                  submodule_search_locations=[str(ROOT)])
    plugin = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = plugin
    spec.loader.exec_module(plugin)
    ctx = FakeCtx()
    plugin.register(ctx)
    assert len(ctx.tools) == 7
    (skill,) = ctx.skills
    assert skill["name"] == "annotary"
    # Hermes shows the first 60 characters in the system prompt's skill index: they must say what it is.
    first = skill["description"].split(".")[0]
    assert len(first) <= 57 and first.startswith("Annotary")
    assert skill["frontmatter"]["name"] == "annotary"
