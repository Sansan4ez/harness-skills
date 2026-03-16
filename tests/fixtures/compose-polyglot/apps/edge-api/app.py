def fixture_api_entrypoint() -> dict[str, str]:
    metrics = [
        "http_server_duration_milliseconds",
    ]
    logs = [
        "HTTP request completed",
    ]
    traces = [
        "api.request",
    ]
    return {
        "metrics": ",".join(metrics),
        "logs": ",".join(logs),
        "traces": ",".join(traces),
    }
