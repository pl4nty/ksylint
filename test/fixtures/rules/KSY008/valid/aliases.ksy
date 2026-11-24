meta:
  id: aliases
  title: Test fixture
  license: CC0-1.0
  -affected-by:
    - &first_bug 500
    - &second_bug 295
seq:
  - id: a
    type: u1
    -affected-by: *first_bug
  - id: b
    type: u1
    -affected-by:
      - *first_bug
      - *second_bug
