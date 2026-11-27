import pytest

from core.mathfix import normalize_math as n


@pytest.mark.parametrize("src,want", [
    ("2 pi sqrt(m/(2k))", r"$2 \pi  \sqrt{m/(2k)}$"),
    ("is 3.0 x 10^-5 T and", r"is $3.0\times10^{-5}$ T and"),
    ("density 900 kg m^-3 floats", r"density 900 $\mathrm{kg\,m^{-3}}$ floats"),
    ("C1 = 6 uF, Q = 8 uC", r"C1 = 6 $\mu$F, Q = 8 $\mu$C"),
    ("is $\x1b[0m\\mathbf L$ ok", r"is $\mathbf L$ ok"),
    (r"value \(\dfrac{\pi}{2}\), so", r"value $\dfrac{\pi}{2}$, so"),
    ("3x^2 + 4y^2 = 12", "$3x^{2} + 4y^{2} = 12$"),
    ("The **FRUGAL** word ______.", "The **FRUGAL** word ______."),
    ("speed of 20 m/s. If", "speed of 20 m/s. If"),
    ("already $x^2$ fine", "already $x^2$ fine"),
    ("end.\\n$$x$$", "end.\n$$x$$"),
    ("about $smog.\\nI$. Classical $\\text{SO}_2$$.\\nII$. P",
     "about smog.\nI. Classical $\\text{SO}_2$.\nII. P"),
    ("angle of $60^\\\\circ$.", "angle of $60^\\circ$."),
    ("$\x024mathcal{E}=6$ and $\x07Delta E$", "$\\mathcal{E}=6$ and $\\Delta E$"),
    ("$a\\neq b$ and $\\nabla f$", "$a\\neq b$ and $\\nabla f$"),
    ("$$\\begin{vmatrix}1\\\\x&2\\end{vmatrix}$$", "$$\\begin{vmatrix}1\\\\x&2\\end{vmatrix}$$"),
    ("so II is true.\\\\\nNext", "so II is true.\nNext"),
])
def test_normalize(src, want):
    assert n(src) == want
