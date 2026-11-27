import random
from pathlib import Path

import pytest

from figures.lr.generators import GENERATORS, NETS, fold_net, _OPP


@pytest.mark.parametrize("name", sorted(GENERATORS))
@pytest.mark.parametrize("seed", range(6))
def test_generator_consistent(name, seed, tmp_path):
    it = GENERATORS[name](random.Random(seed), tmp_path, f"q{seed}")
    assert it.answer in "ABCD"
    assert len(it.options) == 4
    if it.option_figures:
        assert len(it.option_figures) == 4
        for p in it.option_figures:
            assert (tmp_path / p).exists()
    else:
        assert len(set(it.options)) == 4, it.options  # distinct text options
    if it.stem_figure:
        assert (tmp_path / it.stem_figure).exists()


def test_nets_valid():
    for cells in NETS:
        sides = fold_net(cells)
        assert sorted(sides.values()) == sorted("TBNSEW")


def test_cross_net_opposites():
    # cross: row (0,1)(1,1)(2,1)(3,1), (1,0) above and (1,2) below column 1
    s = fold_net([(1, 0), (0, 1), (1, 1), (2, 1), (3, 1), (1, 2)])
    assert _OPP[s[(0, 1)]] == s[(2, 1)]
    assert _OPP[s[(1, 1)]] == s[(3, 1)]
    assert _OPP[s[(1, 0)]] == s[(1, 2)]


def test_non_net_rejected():
    with pytest.raises(ValueError):
        fold_net([(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0)])


def test_number_grid_answer(tmp_path):
    for seed in range(20):
        it = GENERATORS["number_grid"](random.Random(seed), tmp_path, "g")
        rows = it.params["rows"]
        assert it.options["ABCD".index(it.answer)] == str(rows[2][2])
