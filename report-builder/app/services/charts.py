"""Step 5: draw charts as PNG files from the analysis numbers."""
import threading
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no window needed, safe on servers
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

_lock = threading.Lock()  # matplotlib is not thread-safe

INK, ACCENT, GRID = "#16202A", "#234E9D", "#E3E7EC"
CHART_NAMES = ("revenue_trend", "top_products", "by_region")


def _fmt(x, _pos=None):
    if abs(x) >= 1_000_000:
        return f"{x / 1_000_000:.1f}M"
    if abs(x) >= 1_000:
        return f"{x / 1_000:.0f}K"
    return f"{x:.0f}"


def _style(ax, title, currency_code):
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", color=INK, pad=12)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, pos: f"{currency_code} {_fmt(x, pos)}"))
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors=INK, labelsize=9, length=0)


def _short(text, n=18):
    return text if len(text) <= n else text[: n - 1] + "…"


def make_charts(analysis: dict, out_dir: Path) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    with _lock:
        # 1. Revenue over time
        pts = analysis["trend"]["points"]
        fig, ax = plt.subplots(figsize=(8, 3.4), dpi=130)
        ax.plot(range(len(pts)), [p["revenue"] for p in pts], color=ACCENT, linewidth=2)
        ax.fill_between(range(len(pts)), [p["revenue"] for p in pts], color=ACCENT, alpha=0.08)
        step = max(1, len(pts) // 8)
        ax.set_xticks(range(0, len(pts), step))
        ax.set_xticklabels([pts[i]["date"][5:] for i in range(0, len(pts), step)])
        currency = analysis["currency"]
        _style(ax, f"Revenue per {analysis['trend']['granularity']} ({currency})", currency)
        fig.tight_layout()
        fig.savefig(out_dir / "revenue_trend.png")
        plt.close(fig)
        made.append("revenue_trend")

        # 2. Top products (horizontal bars)
        tp = analysis["top_products"][::-1]
        fig, ax = plt.subplots(figsize=(8, 3.4), dpi=130)
        ax.barh([_short(p["name"], 28) for p in tp], [p["revenue"] for p in tp], color=ACCENT)
        _style(ax, f"Top products by revenue ({currency})", currency)
        ax.set_yticks(range(len(tp)))
        ax.set_yticklabels([_short(p["name"], 28) for p in tp])
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, pos: f"{currency} {_fmt(x, pos)}"))
        ax.grid(axis="y", visible=False)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
        fig.tight_layout()
        fig.savefig(out_dir / "top_products.png")
        plt.close(fig)
        made.append("top_products")

        # 3. Revenue by region
        if analysis["by_region"]:
            reg = analysis["by_region"]
            fig, ax = plt.subplots(figsize=(8, 3.4), dpi=130)
            ax.bar([_short(r["name"], 14) for r in reg], [r["revenue"] for r in reg], color=ACCENT)
            _style(ax, f"Revenue by region ({currency})", currency)
            fig.tight_layout()
            fig.savefig(out_dir / "by_region.png")
            plt.close(fig)
            made.append("by_region")
    return made
