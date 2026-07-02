"""命令树顺序补全测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from console.api import complete_cmd
from console.completion import analyze_completion_line, complete_text


def _values(text: str) -> list[str]:
    r = complete_text(text)
    return [c["value"] for c in r["data"]["completions"]]


def _kinds(text: str) -> list[str]:
    r = complete_text(text)
    return [c["kind"] for c in r["data"]["completions"]]


class TestCommandCompletion:
    def test_prefix_filters_commands(self):
        vals = _values("/se")
        assert "/serial" in vals
        assert all(v.startswith("/se") or v == "/serial" for v in vals if v.startswith("/s"))

    def test_exit_in_command_completions(self):
        vals = _values("/e")
        assert "/exit" in vals

    def test_exit_prefix(self):
        vals = _values("/ex")
        assert "/exit" in vals
        assert "/exit" in _values("")

    def test_empty_shows_all_commands(self):
        vals = _values("")
        assert "/decode" in vals
        assert "/serial" in vals


class TestSubCommandCompletion:
    def test_after_command_space_shows_subs(self):
        vals = _values("/serial ")
        assert "connect" in vals
        assert "send" in vals
        assert _kinds("/serial ") == ["sub_command"] * len(vals)

    def test_partial_sub_prefix(self):
        vals = _values("/serial c")
        assert "connect" in vals
        assert "close" in vals
        assert "disconnect" not in vals or "disconnect" not in [v for v in vals if v.startswith("c") is False]

    def test_locked_sub_hides_others(self):
        vals = _values("/serial connect")
        assert "disconnect" not in vals
        assert "send" not in vals
        assert "--port" in vals

    def test_locked_sub_with_space(self):
        vals = _values("/serial connect ")
        assert "disconnect" not in vals
        assert "--port" in vals
        assert "--hex" not in vals

    def test_delete_sub_prefix_reopens_subs(self):
        vals = _values("/serial conn")
        assert "connect" in vals
        assert "--port" not in vals


class TestArgumentCompletion:
    def test_required_before_recommended(self):
        vals = _values("/serial connect ")
        assert vals[0] == "--port"
        assert "--to" not in vals

    def test_after_required_shows_recommended(self):
        vals = _values("/serial connect --port=mock://loop ")
        assert "--name" in vals
        assert "--port" not in vals

    def test_after_recommended_shows_optional(self):
        vals = _values("/serial connect --port=mock://loop --name=default ")
        assert "--baudrate" in vals
        assert "--port" not in vals
        assert "--to" not in vals

    def test_flag_prefix_cross_tier(self):
        vals = _values("/serial connect --ba")
        assert "--baudrate" in vals
        assert "--port" not in vals

    def test_used_non_repeatable_excluded(self):
        vals = _values("/serial connect --port=mock://loop --ba")
        assert "--baudrate" in vals
        assert "--port" not in vals


class TestRepeatableParams:
    def test_filter_always_available(self):
        vals = _values("/find search --filter=档案 ")
        assert "--filter" in vals

    def test_var_repeatable(self):
        vals = _values("/run execute --file=plan.yaml --var=port=COM1 ")
        assert "--var" in vals


class TestDefaultSub:
    def test_decode_skips_sub(self):
        vals = _values("/decode --proto=csg ")
        assert "--hex" in vals
        assert "decode" not in vals

    def test_build_resolve_flag(self):
        vals = _values("/build --resolve ")
        assert "--proto" in vals


class TestArgumentValueCompletion:
    def test_port_space_shows_default_and_examples(self):
        r = complete_text("/serial connect --port ")
        kinds = [c["kind"] for c in r["data"]["completions"]]
        vals = [c["value"] for c in r["data"]["completions"]]
        assert kinds and all(k == "argument_value" for k in kinds)
        assert vals[0] == "mock://loop"
        assert r["data"]["completions"][0].get("default") is True
        assert "virtual://demo" in vals

    def test_port_prefix_filters(self):
        vals = _values("/serial connect --port mo")
        assert vals == ["mock://loop"]

    def test_port_equals_form(self):
        vals = _values("/serial connect --port=mo")
        assert "mock://loop" in vals

    def test_baudrate_default(self):
        vals = _values("/serial connect --port=mock://loop --name=default --baudrate ")
        assert "9600" in vals
        assert vals[0] == "9600"

    def test_stage_argument_value(self):
        assert analyze_completion_line("/serial connect --port ").stage == "argument_value"
        assert analyze_completion_line("/serial connect --port=mo").stage == "argument_value"
        assert analyze_completion_line("/serial connect --port mo").stage == "argument_value"


class TestNestedThenCompletion:
    def test_then_space_suggests_nested_commands(self):
        vals = _values("/auto_rule add --id x --match 68.*16 --then ")
        assert "/print" in vals
        assert "/serial" in vals

    def test_then_partial_command(self):
        vals = _values("/auto_rule add --id x --match 68.*16 --then /pr")
        assert vals == ["/print"]

    def test_then_print_params(self):
        vals = _values("/auto_rule add --id x --match 68.*16 --then /print ")
        assert "--text" in vals

    def test_then_print_flag_prefix(self):
        vals = _values("/auto_rule add --id x --match 68.*16 --then /print --te")
        assert "--text" in vals

    def test_stage_nested_then(self):
        st = analyze_completion_line("/auto_rule add --id x --match y --then /print ")
        assert st.stage == "nested_script"
        assert st.nested is not None
        assert st.nested.command == "print"


class TestHelpNestedCompletion:
    def test_help_target_slash_suggests_all_commands(self):
        vals = _values("/help --target /")
        assert "/serial" in vals
        assert "/build" in vals
        assert "/decode" in vals
        assert len(vals) > 5

    def test_help_target_space_suggests_commands(self):
        vals = _values("/help --target ")
        assert "/serial" in vals
        assert "/build" in vals

    def test_help_target_partial_command(self):
        vals = _values("/help --target /de")
        assert "/decode" in vals
        assert "/delay" in vals

    def test_help_positional_serial_subs(self):
        vals = _values("/help /serial ")
        assert "connect" in vals
        assert "send" in vals

    def test_help_target_serial_connect_params(self):
        vals = _values("/help --target /serial connect ")
        assert "--port" in vals

    def test_help_space_suggests_commands(self):
        vals = _values("/help ")
        assert "/auto_rule" in vals

    def test_stage_nested_target(self):
        st = analyze_completion_line("/help --target /serial connect ")
        assert st.stage == "nested_target"
        assert st.nested is not None
        assert st.nested.command == "serial"


class TestBuildDynamicCompletion:
    def setup_method(self):
        from console.build_completion import (
            _load_ir_routers, _load_protocol_map, _resolve_schema_cached,
        )
        _load_protocol_map.cache_clear()
        _resolve_schema_cached.cache_clear()
        _load_ir_routers.cache_clear()

    def test_proto_csg_suggests_dir_first(self):
        vals = _values("/build --proto=csg ")
        assert "--dir" in vals
        assert "--afn" not in vals
        assert "--func" not in vals

    def test_proto_dlt645_suggests_dir_first(self):
        vals = _values("/build --proto=dlt645 ")
        assert "--dir" in vals
        assert "--func" not in vals
        assert "--afn" not in vals

    def test_dir_then_afn_not_addr(self):
        vals = _values("/build --proto=csg --dir=downlink ")
        assert "--afn" in vals
        assert "--addr" not in vals

    def test_afn_value_filtered_by_dir(self):
        vals = _values("/build --proto=csg --dir=downlink --afn=0x")
        assert any("0x03" in v or "0x00" in v for v in vals)

    def test_di_value_filtered_by_dir_and_afn(self):
        vals = _values("/build --proto=csg --dir=downlink --afn=0x03 --di=E8")
        assert any("E803" in v.upper() for v in vals)

    def test_uplink_only_di_not_offered_on_downlink(self):
        vals = _values("/build --proto=csg --dir=downlink --afn=0x02 --di=")
        assert "E8000203" in vals
        assert "E8000103" not in vals

    def test_uplink_only_di_offered_on_uplink(self):
        vals = _values("/build --proto=csg --dir=uplink --afn=0x02 --di=")
        assert "E8000103" in vals

    def test_dir_values_only_from_filtered_routes(self):
        vals = _values("/build --proto=csg --dir=uplink --afn=0x02 --di=E8000103 --dir=")
        assert vals == ["uplink"]

    def test_resolved_schema_fields_without_explicit_addr(self):
        vals = _values("/build --proto=csg --dir=downlink --afn=0x03 --di=E8030306 ")
        assert "--start_slave_index" in vals or "--slave_count" in vals
        assert "--afn" not in vals
        assert "--addr" not in vals

    def test_addr_not_prompted_when_route_unique(self):
        vals = _values("/build --proto=csg --dir=downlink --afn=0x00 --di=E8010001 ")
        assert "--addr" not in vals
        assert "--wait_time" in vals

    def test_dir_default_downlink(self):
        vals = _values("/build --proto=csg --dir=")
        assert "downlink" in vals

    def test_ack_route_suggests_wait_time_not_set(self):
        vals = _values("/build --proto=csg --dir=downlink --afn=0x00 --di=E8010001 ")
        assert "--wait_time" in vals
        assert "--set" not in vals

    def test_wait_time_default_value(self):
        vals = _values("/build --proto=csg --dir=downlink --afn=0x00 --di=E8010001 --wait_time=")
        assert "0" in vals


class TestRouteDynamicCompletion:
    def setup_method(self):
        from console.build_completion import (
            _load_ir_routers, _load_protocol_map, _resolve_schema_cached,
        )
        _load_protocol_map.cache_clear()
        _resolve_schema_cached.cache_clear()
        _load_ir_routers.cache_clear()

    def test_route_csg_di_all_not_static_examples(self):
        vals = _values("/route --proto=csg --di=")
        assert len(vals) > 10
        assert "00010000" not in vals
        assert any(v.startswith("E8") for v in vals)

    def test_route_csg_di_prefix_filter(self):
        vals = _values("/route --proto=csg --dir=downlink --afn=0x03 --di=E803")
        assert all(v.upper().startswith("E803") for v in vals)
        assert "00010000" not in vals

    def test_route_dlt645_di_no_csg(self):
        vals = _values("/route --proto=dlt645 --di=")
        assert len(vals) > 5
        assert not any(v.startswith("E8") for v in vals)
        assert any(v.startswith("0001") for v in vals)

    def test_build_csg_di_full_list(self):
        vals = _values("/build --proto=csg --di=")
        assert len(vals) > 10
        assert "00010000" not in vals

    def test_afn_shows_category_not_di_function(self):
        r = complete_text("/route --proto=csg --dir=downlink --afn=")
        labels = [c.get("label", "") for c in r["data"]["completions"]]
        afn01 = next((l for l in labels if l.startswith("0x01")), "")
        assert "复位硬件" not in afn01
        assert "初始化" in afn01

    def test_di_shows_specific_function(self):
        r = complete_text("/route --proto=csg --dir=downlink --afn=0x01 --di=")
        labels = [c.get("label", "") for c in r["data"]["completions"]]
        assert any("复位硬件" in l for l in labels)
        assert any("E8020101" in l for l in labels)

    def test_di_space_form_completes(self):
        vals = _values("/build --proto=csg --dir=downlink --afn=0x01 --di ")
        assert len(vals) >= 3
        assert "E8020101" in vals

    def test_di_space_partial_prefix(self):
        vals = _values("/build --proto=csg --dir=downlink --afn=0x01 --di E802")
        assert all(v.startswith("E802") for v in vals)


class TestLegacyApi:
    def test_complete_cmd_serial_subs(self):
        r = complete_cmd(command="serial", prefix="")
        subs = [c["value"] for c in r["data"]["completions"] if c["kind"] == "sub_command"]
        assert "connect" in subs

    def test_complete_cmd_connect_params(self):
        r = complete_cmd(command="serial", sub="connect", prefix="")
        keys = [c["value"] for c in r["data"]["completions"]]
        assert keys[0] == "--port"
        assert "--hex" not in keys


class TestAutoRuleMatchCompletion:
    def setup_method(self):
        from console.build_completion import (
            _load_ir_routers, _load_protocol_map, _resolve_schema_cached,
        )
        _load_protocol_map.cache_clear()
        _resolve_schema_cached.cache_clear()
        _load_ir_routers.cache_clear()

    def test_match_space_suggests_proto_and_regex(self):
        vals = _values("/auto_rule add --id test --match ")
        assert "--proto" in vals
        assert "--field" in vals
        assert "68.*16" in vals

    def test_match_proto_csg_suggests_dir(self):
        vals = _values("/auto_rule add --id test --match --proto csg ")
        assert "--dir" in vals
        assert "--afn" in vals
        assert "--di" in vals
        assert "--addr" not in vals
        assert "--then" in vals

    def test_match_dir_suggests_afn_di_not_addr(self):
        vals = _values("/auto_rule add --id test --match --proto csg --dir downlink ")
        assert "--afn" in vals
        assert "--di" in vals
        assert "--addr" not in vals
        assert "--then" in vals

    def test_match_proto_afn_di_labeled(self):
        r = complete_text(
            "/auto_rule add --id test --match --proto csg --dir=downlink --afn=0x00 --di="
        )
        labels = [c.get("label", "") for c in r["data"]["completions"]]
        assert any("E8010001" in lb for lb in labels)
        assert any("—" in lb for lb in labels)

    def test_match_route_complete_suggests_then_not_build_schema(self):
        vals = _values(
            "/auto_rule add --id test --match --proto csg --dir=downlink "
            "--afn=0x00 --di=E8010001 "
        )
        assert "--then" in vals
        assert "--wait_time" not in vals
        assert "--addr" not in vals

    def test_match_complete_suggests_then(self):
        vals = _values(
            "/auto_rule add --id test --match --proto csg --dir=downlink "
            "--afn=0x00 --di=E8010001 "
        )
        assert "--then" in vals

    def test_match_regex_not_nested_route(self):
        st = analyze_completion_line("/auto_rule add --id test --match 68.*16 ")
        assert st.stage != "nested_match"
        assert "--then" in _values("/auto_rule add --id test --match 68.*16 ")

    def test_stage_nested_match(self):
        st = analyze_completion_line("/auto_rule add --id test --match --proto csg ")
        assert st.stage == "nested_match"
        assert st.nested is not None
        assert st.nested.command == "auto_rule_match"

    def test_then_serial_send_build_suggests_proto(self):
        vals = _values(
            "/auto_rule add --id test --match --proto csg --afn 0x01 "
            "--then /serial send --build "
        )
        assert "--proto" in vals
        assert "--build" not in vals

    def test_then_serial_send_build_proto_csg_suggests_dir(self):
        vals = _values(
            "/auto_rule add --id test --match --proto csg --afn 0x01 "
            "--then /serial send --build --proto csg "
        )
        assert "--dir" in vals
        assert "--proto" not in vals

    def test_then_tail_not_truncated_at_proto(self):
        st = analyze_completion_line(
            "/auto_rule add --id test --then /serial send --build --proto csg "
        )
        assert st.nested is not None
        assert st.nested.stage == "nested_serial_send_build"
        assert st.nested.nested is not None
        assert st.nested.nested.used_args.get("proto") == "csg"


class TestSerialSendBuildCompletion:
    def setup_method(self):
        from console.build_completion import (
            _load_ir_routers, _load_protocol_map, _resolve_schema_cached,
        )
        _load_protocol_map.cache_clear()
        _resolve_schema_cached.cache_clear()
        _load_ir_routers.cache_clear()

    def test_send_without_build_no_proto(self):
        vals = _values("/serial send ")
        assert "--build" in vals
        assert "--hex" in vals
        assert "--proto" not in vals

    def test_send_build_space_suggests_proto(self):
        vals = _values("/serial send --build ")
        assert "--proto" in vals
        assert "--hex" not in vals

    def test_send_build_proto_csg_suggests_dir(self):
        vals = _values("/serial send --build --proto csg ")
        assert "--dir" in vals
        assert "--afn" not in vals

    def test_send_build_di_labeled(self):
        r = complete_text(
            "/serial send --build --proto csg --dir=downlink --afn=0x00 --di="
        )
        labels = [c.get("label", "") for c in r["data"]["completions"]]
        assert any("E8010001" in lb for lb in labels)

    def test_send_build_complete_suggests_to(self):
        vals = _values(
            "/serial send --build --proto csg --dir=downlink "
            "--afn=0x00 --di=E8010001 --wait_time=0 "
        )
        assert "--to" in vals

    def test_stage_nested_serial_send_build(self):
        st = analyze_completion_line("/serial send --build --proto csg ")
        assert st.stage == "nested_serial_send_build"
        assert st.nested is not None
        assert st.nested.command == "serial_send_build"


class TestAnalyzeState:
    def test_stage_transitions(self):
        assert analyze_completion_line("").stage == "command"
        assert analyze_completion_line("/serial ").stage == "sub_command"
        assert analyze_completion_line("/serial connect").stage == "argument"
        assert analyze_completion_line("/serial connect --po").stage == "argument"


class TestRobustTokenize:
    def test_unclosed_quote_with_trailing_space(self):
        r = complete_text('/decode --hex="68 0C ')
        assert r["status"] == "success"
        assert "completions" in r["data"]

    def test_unclosed_quote_no_crash(self):
        r = complete_text('/help "/serial open')
        assert r["status"] == "success"

    def test_tokenize_dangling_quote(self):
        from console.completion import tokenize_for_completion

        tokens, partial, _ends = tokenize_for_completion('/decode --hex="68 ')
        assert tokens or partial
