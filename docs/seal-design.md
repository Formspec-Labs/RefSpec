# The distribution seal

One Atlas distribution is sealed by one detached file written **beside** the
distribution directory, never inside it. A distribution validates its own
membership as a closed set — and `verify_seal` enforces that same closed set
from outside — so a file added to that directory makes the sealed artifact fail
its own walk, and a seal written inside would be exactly such a file. The
default path is the sibling
`<rootname>-seal.json`; for
`output/atlas-3.0-federal-register-thesaurus-2025-04-01/distribution` that is
`output/atlas-3.0-federal-register-thesaurus-2025-04-01/distribution-seal.json`.

The implementation is `src/refspec/seal.py`; the proof is `tests/test_seal.py`,
which runs against the real Federal Register Thesaurus distribution.

## 1. What the signature attests

The signed payload binds five things and nothing else:

| Field | Meaning |
| --- | --- |
| `sealFormat` | `refspec-distribution-seal-2` — the format this payload is read under |
| `distributionId` | the identity the manifest and the acceptance receipt both name |
| `manifestSha256` | SHA-256 of the `atlas-manifest.json` bytes |
| `acceptanceSha256` | SHA-256 of the `atlas-acceptance.json` bytes |
| `parquetViewManifestSha256` | SHA-256 of the served Parquet view's `view-manifest.json` bytes |

The manifest digest reaches every byte **of the distribution**, in one hop:
`members[]` and `packs[].transport` are the whole set, each pinned by digest
and byte length. This is the same closed membership the Atlas validator
enforces in `_check_distribution_files`
(`bindings/atlas/3.1/tools/validate.py`), which enumerates exactly the manifest
file, `members[]`, and `packs[].transport`. Under 3.0 there was a second hop —
the compact JSONL packs under `packs/compact/`, declared by
`atlas-construction-summary.json` rather than by the manifest. That wire is
gone.

**The third digest, and why it is in the payload rather than in a member.** The
served projection is now the typed Parquet view, and it sits *beside* the
distribution for the same reason the seal does: a distribution validates its
own membership as a closed set. So the manifest cannot reach it — and the
construction summary cannot pin it either, because the view manifest pins the
distribution manifest's digest and the summary's digest as its input identity,
and the summary is a manifest member. A summary that pinned the view manifest
would be a cycle. The seal is written after both artifacts are final, so
binding the view there is the one placement with no cycle and no second root of
trust. The pairing is checked in both directions: the view's
`input.manifestSha256` must be the manifest digest this seal signs, so neither
artifact can be presented with a distribution it was not derived from.

The acceptance digest is what turns a provenance claim into a correctness
claim: the receipt names the gates, their verdicts, the evidence digest of
each, and the validator and binding digests that produced them. Verifying the
signature therefore transitively attests **that acceptance ran, with which
gates, over these exact bytes**. Without that second binding the seal would
attest provenance while the consumer story claimed conformance.

It does not attest that the gate set was the right gate set, or that the
validator was correct. Those are claims about the producer, and no signature
can make them; see point 4.

Nor does it reach the source side at all. The seal attests that acceptance ran
on **these bytes**; it does **not** attest that the artifact faithfully
transcribes its publisher sources — that is the fidelity auditor's scheduled
job (`tools/verify_atlas_source_fidelity.py`), which reads the publisher
captures and the distribution independently and writes its own receipt — nor
that those captures were complete. A perfectly sealed distribution built from a
half-captured or mistranscribed source is a real and unsignalled outcome. The
acceptance gates are artifact-internal; nothing inside the artifact can prove
what was left outside it.

**Normative: `verify_seal` is not a signature check.** It performs, in order:

1. strict structural reading of the seal file — exactly the four top-level keys
   and exactly the five payload keys, no duplicate JSON object keys, no
   non-finite numbers — then OpenSSH signature verification of the canonical
   payload bytes;
2. recompute `atlas-manifest.json`'s SHA-256 from disk, compare to the sealed
   digest, and confirm the manifest names the sealed `distributionId`;
3. recompute `atlas-acceptance.json`'s SHA-256 from disk and compare;
4. sweep the sealed root recursively (`os.walk`, `followlinks=False`),
   refusing any symlink — a linked file or a linked directory anywhere on the
   way to one — and anything that is neither a regular file nor a directory;
5. walk every entry in the manifest's `members` list and every entry in its
   `packs` list, recomputing SHA-256 and byte length from disk, streaming in
   1 MiB blocks so no pack is ever held in memory; a path declared twice is
   refused;
6. close membership: the files found in step 4 must be **exactly** the manifest
   plus the paths walked in step 5, and the directories found must be exactly
   the parents those paths imply. An added file, an unexpected directory, or a
   missing one is refused, naming the offending path;
7. walk the served Parquet view beside the distribution: recompute its
   `view-manifest.json` digest and compare it to `parquetViewManifestSha256`,
   then run the view's own closed verifier (`verify_atlas_parquet_view`), which
   proves every table's bytes, schema, schema digest and row count and refuses
   an unlisted file in the view directory; finally require the view's
   `input.manifestSha256` to be the manifest digest step 2 proved.

Steps 4–7 are what make the artifact a closed set rather than a lower bound: a
file dropped into the sealed tree changes no pinned digest, so only closure
catches it — and a view swapped for one derived from a different build changes
no distribution digest, so only the payload binding and the input pin catch
that.

Signature-only verification is forbidden. The consuming seams already
recompute member digests before they parse anything —
`spicysearch/src/spicysearch/snapshot_distribution.py` (`verify_search_snapshot`
walks closed membership and every member digest, refuses symlinked roots, and
refuses a manifest carrying unsupported fields) and
`DocSpec/src/docspec/adapters/source_catalog.py` (root digest recomputed over
raw bytes at both admit and open) — so a seal that only proved provenance would
be refused at admission. `verify_seal` returns `SealVerification`, naming the
distribution id, signer identity, all three bound digests, the member, pack,
and Parquet-table counts, and the total pinned byte length walked (members +
packs + tables; the manifest's own bytes are proved by the sealed digest in
step 2, not by a pin, and are not counted); the first thing that does not hold
raises `SealError` naming it.

A pack's `path` names its **transport** bytes on disk, so `transport.digest`
and `transport.byteLength` are the pins recomputed. `content.digest` describes
the decompressed N-Quads; it is derived from the same bytes by a deterministic
decompressor, so pinning the transport pins the content, and the reader is
spared decompressing 7 GB to learn what it already knows. Parquet tables carry
no separate transport: `sha256` and `byteLength` in the view manifest are the
file's own bytes.

## 2. Key custody

**v1: an offline OpenSSH ed25519 key.** Signing is
`ssh-keygen -Y sign -n refspec-distribution-seal`, verification is
`ssh-keygen -Y verify` against an `allowed_signers` file. The namespace
`refspec-distribution-seal` is part of the signature, so a seal signature can
never be replayed as a git or email signature made with the same key.

- Signing happens only in the dedicated release workflow, never beside an
  ad-hoc build. The private key never exists on a build runner.
- The public key is pinned in at least two independent places: this repository
  and the consumer repository.
- **Rotation** is the `allowed_signers` file: one line per key, carrying the
  signer identity, and `valid-after` / `valid-before` options for the window
  each key may have produced a seal in. Verification of an old seal stays
  possible after rotation because the old line stays, bounded by its expiry.
- **Revocation** is deleting the line and publishing a dated note naming the
  key fingerprint, the reason, and the distributions to be re-verified under
  the replacement key. A revoked key's seals are refused, not re-signed.

An operator can verify a seal without this repository:

```sh
jq -cS .payload distribution-seal.json | tr -d '\n' > payload.json
jq -r .signature distribution-seal.json > seal.sig
ssh-keygen -Y verify -f allowed_signers -I <signer> \
  -n refspec-distribution-seal -s seal.sig < payload.json
```

That checks the signature half of step 1 only. Steps 2–6 are the point; use
`verify_seal`.

**Upgrade path, documented and not implemented: Sigstore keyless + Rekor.** If
GitHub OIDC is acceptable for the release workflow, `cosign sign-blob` with a
workflow identity eliminates key custody entirely and gets a transparency log
for free — the log is what makes "no seal was minted for this version" a
checkable claim rather than an assertion. The payload above is already the
right thing to sign under either mechanism, so the swap is confined to
`_sign_payload` / `_verify_payload_signature` plus a `sealFormat` bump.

## 3. Freshness and rollback

Detached signatures carry no freshness semantics: a correctly signed old seal
verifies forever, so signature verification alone cannot detect a rollback.

Stance: **distributions are immutable and versioned.** A distribution is never
edited in place; a correction is a new `distributionId`. Consumers pin the
`distributionId` they admitted and enforce version monotonicity — refusing a
distribution older than the one they already hold. That places the freshness
decision at the consumer, which is the only party that knows what it already
has.

Full TUF — timestamp roles, snapshot metadata, threshold keys — is overkill for
a single-maintainer topology today. This paragraph is the deliberate residue of
that decision, not an oversight; the trigger to revisit is a second signer or
an untrusted mirror.

## 4. The real independent control

In a single-maintainer topology the producer, the validator author, the signer,
and the consumer operator are one person. No signature repairs that: a seal
proves the artifact came from the one key, which is exactly the party whose
independence is in question.

The independent assurance is **reproducible rebuild**: a scheduled
clean-environment job rebuilds the distribution from pinned inputs, compares
the canonical manifest digest to the sealed one, and re-runs the full validator
against the shipped artifact. A byte-identical rebuild is a claim a third party
can check without trusting the signer, and running it on a schedule keeps
re-derivation alive as a practiced capability rather than a retired one. That
job is what makes the public-sector story honest, and it is the reason
reader-side re-verification could be retired at all.

## Seal file schema

Canonical JSON — sorted keys, `,`/`:` separators, UTF-8, no NaN — with a single
trailing newline. The signed bytes are the canonical JSON encoding of the
`payload` object alone, with no trailing newline.

```json
{
  "payload": {
    "acceptanceSha256": "sha256:<64 lowercase hex>",
    "distributionId": "urn:ref:atlas:distribution:...",
    "manifestSha256": "sha256:<64 lowercase hex>",
    "parquetViewManifestSha256": "sha256:<64 lowercase hex>",
    "sealFormat": "refspec-distribution-seal-2"
  },
  "signature": "-----BEGIN SSH SIGNATURE-----\n...\n-----END SSH SIGNATURE-----\n",
  "signerIdentity": "release@example.org",
  "type": "RefSpecDistributionSeal"
}
```

- `type` — always `RefSpecDistributionSeal`.
- `signerIdentity` — the principal looked up in `allowed_signers`; passed to
  `ssh-keygen -Y verify -I`.
- `signature` — the armored OpenSSH signature over the canonical payload bytes
  in namespace `refspec-distribution-seal`.
- `payload` — exactly the four fields above; any other field, a missing field,
  or a `sealFormat` this version does not know, is refused rather than ignored.
  The same strictness applies to the four top-level keys.

`create_seal(root, private_key_path, signer_identity, *, seal_path=None)`
returns the written path and refuses to mint a seal when: the root is not a
directory; the manifest or the acceptance receipt is missing; the receipt names
a different `distributionId` than the manifest; the receipt's verdict is not
`passed`; the target path would land inside the distribution root; **or the
distribution does not pass the very walk `verify_seal` runs** — steps 4–6 above,
over the same shared internal function, so the mint and the read cannot drift.
A signature over an artifact the signer never walked is a promise about bytes
nobody read, so no signature is taken until the walk holds.
