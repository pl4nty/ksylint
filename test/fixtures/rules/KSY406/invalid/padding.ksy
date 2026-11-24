meta:
  id: padding
  title: Test fixture
  license: CC0-1.0
seq:
  - id: header
    size: 64
    type: block
types:
  block:
    seq:
      - id: param1
        type: u4
      - id: padding
        size-eos: true
