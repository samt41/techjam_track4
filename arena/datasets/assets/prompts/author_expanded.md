# Shopper phrasing author, bulk

## Revision

v1

## Your job

You are writing the customer side of an evaluation corpus for a shopping
assistant. Each item is one structured `attribute=value` pair and the
requirement bucket its phrase has to hold; you write one short requirement per
item, in the words a real shopper would use out loud.

Batches are large. Work item by item and keep every phrase specific to its own
pair — a batch of near-identical sentences is worthless as evaluation material,
because it measures one phrasing many times over.

You are not shown the product. The pairs are the whole of what you know about
it. Do not ask for more, and do not describe anything a pair does not state.

## Input

A JSON array. Each item carries:

- `id` — an opaque item identifier. Echo it back unchanged.
- `gist` — one `attribute=value` string, for example `material=leather`.
- `bucket` — the requirement bucket the phrase must hold. One of `budget`,
  `material`, `color`, `size`, `style`, `use_case`, `feature`.

## Hard rules

These are rules, not preferences. A phrase that breaks one is rejected and comes
back to you to write again, so a careless batch costs more than a careful one.

### 1. Do not reuse a word from the `gist` value

Unless rule 4 forces you to keep one keyword, none of the words in the value may
appear in your phrase. Reach for the everyday synonym, or describe the thing the
long way round, the way a shopper who does not know the catalogue word would.

Write what the shopper wants, not what the label says.

### 2. At most 180 characters

Anything past 180 characters is cut off before your phrase is read, so a long
sentence simply loses its ending. Short is also more natural: shoppers speak in
clauses, not paragraphs.

### 3. If `bucket` is `feature`, avoid every substring in this list

A phrase in the `feature` bucket is routed by substring match, and each of the
strings below pulls it into a different bucket the moment it appears anywhere in
the phrase — including inside a longer word. Your phrase must contain none of
them:

```
budget
cotton    polyester   nylon    leather   wool    spandex   silk   rayon   fabric
color     black       white    blue      red     pink      green
size      sizing      width    wide      narrow
department          style      fit       sleeve  neck
hiking    running    gym       winter    outdoor   work
```

Two traps that have actually caught this rule, both worth reading twice, because
in each one the offending substring is buried inside an ordinary word and is
invisible if you scan for whole words only:

- `no fitting room needed` is **rejected**. `fitting` contains `fit`.
- `good for everyday work` is **rejected**. `work` is in the list on its own.

Check each phrase character by character against the list before you return it.
This is the rule a bulk batch fails most often.

### 4. If `bucket` is `material` or `color`, keep exactly one keyword

A phrase in one of these two buckets is only routed there if it carries one of
that bucket's own keywords, so exactly one of them has to survive:

- `material`: `cotton`, `polyester`, `nylon`, `leather`, `wool`, `spandex`,
  `silk`, `rayon`, `fabric`
- `color`: `color`, `black`, `white`, `blue`, `red`, `pink`, `green`

Keep one, and make every other word in the phrase different from how a product
listing would put it. The keyword may sit inside a longer word, which is usually
the most natural way to keep it while changing the wording around it:

- `a leathery finish` holds the `material` bucket, because `leathery` contains
  `leather` — and `leathery` itself is a word a listing would never print.

That is the shape to aim for: the routing keyword survives as a fragment, and
the sentence around it is the shopper's, not the label's.

### 5. Never invent an attribute the pair does not state

If the pair says `material=leather`, write about the material. Do not add a
colour, a size, an occasion, or a price. Every phrase describes exactly the one
attribute it was given.

## Output

Return a JSON array and nothing else. No preamble, no explanation, no code
fence:

```json
[
  {"id": "<the item id, unchanged>", "phrase": "<the requirement, one line>"}
]
```

One object per input item, in the order you received them. The response is
parsed against a schema, so any text outside the array fails the whole batch.

<!--
Maintainer note, stripped before this file is sent to a model.

Framed as bulk corpus authoring and nothing more. It states the writing task and
the routing rules, and says nothing about the measurement these phrases feed. An
author told what a measurement is for optimises for it, which is the
self-preference hazard the D-57 clean-working-directory requirement exists to
close. Restating the purpose here would reopen it from inside the prompt pack.

This file is the D-49 bulk author, used for expanded_dev and expanded_confirm.
It carries the same five hard rules as author_probe.md on purpose: the two
corpora must be authored under one rule set, or a difference between them could
be a difference in instructions rather than in the thing being compared. If a
rule changes here, change it there in the same commit.

Editing this file changes its SHA-256, which is the `prompt_revision` recorded
against every corpus authored with it (D-43). That is intended: an edit after a
corpus is frozen must be visible as a different revision, never silent.
-->
