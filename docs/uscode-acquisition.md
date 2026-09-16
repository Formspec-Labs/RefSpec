# U.S. Code inputs

SpicyDocs fetches title ZIPs and validates each member against the title and
release point stated in its XML. RefSpec then applies its existing reference,
source-credit and section rules. A filename alone does not establish an edition.

The reference-edge tool caches each successful capture under
`xml_usc26@119-102/`, containing `archive.zip` and `capture.json`. Both files
become visible together after validation. Reuse checks the native identity,
ZIP digest and byte count against the saved HTTP evidence. Another edition
gets another directory. Old flat cache files remain untouched and are not read.
An incomplete or conflicting capture stops the run.

The saved timestamp describes the original HTTP observation. Rehashing cached
bytes does not authenticate a publisher or prove an unrecorded history. Existing
extraction receipts keep their URL, ZIP/member sizes and hexadecimal digests.

Whole-Code and annual builds use shared archive callbacks with a 128 MiB
compressed bound, 128 MiB per member and 1 GiB total expansion. They process one
member at a time and publish results only after all selected inputs succeed.
Source-credit output keeps sorted member order. Section candidates keep original
archive member order, explicit release selection and RefSpec's annual-year policy.

The frozen checks and deliberate stricter refusals are in
`tests/test_uscode_acquisition_shared.py` and `tests/test_build_usc_structure.py`.
