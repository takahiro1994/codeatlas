from .metrics import collect_metrics


def render_dashboard(metrics: dict | None = None) -> str:
    # FIXME: replace with a real template system
    payload = metrics or collect_metrics()
    return f"dashboard:{sorted(payload)}"

