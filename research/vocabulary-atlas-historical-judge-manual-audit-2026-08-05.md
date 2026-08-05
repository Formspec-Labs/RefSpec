# Vocabulary Atlas historical judge manual audit

Date: 2026-08-05

Status: independent blind decisions recorded before opening the model-answer
key. This audit makes no provider call and changes no qualification artifact.

The input is the 108-row English sample at
`/tmp/refspec-candidate-benchmark.ANhNrc/judge-audit-blind-108.json`, digest
`sha256:20eb9b423284f10dd4a99e003c93101c34a0fd6bc24583951ac4ba85eafed1ff`.
The sample contains six deterministic rows from every combination of three
vocabulary pairs and six historical generation classes. It withholds the
generation class, control flag, model answers, qualification disposition, and
admitted relation.

I applied the same search-expansion rubric used by the two model families:
`same`, `near_same`, `target_is_broader`, `target_is_narrower`, `related`,
`unrelated`, or `insufficient_evidence`. `related` means a direct, useful
association; it grants no default traversal.

| Row | Audit ID | Independent verdict |
| ---: | --- | --- |
| 1 | `audit-1081c08326d2eb9900f2` | `unrelated` |
| 2 | `audit-2218e52bf9e2983362a1` | `same` |
| 3 | `audit-cf073f50d6e5cfbe6417` | `target_is_broader` |
| 4 | `audit-4c97c6dd608fc202015c` | `target_is_narrower` |
| 5 | `audit-5fa422b236c87652e815` | `target_is_broader` |
| 6 | `audit-aea7c5a475b7c88febbc` | `unrelated` |
| 7 | `audit-257c70bcb2159a71c4c7` | `unrelated` |
| 8 | `audit-0dbd2af44b6406b8131d` | `same` |
| 9 | `audit-ea78d5cf55f97039621a` | `unrelated` |
| 10 | `audit-efb8fbedb916b2b9e6cb` | `related` |
| 11 | `audit-56b3ebb3051c503791a0` | `unrelated` |
| 12 | `audit-8fdb1a484e086a1b671f` | `same` |
| 13 | `audit-b4bf3e4008813f5ccf28` | `target_is_narrower` |
| 14 | `audit-e1077c2e9ab99ded3036` | `related` |
| 15 | `audit-a9429f9aa7cce131cb86` | `related` |
| 16 | `audit-f290f1258c4942716f94` | `related` |
| 17 | `audit-c12691e21374acd64a93` | `target_is_narrower` |
| 18 | `audit-1b524c39be725f6afffb` | `unrelated` |
| 19 | `audit-d652c809dd09e66b8386` | `unrelated` |
| 20 | `audit-8428606b09a7097418b3` | `unrelated` |
| 21 | `audit-bcad3e6624d7c1d12a6c` | `target_is_broader` |
| 22 | `audit-3b416158fbb8bcab4c84` | `target_is_narrower` |
| 23 | `audit-7c2a3f1cc98c86ae79f8` | `unrelated` |
| 24 | `audit-c36db7c5137a0c651052` | `same` |
| 25 | `audit-c8a0b9924425552097bd` | `related` |
| 26 | `audit-700c10498a38a70a9daf` | `target_is_broader` |
| 27 | `audit-03e4f2783644d2034ef9` | `unrelated` |
| 28 | `audit-5ebccd30fe813f1b91e4` | `target_is_narrower` |
| 29 | `audit-fa9f969c6bc6ba6cd2f9` | `unrelated` |
| 30 | `audit-9e680ee2d231bd24bf2b` | `target_is_broader` |
| 31 | `audit-2fdd00ffda35c16be7ac` | `unrelated` |
| 32 | `audit-cae0a1083cf36c39df09` | `same` |
| 33 | `audit-4470d6ce283f7dbd9333` | `unrelated` |
| 34 | `audit-e46ef761a3fd647867ee` | `near_same` |
| 35 | `audit-3fb0609a04cf3004314e` | `related` |
| 36 | `audit-9462a2580cf25ebba8b6` | `target_is_narrower` |
| 37 | `audit-c5e55b6970cb556f616a` | `related` |
| 38 | `audit-b824eb73425c91285468` | `unrelated` |
| 39 | `audit-f59d95a5248fdf97e211` | `near_same` |
| 40 | `audit-af930740946406802dea` | `related` |
| 41 | `audit-96ac83c56ee7d8f38394` | `unrelated` |
| 42 | `audit-e9b8a1874afd88629b75` | `same` |
| 43 | `audit-cafc5846216360e0d903` | `unrelated` |
| 44 | `audit-12ce1b9d28a48f1bbd13` | `same` |
| 45 | `audit-b2c1099777ac5a07e607` | `unrelated` |
| 46 | `audit-8cd0698e4953ee695ede` | `target_is_narrower` |
| 47 | `audit-e81019ccf8f76d8f6b15` | `unrelated` |
| 48 | `audit-541181cf72289c20ea7c` | `same` |
| 49 | `audit-b2164b82560034191cb5` | `unrelated` |
| 50 | `audit-d232da4798e1dfb0299d` | `unrelated` |
| 51 | `audit-fff1270f25a0b5ffeabb` | `unrelated` |
| 52 | `audit-7149fa75d19879fb63a1` | `target_is_narrower` |
| 53 | `audit-be2fc1d74fec78db0e11` | `unrelated` |
| 54 | `audit-563ba04b8da44053ccab` | `target_is_narrower` |
| 55 | `audit-91b319e9c7d45c714b4b` | `same` |
| 56 | `audit-8a209b2d5e197027f69e` | `unrelated` |
| 57 | `audit-2aabe4a775c87d179396` | `related` |
| 58 | `audit-6521b8c0121d2d83849c` | `target_is_narrower` |
| 59 | `audit-625dd46a6988f66b29a7` | `target_is_broader` |
| 60 | `audit-383c7491e3ae31c9ff3e` | `same` |
| 61 | `audit-d56d288c55d6b1239c95` | `target_is_broader` |
| 62 | `audit-3b33347ca12e72799033` | `unrelated` |
| 63 | `audit-276ffc65fae988466fbb` | `same` |
| 64 | `audit-1250a28d5c3d23a25886` | `related` |
| 65 | `audit-e7e68f822c2c28047bb5` | `same` |
| 66 | `audit-fec2438c7f7b9832e55d` | `same` |
| 67 | `audit-779c1813af0a8ce44168` | `related` |
| 68 | `audit-bfe270048a87f49d34c2` | `target_is_broader` |
| 69 | `audit-a7ea5979933d4efbf4b9` | `target_is_narrower` |
| 70 | `audit-8a26602b8681dc712bf5` | `same` |
| 71 | `audit-97289cfa41cc01d5140a` | `unrelated` |
| 72 | `audit-859f59c0e78bfda530ef` | `related` |
| 73 | `audit-99b734aee6044cda1dbf` | `unrelated` |
| 74 | `audit-50db6fca4ca2e4fa8a04` | `related` |
| 75 | `audit-925831138eb3c788cfde` | `unrelated` |
| 76 | `audit-f6dc5dc4331b2e31eb57` | `unrelated` |
| 77 | `audit-6664204545d3a4f3ac4f` | `target_is_broader` |
| 78 | `audit-171c93f9ffd62b061178` | `unrelated` |
| 79 | `audit-50281902665cd4fdf0b1` | `related` |
| 80 | `audit-a5a57399169da3dad68f` | `same` |
| 81 | `audit-41178a10bac27b34597e` | `unrelated` |
| 82 | `audit-a24570d7204d5be74aae` | `target_is_narrower` |
| 83 | `audit-68d245907d308b2b8258` | `same` |
| 84 | `audit-dcaa07eae01577e67e32` | `target_is_broader` |
| 85 | `audit-4dc02e968aa7c32693cb` | `same` |
| 86 | `audit-252f53ce11b63650e9aa` | `unrelated` |
| 87 | `audit-a03618c1d7952cef790a` | `related` |
| 88 | `audit-33b354431866dd3829f6` | `same` |
| 89 | `audit-5ef26abf412bb04ef9ac` | `target_is_broader` |
| 90 | `audit-c49ce04f80adeec32d05` | `unrelated` |
| 91 | `audit-f3e2d16d26ebffb15c2b` | `unrelated` |
| 92 | `audit-a5665354595d7f03a010` | `unrelated` |
| 93 | `audit-04a2647cc4e51c453ce6` | `related` |
| 94 | `audit-8938571818dc0c12f0bb` | `target_is_narrower` |
| 95 | `audit-e5722506e16d3baa524f` | `related` |
| 96 | `audit-08a3fbc25e3e9b29f736` | `related` |
| 97 | `audit-be8e9a5a253ce311edb9` | `target_is_narrower` |
| 98 | `audit-e24d14485949ec56b97d` | `same` |
| 99 | `audit-8a913aca108d9f4d8d6d` | `near_same` |
| 100 | `audit-6c89b477ddf9a4da59dd` | `same` |
| 101 | `audit-23512fcb6d0149123012` | `unrelated` |
| 102 | `audit-ef8c093c833af06e37b7` | `near_same` |
| 103 | `audit-944920ff455807d3b644` | `target_is_broader` |
| 104 | `audit-765868c683acd2a5a8f8` | `unrelated` |
| 105 | `audit-c0ad196f3eacf03ba46c` | `same` |
| 106 | `audit-66984d03795f0c4f4ac6` | `unrelated` |
| 107 | `audit-62de9e80b36ae93a48e3` | `unrelated` |
| 108 | `audit-29a5725d649320f861f0` | `related` |

The comparison to the sealed model-answer key is intentionally deferred until
after this table is content-addressed.
