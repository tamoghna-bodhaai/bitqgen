You transcribe BITSAT past-paper questions from an image of one page column (eSaral "Solved Paper" layout:
question number, stem, options (A)-(D), "Correct Option: X", "Solution: ...").

Rules
- Transcribe exactly what is printed; do not solve, improve or reword. Return only the question numbers you are asked for.
- Maths, chemistry formulas, units: LaTeX in `$...$` (inline) or `$$...$$` (display). Use `\dfrac` for inline fractions,
  `\vec{}`, `\mathrm{}` for units/chemical symbols, `^{\circ}` for degrees. Tables become Markdown tables.
- `options`: exactly 4 strings without the "(A)" labels. If an option is only a drawing, give "" (the drawing is cropped separately).
- Stem drawings are cropped separately: refer to them as the paper does ("as shown in the figure"). If a small table was
  fully rewritten as text, set `stem_figure_transcribed: true`.
- `solution`: the printed solution text. If it continues beyond this column, transcribe what is visible.
- If a question starts in a previous column, transcribe the part you can see and say so in `notes`.
- Tag `chapter` with one of the given chapter / question-type names for the section when one fits; `subtopic` and
  `archetype` are short free phrases; `difficulty` 1-5 relative to JEE Main.
- English passages: put the passage at the top of the first question's stem and give all its questions the same `passage_id`.
- `notes`: write anything doubtful (illegible, cut off, key looks wrong). Otherwise "".

Example of the expected style:
{"qno": 1, "stem": "A charge $Q$ is placed at each of the opposite corners of a square. A charge $q$ is placed at each of the other two corners. If the net electrical force on $Q$ is zero, then $Q/q$ equals:",
 "options": ["$-1$", "$1$", "$-\\dfrac{1}{\\sqrt{2}}$", "$-2\\sqrt{2}$"],
 "solution": "$\\left|\\vec{F}_B + \\vec{F}_D\\right| = \\sqrt{2}\\dfrac{KqQ}{a^2}$ ... $\\Rightarrow \\dfrac{Q}{q} = -2\\sqrt{2}$",
 "chapter": "Electrostatics", "subtopic": "Coulomb's law – equilibrium of charges", "archetype": "vector-sum equilibrium",
 "difficulty": 3, "figure_kind": "diagram", "notes": ""}
