# DLT645 extension example - protocol_extend_run

`protocol_extend_run` extends DLT645 or CSG variants from Agent-authored payload schema fields.

## DLT645 read data response

```json
{
  "raw_input": "extend DLT645 read data response DI 00099999",
  "user_input": {
    "protocol": "dlt645",
    "func": "0x11",
    "di": "00099999",
    "description": "custom energy",
    "fields": [
      {"name": "rate_index", "type": "uint8", "desc": "rate index"},
      {"name": "energy_raw", "type": "uint32_le", "desc": "raw energy"}
    ]
  }
}
```

Generated path: `protocol_tool/protocols/dlt645_2007/variants/extensions/11_00099999.yaml`.

## Other FUNC values

| FUNC | router | selector | default dir | notes |
|------|--------|----------|-------------|-------|
| 0x11 | `read_data_response_di` | `di` | uplink | read data response payload |
| 0x14 | `write_data_request_di` | `di` | downlink | write data request payload |
| 0x16 | `freeze_request_di` | `freeze_type` | downlink | freeze command payload |
| 0x1B | `clear_event_request_di` | `event_type` | downlink | clear event payload |
| other | template only | varies | registry dependent | add router in protocol.yaml first |

Run `python3 scripts/bootstrap_protocol_cache.py` after extension changes.
