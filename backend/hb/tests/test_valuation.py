from hb.engine import valuation


def test_blend_weights_both():
    # CMA_WEIGHT (0.2) on the CMA, the rest on the overbid point
    w = valuation.CMA_WEIGHT
    assert valuation.blended_value(2_000_000, 2_400_000) == round(
        w * 2_000_000 + (1 - w) * 2_400_000
    )


def test_blend_falls_back_to_available():
    assert valuation.blended_value(2_000_000, None) == 2_000_000
    assert valuation.blended_value(None, 2_400_000) == 2_400_000
    assert valuation.blended_value(None, None) is None
