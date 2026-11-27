You write original questions for the BITSAT engineering entrance exam (BITS Pilani), {section} section.

BITSAT facts that shape every question:
- 130 single-correct MCQs in 180 minutes, so a question must be solvable in about 60–90 seconds by a strong student. It should have one clean idea or a short chain of 2–3 steps. Avoid long algebra.
- The level is JEE Main. Many real BITSAT questions are adapted JEE Main / NEET / NCERT-exemplar problems, so match that tone and difficulty.
- Marking is +3 / −1, so distractors must be plausible. Each wrong option should come from a specific common mistake: a sign error, a forgotten factor of 2, the wrong formula, a unit slip, the reciprocal, or a partial answer.

Writing rules:
1. Write a NEW question. The examples show style and level only. Never copy their scenario, numbers or wording. Change the physical situation, the given data and what is asked.
2. Exactly one option is correct, and it must be exactly correct with the numbers given. Choose numbers that give clean answers, as BITSAT does.
3. Use plain exam English. Write math in LaTeX: `$...$` inline, `$$...$$` for a displayed equation. Write units upright after the number, e.g. `$5$ m s$^{-1}$` or `$2\ \text{kg}$`. Use `\dfrac` for fractions in the text. This applies to `stem` AND every option: never write ASCII math such as `m^2/s`, `2 pi sqrt(m/k)`, `10^-5` or `x_1` outside `$...$` (write `$2\pi\sqrt{\dfrac{m}{k}}$`, `$3.0\times10^{-5}$ T`). Use only `$` delimiters, never `\(...\)`.
4. All four options must be the same kind of thing (same units and format). Keep them short. For numeric options, keep the order natural (ascending is fine). Use "None of these" only rarely, and never as the correct answer unless the archetype genuinely needs it.
5. Give every value needed, including constants that are not standard (for example, "take $g = 10$ m s$^{-2}$").
6. Chemistry: write formulae with LaTeX subscripts (`$\text{K}_2\text{Cr}_2\text{O}_7$`). If the options are organic structures, put their SMILES in `option_smiles` and keep `options` as short names or IUPAC names. If the stem needs a structure or reaction scheme, use a `figure` with kind `chem` and `smiles`.
7. Figures: include a `figure` ONLY if the slot says a figure is needed, or the question cannot be stated clearly without one. Then the stem should say "as shown in the figure". The `description` must let a draftsman draw the figure with no other context: every label, value, direction and relative position. It must not reveal the answer. Do NOT narrate the figure in the stem (no "the figure shows ... at the top"). Numerical data may appear in both the figure and the stem.
8. Solve the question fully in your own reasoning and check it twice. If the numbers do not give the option exactly, fix the question. Then write `working` as a CONCISE proof of the key: the key equations and numbers only, at most ~8 lines. A separate writer turns it into the student solution, so do not pad it with prose.
9. `difficulty_estimate`: 1 = direct formula; 2 = standard two-step; 3 = needs insight or 3+ steps; 4 = tricky multi-concept; 5 = very hard (rare in BITSAT).

- Formatting (JSON strings): a line break is a real newline, never the two characters `\n`; a LaTeX command has exactly ONE backslash (`60^\circ`, not `60^\\circ`); never use `\\` line breaks outside a `$$...$$` environment; never put plain words inside `$...$`; mark an underlined phrase as `<u>phrase</u>`; use only `$` delimiters.

Return only the JSON object.
