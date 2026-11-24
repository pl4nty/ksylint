<h1 align="center">ksylint</h1>

<p align="center">Lint and auto-format Kaitai Struct <code>.ksy</code> files according to the
<a href="https://doc.kaitai.io/ksy_style_guide.html">official KSY style guide</a>.</p>

<p align="center">
 <a href="https://github.com/pl4nty/ksylint/actions/workflows/ci.yml"><img src="https://github.com/pl4nty/ksylint/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
</p>

ksylint checks `.ksy` files for

- **file layout**: UTF-8, LF line endings, trailing newline, a single implicit
  YAML document, 2-space indentation, indented sequences, `- id: ...` map items;
- **schema** validity against the current
  [official KSY JSON schema](https://github.com/kaitai-io/ksy_schema)
  and canonical encoding names;
- **meta section** conventions: `meta/id` matches the file name, a title,
  a valid SPDX `license`, `file-extension` style, sorted `xref` and `tags`,
  no top-level-only or reserved keys in nested meta sections;
- **key order** of type specs, meta sections, attributes, instances,
  parameters, enum values and switch types (never of user-named maps such as
  the keys of `types`, `instances` or `enums`);
- **documentation**: plain single-line docs, `|` literal multi-line docs,
  80-column wrapping, `https` URLs in `doc-ref`/`xref`;
- **naming and references**: `lower_snake_case` identifiers, unused types and
  enums;
- optionally, everything **kaitai-struct-compiler** reports (`--compile`).

Most layout and ordering problems can be fixed automatically with `--fix`.

## Installation

```sh
pip install ksylint
# or the development version
pip install git+https://github.com/pl4nty/ksylint
```

ksylint needs Python 3.10 or newer.

## Usage

```sh
ksylint hello_world.ksy            # lint files
ksylint formats/                   # lint every *.ksy below a directory
ksylint --fix formats/             # apply safe autofixes in place
ksylint --diff formats/            # show what --fix would change
ksylint --list-rules               # show all rules
cat foo.ksy | ksylint - --stdin-filename foo.ksy
```

Example output:

```text
image/foo.ksy:12:5: error [KSY302 attribute-key-order] attribute key order: `size` should come before `type` (expected order: id, size, type, encoding)
image/foo.ksy:14:15: error [KSY101 encoding-name] use canonical encoding name `ASCII` instead of `ascii`
Found 2 problems (2 errors) in 1 of 1 file. 2 fixable with `--fix`.
```

Useful options:

| Option | Meaning |
|--------|---------|
| `--format text\|json\|sarif\|github` | Output format. `github` prints [workflow annotations](https://docs.github.com/actions/using-workflows/workflow-commands-for-github-actions) (`::error file=...,line=...::...`), `sarif` is SARIF 2.1.0 for code scanning. |
| `--select RULES` | Only run these rules (comma-separated IDs, ID prefixes such as `KSY3`, rule names, or `ALL`). |
| `--extend-select RULES` | Enable rules in addition to the defaults. |
| `--ignore RULES` | Disable rules. |
| `--fail-on error\|warning\|info` | Lowest severity that makes ksylint exit with status 1 (default `warning`). |
| `--exit-zero` | Always exit with 0. |
| `--statistics` | Print per-rule counts. |
| `--config FILE` / `--isolated` | Use a specific config file / ignore config files. |
| `--compile`, `--ksc PATH`, `-I DIR` | Also run kaitai-struct-compiler and report its errors and warnings. |

Exit status: `0` no problems (at or above `--fail-on`), `1` problems found
(or, with `--diff`, changes pending), `2` usage or configuration error.

## Autofix

`ksylint --fix` repairs:

- BOM, CRLF/CR line endings, missing or extra trailing newlines;
- `---` document markers and `%YAML`/`%TAG` directives;
- indentation: 2 spaces, indented block sequences, exactly one space after
  `-`, the first key of a map on the `-` line, block scalar indentation;
- key order of spec objects (`KSY300`–`KSY306`), `xref` key order and `tags`
  order;
- non-canonical encoding names (`ascii` → `ASCII`, `utf8` → `UTF-8`,
  `cp437` → `IBM437`, ...).

Fixes are surgical, line-based edits computed from YAML node positions:
comments travel with the keys they precede, and quoting, flow collections,
alignment and blank lines are left alone. After every step the file is
re-parsed and the loaded data is compared with the data before the step; a
step that would change anything else is discarded. Fixing is idempotent.

Only enabled rules are fixed: a rule that is ignored, or disabled with a
`# ksylint: disable-file` comment, is left alone. The indentation rules
`KSY007`–`KSY009` are fixed in one pass, which is skipped if it would also
"fix" one of them that is disabled. Line-level `disable` comments only silence
the diagnostic.

## Configuration

ksylint reads `.ksylint.toml` (top-level keys) or the `[tool.ksylint]` table
of `pyproject.toml`, searching upwards from the current directory.

```toml
[tool.ksylint]
select = ["ALL"]               # default: all rules except the compiler ones
ignore = ["KSY600", "KSY601"]  # rule IDs, ID prefixes or rule names
fail-on = "error"              # error | warning | info
exclude = ["_build/**"]        # glob patterns, relative to the given directory
compile = false                # run kaitai-struct-compiler (KSY900/KSY901)
ksc = "kaitai-struct-compiler"
ksc-target = "python"
import-paths = ["."]           # for --compile; default: the repository root

[tool.ksylint.severity]        # keys: rule IDs, ID prefixes or rule names
KSY402 = "info"

[tool.ksylint.rules.doc-line-length]
max-length = 100
```

Problems can also be silenced inline:

```yaml
doc: "Quoted on purpose"  # ksylint: disable=KSY400
# ksylint: disable-next-line=doc-line-length
doc: A very long line ...
# ksylint: disable-file=KSY600,KSY601
```

The rule list is comma-separated (IDs or names; without a list, all rules are
disabled) and may be followed by an explanation.

## Rules

Severities are defaults and can be changed per rule. Rules marked "yes" are
fixed by `--fix`.

<!-- rules-table:start (generated by scripts/gen_rule_table.py) -->

#### File format and layout

| ID | Name | Severity | Fix | Description |
|----|------|----------|:---:|-------------|
| `KSY001` | `utf8-encoding` | error | yes | File must be UTF-8 encoded, without a byte order mark. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#general)) |
| `KSY002` | `line-endings` | error | yes | Lines must end with LF (Unix line endings), not CRLF or CR. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#general)) |
| `KSY003` | `trailing-newline` | error | yes | File must end with a single newline character. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#general)) |
| `KSY004` | `single-document` | error | yes | Single implicit YAML document: no `---` marker, no `%YAML`/`%TAG` directives, no `...`. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#general)) |
| `KSY005` | `yaml-syntax` | error |  | File must be well-formed YAML with a mapping at the top level. |
| `KSY006` | `duplicate-key` | error |  | Mapping keys must be unique. |
| `KSY007` | `indentation` | error | yes | Use 2-space indentation (and exactly one space after `-`). ([style guide](https://doc.kaitai.io/ksy_style_guide.html#general)) |
| `KSY008` | `sequence-indent` | error | yes | Block sequences must be indented relative to their parent key. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#general)) |
| `KSY009` | `seq-map-first-key` | error | yes | A map inside a sequence must start on the `-` line (`- id: foo`). ([style guide](https://doc.kaitai.io/ksy_style_guide.html#general)) |
| `KSY010` | `block-style` | info |  | Prefer block style over flow style for maps (`{ ... }`). ([style guide](https://doc.kaitai.io/ksy_style_guide.html#general)) |
| `KSY011` | `file-name` | error |  | File name must end with `.ksy`. |

#### Schema

| ID | Name | Severity | Fix | Description |
|----|------|----------|:---:|-------------|
| `KSY100` | `schema` | error |  | File must validate against the official KSY JSON schema. |
| `KSY101` | `encoding-name` | error | yes | Use canonical, byte-order-explicit encoding names (e.g. `UTF-8`, `ASCII`, `UTF-16LE`). ([style guide](https://doc.kaitai.io/ksy_style_guide.html#encoding-name)) |
| `KSY102` | `ineffective-pad-right` | warning |  | `pad-right` has no effect without `size` or `size-eos: true`. |
| `KSY103` | `strz-terminator` | warning |  | `type: strz` already implies `terminator: 0`; use `type: str` for other terminators. |

#### Meta section

| ID | Name | Severity | Fix | Description |
|----|------|----------|:---:|-------------|
| `KSY200` | `meta-id` | error |  | The top-level type must have `meta/id`. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#meta)) |
| `KSY201` | `meta-id-filename` | error |  | `meta/id` must match the file name (without `.ksy`). ([style guide](https://doc.kaitai.io/ksy_style_guide.html#meta)) |
| `KSY202` | `meta-human-info` | error |  | Top-level meta must have at least one of title, application, file-extension, xref, tags. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#meta)) |
| `KSY203` | `license-missing` | warning |  | Top-level meta should declare a `license`. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#meta)) |
| `KSY204` | `license-spdx` | error |  | `meta/license` must be a valid SPDX license expression. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#meta)) |
| `KSY205` | `license-canonical` | warning |  | Use the current, canonical SPDX identifier (e.g. `GPL-2.0-only`, not deprecated `GPL-2.0`). ([style guide](https://doc.kaitai.io/ksy_style_guide.html#meta)) |
| `KSY206` | `file-extension-style` | error |  | `file-extension`: a string if there is one, a block sequence if there are several. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#meta)) |
| `KSY207` | `xref-order` | error | yes | Keys inside `meta/xref` must be in alphabetical order. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#meta)) |
| `KSY208` | `tags-order` | error | yes | Values inside `meta/tags` must be in alphabetical order. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#meta)) |
| `KSY209` | `nested-meta-keys` | error |  | Nested (non-top-level) meta sections may only set encoding, endian and bit-endian. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#meta)) |
| `KSY210` | `reserved-keys` | error |  | `ks-debug` and `ks-opaque-types` are reserved for internal use. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#meta)) |

#### Key order

| ID | Name | Severity | Fix | Description |
|----|------|----------|:---:|-------------|
| `KSY300` | `type-key-order` | error | yes | Sections of a type spec must follow the style guide order. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#type)) |
| `KSY301` | `meta-key-order` | error | yes | Keys of a meta section must follow the style guide order. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#meta)) |
| `KSY302` | `attribute-key-order` | error | yes | Keys of a sequence attribute must follow the style guide order. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#seq-attr)) |
| `KSY303` | `instance-key-order` | error | yes | Keys of an instance must follow the style guide order. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#inst-attr)) |
| `KSY304` | `param-key-order` | warning | yes | Keys of a parameter spec should be ordered id, type, enum, doc, doc-ref. |
| `KSY305` | `enum-value-key-order` | warning | yes | Keys of an enum value spec should be ordered id, -orig-id, doc, doc-ref. |
| `KSY306` | `switch-key-order` | warning | yes | A switch type should list `switch-on` before `cases`. |

#### Documentation

| ID | Name | Severity | Fix | Description |
|----|------|----------|:---:|-------------|
| `KSY400` | `doc-single-line` | warning |  | Single-line docs should be plain unquoted scalars. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#doc)) |
| `KSY401` | `doc-multi-line` | warning |  | Multi-line docs should use the literal block style (`doc: \|`). ([style guide](https://doc.kaitai.io/ksy_style_guide.html#doc)) |
| `KSY402` | `doc-line-length` | warning |  | Wrap doc lines at 80 columns. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#doc)) Options: `max-length` (default `80`). |
| `KSY403` | `insecure-url` | warning |  | Prefer `https://` URLs in doc-ref and xref. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#doc-ref)) |
| `KSY404` | `malformed-url` | warning |  | URLs in doc-ref and xref must be well-formed (`URL description`). ([style guide](https://doc.kaitai.io/ksy_style_guide.html#doc-ref)) |
| `KSY405` | `trivial-doc` | info |  | `doc` should not just repeat the attribute id. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#seq-attr)) |
| `KSY406` | `trailing-padding` | info |  | Do not read trailing padding just to consume the rest of a substream. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#seq-attr)) |

#### Naming

| ID | Name | Severity | Fix | Description |
|----|------|----------|:---:|-------------|
| `KSY500` | `identifier-case` | error |  | Identifiers (ids, type, enum and instance names) must be lower_snake_case. ([style guide](https://doc.kaitai.io/ksy_style_guide.html#attr-id)) |

#### References

| ID | Name | Severity | Fix | Description |
|----|------|----------|:---:|-------------|
| `KSY600` | `unused-type` | warning |  | Types that are defined but never referenced. |
| `KSY601` | `unused-enum` | warning |  | Enums that are defined but never referenced. |

#### Compiler

| ID | Name | Severity | Fix | Description |
|----|------|----------|:---:|-------------|
| `KSY900` | `ksc-error` | error |  | Errors reported by kaitai-struct-compiler (only with `--compile`). *Off by default.* |
| `KSY901` | `ksc-warning` | warning |  | Warnings reported by kaitai-struct-compiler (only with `--compile`). *Off by default.* |

<!-- rules-table:end -->

## pre-commit

```yaml
repos:
  - repo: https://github.com/pl4nty/ksylint
    rev: v1.0.0  # or a commit SHA
    hooks:
      - id: ksylint      # lint only
      # - id: ksylint-fix  # fix, then lint
```

## GitHub Action

```yaml
jobs:
  ksylint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pl4nty/ksylint@v1  # or a commit SHA
        with:
          paths: .                       # files or directories
          args: --ignore KSY600,KSY601   # extra CLI arguments
          # format: github               # inline annotations (default)
          # sarif-file: ksylint.sarif    # also write SARIF for code scanning
```

## Library API

```python
import ksylint

diags = ksylint.lint_text(text, "foo.ksy")  # list[ksylint.Diagnostic]
for d in diags:
    print(d.line, d.column, d.rule_id, d.severity, d.message, d.path)

fixed = ksylint.fix_text(text, "foo.ksy").text  # autofix

cfg = ksylint.Config(select=["KSY3"], severity={"KSY302": "warning"})
ksylint.lint_text(text, "foo.ksy", config=cfg)
```

`lint_text` and `fix_text` are pure functions: they take the file contents
(`str` or `bytes`) and never touch the file system or network, so they can
back an editor integration or language server, including in the browser via
Pyodide (for example in VS Code for the Web). The file name is only used for
reporting and for the `meta/id` / `.ksy` file-name checks; pass `None` to skip
them. Each `Diagnostic` has `file`, 1-based `line`/`column` (plus
`end_line`/`end_column` where known), `rule_id`, `rule_name`, `severity`,
`message`, `path` (a JSON-pointer-like YAML path such as
`/types/header/seq/2/type`), `fixable` and `url` (style guide section).

## Development

```sh
pip install -e ".[dev]"
pytest                                   # tests
ruff check . && ruff format --check .    # lint
python scripts/gen_rule_table.py         # refresh the rule table above
python scripts/update_schema.py          # refresh the vendored KSY schema
KSYLINT_FORMATS_DIR=../kaitai_struct_formats pytest test/test_integration.py
```

Rules live in `ksylint/rules/`; each is a function registered with
`@rule(id, name, severity, summary, anchor=..., fixable=...)`. Add a
`test/fixtures/rules/<ID>/invalid/*.ksy` fixture (and ideally a `valid/` one)
for every new rule.

The vendored schema and its provenance are described in
[`ksylint/data/README.md`](ksylint/data/README.md).

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
