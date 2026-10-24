# security.md

The layered security model for running LLM-written analysis code, and
what each layer is actually responsible for.

## The two layers

1. **The static checker** (`src/sandbox_analyst/guard/`) — an AST-only
   pass over the model's script before it ever runs. It never executes,
   compiles-to-run, or imports the code it checks. Its job is **fast,
   cheap repair feedback**: catching obviously-bad code before paying
   for a sandbox spin-up, with error messages the model can act on.

2. **The Modal sandbox** (`src/sandbox_analyst/sandbox/`) — gVisor
   isolation, `block_network=True` (no outbound traffic, including
   DNS), a memory/CPU limit, and a wall-clock timeout, confirmed live
   in `docs/sandbox-env.md`. This is the **actual security boundary**.
   Nothing about the checker is relied on for safety; it is defense in
   depth only (D-009).

This split matters because an AST checker can always be bypassed by
sufficiently clever Python — see "Known bypasses" below — and treating
it as the security boundary would be a false sense of safety. Each
layer was red-teamed with the other disabled: the checker tests
(`tests/guard/`) call `check()` directly with no sandbox involved; the
sandbox tests (`tests/sandbox/test_modal_live.py`) run code with no
checker in front of it, including code that would fail the checker
(e.g. the network/OOM/timeout probes).

## What the checker blocks

| Rule | Blocks |
|---|---|
| `SYNTAX` | Code that doesn't parse at all (reported with a line number so the model can repair it) |
| `IMPORT_NOT_ALLOWED` | Any import whose top-level root isn't on the allowlist (`policy.ALLOWED_IMPORT_ROOTS`); all relative imports |
| `FORBIDDEN_CALL` | Bare references (not just calls) to `eval`, `exec`, `compile`, `__import__`, `getattr`, `setattr`, `delattr`, `globals`, `locals`, `vars`, `breakpoint`, `input`, `help`, `exit`, `quit` |
| `DUNDER_ACCESS` | Any name or attribute of the form `__x__` |
| `FORBIDDEN_ATTRIBUTE` | Denylisted names (`os`, `sys`, `subprocess`, `socket`, `shutil`, `ctypes`, `builtins`, `importlib`, `system`, `popen`, `remove`, `rmtree`, ... — full list in `policy.py`) anywhere in a name or attribute chain |
| `UNSAFE_WRITE` | `open()` in a write mode, or a known writer method (`to_csv`, `savefig`, ...), unless called with no path at all or a literal path inside `/work` |
| `PICKLE` | `read_pickle`; `allow_pickle=True` (or a non-literal value for it) |

The import allowlist grows only on false-positive evidence from real
dev tasks, logged in `DECISIONS.md` (D-010). Reads are allowed from
anywhere (not just `/work`) because the sandbox holds no secrets; only
writes are path-restricted.

## Known static-checker bypasses (contained by the sandbox)

Found by deliberately red-teaming `check()` in isolation. Each is
captured as an `xfail(strict=True)` test in
`tests/guard/test_bypass_hunt.py` so it can't silently regress or
silently get "fixed" without this doc being updated.

### 1. Format-string attribute traversal

```python
"{0.__class__.__bases__[0].__subclasses__()}".format(object())
```

`str.format()` interprets `{0.__class__...}` itself, at runtime, using
its own mini format-language — the dangerous names never appear as a
real `ast.Attribute`/`ast.Name` node, only as *characters inside a
string literal*. The checker only inspects actual AST nodes, so this is
invisible to `DUNDER_ACCESS`.

**Why not closed:** The only way to catch this at the AST layer is to
scan string literal *contents* for dunder-looking substrings, which
would false-positive on completely benign strings (docstrings, column
names, regex patterns, anything that happens to contain `__`). Not
worth the false-positive rate for something the sandbox already
contains — reaching a class object inside the sandbox's own process
grants no privilege beyond what that process already has, and there's
no network to exfiltrate anything over.

### 2. Aliasing the `open` builtin

```python
o = open
o("/etc/passwd", "w")
```

`UNSAFE_WRITE`'s `open()`-specific check matches on the call's function
being the literal name `open`. Assigning `open` to another name and
calling through that alias produces a call whose `func` is a different
`ast.Name`, which the rule doesn't recognize.

**Why not closed:** Closing this generally requires either (a) alias
tracking (a real dataflow pass, well beyond "AST-only, fast feedback"),
or (b) flagging any two-argument call with two string-literal arguments
regardless of function name, which would false-positive constantly
(e.g. `re.sub("a", "wax", text)` — two string literals, nothing to do
with file writes). Again, the sandbox's own filesystem is not
sensitive (no secrets live there, and the only destination that
matters, `/work`, is where the agent's own evidence already lives), so
a successful bypass here still can't exfiltrate anything — there's no
network, and the attempted destination is either inside the already-
visible `/work` or vanishes along with the sandbox at `terminate()`.

Both bypasses share a property worth naming: neither one, if it
succeeded, would let code do anything the sandbox doesn't already
allow a cooperative script to do (write inside its own ephemeral
filesystem, introspect its own objects). They're checker gaps, not
sandbox escapes.
