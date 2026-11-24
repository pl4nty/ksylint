meta:
  id: custom_process
  title: Test fixture
  license: CC0-1.0
seq:
  - id: a
    size: 4
    process: kaitai.compress.zlib(15, "raw")
  - id: b
    size: 4
    process: kaitai.compress.lz4
  - id: c
    size: 4
    process: rot(5, 2)
  - id: d
    size: 4
    process: util.custom_arc4.custom_arc4([0xA7, 0xBF, 0x73, 0xA0,
                                           0x85, 0x6F, 0x00, 0x80])
  - id: e
    size: 4
    process: xor(0x55)
  - id: f
    size: 4
    process: zlib
