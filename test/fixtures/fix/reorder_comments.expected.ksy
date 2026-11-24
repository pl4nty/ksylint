meta:
  id: reorder_comments
  title: Reorder test
  license: CC0-1.0
seq:
  # the first field
  - id: one # trailing comment
    type: u1
    doc: |
      # not a comment, part of the doc
      Doc text.

  - id: two
    size: 4
    # about the type
    type: str
    encoding: ASCII

instances:
  three:
    value: 3
types:
  sub:
    seq:
      - id: x
        type: u1
