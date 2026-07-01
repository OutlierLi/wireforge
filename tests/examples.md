# WireForge Command Examples (All Success Cases)

## /build — Build protocol frames

### DLT645 read data request
/build --proto dlt645 --func 0x11 --dir downlink --di 00010000
@expect success

### DLT645 read data response with variant fields
/build --proto dlt645 --func 0x11 --dir uplink --di 00010000 --freeze_year 26 --freeze_month 06 --freeze_day 21 --freeze_hour 20
@expect success

### DLT645 read address request
/build --proto dlt645 --func 0x13 --dir downlink
@expect success

### DLT645 read address response
/build --proto dlt645 --func 0x13 --dir uplink --address_data 000000000001
@expect success

### CSG query vendor
/build --proto csg --afn 0x03 --dir downlink --di E8000301
@expect success

### CSG uplink ACK
/build --proto csg --afn 0x00 --dir uplink --di E8010001 --wait_time 0
@expect success

### CSG with address area
/build --proto csg --afn 0x02 --dir downlink --di E8020201 --addr true --address_area.adst 012400038813 --payload FFFFFFFFFF
@expect success

### DLT645 resolve (show input schema)
/build --proto dlt645 --func 0x11 --dir uplink --di 00010000 --resolve
@expect success

### CSG resolve (show input schema)
/build --proto csg --afn 0x00 --dir uplink --di E8010001 --resolve
@expect success

## /decode — Decode hex frames

### DLT645 read address request
/decode --proto dlt645 --hex FEFEFEFE68AAAAAAAAAAAA681300DF16
@expect success

### DLT645 read data response
/decode --proto dlt645 --hex FEFEFEFE6801000000000068910833333433593954537016
@expect success

### CSG query vendor
/decode --proto csg --hex 680C00400301010300E83016
@expect success

### CSG uplink ACK
/decode --proto csg --hex 680E00800001010001E800006B16
@expect success

## /serial — Serial port management

### Connect mock port
/serial connect --port mock://loop --baudrate 9600
@expect success

### Send data
/serial send --to default --hex 680C00400301010300E83016
@expect success

### List ports
/serial ports
@expect success

### Set baudrate
/serial set --baudrate 115200
@expect success

### Close connection
/serial close
@expect success

## /time — Serial display timestamp

### Enable timestamp on TX/RX display
/time on
@expect success

### Disable timestamp
/time off
@expect success

### Show current status
/time
@expect success

## /auto_rule — Auto-reply rules

`mock://auto` 仅在规则命中时回复；无规则时 RX 为空。

**CLI 写法**（终端直接输入，用命令行，不用 JSON）：

```text
/auto_rule add --id test2 --match 68.*16 --then /print --text=success
/auto_rule add --id ack --match 010300E8 --then /send --hex "68 0E 00 80 00 01 01 00 01 E8 00 6B 16"
```

**TestPlan YAML** 仍用 dict 格式（`command` + `args`），见各 example md。

### Add rule (dict then — recommended)
/auto_rule add --id test_rule --match 010300E8 --then '[{"command":"/send","args":{"hex":"68 0E 00 80 00 01 01 00 01 E8 00 00 6B 16"}}]'
@expect success

### Add rule with composite match
/auto_rule add --id combo_rule --match '{"all":["010300E8","0040"]}' --then '[{"command":"/send","args":{"hex":"11 22"}}]'
@expect success

### List rules
/auto_rule list
@expect success

### Show rule
/auto_rule show --id test_rule
@expect success

### Test rule match
/auto_rule test --id test_rule --hex 680C00400301010300E83016
@expect success

### Disable rule
/auto_rule disable --id test_rule
@expect success

### Enable rule
/auto_rule enable --id test_rule
@expect success

### Load YAML rules
/auto_rule load --file database/rules/auto_reply_rules.yaml
@expect success

### History
/auto_rule history
@expect success

### Delete rule
/auto_rule delete --id test_rule
@expect success

## /help — Command help

### List all commands
/help
@expect success

### Help for /serial
/help /serial
@expect success

### Help for /serial send
/help /serial send
@expect success

### Help for /build
/help /build
@expect success

### Help for /auto_rule
/help /auto_rule
@expect success

## /upg — Firmware upgrade

### Build cache only
/upg --file tests/test_firmware.bin --segment-size 128 --build-only
@expect success
