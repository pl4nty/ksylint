meta:
  id: nested_title
  title: Test fixture
  license: CC0-1.0
seq:
  - id: one
    type: sub
types:
  sub:
    meta:
      title: Not here
      endian: le
    seq:
      - id: x
        type: u2
