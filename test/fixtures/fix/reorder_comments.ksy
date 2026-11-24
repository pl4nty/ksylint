seq:
  # the first field
  - type: u1
    id: one # trailing comment
    doc: |
      # not a comment, part of the doc
      Doc text.

  - size: 4
    # about the type
    type: str
    id: two
    encoding: ascii
meta:
  title: Reorder test
  id: reorder_comments
  license: CC0-1.0

types:
  sub:
    seq:
      - id: x
        type: u1
instances:
  three:
    value: 3
