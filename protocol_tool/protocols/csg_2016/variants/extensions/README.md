# CSG 2016 extension variants

This directory stores Agent-authored extension variant YAML written by `protocol_extend_run` from payload schema fields.

- Built-in payloads are checked in under `../payloads/`.
- The compiler loads `variants/**/*.yaml` automatically.
- File naming convention: `{AFN}_{DI}.yaml`.

After adding files, run:

```bash
python3 scripts/bootstrap_protocol_cache.py
```
