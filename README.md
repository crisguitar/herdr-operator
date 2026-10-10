# herdr-operator

Keeps herdr and tmux config in sync across my machines (this Mac + Linux boxes over ssh).

- `herdr/managed.toml` – settings enforced in `~/.config/herdr/config.toml`. Plain keys are set in place; `[[keys.command]]` entries are owned by the operator (tagged `# herdr-operator:managed`, replaced on each apply). Everything else in the host's file is left alone.
- `tmux/tmux.conf` – owned whole-file; written to `~/.config/tmux/tmux.conf` (tmux >= 3.2) or `~/.tmux.conf`.
- `hosts.toml` – gitignored; copy `hosts.example.toml`. Hosts are ssh aliases; `local = true` for this machine.

```
mise install
mise run status            # which hosts drifted
mise run diff [host...]    # what would change
mise run apply [host...]   # write it (previous file kept as *.operator-bak)
```
