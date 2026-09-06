from sale_bot.providers import CHEONGJU_NEIGHBORHOODS


def test_cheongju_composite_regions_use_daangn_names():
    expected = {
        "충청북도 청주시 상당구 용담.명암.산성동",
        "충청북도 청주시 서원구 성화.개신.죽림동",
        "충청북도 청주시 흥덕구 운천.신봉동",
        "충청북도 청주시 흥덕구 봉명2.송정동",
        "충청북도 청주시 청원구 율량.사천동",
    }
    assert len(CHEONGJU_NEIGHBORHOODS) == 43
    assert expected <= set(CHEONGJU_NEIGHBORHOODS)

    old_names = {
        "충청북도 청주시 상당구 용담명암산성동",
        "충청북도 청주시 서원구 성화개신죽림동",
        "충청북도 청주시 흥덕구 운천신봉동",
        "충청북도 청주시 흥덕구 봉명2송정동",
        "충청북도 청주시 청원구 율량사천동",
    }
    assert not (old_names & set(CHEONGJU_NEIGHBORHOODS))
