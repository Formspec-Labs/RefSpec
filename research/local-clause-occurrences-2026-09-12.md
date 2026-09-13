# Bounded local clause occurrences

`citation_grammar.find_local_clause_occurrences` adds a text occurrence reader
for singular, unqualified lowercase Roman clause labels. It supplies exact source
positions and explicit refusals. Consumers must establish the local native scope;
the reader supplies neither target addresses nor governing relationships.

The inspected source is 20 USC 1414(d)(1)(C)(iii). Its raw USLM structure contains
the following text, without `<ref>` elements around the two clause references:

```xml
<clause identifier="/us/usc/t20/s1414/d/1/C/iii">
  <num value="iii" class="bold">(iii)</num>
  <heading class="bold"> Written agreement and consent required</heading>
  <content><p style="-uslm-lc:I14" class="indent3">A parent’s agreement under clause (i) and consent under clause (ii) shall be in writing.</p></content>
</clause>
```

The surrounding clause distinguishes agreement and consent and rules out a
broken publisher hyperlink as the cause of their absence from the native edge
reader. The fixture retains the actual sentence; mutations cover qualified
containers, lists, ranges, nested pinpoints, label case and paragraph boundaries.
Those forms remain refused rather than being shortened to an assumed target.
Broader local-reference recognition remains open. Recognition of quoted prose
does not establish that it is operative text.

Implementation reuses the existing label lexer and indexes structural boundaries
once: O(text length + occurrence count × log boundary count), with linear storage.
No existing matcher was replaced. Targeted grammar regression checks passed
180 tests; Ruff passed on the changed source and tests.
