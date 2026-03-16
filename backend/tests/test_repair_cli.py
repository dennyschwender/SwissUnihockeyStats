"""Tests for manage.py repair command."""

from click.testing import CliRunner


def test_repair_command_exits_zero():
    from manage import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["repair"])
    assert result.exit_code == 0, result.output


def test_repair_command_prints_summary():
    from manage import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["repair"])
    assert "Repair complete" in result.output or "Repair done" in result.output
    assert (
        "total_fixed" in result.output
        or "rows fixed" in result.output
        or "Total rows fixed" in result.output
    )
