// Page template. All content arrives through data.json, so scripture text is only ever
// *displayed* by Typst, never interpreted as markup.
#let d = json("data.json")

#let rule-color = luma(150)
#let primary = d.texts.at(0)
#let parallel = d.texts.len() > 1

// "Study" layout: wide margins and open line spacing leave room for notes.
#let side = if not d.notes { 2.6cm } else if parallel { 2.8cm } else { 4.2cm }
#let leading = if d.notes { 1.05em } else { 0.68em }

#set document(title: d.title)
#set page(
  paper: d.paper,
  margin: (x: side, top: 2.8cm, bottom: 2.8cm),
  header: context {
    // Running head on every page but the first.
    if counter(page).get().first() > 1 {
      set text(font: primary.font, size: 0.85em, fill: luma(90))
      align(center, d.title)
    }
  },
  footer: context {
    set text(font: primary.font, size: 0.9em)
    align(center, counter(page).display())
  },
)

// Line numbers restart on every page. In parallel mode they count the first text's lines.
#set par.line(
  numbering: if d.line_numbers { n => text(size: 0.7em, fill: luma(115), str(n)) } else { none },
  number-clearance: 1em,
  numbering-scope: "page",
)

// Lines of poetry: hanging indent so wrapped lines stay inside their level. No stanza gaps.
#let poetry(lines) = {
  for l in lines {
    par(first-line-indent: 0pt, hanging-indent: 1.4em * (l.level + 1), justify: false,
        leading: leading, spacing: leading)[#h(1.4em * l.level)#l.text]
  }
}

// Copyright and licence notice, set small at the end of its text.
#let colophon(c) = {
  set par.line(numbering: none)
  set text(size: 0.78em)
  set par(justify: false, first-line-indent: 0pt, leading: 0.55em, spacing: 0.8em)
  v(2.2em)
  line(length: 2.5em, stroke: 0.5pt + rule-color)
  v(0.2em)
  text(weight: "bold")[#c.name]
  if c.abbreviation != none [ (#c.abbreviation)]
  if c.notice != none { par(emph(c.notice)) }
  for p in c.statement { par(p) }
}

// One text rendered with its own language, font and typographic settings.
#let render-text(t) = {
  set text(
    font: t.font,
    lang: t.lang,
    region: t.region,
    dir: if t.dir == "rtl" { rtl } else { ltr },
    size: d.size * 1pt,
    hyphenate: t.hyphenate,
    cjk-latin-spacing: auto,
  )
  set par(
    justify: t.justify,
    leading: if t.cjk { leading + 0.3em } else { leading },
    spacing: if t.cjk { leading + 0.3em } else { leading },
    first-line-indent: if t.cjk { 2em } else { 1.2em },
  )
  if t.heading != none {
    set par.line(numbering: none)
    align(center, block(below: 1em, text(0.85em, style: "italic", t.heading)))
  }
  for b in t.blocks {
    if b.type == "prose" { par(b.text) } else { poetry(b.lines) }
  }
  if t.colophon != none { colophon(t.colophon) }
}

// Title block.
#{
  set align(center)
  set text(font: primary.font)
  set par.line(numbering: none)
  text(size: 1.9em, tracking: 0.04em, d.title)
  v(0.5em)
  line(length: 2.5em, stroke: 0.5pt + rule-color)
  v(1.6em)
}

#if not parallel {
  render-text(primary)
} else {
  grid(
    columns: (1fr,) * d.texts.len(),
    inset: (x: 0.9em),
    stroke: (x, y) => if x > 0 { (left: 0.4pt + rule-color) },
    ..d.texts.map(t => render-text(t)),
  )
}
