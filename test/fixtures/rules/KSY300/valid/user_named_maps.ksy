meta:
  id: user_named_maps
  title: Test fixture
  license: CC0-1.0
doc: |
  User-named maps (types, instances, enums, enum values, cases) are never
  key-ordered, even if their names look like spec keys.
seq:
  - id: one
    type: seq
    enum: type
  - id: two
    type:
      switch-on: one
      cases:
        type::size: doc
        type::id: seq
instances:
  type:
    value: 1
  size:
    value: 2
  doc:
    value: 3
enums:
  type:
    2: size
    1: id
types:
  seq:
    seq:
      - id: x
        type: u1
  doc:
    seq:
      - id: y
        type: u1
