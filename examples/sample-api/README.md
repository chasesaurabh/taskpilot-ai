# TaskPilot sample API

This deliberately small FastAPI service is the writable repository used by the no-key demo. Its baseline `/products` endpoint returns an unpaginated list; the documented TaskPilot task adds bounded pagination and focused tests.

```bash
python -m pytest -q
```
