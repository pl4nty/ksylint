meta:
  id: docs
  title: Doc fixes
  license: CC0-1.0
doc: |
  A paragraph with a line that is far too long for the eighty column limit of the style guide, so it is wrapped.
  A short line stays as it is.

  * A list item that is also much too long for the limit and gets a hanging indent when wrapped.
    A continuation line of the list item that is too long as well and is wrapped with the same indent.
  1. A numbered list item that is also much too long for the limit and is wrapped as well, too.

  ```
  code in a fence is never wrapped, however long the line may get, and it gets quite long here
  ```

      indented code is never wrapped either, however long the line may get, as it gets long here

  | a table row | with cells | that is too long but must not be wrapped because it is a table |
  # A heading that is too long but must not be wrapped, because it would not be a heading anymore
  A line with a URL https://example.com/a/very/long/path/that/cannot/be/broken/anywhere/at/all/really
  Never break a line before a token that would then start a list item, such as a - this one
seq:
  - id: a
    type: u1
    doc: |
      Just one line.
  - id: b
    type: u1
    doc: "Quoted for no reason."
  - id: c
    type: u1
    doc: "Quoted: for a reason"
  - id: d
    type: u1
    doc: >
      Folded text
      on two lines.
  - id: e
    type: u1
    doc: A plain doc that continues
      on the next line.
  - id: f
    type: u1
    doc: A single-line plain doc that is longer than eighty characters and becomes a block.
  - id: g
    type: u1
    doc: "Quoted on purpose"  # ksylint: disable=KSY400
  - id: h
    type: u1
    doc: |
      A one-line literal doc that is longer than eighty characters is wrapped, not unblocked.
  - id: i
    type: u1
    doc: >
      Folded text with a line that is far too long for the limit, which is wrapped in a second round.
