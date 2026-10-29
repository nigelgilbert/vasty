"""`rig completion` (spec §10.4).

`rig completion bash|zsh|fish` prints a completion script built from the
argument parser. The scripts call the hidden `rig completion --list KIND` to
complete lease ids and names, group names and profile names. Lease and group
names come from `~/.local/state/rig/leases.json`, read directly and tolerantly
so a missing or malformed cache yields no names.

The script prints as raw text. `--json` wraps it in `{shell, script}`.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rig.cli import Outcome, build_parser
from rig.context import Context
from rig.errors import RigError, invalid

HISTORY = frozenset({"expired", "released", "gone"})
LEASE_VERBS = ("extend", "release", "status", "tag", "sync", "ssh")
GROUP_OPTS = ("--group", "--set-group")
LEASE_OPTS = ("--on",)
PROFILE_OPTS = ("--profile",)
FILE_OPTS = ("--startup", "--sync")
SHELLS = ("bash", "zsh", "fish")


@dataclass
class CompletionResult:
    shell: str
    script: str


@dataclass
class VerbSpec:
    """Options and positional words one verb accepts."""

    name: str
    value_opts: list[str]
    bool_opts: list[str]
    words: list[str]


def _options(parser: argparse.ArgumentParser, spec: VerbSpec) -> None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for word, child in action.choices.items():
                spec.words.append(word)
                _options(child, spec)
            continue
        if action.help == argparse.SUPPRESS or not action.option_strings:
            continue
        for opt in action.option_strings:
            target = spec.bool_opts if action.nargs == 0 else spec.value_opts
            if opt not in target:
                target.append(opt)


def verb_specs() -> list[VerbSpec]:
    """Read every verb's options and sub-words from the CLI parser."""
    root = build_parser()
    specs: list[VerbSpec] = []
    for action in root._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                spec = VerbSpec(name, [], [], [])
                _options(child, spec)
                if name == "completion":
                    spec.words = list(SHELLS)
                specs.append(spec)
    return specs


def _read_cache(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    leases = data.get("leases") if isinstance(data, dict) else None
    return leases if isinstance(leases, dict) else {}


def cached_names(path: Path, kind: str) -> list[str]:
    """Return active lease ids and names, or group names, from the cache file."""
    out: list[str] = []
    for lease_id, entry in _read_cache(path).items():
        if not isinstance(entry, dict) or entry.get("state") in HISTORY:
            continue
        label = entry.get("label")
        label = label if isinstance(label, dict) else {}
        if kind == "leases":
            values = [lease_id, label.get("name")]
        else:
            values = [label.get("group")]
        for value in values:
            if isinstance(value, str) and value and value not in out:
                out.append(value)
    return sorted(out)


def _profile_names(ctx: Context) -> list[str]:
    try:
        return sorted(ctx.settings.profiles)
    except RigError:
        return []


def _fish_opt(opt: str) -> str:
    return f"-l {opt[2:]}" if opt.startswith("--") else f"-s {opt[1:]}"


def _words(items: list[str]) -> str:
    return " ".join(items)


def bash_script(specs: list[VerbSpec]) -> str:
    verbs = _words([s.name for s in specs])
    cases = []
    for s in specs:
        cases.append(
            f'    {s.name}) opts="{_words(s.value_opts + s.bool_opts)}"; '
            f'vopts="{_words(s.value_opts)}";;'
        )
    words = []
    for s in specs:
        if s.name in LEASE_VERBS:
            words.append(f'    {s.name}:0) COMPREPLY=($(compgen -W "$(_rig_names leases)" -- "$cur"));;')
        if s.words:
            pos = 1 if s.name == "sync" else 0
            words.append(f'    {s.name}:{pos}) COMPREPLY=($(compgen -W "{_words(s.words)}" -- "$cur"));;')
    return "\n".join([
        "# bash completion for rig. Load with: source <(rig completion bash)",
        "_rig_names() { command rig completion --list \"$1\" 2>/dev/null; }",
        "_rig() {",
        "  local cur prev verb opts vopts w i pos",
        '  cur="${COMP_WORDS[COMP_CWORD]}"',
        '  prev="${COMP_WORDS[COMP_CWORD-1]}"',
        "  COMPREPLY=()",
        "  if [[ $COMP_CWORD -eq 1 ]]; then",
        f'    COMPREPLY=($(compgen -W "{verbs}" -- "$cur")); return 0',
        "  fi",
        '  verb="${COMP_WORDS[1]}"',
        '  case "$prev" in',
        f'    {"|".join(GROUP_OPTS)}) COMPREPLY=($(compgen -W "$(_rig_names groups)" -- "$cur")); return 0;;',
        f'    {"|".join(LEASE_OPTS)}) COMPREPLY=($(compgen -W "$(_rig_names leases)" -- "$cur")); return 0;;',
        f'    {"|".join(PROFILE_OPTS)}) COMPREPLY=($(compgen -W "$(_rig_names profiles)" -- "$cur")); return 0;;',
        f'    {"|".join(FILE_OPTS)}) COMPREPLY=($(compgen -f -- "$cur")); return 0;;',
        "  esac",
        '  opts=""; vopts=""',
        '  case "$verb" in',
        *cases,
        "  esac",
        '  [[ " $vopts " == *" $prev "* ]] && return 0',
        '  if [[ "$cur" == -* ]]; then',
        '    COMPREPLY=($(compgen -W "$opts" -- "$cur")); return 0',
        "  fi",
        "  pos=0",
        "  for ((i=2; i<COMP_CWORD; i++)); do",
        '    w="${COMP_WORDS[i]}"',
        '    [[ "$w" == "--" ]] && return 0',
        '    if [[ "$w" == -* ]]; then',
        '      [[ " $vopts " == *" $w "* ]] && i=$((i+1))',
        "    else",
        "      pos=$((pos+1))",
        "    fi",
        "  done",
        '  case "$verb:$pos" in',
        *words,
        "  esac",
        "  return 0",
        "}",
        "complete -o default -F _rig rig",
        "",
    ])


def zsh_script(specs: list[VerbSpec]) -> str:
    verbs = _words([s.name for s in specs])
    cases = []
    for s in specs:
        cases.append(
            f"    {s.name}) opts=({_words(s.value_opts + s.bool_opts)}); "
            f"vopts=({_words(s.value_opts)});;"
        )
    words = []
    for s in specs:
        if s.name in LEASE_VERBS:
            words.append(f'    {s.name}:0) cands=(${{(f)"$(_rig_names leases)"}}); compadd -a cands;;')
        if s.words:
            pos = 1 if s.name == "sync" else 0
            words.append(f"    {s.name}:{pos}) cands=({_words(s.words)}); compadd -a cands;;")
    return "\n".join([
        "#compdef rig",
        "# zsh completion for rig. Load with: source <(rig completion zsh)",
        '_rig_names() { command rig completion --list "$1" 2>/dev/null }',
        "_rig() {",
        "  local cur prev verb w i pos",
        "  local -a cands opts vopts",
        '  cur="${words[CURRENT]}"',
        '  prev="${words[CURRENT-1]}"',
        "  if (( CURRENT == 2 )); then",
        f"    cands=({verbs}); compadd -a cands; return",
        "  fi",
        '  verb="${words[2]}"',
        '  case "$prev" in',
        f'    {"|".join(GROUP_OPTS)}) cands=(${{(f)"$(_rig_names groups)"}}); compadd -a cands; return;;',
        f'    {"|".join(LEASE_OPTS)}) cands=(${{(f)"$(_rig_names leases)"}}); compadd -a cands; return;;',
        f'    {"|".join(PROFILE_OPTS)}) cands=(${{(f)"$(_rig_names profiles)"}}); compadd -a cands; return;;',
        f'    {"|".join(FILE_OPTS)}) _files; return;;',
        "  esac",
        '  case "$verb" in',
        *cases,
        "  esac",
        "  (( ${vopts[(Ie)$prev]} )) && return",
        '  if [[ "$cur" == -* ]]; then',
        "    compadd -a opts; return",
        "  fi",
        "  pos=0",
        "  for (( i=3; i<CURRENT; i++ )); do",
        '    w="${words[i]}"',
        '    [[ "$w" == "--" ]] && { _files; return; }',
        '    if [[ "$w" == -* ]]; then',
        "      (( ${vopts[(Ie)$w]} )) && i=$((i+1))",
        "    else",
        "      pos=$((pos+1))",
        "    fi",
        "  done",
        '  case "$verb:$pos" in',
        *words,
        "    *) _files;;",
        "  esac",
        "}",
        'if [[ "${funcstack[1]}" == "_rig" ]]; then _rig "$@"; else compdef _rig rig; fi',
        "",
    ])


def fish_script(specs: list[VerbSpec]) -> str:
    all_vopts = sorted({o for s in specs for o in s.value_opts})
    lines = [
        "# fish completion for rig. Load with: rig completion fish | source",
        "function __rig_names",
        "    command rig completion --list $argv[1] 2>/dev/null",
        "end",
        "function __rig_verb",
        "    set -l tokens (commandline -opc)",
        "    test (count $tokens) -ge 2; and contains -- $tokens[2] $argv",
        "end",
        "function __rig_at",
        "    set -l tokens (commandline -opc)",
        "    test (count $tokens) -ge 2; or return 1",
        "    contains -- $tokens[2] $argv[1..-2]; or return 1",
        "    set -l rest",
        "    if test (count $tokens) -gt 2",
        "        set rest $tokens[3..-1]",
        "    end",
        "    set -l n 0",
        "    set -l skip 0",
        "    for t in $rest",
        "        if test $skip -eq 1",
        "            set skip 0",
        "        else if string match -q -- '-*' $t",
        f"            contains -- $t {_words(all_vopts)}; and set skip 1",
        "        else",
        "            set n (math $n + 1)",
        "        end",
        "    end",
        "    test $n -eq $argv[-1]",
        "end",
        "complete -c rig -f",
        f"complete -c rig -n __fish_use_subcommand -a '{_words([s.name for s in specs])}'",
    ]
    for s in specs:
        cond = f"-n '__rig_verb {s.name}'"
        for opt in s.value_opts:
            name = _fish_opt(opt)
            if opt in GROUP_OPTS:
                lines.append(f"complete -c rig {cond} {name} -x -a '(__rig_names groups)'")
            elif opt in LEASE_OPTS:
                lines.append(f"complete -c rig {cond} {name} -x -a '(__rig_names leases)'")
            elif opt in PROFILE_OPTS:
                lines.append(f"complete -c rig {cond} {name} -x -a '(__rig_names profiles)'")
            elif opt in FILE_OPTS:
                lines.append(f"complete -c rig {cond} {name} -r -F")
            else:
                lines.append(f"complete -c rig {cond} {name} -x")
        for opt in s.bool_opts:
            lines.append(f"complete -c rig {cond} {_fish_opt(opt)}")
        if s.name in LEASE_VERBS:
            lines.append(f"complete -c rig -n '__rig_at {s.name} 0' -a '(__rig_names leases)'")
        if s.words:
            pos = 1 if s.name == "sync" else 0
            lines.append(f"complete -c rig -n '__rig_at {s.name} {pos}' -a '{_words(s.words)}'")
        if s.name == "sync":
            lines.append("complete -c rig -n '__rig_verb sync' -F")
    lines.append("")
    return "\n".join(lines)


def render(shell: str) -> str:
    specs = verb_specs()
    if shell == "bash":
        return bash_script(specs)
    if shell == "zsh":
        return zsh_script(specs)
    return fish_script(specs)


def execute(ctx: Context, args: argparse.Namespace) -> Outcome:
    if args.list_kind is not None:
        if args.list_kind == "profiles":
            names = _profile_names(ctx)
        else:
            names = cached_names(ctx.state_dir / "leases.json", args.list_kind)
        ctx.stdout.write("".join(name + "\n" for name in names))
        return Outcome(None, emit=False)
    if args.shell is None:
        raise invalid("completion needs a shell.", "rig completion bash")
    script = render(args.shell)
    if args.json:
        return Outcome(CompletionResult(args.shell, script))
    ctx.stdout.write(script)
    return Outcome(None, emit=False)
