import matplotlib

matplotlib.use("Agg")
from datetime import datetime

import matplotlib.pyplot as plt


def build_trend_chart(routes_history: dict[str, dict], out_path: str) -> bool:
    """routes_history: {route_name: {"history": [{"price": float, "checked_at": iso str}, ...], "currency": str}}

    Writes a PNG with one subplot per route showing price over time.
    Returns False (and writes nothing) if no route has at least 2 points to plot.
    """
    plottable = {
        name: data for name, data in routes_history.items() if len(data["history"]) >= 2
    }
    if not plottable:
        return False

    n = len(plottable)
    cols = 2
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(11, 4 * rows), squeeze=False)

    for i, (name, data) in enumerate(plottable.items()):
        ax = axes[i // cols][i % cols]
        points = data["history"]
        times = [datetime.fromisoformat(p["checked_at"]) for p in points]
        prices = [p["price"] for p in points]
        ax.plot(times, prices, marker="o", linewidth=1.5)
        ax.set_title(name, fontsize=10)
        ax.set_ylabel(data.get("currency", "USD"))
        ax.tick_params(axis="x", rotation=30, labelsize=8)
        ax.grid(True, alpha=0.3)

    for j in range(n, rows * cols):
        axes[j // cols][j % cols].axis("off")

    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return True
