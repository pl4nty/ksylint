meta:
  id: used_via_cast
  title: Test fixture
  license: CC0-1.0
seq:
  - id: one
    type: u1
instances:
  two:
    value: _root.as<sub>
    if: false
types:
  sub:
    seq:
      - id: x
        type: u1
