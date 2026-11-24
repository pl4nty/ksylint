meta:
    id: indentation
    title: Indentation test
    license: CC0-1.0
doc: |
    Over-indented doc.
      Keeps relative indentation.
seq:
- id: one
  type: u1
-
  id: two
  type:
      switch-on: one
      cases:
          1: u1
          _: u2
-   id: three
    contents: [1, 2]
