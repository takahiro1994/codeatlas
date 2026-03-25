from widgets.dashboard import render_dashboard
from widgets.metrics import collect_metrics


def main() -> None:
    # TODO: split orchestration from the HTTP surface
    metrics = collect_metrics()
    print(render_dashboard(metrics))


if __name__ == "__main__":
    main()

