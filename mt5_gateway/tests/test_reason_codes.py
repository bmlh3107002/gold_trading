from mt5_gateway.reason_codes import AMBIGUOUS, ReasonCode, from_retcode


def test_known_codes():
    assert from_retcode(10009) is ReasonCode.OK
    assert from_retcode(10018) is ReasonCode.MARKET_CLOSED


def test_unknown_code_is_ambiguous():
    assert from_retcode(99999) is ReasonCode.UNKNOWN
    assert ReasonCode.UNKNOWN in AMBIGUOUS
