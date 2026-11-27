"""Builds samples/sample_paper.json (+ a figure) for renderer testing. Original questions."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).parent
ASSETS = HERE / "assets"
ASSETS.mkdir(exist_ok=True)

# --- figure: block on an incline -------------------------------------------
fig, ax = plt.subplots(figsize=(3.2, 1.8), dpi=200)
th = np.radians(30)
L = 3
ax.plot([0, L * np.cos(th), L * np.cos(th), 0], [0, L * np.sin(th), 0, 0], "k", lw=1.2)
cx, cy, s = 1.5 * np.cos(th), 1.5 * np.sin(th), 0.45
R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
box = (R @ np.array([[0, s, s, 0, 0], [0, 0, s, s, 0]])).T + [cx, cy]
ax.fill(box[:, 0], box[:, 1], facecolor="#ddd", edgecolor="k", lw=1)
ax.annotate("", xy=(cx - 0.55 * np.cos(th), cy - 0.55 * np.sin(th) + 0.18),
            xytext=(cx + 0.05, cy + 0.18), arrowprops=dict(arrowstyle="->", lw=1))
ax.text(cx - 0.75, cy + 0.32, "$F$", fontsize=9)
ax.add_patch(matplotlib.patches.Arc((L * np.cos(th), 0), 0.8, 0.8, theta1=180 - 30, theta2=180))
ax.add_patch(matplotlib.patches.Arc((0, 0), 0.9, 0.9, theta1=0, theta2=30))
ax.text(0.5, 0.08, r"$30^\circ$", fontsize=8)
ax.set_aspect("equal"); ax.axis("off")
fig.savefig(ASSETS / "incline.png", bbox_inches="tight", transparent=False, facecolor="white")
plt.close(fig)

Q = []
def q(qno, section, stem, opts, ans, sol="", **kw):
    Q.append(dict(qno=qno, section=section, stem=stem, options=[{"text": o} for o in opts],
                  answer=ans, solution=sol, **kw))

q(1, "Physics",
  r"A gas at pressure $3$ atm and temperature $250\ \text{K}$ has a mean free time of $4 \times 10^{-8}\ \text{s}$ between collisions. If the pressure is halved and the temperature raised to $400\ \text{K}$, the new mean free time is close to:",
  [r"$1.0 \times 10^{-7}\ \text{s}$", r"$6.3 \times 10^{-8}\ \text{s}$", r"$4.0 \times 10^{-8}\ \text{s}$", r"$2.5 \times 10^{-8}\ \text{s}$"], "A",
  r"$\tau \propto \dfrac{\lambda}{v_{rms}}$, with $\lambda \propto \dfrac{T}{P}$ and $v_{rms} \propto \sqrt{T}$, so $\tau \propto \dfrac{\sqrt{T}}{P}$." "\n\n"
  r"$$\tau_2 = 4\times10^{-8}\times\sqrt{\frac{400}{250}}\times\frac{3}{1.5} \approx 1.0\times10^{-7}\ \text{s}$$",
  difficulty=3)

q(2, "Physics",
  r"A block rests on a rough incline of angle $30^\circ$ as shown. It just stays at rest when a force of $3\ \text{N}$ acts down the incline, and also when a force of $13\ \text{N}$ acts up the incline. The coefficient of static friction is: $[\,g = 10\ \text{m/s}^2\,]$",
  [r"$\dfrac{\sqrt{3}}{2}$", r"$\dfrac{8}{5\sqrt{3}}$", r"$\dfrac{1}{2}$", r"$\dfrac{2}{3}$"], "B",
  r"Down: $3 + mg\sin30^\circ = \mu mg\cos30^\circ$; Up: $13 = mg\sin30^\circ + \mu mg\cos30^\circ$." "\n\n"
  r"Adding: $2\mu mg\cos30^\circ = 16 \Rightarrow \mu mg \cos 30^\circ = 8$. Subtracting: $2mg\sin30^\circ = 10 \Rightarrow mg = 10$, so $\mu = \dfrac{8}{10 \cdot \frac{\sqrt3}{2}} = \dfrac{8}{5\sqrt3}$.",
  figure={"kind": "diagram", "path": "incline.png", "width_pct": 62}, difficulty=3)

q(31, "Chemistry",
  r"For a cell reaction, $E^\circ_{\text{cell}}$ is positive. Which of the following correctly describes $\Delta G^\circ$ and $K_{eq}$?",
  [r"$\Delta G^\circ > 0$ and $K_{eq} < 1$", r"$\Delta G^\circ > 0$ and $K_{eq} > 1$", r"$\Delta G^\circ < 0$ and $K_{eq} > 1$", r"$\Delta G^\circ < 0$ and $K_{eq} < 1$"], "C",
  r"$\Delta G^\circ = -nFE^\circ_{\text{cell}} < 0$ and $\Delta G^\circ = -2.303RT\log K_{eq} \Rightarrow K_{eq} > 1$.", difficulty=2)

q(32, "Chemistry",
  r"A gas-phase reaction $2\text{X} \rightarrow \text{Y} + 3\text{Z}$ takes place in a closed vessel. The concentration of Z rises by $6 \times 10^{-3}\ \text{mol L}^{-1}$ in $12$ s. The rate of disappearance of X (in $\text{mol L}^{-1}\text{s}^{-1}$) is",
  [r"$5.0 \times 10^{-4}$", r"$3.3 \times 10^{-4}$", r"$1.0 \times 10^{-3}$", r"$2.5 \times 10^{-4}$"], "B",
  r"$-\dfrac{1}{2}\dfrac{d[\text{X}]}{dt} = \dfrac{1}{3}\dfrac{d[\text{Z}]}{dt}$, so $-\dfrac{d[\text{X}]}{dt} = \dfrac{2}{3}\times\dfrac{6\times10^{-3}}{12} = 3.3\times10^{-4}$.", difficulty=2)

q(61, "English Proficiency",
  "Choose the option that best explains the meaning of the idiom in the sentence:\n\nThe sudden audit **put a spoke in the wheel** of the merger talks.",
  ["Sped up the process", "Obstructed the plan", "Made the plan public", "Revealed hidden profits"], "B",
  "To *put a spoke in someone's wheel* means to hinder or obstruct their plans.", difficulty=2)

q(62, "English Proficiency",
  "Part of the sentence is in bold. Choose the alternative that improves it. If no improvement is needed, choose (D).\n\nHardly **had she reached the station than** the train pulled out.",
  ["had she reached the station when", "she had reached the station than", "had she reached the station then", "No improvement"], "A",
  "*Hardly* is followed by *when*, not *than*.", difficulty=2)

q(71, "Logical Reasoning",
  r"PENCIL : NCLPEI :: MARKET : ?",
  ["RKTMAE", "RKMTAE", "KRTMEA", "RTKMAE"], "A",
  "Letters at positions 1 2 3 4 5 6 are rearranged as 3 4 6 1 2 5: PENCIL becomes N C L P E I. Applying the same to MARKET gives R K T M A E.", difficulty=2)

q(72, "Logical Reasoning",
  "Arrange the words in a meaningful sequence:\n\n1. Harvest  2. Sowing  3. Ploughing  4. Irrigation  5. Marketing",
  ["3, 2, 4, 1, 5", "2, 3, 4, 1, 5", "3, 4, 2, 1, 5", "3, 2, 1, 4, 5"], "A", "Ploughing, sowing, irrigation, harvest, marketing.", difficulty=1)

q(91, "Mathematics",
  r"If $\alpha, \beta \in \left(-\dfrac{\pi}{4}, 0\right)$ with $\sin(\alpha+\beta) = -\dfrac{56}{65}$ and $\sin\alpha = -\dfrac{3}{5}$, then $\tan(2\alpha + \beta)$ equals",
  [r"$\dfrac{36}{323}$", r"$-\dfrac{323}{36}$", r"$\dfrac{323}{36}$", r"$-\dfrac{36}{323}$"], "C",
  r"$\cos\alpha = \dfrac45 \Rightarrow \tan\alpha = -\dfrac34$. Since $\alpha + \beta \in \left(-\dfrac{\pi}{2}, 0\right)$, $\cos(\alpha+\beta) = \dfrac{33}{65}$ and $\tan(\alpha+\beta) = -\dfrac{56}{33}$." "\n\n"
  r"$$\tan(2\alpha+\beta) = \frac{-\frac{56}{33} - \frac34}{1 - \frac{56}{33}\cdot\frac34} = \frac{-\frac{323}{132}}{-\frac{36}{132}} = \frac{323}{36}$$", difficulty=4)

q(92, "Mathematics",
  r"The area (in sq. units) of the region $\{(x, y) : x^2 \le y \le 4 - x^2\}$ is",
  [r"$\dfrac{16\sqrt{2}}{3}$", r"$\dfrac{8\sqrt{2}}{3}$", r"$\dfrac{32}{3}$", r"$\dfrac{16}{3}$"], "A",
  r"The curves meet at $x = \pm\sqrt{2}$. $$A = \int_{-\sqrt2}^{\sqrt2} (4 - 2x^2)\,dx = 2\left[4x - \tfrac{2x^3}{3}\right]_0^{\sqrt2} = \frac{16\sqrt2}{3}$$", difficulty=3)

paper = {"title": "BITSAT Practice Paper — Sample Set", "subtitle": "Renderer test · 10 questions",
         "pattern_id": "bitsat_130", "questions": Q}
(HERE / "sample_paper.json").write_text(json.dumps(paper, indent=1, ensure_ascii=False))
print("wrote", HERE / "sample_paper.json")
