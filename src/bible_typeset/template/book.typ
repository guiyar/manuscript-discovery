// Page template. All content arrives through data.json, so scripture text is
// only ever *displayed* by Typst, never interpreted as markup.
#let d = json("data.json")

#let rule-color = luma(150)
#let primary = d.texts.at(0)

#set document(title: d.title)
#set page(
  paper: d.paper,
  margin: (x: 2.6cm, top: 2.8cm, bottom: 2.8cm),
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

// Lines of poetry: hanging indent so wrapped lines stay inside their level.
#let poetry(lines) = block(above: 0.9em, below: 0.9em, breakable: true)[
  #for l in lines {
    block(above: 0.35em, below: 0.35em)[
      #par(
        first-line-indent: 0pt,
        hanging-indent: 1.4em * (l.level + 1),
        justify: false,
      )[#h(1.4em * l.level)#l.text]
    ]
  }
]

// One text rendered with its own language, font and typographic settings.
#let render-text(t, columnar: false) = {
  set text(
    font: t.font,
    lang: t.lang,
    region: t.region,
    size: d.size * 1pt,
    hyphenate: t.hyphenate,
    cjk-latin-spacing: auto,
  )
  set par(
    justify: t.justify,
    leading: if t.cjk { 0.95em } else { 0.68em },
    spacing: if t.cjk { 0.95em } else { 0.68em },
    first-line-indent: if t.cjk { 2em } else { 1.2em },
  )
  if columnar and t.label != none {
    align(center, block(below: 1em, text(0.85em, style: "italic", t.label)))
  }
  for b in t.blocks {
    if b.type == "prose" {
      par(b.text)
    } else {
      poetry(b.lines)
    }
  }
}

// Title block.
#{
  set align(center)
  set text(font: primary.font)
  text(size: 1.9em, tracking: 0.04em, d.title)
  v(0.5em)
  line(length: 2.5em, stroke: 0.5pt + rule-color)
  if d.subtitle != none {
    v(0.2em)
    text(size: 0.95em, style: "italic", fill: luma(70), d.subtitle)
  }
  v(1.6em)
}

#if d.texts.len() == 1 {
  render-text(primary)
} else {
  grid(
    columns: (1fr,) * d.texts.len(),
    inset: (x: 0.9em),
    stroke: (x, y) => if x > 0 { (left: 0.4pt + rule-color) },
    ..d.texts.map(t => render-text(t, columnar: true)),
  )
}
