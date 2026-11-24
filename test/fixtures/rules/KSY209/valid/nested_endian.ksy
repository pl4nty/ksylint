meta:
  id: nested_endian
  title: Test fixture
  license: CC0-1.0
seq:
  - id: one
    type: sub
types:
  sub:
    meta:
      endian: le
    seq:
      - id: x
        type: u2
