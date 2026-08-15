"""ensure_graphify.sh — the resolve-or-install ladder.

The engine went from consent-by-installation to expected-present (2026-08-15,
"rich agent by default"): the script must try every reasonable path to an engine
and concede only when installation is provably impossible. These tests drive the
decision ladder with stub interpreters — no network, no real pip.

Exit-code contract under test (callers key behavior off it):
  0 ready (python path on stdout) / 2 operator kill switch / 3 impossible.
"""
import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "ensure_graphify.sh"


def _write(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _ok_python(path: Path) -> Path:
    """A stub interpreter that already 'has' the engine installed. Keys on the
    shared prefix: engine_ok probes `import graphify` then `import graphifyy`
    (dist name and module name differ on the real wheel)."""
    return _write(path, "#!/bin/sh\ncase \"$*\" in *'import graph'*) exit 0;; esac\nexit 0\n")


def _broken_python(path: Path) -> Path:
    """A stub interpreter that cannot import the engine under either module name."""
    return _write(path, "#!/bin/sh\ncase \"$*\" in *'import graph'*) exit 1;; esac\nexit 0\n")


def _bootstrap_python(path: Path) -> Path:
    """A stub base interpreter: passes the version probe, 'creates' a venv whose
    python only imports graphifyy after 'pip install' drops a marker file."""
    return _write(path, """#!/bin/sh
case "$*" in
  *'sys.version_info'*) exit 0 ;;
  *'-m venv'*)
    venv="$2"
    [ "$1" = "-m" ] && venv="$3"
    mkdir -p "$venv/bin"
    cat > "$venv/bin/python" <<INNER
#!/bin/sh
here="\\$(cd "\\$(dirname "\\$0")/.." && pwd)"
case "\\$*" in
  *'pip install'*) touch "\\$here/.installed"; exit 0 ;;
  *'import graph'*) [ -f "\\$here/.installed" ] && exit 0 || exit 1 ;;
esac
exit 0
INNER
    chmod +x "$venv/bin/python"
    exit 0 ;;
esac
exit 0
""")


def run(env_extra: dict, path_dirs: list) -> subprocess.CompletedProcess:
    env = {"HOME": env_extra.pop("HOME"), "PATH": ":".join(str(d) for d in path_dirs) + ":/usr/bin:/bin"}
    env.update(env_extra)
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env)


def test_kill_switch_exits_2_and_is_quiet_on_stdout(tmp_path):
    r = run({"HOME": str(tmp_path), "GRAPHIFY_ADAPTER": "0"}, [])
    assert r.returncode == 2
    assert r.stdout == ""
    assert "disabled by operator" in r.stderr


def test_explicit_override_wins_when_healthy(tmp_path):
    py = _ok_python(tmp_path / "mypython")
    r = run({"HOME": str(tmp_path), "GRAPHIFY_PYTHON": str(py)}, [])
    assert r.returncode == 0
    assert r.stdout.strip() == str(py)


def test_explicit_override_broken_is_impossible_not_a_guess(tmp_path):
    py = _broken_python(tmp_path / "mypython")
    r = run({"HOME": str(tmp_path), "GRAPHIFY_PYTHON": str(py)}, [])
    assert r.returncode == 3
    assert "cannot import the engine" in r.stderr


def test_healthy_existing_venv_is_reused_not_rebuilt(tmp_path):
    venv = tmp_path / "engine-venv"
    (venv / "bin").mkdir(parents=True)
    _ok_python(venv / "bin" / "python")
    marker = venv / ".reuse_marker"
    marker.touch()
    r = run({"HOME": str(tmp_path), "GRAPHIFY_VENV_DIR": str(venv)}, [])
    assert r.returncode == 0
    assert r.stdout.strip() == str(venv / "bin" / "python")
    assert marker.exists()          # a rebuild would have rm -rf'd the venv


def test_no_compatible_python_is_the_only_true_impossible(tmp_path):
    stubs = tmp_path / "bin"
    stubs.mkdir()                    # empty PATH dir: no python anywhere
    r = run({"HOME": str(tmp_path), "GRAPHIFY_VENV_DIR": str(tmp_path / "v")}, [stubs])
    assert r.returncode == 3
    assert "no python >= 3.10" in r.stderr


def test_bootstrap_installs_into_fresh_venv(tmp_path):
    stubs = tmp_path / "bin"
    stubs.mkdir()
    _bootstrap_python(stubs / "python3.13")
    venv = tmp_path / "engine-venv"
    r = run({"HOME": str(tmp_path), "GRAPHIFY_VENV_DIR": str(venv)}, [stubs])
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == str(venv / "bin" / "python")
    assert (venv / ".installed").exists()   # pip ran


def test_broken_venv_is_rebuilt_via_bootstrap(tmp_path):
    stubs = tmp_path / "bin"
    stubs.mkdir()
    _bootstrap_python(stubs / "python3.13")
    venv = tmp_path / "engine-venv"
    (venv / "bin").mkdir(parents=True)
    _broken_python(venv / "bin" / "python")   # half-finished install
    stale = venv / ".stale_marker"
    stale.touch()
    r = run({"HOME": str(tmp_path), "GRAPHIFY_VENV_DIR": str(venv)}, [stubs])
    assert r.returncode == 0, r.stderr
    assert not stale.exists()                 # rm -rf'd, then rebuilt
    assert (venv / ".installed").exists()
