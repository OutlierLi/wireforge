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
/build --proto csg --afn 0x00 --dir uplink --di E8010001 --result 0
@expect success

### CSG with address area
/build --proto csg --afn 0x02 --dir downlink --di E8020201 --addr true --task_info 010203
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

### DLT645 read data request
/decode --proto dlt645 --hex FEFEFEFE680100000000000068110433333433B316
@expect success

### CSG query vendor
/decode --proto csg --hex 680C00400301010300E83016
@expect success

### CSG uplink ACK
/decode --proto csg --hex 680D00800001010001E8006B16
@expect success

## /serial — Serial port management

### Connect mock port
/serial connect --port mock://loop --baudrate 9600
@expect success

### Send data
/serial send --hex 680C00400301010300E83016
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

## /auto_rule — Auto-reply rules

### Add rule
/auto_rule add --id test_rule --match 68..16 --then example_action
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
/auto_rule load --file tests/rules.yaml
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
