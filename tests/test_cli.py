"""单元测试: CLI 命令"""
from typer.testing import CliRunner
from protocol_tool.cli.main import app


def test_inspect_protocol():
    runner = CliRunner()
    result = runner.invoke(app, ["inspect", "protocol", "--protocol", "dlt645_2007"])
    assert result.exit_code == 0
    assert "dlt645_2007" in result.stdout
    assert "DL/T 645-2007" in result.stdout


def test_inspect_routes():
    runner = CliRunner()
    result = runner.invoke(app, ["inspect", "routes", "--protocol", "dlt645_2007"])
    assert result.exit_code == 0
    assert "main" in result.stdout
    assert "control.func" in result.stdout


def test_decode():
    runner = CliRunner()
    result = runner.invoke(app, [
        "decode", "--protocol", "dlt645_2007",
        "--hex", "FE FE FE FE 68 AA AA AA AA AA AA 68 13 00 DF 16",
    ])
    assert result.exit_code == 0
    assert "dlt645_2007" in result.stdout


def test_decode_trace():
    runner = CliRunner()
    result = runner.invoke(app, [
        "decode", "--protocol", "dlt645_2007", "--trace",
        "--hex", "FE FE FE FE 68 AA AA AA AA AA AA 68 13 00 DF 16",
    ])
    assert result.exit_code == 0


def test_inspect_csg():
    runner = CliRunner()
    result = runner.invoke(app, ["inspect", "protocol", "--protocol", "csg_2016"])
    assert result.exit_code == 0
    assert "csg_2016" in result.stdout


def test_compile():
    runner = CliRunner()
    result = runner.invoke(app, ["compile", "--protocol", "dlt645_2007"])
    assert result.exit_code == 0
