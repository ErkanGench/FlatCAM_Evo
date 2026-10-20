"""The Sender detects the E-Cut adapter by its own banner; no board is needed."""
from appPlugins.ToolGrblSender.SenderGrbl import ECUT_BANNER, is_controller_banner


def test_both_controller_banners_are_detected():
    assert is_controller_banner("Grbl 1.1h ['$' for help]")
    assert is_controller_banner(ECUT_BANNER)
    assert is_controller_banner('  ' + ECUT_BANNER.upper() + '\r\n')


def test_other_lines_are_not_banners():
    for line in ('ok', 'error:20', 'ALARM:1', '[MSG:E-Cut: refused]', '', None, 'E-Cut host adapter'):
        assert not is_controller_banner(line)


def test_the_adapter_banner_has_no_third_party_firmware_name():
    assert 'grbl' not in ECUT_BANNER.lower()
