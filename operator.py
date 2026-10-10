# /// script
# requires-python = ">=3.11"
# dependencies = ["tomlkit>=0.13"]
# ///
"""herdr-operator: push managed herdr + tmux config to local and remote hosts.

  operator.py status [host...]   one-line sync state per host
  operator.py diff   [host...]   unified diff of pending changes
  operator.py apply  [host...]   write changes (backs up the old file)
"""
import difflib
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

import tomlkit

ROOT = Path(__file__).parent
MARK = "# herdr-operator:managed"
TMUX_HEADER = "# Managed by herdr-operator - local edits will be overwritten.\n"
HERDR_PATH = "$HOME/.config/herdr/config.toml"


class Host:
    def __init__(self, name, cfg):
        self.name = name
        self.local = cfg.get("local", False)
        self.ssh = cfg.get("ssh", name)
        self.herdr = cfg.get("herdr", True)
        self.tmux = cfg.get("tmux", True)

    def sh(self, script, stdin=None):
        cmd = ["sh", "-c", script] if self.local else ["ssh", "-o", "BatchMode=yes", self.ssh, script]
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stderr.strip() or f"exit {r.returncode}")
        return r.stdout

    def read(self, path):
        return self.sh(f'cat "{path}" 2>/dev/null || true')

    def write(self, path, content):
        p = f'"{path}"'
        self.sh(
            f'mkdir -p "$(dirname {p})" && {{ [ -f {p} ] && cp {p} {p}.operator-bak; true; }} '
            f"&& cat > {p}.tmp && mv {p}.tmp {p}",
            stdin=content,
        )

    def tmux_path(self):
        out = self.sh("tmux -V 2>/dev/null || true").strip()  # e.g. "tmux 3.4", "tmux next-3.5"
        digits = "".join(c if c.isdigit() or c == "." else " " for c in out).split()
        try:
            ver = tuple(int(x) for x in digits[0].split(".")[:2]) if digits else (3, 2)
        except ValueError:
            ver = (3, 2)
        # tmux reads ~/.config/tmux/tmux.conf since 3.2
        return "$HOME/.config/tmux/tmux.conf" if ver >= (3, 2) else "$HOME/.tmux.conf"


def strip_owned(text):
    """Remove marker lines and the [[keys.command]] table following each."""
    out, state = [], None  # state: None | "header" | "body"
    for line in text.splitlines(keepends=True):
        s = line.strip()
        if s == MARK:
            state = "header"
            continue
        if state == "header":
            state = "body"  # the [[keys.command]] line itself
            continue
        if state == "body":
            if s.startswith("["):
                state = None
            else:
                continue
        out.append(line)
    return "".join(out).rstrip("\n")


def render_herdr(current):
    managed_text = (ROOT / "herdr/managed.toml").read_text()
    managed = tomllib.loads(managed_text)
    commands = managed.get("keys", {}).get("command", [])

    doc = tomlkit.parse(strip_owned(current))

    def merge(dst, src):
        for k, v in src.items():
            if k == "command" and dst is doc.get("keys", None) and isinstance(v, list):
                continue
            if isinstance(v, dict):
                if k not in dst:
                    dst[k] = tomlkit.table()
                merge(dst[k], v)
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                continue
            else:
                dst[k] = v

    merge(doc, {k: v for k, v in managed.items()})
    body = tomlkit.dumps(doc).rstrip("\n")

    blocks = []
    for c in commands:
        blocks.append(MARK + "\n[[keys.command]]\n" + "".join(f"{k} = {tomlkit.item(v).as_string()}\n" for k, v in c.items()))
    result = body + ("\n\n" if body else "") + "\n".join(blocks)
    tomllib.loads(result)  # must stay valid
    return result.rstrip("\n") + "\n"


def plan(host):
    items = []
    if host.herdr:
        cur = host.read(HERDR_PATH)
        items.append(("herdr", HERDR_PATH, cur, render_herdr(cur)))
    if host.tmux:
        path = host.tmux_path()
        new = TMUX_HEADER + (ROOT / "tmux/tmux.conf").read_text()
        items.append(("tmux", path, host.read(path), new))
    return items


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("status", "diff", "apply"):
        sys.exit(__doc__)
    cmd, wanted = sys.argv[1], set(sys.argv[2:])
    hosts_file = ROOT / "hosts.toml"
    if not hosts_file.exists():
        sys.exit("hosts.toml missing - copy hosts.example.toml")
    hosts = [Host(n, c) for n, c in tomllib.loads(hosts_file.read_text()).get("hosts", {}).items()]
    hosts = [h for h in hosts if not wanted or h.name in wanted]
    if wanted - {h.name for h in hosts}:
        sys.exit(f"unknown host(s): {', '.join(sorted(wanted - {h.name for h in hosts}))}")

    failed = False
    for h in hosts:
        try:
            for what, path, cur, new in plan(h):
                tag = f"{h.name:<12} {what:<6}"
                if cur == new:
                    print(f"{tag} in sync")
                    continue
                if cmd == "status":
                    print(f"{tag} DRIFT ({'new file' if not cur else 'changed'})")
                elif cmd == "diff":
                    print(f"{tag} {path}")
                    sys.stdout.writelines(difflib.unified_diff(
                        cur.splitlines(True), new.splitlines(True), "current", "managed"))
                else:
                    h.write(path, new)
                    print(f"{tag} updated")
        except Exception as e:  # keep going on other hosts
            failed = True
            print(f"{h.name:<12} ERROR {e}", file=sys.stderr)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
